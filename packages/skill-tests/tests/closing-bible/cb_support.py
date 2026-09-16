"""Shared helpers for the closing-bible suite: synthetic folders, inspection
records written the way the skill's model would write them, the pipeline in
one call, and the receipt line as status-taxonomy.md prints it.

Everything here codes against the fixed surface documented by the closing-bible
skill ("Fixed surface the builders coded against"). The census / families /
reconcile modules are imported lazily so
the models-only tests pass before those modules exist.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pdfgen import write_pdf

ROOT = Path(__file__).resolve().parents[4]
SKILL = ROOT / "skills" / "transactional" / "closing-bible"
SCRIPTS = SKILL / "scripts"
REFERENCES = SKILL / "references"
CLI = SCRIPTS / "closing_bible.py"

AS_OF = "2026-03-02"
MATTER = "Project Aurora"
SELLER = "Northgate Holdings Limited"
BUYER = "Eastbridge Capital LP"
CLOSING_DATE_TEXT = "1 March 2026"

RECEIPT_STATUSES = (
    "ready",
    "unsigned",
    "undated",
    "incomplete",
    "version-conflict",
    "missing",
    "unreadable",
    "not-required",
)


# ------------------------------------------------------------- page text


def cover(title: str, parties: tuple[str, str] = (SELLER, BUYER)) -> str:
    return f"{title.upper()}\n{MATTER}\nbetween\n{parties[0]}\nand\n{parties[1]}"


def signed_page(
    *, party: str = SELLER, signatory: str = "A. Signatory", date: str | None
) -> str:
    lines = [
        f"SIGNED by {signatory}",
        f"for and on behalf of {party}",
        f"/s/ {signatory}",
    ]
    lines.append(f"Dated: {date}" if date else "Dated: ______________")
    return "\n".join(lines)


def blank_block(party: str = SELLER) -> str:
    return (
        f"EXECUTED as a DEED by {party}\n"
        "Director: ______________\n"
        "Witness: ______________\n"
        "Date: ______________"
    )


# -------------------------------------------------------------- hashing


def doc_id(path: Path) -> str:
    """The manifest's document id: sha256 of the bytes, first 12 hex."""

    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()[:12]


def hash_tree(root: Path) -> dict[str, str]:
    """Relative path -> sha256 for every file under root (anchor A4)."""

    out: dict[str, str] = {}
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        out[path.relative_to(root).as_posix()] = hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
    return out


# ------------------------------------------------------------ the folder


