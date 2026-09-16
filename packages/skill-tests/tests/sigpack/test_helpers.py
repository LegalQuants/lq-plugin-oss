"""Unit pins for sigpack mechanics: staging, hostile filenames, ledger selection."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
# The skill lives under a practice folder since the plugin split; find it by name.
SCRIPT = next(ROOT.glob("skills/**/sigpack/scripts/sigpack.py"))

pytest.importorskip("pypdf")  # sigpack.py exits at import without it


def _load():
    spec = importlib.util.spec_from_file_location("sigpack", SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["sigpack"] = mod
    spec.loader.exec_module(mod)
    return mod


def _blank_pdf(
    path: Path,
    width: float = 612,
    height: float = 792,
    pages: int = 1,
    marker: bytes = b"",
) -> None:
    """A valid PDF of blank pages. `marker` makes the content stream unique —
    sheet_hash is content-based, so two byte-identical blank pages would read
    as duplicates of each other."""
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, NameObject

    w = PdfWriter()
    for _ in range(pages):
        page = w.add_blank_page(width=width, height=height)
        if marker:
            stream = DecodedStreamObject()
            stream.set_data(b"%" + marker)  # a comment line: valid, inert content
            page[NameObject("/Contents")] = stream
    with open(path, "wb") as fh:
        w.write(fh)


def _page_width(pdf: Path, page1: int) -> float:
    from pypdf import PdfReader

    return float(PdfReader(str(pdf)).pages[page1 - 1].mediabox.width)


def _one_page_ledger(exec_dir: Path) -> dict:
    """A one-block ledger over a two-page Doc.pdf; page 2 is the signature page."""
    return {
        "matter": "unit",
        "created": "2026-09-05",
        "closing_date": None,
        "execution_dir": str(exec_dir),
        "returned_dirs": [],
        "signature_pages": [
            {
                "id": "D-p2",
                "file": "Doc.pdf",
                "page": 2,
                "agreement": "Deed",
                "footer": None,
                "version_marker": None,
                "reserved": False,
                "esig_separator": False,
                "blocks": [
                    {
                        "block": 1,
                        "party": "ACME",
                        "signatory": "A. Signer",
                        "capacity": "Director",
                        "signatures": [],
                        "signatures_required": 1,
                        "date_field": False,
                        "copies_required": 1,
                        "status": "sent",
                        "returned": [],
                    }
                ],
            }
        ],
        "packs_sent": [],
        "returned_pages": [],
        "unmatched_returns": [],
        "receipt": {},
    }


def _returned_page(pack: str, batch: Path, **fields) -> dict:
    """One signed registry entry as `read` plus a model verdict would leave it."""
    rec = {
        "pack": pack,
        "page": 1,
        "batch": str(batch),
        "scanned": False,
        "text_source": "native",
        "footer_agreement": "Deed",
        "footer_party": "ACME",
        "version_marker": None,
        "esign_artifact": False,
        "sheet_hash": None,
        "render": None,
        "agreement": "Deed",
        "party": "ACME",
        "execution": "signed",
        "printed_name": "A. Signer",
        "dated": None,
        "text_preview": "",
    }
    rec.update(fields)
    return rec


def test_staged_moves_files_only_on_success(tmp_path: Path) -> None:
    sp = _load()
    out = tmp_path / "out"
    with sp.staged(out, "one") as stage:
        (stage / "a.png").write_bytes(b"a")
        (stage / "b.png").write_bytes(b"b")
        assert not (out / "a.png").exists()
    assert sorted(p.name for p in out.iterdir()) == ["a.png", "b.png"]


def test_staged_leaves_nothing_on_failure(tmp_path: Path) -> None:
    sp = _load()
    out = tmp_path / "out"
    with pytest.raises(RuntimeError):
        with sp.staged(out, "two") as stage:
            (stage / "a.png").write_bytes(b"a")
            raise RuntimeError("page 2 exploded")
    assert list(out.iterdir()) == []


def test_clear_staging_removes_only_staging_dirs(tmp_path: Path) -> None:
    sp = _load()
    out = tmp_path / "out"
    (out / ".staging-old").mkdir(parents=True)
    (out / "keep.png").write_bytes(b"k")
    assert sp.clear_staging(out) == 1
    assert [p.name for p in out.iterdir()] == ["keep.png"]


@pytest.mark.skipif(
    os.name == "nt", reason="POSIX pins: ':' and '\\' are illegal in Windows filenames"
)
def test_special_filenames_round_trip(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A community report against an older build had a colon-named file register
    but break `status` later. Pin the POSIX round-trip: raw names land in the
    ledger and every later lookup resolves by plain join."""
    sp = _load()
    exec_dir = tmp_path / "execution"
    exec_dir.mkdir()
    names = ["A:B.pdf", "C\\D.pdf"]
    for name in names:
        _blank_pdf(exec_dir / name)
    candidates = tmp_path / "candidates.json"
    sp.main(
        ["scan", str(exec_dir), "--out", str(candidates), "--workspace", str(tmp_path)]
    )
    scanned = {d["file"] for d in json.loads(candidates.read_text())["documents"]}
    assert scanned == set(names)

    classified = tmp_path / "classified.json"
    classified.write_text(
        json.dumps(
            {
                "signature_pages": [
                    {
                        "file": name,
                        "page": 1,
                        "agreement": agreement,
                        "blocks": [
                            {
                                "party": party,
                                "signatory": "A. Signer",
                                "capacity": "Director",
                            }
                        ],
                    }
                    for name, agreement, party in (
                        ("A:B.pdf", "Side Letter", "ACME"),
                        ("C\\D.pdf", "Joinder", "BLUECO"),
                    )
                ]
            }
        )
    )
    ledger = tmp_path / "sigpack.ledger.json"
    sp.main(
        [
            "init",
            "--ledger",
            str(ledger),
            "--execution",
            str(exec_dir),
            "--classified",
            str(classified),
            "--matter",
            "names",
        ]
    )
    led = json.loads(ledger.read_text())
    assert {p["file"] for p in led["signature_pages"]} == set(names)

    returned = tmp_path / "returned"
    returned.mkdir()
    packs = ["(Signed) P:Q.pdf", "(Signed) R\\S.pdf"]
    for pack in packs:
        _blank_pdf(returned / pack, width=500, height=500, marker=pack.encode())
    sp.main(["read", "--ledger", str(ledger), "--returned", str(returned)])
    led = json.loads(ledger.read_text())
    assert {r["pack"] for r in led["returned_pages"]} == set(packs)
    fill = {
        "(Signed) P:Q.pdf": ("Side Letter", "ACME"),
        "(Signed) R\\S.pdf": ("Joinder", "BLUECO"),
    }
    for r in led["returned_pages"]:
        r["execution"] = "signed"
        r["agreement"], r["party"] = fill[r["pack"]]
    ledger.write_text(json.dumps(led))

    capsys.readouterr()  # drop scan/init/read output; status must stand alone
    sp.main(["status", "--ledger", str(ledger)])
    assert "NOT COMPLETE" in capsys.readouterr().out

    out_dir = tmp_path / "executed"
    sp.main(["compile", "--ledger", str(ledger), "--out-dir", str(out_dir)])
    led = json.loads(ledger.read_text())
    assert led["receipt"]["complete"] is True
    for p in led["signature_pages"]:
        executed = out_dir / f"(Executed) {p['file']}"
        assert executed.exists()
        chosen = [x for x in p["blocks"][0]["returned"] if x.get("chosen")]
        assert len(chosen) == 1
        assert chosen[0]["placed_in"].endswith(f"{p['file']}#1")
        # the colon/backslash-named pack was found by name and its sheet placed
        assert _page_width(executed, 1) == 500

    capsys.readouterr()
    sp.main(["status", "--ledger", str(ledger)])
    assert "COMPLETE" in capsys.readouterr().out


