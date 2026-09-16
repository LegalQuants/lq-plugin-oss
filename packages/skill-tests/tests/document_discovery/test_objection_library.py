"""Behavioral checks for candidate curation, provenance and version handoffs."""

import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
SCRIPTS = ROOT / "skills/litigation/document-discovery/scripts"


def load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


core = load("objection_review")
builder = load("objection_library")


def entry(entry_id):
    return {
        "id": entry_id,
        "family": "scope",
        "label": "Scope",
        "variant": "Identified unrelated portion",
        "wording": "The identified portion concerns {{unrelated_subject}}.",
        "fields": {"unrelated_subject": "Identify the unrelated subject"},
        "guidance": "Identify the portion before selecting this candidate.",
        "conditions": ["An identified unrelated portion"],
        "exclusions": ["Do not withhold relevant non-objected material"],
        "sources": [{"source_id": "prior", "locator": "Response 1"}],
    }


@pytest.fixture
def catalog():
    library = {
        "kind": "objection-library",
        "format_version": 1,
        "id": "test-library",
        "version": 1,
        "entries": [],
    }
    items = []
    for index in range(3):
        items.append(
            {
                "id": f"candidate-{index}",
                "classification": "new_entry" if index < 2 else "matter_only",
                "target_id": None,
                "before": None,
                "after": entry(f"scope-{index}") if index < 2 else None,
                "evidence": ["Response 1 in the supplied test source"],
                "reason": "Proposed reusable scope language"
                if index < 2
                else "Matter fact",
                "decision": "pending",
                "decision_record": None,
            }
        )
    return {
        "kind": "objection-library-catalog",
        "format_version": 1,
        "id": "test-catalog",
        "title": "Candidate library",
        "scope": "Test federal RFPs",
        "notes": ["Synthetic contract test; no attorney approval."],
        "library": library,
        "proposals": {
            "kind": "objection-library-proposals",
            "format_version": 1,
            "id": "capture-one",
            "base_sha256": core.digest(library),
            "items": items,
        },
        "sources": [
            {
                "id": "prior",
                "file": "sources/prior.md",
                "title": "Prior responses",
                "sha256": "a" * 64,
            }
        ],
        "passages": [
            {
                "id": "passage-one",
                "source_id": "prior",
                "locator": "Response 1",
                "request": "Produce unrelated records.",
                "original": "The identified portion concerns unrelated products.",
                "context": "Substantive matter content is separately excluded.",
                "proposal_ids": [item["id"] for item in items],
            }
        ],
    }


def decisions(catalog, purpose="application"):
    return {
        "kind": "objection-library-decisions",
        "format_version": 2,
        "catalog_id": catalog["id"],
        "catalog_sha256": core.digest(catalog),
        "base_sha256": core.digest(catalog["library"]),
        "purpose": purpose,
        "rows": [
            {
                "proposal_id": item["id"],
                "decision": "pending",
                "after": copy.deepcopy(item["after"]),
                "note": "",
                "action": None,
            }
            for item in catalog["proposals"]["items"]
        ],
    }


def decide(row, decision):
    row["decision"] = decision
    row["action"] = (
        None
        if decision == "pending"
        else {
            "kind": "individual",
            "at": "2026-09-06T12:30:00Z",
            "decision": decision,
            "reviewed_content_sha256": core.digest(builder.decision_content(row)),
        }
    )


def test_atomic_application_rechecks_exact_edited_subset(catalog):
    chosen = decisions(catalog)
    # An intentional change to scope guidance is allowed with fresh approval.
    chosen["rows"][0]["after"]["wording"] = (
        "Counsel's chosen formulation for {{unrelated_subject}}."
    )
    chosen["rows"][0]["after"]["conditions"] = []
    chosen["rows"][0]["after"]["exclusions"] = []
    decide(chosen["rows"][0], "accept")
    decide(chosen["rows"][1], "defer")
    library = builder.apply_decisions(catalog, chosen)
    assert [entry["id"] for entry in library["entries"]] == ["scope-0"]
    assert library["entries"][0]["wording"] == chosen["rows"][0]["after"]["wording"]
    assert catalog["library"]["entries"] == []
    chosen["rows"][0]["after"]["wording"] += " A later edit."
    with pytest.raises(ValueError, match="changed after"):
        builder.apply_decisions(catalog, chosen)
    decide(chosen["rows"][0], "accept")
    assert builder.apply_decisions(catalog, chosen)["entries"][0]["wording"].endswith(
        "A later edit."
    )


