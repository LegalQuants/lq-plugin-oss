"""Wave 2: `plan` (Gate 2), `build` and `update` against
references/assembly-rules.md. Everything runs in-process against the
`assemble` API so tool absences can be simulated; the CLI path is the matrix
rows 11/13/14/16.

Fictional throughout: Project Aurora, Northgate Holdings Limited selling to
Eastbridge Capital LP, closing 1 March 2026."""

from __future__ import annotations

import hashlib
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest
from cb_support import (
    AS_OF,
    BUYER,
    CLOSING_DATE_TEXT,
    SELLER,
    Audit,
    Bible,
    Folder,
    approve,
    checklist,
    cover,
    hash_tree,
    load,
    rec_not_expected,
    rec_signed,
    rec_unsigned,
    signed_page,
    write_audit_outputs,
    write_docx,
)
from closing_bible import assemble, models

SPA = "Share Purchase Agreement"
DL = "Disclosure Letter"
ESCROW = "Escrow Agreement"
SCHEDULE_1 = "Schedule 1"
MINUTES = "Board Minutes"

FORBIDDEN = ("validly executed", "duly executed", "due execution")


def _signed(
    folder: Folder,
    rel: str,
    title: str,
    *,
    date: str | None = CLOSING_DATE_TEXT,
    body_pages: int = 1,
) -> str:
    return folder.pdf(
        rel,
        [
            cover(title),
            *(["operative terms"] * body_pages),
            signed_page(party=SELLER, date=date)
            + "\n"
            + signed_page(party=BUYER, date=date),
        ],
    )


def _unsigned(folder: Folder, rel: str, title: str) -> str:
    return folder.pdf(
        rel,
        [
            cover(title),
            "operative terms",
            f"SIGNED by ______________\nfor and on behalf of {SELLER}\nDated: ______________",
        ],
    )


@pytest.fixture
def package_parent(tmp_path: Path) -> Path:
    path = tmp_path / "packages"
    path.mkdir()
    return path


def _three(folder: Folder) -> dict[str, str]:
    """SPA (signed, 3 pp.), Disclosure Letter (signed), Schedule 1 (unsigned by design)."""

    return {
        "spa": _signed(folder, "(Executed) Share Purchase Agreement.pdf", SPA),
        "dl": _signed(folder, "Disclosure Letter.pdf", DL, body_pages=2),
        "sch": folder.pdf("Schedule 1.pdf", ["SCHEDULE 1\nProperties"]),
    }


THREE_ROWS = [("1.1", SPA, True), ("1.2", DL, True), ("1.3", SCHEDULE_1, False)]


def folder_signed(folder: Folder, rel: str, title: str, body: str = "Body.") -> str:
    """A signed PDF in an arbitrary folder (the round-3 update test builds two)."""

    return folder.pdf(rel, [cover(title), body, signed_page(date=CLOSING_DATE_TEXT)])


def _three_records(ids: dict[str, str]) -> Any:
    def records(run: Audit) -> list[dict[str, Any]]:
        return [
            rec_signed(run.family_of(ids["spa"]), ids["spa"], page=3),
            rec_signed(run.family_of(ids["dl"]), ids["dl"], page=4),
            rec_not_expected(run.family_of(ids["sch"]), ids["sch"]),
        ]

    return records


def _mixed(folder: Folder) -> dict[str, str]:
    """A ready SPA, an unsigned escrow, a ready schedule — plus a missing row."""

    return {
        "spa": _signed(folder, "(Executed) Share Purchase Agreement.pdf", SPA),
        "escrow": _unsigned(folder, "Escrow Agreement.pdf", ESCROW),
        "sch": folder.pdf("Schedule 1.pdf", ["SCHEDULE 1\nProperties"]),
    }


MIXED_ROWS = [
    ("1.1", SPA, True),
    ("2.1", ESCROW, True),
    ("1.3", SCHEDULE_1, False),
    ("3.1", "Landlord Consent", True),
]


def _mixed_records(ids: dict[str, str]) -> Any:
    def records(run: Audit) -> list[dict[str, Any]]:
        return [
            rec_signed(run.family_of(ids["spa"]), ids["spa"], page=3),
            rec_unsigned(run.family_of(ids["escrow"]), ids["escrow"], page=3),
            rec_not_expected(run.family_of(ids["sch"]), ids["sch"]),
        ]

    return records


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _package_files(package: Path) -> set[str]:
    return {
        p.relative_to(package).as_posix() for p in package.rglob("*") if p.is_file()
    }


def _all_text(package: Path) -> str:
    return "\n".join(
        p.read_text(encoding="utf-8", errors="replace")
        for p in package.rglob("*")
        if p.is_file() and p.suffix in (".json", ".html", ".md")
    ).lower()


# ------------------------------------------------------------------ plan


