"""Typed dataclasses for the closing-bible artifacts that carry judgment.

They mirror `inspection.schema.json`, the `items[]` of
`closing-index.schema.json`, and `closing-receipt.schema.json`, and carry the
invariants a schema cannot express — the derivation table and the seven rules
in `../../references/status-taxonomy.md`. The skill vendors no JSON Schema
validator; `from_dict()` on the inspection classes is the gate that rejects a
malformed record with a named reason instead of absorbing it, and
`to_dict()` produces the exact schema-conforming shape.

The manifest, families, selection plan and execution overview are plain
dicts, validated by shape in the module that writes each.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from hashlib import sha256
from typing import Any

SCHEMA_VERSION = "1.0.0"

# The nine statuses of status-taxonomy.md. `unexpected` is a family, not an
# index row: it lives in closing-index.unexpected_families until Gate 1.
STATUSES = frozenset(
    {
        "ready",
        "unsigned",
        "undated",
        "incomplete",
        "version-conflict",
        "missing",
        "unexpected",
        "unreadable",
        "not-required",
    }
)
ITEM_STATUSES = STATUSES - {"unexpected"}
# Only these may be proposed by inspection; the rest belong to reconciliation
# or the user.
INSPECTION_STATUSES = frozenset(
    {"ready", "unsigned", "undated", "incomplete", "version-conflict", "unreadable"}
)
# A selected source exists only for these; version-conflict is a stop.
SELECTABLE_STATUSES = frozenset({"ready", "unsigned", "undated", "incomplete"})
# Statuses inspection may propose with no pick.
NO_PICK_STATUSES = frozenset({"version-conflict", "unreadable"})

EVIDENCE_CLAIMS = frozenset(
    {"version", "execution", "date", "completeness", "identity"}
)
EVIDENCE_SOURCES = frozenset(
    {"sigpack-ledger", "visual-inspection", "text-extraction", "filename", "checklist"}
)
# The only sources that may carry an execution or date claim (rules 1, 3).
EXECUTION_EVIDENCE_SOURCES = frozenset({"sigpack-ledger", "visual-inspection"})
# What a filename may say something about, and nothing more (rule 1).
FILENAME_CLAIMS = frozenset({"version", "identity"})

EXECUTION_SOURCES = frozenset({"sigpack-ledger", "visual-inspection", "none"})
APPARENT_STATUSES = frozenset(
    {
        "appears-signed",
        "appears-incomplete",
        "appears-unsigned",
        "unclear",
        "not-expected",
        "not-inspected",
    }
)
NOT_SIGNED_STATUSES = frozenset(
    {"appears-incomplete", "appears-unsigned", "unclear", "not-inspected"}
)
DATED = frozenset({"dated", "undated", "not-expected", "unclear"})
INDEX_SOURCES = frozenset({"user-checklist", "sigpack-ledger", "drafted-from-census"})
GROUPING_BASIS = frozenset(
    {"hash", "normalised-title", "sigpack-agreement", "checklist-ref", "user-regrouped"}
)
READABILITY = frozenset({"native", "scanned", "suspect", "encrypted", "corrupt"})
OUTCOMES = frozenset({"complete", "qualified", "failed"})
MODES = frozenset({"audit", "build", "update"})

DOC_ID = re.compile(r"^sha256:[0-9a-f]{12}$")
FAMILY_ID = re.compile(r"^fam_[0-9a-f]{12}$")
ITEM_ID = re.compile(r"^CB-[0-9]{3}$")
DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")


def family_id_for(member_ids: list[str] | tuple[str, ...]) -> str:
    """Same members, same family id, across runs."""

    payload = "\n".join(sorted(set(member_ids)))
    return "fam_" + sha256(payload.encode("utf-8")).hexdigest()[:12]


def corpus_id_for(document_ids: list[str] | set[str]) -> str:
    payload = "\n".join(sorted(set(document_ids)))
    return sha256(payload.encode("utf-8")).hexdigest()[:16]


def derive_status(
    *,
    no_pick: bool,
    unreadable: bool,
    execution_expected: bool,
    apparent_status: str,
    dated: str,
    missing_components: int,
) -> str:
    """The derivation table in status-taxonomy.md, first row wins."""

    if no_pick:
        return "version-conflict"
    if unreadable:
        return "unreadable"
    if execution_expected and apparent_status in NOT_SIGNED_STATUSES:
        return "unsigned"
    if (
        execution_expected
        and apparent_status == "appears-signed"
        and dated in ("undated", "unclear")
    ):
        return "undated"
    if missing_components:
        return "incomplete"
    return "ready"


MONTHS = (
    "jan",
    "feb",
    "mar",
    "apr",
    "may",
    "jun",
    "jul",
    "aug",
    "sep",
    "oct",
    "nov",
    "dec",
)


def looks_like_a_date(text: str) -> bool:
    """A printed date carries a digit or a month name; '[DATE]' and '.....' do not."""

    low = text.casefold()
    return any(ch.isdigit() for ch in low) or any(m in low for m in MONTHS)


def _require(cond: bool, reason: str) -> None:
    if not cond:
        raise ValueError(reason)


def _str(d: dict[str, Any], key: str, where: str) -> str:
    value = d.get(key)
    if not isinstance(value, str):
        raise ValueError(f"{where}: {key} must be a string")
    return value


def _fields(d: Any, allowed: set[str], required: set[str], where: str) -> None:
    _require(isinstance(d, dict), f"{where}: must be an object")
    missing = required - set(d)
    _require(not missing, f"{where}: missing fields {sorted(missing)}")
    extra = set(d) - allowed
    _require(not extra, f"{where}: unexpected fields {sorted(extra)}")


# ------------------------------------------------------------------ evidence


@dataclass(frozen=True)
class Evidence:
    """One thing that was seen, and where. Never a conclusion."""

    claim: str
    source: str
    document_id: str | None
    locator: str
    observation: str

    def __post_init__(self) -> None:
        _require(
            self.claim in EVIDENCE_CLAIMS, f"unsupported evidence claim: {self.claim}"
        )
        _require(
            self.source in EVIDENCE_SOURCES,
            f"unsupported evidence source: {self.source}",
        )
        if self.document_id is not None:
            _require(
                bool(DOC_ID.match(self.document_id)),
                f"bad document_id: {self.document_id}",
            )
        _require(bool(self.locator.strip()), "evidence locator must not be empty")
        _require(
            bool(self.observation.strip()), "evidence observation must not be empty"
        )
        _require(
            len(self.observation) <= 500,
            "evidence observation must be 500 characters or fewer",
        )
        # Rules 1 and 3: an execution or date claim needs the ledger or a look
        # at the page (a filename date is never a date); beyond that, a
        # filename can speak to version or identity only.
        if self.claim in ("execution", "date"):
            _require(
                self.source in EXECUTION_EVIDENCE_SOURCES,
                f"'{self.claim}' evidence must come from the sigpack ledger or visual "
                f"inspection, not {self.source} (status-taxonomy.md rules 1 and 3)",
            )
        if self.source == "filename":
            _require(
                self.claim in FILENAME_CLAIMS,
                f"a filename cannot evidence '{self.claim}' (status-taxonomy.md rule 1)",
            )

    @classmethod
    def from_dict(cls, d: Any, where: str = "evidence") -> Evidence:
        keys = {"claim", "source", "document_id", "locator", "observation"}
        _fields(d, keys, keys, where)
        doc = d.get("document_id")
        _require(
            doc is None or isinstance(doc, str),
            f"{where}: document_id must be a string or null",
        )
        return cls(
            claim=_str(d, "claim", where),
            source=_str(d, "source", where),
            document_id=doc,
            locator=_str(d, "locator", where),
            observation=_str(d, "observation", where),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim": self.claim,
            "source": self.source,
            "document_id": self.document_id,
            "locator": self.locator,
            "observation": self.observation,
        }


# ------------------------------------------------------------- execution


@dataclass(frozen=True)
class SignaturePageRef:
    document_id: str
    page: int | None

    def __post_init__(self) -> None:
        _require(
            bool(DOC_ID.match(self.document_id)),
            f"bad signature page document_id: {self.document_id}",
        )
        _require(
            self.page is None
            or (
                isinstance(self.page, int)
                and not isinstance(self.page, bool)
                and self.page >= 1
            ),
            "signature page number must be an integer of 1 or more",
        )

    @classmethod
    def from_dict(cls, d: Any, where: str) -> SignaturePageRef:
        keys = {"document_id", "page"}
        _fields(d, keys, keys, where)
        page = d.get("page")
        _require(
            page is None or (isinstance(page, int) and not isinstance(page, bool)),
            f"{where}: page must be an integer or null",
        )
        return cls(document_id=_str(d, "document_id", where), page=page)

    def to_dict(self) -> dict[str, Any]:
        return {"document_id": self.document_id, "page": self.page}


@dataclass(frozen=True)
class ExecutionFinding:
    """PRD §4 'Execution evidence': what the execution pages showed.

    The structured landing place for the no-ledger path. `apparent_status`
    and `dated` are the inputs to the derivation table; `document_date` is the
    date as printed, verbatim, never from a filename or timestamp.
    """

    apparent_status: str
    dated: str
    document_date: str | None = None
    signature_pages: tuple[SignaturePageRef, ...] = ()

    def __post_init__(self) -> None:
        _require(
            self.apparent_status in APPARENT_STATUSES,
            f"unsupported apparent_status: {self.apparent_status}",
        )
        _require(self.dated in DATED, f"unsupported dated value: {self.dated}")
        if self.dated == "dated":
            _require(
                bool(self.document_date and self.document_date.strip()),
                "dated requires document_date as printed on the page",
            )
            _require(
                looks_like_a_date(self.document_date or ""),
                f"document_date {self.document_date!r} does not read as a date; a placeholder "
                "or a blank date line is undated (status-taxonomy.md rule 3)",
            )
        if self.dated in ("undated", "not-expected"):
            _require(
                self.document_date is None,
                f"{self.dated} may not carry a document_date",
            )
        if self.apparent_status == "not-inspected":
            _require(
                self.dated == "unclear" and self.document_date is None,
                "not-inspected requires dated: unclear and document_date: null — nothing was looked at",
            )

    @classmethod
    def from_dict(cls, d: Any, where: str) -> ExecutionFinding:
        keys = {"apparent_status", "dated", "document_date", "signature_pages"}
        _fields(d, keys, keys, where)
        date = d.get("document_date")
        _require(
            date is None or isinstance(date, str),
            f"{where}: document_date must be a string or null",
        )
        pages = d.get("signature_pages")
        _require(isinstance(pages, list), f"{where}: signature_pages must be a list")
        return cls(
            apparent_status=_str(d, "apparent_status", where),
            dated=_str(d, "dated", where),
            document_date=date,
            signature_pages=tuple(
                SignaturePageRef.from_dict(p, f"{where}: signature_pages[{i}]")
                for i, p in enumerate(pages)
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "apparent_status": self.apparent_status,
            "dated": self.dated,
            "document_date": self.document_date,
            "signature_pages": [p.to_dict() for p in self.signature_pages],
        }


# ---------------------------------------------------------------- inspection


@dataclass(frozen=True)
class MissingComponent:
    component: str
    referenced_at: str

    def __post_init__(self) -> None:
        _require(bool(self.component.strip()), "missing component must be named")
        _require(
            bool(self.referenced_at.strip()),
            "missing component must say where it was referenced",
        )

    def to_dict(self) -> dict[str, Any]:
        return {"component": self.component, "referenced_at": self.referenced_at}


@dataclass(frozen=True)
class FamilyInspection:
    """What inspection found for one family. Proposes; never decides."""

    family_id: str
    member_ids: tuple[str, ...]
    proposed_pick: str | None
    proposed_status: str
    execution_expected: bool
    execution: ExecutionFinding
    evidence: tuple[Evidence, ...]
    missing_components: tuple[MissingComponent, ...] = ()
    note: str = ""

    def __post_init__(self) -> None:
        fid = self.family_id
        _require(bool(FAMILY_ID.match(fid)), f"bad family_id: {fid}")
        _require(len(self.member_ids) >= 1, f"{fid}: member_ids must not be empty")
        for member in self.member_ids:
            _require(bool(DOC_ID.match(member)), f"{fid}: bad member id {member}")
        _require(
            self.proposed_status in INSPECTION_STATUSES,
            f"{fid}: inspection may not propose '{self.proposed_status}'",
        )
        if self.proposed_status in NO_PICK_STATUSES:
            _require(
                self.proposed_pick is None,
                f"{fid}: no pick may be recorded on {self.proposed_status} (rule 2)",
            )
        else:
            _require(
                self.proposed_pick is not None,
                f"{fid}: {self.proposed_status} requires a proposed_pick",
            )
            _require(
                self.proposed_pick in self.member_ids,
                f"{fid}: proposed_pick {self.proposed_pick} is not a member",
            )
        _require(
            len(self.evidence) >= 1, f"{fid}: at least one evidence record is required"
        )
        _require(
            len(self.note) <= 1000, f"{fid}: note must be 1000 characters or fewer"
        )
        if not self.execution_expected:
            _require(
                self.execution.apparent_status == "not-expected"
                and self.execution.dated == "not-expected",
                f"{fid}: execution not expected, so apparent_status and dated must be not-expected",
            )
        else:
            _require(
                self.execution.apparent_status != "not-expected",
                f"{fid}: execution expected, so apparent_status must be a finding, not not-expected",
            )
        # Findings are about the pick: execution and date evidence, and every
        # signature page, must name the proposed pick (a ledger record may
        # carry null). Evidence about another file is not evidence about this one.
        if self.proposed_pick is not None:
            for e in self.evidence:
                if e.claim in ("execution", "date"):
                    _require(
                        e.document_id == self.proposed_pick
                        or (e.document_id is None and e.source == "sigpack-ledger"),
                        f"{fid}: {e.claim} evidence cites a document that is not the pick "
                        f"({e.document_id} at {e.locator}); findings are about the pick",
                    )
            for p in self.execution.signature_pages:
                _require(
                    p.document_id == self.proposed_pick,
                    f"{fid}: signature page cites {p.document_id}, not the pick; findings are about the pick",
                )
        # Rule 1: appears-signed needs an execution evidence record from the
        # ledger or a look at the page — a label is not enough.
        if self.execution.apparent_status == "appears-signed":
            _require(
                self.has_execution_evidence(),
                f"{fid}: appears-signed without execution evidence from the sigpack ledger "
                "or visual inspection (status-taxonomy.md rule 1)",
            )
        # Rule 3: a date is something that was read, on the page or in the ledger.
        if self.execution.dated == "dated":
            _require(
                any(
                    e.claim == "date" and e.source in EXECUTION_EVIDENCE_SOURCES
                    for e in self.evidence
                ),
                f"{fid}: dated without a date evidence record from the sigpack ledger or visual "
                "inspection (status-taxonomy.md rule 3)",
            )
        derived = self.derived_status()
        _require(
            self.proposed_status == derived,
            f"{fid}: proposed {self.proposed_status} but findings support {derived} "
            "(status-taxonomy.md derivation)",
        )

    def has_execution_evidence(self) -> bool:
        return any(
            e.claim == "execution" and e.source in EXECUTION_EVIDENCE_SOURCES
            for e in self.evidence
        )

    def derived_status(self) -> str:
        return derive_status(
            no_pick=self.proposed_status == "version-conflict",
            unreadable=self.proposed_status == "unreadable",
            execution_expected=self.execution_expected,
            apparent_status=self.execution.apparent_status,
            dated=self.execution.dated,
            missing_components=len(self.missing_components),
        )

    @classmethod
    def from_dict(cls, d: Any) -> FamilyInspection:
        where = f"inspection {d.get('family_id', '<no family_id>') if isinstance(d, dict) else '<not an object>'}"
        keys = {
            "family_id",
            "member_ids",
            "proposed_pick",
            "proposed_status",
            "execution_expected",
            "execution",
            "evidence",
            "missing_components",
            "note",
        }
        _fields(d, keys, keys, where)
        members = d["member_ids"]
        _require(
            isinstance(members, list) and all(isinstance(m, str) for m in members),
            f"{where}: member_ids must be a list of strings",
        )
        pick = d["proposed_pick"]
        _require(
            pick is None or isinstance(pick, str),
            f"{where}: proposed_pick must be a string or null",
        )
        _require(
            isinstance(d["execution_expected"], bool),
            f"{where}: execution_expected must be true or false",
        )
        _require(isinstance(d["evidence"], list), f"{where}: evidence must be a list")
        _require(
            isinstance(d["missing_components"], list),
            f"{where}: missing_components must be a list",
        )
        components = []
        for i, item in enumerate(d["missing_components"]):
            sub = f"{where}: missing_components[{i}]"
            _fields(
                item,
                {"component", "referenced_at"},
                {"component", "referenced_at"},
                sub,
            )
            components.append(
                MissingComponent(
                    component=_str(item, "component", sub),
                    referenced_at=_str(item, "referenced_at", sub),
                )
            )
        return cls(
            family_id=_str(d, "family_id", where),
            member_ids=tuple(members),
            proposed_pick=pick,
            proposed_status=_str(d, "proposed_status", where),
            execution_expected=d["execution_expected"],
            execution=ExecutionFinding.from_dict(d["execution"], f"{where}: execution"),
            evidence=tuple(
                Evidence.from_dict(e, f"{where}: evidence[{i}]")
                for i, e in enumerate(d["evidence"])
            ),
            missing_components=tuple(components),
            note=_str(d, "note", where),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "family_id": self.family_id,
            "member_ids": list(self.member_ids),
            "proposed_pick": self.proposed_pick,
            "proposed_status": self.proposed_status,
            "execution_expected": self.execution_expected,
            "execution": self.execution.to_dict(),
            "evidence": [e.to_dict() for e in self.evidence],
            "missing_components": [m.to_dict() for m in self.missing_components],
            "note": self.note,
        }


@dataclass
class Inspection:
    corpus_id: str
    families: list[FamilyInspection] = field(default_factory=list)
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require(
            self.schema_version == SCHEMA_VERSION,
            f"unsupported inspection schema_version: {self.schema_version}",
        )
        seen: set[str] = set()
        for fam in self.families:
            _require(
                fam.family_id not in seen, f"inspection lists {fam.family_id} twice"
            )
            seen.add(fam.family_id)

    @classmethod
    def from_dict(cls, d: Any) -> Inspection:
        """Strict: one bad family record rejects the whole file.

        Reconciliation uses `from_dict_lenient` so that one malformed record is
        counted and named while the rest are still read.
        """

        keys = {"schema_version", "corpus_id", "families"}
        _fields(d, keys, keys, "inspection")
        _require(isinstance(d["families"], list), "inspection: families must be a list")
        return cls(
            corpus_id=_str(d, "corpus_id", "inspection"),
            families=[FamilyInspection.from_dict(f) for f in d["families"]],
            schema_version=_str(d, "schema_version", "inspection"),
        )

    @classmethod
    def from_dict_lenient(
        cls, d: Any
    ) -> tuple[Inspection, list[tuple[str | None, str]]]:
        """Read every valid family record; return the rejected ones with reasons.

        Each rejection is `(family_id or None, reason)`. The caller counts them
        in `receipt.inspection.rejected` and names them in `exceptions.md`.
        """

        keys = {"schema_version", "corpus_id", "families"}
        _fields(d, keys, keys, "inspection")
        _require(isinstance(d["families"], list), "inspection: families must be a list")
        good: list[FamilyInspection] = []
        rejected: list[tuple[str | None, str]] = []
        seen: set[str] = set()
        for raw in d["families"]:
            try:
                rec = FamilyInspection.from_dict(raw)
            except ValueError as error:
                fid = raw.get("family_id") if isinstance(raw, dict) else None
                rejected.append((fid if isinstance(fid, str) else None, str(error)))
                continue
            # A family inspected twice: the first record stands, the second is
            # rejected and counted, not a reason to refuse the whole file.
            if rec.family_id in seen:
                rejected.append(
                    (
                        rec.family_id,
                        "listed twice in inspection.json; the first record was read "
                        "and this one rejected",
                    )
                )
                continue
            seen.add(rec.family_id)
            good.append(rec)
        return cls(
            corpus_id=_str(d, "corpus_id", "inspection"),
            families=good,
            schema_version=_str(d, "schema_version", "inspection"),
        ), rejected

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "corpus_id": self.corpus_id,
            "families": [f.to_dict() for f in self.families],
        }


# --------------------------------------------------------------------- index


@dataclass(frozen=True)
class ExecutionRecord:
    evidence_source: str = "none"
    apparent_status: str = "not-inspected"
    dated: str = "unclear"
    ledger_page_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require(
            self.evidence_source in EXECUTION_SOURCES,
            f"unsupported evidence_source: {self.evidence_source}",
        )
        _require(
            self.apparent_status in APPARENT_STATUSES,
            f"unsupported apparent_status: {self.apparent_status}",
        )
        _require(self.dated in DATED, f"unsupported dated value: {self.dated}")
        if self.evidence_source == "sigpack-ledger":
            _require(
                len(self.ledger_page_ids) >= 1,
                "the ledger as source must cite at least one page id",
            )
        else:
            _require(
                not self.ledger_page_ids,
                "ledger_page_ids may be cited only when the ledger is the source",
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_source": self.evidence_source,
            "apparent_status": self.apparent_status,
            "dated": self.dated,
            "ledger_page_ids": list(self.ledger_page_ids),
        }


@dataclass(frozen=True)
class IndexItem:
    item_id: str
    order: int
    title: str
    checklist_ref: str | None
    execution_expected: bool
    status: str
    family_id: str | None
    selected_id: str | None
    execution: ExecutionRecord
    parties: tuple[str, ...] = ()
    document_date: str | None = None
    start_page: int | None = None
    missing_components: tuple[str, ...] = ()
    qualification: str = ""

    def __post_init__(self) -> None:
        iid = self.item_id
        _require(bool(ITEM_ID.match(iid)), f"bad item_id: {iid}")
        _require(self.order >= 1, f"{iid}: order must be 1 or more")
        _require(bool(self.title.strip()), f"{iid}: title must not be empty")
        _require(
            self.status in ITEM_STATUSES,
            f"{iid}: '{self.status}' is not an index item status",
        )
        _require(
            len(self.qualification) <= 500,
            f"{iid}: qualification must be 500 characters or fewer",
        )
        _require(
            self.start_page is None or self.start_page >= 1,
            f"{iid}: start_page must be 1 or more",
        )
        if self.status in SELECTABLE_STATUSES:
            _require(
                self.selected_id is not None,
                f"{iid}: {self.status} requires a selected_id",
            )
        else:
            # Rule 2: a version-conflict never carries a selection; nor do
            # missing, unreadable or not-required.
            _require(
                self.selected_id is None,
                f"{iid}: no selected_id may be written on {self.status} (status-taxonomy.md rule 2)",
            )
        if self.status == "missing":
            _require(self.family_id is None, f"{iid}: missing has no family")
        elif self.status != "not-required":
            _require(
                self.family_id is not None, f"{iid}: {self.status} requires a family_id"
            )
        if self.status in ("ready", "not-required"):
            _require(
                not self.qualification.strip(),
                f"{iid}: {self.status} carries no qualification",
            )
        else:
            _require(
                bool(self.qualification.strip()),
                f"{iid}: {self.status} must say why in one line",
            )
        if not self.execution_expected:
            _require(
                self.execution.apparent_status == "not-expected"
                and self.execution.dated == "not-expected",
                f"{iid}: execution not expected, so apparent_status and dated must be not-expected",
            )
        # The derivation table, checked at the index for the inspected statuses.
        if self.status in SELECTABLE_STATUSES:
            derived = derive_status(
                no_pick=False,
                unreadable=False,
                execution_expected=self.execution_expected,
                apparent_status=self.execution.apparent_status,
                dated=self.execution.dated,
                missing_components=len(self.missing_components),
            )
            _require(
                self.status == derived,
                f"{iid}: status {self.status} but the execution record supports {derived}",
            )
        if self.status == "ready" and self.execution_expected:
            _require(
                self.execution.evidence_source in EXECUTION_EVIDENCE_SOURCES,
                f"{iid}: ready requires execution evidence from the ledger or inspection (rule 1)",
            )
        # Rule 3: a document date is something that was read on the page or in
        # the ledger; an item with no evidence source has no date to show.
        if self.document_date is not None:
            _require(
                self.execution.dated == "dated"
                and self.execution.evidence_source in EXECUTION_EVIDENCE_SOURCES,
                f"{iid}: document_date {self.document_date!r} without a dated finding "
                "from the ledger or inspection (status-taxonomy.md rule 3)",
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "order": self.order,
            "title": self.title,
            "parties": list(self.parties),
            "checklist_ref": self.checklist_ref,
            "execution_expected": self.execution_expected,
            "status": self.status,
            "family_id": self.family_id,
            "selected_id": self.selected_id,
            "document_date": self.document_date,
            "start_page": self.start_page,
            "execution": self.execution.to_dict(),
            "missing_components": list(self.missing_components),
            "qualification": self.qualification,
        }


# ------------------------------------------------------------------- receipt

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
SOURCE_KEYS = {
    "files",
    "distinct",
    "in_families",
    "duplicates",
    "unreadable",
    "skipped",
}
INSPECTION_KEYS = {"families", "inspected", "rejected"}
SIGPACK_KEYS = {"ledger_supplied", "ledger_current", "documents_cited"}
PACKAGE_KEYS = {
    "version",
    "folder",
    "prior_folder",
    "combined_pdf",
    "volumes",
    "conversions_unverified",
}
OUTPUT_KEYS = {
    "item_id",
    "status",
    "output",
    "pages_expected",
    "pages_included",
    "reconciled",
}


def outcome_for(
    by_status: dict[str, int], unexpected_families: int, sources: dict[str, int]
) -> str:
    """The receipt outcomes table in status-taxonomy.md."""

    if sources.get("in_families") != sources.get("distinct"):
        return "failed"
    if sources.get("unreadable", 0) > 0:
        return "failed"
    if by_status.get("missing", 0) or by_status.get("unreadable", 0):
        return "failed"
    if sum(by_status.values()) == 0:
        # An empty expected set is nothing to audit, not a clean closing.
        return "failed"
    not_ready = sum(
        v for k, v in by_status.items() if k not in ("ready", "not-required")
    )
    if not_ready or unexpected_families or sources.get("skipped", 0) > 0:
        return "qualified"
    return "complete"


@dataclass(frozen=True)
class Receipt:
    corpus_id: str
    mode: str
    index_approved: bool
    expected_items: int
    by_status: dict[str, int]
    unexpected_families: int
    sources: dict[str, int]
    inspection: dict[str, int]
    sigpack: dict[str, Any]
    as_of: str
    included_outputs: tuple[dict[str, Any], ...] = ()
    package: dict[str, Any] | None = None
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require(self.mode in MODES, f"unsupported mode: {self.mode}")
        _require(
            bool(DATE.match(self.as_of)), f"as_of must be YYYY-MM-DD, got {self.as_of}"
        )
        try:
            date.fromisoformat(self.as_of)
        except ValueError as error:
            raise ValueError(f"as_of is not a real date: {self.as_of}") from error
        _require(
            set(self.by_status) == set(RECEIPT_STATUSES),
            "by_status must carry every receipt status and nothing else",
        )
        _require(
            set(self.sources) == SOURCE_KEYS,
            f"sources must carry exactly {sorted(SOURCE_KEYS)}",
        )
        _require(
            set(self.inspection) == INSPECTION_KEYS,
            f"inspection must carry exactly {sorted(INSPECTION_KEYS)}",
        )
        _require(
            set(self.sigpack) == SIGPACK_KEYS,
            f"sigpack must carry exactly {sorted(SIGPACK_KEYS)}",
        )
        _require(self.unexpected_families >= 0, "unexpected_families must be 0 or more")
        # Rule 7: the receipt balances or it is not written.
        total = sum(self.by_status.values())
        _require(
            total == self.expected_items,
            f"receipt does not balance: {self.expected_items} expected items, {total} by status (rule 7)",
        )
        _require(
            self.sources["in_families"] == self.sources["distinct"],
            "receipt does not balance: every distinct source must sit in exactly one family (rule 7)",
        )
        _require(
            self.sources["duplicates"]
            == self.sources["files"] - self.sources["distinct"],
            "receipt does not balance: duplicates must equal files minus distinct (rule 7)",
        )
        # Rejected records are not capped by the family count: a stray record
        # for a family that is not in families.json, or a duplicate, is
        # counted and named (anchor A3), never a reason to refuse the run.
        _require(
            self.inspection["inspected"] <= self.inspection["families"],
            "inspected families exceed the number of families",
        )
        if self.mode == "audit":
            _require(
                not self.included_outputs and self.package is None,
                "audit mode assembles nothing; included_outputs must be empty and package null",
            )
        else:
            # assembly-rules.md rule 6: a build/update receipt names its package
            # and carries one reconciled row per plan entry.
            _require(
                isinstance(self.package, dict) and set(self.package) == PACKAGE_KEYS,
                f"{self.mode} receipt must carry package with exactly {sorted(PACKAGE_KEYS)}",
            )
            for row in self.included_outputs:
                _require(
                    set(row) == OUTPUT_KEYS,
                    f"included_outputs rows must carry exactly {sorted(OUTPUT_KEYS)}",
                )
                _require(
                    row["reconciled"]
                    == (row["pages_expected"] == row["pages_included"]),
                    f"{row['item_id']}: reconciled must state whether the page counts agree",
                )

    @property
    def outcome(self) -> str:
        base = outcome_for(self.by_status, self.unexpected_families, self.sources)
        if self.mode == "audit" or base == "failed":
            return base
        # assembly-rules.md rule 5 and 6: an unreconciled output fails; an
        # unverified conversion or a qualified inclusion keeps it from complete.
        if any(not row["reconciled"] for row in self.included_outputs):
            return "failed"
        package = self.package or {}
        if package.get("conversions_unverified", 0) or any(
            row["status"] != "ready" for row in self.included_outputs
        ):
            return "qualified"
        return base

    def line(self) -> str:
        parts = [f"{self.expected_items} expected"]
        parts += [f"{self.by_status[s]} {s}" for s in RECEIPT_STATUSES]
        parts.append(f"{self.unexpected_families} unexpected")
        return " · ".join(parts) + f" · {self.outcome.upper()}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "corpus_id": self.corpus_id,
            "mode": self.mode,
            "index_approved": self.index_approved,
            "expected_items": self.expected_items,
            "by_status": dict(self.by_status),
            "unexpected_families": self.unexpected_families,
            "sources": dict(self.sources),
            "inspection": dict(self.inspection),
            "sigpack": dict(self.sigpack),
            "package": dict(self.package) if self.package is not None else None,
            "included_outputs": [dict(o) for o in self.included_outputs],
            "outcome": self.outcome,
            "as_of": self.as_of,
        }
