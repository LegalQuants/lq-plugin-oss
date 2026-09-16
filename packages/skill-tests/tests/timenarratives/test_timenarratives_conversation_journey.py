"""Conversation intake -> anchored map -> bound unposted draft, including attacks."""

from __future__ import annotations

import importlib
import json

import pytest
from test_timenarratives_anchor_map import _draft
from test_timenarratives_contracts import make_confirmation, make_map
from test_timenarratives_conversation import (
    compile_snapshot,
    message,
    prepare,
    snapshot,
)
from test_timenarratives_render_cli import _args

anchor = importlib.import_module("anchor_map")
canonical = importlib.import_module("canonical_json")
compiler = importlib.import_module("build_packet")
semantics = importlib.import_module("map_semantics")
renderer = importlib.import_module("render_deliverable")
start = importlib.import_module("start_run")


def mapping_for(packet):
    mapping = make_map(packet)
    unit = packet["units"][0]
    mapping["atoms"][0]["unitId"] = unit["unitId"]
    mapping["unitAssessment"] = [
        {"unitId": unit["unitId"], "disposition": "used", "reason": None}
    ]
    for row in packet["units"][1:]:
        if row["eligibility"] in {"eligible", "requires_confirmation"}:
            mapping["unitAssessment"].append(
                {
                    "unitId": row["unitId"],
                    "disposition": "needs_confirmation",
                    "reason": "source_partially_read",
                }
            )
    event = mapping["events"][0]
    event.update(
        performedByActorId=packet["actor"]["id"],
        namedTimekeeperActorId=packet["actor"]["id"],
        matterId=packet["matter"]["id"],
    )
    mapping["clauses"][0].update(
        clauseOwnerActorId=packet["actor"]["id"],
        text="Prepared claim analysis for the selected matter.",
    )
    return mapping


def journey(tmp_path, value=None):
    req, selected, source = prepare(tmp_path, value)
    packet = compiler.compile_packet(req, selected)
    mapping, faults = anchor.resolve(packet, _draft(mapping_for(packet), packet))
    assert faults == []
    paths = {"source_root": selected, "source": source}
    for key, data in (
        ("request", req),
        ("packet", packet),
        ("map", mapping),
        ("confirmation", make_confirmation(packet, mapping)),
    ):
        paths[key] = tmp_path / (key + ".json")
        paths[key].write_text(json.dumps(data), encoding="utf-8")
    return paths, packet, mapping


def test_human_contribution_renders_and_ai_output_stays_context(tmp_path):
    paths, packet, mapping = journey(
        tmp_path, snapshot([message(), message("ai", "assistant")])
    )
    output = tmp_path / "draft"
    assert renderer.main(_args(paths, output)) == 0
    product = json.loads((output / "artifacts/deliverable.json").read_text())
    assert product["narratives"][0]["text"] == mapping["clauses"][0]["text"]
    assert product["narratives"][0]["supportClass"] == "documentary_supported"
    assert product["receipt"]["counts"]["usedUnits"] == 1
    assert product["receipt"]["counts"]["accountedUnits"] == 2
    assert product["receipt"]["packetDigest"] == packet["packetDigestSha256"]


@pytest.mark.parametrize(
    "mutation", ["text", "role", "author", "order", "id", "coverage", "delete"]
)
def test_changed_conversation_refuses_publication_after_confirmation(
    tmp_path, mutation
):
    paths, _, _ = journey(tmp_path, snapshot([message(), message("ai", "assistant")]))
    value = json.loads(paths["source"].read_text())
    if mutation == "text":
        value["messages"][0]["text"] += " Changed."
    elif mutation == "role":
        value["messages"][0]["role"] = "assistant"
    elif mutation == "author":
        value["messages"][0]["author"] = "Another lawyer"
    elif mutation == "order":
        value["messages"].reverse()
    elif mutation == "id":
        value["conversationId"] = "unselected"
    elif mutation == "coverage":
        value["coverage"] = {"status": "partial", "gaps": ["Missing a turn"]}
    if mutation == "delete":
        paths["source"].unlink()
    else:
        paths["source"].write_text(json.dumps(value), encoding="utf-8")
    output = tmp_path / "refused"
    assert renderer.main(_args(paths, output)) == 1
    assert not output.exists()


