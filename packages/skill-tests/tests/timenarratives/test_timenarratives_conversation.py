"""Snapshot intake contracts and ordered source-time selection."""

from __future__ import annotations

import copy
import hashlib
import importlib
import json
from pathlib import Path

import pytest
from test_timenarratives_packet import request
from timenarratives_schema import published_schema_accepts

compiler = importlib.import_module("build_packet")
contract = importlib.import_module("structural_contracts")
start = importlib.import_module("start_run")
SCHEMAS = Path(__file__).resolve().parents[4] / "skills/core/timenarratives/schemas"


def message(identity="msg/1", role="user", timestamp="2026-08-21T09:00:00Z"):
    return {
        "messageId": identity,
        "role": role,
        "author": "James Cockburn",
        "timestamp": timestamp,
        "text": "I prepared claim analysis for M-100.",
    }


def snapshot(messages=None, **overrides):
    value = {
        "schemaVersion": "timenarratives.conversation.v1",
        "conversationId": "chat/one",
        "origin": "host_reader",
        "scope": {"since": None, "until": None},
        "coverage": {"status": "complete", "gaps": []},
        "messages": messages if messages is not None else [message()],
    }
    value.update(overrides)
    return value


def prepare(tmp_path, value=None, **filters):
    selected = tmp_path / "selected"
    selected.mkdir(exist_ok=True)
    source = selected / "conversation.json"
    source.write_text(
        json.dumps(value or snapshot(), ensure_ascii=True), encoding="utf-8"
    )
    req = request(
        [{"kind": "conversation", "path": source.name, "conversationId": "chat/one"}],
        sourceTypes=["conversation"],
        **filters,
    )
    return req, selected, source


def compile_snapshot(tmp_path, value=None, **filters):
    req, selected, _ = prepare(tmp_path, value, **filters)
    result = compiler.compile_packet(req, selected)
    assert contract.validate_packet_semantic_boundary(result) == []
    return result


def test_lossless_order_roles_hashes_and_contract_copies(tmp_path):
    human = message()
    human["text"] = "AÃ©\r\nB\rC"
    value = snapshot([human, message("assistant", "assistant")])
    req, selected, source = prepare(tmp_path, value)
    original = source.read_bytes()
    packet = compiler.compile_packet(req, selected)
    assert source.read_bytes() == original
    assert contract.validate_packet_semantic_boundary(packet) == []
    assert packet["containers"][0]["rawSha256"] == hashlib.sha256(original).hexdigest()
    assert packet["units"][0]["canonicalText"] == "AÃ©\nB\nC"
    part = packet["parts"][0]
    assert part["rawSha256"] == hashlib.sha256(human["text"].encode()).hexdigest()
    assert part["conversationMessage"]["messageId"] == "msg/1"
    assert part["conversationMessage"]["index"] == 0
    assert "/message:msg%2F1/index:0/role:user" in part["locator"]
    assert packet["units"][0]["assertedByActorId"] is None
    assert packet["units"][0]["sourceClass"] == "documentary_supported"
    assert packet["units"][1]["eligibility"] == "context_only"
    for kind, instance in (
        ("conversation", value),
        ("packet", packet),
        ("request", req),
    ):
        name = f"timenarratives-{kind}.schema.json"
        assert published_schema_accepts(SCHEMAS / name, instance)
        assert (SCHEMAS / name).read_bytes() == (
            SCHEMAS.parents[3] / "packages/contracts/schemas" / name
        ).read_bytes()


@pytest.mark.parametrize("role", ["assistant", "tool", "quoted", "unknown"])
def test_nonhuman_roles_cannot_be_evidence_even_when_author_is_lawyer(tmp_path, role):
    packet = compile_snapshot(tmp_path, snapshot([message(role=role)]))
    assert packet["units"][0]["role"] == "context"
    assert packet["units"][0]["eligibility"] == "context_only"


def test_summary_cannot_support_human_activity(tmp_path):
    packet = compile_snapshot(tmp_path, snapshot(origin="summary"))
    assert packet["units"][0]["eligibility"] == "context_only"
    assert "conversation_summary_context_only" in packet["limitations"]


@pytest.mark.parametrize(
    "mutation,reason",
    [
        ("scope", "conversation_scope_mismatch"),
        ("identity", "conversation_id_mismatch"),
        ("duplicate", "duplicate_conversation_message"),
        ("role", "malformed_conversation"),
        ("timestamp", "malformed_conversation"),
        ("missing", "malformed_conversation"),
        ("unknown", "malformed_conversation"),
        ("coverage", "malformed_conversation"),
        ("nul", "malformed_conversation"),
        ("surrogate", "malformed_conversation"),
    ],
)
def test_malformed_or_mismatched_snapshot_is_not_partially_used(
    tmp_path, mutation, reason
):
    value = snapshot()
    if mutation == "scope":
        value["scope"]["since"] = "2026-08-21T09:00:00Z"
    elif mutation == "identity":
        value["conversationId"] = "different"
    elif mutation == "duplicate":
        value["messages"].append(copy.deepcopy(value["messages"][0]))
    elif mutation == "role":
        value["messages"][0]["role"] = "system"
    elif mutation == "timestamp":
        value["messages"][0]["timestamp"] = "2026-08-21"
    elif mutation == "missing":
        del value["messages"][0]["author"]
    elif mutation == "unknown":
        value["messages"][0]["verified"] = True
    elif mutation == "coverage":
        value["coverage"]["status"] = "partial"
    elif mutation == "nul":
        value["messages"][0]["text"] = "bad\x00body"
    elif mutation == "surrogate":
        value["messages"][0]["text"] = "bad\ud800body"
    packet = compile_snapshot(tmp_path, value)
    assert packet["errors"] == [reason]
    assert packet["units"] == []
    assert packet["roots"][0]["disposition"] == "unreadable"