def test_wrong_version_first_is_never_chosen(tmp_path: Path) -> None:
    """The eval pins valid-then-stale (a signed block is never downgraded); pin the
    reverse ordering: a wrong-version sheet that arrives FIRST is quarantined and
    never chosen, and the valid sheet that follows it is the one placed."""
    sp = _load()
    exec_dir = tmp_path / "execution"
    exec_dir.mkdir()
    _blank_pdf(exec_dir / "Doc.pdf", pages=2)
    ledger = tmp_path / "sigpack.ledger.json"
    led = _one_page_ledger(exec_dir)
    led["signature_pages"][0]["version_marker"] = "12345678-v3"
    out_dir = tmp_path / "executed"

    stale_batch = tmp_path / "batch-stale"
    stale_batch.mkdir()
    _blank_pdf(stale_batch / "old.pdf", width=500, height=500)
    led["returned_dirs"].append(str(stale_batch))
    led["returned_pages"].append(
        _returned_page("old.pdf", stale_batch, version_marker="12345678-v2")
    )
    ledger.write_text(json.dumps(led))
    sp.main(["compile", "--ledger", str(ledger), "--out-dir", str(out_dir)])

    led = json.loads(ledger.read_text())
    block = led["signature_pages"][0]["blocks"][0]
    assert block["status"] == "wrong-version"
    assert len(block["returned"]) == 1
    assert block["returned"][0]["chosen"] is False
    assert block["returned"][0]["placed_in"] is None
    assert led["returned_pages"][0]["outcome"] == "wrong-version"
    report = json.loads((out_dir / "compile-report.json").read_text())
    assert len(report["rejected"]) == 1
    assert report["placed_now"] == 0
    assert led["receipt"]["blocks_wrong_version"] == 1
    assert led["receipt"]["complete"] is False
    # the original unsigned page stays in the slot; the stale sheet is not placed
    assert _page_width(out_dir / "(Executed) Doc.pdf", 2) == 612

    valid_batch = tmp_path / "batch-valid"
    valid_batch.mkdir()
    _blank_pdf(valid_batch / "new.pdf", width=700, height=700)
    led["returned_dirs"].append(str(valid_batch))
    led["returned_pages"].append(
        _returned_page("new.pdf", valid_batch, version_marker="12345678-v3")
    )
    ledger.write_text(json.dumps(led))
    sp.main(["compile", "--ledger", str(ledger), "--out-dir", str(out_dir)])

    led = json.loads(ledger.read_text())
    block = led["signature_pages"][0]["blocks"][0]
    assert block["status"] == "signed"
    stale, valid = block["returned"]
    assert stale["pack"] == "old.pdf"
    assert stale["chosen"] is False
    assert stale["placed_in"] is None
    assert valid["pack"] == "new.pdf"
    assert valid["chosen"] is True
    assert valid["placed_in"].endswith("Doc.pdf#2")
    assert _page_width(out_dir / "(Executed) Doc.pdf", 2) == 700
    assert led["receipt"]["complete"] is True
    report = json.loads((out_dir / "compile-report.json").read_text())
    assert report["placed_now"] == 1
    assert report["rejected"] == []