def test_approved_subset_preserves_wording_and_continues_remaining(catalog):
    original = copy.deepcopy(catalog)
    chosen = decisions(catalog)
    chosen["rows"][0]["after"]["wording"] += " Only that portion is disputed."
    chosen["rows"][0]["note"] = "Synthetic test decision"
    decide(chosen["rows"][0], "accept")
    chosen["rows"][1]["after"]["label"] = "Narrower scope candidate"
    decide(chosen["rows"][1], "defer")
    decide(chosen["rows"][2], "reject")
    proposed = builder.reconcile(catalog, chosen)
    updated = core.apply_proposals(catalog["library"], proposed)
    assert catalog == original
    assert updated["version"] == 2
    assert len(updated["entries"]) == 1
    assert updated["entries"][0]["wording"] == chosen["rows"][0]["after"]["wording"]
    assert "not authenticated" in updated["entries"][0]["approval"]["record"]
    for item, source in zip(
        proposed["items"], original["proposals"]["items"], strict=True
    ):
        for name in ("classification", "target_id", "before", "evidence", "reason"):
            assert item[name] == source[name]
    continued = builder.continue_catalog(catalog, chosen, updated)
    assert continued["library"] == updated
    assert len(continued["proposals"]["items"]) == 1
    pending = continued["proposals"]["items"][0]
    assert pending["after"]["label"] == "Narrower scope candidate"
    assert pending["decision"] == "pending" and pending["decision_record"] is None
    assert continued["passages"][0]["proposal_ids"] == [pending["id"]]
    with pytest.raises(ValueError, match="Wrong or changed catalog"):
        builder.decisions_check(continued, chosen)
    with pytest.raises(ValueError, match="already applied"):
        core.apply_proposals(updated, proposed)


@pytest.mark.parametrize("name", ["catalog_id", "catalog_sha256", "base_sha256"])
def test_wrong_origin_is_rejected(catalog, name):
    chosen = decisions(catalog)
    chosen[name] = "wrong-origin"
    with pytest.raises(ValueError):
        builder.reconcile(catalog, chosen)


@pytest.mark.parametrize("change", ["missing", "duplicate", "reordered", "invented"])
def test_every_candidate_must_survive_export_in_order(catalog, change):
    chosen = decisions(catalog)
    rows = chosen["rows"]
    if change == "missing":
        rows.pop()
    elif change == "duplicate":
        rows.append(copy.deepcopy(rows[0]))
    elif change == "reordered":
        rows.reverse()
    else:
        rows[0]["proposal_id"] = "invented"
    with pytest.raises(ValueError):
        builder.decisions_check(catalog, chosen)


@pytest.mark.parametrize(
    "name,value",
    [
        ("id", "different-identity"),
        ("family", "different-family"),
        ("sources", [{"source_id": "other", "locator": "invented"}]),
        ("status", "approved"),
    ],
)
def test_curation_cannot_rewrite_candidate_origin(catalog, name, value):
    chosen = decisions(catalog)
    chosen["rows"][0]["after"][name] = value
    decide(chosen["rows"][0], "accept")
    with pytest.raises(ValueError, match="origin data|entry keys"):
        builder.reconcile(catalog, chosen)


def test_any_edit_after_action_requires_another_decision(catalog):
    chosen = decisions(catalog)
    decide(chosen["rows"][0], "accept")
    chosen["rows"][0]["after"]["guidance"] += " Changed after approval."
    with pytest.raises(ValueError, match="changed after the recorded action"):
        builder.reconcile(catalog, chosen)
    decide(chosen["rows"][0], "accept")
    assert builder.reconcile(catalog, chosen)["items"][0]["decision"] == "accept"


def test_progress_never_becomes_applyable_even_with_individual_actions(catalog):
    chosen = decisions(catalog, "progress")
    decide(chosen["rows"][0], "accept")
    builder.decisions_check(catalog, chosen)
    with pytest.raises(ValueError, match="Progress is not"):
        builder.reconcile(catalog, chosen)


