import copy

import pytest
from test_objection_review import core, decisions
from test_objection_review import review as review


def refresh(review, row):
    row["selected_ids"] = [choice["component_id"] for choice in row["choices"]]
    row["action"] = {
        "kind": "individual",
        "at": "development-test",
        "reviewed_content_sha256": core.digest(core.reviewed_content(review, row)),
    }


def custom(text=""):
    return {
        "component_id": "saved-custom-draft",
        "entry_id": None,
        "params": {},
        "wording": text,
        "edited": True,
        "scope": "",
        "notes": "Keep this note, too.",
    }


def test_complete_draft_roundtrip_keeps_unselected_edits(review):
    saved = decisions(review)
    saved["purpose"] = "progress"
    row = saved["rows"][1]
    row["state"], row["action"] = "not_reviewed", None
    row["drafts"][0].update(
        wording="An edited but deselected qualification.", edited=True
    )
    row["drafts"].append(custom("A custom draft kept after deselection."))
    row["choices"], row["selected_ids"] = [], []
    restored = core.resume_selections(review, saved)
    assert restored == saved
    assert len(restored["rows"][1]["drafts"]) == 2
    assert restored["rows"][1]["choices"] == []
    with pytest.raises(ValueError, match="Progress"):
        core.materialize(review, restored)


def test_incomplete_drafts_save_but_do_not_authorize_insertion(review):
    saved = decisions(review)
    row = saved["rows"][1]
    row["state"], row["action"] = "needs_input", None
    row["drafts"][0]["params"] = dict.fromkeys(row["drafts"][0]["params"], "")
    row["drafts"][0].update(wording="", edited=True)
    row["drafts"].append(custom())
    row["choices"] = row["drafts"]
    row["selected_ids"] = [c["component_id"] for c in row["choices"]]
    core.selections_check(review, saved)
    assert core.materialize(review, saved)["requests"][1]["objection_text"] == ""
    row["state"] = "reviewed"
    refresh(review, row)
    with pytest.raises(ValueError, match="selected wording"):
        core.materialize(review, saved)


@pytest.mark.parametrize(
    "mutation", ["wording", "params", "order", "selection", "notes"]
)
def test_exact_review_action_rejects_changed_content(review, mutation):
    saved = decisions(review)
    row = saved["rows"][1]
    row["choices"].append(custom("An additional independently reviewed component."))
    refresh(review, row)
    if mutation == "wording":
        row["choices"][0].update(wording="Changed after review.", edited=True)
    elif mutation == "params":
        row["choices"][0]["params"][next(iter(row["choices"][0]["params"]))] = (
            "A different portion"
        )
        row["choices"][0]["edited"] = True
    elif mutation == "order":
        row["choices"].reverse()
    elif mutation == "selection":
        row["choices"] = row["choices"][:1]
    else:
        row["notes"] = "An altered review note."
    row["selected_ids"] = [c["component_id"] for c in row["choices"]]
    with pytest.raises(ValueError, match="after the recorded review"):
        core.materialize(review, saved)
    refresh(review, row)
    result = core.materialize(review, saved)
    assert result["requests"][1]["objection_text"] == "\n\n".join(
        c["wording"] for c in row["choices"]
    )
    assert (
        row["notes"] not in result["requests"][1]["objection_text"]
        if row["notes"]
        else True
    )


def test_compatibility_projection_cannot_override_drafts(review):
    saved = copy.deepcopy(decisions(review))
    row = saved["rows"][1]
    row["choices"] = copy.deepcopy(row["choices"])
    row["choices"][0].update(wording="A disconnected selected projection.", edited=True)
    refresh(review, row)
    with pytest.raises(ValueError, match="saved draft"):
        core.materialize(review, saved)


def test_legacy_import_preserves_available_edits_without_approval(review):
    legacy = decisions(review)
    legacy["format_version"] = 1
    for row in legacy["rows"]:
        row.pop("drafts")
        row.pop("selected_ids")
        row["action"].pop("reviewed_content_sha256")
    legacy["rows"][0]["choices"].append(custom("Legacy custom wording."))
    with pytest.raises(ValueError, match="format version"):
        core.materialize(review, legacy)
    restored = core.resume_selections(review, legacy)
    assert restored["purpose"] == "progress"
    assert restored["rows"][0]["drafts"][0]["wording"] == "Legacy custom wording."
    assert all(
        row["state"] == "not_reviewed" and row["action"] is None
        for row in restored["rows"]
    )
    assert restored["rows"][0]["legacy_action"] == legacy["rows"][0]["action"]
    assert legacy["format_version"] == 1


def test_legacy_migration_cannot_change_source_or_library(review):
    legacy = decisions(review)
    legacy["format_version"] = 1
    legacy["source_sha256"] = "a" * 64
    with pytest.raises(ValueError, match="served source"):
        core.resume_selections(review, legacy)


def test_reviewed_none_and_unfinished_remain_distinct(review):
    saved = decisions(review)
    row = saved["rows"][0]
    assert row["choices"] == []
    result = core.materialize(review, saved)
    assert not result["requests"][0]["open_review"]
    row["state"], row["action"] = "needs_input", None
    assert core.materialize(review, saved)["requests"][0]["open_review"]
    row["state"] = "reviewed"
    refresh(review, row)
    assert not core.materialize(review, saved)["requests"][0]["open_review"]


def test_lawyer_can_replace_wording_and_review_without_original_field_values(review):
    saved = decisions(review)
    row = saved["rows"][1]
    row["drafts"][0].update(
        wording="Lawyer supplied revised starting wording with its own qualification.",
        params=dict.fromkeys(row["drafts"][0]["params"], ""),
        edited=True,
    )
    refresh(review, row)
    assert (
        core.materialize(review, saved)["requests"][1]["objection_text"]
        == row["drafts"][0]["wording"]
    )