def test_legacy_placed_in_migrates_to_chosen(tmp_path: Path) -> None:
    """Pre-`chosen` ledgers recorded placement at match time in `placed_in`.
    Compile migrates such a return to the modern shape: chosen=True, the stale
    address cleared, and the writer records the address it actually wrote."""
    sp = _load()
    exec_dir = tmp_path / "execution"
    exec_dir.mkdir()
    _blank_pdf(exec_dir / "Doc.pdf", pages=2)
    batch = tmp_path / "batch"
    batch.mkdir()
    _blank_pdf(batch / "old.pdf", width=500, height=500)
    ledger = tmp_path / "sigpack.ledger.json"
    led = _one_page_ledger(exec_dir)
    block = led["signature_pages"][0]["blocks"][0]
    block["status"] = "signed"
    block["returned"].append(
        {
            "pack": "old.pdf",
            "page": 1,
            "batch": str(batch),
            "execution": "signed",
            "printed_name_matches": True,
            "dated": None,
            "sheet_hash": None,
            # legacy shape: placed_in written at match time, no `chosen` key
            "placed_in": "(Executed) Doc.pdf#9",
            "spare": False,
        }
    )
    led["returned_dirs"].append(str(batch))
    ledger.write_text(json.dumps(led))

    out_dir = tmp_path / "executed"
    sp.main(["compile", "--ledger", str(ledger), "--out-dir", str(out_dir)])

    led = json.loads(ledger.read_text())
    (migrated,) = led["signature_pages"][0]["blocks"][0]["returned"]
    assert migrated["chosen"] is True
    # the bogus legacy address was cleared; the writer recorded the real one
    assert "#9" not in migrated["placed_in"]
    assert migrated["placed_in"].endswith("Doc.pdf#2")
    assert _page_width(out_dir / "(Executed) Doc.pdf", 2) == 500
    assert led["receipt"]["complete"] is True