def test_partial_application_preserves_incomplete_drafts(catalog):
    chosen = decisions(catalog)
    decide(chosen["rows"][0], "accept")
    chosen["rows"][1]["after"]["wording"] = "Incomplete {{new_field}}"
    chosen["rows"][1]["after"]["fields"] = {"new_field": ""}
    decide(chosen["rows"][1], "defer")
    proposed = builder.reconcile(catalog, chosen)
    assert proposed["items"][1]["after"] == chosen["rows"][1]["after"]
    updated = core.apply_proposals(catalog["library"], proposed)
    assert len(updated["entries"]) == 1
    with pytest.raises(ValueError, match="repair invalid fields"):
        builder.continue_catalog(catalog, chosen, updated)
    assert chosen["rows"][1]["after"]["fields"] == {"new_field": ""}


@pytest.mark.parametrize(
    "wording,fields",
    [
        ("Missing {{description}}", {"description": ""}),
        ("Wrong {{Unknown}}", {}),
        ("Unclosed {{unknown", {}),
        ("Unopened unknown}}", {}),
        ("Extra {{{{unknown}}}}", {"unknown": "Describe"}),
        ("Empty", {"unknown": "Extra field"}),
        ("", {}),
    ],
)
def test_invalid_drafts_can_be_saved_but_not_approved(catalog, wording, fields):
    chosen = decisions(catalog, "progress")
    row = chosen["rows"][0]
    row["after"].update(wording=wording, fields=fields)
    builder.decisions_check(catalog, chosen)
    decide(row, "accept")
    with pytest.raises(ValueError):
        builder.decisions_check(catalog, chosen)


@pytest.mark.parametrize("decision", ["pending", "reject", "defer"])
def test_unapproved_candidates_never_create_a_version(catalog, decision):
    chosen = decisions(catalog)
    for row in chosen["rows"]:
        decide(row, decision)
    proposed = builder.reconcile(catalog, chosen)
    with pytest.raises(ValueError, match="No accepted"):
        core.apply_proposals(catalog["library"], proposed)


def test_nonreusable_material_cannot_enter_library(catalog):
    chosen = decisions(catalog)
    decide(chosen["rows"][2], "accept")
    with pytest.raises(ValueError, match="Non-reusable"):
        builder.reconcile(catalog, chosen)


@pytest.mark.parametrize(
    "action",
    [
        None,
        {"kind": "batch", "at": "test", "after_sha256": "a" * 64},
        {"kind": "individual", "at": "", "after_sha256": "a" * 64},
    ],
)
def test_no_implicit_or_batch_library_approval(catalog, action):
    chosen = decisions(catalog)
    chosen["rows"][0].update(decision="accept", action=action)
    with pytest.raises(ValueError):
        builder.reconcile(catalog, chosen)


def test_pending_row_cannot_smuggle_decided_action(catalog):
    chosen = decisions(catalog)
    decide(chosen["rows"][0], "accept")
    chosen["rows"][0]["decision"] = "pending"
    with pytest.raises(ValueError, match="Pending row"):
        builder.decisions_check(catalog, chosen)


@pytest.mark.parametrize(
    "damage",
    [
        "missing-passage",
        "unknown-source",
        "duplicate-passage",
        "preapproval",
        "candidate-approval",
        "unknown-entry-source",
    ],
)
def test_catalog_requires_pending_source_backed_candidates(catalog, damage):
    if damage == "missing-passage":
        catalog["passages"][0]["proposal_ids"].pop()
    elif damage == "unknown-source":
        catalog["passages"][0]["source_id"] = "invented"
    elif damage == "duplicate-passage":
        catalog["passages"].append(copy.deepcopy(catalog["passages"][0]))
    elif damage == "preapproval":
        catalog["proposals"]["items"][0]["decision"] = "accept"
    elif damage == "candidate-approval":
        catalog["proposals"]["items"][0]["after"]["status"] = "approved"
    else:
        catalog["proposals"]["items"][0]["after"]["sources"][0]["source_id"] = (
            "invented"
        )
    with pytest.raises(ValueError):
        builder.catalog_check(catalog)