def test_plan_orders_entries_and_names_every_exclusion(
    folder: Folder, out_dir: Path, package_parent: Path
) -> None:
    ids = _mixed(folder)
    bible = Bible(folder, out_dir, package_parent, checklist=checklist(MIXED_ROWS))
    result = bible.audit(_mixed_records(ids))
    assert result.receipt["outcome"] == "failed"  # Landlord Consent is missing

    plan = bible.plan(approved=False)
    assert plan["approved"] is False
    assert plan["include_qualified"] is False
    assert plan["package"] == {
        "version": 1,
        "folder": "closing-bible-v001",
        "prior_folder": None,
    }
    assert bible.run is not None
    assert plan["corpus_id"] == bible.run.corpus_id
    assert plan["index_sha256"] == assemble.index_sha256(
        load(out_dir / "closing-index.json")
    )
    assert [(e["order"], e["item_id"], e["title"]) for e in plan["entries"]] == [
        (1, "CB-001", SPA),
        (3, "CB-003", SCHEDULE_1),
    ]
    spa = plan["entries"][0]
    assert spa["source_id"] == ids["spa"]
    assert spa["source_path"] == "(Executed) Share Purchase Agreement.pdf"
    assert spa["output_name"] == "001 - Share Purchase Agreement.pdf"
    assert spa["conversion"] == "none"
    assert spa["execution_pages"] == [3]
    assert spa["qualification"] == ""
    assert plan["entries"][1]["execution_pages"] == []
    assert [(x["item_id"], x["status"], x["reason"]) for x in plan["excluded"]] == [
        ("CB-002", "unsigned", "qualified-not-included"),
        ("CB-004", "missing", "missing"),
    ]
    assert plan["volume_pages"] is None
    for key in (
        "schema_version",
        "corpus_id",
        "index_sha256",
        "approved",
        "include_qualified",
        "package",
        "entries",
        "excluded",
        "volume_pages",
    ):
        assert key in plan


def test_plan_include_qualified_carries_the_qualification(
    folder: Folder, out_dir: Path, package_parent: Path
) -> None:
    ids = _mixed(folder)
    bible = Bible(folder, out_dir, package_parent, checklist=checklist(MIXED_ROWS))
    bible.audit(_mixed_records(ids))
    plan = bible.plan(include_qualified=True, approved=False)
    assert plan["include_qualified"] is True
    assert [e["item_id"] for e in plan["entries"]] == ["CB-001", "CB-002", "CB-003"]
    escrow = plan["entries"][1]
    assert escrow["status"] == "unsigned"
    assert escrow["qualification"]  # one line, from the index
    assert escrow["execution_pages"] == [3]
    # missing / unreadable / version-conflict / not-required never enter.
    assert [(x["item_id"], x["reason"]) for x in plan["excluded"]] == [
        ("CB-004", "missing")
    ]


def test_plan_refuses_an_unapproved_index(
    folder: Folder, out_dir: Path, package_parent: Path
) -> None:
    ids = _three(folder)
    run = Audit(folder.root, checklist=checklist(THREE_ROWS))
    result = run.reconcile(_three_records(ids)(run))
    assert result.index["approved"] is False
    with pytest.raises(ValueError, match="not approved"):
        assemble.plan(
            result.index,
            result.plan,
            run.manifest,
            result.overview,
            package_parent=package_parent,
        )


def test_plan_version_is_one_above_the_highest_sibling(
    folder: Folder, out_dir: Path, package_parent: Path
) -> None:
    ids = _three(folder)
    bible = Bible(folder, out_dir, package_parent, checklist=checklist(THREE_ROWS))
    bible.audit(_three_records(ids))
    (package_parent / "closing-bible-v003").mkdir()
    (package_parent / "closing-bible-v003.partial").mkdir()  # a crashed run, ignored
    (package_parent / "notes").mkdir()
    plan = bible.plan(approved=False)
    assert plan["package"]["version"] == 4
    assert plan["package"]["folder"] == "closing-bible-v004"
    with pytest.raises(ValueError, match="volume_pages"):
        bible.plan(volume_pages=10)


# ---------------------------------------------------------- Gate 2 refusals


def _built_nothing(package_parent: Path) -> None:
    assert not any(
        p.name.startswith("closing-bible-v") for p in package_parent.iterdir()
    )


def test_build_refuses_an_unapproved_plan(
    folder: Folder, out_dir: Path, package_parent: Path
) -> None:
    ids = _three(folder)
    bible = Bible(folder, out_dir, package_parent, checklist=checklist(THREE_ROWS))
    bible.audit(_three_records(ids))
    plan = bible.plan(approved=False)
    before = hash_tree(folder.root)
    with pytest.raises(ValueError, match="not approved"):
        bible.build(plan)
    _built_nothing(package_parent)
    assert hash_tree(folder.root) == before


def test_build_refuses_when_the_index_moved(
    folder: Folder, out_dir: Path, package_parent: Path
) -> None:
    ids = _three(folder)
    bible = Bible(folder, out_dir, package_parent, checklist=checklist(THREE_ROWS))
    bible.audit(_three_records(ids))
    plan = bible.plan()
    index = load(out_dir / "closing-index.json")
    index["items"][0]["title"] = "Share Purchase Agreement (amended)"
    (out_dir / "closing-index.json").write_text(
        __import__("json").dumps(index, indent=2, sort_keys=True) + "\n"
    )
    with pytest.raises(ValueError, match="changed since the plan"):
        bible.build(plan)
    _built_nothing(package_parent)