@pytest.mark.parametrize(
    "data", [b'{"a":1,"a":2}', b'{"messages":NaN}', b"\xff", b"{" + b"[" * 1500]
)
def test_strict_json_rejects_duplicate_keys_invalid_encoding_and_depth(tmp_path, data):
    req, selected, source = prepare(tmp_path)
    source.write_bytes(data)
    packet = compiler.compile_packet(req, selected)
    assert packet["errors"] == ["malformed_conversation"]
    assert not packet["units"]


def test_partial_and_missing_dates_keep_supported_work_eligible(tmp_path):
    scope = {"since": "2026-08-21T09:00:00Z", "until": "2026-08-21T10:00:00Z"}
    messages = [
        message("before", timestamp="2026-08-21T08:59:59Z"),
        message("start"),
        message("unknown", timestamp=None),
        message("end", timestamp="2026-08-21T11:00:00+01:00"),
        message("after", timestamp="2026-08-21T10:00:01Z"),
    ]
    value = snapshot(
        messages,
        scope=scope,
        coverage={"status": "partial", "gaps": ["Earlier turns unavailable"]},
    )
    packet = compile_snapshot(tmp_path, value, **scope)
    assert [u["eligibility"] for u in packet["units"]] == [
        "context_only",
        "eligible",
        "requires_confirmation",
        "eligible",
        "context_only",
    ]
    assert len(packet["parts"]) == len(messages)
    assert packet["containers"][0]["conversation"]["coverage"] == value["coverage"]
    assert set(packet["limitations"]) == {
        "conversation_partial_coverage",
        "conversation_message_time_missing",
    }


def test_chronology_conflict_is_visible_without_reordering(tmp_path):
    value = snapshot(
        [message("later", timestamp="2026-08-21T10:00:00Z"), message("earlier")]
    )
    packet = compile_snapshot(tmp_path, value)
    assert [p["conversationMessage"]["messageId"] for p in packet["parts"]] == [
        "later",
        "earlier",
    ]
    assert packet["limitations"] == ["conversation_timestamp_order_conflict"]
    assert all(u["eligibility"] == "eligible" for u in packet["units"])


def test_null_message_timestamp_without_source_window_is_not_invented(tmp_path):
    packet = compile_snapshot(tmp_path, snapshot([message(timestamp=None)]))
    assert packet["units"][0]["sourceTime"] is None
    assert packet["units"][0]["eligibility"] == "eligible"


def test_same_snapshot_repeats_once_but_different_paths_need_consolidation(tmp_path):
    req, selected, _ = prepare(tmp_path)
    req["selections"].append(copy.deepcopy(req["selections"][0]))
    packet = compiler.compile_packet(req, selected)
    assert len(packet["units"]) == 1
    assert packet["roots"][1]["disposition"] == "exactDuplicate"
    req["selections"][1]["path"] = "other.json"
    with pytest.raises(
        compiler.PacketBuildError, match="duplicate_conversation_selection"
    ):
        compiler.compile_packet(req, selected)


def test_wrong_expected_id_cannot_use_raw_duplicate_shortcut(tmp_path):
    req, selected, _ = prepare(tmp_path)
    req["selections"].append({**req["selections"][0], "conversationId": "wrong"})
    packet = compiler.compile_packet(req, selected)
    assert packet["roots"][1]["disposition"] == "unreadable"
    assert "conversation_id_mismatch" in packet["errors"]


def test_request_helper_accepts_conversation_only_run(tmp_path):
    value = start.build_request(
        lawyer="James",
        matter="Cedar",
        paths=[],
        conversations=[("host/id", "chat.json")],
    )
    assert value["selections"] == [
        {"kind": "conversation", "conversationId": "host/id", "path": "chat.json"}
    ]


def test_future_source_timestamp_is_context_even_without_explicit_window(tmp_path):
    packet = compile_snapshot(
        tmp_path, snapshot([message(timestamp="2026-08-22T09:00:00Z")])
    )
    assert packet["units"][0]["eligibility"] == "context_only"
    assert packet["parts"][0]["reason"] == "source_after_as_of"


def test_source_type_filter_is_preserved_for_conversation_selection(tmp_path):
    req, selected, _ = prepare(tmp_path)
    req["filters"]["sourceTypes"] = ["text"]
    packet = compiler.compile_packet(req, selected)
    assert packet["roots"][0]["disposition"] == "excluded"
    assert packet["units"] == []
    assert contract.validate_packet_semantic_boundary(packet) == []


def test_large_message_splits_with_lossless_order_and_distinct_message_offsets(
    tmp_path,
):
    human = message()
    human["text"] = "é" * 40000
    packet = compile_snapshot(tmp_path, snapshot([human, message("second")]))
    first_units = packet["units"][:2]
    assert "".join(u["canonicalText"] for u in first_units) == human["text"]
    assert [u["utf8Start"] for u in first_units] == [0, 65536]
    assert packet["units"][2]["utf8Start"] == 0
    assert len({u["unitId"] for u in packet["units"]}) == 3


def test_packet_budget_exceeded_is_fault_not_truncation(tmp_path):
    huge = message()
    huge["text"] = "é" * 160000
    req, selected, _ = prepare(tmp_path, snapshot([huge]))
    packet = compiler.compile_packet(req, selected)
    assert "".join(u["canonicalText"] for u in packet["units"]) == huge["text"]
    assert packet["budget"]["withinLimit"] is False
    assert "packet_budget_exceeded" in {
        f["code"] for f in contract.validate_packet_semantic_boundary(packet)
    }
