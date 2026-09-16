"""Reconcile families and inspection against the expected closing set.

PRD §4 "Expected-set reconciliation", "Execution evidence", "Execution
spotlight" and "Version selection", applied through the derivation table and
the seven rules in `../../references/status-taxonomy.md` and the ledger
contract in `../../references/sigpack-ledger-consumption.md`.

`reconcile()` returns five artifacts — closing-index, selection-plan,
execution-overview, closing-receipt (each the shape of its schema under
`../../references/`) and `exceptions.md` — and raises `ValueError` when the
inputs describe different folders or the receipt would not balance. It reads
sources only to hash them for the ledger gate; it never writes.

Inspection proposes; this module and the lawyer decide. A record that does
not validate, names the wrong members, picks a file the census marks
unreadable, or cites the ledger while disagreeing with it is rejected with
its reason, counted in `receipt.inspection.rejected`, and named in
`exceptions.md`. Nothing is absorbed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from hashlib import sha256
from pathlib import Path
from typing import Any

from .families import (
    check_families,
    check_manifest,
    checklist_digest,
    normalised_title,
    title_overlap,
)
from .models import (
    DATE,
    DOC_ID,
    INSPECTION_STATUSES,
    ITEM_ID,
    NOT_SIGNED_STATUSES,
    RECEIPT_STATUSES,
    SCHEMA_VERSION,
    SELECTABLE_STATUSES,
    Evidence,
    ExecutionRecord,
    FamilyInspection,
    IndexItem,
    Inspection,
    Receipt,
    derive_status,
)

# status-taxonomy.md "Receipt outcomes": sources.unreadable counts encrypted,
# corrupt and suspect, and an id the census cannot read is never selected.
UNREADABLE = frozenset({"encrypted", "corrupt", "suspect"})
# Worst first, the order the census ranks a document's rows by.
READABILITY_RANK = ("corrupt", "encrypted", "suspect", "scanned", "native")
QUALIFICATION_MAX = 500
NOT_INSPECTED_COMPONENT = "completeness not inspected (no valid inspection record)"
_HASH_CHUNK = 1024 * 1024


# ------------------------------------------------------------------ helpers


def _clip(text: str, limit: int = QUALIFICATION_MAX) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _posix(path: str) -> str:
    path = path.replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]
    return path.strip("/")


def _basename(path: str) -> str:
    return _posix(path).rsplit("/", 1)[-1]


def _depth(path: str) -> int:
    return _posix(path).count("/")


def _hash_id(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(_HASH_CHUNK), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()[:12]


# ------------------------------------------------------------------- ledger


@dataclass
class _Block:
    page_id: str
    number: int
    party: str
    status: str
    date_field: bool
    dated: str | None
    placed_doc: str | None
    placed_page: int | None
    placed_name: str | None
    held: bool = False  # signed, chosen return, no placed_in: the sheet is HELD


@dataclass
class _Page:
    page_id: str
    agreement: str
    file: str
    exec_doc: str | None
    blocks: list[_Block]
    reserved: bool = False

    def live_blocks(self) -> list[_Block]:
        if self.reserved:
            return [b for b in self.blocks if b.party]
        return list(self.blocks)


@dataclass
class _Ledger:
    supplied: bool
    current: bool
    note: str = ""
    matter: str | None = None
    closing_date: str | None = None
    receipt: dict[str, Any] | None = None
    pages: list[_Page] = field(default_factory=list)
    agreements: list[str] = field(default_factory=list)
    unplaced_notes: list[str] = field(default_factory=list)

    def pages_for(self, members: set[str]) -> list[_Page]:
        return [
            p
            for p in self.pages
            if p.exec_doc in members or any(b.placed_doc in members for b in p.blocks)
        ]

    def pages_for_agreement(self, agreement: str) -> list[_Page]:
        return [p for p in self.pages if p.agreement == agreement]


def _read_ledger(
    sigpack: Any, manifest: dict[str, Any], sigpack_dir: Path | None
) -> _Ledger:
    """The gate in sigpack-ledger-consumption.md, then the fields read."""

    if not isinstance(sigpack, dict):
        raise ValueError("sigpack ledger must be a JSON object")
    raw_pages = sigpack.get("signature_pages")
    if not isinstance(raw_pages, list):
        return _Ledger(True, False, "ledger has no signature_pages list")
    receipt = sigpack.get("receipt")
    as_of = receipt.get("as_of") if isinstance(receipt, dict) else None
    if not isinstance(as_of, str) or not as_of.strip():
        return _Ledger(True, False, "ledger receipt has no as_of")

    ids = {d["id"] for d in manifest["documents"]}
    by_path = {_posix(d["path"]): d["id"] for d in manifest["documents"]}
    by_basename: dict[str, dict[str, str]] = {}  # basename -> {id: shallowest path}
    for path, doc_id in sorted(by_path.items(), key=lambda kv: (_depth(kv[0]), kv[0])):
        by_basename.setdefault(_basename(path), {}).setdefault(doc_id, path)

    def resolve_execution(rel: str) -> str | None:
        """`<ledger folder>/<execution_dir>/<file>`, hashed against the census."""

        rel = _posix(rel)
        if not rel:
            return None
        if sigpack_dir is not None:
            candidate = sigpack_dir / rel
            if not candidate.is_file():
                return None
            found = _hash_id(candidate)
            return found if found in ids else None
        # No ledger folder given: the ledger is taken to sit at the census root,
        # so a path the census walked is a file whose bytes the census hashed.
        for path, doc_id in by_path.items():
            if path == rel or path.endswith("/" + rel):
                return doc_id
        return None

    def resolve_placed(name: str, where: str) -> str | None:
        """A `placed_in` name is a bare output name: the census document whose
        basename equals it, anywhere under the closing folder. Several distinct
        documents → the one nearest the ledger's folder (the shallowest path),
        noted under "Ledger notes". None → no document."""

        matches = by_basename.get(_basename(name), {})
        if not matches:
            unplaced.append(
                f"{where}: placed_in {name!r} is not a file in the folder; omitted from signature_pages"
            )
            return None
        doc_id, path = next(iter(matches.items()))
        if len(matches) > 1:
            others = ", ".join(sorted(p for i, p in matches.items() if i != doc_id))
            unplaced.append(
                f"{where}: placed_in {name!r} matches {len(matches)} files; took {path} "
                f"(closest to the ledger folder) over {others}"
            )
        return doc_id

    execution_dir = sigpack.get("execution_dir")
    execution_dir = _posix(execution_dir) if isinstance(execution_dir, str) else ""
    pages: list[_Page] = []
    agreements: list[str] = []
    unplaced: list[str] = []
    for i, raw in enumerate(raw_pages):
        if not isinstance(raw, dict):
            return _Ledger(True, False, f"signature_pages[{i}] is not an object")
        page_id = str(raw.get("id") or f"page-{i + 1}")
        agreement = raw.get("agreement")
        file = raw.get("file")
        if not isinstance(agreement, str) or not isinstance(file, str):
            return _Ledger(True, False, f"{page_id}: agreement or file missing")
        raw_blocks = raw.get("blocks") or []
        blocks: list[_Block] = []
        for j, rb in enumerate(raw_blocks):
            if not isinstance(rb, dict):
                continue
            party = rb.get("party")
            party = party.strip() if isinstance(party, str) else ""
            number = rb.get("block")
            number = number if isinstance(number, int) else j + 1
            status = rb.get("status")
            if not isinstance(status, str) or not status.strip():
                # A block whose status the ledger does not settle cannot be
                # read as anything; the whole ledger is not current.
                return _Ledger(True, False, f"{page_id} block {number}: no status")
            # Only the chosen return is read; every other returned[] entry is
            # sigpack's working trail (sigpack-ledger-consumption.md "Fields
            # not read"), placed_in or not.
            chosen = next(
                (
                    r
                    for r in rb.get("returned") or []
                    if isinstance(r, dict) and r.get("chosen") is True
                ),
                None,
            )
            dated = None
            placed_doc = placed_name = None
            placed_page = None
            held = False
            if chosen is not None:
                for key in ("dated", "dated_applied"):
                    value = chosen.get(key)
                    if isinstance(value, str) and value.strip():
                        dated = value.strip()
                        break
                placed = chosen.get("placed_in")
                if isinstance(placed, str) and placed.strip():
                    name, _, page_no = placed.partition("#")
                    placed_name = name
                    # "#0" or a non-number is not a page; the schema wants 1 or more.
                    placed_page = (
                        int(page_no)
                        if page_no.isdigit() and int(page_no) >= 1
                        else None
                    )
                    placed_doc = resolve_placed(
                        name, f"{page_id} block {rb.get('block', j + 1)}"
                    )
                else:
                    # A chosen return that was never placed: sigpack holds the
                    # signed sheet; the executed file lacks it.
                    held = status.strip() == "signed"
            blocks.append(
                _Block(
                    page_id=page_id,
                    number=number,
                    party=party,
                    status=status.strip(),
                    date_field=bool(rb.get("date_field", True)),
                    dated=dated,
                    placed_doc=placed_doc,
                    placed_page=placed_page,
                    placed_name=placed_name,
                    held=held,
                )
            )
        reserved = bool(raw.get("reserved"))
        live = not reserved or any(b.party for b in blocks)
        if not live:
            continue  # a reserved page with no party is ignored, as the ledger does
        exec_doc = resolve_execution(
            f"{execution_dir}/{file}" if execution_dir else file
        )
        if exec_doc is None and not any(b.placed_doc for b in blocks):
            return _Ledger(
                True,
                False,
                f"{page_id}: neither the execution version {file!r} nor an executed "
                "output matches a file in the folder",
            )
        pages.append(_Page(page_id, agreement, file, exec_doc, blocks, reserved))
        if agreement not in agreements:
            agreements.append(agreement)
    if not pages:
        return _Ledger(True, False, "ledger has no live signature pages")

    matter = sigpack.get("matter")
    closing_date = sigpack.get("closing_date")
    return _Ledger(
        supplied=True,
        current=True,
        matter=matter if isinstance(matter, str) else None,
        closing_date=closing_date if isinstance(closing_date, str) else None,
        receipt=dict(receipt) if isinstance(receipt, dict) else None,
        pages=pages,
        agreements=agreements,
        unplaced_notes=unplaced,
    )


@dataclass
class _LedgerFinding:
    apparent_status: str
    dated: str
    document_date: str | None
    page_ids: list[str]
    blocks: list[dict[str, Any]]
    signature_pages: list[dict[str, Any]]
    exceptions: list[str]
    evidence: list[Evidence]
    parties: list[str]
    applies: bool
    signed: int
    total: int
    summary: str
    ledger_apparent: str  # what the blocks read, before the pick was considered


def _ledger_finding(
    pages: list[_Page], pick: str | None, members: set[str]
) -> _LedgerFinding:
    """The block status → apparent status table, applied over the live blocks
    of the pages that describe this family, plus dating and the overview
    material. `applies` is false when the pick is not the executed output the
    ledger placed the pages into (the ledger speaks about that file)."""

    live = [b for p in pages for b in p.live_blocks()]
    statuses = [b.status for b in live]
    exceptions: list[str] = []
    # The lines of the "Block status → apparent status" table, verbatim.
    for b in live:
        if b.status == "unclear":
            exceptions.append(f"unclear return on `{b.page_id}` block {b.number}")
    for b in live:
        if b.status == "wrong-version":
            exceptions.append(
                f"version-mismatched return on `{b.page_id}` block {b.number}"
            )
    for b in live:
        if b.status in ("partial", "blank", "required", "sent"):
            exceptions.append(
                f"block {b.number} (`{b.party or 'party unknown'}`) not signed"
            )
    held = [b for b in live if b.held]
    for b in held:
        exceptions.append(f"signed sheet for `{b.page_id}` held, not placed")

    if any(s == "unclear" for s in statuses):
        apparent = "unclear"
    elif statuses and all(s in ("required", "sent") for s in statuses):
        apparent = "appears-unsigned"
    elif any(s == "wrong-version" for s in statuses):
        apparent = "appears-incomplete"
    elif any(s in ("partial", "blank", "required", "sent") for s in statuses):
        apparent = "appears-incomplete"
    elif held:
        # Row 5: a signed sheet sigpack still holds is not in the executed file.
        apparent = "appears-incomplete"
    elif statuses and all(s == "signed" for s in statuses):
        apparent = "appears-signed"
    else:
        apparent = "unclear"

    # The ledger speaks about the executed file: a signed block attaches to the
    # pick only when its own sheet was placed into the pick. All placed there →
    # applies; none → the compilation is elsewhere or absent; some → the pick
    # lacks the other sheets (appears-incomplete, each named).
    placed_docs = {b.placed_doc for b in live if b.placed_doc}
    signed_blocks = [b for b in live if b.status == "signed"]
    in_pick = [b for b in signed_blocks if pick is not None and b.placed_doc == pick]
    elsewhere = [b for b in signed_blocks if not b.held and b.placed_doc != pick]
    applies = bool(in_pick) and not elsewhere and not held
    signed = len(signed_blocks)
    total = len(statuses)
    summary = f"ledger shows {signed} of {total} blocks signed"
    ledger_apparent = apparent
    if apparent == "appears-signed" and not applies:
        if in_pick:
            for b in elsewhere:
                exceptions.append(
                    f"signed sheet for `{b.page_id}` placed in {b.placed_name!r}, "
                    "not in the selected file"
                )
            apparent = "appears-incomplete"
        else:
            if placed_docs & members:
                summary += "; the selected file is not the executed compilation"
            else:
                summary += "; executed compilation not in folder"
            apparent = "appears-unsigned"

    # Dated per block, worst wins (sigpack-ledger-consumption.md "Fields
    # read"): one dated block never dates a document whose other block waits.
    dated_values = [b.dated for b in live if b.dated]
    if any(b.date_field and not b.dated for b in live):
        dated = "undated"
    elif dated_values:
        dated = "dated"
    else:
        dated = "not-expected"
    document_date = dated_values[0] if (dated == "dated" and applies) else None

    # Findings are about the pick: the ledger's records name the pick when its
    # sheet was placed there, and nothing otherwise (status-taxonomy.md).
    def about(b: _Block) -> str | None:
        return b.placed_doc if pick is not None and b.placed_doc == pick else None

    evidence: list[Evidence] = []
    blocks: list[dict[str, Any]] = []
    parties: list[str] = []
    for b in live:
        blocks.append(
            {"party": b.party, "status": b.status, "ledger_page_id": b.page_id}
        )
        if b.party and b.party not in parties:
            parties.append(b.party)
        label = f"block {b.number}" + (f" ({b.party})" if b.party else "")
        evidence.append(
            Evidence(
                claim="execution",
                source="sigpack-ledger",
                document_id=about(b),
                locator=b.page_id,
                observation=_clip(f"{label}: {b.status}"),
            )
        )
        if b.dated:
            evidence.append(
                Evidence(
                    claim="date",
                    source="sigpack-ledger",
                    document_id=about(b),
                    locator=b.page_id,
                    observation=_clip(f"{label}: dated {b.dated}"),
                )
            )
    signature_pages: list[dict[str, Any]] = []
    seen: set[tuple[str, int | None]] = set()
    for b in live:
        placed = about(b)
        if placed and (placed, b.placed_page) not in seen:
            seen.add((placed, b.placed_page))
            signature_pages.append({"document_id": placed, "page": b.placed_page})
    return _LedgerFinding(
        apparent_status=apparent,
        dated=dated,
        document_date=document_date,
        page_ids=[p.page_id for p in pages],
        blocks=blocks,
        signature_pages=signature_pages,
        exceptions=exceptions,
        evidence=evidence,
        parties=parties,
        applies=applies,
        signed=signed,
        total=total,
        summary=summary,
        ledger_apparent=ledger_apparent,
    )


# ------------------------------------------------------------ expected set


@dataclass
class _Expected:
    item_id: str
    order: int
    title: str
    checklist_ref: str | None
    execution_expected: bool | None
    parties: tuple[str, ...]
    family_id: str | None
    preset_status: str | None = None


def _index_items(index: dict[str, Any]) -> list[dict[str, Any]]:
    items = index.get("items")
    if not isinstance(items, list):
        raise ValueError("index: items must be a list")
    out: list[dict[str, Any]] = []
    for i, item in enumerate(items):
        where = f"index items[{i}]"
        if not isinstance(item, dict):
            raise ValueError(f"{where}: must be an object")
        iid = item.get("item_id")
        if not isinstance(iid, str) or not ITEM_ID.match(iid):
            raise ValueError(f"{where}: bad item_id {iid!r}")
        if not isinstance(item.get("title"), str) or not item["title"].strip():
            raise ValueError(f"{where}: title must be a non-empty string")
        if not isinstance(item.get("execution_expected"), bool):
            raise ValueError(f"{where}: execution_expected must be true or false")
        if not isinstance(item.get("order"), int) or item["order"] < 1:
            raise ValueError(f"{where}: order must be 1 or more")
        out.append(item)
    if len({i["item_id"] for i in out}) != len(out):
        raise ValueError("index: item_id values must be unique")
    return out


def _checklist_rows(checklist: dict[str, Any]) -> list[dict[str, Any]]:
    rows = checklist.get("items")
    if not isinstance(rows, list):
        raise ValueError("checklist: items must be a list")
    out: list[dict[str, Any]] = []
    for i, row in enumerate(rows):
        where = f"checklist items[{i}]"
        if not isinstance(row, dict):
            raise ValueError(f"{where}: must be an object")
        for key in ("ref", "title"):
            if not isinstance(row.get(key), str) or not row[key].strip():
                raise ValueError(f"{where}: {key} must be a non-empty string")
        if not isinstance(row.get("execution_expected"), bool):
            raise ValueError(f"{where}: execution_expected must be true or false")
        out.append(row)
    if len({r["ref"] for r in out}) != len(out):
        raise ValueError("checklist: ref values must be unique")
    return out


def _parties(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(p for p in value if isinstance(p, str) and p.strip())


class _Binder:
    """Bind expected items to families, each family at most once."""

    def __init__(self, families: list[dict[str, Any]]) -> None:
        self.families = families
        self.by_id = {f["family_id"]: f for f in families}
        self.bound: set[str] = set()
        self.ties: list[str] = []  # rows left unbound because two families tied

    def take(self, fid: str | None) -> str | None:
        if fid is None or fid not in self.by_id or fid in self.bound:
            return None
        self.bound.add(fid)
        return fid

    def by_field(self, key: str, value: Any) -> str | None:
        for fam in self.families:
            if fam["family_id"] not in self.bound and fam.get(key) == value:
                return self.take(fam["family_id"])
        return None

    def by_members(self, docs: set[str]) -> str | None:
        for fam in self.families:
            if fam["family_id"] not in self.bound and docs & set(fam["member_ids"]):
                return self.take(fam["family_id"])
        return None

    def by_title(self, title: str) -> str | None:
        wanted = normalised_title(title)
        for fam in self.families:
            if fam["family_id"] in self.bound:
                continue
            if wanted and normalised_title(fam["title_hint"]) == wanted:
                return self.take(fam["family_id"])
        scored = [
            (title_overlap(fam["title_hint"], title), fam["family_id"])
            for fam in self.families
            if fam["family_id"] not in self.bound
        ]
        best = max((s for s, _ in scored), default=0.0)
        if best < 0.6:
            return None
        candidates = [fid for s, fid in scored if s == best]
        if len(candidates) > 1:
            # README "Fixed surface": a tie between equal candidates is no
            # match; the lawyer separates them at Gate 1.
            self.ties.append(
                f"{title!r} matches {len(candidates)} families equally "
                f"({', '.join(candidates)}); not bound — the lawyer decides at Gate 1"
            )
            return None
        return self.take(candidates[0])

    def unbound(self) -> list[dict[str, Any]]:
        return [f for f in self.families if f["family_id"] not in self.bound]


def _expected_set(
    index: dict[str, Any] | None,
    checklist: dict[str, Any] | None,
    families: list[dict[str, Any]],
    ledger: _Ledger,
    records: dict[str, FamilyInspection],
    notes: list[str],
    excluded: set[str],
) -> tuple[str, bool, str | None, list[_Expected], _Binder]:
    """PRD §4 precedence. Returns (index_source, approved, matter, items, binder).

    An approved index from an earlier run wins; else the lawyer's checklist is
    the expected set (every row an item, in checklist order, unmatched rows
    `missing`); else the ledger's agreements; else one item per family.
    `excluded` families (the ledger file itself) are never bound or listed."""

    binder = _Binder(families)
    binder.bound.update(excluded)
    items: list[_Expected] = []

    if index is not None and index.get("approved") is True:
        raw_items = sorted(
            _index_items(index), key=lambda i: (i["order"], i["item_id"])
        )
        bound = [binder.take(raw.get("family_id")) for raw in raw_items]
        for i, raw in enumerate(raw_items):
            ref = raw.get("checklist_ref")
            if bound[i] is None and isinstance(ref, str):
                bound[i] = binder.by_field("checklist_ref", ref)
        for i, raw in enumerate(raw_items):
            fid = bound[i] or binder.by_title(raw["title"])
            preset = "not-required" if raw.get("status") == "not-required" else None
            ref = raw.get("checklist_ref")
            items.append(
                _Expected(
                    item_id=raw["item_id"],
                    order=raw["order"],
                    title=raw["title"],
                    checklist_ref=ref if isinstance(ref, str) else None,
                    execution_expected=raw["execution_expected"],
                    parties=_parties(raw.get("parties")),
                    family_id=fid,
                    preset_status=preset,
                )
            )
        source = index.get("index_source")
        if source not in ("user-checklist", "sigpack-ledger", "drafted-from-census"):
            source = "user-checklist"
        matter = index.get("matter")
        return source, True, matter if isinstance(matter, str) else None, items, binder

    if index is not None:
        notes.append(
            "closing-index.json was supplied but is not approved; the expected set was drafted afresh"
        )

    if checklist is not None:
        rows = _checklist_rows(checklist)
        bound = [binder.by_field("checklist_ref", row["ref"]) for row in rows]
        for n, row in enumerate(rows, 1):
            fid = bound[n - 1] or binder.by_title(row["title"])
            items.append(
                _Expected(
                    item_id=f"CB-{n:03d}",
                    order=n,
                    title=row["title"],
                    checklist_ref=row["ref"],
                    execution_expected=row["execution_expected"],
                    parties=_parties(row.get("parties")),
                    family_id=fid,
                )
            )
        matter = checklist.get("matter")
        return (
            "user-checklist",
            False,
            matter if isinstance(matter, str) else None,
            items,
            binder,
        )

    # A families.json carrying checklist_refs without the checklist passed here
    # is not a tier of its own (README "Fixed surface": exactly four tiers);
    # the refs are informational and the set falls through.
    if any(isinstance(f.get("checklist_ref"), str) for f in families):
        notes.append(
            "families.json carries checklist rows but no --checklist was given to reconcile; "
            "the expected set was not taken from the checklist (pass --checklist to reconcile "
            "against every row)"
        )

    if ledger.current:
        bound = [binder.by_field("sigpack_agreement", a) for a in ledger.agreements]
        for i, agreement in enumerate(ledger.agreements):
            if bound[i] is None:
                docs = {
                    d
                    for p in ledger.pages_for_agreement(agreement)
                    for d in [p.exec_doc, *[b.placed_doc for b in p.blocks]]
                    if d
                }
                bound[i] = binder.by_members(docs)
        for n, agreement in enumerate(ledger.agreements, 1):
            fid = bound[n - 1] or binder.by_title(agreement)
            items.append(
                _Expected(
                    item_id=f"CB-{n:03d}",
                    order=n,
                    title=agreement,
                    checklist_ref=binder.by_id[fid].get("checklist_ref")
                    if fid
                    else None,
                    execution_expected=True,
                    parties=(),
                    family_id=fid,
                )
            )
        return "sigpack-ledger", False, ledger.matter, items, binder

    # One item per family — except the ledger's own file, which is set aside
    # whether or not the ledger passed the gate (sigpack-ledger-consumption.md:
    # "never appears as an unexpected document or a phantom expected item").
    ordered = sorted(
        (f for f in families if f["family_id"] not in excluded),
        key=lambda f: (f["title_hint"].casefold(), f["family_id"]),
    )
    for n, fam in enumerate(ordered, 1):
        fid = binder.take(fam["family_id"])
        rec = records.get(fam["family_id"])
        items.append(
            _Expected(
                item_id=f"CB-{n:03d}",
                order=n,
                title=fam["title_hint"],
                checklist_ref=None,
                execution_expected=rec.execution_expected if rec else None,
                parties=(),
                family_id=fid,
            )
        )
    return "drafted-from-census", False, None, items, binder


# ---------------------------------------------------------------- resolve


@dataclass
class _Resolved:
    item: IndexItem
    proposed_pick: str | None
    proposed_status: str | None
    evidence: list[dict[str, Any]]
    blocks: list[dict[str, Any]]
    signature_pages: list[dict[str, Any]]
    exceptions: list[str]
    not_inspected: bool
    ledger_cited: bool


def readability_by_id(manifest: dict[str, Any]) -> dict[str, str]:
    """Readability per document id: the worst any of its rows carries. The
    census already writes rows that agree; a manifest that does not is read
    the same way, so an unreadable id never hides behind a readable path."""

    out: dict[str, str] = {}
    for doc in manifest["documents"]:
        value = str(doc.get("readability") or "native")
        rank = READABILITY_RANK.index(value) if value in READABILITY_RANK else 0
        current = out.get(doc["id"])
        if current is None or rank < READABILITY_RANK.index(current):
            out[doc["id"]] = READABILITY_RANK[rank]
    return out


def _paths(manifest: dict[str, Any], doc_id: str) -> str:
    paths = sorted(d["path"] for d in manifest["documents"] if d["id"] == doc_id)
    return ", ".join(paths)


def _family_pages(ledger: _Ledger, fam: dict[str, Any]) -> list[_Page]:
    """The current ledger's pages that describe this family: by member hash,
    else by the agreement name families recorded. Empty when not current."""

    if not ledger.current:
        return []
    pages = ledger.pages_for(set(fam["member_ids"]))
    if not pages and fam.get("sigpack_agreement"):
        pages = ledger.pages_for_agreement(fam["sigpack_agreement"])
    return pages


def _resolve(
    exp: _Expected,
    fam: dict[str, Any] | None,
    rec: FamilyInspection | None,
    proposal: tuple[str | None, str | None],
    ledger: _Ledger,
    readability: dict[str, str],
    manifest: dict[str, Any],
) -> _Resolved:
    proposed_pick, proposed_status = proposal
    exceptions: list[str] = []
    evidence: list[dict[str, Any]] = []
    blocks: list[dict[str, Any]] = []
    signature_pages: list[dict[str, Any]] = []

    def build(
        status: str,
        selected: str | None,
        execution_expected: bool,
        execution: ExecutionRecord,
        qualification: str,
        missing: tuple[str, ...] = (),
        document_date: str | None = None,
        parties: tuple[str, ...] = (),
        family_id: str | None = None,
        not_inspected: bool = False,
    ) -> _Resolved:
        item = IndexItem(
            item_id=exp.item_id,
            order=exp.order,
            title=exp.title,
            checklist_ref=exp.checklist_ref,
            execution_expected=execution_expected,
            status=status,
            family_id=family_id,
            selected_id=selected,
            execution=execution,
            parties=parties,
            document_date=document_date,
            start_page=None,
            missing_components=missing,
            qualification=_clip(qualification)
            if status not in ("ready", "not-required")
            else "",
        )
        return _Resolved(
            item=item,
            proposed_pick=proposed_pick,
            proposed_status=proposed_status,
            evidence=evidence,
            blocks=blocks,
            signature_pages=signature_pages,
            exceptions=exceptions,
            not_inspected=not_inspected,
            ledger_cited=execution.evidence_source == "sigpack-ledger",
        )

    def not_expected() -> ExecutionRecord:
        return ExecutionRecord("none", "not-expected", "not-expected", ())

    def not_inspected_record(expected: bool) -> ExecutionRecord:
        if expected:
            return ExecutionRecord("none", "not-inspected", "unclear", ())
        return not_expected()

    # A. confirmed by the user as outside the closing set — with or without a
    # family: an approved index may mark a `missing` item not-required at
    # Gate 1 (status-taxonomy.md "missing and not-required are set by
    # reconciliation and by the user").
    if exp.preset_status == "not-required":
        expected = bool(exp.execution_expected)
        return build(
            "not-required",
            None,
            expected,
            not_inspected_record(expected),
            "",
            parties=exp.parties,
            family_id=fam["family_id"] if fam is not None else None,
        )

    # B. missing
    if fam is None:
        expected = True if exp.execution_expected is None else exp.execution_expected
        return build(
            "missing",
            None,
            expected,
            not_inspected_record(expected),
            "expected item not found in the source folder",
            parties=exp.parties,
        )

    fid = fam["family_id"]
    members = set(fam["member_ids"])
    ledger_pages = _family_pages(ledger, fam)

    if exp.execution_expected is not None:
        expected = exp.execution_expected
    elif rec is not None:
        expected = rec.execution_expected
    else:
        # status-taxonomy.md "Not inspected": when nothing — checklist, ledger
        # or inspection — says whether a document is one the parties sign,
        # execution is presumed expected.
        expected = True

    # C. pick
    n_members = len(members)
    pick: str | None
    if rec is not None:
        evidence.extend(e.to_dict() for e in rec.evidence)
        if rec.proposed_status == "version-conflict":
            # The lawyer reads what the inspector saw, not a generic sentence:
            # the note, else the distinct observations behind the stop.
            seen = list(dict.fromkeys(e.observation.strip() for e in rec.evidence))
            note = (
                rec.note.strip()
                or "; ".join(s for s in seen if s)
                or "more than one plausible final version and the evidence does not separate them"
            )
            return build(
                "version-conflict",
                None,
                expected,
                not_inspected_record(expected),
                f"{n_members} versions in the folder; {note}",
                family_id=fid,
                parties=exp.parties,
            )
        if rec.proposed_status == "unreadable":
            note = (
                rec.note.strip() or "cannot be opened, rendered or read with confidence"
            )
            return build(
                "unreadable",
                None,
                expected,
                not_inspected_record(expected),
                note,
                family_id=fid,
                parties=exp.parties,
            )
        pick = rec.proposed_pick
    else:
        unreadable_members = sorted(
            m for m in members if readability.get(m) in UNREADABLE
        )
        if len(unreadable_members) == n_members:
            return build(
                "unreadable",
                None,
                expected,
                not_inspected_record(expected),
                "every file in the family is "
                + ", ".join(
                    f"{readability[m]} ({_paths(manifest, m)})"
                    for m in unreadable_members
                ),
                family_id=fid,
                parties=exp.parties,
                not_inspected=True,
            )
        # Several members and no look: no pick, not even from a ledger
        # placed_in naming one of them — the ledger speaks to execution, not
        # to which version is final (status-taxonomy.md "Not inspected";
        # PRD §7 zero silent version choices).
        if n_members == 1:
            pick = next(iter(members))
        else:
            return build(
                "version-conflict",
                None,
                expected,
                not_inspected_record(expected),
                f"not inspected; {n_members} versions in the folder and none can be selected without a look",
                family_id=fid,
                parties=exp.parties,
                not_inspected=True,
            )
        if readability.get(pick) in UNREADABLE:
            return build(
                "unreadable",
                None,
                expected,
                not_inspected_record(expected),
                f"{readability[pick]} in the census ({_paths(manifest, pick)})",
                family_id=fid,
                parties=exp.parties,
                not_inspected=True,
            )

    if pick is None:
        raise ValueError(f"{fid}: {proposed_status or 'not inspected'} without a pick")

    # D. execution record
    qualifiers: list[str] = []
    document_date: str | None = None
    parties = exp.parties
    finding = _ledger_finding(ledger_pages, pick, members) if ledger_pages else None
    if finding is not None:
        blocks.extend(finding.blocks)
        signature_pages.extend(finding.signature_pages)
        exceptions.extend(finding.exceptions)
        evidence.extend(e.to_dict() for e in finding.evidence)
        if not parties:
            parties = tuple(finding.parties)

    if rec is None:
        # Not inspected: nothing was looked at, so never ready (status-taxonomy.md
        # "Not inspected"). Execution still comes from a current ledger that
        # covers the pick (rule 4: read by reconciliation itself, never
        # reclassified); completeness was inspected by nobody, so that missing
        # component is named and the derivation cannot reach `ready`.
        qualifiers.append("not inspected")
        if not expected:
            execution = not_expected()
        elif finding is not None:
            execution = ExecutionRecord(
                "sigpack-ledger",
                finding.apparent_status,
                finding.dated,
                tuple(finding.page_ids),
            )
            document_date = finding.document_date
            qualifiers.append(finding.summary)
            qualifiers.extend(finding.exceptions[:3])
        else:
            execution = not_inspected_record(expected)
        missing: tuple[str, ...] = (NOT_INSPECTED_COMPONENT,)
        status = derive_status(
            no_pick=False,
            unreadable=False,
            execution_expected=expected,
            apparent_status=execution.apparent_status,
            dated=execution.dated,
            missing_components=len(missing),
        )
        return build(
            status,
            pick,
            expected,
            execution,
            "; ".join(qualifiers),
            missing=missing,
            document_date=document_date,
            parties=parties,
            family_id=fid,
            not_inspected=True,
        )

    looked = any(
        e.claim == "execution" and e.source == "visual-inspection" for e in rec.evidence
    )
    if not expected:
        execution = not_expected()
    elif (
        finding is not None
        and finding.apparent_status == "appears-signed"
        and looked
        and rec.execution.apparent_status in NOT_SIGNED_STATUSES
        and rec.execution.apparent_status != "not-inspected"
    ):
        # The ledger says signed, but a look at the selected file found a
        # blank, partial or unclear block. `placed_in` is a name, not a hash,
        # so the ledger's finding cannot be tied to these bytes: the visual
        # finding governs the item, the ledger's blocks stay as they are in the
        # overview, and the disagreement is written under "Ledger notes"
        # (status-taxonomy.md rule 4; sigpack-ledger-consumption.md "The
        # ledger speaks about the executed file"). Nothing is reclassified.
        apparent = rec.execution.apparent_status
        execution = ExecutionRecord(
            "visual-inspection", apparent, rec.execution.dated, ()
        )
        if rec.execution.dated == "dated":
            document_date = rec.execution.document_date
        for p in rec.execution.signature_pages:
            if p.to_dict() not in signature_pages:
                signature_pages.append(p.to_dict())
        seen_as = apparent.replace("-", " ") + " on visual inspection"
        qualifiers.append(seen_as)
        exceptions.append(seen_as)
        block = {
            "appears-unsigned": "a blank block",
            "appears-incomplete": "a partial block",
        }.get(apparent, "an unclear block")
        exceptions.append(
            f"inspection saw {block} on the selected file; the ledger's signed "
            "finding could not be tied to these bytes"
        )
    elif finding is not None:
        execution = ExecutionRecord(
            "sigpack-ledger",
            finding.apparent_status,
            finding.dated,
            tuple(finding.page_ids),
        )
        document_date = finding.document_date
        if finding.apparent_status != "appears-signed":
            qualifiers.append(finding.summary)
            qualifiers.extend(finding.exceptions[:3])
        elif finding.dated in ("undated", "unclear"):
            qualifiers.append(
                "ledger: every block signed but no completion date on the page"
            )
        if rec.execution.apparent_status != finding.apparent_status and not any(
            e.source == "sigpack-ledger" and e.claim in ("execution", "date")
            for e in rec.evidence
        ):
            # A record that did not cite the ledger is not rejected for
            # disagreeing with it, but the disagreement is the lawyer's to see:
            # the inspector saw one thing on the page, the ledger settled another.
            exceptions.append(
                "inspection disagrees with the ledger: the record saw "
                f"{rec.execution.apparent_status} on visual inspection, the ledger "
                f"reads {finding.apparent_status}; the ledger governs (rule 4)"
            )
        if (
            ledger.receipt
            and ledger.receipt.get("complete") is True
            and finding.apparent_status != "appears-signed"
        ):
            exceptions.append(
                "the ledger receipt says complete but this item's blocks do not all read signed"
            )
    elif not rec.execution_expected:
        execution = ExecutionRecord("none", "not-inspected", "unclear", ())
        qualifiers.append(
            "the checklist expects execution but inspection did not look at the execution pages"
        )
    else:
        apparent = rec.execution.apparent_status
        dated = rec.execution.dated
        source = (
            "visual-inspection" if looked and apparent != "not-inspected" else "none"
        )
        unverified = apparent == "appears-signed" and not looked
        if unverified:
            # The only execution evidence cites a ledger this run cannot verify
            # against: an unverified citation is not evidence (rule 4). Say
            # which of the three it was; no page was looked at.
            apparent, dated = "unclear", "unclear"
            if ledger.current:
                why = "which is current but does not cover this document"
            elif ledger.supplied:
                why = "that does not match the folder"
            else:
                why = "that was not supplied"
            qualifiers.append(
                f"execution evidence cites a sigpack ledger {why}; no execution page was inspected"
            )
        execution = ExecutionRecord(source, apparent, dated, ())
        if dated == "dated":
            document_date = rec.execution.document_date
        signature_pages.extend(p.to_dict() for p in rec.execution.signature_pages)
        if apparent in NOT_SIGNED_STATUSES and not unverified:
            seen_as = apparent.replace("-", " ") + (
                " on visual inspection" if looked else ""
            )
            qualifiers.append(seen_as)
            exceptions.append(seen_as)
        elif dated in ("undated", "unclear") and not unverified:
            qualifiers.append(
                "appears signed but no completion date on the execution page"
            )

    missing = tuple(
        f"{m.component} ({m.referenced_at})" for m in rec.missing_components
    )
    status = derive_status(
        no_pick=False,
        unreadable=False,
        execution_expected=expected,
        apparent_status=execution.apparent_status,
        dated=execution.dated,
        missing_components=len(missing),
    )
    if status == "incomplete":
        qualifiers = ["missing: " + "; ".join(missing)] + qualifiers
    if rec.note.strip() and status != "ready":
        qualifiers.append(rec.note.strip())
    return build(
        status,
        pick if status in SELECTABLE_STATUSES else None,
        expected,
        execution,
        "; ".join(qualifiers),
        missing=missing,
        document_date=document_date,
        parties=parties,
        family_id=fid,
    )


# ------------------------------------------------------------- inspection


def _validate_records(
    inspection: dict[str, Any],
    families: dict[str, dict[str, Any]],
    ledger: _Ledger,
    readability: dict[str, str],
    manifest: dict[str, Any],
    ledger_doc: str | None = None,
) -> tuple[
    dict[str, FamilyInspection],
    list[tuple[str | None, str]],
    dict[str, tuple[str | None, str | None]],
]:
    """Lenient read, then the reconciliation-level checks. Returns the valid
    records by family, the rejections, and what each record proposed (kept
    for the selection plan even when the record was rejected)."""

    parsed, rejected = Inspection.from_dict_lenient(inspection)

    proposals: dict[str, tuple[str | None, str | None]] = {}
    for raw in inspection.get("families") or []:
        if not isinstance(raw, dict) or not isinstance(raw.get("family_id"), str):
            continue
        pick = raw.get("proposed_pick")
        status = raw.get("proposed_status")
        # The first record for a family is the one read; a duplicate is rejected.
        proposals.setdefault(
            raw["family_id"],
            (
                pick if isinstance(pick, str) and DOC_ID.match(pick) else None,
                status
                if isinstance(status, str) and status in INSPECTION_STATUSES
                else None,
            ),
        )

    good: dict[str, FamilyInspection] = {}
    for rec in parsed.families:
        fam = families.get(rec.family_id)
        if fam is None:
            rejected.append((rec.family_id, "unknown family: not in families.json"))
            continue
        if sorted(rec.member_ids) != sorted(fam["member_ids"]):
            rejected.append((rec.family_id, "member_ids do not match families.json"))
            continue
        pick = rec.proposed_pick
        if pick is not None and readability.get(pick) in UNREADABLE:
            rejected.append(
                (
                    rec.family_id,
                    f"proposed {rec.proposed_status} but the census marks {pick} as {readability[pick]}",
                )
            )
            continue
        if pick is not None and pick == ledger_doc:
            rejected.append(
                (
                    rec.family_id,
                    f"proposed pick {pick} is the sigpack ledger file itself "
                    f"({_paths(manifest, pick)}), not a closing document",
                )
            )
            continue
        citations = [
            e
            for e in rec.evidence
            if e.source == "sigpack-ledger" and e.claim in ("execution", "date")
        ]
        pages = _family_pages(ledger, fam) if citations else []
        if pages:
            # A citation names a page the ledger actually holds for this
            # family (inspection.schema.json: locator = ledger page id), or it
            # is not a citation.
            held = [p.page_id for p in pages]
            unknown = sorted({e.locator for e in citations if e.locator not in held})
            if unknown:
                rejected.append(
                    (
                        rec.family_id,
                        f"cites sigpack ledger page(s) {', '.join(unknown)} that the ledger "
                        f"does not hold for this family (its pages: {', '.join(held)}) "
                        "(status-taxonomy.md rule 4)",
                    )
                )
                continue
            members = set(fam["member_ids"])
            finding = _ledger_finding(pages, pick, members)
            if (
                rec.execution.apparent_status != finding.apparent_status
                or rec.execution.dated != finding.dated
            ):
                if (
                    pick is not None
                    and not finding.applies
                    and finding.ledger_apparent == "appears-signed"
                    and rec.execution.apparent_status == "appears-signed"
                ):
                    # The record reports what the ledger says, but of the
                    # wrong file: the ledger's signed pages sit in the
                    # executed compilation, not in the pick.
                    reason = (
                        "cites the sigpack ledger for a pick that is not the executed "
                        "compilation the ledger placed its pages into; the ledger's "
                        f"appears-signed applies to that file, not to {_paths(manifest, pick)} "
                        f"({finding.summary}) (status-taxonomy.md rule 4; "
                        "sigpack-ledger-consumption.md 'The ledger speaks about the executed file')"
                    )
                else:
                    reason = (
                        "cites the sigpack ledger but disagrees with it: the ledger reads "
                        f"{finding.apparent_status}/{finding.dated}, the record says "
                        f"{rec.execution.apparent_status}/{rec.execution.dated} (status-taxonomy.md rule 4)"
                    )
                rejected.append((rec.family_id, reason))
                continue
        good[rec.family_id] = rec
    return good, rejected, proposals


# ------------------------------------------------------------ exceptions.md


def _exceptions_md(
    matter: str,
    receipt: Receipt,
    resolved: list[_Resolved],
    unexpected: list[dict[str, Any]],
    rejected: list[tuple[str | None, str]],
    item_of_family: dict[str, str],
    ledger: _Ledger,
    notes: list[str],
    manifest: dict[str, Any],
    inspected: set[str],
) -> str:
    def rows(status: str) -> list[str]:
        return [
            f"- {r.item.item_id} {r.item.title}: {r.item.qualification}"
            for r in resolved
            if r.item.status == status
        ]

    def section(title: str, lines: list[str]) -> list[str]:
        return [f"## {title}", *(lines or ["- none"]), ""]

    unexpected_lines = [
        f"- {u['family_id']} {u['title_hint']}: {len(u['member_ids'])} file(s) not on the expected set "
        f"({', '.join(_paths(manifest, m) for m in u['member_ids'])}); "
        "the lawyer decides at Gate 1 whether it becomes an item or is marked not-required"
        for u in unexpected
    ]
    rejected_lines = []
    for fid, reason in rejected:
        prefix = item_of_family.get(fid or "", "")
        label = (prefix + " " if prefix else "") + (fid or "unknown family")
        rejected_lines.append(f"- {label}: {reason}")
    not_inspected_lines = [
        f"- {r.item.item_id} {r.item.title} ({r.item.family_id}): no valid inspection record; "
        f"written as {r.item.status}"
        for r in resolved
        if r.not_inspected
    ]
    # An unexpected family nobody looked at is named here too: "every family
    # was looked at, or is named under Not inspected" (SKILL.md Final checks).
    not_inspected_lines += [
        f"- {u['family_id']} {u['title_hint']}: unexpected and no valid inspection record"
        for u in unexpected
        if u["family_id"] not in inspected
    ]
    skipped_lines = [
        f"- {s['path']} ({s['reason']}): not inventoried by the census"
        for s in manifest.get("skipped") or []
    ]

    ledger_lines: list[str] = []
    if not ledger.supplied:
        ledger_lines.append(
            "- no sigpack ledger supplied; execution evidence comes from inspection alone"
        )
    elif not ledger.current:
        ledger_lines.append(
            f"- a sigpack ledger was found but does not match the folder ({ledger.note}); "
            "it was not cited and execution evidence comes from inspection alone"
        )
    else:
        cited = sum(1 for r in resolved if r.ledger_cited)
        ledger_lines.append(
            f"- sigpack ledger is current (receipt as of {(ledger.receipt or {}).get('as_of')}); "
            f"cited on {cited} item(s)"
        )
        if ledger.closing_date:
            ledger_lines.append(
                f"- ledger closing_date {ledger.closing_date} is shown for information only; it decides nothing"
            )
        for r in resolved:
            for line in r.exceptions:
                if line.startswith(
                    (
                        "the ledger receipt says complete",
                        "inspection disagrees with the ledger",
                        "inspection saw ",
                    )
                ):
                    ledger_lines.append(f"- {r.item.item_id} {r.item.title}: {line}")
        ledger_lines.extend(f"- {n}" for n in ledger.unplaced_notes)
    ledger_lines.extend(f"- {n}" for n in notes)

    lines = [f"# Exceptions — {matter}", "", receipt.line(), ""]
    lines += section("Missing", rows("missing"))
    lines += section("Incomplete", rows("incomplete"))
    lines += section("Version conflicts", rows("version-conflict"))
    lines += section("Unsigned", rows("unsigned"))
    lines += section("Undated", rows("undated"))
    lines += section("Unexpected", unexpected_lines)
    lines += section("Unreadable", rows("unreadable"))
    lines += section("Rejected inspection records", rejected_lines)
    lines += section("Not inspected", not_inspected_lines)
    lines += section("Not inventoried", skipped_lines)
    lines += section("Ledger notes", ledger_lines)
    return "\n".join(lines).rstrip() + "\n"


# ----------------------------------------------------------------- public


def reconcile(
    manifest: dict,
    families: dict,
    inspection: dict,
    *,
    checklist: dict | None = None,
    index: dict | None = None,
    sigpack: dict | None = None,
    sigpack_dir: Path | None = None,
    sigpack_path: Path | None = None,
    checklist_sha256: str | None = None,
    as_of: str,
) -> tuple[dict, dict, dict, dict, str]:
    """Return (closing_index, selection_plan, execution_overview, receipt, exceptions_md).

    `checklist` is the lawyer's checklist.json (the same one given to
    families): the expected set, PRD precedence 1. `checklist_sha256` is the
    sha256 of its bytes when the caller has the file; without it the dict's
    canonical JSON is hashed. Either must equal `families.checklist_sha256`,
    or the run is refused: rows bound at the families stage must be the rows
    reconciled. `index` is an approved closing-index.json from an earlier run
    and, when given, wins over the checklist; one for another corpus_id is
    refused. `sigpack_path` is the ledger file as supplied; its hash
    identifies the ledger's own document, whatever the file is named. Without
    it, a `sigpack.ledger.json` in `sigpack_dir` is taken to be the ledger.
    """

    if not isinstance(as_of, str) or not DATE.match(as_of):
        raise ValueError(f"as_of must be YYYY-MM-DD, got {as_of!r}")
    try:
        date.fromisoformat(as_of)
    except ValueError as error:
        raise ValueError(f"as_of {as_of} is not a real date") from error
    check_manifest(manifest)
    corpus_id = manifest["corpus_id"]
    if not isinstance(families, dict):
        raise ValueError("families must be a JSON object")
    if families.get("corpus_id") != corpus_id:
        raise ValueError(
            f"families corpus_id {families.get('corpus_id')!r} is not the manifest's "
            f"{corpus_id!r}: a different folder"
        )
    if not isinstance(inspection, dict):
        raise ValueError("inspection must be a JSON object")
    if inspection.get("corpus_id") != corpus_id:
        raise ValueError(
            f"inspection corpus_id {inspection.get('corpus_id')!r} is not the manifest's "
            f"{corpus_id!r}: a different folder"
        )
    if checklist is not None and not isinstance(checklist, dict):
        raise ValueError("checklist must be a JSON object")
    if index is not None and not isinstance(index, dict):
        raise ValueError("index must be a JSON object")
    if index is not None and not (
        index.get("schema_version") == SCHEMA_VERSION
        and "index_source" in index
        and isinstance(index.get("items"), list)
    ):
        hint = (
            " (this looks like a checklist; pass it as --checklist)"
            if isinstance(index.get("items"), list)
            and index.get("items")
            and isinstance(index["items"][0], dict)
            and "ref" in index["items"][0]
            else ""
        )
        raise ValueError(
            "index is not a closing-index.json written by reconcile" + hint
        )
    if (
        index is not None
        and index.get("approved") is True
        and index.get("corpus_id") != corpus_id
    ):
        # closing-index.schema.json: its decisions were taken about other files.
        raise ValueError(
            f"approved index corpus_id {index.get('corpus_id')!r} is not the manifest's "
            f"{corpus_id!r}: its decisions were taken about other files; refused"
        )

    doc_ids = sorted({d["id"] for d in manifest["documents"]})
    check_families(families, doc_ids)
    if checklist is not None:
        # families.schema.json: the rows bound there must be the rows here.
        supplied = checklist_sha256 or checklist_digest(checklist) or ""
        bound = families.get("checklist_sha256")
        if bound is None:
            raise ValueError(
                "a checklist was given to reconcile but families.json was built without "
                "one (checklist_sha256 null); run families with the same --checklist first"
            )
        if bound != supplied:
            raise ValueError(
                f"checklist sha256 {supplied[:12]}… is not the one families.json was bound "
                f"against ({bound[:12]}…): the checklist changed between families and "
                "reconcile; run families again with this checklist"
            )
    fam_list: list[dict[str, Any]] = [dict(f) for f in families["families"]]
    families_by_id = {f["family_id"]: f for f in fam_list}
    readability = readability_by_id(manifest)

    if sigpack is not None:
        ledger = _read_ledger(sigpack, manifest, sigpack_dir)
    else:
        ledger = _Ledger(False, False)

    # The ledger file itself, when it sits in the closing folder, is inventoried
    # like everything else. The document whose hash equals the supplied file —
    # that one id, never a family chosen by title — is set aside whether or not
    # the ledger passed the gate: it is neither an item nor unexpected, and its
    # family is recorded not-required in the selection plan while still counting
    # in sources.in_families. Any other member of that family is a document
    # (sigpack-ledger-consumption.md, "Resolving the files").
    notes: list[str] = []
    excluded: set[str] = set()
    ledger_file: Path | None = None
    ledger_doc: str | None = None
    if sigpack is not None and sigpack_path is not None:
        ledger_file = sigpack_path
    elif sigpack is not None and sigpack_dir is not None:
        ledger_file = sigpack_dir / "sigpack.ledger.json"
    if ledger_file is not None and ledger_file.is_file():
        ledger_doc = _hash_id(ledger_file)
        for fam in fam_list:
            if ledger_doc not in fam["member_ids"]:
                continue
            others = sorted(m for m in fam["member_ids"] if m != ledger_doc)
            if not others:
                excluded.add(fam["family_id"])
                notes.append(
                    f"{fam['family_id']} is the ledger itself, not a closing document "
                    f"({ledger_file.name}); recorded not-required in the selection plan"
                )
            else:
                fam["member_ids"] = others
                notes.append(
                    f"{ledger_doc} in {fam['family_id']} is the ledger itself, not a closing "
                    f"document ({ledger_file.name}); set aside — the family's other "
                    f"{len(others)} file(s) ({', '.join(_paths(manifest, m) for m in others)}) "
                    "are reconciled as documents"
                )
    records, rejected, proposals = _validate_records(
        inspection,
        {f["family_id"]: f for f in families["families"]},
        ledger,
        readability,
        manifest,
        ledger_doc,
    )
    index_source, approved, matter, expected, binder = _expected_set(
        index, checklist, fam_list, ledger, records, notes, excluded
    )
    notes.extend(binder.ties)
    if matter is None and ledger.current and ledger.matter:
        matter = ledger.matter
    if matter is None:
        matter = str(manifest.get("root_label") or "")

    resolved: list[_Resolved] = []
    for exp in expected:
        fam = families_by_id.get(exp.family_id) if exp.family_id else None
        rec = records.get(exp.family_id) if exp.family_id else None
        proposal = proposals.get(exp.family_id or "", (None, None))
        resolved.append(
            _resolve(exp, fam, rec, proposal, ledger, readability, manifest)
        )

    unexpected = sorted(
        (
            {
                "family_id": f["family_id"],
                "title_hint": f["title_hint"],
                "member_ids": sorted(f["member_ids"]),
            }
            for f in binder.unbound()
        ),
        key=lambda u: (u["title_hint"].casefold(), u["family_id"]),
    )
    item_of_family = {
        r.item.family_id: r.item.item_id for r in resolved if r.item.family_id
    }

    by_status = {s: 0 for s in RECEIPT_STATUSES}
    for r in resolved:
        by_status[r.item.status] += 1
    files = len(manifest["documents"])
    distinct = len(doc_ids)
    receipt = Receipt(
        corpus_id=manifest["corpus_id"],
        mode="audit",
        index_approved=approved,
        expected_items=len(resolved),
        by_status=by_status,
        unexpected_families=len(unexpected),
        sources={
            "files": files,
            "distinct": distinct,
            "in_families": int(families["counts"]["in_families"]),
            "duplicates": files - distinct,
            "unreadable": sum(1 for d in doc_ids if readability.get(d) in UNREADABLE),
            # Hidden entries are listed, not counted (status-taxonomy.md outcomes).
            "skipped": sum(
                1 for s in manifest["skipped"] if s.get("reason") != "hidden"
            ),
        },
        inspection={
            "families": len(fam_list),
            "inspected": len(records),
            "rejected": len(rejected),
        },
        sigpack={
            "ledger_supplied": ledger.supplied,
            "ledger_current": ledger.current if ledger.supplied else None,
            "documents_cited": sum(1 for r in resolved if r.ledger_cited),
        },
        as_of=as_of,
    )

    closing_index = {
        "schema_version": SCHEMA_VERSION,
        "matter": matter,
        "index_source": index_source,
        "approved": approved,
        "corpus_id": manifest["corpus_id"],
        "items": [r.item.to_dict() for r in resolved],
        "unexpected_families": unexpected,
    }

    plan_families: list[dict[str, Any]] = []
    for r in resolved:
        fid = r.item.family_id
        if fid is None:
            continue
        fam = families_by_id[fid]
        plan_families.append(
            {
                "family_id": fid,
                "item_id": r.item.item_id,
                "title_hint": fam["title_hint"],
                "grouping_basis": list(fam["grouping_basis"]),
                "member_ids": sorted(fam["member_ids"]),
                "proposed_pick": r.proposed_pick,
                "proposed_status": r.proposed_status,
                "resolved_status": r.item.status,
                "selected_id": r.item.selected_id,
                "evidence": r.evidence,
            }
        )
    for u in unexpected:
        fam = families_by_id[u["family_id"]]
        rec = records.get(u["family_id"])
        proposal = proposals.get(u["family_id"], (None, None))
        plan_families.append(
            {
                "family_id": u["family_id"],
                "item_id": None,
                "title_hint": fam["title_hint"],
                "grouping_basis": list(fam["grouping_basis"]),
                "member_ids": sorted(fam["member_ids"]),
                "proposed_pick": proposal[0],
                "proposed_status": proposal[1],
                "resolved_status": "unexpected",
                "selected_id": None,
                "evidence": [e.to_dict() for e in rec.evidence] if rec else [],
            }
        )
    for fid in sorted(excluded):
        fam = families_by_id[fid]
        plan_families.append(
            {
                "family_id": fid,
                "item_id": None,
                "title_hint": fam["title_hint"],
                "grouping_basis": list(fam["grouping_basis"]),
                "member_ids": sorted(fam["member_ids"]),
                "proposed_pick": None,
                "proposed_status": None,
                "resolved_status": "not-required",
                "selected_id": None,
                "evidence": [],
            }
        )
    selection_plan = {
        "schema_version": SCHEMA_VERSION,
        "corpus_id": manifest["corpus_id"],
        "families": plan_families,
    }

    execution_overview = {
        "schema_version": SCHEMA_VERSION,
        "corpus_id": manifest["corpus_id"],
        "sigpack": {
            "ledger_supplied": ledger.supplied,
            "ledger_current": ledger.current if ledger.supplied else None,
            "closing_date": ledger.closing_date if ledger.current else None,
            "ledger_receipt": ledger.receipt if ledger.current else None,
        },
        "documents": [
            {
                "item_id": r.item.item_id,
                "title": r.item.title,
                "execution_expected": r.item.execution_expected,
                "evidence_source": r.item.execution.evidence_source,
                "apparent_status": r.item.execution.apparent_status,
                "qualification": r.item.qualification,
                "blocks": r.blocks,
                "document_date": r.item.document_date,
                "dating_unresolved": bool(
                    r.item.execution_expected
                    and r.item.execution.dated in ("undated", "unclear")
                ),
                "signature_pages": r.signature_pages,
                "exceptions": r.exceptions,
            }
            for r in resolved
        ],
    }

    exceptions_md = _exceptions_md(
        matter,
        receipt,
        resolved,
        unexpected,
        rejected,
        item_of_family,
        ledger,
        notes,
        manifest,
        set(records),
    )
    return (
        closing_index,
        selection_plan,
        execution_overview,
        receipt.to_dict(),
        exceptions_md,
    )