def test_build_refuses_when_the_corpus_moved(
    folder: Folder, out_dir: Path, package_parent: Path
) -> None:
    ids = _three(folder)
    bible = Bible(folder, out_dir, package_parent, checklist=checklist(THREE_ROWS))
    bible.audit(_three_records(ids))
    plan = bible.plan()
    plan["corpus_id"] = "0000000000000000"
    with pytest.raises(ValueError, match="corpus"):
        bible.build(plan)
    _built_nothing(package_parent)


def test_build_refuses_an_existing_package_folder(
    folder: Folder, out_dir: Path, package_parent: Path
) -> None:
    ids = _three(folder)
    bible = Bible(folder, out_dir, package_parent, checklist=checklist(THREE_ROWS))
    bible.audit(_three_records(ids))
    plan = bible.plan()
    (package_parent / "closing-bible-v001").mkdir()
    sentinel = package_parent / "closing-bible-v001" / "keep.txt"
    sentinel.write_text("prior package, never modified")
    with pytest.raises(ValueError, match="already exists"):
        bible.build(plan)
    assert sentinel.read_text() == "prior package, never modified"
    assert _package_files(package_parent / "closing-bible-v001") == {"keep.txt"}


def test_build_refuses_a_package_inside_the_closing_folder(
    folder: Folder, out_dir: Path, tmp_path: Path
) -> None:
    ids = _three(folder)
    inside = folder.root / "bible"
    bible = Bible(
        folder, out_dir, tmp_path / "elsewhere", checklist=checklist(THREE_ROWS)
    )
    bible.audit(_three_records(ids))
    plan = bible.plan()
    before = hash_tree(folder.root)
    with pytest.raises(ValueError, match="inside the closing folder"):
        assemble.build(
            plan,
            root=folder.root,
            audit_dir=out_dir,
            package_parent=inside,
            as_of=AS_OF,
        )
    assert hash_tree(folder.root) == before
    assert not inside.exists()


def test_build_refuses_a_plan_that_enters_nothing(
    folder: Folder, out_dir: Path, package_parent: Path
) -> None:
    escrow = _unsigned(folder, "Escrow Agreement.pdf", ESCROW)
    bible = Bible(
        folder, out_dir, package_parent, checklist=checklist([("2.1", ESCROW, True)])
    )
    bible.audit(lambda run: [rec_unsigned(run.family_of(escrow), escrow, page=3)])
    plan = bible.plan()
    assert plan["entries"] == []
    with pytest.raises(ValueError, match="nothing enters the bible") as excinfo:
        bible.build(plan)
    assert "CB-001" in str(excinfo.value) and "include-qualified" in str(excinfo.value)
    _built_nothing(package_parent)


# -------------------------------------------------------- build, no pypdf