@pytest.mark.parametrize(
    "path",
    [
        "../secret",
        "/tmp/secret",
        "C:/secret",
        "C:secret",
        "sources/../../secret",
        "sources\\secret",
        "sources//prior.md",
    ],
)
def test_catalog_source_paths_are_portable_and_bounded(catalog, path):
    catalog["sources"][0]["file"] = path
    with pytest.raises(ValueError, match="relative path"):
        builder.catalog_check(catalog)


def test_source_check_uses_selected_bytes_and_rejects_symlinks(catalog, tmp_path):
    folder = tmp_path / "sources"
    folder.mkdir()
    source = folder / "prior.md"
    source.write_text("Supplied test source", encoding="utf-8")
    catalog["sources"][0]["sha256"] = core.file_digest(source)
    builder.check_sources(catalog, tmp_path)
    source.write_text("Changed bytes", encoding="utf-8")
    with pytest.raises(ValueError, match="Source bytes changed"):
        builder.check_sources(catalog, tmp_path)
    source.unlink()
    original = tmp_path / "original.md"
    original.write_text("Supplied test source", encoding="utf-8")
    source.symlink_to(original)
    with pytest.raises(ValueError, match="symlinks"):
        builder.check_sources(catalog, tmp_path)


def test_conflicting_acceptances_are_rejected_together(catalog):
    catalog["proposals"]["items"][1]["after"]["id"] = "scope-0"
    builder.catalog_check(catalog)
    chosen = decisions(catalog)
    decide(chosen["rows"][0], "accept")
    decide(chosen["rows"][1], "accept")
    with pytest.raises(ValueError, match="already exists|Conflicting"):
        builder.reconcile(catalog, chosen)


def test_continuation_rejects_unrelated_or_stale_library(catalog):
    chosen = decisions(catalog)
    decide(chosen["rows"][0], "accept")
    updated = core.apply_proposals(
        catalog["library"], builder.reconcile(catalog, chosen)
    )
    for library in (catalog["library"], {**updated, "version": updated["version"] + 1}):
        with pytest.raises(ValueError, match="exact applied decision snapshot"):
            builder.continue_catalog(catalog, chosen, library)


def test_feedback_candidates_must_match_current_entry(catalog):
    old = entry("existing-scope")
    old.update(status="approved", approval={"record": "Synthetic existing approval"})
    catalog["library"]["entries"] = [old]
    catalog["proposals"]["base_sha256"] = core.digest(catalog["library"])
    proposal = catalog["proposals"]["items"][0]
    proposal.update(
        classification="replacement",
        target_id=old["id"],
        before=copy.deepcopy(old),
        after=copy.deepcopy(old),
    )
    proposal["after"]["wording"] += " Proposed qualification."
    builder.catalog_check(catalog)
    proposal["before"]["guidance"] += " Incorrect snapshot."
    with pytest.raises(ValueError, match="before-entry does not match"):
        builder.catalog_check(catalog)


def test_continuation_refuses_deferred_variant_after_its_parent_changed(catalog):
    old = entry("existing-scope")
    old.update(status="approved", approval={"record": "Synthetic existing approval"})
    catalog["library"]["entries"] = [old]
    catalog["proposals"]["base_sha256"] = core.digest(catalog["library"])
    first, second = catalog["proposals"]["items"][:2]
    first.update(
        classification="replacement",
        target_id=old["id"],
        before=copy.deepcopy(old),
        after=copy.deepcopy(old),
    )
    first["after"]["wording"] += " A changed qualification."
    second.update(
        classification="new_variant", target_id=old["id"], before=copy.deepcopy(old)
    )
    chosen = decisions(catalog)
    decide(chosen["rows"][0], "accept")
    decide(chosen["rows"][1], "defer")
    updated = core.apply_proposals(
        catalog["library"], builder.reconcile(catalog, chosen)
    )
    with pytest.raises(ValueError, match="changed targets"):
        builder.continue_catalog(catalog, chosen, updated)