@dataclass
class Folder:
    """A synthetic closing folder under tmp_path. Records every id it wrote."""

    root: Path

    def __post_init__(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.ids: dict[str, str] = {}

    def pdf(
        self,
        rel: str,
        pages: list[str],
        *,
        encrypt: bool = False,
        corrupt: bool = False,
        mtime: str | None = None,
    ) -> str:
        path = self.root / rel
        write_pdf(path, pages, encrypt=encrypt, corrupt=corrupt)
        if mtime is not None:
            import datetime as dt

            stamp = dt.datetime.fromisoformat(mtime).timestamp()
            os.utime(path, (stamp, stamp))
        self.ids[rel] = doc_id(path)
        return self.ids[rel]

    def copy_of(self, src_rel: str, rel: str) -> str:
        """A byte-identical duplicate under another name (contract row 2)."""

        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((self.root / src_rel).read_bytes())
        self.ids[rel] = doc_id(path)
        return self.ids[rel]

    def json(self, rel: str, obj: Any) -> Path:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n")
        return path

    def hashes(self) -> dict[str, str]:
        return hash_tree(self.root)


# ------------------------------------------------------ expected-set inputs


def checklist(
    rows: Sequence[tuple[str, str, bool] | tuple[str, str, bool, list[str]]],
    *,
    matter: str = MATTER,
) -> dict[str, Any]:
    """checklist.json per references/checklist.schema.json."""

    items = []
    for row in rows:
        ref, title, execution_expected, *parties = row
        item: dict[str, Any] = {
            "ref": ref,
            "title": title,
            "execution_expected": execution_expected,
        }
        if parties:
            item["parties"] = list(parties[0])
        items.append(item)
    return {"matter": matter, "items": items}


def ledger_block(
    number: int,
    party: str,
    status: str,
    *,
    date_field: bool = True,
    dated: str | None = None,
    placed_in: str | None = None,
    signatory: str = "A. Signatory",
) -> dict[str, Any]:
    """One signature block, per sigpack/references/ledger_schema.md."""

    block: dict[str, Any] = {
        "block": number,
        "party": party,
        "signatory": signatory,
        "capacity": "Authorised Signatory",
        "date_field": date_field,
        "copies_required": 1,
        "status": status,
        "returned": [],
    }
    if status not in ("required", "sent"):
        block["returned"].append(
            {
                "pack": f"(Signed) Signature Pack - {signatory}.pdf",
                "page": number,
                "batch": "returned/2026-03-01/",
                "execution": status,
                "printed_name_matches": True,
                "dated": dated,
                "chosen": True,
                "placed_in": placed_in,
                "spare": False,
            }
        )
    return block


def ledger_page(
    page_id: str,
    file: str,
    page: int,
    agreement: str,
    blocks: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "id": page_id,
        "file": file,
        "page": page,
        "agreement": agreement,
        "footer": f"Signature Page - {agreement}",
        "version_marker": "(none printed)",
        "reserved": False,
        "esig_separator": False,
        "blocks": blocks,
    }


def ledger(
    pages: list[dict[str, Any]],
    *,
    matter: str = MATTER,
    as_of: str = "2026-03-01",
    closing_date: str | None = "2026-03-01",
    execution_dir: str = "execution/",
) -> dict[str, Any]:
    """A settled sigpack.ledger.json: manifest, block statuses, balanced receipt."""

    blocks = [b for p in pages for b in p["blocks"]]
    by = {
        s: sum(1 for b in blocks if b["status"] == s)
        for s in (
            "signed",
            "partial",
            "blank",
            "unclear",
            "wrong-version",
            "required",
            "sent",
        )
    }
    receipt = {
        "pages_required": len(pages),
        "blocks_required": len(blocks),
        "blocks_signed": by["signed"],
        "blocks_partial": by["partial"],
        "blocks_blank": by["blank"],
        "blocks_unclear": by["unclear"],
        "blocks_missing": len(blocks) - by["signed"],
        "spare_originals": 0,
        "unmatched_returns": 0,
        "reserved_unassigned": 0,
        "complete": by["signed"] == len(blocks),
        "as_of": as_of,
    }
    return {
        "matter": matter,
        "created": "2026-02-20",
        "closing_date": closing_date,
        "execution_dir": execution_dir,
        "returned_dirs": ["returned/2026-03-01/"],
        "signature_pages": pages,
        "packs_sent": [],
        "unmatched_returns": [],
        "checkpoints": [],
        "receipt": receipt,
    }


# ------------------------------------------------------- inspection records


def evidence(
    claim: str,
    source: str,
    locator: str,
    observation: str,
    document_id: str | None = None,
) -> dict[str, Any]:
    return {
        "claim": claim,
        "source": source,
        "document_id": document_id,
        "locator": locator,
        "observation": observation,
    }


def record(
    family: dict[str, Any],
    *,
    pick: str | None,
    status: str,
    execution_expected: bool,
    apparent: str,
    dated: str,
    evidence: list[dict[str, Any]],
    document_date: str | None = None,
    signature_pages: list[dict[str, Any]] | None = None,
    missing: Sequence[tuple[str, str]] = (),
    note: str = "",
    validate: bool = True,
) -> dict[str, Any]:
    """One families[] entry of inspection.json, checked against models unless
    the test is deliberately writing a bad one."""

    rec = {
        "family_id": family["family_id"],
        "member_ids": list(family["member_ids"]),
        "proposed_pick": pick,
        "proposed_status": status,
        "execution_expected": execution_expected,
        "execution": {
            "apparent_status": apparent,
            "dated": dated,
            "document_date": document_date,
            "signature_pages": list(signature_pages or []),
        },
        "evidence": evidence,
        "missing_components": [
            {"component": c, "referenced_at": at} for c, at in missing
        ],
        "note": note,
    }
    if validate:
        from closing_bible import models

        models.FamilyInspection.from_dict(rec)
    return rec


def rec_signed(
    family: dict[str, Any],
    pick: str,
    *,
    page: int | None,
    date: str | None = CLOSING_DATE_TEXT,
    source: str = "visual-inspection",
    locator: str | None = None,
    missing: Sequence[tuple[str, str]] = (),
    extra_evidence: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Execution expected; the pages show signatures. Dated when `date` is given."""

    loc = locator or f"page {page}"
    ev = [
        evidence(
            "execution",
            source,
            loc,
            "every block carries a signature and printed name",
            pick,
        ),
        evidence(
            "date",
            source,
            loc,
            f"date line reads {date}" if date else "date line is blank",
            pick,
        ),
    ]
    ev += extra_evidence or []
    if missing:
        status = "incomplete" if date else "undated"
    else:
        status = "ready" if date else "undated"
    return record(
        family,
        pick=pick,
        status=status,
        execution_expected=True,
        apparent="appears-signed",
        dated="dated" if date else "undated",
        document_date=date,
        signature_pages=[{"document_id": pick, "page": page}],
        evidence=ev,
        missing=missing,
    )


def rec_unsigned(
    family: dict[str, Any],
    pick: str,
    *,
    page: int,
    apparent: str = "appears-unsigned",
    observation: str = "signature block is blank; no signature or witness mark",
    extra_evidence: list[dict[str, Any]] | None = None,
    source: str = "visual-inspection",
    locator: str | None = None,
) -> dict[str, Any]:
    return record(
        family,
        pick=pick,
        status="unsigned",
        execution_expected=True,
        apparent=apparent,
        dated="undated",
        signature_pages=[{"document_id": pick, "page": page}],
        evidence=[
            evidence("execution", source, locator or f"page {page}", observation, pick),
            *(extra_evidence or []),
        ],
    )


def rec_not_expected(
    family: dict[str, Any],
    pick: str,
    *,
    missing: Sequence[tuple[str, str]] = (),
) -> dict[str, Any]:
    """A schedule or exhibit nobody signs."""

    return record(
        family,
        pick=pick,
        status="incomplete" if missing else "ready",
        execution_expected=False,
        apparent="not-expected",
        dated="not-expected",
        evidence=[
            evidence(
                "identity",
                "text-extraction",
                "page 1",
                "heading matches the checklist row",
                pick,
            )
        ],
        missing=missing,
    )


def rec_conflict(family: dict[str, Any], observation: str) -> dict[str, Any]:
    return record(
        family,
        pick=None,
        status="version-conflict",
        execution_expected=True,
        apparent="unclear",
        dated="unclear",
        evidence=[
            evidence(
                "version", "visual-inspection", f"{m} execution pages", observation, m
            )
            for m in family["member_ids"]
        ],
    )


def rec_unreadable(
    family: dict[str, Any], *, execution_expected: bool = True
) -> dict[str, Any]:
    return record(
        family,
        pick=None,
        status="unreadable",
        execution_expected=execution_expected,
        apparent="not-inspected" if execution_expected else "not-expected",
        dated="unclear" if execution_expected else "not-expected",
        evidence=[
            evidence(
                "identity",
                "filename",
                family["member_ids"][0],
                "file could not be opened for review",
                family["member_ids"][0],
            )
        ],
    )


# --------------------------------------------------------------- pipeline


def modules():
    """census, families, reconcile — imported late so models-only tests run first."""

    from closing_bible import census, families, reconcile

    return census, families, reconcile


@dataclass
class Result:
    index: dict[str, Any]
    plan: dict[str, Any]
    overview: dict[str, Any]
    receipt: dict[str, Any]
    exceptions: str

    def item(self, title: str) -> dict[str, Any]:
        hits = [
            i for i in self.index["items"] if i["title"].casefold() == title.casefold()
        ]
        assert len(hits) == 1, f"{title!r}: {len(hits)} items match"
        return hits[0]

    def overview_doc(self, item_id: str) -> dict[str, Any]:
        hits = [d for d in self.overview["documents"] if d["item_id"] == item_id]
        assert len(hits) == 1, f"{item_id}: {len(hits)} overview documents"
        return hits[0]

    def plan_family(self, family_id: str) -> dict[str, Any]:
        hits = [f for f in self.plan["families"] if f["family_id"] == family_id]
        assert len(hits) == 1, f"{family_id}: {len(hits)} plan families"
        return hits[0]

    def line(self) -> str:
        """The receipt line, the way models.Receipt.line() prints it."""

        return receipt_line(self.receipt)

    def all_text(self) -> str:
        return "\n".join(
            [
                json.dumps(self.index, sort_keys=True),
                json.dumps(self.plan, sort_keys=True),
                json.dumps(self.overview, sort_keys=True),
                json.dumps(self.receipt, sort_keys=True),
                self.exceptions,
            ]
        )


class Audit:
    """census → families, then `reconcile(records)` as often as a test needs."""

    def __init__(
        self,
        root: Path,
        *,
        checklist: dict[str, Any] | None = None,
        sigpack: dict[str, Any] | None = None,
        sigpack_dir: Path | None = None,
        sigpack_path: Path | None = None,
    ) -> None:
        census, families, _ = modules()
        self.root = root
        self.checklist = checklist
        self.sigpack = sigpack
        self.sigpack_dir = sigpack_dir
        self.sigpack_path = sigpack_path
        self.manifest = census.build_manifest(root)
        self.families = families.build_families(
            self.manifest, sigpack=sigpack, checklist=checklist
        )

    @property
    def corpus_id(self) -> str:
        return self.manifest["corpus_id"]

    def document(self, rel: str) -> dict[str, Any]:
        hits = [d for d in self.manifest["documents"] if d["path"] == rel]
        assert len(hits) == 1, f"{rel}: {len(hits)} manifest rows"
        return hits[0]

    def family_of(self, document_id: str) -> dict[str, Any]:
        hits = [f for f in self.families["families"] if document_id in f["member_ids"]]
        assert len(hits) == 1, f"{document_id}: in {len(hits)} families"
        return hits[0]

    def inspection(
        self, records: list[dict[str, Any]], *, corpus_id: str | None = None
    ) -> dict[str, Any]:
        return {
            "schema_version": "1.0.0",
            "corpus_id": corpus_id or self.corpus_id,
            "families": records,
        }

    def reconcile(
        self,
        records: list[dict[str, Any]],
        *,
        index: dict[str, Any] | None = None,
        as_of: str = AS_OF,
        corpus_id: str | None = None,
    ) -> Result:
        _, _, reconcile = modules()
        outputs = reconcile.reconcile(
            self.manifest,
            self.families,
            self.inspection(records, corpus_id=corpus_id),
            checklist=self.checklist,
            index=index,
            sigpack=self.sigpack,
            sigpack_dir=self.sigpack_dir,
            sigpack_path=self.sigpack_path,
            as_of=as_of,
        )
        return Result(*outputs)


def write_cli_inputs(
    run: Audit, out_dir: Path, records: list[dict[str, Any]]
) -> dict[str, Path]:
    """Write manifest, families, inspection and (when the audit has one) the
    checklist under out_dir for a CLI run. The CLI hashes checklist.json's
    bytes, so families.json is stamped with the hash of the bytes written here
    — the API side hashed the dict's canonical JSON, which is not the file."""

    paths = {
        "manifest": out_dir / "source-manifest.json",
        "families": out_dir / "families.json",
        "inspection": out_dir / "inspection.json",
    }
    families = json.loads(json.dumps(run.families))
    if run.checklist is not None:
        paths["checklist"] = out_dir / "checklist.json"
        paths["checklist"].write_text(json.dumps(run.checklist))
        families["checklist_sha256"] = hashlib.sha256(
            paths["checklist"].read_bytes()
        ).hexdigest()
    paths["manifest"].write_text(json.dumps(run.manifest))
    paths["families"].write_text(json.dumps(families))
    paths["inspection"].write_text(json.dumps(run.inspection(records)))
    return paths


def write_docx(path: Path, paragraphs: list[str]) -> Path:
    """A minimal real .docx (zip + document.xml) that soffice can render."""

    import zipfile

    body = "".join(
        f'<w:p><w:r><w:t xml:space="preserve">{p}</w:t></w:r></w:p>' for p in paragraphs
    )
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{body}<w:sectPr/></w:body></w:document>"
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        "</Types>"
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
        "</Relationships>"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", rels)
        archive.writestr("word/document.xml", document)
    return path


# ------------------------------------------------------- wave 2: assembly


AUDIT_OUTPUTS = (
    "closing-index.json",
    "selection-plan.json",
    "execution-overview.json",
    "closing-receipt.json",
)


def dump(obj: Any) -> str:
    """The script's canonical JSON form (sorted keys, two-space indent)."""

    return json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def write_audit_outputs(run: Audit, result: Result, out_dir: Path) -> None:
    """Lay the audit folder out the way reconcile writes it."""

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "source-manifest.json").write_text(dump(run.manifest))
    (out_dir / "families.json").write_text(dump(run.families))
    (out_dir / "closing-index.json").write_text(dump(result.index))
    (out_dir / "selection-plan.json").write_text(dump(result.plan))
    (out_dir / "execution-overview.json").write_text(dump(result.overview))
    (out_dir / "closing-receipt.json").write_text(dump(result.receipt))
    (out_dir / "exceptions.md").write_text(result.exceptions)


def approve(index: dict[str, Any]) -> dict[str, Any]:
    """Gate 1 recorded: the index the lawyer confirmed, nothing else moved."""

    approved = json.loads(json.dumps(index))
    approved["approved"] = True
    return approved


class Bible:
    """audit → Gate 1 → plan → Gate 2 → build, in-process, against the
    `assemble` API. The CLI path is exercised by the matrix rows."""

    def __init__(
        self,
        folder: Folder,
        out_dir: Path,
        package_parent: Path,
        *,
        checklist: dict[str, Any] | None = None,
        sigpack: dict[str, Any] | None = None,
        sigpack_path: Path | None = None,
    ) -> None:
        self.folder = folder
        self.out_dir = out_dir
        self.package_parent = package_parent
        self.checklist = checklist
        self.sigpack = sigpack
        self.sigpack_path = sigpack_path
        self.run: Audit | None = None
        self.result: Result | None = None

    def audit(
        self,
        records_for: Any,
        *,
        adjust: Any = None,
        as_of: str = AS_OF,
    ) -> Result:
        """Reconcile, record Gate 1 (`adjust(index)` edits the proposed index
        the way the lawyer's decisions would), approve, reconcile again."""

        self.run = Audit(
            self.folder.root,
            checklist=self.checklist,
            sigpack=self.sigpack,
            sigpack_dir=self.sigpack_path.parent if self.sigpack_path else None,
            sigpack_path=self.sigpack_path,
        )
        records = records_for(self.run)
        first = self.run.reconcile(records, as_of=as_of)
        approved = approve(first.index)
        if adjust is not None:
            adjust(approved)
        self.result = self.run.reconcile(records, index=approved, as_of=as_of)
        assert self.result.index["approved"] is True
        write_audit_outputs(self.run, self.result, self.out_dir)
        return self.result

    def plan(
        self,
        *,
        include_qualified: bool = False,
        volume_pages: int | None = None,
        prior: str | None = None,
        approved: bool = True,
    ) -> dict[str, Any]:
        from closing_bible import assemble

        assert self.run is not None and self.result is not None, "audit first"
        plan = assemble.plan(
            load(self.out_dir / "closing-index.json"),
            self.result.plan,
            self.run.manifest,
            self.result.overview,
            include_qualified=include_qualified,
            volume_pages=volume_pages,
            prior_folder=prior,
            package_parent=self.package_parent,
        )
        plan["approved"] = approved
        (self.out_dir / "build-plan.json").write_text(dump(plan))
        return plan

    def build(
        self, plan: dict[str, Any] | None = None, *, as_of: str = AS_OF
    ) -> tuple[dict[str, Any], dict[str, Any], str | None]:
        from closing_bible import assemble

        if plan is None:
            plan = load(self.out_dir / "build-plan.json")
        return assemble.build(
            plan,
            root=self.folder.root,
            audit_dir=self.out_dir,
            package_parent=self.package_parent,
            as_of=as_of,
        )

    def package(self, version: int = 1) -> Path:
        return self.package_parent / f"closing-bible-v{version:03d}"


def cli_audit(
    folder: Folder,
    out_dir: Path,
    records_for: Any,
    *,
    checklist: dict[str, Any] | None = None,
    sigpack_rel: str | None = None,
    as_of: str = AS_OF,
) -> Audit:
    """The audit through the CLI: reconcile, approve at Gate 1, reconcile
    again with --index. Leaves the approved outputs in out_dir."""

    sigpack_path = folder.root / sigpack_rel if sigpack_rel else None
    sigpack = load(sigpack_path) if sigpack_path else None
    run = Audit(
        folder.root,
        checklist=checklist,
        sigpack=sigpack,
        sigpack_dir=sigpack_path.parent if sigpack_path else None,
        sigpack_path=sigpack_path,
    )
    paths = write_cli_inputs(run, out_dir, records_for(run))
    args: list[str | Path] = [
        "reconcile",
        "--manifest",
        paths["manifest"],
        "--families",
        paths["families"],
        "--inspection",
        paths["inspection"],
        "--out-dir",
        out_dir,
        "--root",
        folder.root,
        "--as-of",
        as_of,
    ]
    if "checklist" in paths:
        args += ["--checklist", paths["checklist"]]
    if sigpack_path:
        args += ["--sigpack", sigpack_path]
    run_cli(*args)
    approved_path = out_dir / "approved-index.json"
    approved_path.write_text(dump(approve(load(out_dir / "closing-index.json"))))
    run_cli(*args, "--index", approved_path)
    assert load(out_dir / "closing-index.json")["approved"] is True
    return run


def cli_plan(
    folder: Folder,
    out_dir: Path,
    package_parent: Path,
    *extra: str | Path,
    approved: bool = True,
) -> Path:
    plan_path = out_dir / "build-plan.json"
    run_cli(
        "plan",
        "--out-dir",
        out_dir,
        "--root",
        folder.root,
        "--out",
        plan_path,
        "--package-parent",
        package_parent,
        *extra,
    )
    plan = load(plan_path)
    plan["approved"] = approved
    plan_path.write_text(dump(plan))
    return plan_path


def receipt_line(receipt: dict[str, Any]) -> str:
    """The line from status-taxonomy.md 'Receipt outcomes', from a receipt dict."""

    parts = [f"{receipt['expected_items']} expected"]
    parts += [f"{receipt['by_status'][s]} {s}" for s in RECEIPT_STATUSES]
    parts.append(f"{receipt['unexpected_families']} unexpected")
    return " · ".join(parts) + f" · {receipt['outcome'].upper()}"


def run_cli(*args: str | Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        [sys.executable, str(CLI), *(str(a) for a in args)],
        capture_output=True,
        text=True,
    )
    if check:
        assert proc.returncode == 0, (
            f"{args[0]} exited {proc.returncode}: {proc.stderr[-600:]}"
        )
    return proc


def load(path: Path) -> Any:
    return json.loads(path.read_text())