def test_build_without_pypdf_writes_the_indexed_set(
    folder: Folder, out_dir: Path, package_parent: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ids = _three(folder)
    bible = Bible(folder, out_dir, package_parent, checklist=checklist(THREE_ROWS))
    bible.audit(_three_records(ids))
    bible.plan()
    monkeypatch.setitem(
        sys.modules, "pypdf", None
    )  # `import pypdf` now raises ImportError
    before = hash_tree(folder.root)
    receipt, log, report = bible.build()
    assert hash_tree(folder.root) == before
    assert report is None
    package = bible.package(1)
    files = _package_files(package)
    assert files == {
        "closing-index.json",
        "closing-index.html",
        "execution-overview.json",
        "execution-overview.html",
        "source-manifest.json",
        "families.json",
        "selection-plan.json",
        "build-plan.json",
        "exceptions.md",
        "conversion-log.json",
        "closing-receipt.json",
        "indexed-set/001 - Share Purchase Agreement.pdf",
        "indexed-set/002 - Disclosure Letter.pdf",
        "indexed-set/003 - Schedule 1.pdf",
    }
    assert receipt["mode"] == "build"
    assert receipt["package"] == {
        "version": 1,
        "folder": "closing-bible-v001",
        "prior_folder": None,
        "combined_pdf": None,
        "volumes": [],
        "conversions_unverified": 0,
    }
    assert log["tools"]["pypdf"] is False and log["conversions"] == []
    assert [r["item_id"] for r in receipt["included_outputs"]] == [
        "CB-001",
        "CB-002",
        "CB-003",
    ]
    for row in receipt["included_outputs"]:
        assert row["output"].startswith("indexed-set/")
        assert row["reconciled"] is True
        assert row["pages_expected"] == row["pages_included"] is not None
    assert [r["pages_expected"] for r in receipt["included_outputs"]] == [3, 4, 1]
    # The indexed-set copies are the source bytes.
    assert _sha(package / "indexed-set/001 - Share Purchase Agreement.pdf") == _sha(
        folder.root / "(Executed) Share Purchase Agreement.pdf"
    )
    # No combined PDF, so no starting pages to claim.
    assert all(
        i["start_page"] is None for i in load(package / "closing-index.json")["items"]
    )
    # The outcome is models.Receipt's, not ours.
    expected = models.Receipt(
        corpus_id=receipt["corpus_id"],
        mode="build",
        index_approved=True,
        expected_items=3,
        by_status=receipt["by_status"],
        unexpected_families=0,
        sources=receipt["sources"],
        inspection=receipt["inspection"],
        sigpack=receipt["sigpack"],
        as_of=AS_OF,
        included_outputs=tuple(receipt["included_outputs"]),
        package=receipt["package"],
    ).outcome
    assert receipt["outcome"] == expected == "complete"
    assert load(package / "closing-receipt.json") == receipt
    html = (package / "closing-index.html").read_text()
    assert "<table>" in html and SPA in html and "Starting page" in html
    assert "<script" not in html and "http" not in html.replace("http://www.w3.org", "")
    for word in FORBIDDEN:
        assert word not in _all_text(package)


# ------------------------------------------------------- build, with pypdf


def _outline(reader: Any) -> list[tuple[int, str, int]]:
    out: list[tuple[int, str, int]] = []

    def walk(nodes: Any, depth: int) -> None:
        for node in nodes:
            if isinstance(node, list):
                walk(node, depth + 1)
            else:
                out.append(
                    (
                        depth,
                        str(node.title),
                        reader.get_destination_page_number(node) + 1,
                    )
                )

    walk(reader.outline, 0)
    return out


def test_build_with_pypdf_reconciles_pages_and_bookmarks(
    folder: Folder, out_dir: Path, package_parent: Path
) -> None:
    pypdf = pytest.importorskip("pypdf")
    ids = _three(folder)
    bible = Bible(folder, out_dir, package_parent, checklist=checklist(THREE_ROWS))
    bible.audit(_three_records(ids))
    bible.plan()
    before = hash_tree(folder.root)
    receipt, log, _ = bible.build()
    assert hash_tree(folder.root) == before
    package = bible.package(1)
    assert receipt["package"]["combined_pdf"] == "closing-bible.pdf"
    assert receipt["package"]["volumes"] == []
    assert receipt["outcome"] == "complete"
    assert log["tools"]["pypdf"] is True

    reader = pypdf.PdfReader(str(package / "closing-bible.pdf"))
    index = load(package / "closing-index.json")
    starts = {i["item_id"]: i["start_page"] for i in index["items"]}
    # Front matter first: index page, overview page, then the documents.
    front = [p.extract_text() for p in reader.pages[:2]]
    assert front[0].startswith("CLOSING INDEX") and front[1].startswith(
        "EXECUTION OVERVIEW"
    )
    assert starts == {"CB-001": 3, "CB-002": 6, "CB-003": 10}
    assert len(reader.pages) == 2 + 3 + 4 + 1
    rows = {r["item_id"]: r for r in receipt["included_outputs"]}
    assert (rows["CB-001"]["pages_expected"], rows["CB-001"]["pages_included"]) == (
        3,
        3,
    )
    assert (rows["CB-002"]["pages_expected"], rows["CB-002"]["pages_included"]) == (
        4,
        4,
    )
    assert rows["CB-001"]["output"] == (
        "indexed-set/001 - Share Purchase Agreement.pdf; closing-bible.pdf pp. 3-5"
    )
    assert all(r["reconciled"] for r in rows.values())
    assert _outline(reader) == [
        (0, "Closing index", 1),
        (0, "Execution overview", 2),
        (0, "001 - Share Purchase Agreement", 3),
        (1, "Execution", 5),
        (0, "002 - Disclosure Letter", 6),
        (1, "Execution", 9),
        (0, "003 - Schedule 1", 10),
    ]
    # Source pages are copied, never re-rendered: same content streams.
    for rel, item_id in (
        ("(Executed) Share Purchase Agreement.pdf", "CB-001"),
        ("Disclosure Letter.pdf", "CB-002"),
        ("Schedule 1.pdf", "CB-003"),
    ):
        source = pypdf.PdfReader(str(folder.root / rel))
        start = starts[item_id]
        for n, page in enumerate(source.pages):
            assert (
                reader.pages[start - 1 + n].get_contents().get_data()
                == page.get_contents().get_data()
            )
    # The package index page names every item and its page.
    assert "001 Share Purchase Agreement [ready] p. 3" in front[0].replace("  ", " ")
    for word in FORBIDDEN:
        assert word not in _all_text(package)


def test_build_splits_into_volumes_with_a_master_index(
    folder: Folder, out_dir: Path, package_parent: Path
) -> None:
    pypdf = pytest.importorskip("pypdf")
    rows = []
    ids = {}
    for n in range(1, 13):
        title = f"Ancillary Agreement {n:02d}"
        ids[title] = _signed(folder, f"(Executed) {title}.pdf", title, body_pages=8)
        rows.append((f"{n}", title, True))
    bible = Bible(folder, out_dir, package_parent, checklist=checklist(rows))
    bible.audit(
        lambda run: [rec_signed(run.family_of(i), i, page=10) for i in ids.values()]
    )
    plan = bible.plan(volume_pages=50)
    assert plan["volume_pages"] == 50
    receipt, _, _ = bible.build()
    package = bible.package(1)
    assert receipt["package"]["combined_pdf"] is None
    volumes = receipt["package"]["volumes"]
    assert volumes == sorted(p.name for p in package.glob("closing-bible-volume-*.pdf"))
    assert len(volumes) >= 3
    assert (package / "closing-bible-index.pdf").is_file()
    for name in volumes:
        reader = pypdf.PdfReader(str(package / name))
        assert len(reader.pages) <= 50
        assert _outline(reader)  # each volume carries its own outline
    first = pypdf.PdfReader(str(package / volumes[0]))
    assert first.pages[0].extract_text().startswith("CLOSING INDEX")
    master = (
        pypdf.PdfReader(str(package / "closing-bible-index.pdf"))
        .pages[0]
        .extract_text()
    )
    assert "MASTER INDEX" in master and "volume 02" in master
    starts = {
        i["item_id"]: i["start_page"]
        for i in load(package / "closing-index.json")["items"]
    }
    assert all(isinstance(s, int) and s >= 1 for s in starts.values())
    outputs = {r["item_id"]: r["output"] for r in receipt["included_outputs"]}
    assert "closing-bible-volume-01.pdf pp. " in outputs["CB-001"]
    assert any("closing-bible-volume-02.pdf" in o for o in outputs.values())
    assert receipt["outcome"] == "complete"


def test_qualified_inclusion_keeps_the_outcome_from_complete(
    folder: Folder, out_dir: Path, package_parent: Path
) -> None:
    ids = _mixed(folder)
    rows = [r for r in MIXED_ROWS if r[1] != "Landlord Consent"]
    bible = Bible(folder, out_dir, package_parent, checklist=checklist(rows))
    result = bible.audit(_mixed_records(ids))
    assert result.receipt["outcome"] == "qualified"
    bible.plan(include_qualified=True)
    receipt, _, _ = bible.build()
    escrow = [r for r in receipt["included_outputs"] if r["item_id"] == "CB-002"]
    assert escrow and escrow[0]["status"] == "unsigned" and escrow[0]["reconciled"]
    assert receipt["outcome"] == "qualified"
    package = bible.package(1)
    index = load(package / "closing-index.json")
    assert [i for i in index["items"] if i["item_id"] == "CB-002"][0]["qualification"]
    html = (package / "closing-index.html").read_text()
    assert "unsigned" in html
    assert "indexed-set/002 - Escrow Agreement.pdf" in _package_files(package)


def test_unreconciled_page_count_fails_the_receipt(
    folder: Folder, out_dir: Path, package_parent: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("pypdf")
    ids = _three(folder)
    bible = Bible(folder, out_dir, package_parent, checklist=checklist(THREE_ROWS))
    bible.audit(_three_records(ids))
    bible.plan()
    real = assemble.pdf_page_count
    monkeypatch.setattr(assemble, "pdf_page_count", lambda path: (real(path) or 0) + 1)
    receipt, _, _ = bible.build()
    rows = receipt["included_outputs"]
    assert all(r["pages_expected"] == r["pages_included"] + 1 for r in rows)
    assert all(r["reconciled"] is False for r in rows)
    assert receipt["outcome"] == "failed"


def test_build_refuses_when_a_source_changed_after_the_audit(
    folder: Folder, out_dir: Path, package_parent: Path
) -> None:
    ids = _three(folder)
    bible = Bible(folder, out_dir, package_parent, checklist=checklist(THREE_ROWS))
    bible.audit(_three_records(ids))
    plan = bible.plan()
    _signed(
        folder, "(Executed) Share Purchase Agreement.pdf", SPA, date=None
    )  # overwritten
    with pytest.raises(ValueError, match="no longer hashes"):
        bible.build(plan)
    _built_nothing(package_parent)
    assert not list(package_parent.glob("*.partial"))


# --------------------------------------------------------------- conversion


def _docx_folder(folder: Folder) -> dict[str, str]:
    spa = _signed(folder, "(Executed) Share Purchase Agreement.pdf", SPA)
    docx = write_docx(
        folder.root / "Board Minutes.docx",
        [
            "BOARD MINUTES",
            "Northgate Holdings Limited",
            "Resolved that the SPA be approved.",
        ],
    )
    return {
        "spa": spa,
        "docx": "sha256:" + hashlib.sha256(docx.read_bytes()).hexdigest()[:12],
    }


DOCX_ROWS = [("1.1", SPA, True), ("5.1", MINUTES, False)]


def _docx_records(ids: dict[str, str]) -> Any:
    def records(run: Audit) -> list[dict[str, Any]]:
        return [
            rec_signed(run.family_of(ids["spa"]), ids["spa"], page=3),
            rec_not_expected(run.family_of(ids["docx"]), ids["docx"]),
        ]

    return records


def test_word_without_soffice_stays_native_and_is_named(
    folder: Folder, out_dir: Path, package_parent: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ids = _docx_folder(folder)
    monkeypatch.setattr(assemble, "find_soffice", lambda: None)
    bible = Bible(folder, out_dir, package_parent, checklist=checklist(DOCX_ROWS))
    bible.audit(_docx_records(ids))
    plan = bible.plan()
    minutes = [e for e in plan["entries"] if e["item_id"] == "CB-002"][0]
    assert minutes["conversion"] == "unrenderable"
    assert minutes["output_name"] == "002 - Board Minutes.docx"
    receipt, log, _ = bible.build()
    package = bible.package(1)
    files = _package_files(package)
    assert "indexed-set/002 - Board Minutes.docx" in files
    assert "indexed-set/002 - Board Minutes.pdf" not in files
    assert log["tools"]["soffice"] is False
    [entry] = log["conversions"]
    assert set(entry) == {
        "item_id",
        "source_id",
        "source_path",
        "tool",
        "output",
        "pages_before",
        "pages_after",
        "verified",
        "note",
    }
    assert entry["source_path"] == "Board Minutes.docx" and entry["verified"] is False
    assert entry["tool"] is None and entry["output"] is None
    row = [r for r in receipt["included_outputs"] if r["item_id"] == "CB-002"][0]
    assert row["output"].startswith("indexed-set/002 - Board Minutes.docx")
    assert "not in the combined PDF" in row["output"]
    assert row["pages_expected"] is None and row["pages_included"] is None
    assert row["reconciled"] is True
    assert receipt["package"]["conversions_unverified"] == 1
    assert (
        receipt["outcome"] == "qualified"
    )  # every item ready, but one document is not in the bible
    if receipt["package"]["combined_pdf"]:
        pypdf = pytest.importorskip("pypdf")
        titles = [
            t
            for _, t, _ in _outline(pypdf.PdfReader(str(package / "closing-bible.pdf")))
        ]
        assert "001 - Share Purchase Agreement" in titles and not any(
            "Board Minutes" in t for t in titles
        )


def test_word_conversion_is_logged_and_verified(
    folder: Folder, out_dir: Path, package_parent: Path
) -> None:
    if assemble.find_soffice() is None:
        pytest.skip("soffice not installed")
    if not shutil.which("pdftoppm"):
        pytest.skip("Poppler not installed; the render check cannot run")
    ids = _docx_folder(folder)
    bible = Bible(folder, out_dir, package_parent, checklist=checklist(DOCX_ROWS))
    bible.audit(_docx_records(ids))
    plan = bible.plan()
    assert [e["conversion"] for e in plan["entries"]] == ["none", "docx-to-pdf"]
    before = hash_tree(folder.root)
    receipt, log, _ = bible.build()
    assert hash_tree(folder.root) == before
    package = bible.package(1)
    files = _package_files(package)
    assert {
        "indexed-set/002 - Board Minutes.docx",
        "indexed-set/002 - Board Minutes.pdf",
    } <= files
    assert _sha(package / "indexed-set/002 - Board Minutes.docx") == _sha(
        folder.root / "Board Minutes.docx"
    )
    [entry] = log["conversions"]
    assert entry["tool"] == "soffice" and entry["verified"] is True
    assert entry["output"] == "indexed-set/002 - Board Minutes.pdf"
    assert entry["pages_after"] == 1 and entry["pages_before"] is None
    assert "1 of 1 rendered pages carry visible content" in entry["note"]
    assert "3 paragraphs" in entry["note"]
    assert receipt["package"]["conversions_unverified"] == 0
    row = [r for r in receipt["included_outputs"] if r["item_id"] == "CB-002"][0]
    assert row["pages_expected"] == row["pages_included"] == 1
    if receipt["package"]["combined_pdf"]:
        assert "closing-bible.pdf pp." in row["output"]
        assert receipt["outcome"] == "complete"


def test_failed_conversion_is_unverified_and_omitted(
    folder: Folder, out_dir: Path, package_parent: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ids = _docx_folder(folder)
    monkeypatch.setattr(assemble, "find_soffice", lambda: "/nonexistent/soffice")
    monkeypatch.setattr(assemble, "convert_word", lambda source, soffice, workdir: None)
    bible = Bible(folder, out_dir, package_parent, checklist=checklist(DOCX_ROWS))
    bible.audit(_docx_records(ids))
    plan = bible.plan()
    assert plan["entries"][1]["conversion"] == "docx-to-pdf"
    receipt, log, _ = bible.build()
    [entry] = log["conversions"]
    assert entry["tool"] == "soffice" and entry["verified"] is False
    assert entry["note"] == "conversion produced no PDF"
    assert "indexed-set/002 - Board Minutes.pdf" not in _package_files(bible.package(1))
    assert receipt["package"]["conversions_unverified"] == 1
    assert receipt["outcome"] == "qualified"


# -------------------------------------------------------------------- update


def test_update_writes_the_next_version_and_a_change_report(
    folder: Folder, out_dir: Path, package_parent: Path, tmp_path: Path
) -> None:
    # v001: SPA ready, escrow unsigned (included on instruction), schedule
    # ready, landlord consent missing.
    ids = _mixed(folder)
    bible = Bible(folder, out_dir, package_parent, checklist=checklist(MIXED_ROWS))
    bible.audit(_mixed_records(ids))
    bible.plan(include_qualified=True)
    receipt1, _, report1 = bible.build()
    assert report1 is None and receipt1["package"]["version"] == 1
    prior = bible.package(1)
    prior_hashes = hash_tree(prior)

    # Then: the landlord consent arrives (added), a signed escrow replaces the
    # unsigned one (replaced, status changed), and the lawyer drops Schedule 1
    # (removed). The SPA is unchanged. A late document changes the corpus, so
    # the prior approved index cannot be handed to reconcile (its decisions
    # were taken about other files); the audit re-runs from the same checklist
    # and the lawyer records the Gate 1 decisions again, the prior index as
    # the reference. Item ids come from the checklist, so they hold.
    consent = _signed(folder, "Landlord Consent.pdf", "Landlord Consent")
    (folder.root / "Escrow Agreement.pdf").unlink()
    escrow = _signed(folder, "(Executed) Escrow Agreement.pdf", ESCROW)

    def gate_1(index: dict[str, Any]) -> None:
        for item in index["items"]:
            if item["title"] == SCHEDULE_1:
                item["status"] = "not-required"
                item["selected_id"] = None
                item["qualification"] = "deal team confirmed the schedule is superseded"

    def records(run: Audit) -> list[dict[str, Any]]:
        return [
            rec_signed(run.family_of(ids["spa"]), ids["spa"], page=3),
            rec_signed(run.family_of(escrow), escrow, page=3),
            rec_not_expected(run.family_of(ids["sch"]), ids["sch"]),
            rec_signed(run.family_of(consent), consent, page=3),
        ]

    out2 = tmp_path / "out2"
    bible2 = Bible(folder, out2, package_parent, checklist=checklist(MIXED_ROWS))
    result2 = bible2.audit(records, adjust=gate_1)
    assert result2.item("Landlord Consent")["status"] == "ready"
    assert result2.item(ESCROW)["status"] == "ready"
    assert result2.item(SCHEDULE_1)["status"] == "not-required"
    plan2 = bible2.plan(prior="closing-bible-v001")
    assert plan2["package"] == {
        "version": 2,
        "folder": "closing-bible-v002",
        "prior_folder": "closing-bible-v001",
    }
    before = hash_tree(folder.root)
    receipt2, _, report = bible2.build()
    assert hash_tree(folder.root) == before
    assert hash_tree(prior) == prior_hashes  # the prior bible is preserved untouched
    assert receipt2["mode"] == "update"
    assert receipt2["package"]["version"] == 2
    assert receipt2["package"]["prior_folder"] == "closing-bible-v001"
    assert receipt2["outcome"] == "complete"
    new = bible2.package(2)
    assert report is not None
    assert (new / "change-report.md").read_text() == report
    assert report.splitlines()[0] == "# Change report — closing-bible-v002 against v001"
    sections = report.split("\n## ")
    by_name = {s.split("\n", 1)[0].strip(): s.split("\n", 1)[1] for s in sections[1:]}
    assert set(by_name) == {
        "Added",
        "Replaced",
        "Removed",
        "Status changed",
        "Unchanged",
    }
    assert "CB-004 Landlord Consent" in by_name["Added"]
    assert "Landlord Consent.pdf" in by_name["Added"] and consent in by_name["Added"]
    assert "CB-002 Escrow Agreement" in by_name["Replaced"]
    assert (
        f"({ids['escrow']}) → (Executed) Escrow Agreement.pdf ({escrow})"
        in by_name["Replaced"]
    )
    assert (
        "CB-003 Schedule 1" in by_name["Removed"]
        and "not-required" in by_name["Removed"]
    )
    assert "CB-002 Escrow Agreement: unsigned → ready" in by_name["Status changed"]
    assert by_name["Unchanged"].strip() == "1 item(s)"
    assert assemble.change_report(prior, new) == report


def test_update_refuses_a_missing_prior_package(
    folder: Folder, out_dir: Path, package_parent: Path
) -> None:
    ids = _three(folder)
    bible = Bible(folder, out_dir, package_parent, checklist=checklist(THREE_ROWS))
    bible.audit(_three_records(ids))
    with pytest.raises(ValueError, match="prior package"):
        bible.plan(prior="closing-bible-v001")


# ------------------------------------------------------------- zero mutation


def test_a_source_that_changes_mid_run_drops_the_package(
    folder: Folder, out_dir: Path, package_parent: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ids = _three(folder)
    bible = Bible(folder, out_dir, package_parent, checklist=checklist(THREE_ROWS))
    bible.audit(_three_records(ids))
    bible.plan()
    real = assemble._assemble

    def tampering(*args: Any, **kwargs: Any) -> Any:
        out = real(*args, **kwargs)
        (folder.root / "Schedule 1.pdf").write_bytes(b"%PDF-1.4 tampered")
        return out

    monkeypatch.setattr(assemble, "_assemble", tampering)
    with pytest.raises(assemble.SourceMutated):
        bible.build()
    _built_nothing(package_parent)
    assert not list(package_parent.glob("*.partial"))


def test_write_audit_outputs_round_trip_hash(folder: Folder, out_dir: Path) -> None:
    """The plan's index hash is the hash of the canonical file reconcile writes."""

    ids = _three(folder)
    run = Audit(folder.root, checklist=checklist(THREE_ROWS))
    result = run.reconcile(_three_records(ids)(run))
    approved = approve(result.index)
    result = run.reconcile(_three_records(ids)(run), index=approved)
    write_audit_outputs(run, result, out_dir)
    on_disk = (out_dir / "closing-index.json").read_bytes()
    assert hashlib.sha256(on_disk).hexdigest() == assemble.index_sha256(result.index)


# ------------------------------------------------- round 3 (single probe)
# Adversarial regression — three confirmed
# defects on the wave 2 path. Each pins the behaviour the contract now
# requires; none may be weakened.


def test_r3_exclusion_list_may_never_show_fewer_than_the_index(
    folder: Folder, out_dir: Path, package_parent: Path
) -> None:
    """Gate 2 is where the lawyer sees what will not enter the bible. A plan
    whose exclusion list has been emptied is refused, so the record of what was
    approved can never be shorter than the truth."""

    ids = _mixed(folder)
    bible = Bible(folder, out_dir, package_parent, checklist=checklist(MIXED_ROWS))
    bible.audit(_mixed_records(ids))
    plan = bible.plan()
    assert any(x["status"] == "missing" for x in plan["excluded"])
    plan["excluded"] = []
    with pytest.raises(ValueError, match="exclusion list omits.*CB-004"):
        bible.build(plan)
    _built_nothing(package_parent)


def test_r3_exclusion_reason_may_not_be_rewritten(
    folder: Folder, out_dir: Path, package_parent: Path
) -> None:
    """A missing item relabelled as not-required in the plan is refused: the
    approved index decides why an item stays out."""

    ids = _mixed(folder)
    bible = Bible(folder, out_dir, package_parent, checklist=checklist(MIXED_ROWS))
    bible.audit(_mixed_records(ids))
    plan = bible.plan()
    row = next(x for x in plan["excluded"] if x["status"] == "missing")
    row["status"] = "not-required"
    row["reason"] = "not-required"
    with pytest.raises(ValueError, match="the approved index says"):
        bible.build(plan)
    _built_nothing(package_parent)


def test_r3_update_refuses_a_prior_package_from_another_closing(
    tmp_path: Path, package_parent: Path
) -> None:
    """A change report across two different closings would assert continuity
    that does not exist — Aurora's SPA "replaced by" Borealis's APA. The prior
    package must be the same corpus."""

    def one(name: str, spa_title: str, sch_title: str, body: str) -> Bible:
        f = Folder(tmp_path / name)
        out = tmp_path / f"out-{name}"
        out.mkdir()
        ids = {
            "spa": folder_signed(f, f"(Executed) {spa_title}.pdf", spa_title, body),
            "sch": f.pdf(f"{sch_title}.pdf", [f"{sch_title.upper()}\n{name}"]),
        }
        rows = [("1.1", spa_title, True), ("1.3", sch_title, False)]
        bible = Bible(f, out, package_parent, checklist=checklist(rows))

        def records(run: Audit) -> list[dict[str, Any]]:
            return [
                rec_signed(run.family_of(ids["spa"]), ids["spa"], page=3),
                rec_not_expected(run.family_of(ids["sch"]), ids["sch"]),
            ]

        bible.audit(records)
        return bible

    aurora = one("aurora", SPA, SCHEDULE_1, "Aurora terms.")
    aurora.build(aurora.plan())
    borealis = one("borealis", "Asset Purchase Agreement", "Schedule 2", "Borealis.")
    plan = borealis.plan(prior="closing-bible-v001")
    with pytest.raises(ValueError, match="not a prior version of this closing"):
        borealis.build(plan)


def test_r3_a_staging_folder_it_did_not_write_is_never_deleted(
    folder: Folder, out_dir: Path, package_parent: Path
) -> None:
    """`closing-bible-vNNN.partial` beside the closing folder may be a crashed
    run — or a lawyer's own folder. The skill refuses rather than deleting it."""

    ids = _three(folder)
    bible = Bible(folder, out_dir, package_parent, checklist=checklist(THREE_ROWS))
    bible.audit(_three_records(ids))
    stale = package_parent / "closing-bible-v001.partial"
    stale.mkdir()
    keep = stale / "counsel-notes.md"
    keep.write_text("working notes\n", encoding="utf-8")
    with pytest.raises(ValueError, match="never deletes a folder it did not write"):
        bible.build(bible.plan())
    assert keep.read_text(encoding="utf-8") == "working notes\n"
    assert not (package_parent / "closing-bible-v001").exists()
