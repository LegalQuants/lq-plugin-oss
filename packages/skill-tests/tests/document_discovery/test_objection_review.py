import copy
import importlib.util
import json
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any

import pytest
from public_fixture import upgrade

ROOT = Path(__file__).resolve().parents[4]
SCRIPTS = ROOT / "skills/litigation/document-discovery/scripts"


def load(name, path=None):
    spec = importlib.util.spec_from_file_location(name, path or SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


core = load("objection_review")
word = load("objection_word")


@pytest.fixture
def review():
    inputs = ROOT / "packages/skill-tests/tests/document_discovery/fixtures"
    return upgrade(core.read(inputs / "review.json"), inputs / "served-requests.md")


def decisions(review):
    rows: list[dict[str, Any]] = []
    entries = core.indexed(review["library"]["entries"])
    for request in review["requests"]:
        choices = []
        for s in request["suggestions"]:
            if s["preselected"]:
                choices.append(
                    {
                        "component_id": request["id"] + ":" + s["entry_id"],
                        "entry_id": s["entry_id"],
                        "params": copy.deepcopy(s["params"]),
                        "wording": core.wording(entries[s["entry_id"]], s["params"]),
                        "edited": False,
                        "scope": "",
                        "notes": "",
                    }
                )
        rows.append(
            {
                "request_id": request["id"],
                "state": "reviewed",
                "action": {"kind": "individual", "at": "synthetic-test-action"},
                "notes": "",
                "choices": choices,
                "drafts": choices,
                "selected_ids": [choice["component_id"] for choice in choices],
            }
        )
    for row in rows:
        row["action"]["reviewed_content_sha256"] = core.digest(
            core.reviewed_content(review, row)
        )
    return {
        "kind": "objection-selections",
        "format_version": 2,
        "purpose": "assembly",
        "review_id": review["id"],
        "review_sha256": core.digest(review),
        "source_sha256": review["source"]["sha256"],
        "library_sha256": core.digest(review["library"]),
        "rows": rows,
    }


def test_exact_choices_and_partial_work(review):
    selections = decisions(review)
    selections["rows"][1]["state"] = "not_reviewed"
    selections["rows"][1]["action"] = None
    assembly = core.materialize(review, selections)
    assert assembly["requests"][0]["components"] == []
    assert not assembly["requests"][0]["open_review"]
    assert assembly["requests"][1]["components"] == []
    assert assembly["requests"][1]["open_review"]
    assert (
        assembly["requests"][3]["objection_text"]
        == selections["rows"][3]["choices"][0]["wording"]
    )
    assert assembly["requests"][7]["label"] == assembly["requests"][8]["label"]
    assert assembly["requests"][7]["id"] != assembly["requests"][8]["id"]


@pytest.mark.parametrize(
    "key", ["review_sha256", "library_sha256", "source_sha256", "review_id"]
)
def test_wrong_binding_rejected(review, key):
    selections = decisions(review)
    selections[key] = "wrong"
    with pytest.raises(ValueError):
        core.materialize(review, selections)


def test_progress_is_not_decisions(review):
    selections = decisions(review)
    selections["purpose"] = "progress"
    with pytest.raises(ValueError, match="Progress"):
        core.materialize(review, selections)


def test_explicit_wording_edit_preserved(review):
    selections = decisions(review)
    choice = selections["rows"][1]["choices"][0]
    choice["wording"] += " Additional request-specific qualification."
    with pytest.raises(ValueError, match="Changed library wording"):
        core.materialize(review, selections)
    choice["edited"] = True
    row = selections["rows"][1]
    row["action"]["reviewed_content_sha256"] = core.digest(
        core.reviewed_content(review, row)
    )
    assert (
        core.materialize(review, selections)["requests"][1]["objection_text"]
        == choice["wording"]
    )


def test_order_and_one_off(review):
    selections = decisions(review)
    row = selections["rows"][12]
    row["choices"].reverse()
    row["choices"].append(
        {
            "component_id": "one-off",
            "entry_id": None,
            "params": {},
            "wording": "A reviewed one-off.",
            "edited": True,
            "scope": "",
            "notes": "",
        }
    )
    row["selected_ids"] = [choice["component_id"] for choice in row["choices"]]
    row["action"]["reviewed_content_sha256"] = core.digest(
        core.reviewed_content(review, row)
    )
    result = core.materialize(review, selections)
    assert result["requests"][12]["objection_text"] == "\n\n".join(
        c["wording"] for c in row["choices"]
    )


def test_missing_facts_are_visible_without_preventing_lawyer_review(review):
    review["requests"][5]["suggestions"][0]["preselected"] = True
    html = core.render(review)
    assert review["requests"][5]["suggestions"][0]["missing"]
    assert "Check conditions" in html
    row = decisions(review)["rows"][5]
    assert row["choices"]
    assert "not_reviewed" in html


def test_surfaced_candidates_do_not_select_wording_or_depend_on_source_number(review):
    request = review["requests"][5]
    candidate = request["suggestions"][0]
    candidate["preselected"] = False
    request["candidate_note"] = "A conditional connection; the predicate remains open."
    entry = core.indexed(review["library"]["entries"])[candidate["entry_id"]]
    entry["sources"] = [{"source_id": "synthetic-precedent", "locator": "Response 927"}]
    core.review_check(review)
    row = decisions(review)["rows"][5]
    assert row["choices"] == []
    assert (
        core.materialize(review, decisions(review))["requests"][5]["objection_text"]
        == ""
    )


@pytest.mark.parametrize("note", [None, [], ""])
def test_candidate_note_is_text_when_supplied(review, note):
    review["requests"][0]["candidate_note"] = note
    with pytest.raises(ValueError, match="candidate assessment note"):
        core.review_check(review)


@pytest.mark.parametrize("field,value", [("basis", [None]), ("missing", [{}])])
def test_candidate_explanations_reject_corrupted_text_records(review, field, value):
    review["requests"][5]["suggestions"][0][field] = value
    with pytest.raises(ValueError, match="candidate basis|Missing inputs must be text"):
        core.review_check(review)


def test_request_review_requires_nonempty_approved_library(review):
    review["library"]["entries"] = []
    for request in review["requests"]:
        request["suggestions"] = []
    # The empty record remains a valid curation starter, not a request-review route.
    core.library_check(review["library"])
    with pytest.raises(ValueError, match="nonempty approved objection library"):
        core.render(review)
    with pytest.raises(ValueError, match="nonempty approved objection library"):
        core.materialize(review, decisions(review))


@pytest.mark.parametrize("approval", [None, "approved", {}, {"record": ""}])
def test_request_review_rejects_missing_or_malformed_approval_record(review, approval):
    review["library"]["entries"][0]["approval"] = approval
    with pytest.raises(ValueError, match="Approval must be|approval record"):
        core.render(review)


def test_pending_precedent_is_not_a_selectable_approved_entry(review):
    review["library"]["entries"][0]["status"] = "pending"
    with pytest.raises(ValueError, match="Only approved entries"):
        core.render(review)


def test_supplied_approved_snapshot_is_reused_without_relabeling(review):
    before = copy.deepcopy(review["library"])
    core.render(review)
    assert review["library"] == before
    # Existing duplicate variant declarations are not silently rewritten or
    # treated as proof that the underlying wording is semantically equivalent.
    declared = [(entry["family"], entry["variant"]) for entry in before["entries"]]
    assert len(declared) > len(set(declared))


def test_approval_is_not_inferred(review):
    selections = decisions(review)
    selections["rows"][0]["action"] = None
    with pytest.raises(ValueError, match="explicit review action"):
        core.materialize(review, selections)


def proposals(library):
    before = library["entries"][0]
    after = copy.deepcopy(before)
    after["wording"] += " This objection is limited to that portion."
    return {
        "kind": "objection-library-proposals",
        "format_version": 1,
        "id": "batch-one",
        "base_sha256": core.digest(library),
        "items": [
            {
                "id": "change-one",
                "classification": "replacement",
                "target_id": before["id"],
                "before": copy.deepcopy(before),
                "after": after,
                "evidence": ["synthetic edit"],
                "decision": "accept",
                "decision_record": "Synthetic test approval of exact text",
            }
        ],
    }


def test_versions_are_non_destructive_and_idempotent(review):
    original = copy.deepcopy(review["library"])
    updates = proposals(original)
    new = core.apply_proposals(original, updates)
    assert new["version"] == 2
    assert original == review["library"]
    assert new["entries"][1:] == original["entries"][1:]
    with pytest.raises(ValueError, match="already applied"):
        core.apply_proposals(new, updates)
    stale = copy.deepcopy(original)
    stale["version"] += 1
    with pytest.raises(ValueError, match="Library changed"):
        core.apply_proposals(stale, updates)


def test_replacement_and_new_variant_bind_to_same_original_in_either_order(review):
    original = copy.deepcopy(review["library"])
    updates = proposals(original)
    variant = copy.deepcopy(updates["items"][0])
    variant.update(id="additional-variant", classification="new_variant")
    variant["after"]["id"] += "-alternative"
    variant["after"]["wording"] += " Separate alternative wording."
    updates["items"].append(variant)
    first = core.apply_proposals(original, updates)
    updates["items"].reverse()
    reversed_result = core.apply_proposals(original, updates)
    assert core.indexed(first["entries"]) == core.indexed(reversed_result["entries"])
    assert original == review["library"]
    assert len(first["entries"]) == len(original["entries"]) + 1


@pytest.mark.parametrize(
    "classification", ["matter_only", "substantive_response", "unresolved"]
)
def test_nonreusable_cannot_promote(review, classification):
    updates = proposals(review["library"])
    updates["items"][0]["classification"] = classification
    with pytest.raises(ValueError, match="Non-reusable"):
        core.apply_proposals(review["library"], updates)


@pytest.mark.parametrize("decision", ["pending", "reject", "defer"])
def test_only_accepted_changes_apply(review, decision):
    updates = proposals(review["library"])
    updates["items"][0]["decision"] = decision
    with pytest.raises(ValueError, match="No accepted"):
        core.apply_proposals(review["library"], updates)


def test_no_source_overwrite(tmp_path):
    source = tmp_path / "source.json"
    core.write(source, {"original": True})
    with pytest.raises(FileExistsError):
        core.write(source, {})
    assert json.loads(source.read_text()) == {"original": True}


def make_docx(path, paragraphs):
    root = ET.Element(word.W + "document")
    body = ET.SubElement(root, word.W + "body")
    for value in paragraphs:
        paragraph = ET.SubElement(body, word.W + "p")
        ET.SubElement(ET.SubElement(paragraph, word.W + "r"), word.W + "t").text = value
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", ET.tostring(root))


def test_word_changes_use_baseline_and_preserve_ambiguity(review, tmp_path):
    assembly = core.materialize(review, decisions(review))
    paragraphs = ["Response draft"]
    for request in assembly["requests"]:
        paragraphs.extend([request["label"], request["text"]])
        paragraphs.extend(c["wording"] for c in request["components"])
        paragraphs.extend(["Response:", "[Attorney response]"])
    baseline = tmp_path / "baseline.docx"
    make_docx(baseline, paragraphs)
    bound = word.bind_legacy(assembly, baseline)
    target = bound["baseline"]["mapping"][1]["components"][0]["span"][0]
    paragraphs[target] += " Changed qualification."
    paragraphs[target + 2] = "Substantive answer now supplied."
    returned = tmp_path / "returned.docx"
    make_docx(returned, paragraphs)
    comparison = word.compare(bound, baseline, returned)
    assert comparison["observations"][0]["origin"]["entry_id"] == "scope"
    assert comparison["observations"][1]["origin"] is None
    with pytest.raises(ValueError, match="Wrong delivered baseline"):
        word.compare(bound, returned, returned)


def test_adjacent_mixed_edits_stay_unresolved(review, tmp_path):
    assembly = core.materialize(review, decisions(review))
    assembly["requests"] = [assembly["requests"][12]]
    request = assembly["requests"][0]
    old = [request["text"], *[c["wording"] for c in request["components"]], "Answer"]
    baseline = tmp_path / "baseline.docx"
    make_docx(baseline, old)
    bound = word.bind_legacy(assembly, baseline)
    returned = tmp_path / "returned.docx"
    make_docx(
        returned, [old[0], "Rewritten objections and substantive answer combined."]
    )
    assert word.compare(bound, baseline, returned)["observations"][0]["origin"] is None


def test_multiline_component_and_changed_requests(review, tmp_path):
    selections = decisions(review)
    choice = selections["rows"][1]["choices"][0]
    choice.update(wording="Paragraph one.\nParagraph two.", edited=True)
    row = selections["rows"][1]
    row["action"]["reviewed_content_sha256"] = core.digest(
        core.reviewed_content(review, row)
    )
    assembly = core.materialize(review, selections)
    assembly["requests"] = [assembly["requests"][1]]
    request = assembly["requests"][0]
    baseline = tmp_path / "multi.docx"
    make_docx(
        baseline, [request["text"], "Paragraph one.", "Paragraph two.", "Response"]
    )
    assert word.bind_legacy(assembly, baseline)["baseline"]["mapping"][0]["components"][
        0
    ]["span"] == [1, 3]
    make_docx(baseline, ["Changed served wording", "Paragraph one.", "Paragraph two."])
    with pytest.raises(ValueError, match="Exact request not found"):
        word.bind_legacy(assembly, baseline)
