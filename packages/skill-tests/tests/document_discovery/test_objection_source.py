"""Source accuracy checks and post-extraction integrity are different tests."""

import copy
import zipfile

import objection_source as source
import pytest
from test_objection_review import core
from test_objection_review import review as review


@pytest.mark.parametrize(
    "mutation", ["text", "label", "omit", "duplicate", "order", "context"]
)
def test_source_census_mutations_rejected(review, mutation):
    changed = copy.deepcopy(review)
    if mutation == "text":
        changed["requests"][0]["text"] += " Extra supplied language?"
    elif mutation == "label":
        changed["requests"][0]["label"] = "REQUEST FOR PRODUCTION NO. 999"
    elif mutation == "omit":
        changed["requests"].pop()
    elif mutation == "duplicate":
        changed["requests"].append(copy.deepcopy(changed["requests"][0]))
    elif mutation == "order":
        changed["requests"].reverse()
    else:
        changed["context"][0]["text"] += " Altered definition."
    assert changed["source"]["sha256"] == review["source"]["sha256"]
    with pytest.raises(ValueError, match="census differs|context changed"):
        core.render(changed)


def test_legacy_and_changed_frozen_census_rejected(review):
    legacy = copy.deepcopy(review)
    legacy["format_version"] = 1
    legacy.pop("source_census")
    with pytest.raises(ValueError, match="Legacy review"):
        core.render(legacy)
    review["source_census"]["requests"].pop()
    with pytest.raises(ValueError, match="census changed"):
        core.render(review)


def test_capture_verified_against_actual_source_not_just_claimed_hash(tmp_path):
    path = tmp_path / "served.md"
    path.write_text("REQUEST 4\n\nActual request.\n")
    captured = source.capture(path)
    source.verify_source(captured, path)
    captured["blocks"][1]["text"] = "Invented request under the same byte hash."
    with pytest.raises(ValueError, match="Captured text differs"):
        source.verify_source(captured, path)
    path.write_text("A different original.")
    with pytest.raises(ValueError, match="Original source file changed"):
        source.verify_source(captured, path)


def test_gaps_are_localized_and_cannot_claim_complete_capture(tmp_path):
    path = tmp_path / "served.md"
    path.write_text("RFP 4\n\nReadable request.\n\nAn unresolved source passage.\n")
    extraction = source.capture(path)
    mapping = {
        "requests": [
            {
                "id": "q4",
                "label_spans": [{"block": "b1"}],
                "text_spans": [{"block": "b2"}],
                "context_ids": [],
            }
        ],
        "context": [],
        "other": [],
    }
    comparison = {
        "status": "checked",
        "by": "source reviewer",
        "method": "original-text comparison",
        "notes": "One passage unresolved",
        "unresolved": [],
    }
    with pytest.raises(ValueError, match="partial coverage"):
        source.freeze(extraction, mapping, comparison)
    comparison["status"] = "partial"
    census = source.freeze(extraction, mapping, comparison)
    assert census["requests"][0]["text"] == "Readable request."
    assert census["gaps"][0]["text"] == "An unresolved source passage."
    source.census_check(census)


def test_span_overlap_rejected_and_duplicate_printed_numbers_preserved(review):
    census = review["source_census"]
    assert census["requests"][7]["label"] == census["requests"][8]["label"]
    assert census["requests"][7]["id"] != census["requests"][8]["id"]
    mapping = copy.deepcopy(census["mapping"])
    mapping["requests"][1]["text_spans"] = mapping["requests"][0]["text_spans"]
    with pytest.raises(ValueError, match="Overlapping"):
        source.freeze(census["extraction"], mapping, census["comparison"])


def test_inline_labels_and_multiline_request_spans(tmp_path):
    path = tmp_path / "served.txt"
    path.write_text(
        "Request 8: Produce contracts.\n\nInclude (a) amendments;\nand (b) exhibits."
    )
    extraction = source.capture(path)
    mapping = {
        "context": [],
        "other": [],
        "requests": [
            {
                "id": "occurrence-one",
                "label_spans": [{"block": "b1", "end": 10}],
                "text_spans": [{"block": "b1", "start": 11}, {"block": "b2"}],
                "context_ids": [],
            }
        ],
    }
    comparison = {
        "status": "checked",
        "by": "test",
        "method": "direct text comparison",
        "notes": "Exact spans",
        "unresolved": [],
    }
    census = source.freeze(extraction, mapping, comparison)
    assert census["requests"][0]["label"] == "Request 8:"
    assert (
        census["requests"][0]["text"]
        == "Produce contracts.\nInclude (a) amendments;\nand (b) exhibits."
    )


def test_supplemental_context_retained_separately(review):
    source.check_review_source(review)
    assert any(item["id"] == "facts" for item in review["context"])
    assert not any(item["id"] == "facts" for item in review["source_census"]["context"])


def test_attach_preserves_candidate_assessment_without_altering_source(review):
    review["requests"][0]["candidate_note"] = "No supported connection identified."
    review["requests"][5]["candidate_note"] = (
        "Conditional option; supporting facts open."
    )
    result = source.attach(review, review["source_census"])
    for before, after in zip(review["requests"], result["requests"], strict=True):
        assert before.get("candidate_note") == after.get("candidate_note")
        assert before["suggestions"] == after["suggestions"]
        assert before["text"] == after["text"]
    source.check_review_source(result)
    changed = copy.deepcopy(review)
    changed["requests"][0]["text"] += " Changed under the candidate note."
    with pytest.raises(ValueError, match="wording does not match"):
        source.attach(changed, review["source_census"])


def test_docx_capture_preserves_runs_and_reports_unsupported_numbering(tmp_path):
    path = tmp_path / "source.docx"
    xml = (
        '<w:document xmlns:w="http://schemas.openxmlformats.org/'
        'wordprocessingml/2006/main"><w:body><w:p><w:pPr><w:numPr/>'
        "</w:pPr><w:r><w:t>First </w:t></w:r><w:r><w:t>clause.</w:t>"
        "</w:r></w:p></w:body></w:document>"
    )
    with zipfile.ZipFile(path, "w") as package:
        package.writestr("word/document.xml", xml)
    captured = source.capture(path)
    assert captured["blocks"][0]["text"] == "First clause."
    assert any("Automatic numbering" in note for note in captured["limitations"])
    source.verify_source(captured, path)


def test_unknown_or_unbound_host_extraction_cannot_bypass_source_check(tmp_path):
    original = tmp_path / "served.md"
    original.write_text("Actual source request.")
    extraction = source.capture(original)
    extraction["blocks"][0]["text"] = "Invented source text."
    extraction["method"] = "unknown"
    with pytest.raises(ValueError, match="Unsupported extraction method"):
        source.verify_source(extraction, original)
    extraction["method"] = "host-text-extraction"
    with pytest.raises(ValueError, match="Retained host text"):
        source.verify_source(extraction, original)
    retained = tmp_path / "host.txt"
    retained.write_text("Host extracted source request.")
    extraction = source.capture(original, retained)
    source.verify_source(extraction, original, retained)
    retained.write_text("Changed host extraction.")
    with pytest.raises(ValueError, match="differs from retained"):
        source.verify_source(extraction, original, retained)


def test_reordered_context_spans_rejected(review):
    census = review["source_census"]
    mapping = copy.deepcopy(census["mapping"])
    block = mapping["context"][0]["spans"][0]["block"]
    mapping["context"][0]["spans"] = [
        {"block": block, "start": 10},
        {"block": block, "end": 10},
    ]
    with pytest.raises(ValueError, match="original source order"):
        source.freeze(census["extraction"], mapping, census["comparison"])