@pytest.mark.parametrize("role", ["assistant", "tool", "quoted", "unknown"])
def test_attempt_to_anchor_nonhuman_activity_fails_deterministically(tmp_path, role):
    packet = compile_snapshot(tmp_path, snapshot([message(role=role)]))
    mapping = mapping_for(packet)
    result = semantics.validate_map(packet, mapping)
    assert "ineligible_atom_unit" in {fault["code"] for fault in result["faults"]}


@pytest.mark.parametrize(
    "mutation",
    [
        "unit_role",
        "unit_kind",
        "source_class",
        "author",
        "timestamp",
        "part_role",
        "locator",
        "index",
        "origin",
    ],
)
def test_packet_metadata_forgery_cannot_promote_ai_text_to_lawyer_work(
    tmp_path, mutation
):
    packet = compile_snapshot(tmp_path, snapshot([message(role="assistant")]))
    unit = packet["units"][0]
    if mutation == "unit_role":
        unit.update(role="current", eligibility="eligible")
    elif mutation == "unit_kind":
        unit["kind"] = "text_block"
    elif mutation == "source_class":
        unit["sourceClass"] = "user_attested"
    elif mutation == "author":
        unit["sourceAuthor"] = "Another lawyer"
    elif mutation == "timestamp":
        unit["sourceTime"] = None
    elif mutation == "part_role":
        packet["parts"][0]["role"] = "conversation_user"
    elif mutation == "locator":
        unit["locator"] = "text:forged"
    elif mutation == "index":
        packet["parts"][0]["conversationMessage"]["index"] = 2
    elif mutation == "origin":
        unit["originId"] = unit["containerId"]
    packet["packetDigestSha256"] = canonical.packet_sha256(packet)
    result = semantics.validate_map(packet, mapping_for(packet))
    assert "invalid_conversation_state" in {fault["code"] for fault in result["faults"]}


def test_summary_cannot_be_laundered_into_work_by_unit_role_change(tmp_path):
    packet = compile_snapshot(tmp_path, snapshot(origin="summary"))
    packet["units"][0].update(role="current", eligibility="eligible")
    packet["packetDigestSha256"] = canonical.packet_sha256(packet)
    assert semantics.validate_map(packet, mapping_for(packet))["faults"]


def test_partial_and_unknown_date_do_not_withhold_independent_narrative(tmp_path):
    scope = {"since": "2026-08-21T08:00:00Z", "until": "2026-08-21T10:00:00Z"}
    value = snapshot(
        [message(), message("undated", timestamp=None)],
        scope=scope,
        coverage={"status": "partial", "gaps": ["Older messages unavailable"]},
    )
    packet = compile_snapshot(tmp_path, value, **scope)
    mapping = mapping_for(packet)
    result = renderer.build_rendered(
        packet, mapping, make_confirmation(packet, mapping)
    )
    assert result["faults"] == []
    assert len(result["deliverable"]["narratives"]) == 1
    assert (
        result["deliverable"]["checkQuestions"][0]["unitId"]
        == packet["units"][1]["unitId"]
    )
    assert result["deliverable"]["status"] == "partial_withheld"


def test_current_user_note_remains_attested_alongside_chat_documentary_source(tmp_path):
    req, selected, _ = prepare(tmp_path)
    req["filters"]["sourceTypes"].append("user_note")
    req["selections"].append(
        {"kind": "user_note", "text": "I checked the authorities myself."}
    )
    packet = compiler.compile_packet(req, selected)
    assert packet["units"][0]["sourceClass"] == "documentary_supported"
    assert packet["units"][1]["sourceClass"] == "user_attested"
    assert packet["units"][1]["assertedByActorId"] == req["actor"]["id"]


def test_start_run_cli_compiles_conversation_only_without_file_arguments(
    tmp_path, capsys
):
    _, selected, _ = prepare(tmp_path)
    assert (
        start.main(
            [
                "--lawyer",
                "James Cockburn",
                "--matter",
                "M-100",
                "--source-root",
                str(selected),
                "--conversation",
                "chat/one",
                "conversation.json",
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert result["selected"] == 1
    assert result["readable"] == 1
    assert result["status"] == "ready_for_semantic_analysis"