def test_cli_refuses_to_overwrite_an_existing_output(catalog, tmp_path):
    catalog_file = tmp_path / "catalog.json"
    decisions_file = tmp_path / "decisions.json"
    output = tmp_path / "proposals.json"
    core.write(catalog_file, catalog)
    core.write(decisions_file, decisions(catalog))
    original_bytes = b"Preserve this review artifact.\n"
    output.write_bytes(original_bytes)
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "objection_library.py"),
            "reconcile",
            "--catalog",
            str(catalog_file),
            "--decisions",
            str(decisions_file),
            "--out",
            str(output),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2 and "Not applied" in result.stderr
    assert output.read_bytes() == original_bytes
    output.unlink()
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "objection_library.py"),
            "reconcile",
            "--catalog",
            str(catalog_file),
            "--decisions",
            str(decisions_file),
            "--out",
            str(output),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(output.read_text())["kind"] == "objection-library-proposals"


def test_render_escapes_source_data_without_altering_its_digest(catalog):
    catalog["passages"][0]["original"] = '</script><img src=x onerror="alert(1)">'
    output = builder.render(catalog)
    assert catalog["passages"][0]["original"] not in output
    assert "\\u003c/script>" in output
    assert core.digest(catalog) in output
    assert "CATALOG_DATA" not in output


@pytest.mark.parametrize("original", ["defer", "reject", "accept"])
@pytest.mark.parametrize("change_action_disposition", [False, True])
def test_curation_action_binds_disposition_and_entry(
    catalog, original, change_action_disposition
):
    chosen = decisions(catalog)
    decide(chosen["rows"][0], "accept")
    row = chosen["rows"][1]
    decide(row, original)
    row["decision"] = "reject" if original == "accept" else "accept"
    if change_action_disposition:
        row["action"]["decision"] = row["decision"]
    with pytest.raises(ValueError, match="Decision or wording changed"):
        builder.apply_decisions(catalog, chosen)
    decide(row, row["decision"])
    assert len(builder.apply_decisions(catalog, chosen)["entries"]) == (
        1 if row["decision"] == "reject" else 2
    )


def test_legacy_curation_resumes_as_unapproved_drafts(catalog):
    old = decisions(catalog)
    old["format_version"] = 1
    for row, decision in zip(old["rows"], ["accept", "defer", "reject"], strict=True):
        row["decision"] = decision
        row["action"] = {
            "kind": "individual",
            "at": "legacy",
            "after_sha256": core.digest(row["after"]),
        }
    before = copy.deepcopy(old)
    with pytest.raises(ValueError, match="format version"):
        builder.apply_decisions(catalog, old)
    resumed = builder.resume_decisions(catalog, old)
    assert old == before
    assert resumed["format_version"] == 2 and resumed["purpose"] == "progress"
    assert [row["after"] for row in resumed["rows"]] == [
        row["after"] for row in old["rows"]
    ]
    assert all(
        row["decision"] == "pending" and row["action"] is None
        for row in resumed["rows"]
    )
    assert [row["legacy"]["decision"] for row in resumed["rows"]] == [
        "accept",
        "defer",
        "reject",
    ]
    with pytest.raises(ValueError, match="Progress"):
        builder.apply_decisions(catalog, resumed)
    resumed["purpose"] = "application"
    decide(resumed["rows"][0], "accept")
    assert len(builder.apply_decisions(catalog, resumed)["entries"]) == 1


def test_legacy_curation_wrong_catalog_preserves_original(catalog):
    old = decisions(catalog)
    old.update(format_version=1, catalog_sha256="0" * 64)
    original = copy.deepcopy(old)
    with pytest.raises(ValueError, match="Wrong or changed catalog"):
        builder.resume_decisions(catalog, old)
    assert old == original


def test_empty_curation_starter_keeps_raw_candidates_pending(catalog):
    assert catalog["library"]["entries"] == []
    original = copy.deepcopy(catalog)
    builder.catalog_check(catalog)
    builder.render(catalog)
    assert catalog == original
    assert all(item["decision"] == "pending" for item in catalog["proposals"]["items"])
    chosen = decisions(catalog)
    with pytest.raises(ValueError, match="No accepted"):
        builder.apply_decisions(catalog, chosen)
    decide(chosen["rows"][0], "accept")
    approved = builder.apply_decisions(catalog, chosen)
    assert len(approved["entries"]) == 1
    assert approved["entries"][0]["status"] == "approved"
    assert (
        approved["entries"][0]["approval"]["proposal_id"]
        == chosen["rows"][0]["proposal_id"]
    )
    assert approved["entries"][0]["wording"] == chosen["rows"][0]["after"]["wording"]
    assert catalog == original
