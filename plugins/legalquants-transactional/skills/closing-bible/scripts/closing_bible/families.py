"""Group a source manifest into document families → families.json.

PRD §4 "Source census": a family is one document across its versions and
duplicates. v1 grouping is deterministic from the manifest alone, in this
order (dev-tools/closing-bible/README.md, "Fixed surface"):

1. every path sharing a manifest id is one document (the census already
   collapsed byte-identical files onto one id);
2. documents sharing a normalised `title_hint` are one family;
3. when a sigpack ledger is supplied, a document whose path basename equals a
   ledger `signature_pages[].file` — or the executed output a chosen return was
   `placed_in` — joins that agreement's family and the family records
   `sigpack_agreement`;
4. when a checklist is supplied, a family whose title tokens overlap a
   checklist row's title by at least 0.6 records that row's `ref` as
   `checklist_ref`. A row is given to at most one family (the best match), so
   reconciliation stays one-to-one; a row two families match equally well is
   given to neither (reconcile notes it); the rest are shown to the lawyer at
   Gate 1.

Every distinct id lands in exactly one family or the function refuses
(`ValueError`). Normalisation ideas (entity-suffix stripping, token overlap)
are copied from `../../../diligence/scripts/shared/build_families.py`, never
imported across the skill boundary.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter
from hashlib import sha256
from typing import Any

from .models import DOC_ID, SCHEMA_VERSION, corpus_id_for, family_id_for

ENTITY_SUFFIXES = frozenset(
    {"inc", "llc", "ltd", "limited", "corp", "co", "lp", "llp", "plc", "gmbh", "pty"}
)
# Words a title hint may still carry that say nothing about which document it is.
TITLE_NOISE = frozenset(
    {"the", "of", "a", "an", "and", "to", "for", "copy", "pdf", "docx"}
)
CHECKLIST_OVERLAP = 0.6


def _normalise(text: str) -> str:
    text = text.replace("­", "")
    text = unicodedata.normalize("NFKC", text)
    return re.sub(r"\s+", " ", text.casefold()).strip()


def title_tokens(text: str) -> list[str]:
    """Casefolded alphanumeric tokens with trailing entity suffixes and noise removed."""

    toks = re.sub(r"[^\w\s]+", " ", _normalise(text)).split()
    toks = [t for t in toks if t not in TITLE_NOISE]
    while toks and toks[-1] in ENTITY_SUFFIXES:
        toks.pop()
    return toks


def normalised_title(text: str) -> str:
    return " ".join(title_tokens(text))


def title_overlap(a: str, b: str) -> float:
    """Shared tokens over the larger token set: symmetric, so a long title does
    not swallow a short one it merely contains."""

    ta, tb = set(title_tokens(a)), set(title_tokens(b))
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / max(len(ta), len(tb))


def _basename(path: str) -> str:
    return path.replace("\\", "/").rsplit("/", 1)[-1]


def check_manifest(manifest: Any) -> list[dict[str, Any]]:
    """Refuse a manifest that does not agree with itself, and return its rows.

    source-manifest.schema.json: `corpus_id` is derived from the rows and
    `counts.files`/`counts.distinct` describe them, so a row edited out after
    the census leaves a manifest whose stated corpus_id and counts no longer
    match — that manifest is refused, never reconciled. `skipped[]` must be a
    list: the census lists what it did not inventory, and the receipt counts it.
    """

    if not isinstance(manifest, dict) or not isinstance(
        manifest.get("documents"), list
    ):
        raise ValueError("manifest: documents must be a list")
    if not isinstance(manifest.get("corpus_id"), str):
        raise ValueError("manifest: corpus_id must be a string")
    docs: list[dict[str, Any]] = []
    for i, doc in enumerate(manifest["documents"]):
        where = f"manifest documents[{i}]"
        if not isinstance(doc, dict):
            raise ValueError(f"{where}: must be an object")
        doc_id = doc.get("id")
        if not isinstance(doc_id, str) or not DOC_ID.match(doc_id):
            raise ValueError(f"{where}: bad id {doc_id!r}")
        if not isinstance(doc.get("path"), str):
            raise ValueError(f"{where}: path must be a string")
        if not isinstance(doc.get("title_hint"), str):
            raise ValueError(f"{where}: title_hint must be a string")
        docs.append(doc)
    ids = {d["id"] for d in docs}
    derived = corpus_id_for(ids)
    if manifest["corpus_id"] != derived:
        raise ValueError(
            f"manifest does not agree with itself: corpus_id {manifest['corpus_id']!r} "
            f"but its {len(ids)} distinct document id(s) derive {derived!r}; "
            "the rows were changed after the census — re-run census"
        )
    counts = manifest.get("counts")
    if not isinstance(counts, dict):
        raise ValueError("manifest: counts must be an object")
    if counts.get("files") != len(docs) or counts.get("distinct") != len(ids):
        raise ValueError(
            f"manifest does not agree with itself: counts say {counts.get('files')} files / "
            f"{counts.get('distinct')} distinct but the rows hold {len(docs)} / {len(ids)}; "
            "the rows were changed after the census — re-run census"
        )
    skipped = manifest.get("skipped")
    if not isinstance(skipped, list) or not all(
        isinstance(s, dict) and isinstance(s.get("path"), str) for s in skipped
    ):
        raise ValueError(
            "manifest: skipped must be a list of {path, reason} entries — re-run census"
        )
    return docs


def checklist_digest(checklist: dict[str, Any] | None) -> str | None:
    """sha256 of a checklist handed over as a dict (no file bytes to hash):
    the canonical JSON serialisation, so families and reconcile agree."""

    if checklist is None:
        return None
    payload = json.dumps(checklist, sort_keys=True, separators=(",", ":"))
    return sha256(payload.encode("utf-8")).hexdigest()


def ledger_agreement_files(sigpack: Any) -> dict[str, list[str]]:
    """Agreement → basenames the ledger ties to it, in ledger order: the
    execution version of every signature page and any executed output a chosen
    return was placed into."""

    if not isinstance(sigpack, dict) or not isinstance(
        sigpack.get("signature_pages"), list
    ):
        raise ValueError("sigpack ledger: signature_pages must be a list")
    out: dict[str, list[str]] = {}
    for page in sigpack["signature_pages"]:
        if not isinstance(page, dict):
            continue
        agreement = page.get("agreement")
        file = page.get("file")
        if not isinstance(agreement, str) or not isinstance(file, str):
            continue
        names = out.setdefault(agreement, [])
        if _basename(file) not in names:
            names.append(_basename(file))
        for block in page.get("blocks") or []:
            if not isinstance(block, dict):
                continue
            for ret in block.get("returned") or []:
                if not isinstance(ret, dict) or not ret.get("chosen"):
                    continue
                placed = ret.get("placed_in")
                if isinstance(placed, str) and placed:
                    name = _basename(placed.split("#", 1)[0])
                    if name and name not in names:
                        names.append(name)
    return out


def _checklist_items(checklist: Any) -> list[dict[str, Any]]:
    if not isinstance(checklist, dict) or not isinstance(checklist.get("items"), list):
        raise ValueError("checklist: items must be a list")
    items: list[dict[str, Any]] = []
    for i, item in enumerate(checklist["items"]):
        where = f"checklist items[{i}]"
        if not isinstance(item, dict):
            raise ValueError(f"{where}: must be an object")
        for key in ("ref", "title"):
            if not isinstance(item.get(key), str) or not item[key].strip():
                raise ValueError(f"{where}: {key} must be a non-empty string")
        if not isinstance(item.get("execution_expected"), bool):
            raise ValueError(f"{where}: execution_expected must be true or false")
        items.append(item)
    return items


class _UnionFind:
    def __init__(self, ids: list[str]) -> None:
        self.parent = {i: i for i in ids}

    def find(self, x: str) -> str:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: str, b: str) -> bool:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return False
        self.parent[max(ra, rb)] = min(ra, rb)
        return True


def _family_title(member_ids: list[str], titles: dict[str, list[str]]) -> str:
    """The most common normalised title among the members; ties go to the
    longest raw hint (the fullest name — a duplicate filed as "DL scan" must
    not rename the Disclosure Letter), then the alphabetically first."""

    raw = [t for m in member_ids for t in titles[m]]
    counts = Counter(normalised_title(t) for t in raw)
    return sorted(raw, key=lambda t: (-counts[normalised_title(t)], -len(t), t))[0]


def build_families(
    manifest: dict,
    *,
    sigpack: dict | None = None,
    checklist: dict | None = None,
    checklist_sha256: str | None = None,
) -> dict:
    """Group the manifest into families (shape: references/families.schema.json).

    `checklist_sha256` is the sha256 of the checklist.json bytes when the
    caller has the file (the CLI does); without it the dict's canonical JSON
    is hashed. Either way it is recorded so reconcile can refuse a checklist
    that changed between the two stages.
    """

    docs = check_manifest(manifest)
    ids = sorted({d["id"] for d in docs})
    titles: dict[str, list[str]] = {i: [] for i in ids}
    basenames: dict[str, set[str]] = {i: set() for i in ids}
    for doc in sorted(docs, key=lambda d: (d["id"], d["path"])):
        titles[doc["id"]].append(doc["title_hint"])
        basenames[doc["id"]].add(_basename(doc["path"]))

    uf = _UnionFind(ids)
    basis: dict[str, set[str]] = {i: {"hash"} for i in ids}

    # 2. normalised title
    by_title: dict[str, list[str]] = {}
    for doc_id in ids:
        for hint in titles[doc_id]:
            key = normalised_title(hint)
            if key:
                by_title.setdefault(key, []).append(doc_id)
    for group in by_title.values():
        distinct = sorted(set(group))
        if len(distinct) < 2:
            continue
        for doc_id in distinct:
            basis[doc_id].add("normalised-title")
            uf.union(distinct[0], doc_id)

    # 3. sigpack agreement
    agreement_of: dict[str, str] = {}
    if sigpack is not None:
        for agreement, names in ledger_agreement_files(sigpack).items():
            matched = sorted(doc_id for doc_id in ids if basenames[doc_id] & set(names))
            for doc_id in matched:
                basis[doc_id].add("sigpack-agreement")
                agreement_of.setdefault(doc_id, agreement)
                uf.union(matched[0], doc_id)

    # collect components
    components: dict[str, list[str]] = {}
    for doc_id in ids:
        components.setdefault(uf.find(doc_id), []).append(doc_id)

    families: list[dict[str, Any]] = []
    for members in components.values():
        members = sorted(members)
        grouping = set().union(*(basis[m] for m in members))
        agreements = sorted({agreement_of[m] for m in members if m in agreement_of})
        families.append(
            {
                "family_id": family_id_for(members),
                "title_hint": _family_title(members, titles),
                "grouping_basis": sorted(grouping),
                "member_ids": members,
                "sigpack_agreement": agreements[0] if agreements else None,
                "checklist_ref": None,
            }
        )
    families.sort(key=lambda f: (f["title_hint"].casefold(), f["family_id"]))

    # 4. checklist rows, each given to at most one family
    if checklist is not None:
        items = _checklist_items(checklist)
        scored: list[tuple[float, int, int, int]] = []
        for fi, fam in enumerate(families):
            for ci, item in enumerate(items):
                score = title_overlap(fam["title_hint"], item["title"])
                if score >= CHECKLIST_OVERLAP:
                    scored.append((score, len(fam["member_ids"]), -fi, ci))
        # A tie between equal candidates is no match (README "Fixed surface"):
        # a row whose best score two families share binds to neither.
        best_by_row: dict[int, float] = {}
        for score, _n, _fi, ci in scored:
            best_by_row[ci] = max(best_by_row.get(ci, 0.0), score)
        tied_rows = {
            ci
            for ci, best in best_by_row.items()
            if sum(1 for s, _n, _fi, c in scored if c == ci and s == best) > 1
        }
        scored = [s for s in scored if s[3] not in tied_rows]
        taken_rows: set[int] = set()
        taken_fams: set[int] = set()
        for _score, _n, neg_fi, ci in sorted(
            scored, key=lambda s: (-s[0], -s[1], -s[2], s[3])
        ):
            fi = -neg_fi
            if fi in taken_fams or ci in taken_rows:
                continue
            taken_fams.add(fi)
            taken_rows.add(ci)
            families[fi]["checklist_ref"] = items[ci]["ref"]
            families[fi]["grouping_basis"] = sorted(
                set(families[fi]["grouping_basis"]) | {"checklist-ref"}
            )

    if checklist is not None and checklist_sha256 is None:
        checklist_sha256 = checklist_digest(checklist)
    result = {
        "schema_version": SCHEMA_VERSION,
        "corpus_id": manifest["corpus_id"],
        "checklist_sha256": checklist_sha256 if checklist is not None else None,
        "families": families,
        "counts": {
            "distinct_documents": len(ids),
            "families": len(families),
            "in_families": sum(len(f["member_ids"]) for f in families),
        },
    }
    check_families(result, ids)
    return result


def check_families(families: Any, distinct_ids: list[str] | None = None) -> None:
    """Refuse a families document unless every distinct id sits in exactly one
    family (status-taxonomy.md rule 7)."""

    if not isinstance(families, dict) or not isinstance(families.get("families"), list):
        raise ValueError("families: families must be a list")
    if "checklist_sha256" not in families or not (
        families["checklist_sha256"] is None
        or isinstance(families["checklist_sha256"], str)
    ):
        raise ValueError(
            "families: checklist_sha256 must be present (a sha256 string, or null when "
            "no checklist was given) — re-run families"
        )
    seen: dict[str, str] = {}
    for fam in families["families"]:
        if not isinstance(fam, dict):
            raise ValueError("families: every family must be an object")
        members = fam.get("member_ids")
        fid = fam.get("family_id")
        if not isinstance(members, list) or not members:
            raise ValueError(f"families: {fid} has no member_ids")
        if fid != family_id_for(members):
            raise ValueError(f"families: {fid} does not match its members")
        for member in members:
            if member in seen:
                raise ValueError(
                    f"families: {member} sits in both {seen[member]} and {fid}"
                )
            seen[member] = str(fid)
    counts = families.get("counts") or {}
    if counts.get("in_families") != len(seen):
        raise ValueError("families: counts.in_families does not match the members")
    if distinct_ids is not None:
        expected = set(distinct_ids)
        if set(seen) != expected:
            missing = sorted(expected - set(seen))
            extra = sorted(set(seen) - expected)
            raise ValueError(
                f"families: not every distinct document is in exactly one family "
                f"(missing {missing}, unknown {extra})"
            )
        if counts.get("distinct_documents") != len(expected):
            raise ValueError("families: counts.distinct_documents is wrong")
