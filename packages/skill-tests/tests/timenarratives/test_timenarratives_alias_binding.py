"""Alias identity is a strict, digest-bound TimeNarratives input."""

from __future__ import annotations

import copy
import importlib
import json
import sys
from email.message import EmailMessage
from email.policy import SMTP
from pathlib import Path

import pytest
from test_timenarratives_contracts import make_confirmation, make_map
from timenarratives_schema import published_schema_accepts

ROOT = Path(__file__).resolve().parents[4]
SCRIPTS = ROOT / "skills" / "core" / "timenarratives" / "scripts"
SCHEMAS = ROOT / "skills" / "core" / "timenarratives" / "schemas"
sys.path.insert(0, str(SCRIPTS))

build_packet = importlib.import_module("build_packet")
canonical_sha256 = importlib.import_module("canonical_json").canonical_sha256
validate_confirmation = importlib.import_module("map_semantics").validate_confirmation
validate_map = importlib.import_module("map_semantics").validate_map
validate_schema_subset = importlib.import_module("schema_subset").validate_schema_subset
validate_structure = importlib.import_module("structural_contracts").validate_structure


def _request() -> dict:
    return {
        "schemaVersion": "timenarratives.request.v1",
        "runId": "alias-binding",
        "actor": {
            "id": "ACTOR1",
            "name": "Avery Example",
            "aliases": ["A. Example", " avery@example.test "],
        },
        "matter": {
            "id": "MATTER1",
            "client": "Synthetic Client",
            "aliases": ["Meridian proceedings", "Ref 42"],
        },
        "selections": [{"kind": "file", "path": "source.eml"}],
        "filters": {
            "sourceTypes": ["email"],
            "since": None,
            "until": None,
            "asOf": "2026-08-21T12:00:00+01:00",
        },
    }


def _write_source(
    path: Path, author: str | None = "Avery Example <avery@example.test>"
) -> None:
    message = EmailMessage()
    if author is not None:
        message["From"] = author
    message["Date"] = "Thu, 20 Aug 2026 09:00:00 +0100"
    message.set_content("Prepared claim analysis for Meridian.")
    path.write_bytes(message.as_bytes(policy=SMTP))


def _schema_accepts(tmp_path: Path, schema_name: str, value: dict) -> bool:
    del tmp_path
    return published_schema_accepts(SCHEMAS / schema_name, value)


def _map_for(packet: dict) -> dict:
    mapping = make_map(packet)
    unit = packet["units"][0]
    mapping["unitAssessment"][0]["unitId"] = unit["unitId"]
    mapping["atoms"][0].update(
        unitId=unit["unitId"],
        endByte=unit["utf8End"],
        spanSha256=unit["canonicalUtf8Sha256"],
    )
    mapping["events"][0].update(
        assertedBy=unit["sourceAuthor"],
        performedByActorId=packet["actor"]["id"],
        namedTimekeeperActorId=packet["actor"]["id"],
        matterId=packet["matter"]["id"],
    )
    mapping["clauses"][0]["clauseOwnerActorId"] = packet["actor"]["id"]
    return mapping


def test_aliases_round_trip_exactly_and_bind_all_downstream_digests(
    tmp_path: Path,
) -> None:
    _write_source(tmp_path / "source.eml")
    request = _request()
    packet = build_packet.compile_packet(request, tmp_path)
    mapping = _map_for(packet)
    confirmation = make_confirmation(packet, mapping)

    assert packet["actor"] == request["actor"]
    assert packet["matter"] == request["matter"]
    assert packet["requestDigestSha256"] == canonical_sha256(request)
    assert validate_map(packet, mapping)["faults"] == []
    assert validate_confirmation(packet, mapping, confirmation)["faults"] == []

    changed_request = copy.deepcopy(request)
    changed_request["actor"]["aliases"].append("Avery E.")
    changed_packet = build_packet.compile_packet(changed_request, tmp_path)

    assert changed_packet["requestDigestSha256"] != packet["requestDigestSha256"]
    assert changed_packet["packetDigestSha256"] != packet["packetDigestSha256"]
    map_codes = {x["code"] for x in validate_map(changed_packet, mapping)["faults"]}
    confirmation_codes = {
        x["code"]
        for x in validate_confirmation(changed_packet, mapping, confirmation)["faults"]
    }
    assert "map_packet_digest" in map_codes
    assert "stale_packet_confirmation" in confirmation_codes


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value["actor"].pop("aliases"),
        lambda value: value["matter"].pop("aliases"),
        lambda value: value["actor"].update(aliasz=[]),
        lambda value: value["actor"].update(aliases=["same", "same"]),
        lambda value: value["matter"].update(aliases=["same", "same"]),
        lambda value: value["actor"].update(aliases=[""]),
        lambda value: value["actor"].update(aliases=[" \t"]),
        lambda value: value["actor"].update(aliases=[7]),
        lambda value: value["actor"].update(aliases=["x" * 257]),
        lambda value: value["matter"].update(aliases=[str(x) for x in range(21)]),
    ],
)
def test_invalid_request_alias_contract_fails_runtime_and_schema(
    tmp_path: Path, mutate
) -> None:
    request = _request()
    mutate(request)

    with pytest.raises(build_packet.PacketBuildError):
        build_packet.compile_packet(request, tmp_path)
    assert not _schema_accepts(tmp_path, "timenarratives-request.schema.json", request)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value["actor"].pop("aliases"),
        lambda value: value["matter"].update(aliases=["same", "same"]),
        lambda value: value["actor"].update(aliases=[""]),
        lambda value: value["matter"].update(aliases=["x" * 257]),
    ],
)
def test_packet_schema_refuses_missing_duplicate_or_invalid_aliases(
    tmp_path: Path, mutate
) -> None:
    _write_source(tmp_path / "source.eml")
    packet = build_packet.compile_packet(_request(), tmp_path)
    mutate(packet)
    schema = json.loads(
        (SCHEMAS / "timenarratives-packet.schema.json").read_text(encoding="utf-8")
    )
    assert validate_schema_subset(packet, schema)
    assert not _schema_accepts(tmp_path, "timenarratives-packet.schema.json", packet)


def test_external_actor_and_matter_ids_round_trip_across_packet_and_map(
    tmp_path: Path,
) -> None:
    _write_source(tmp_path / "source.eml")
    request = _request()
    request["actor"]["id"] = "007/ACTOR"
    request["matter"]["id"] = "12345/ABC-001"

    packet = build_packet.compile_packet(request, tmp_path)
    mapping = _map_for(packet)

    assert packet["actor"]["id"] == "007/ACTOR"
    assert packet["matter"]["id"] == "12345/ABC-001"
    assert _schema_accepts(tmp_path, "timenarratives-request.schema.json", request)
    assert _schema_accepts(tmp_path, "timenarratives-packet.schema.json", packet)
    assert _schema_accepts(tmp_path, "timenarratives-map.schema.json", mapping)
    assert validate_structure("map", mapping) == []
    assert validate_map(packet, mapping)["faults"] == []

    invalid_graph = copy.deepcopy(mapping)
    invalid_graph["events"][0]["eventId"] = "12345/ABC-001"
    assert not _schema_accepts(
        tmp_path, "timenarratives-map.schema.json", invalid_graph
    )
    assert validate_structure("map", invalid_graph)


@pytest.mark.parametrize(
    ("target", "value"),
    [
        ("actor", ""),
        ("matter", ""),
        ("actor", " \t"),
        ("matter", " \t"),
        ("actor", "ACTOR\n1"),
        ("matter", "MATTER\x001"),
        ("actor", "x" * 257),
        ("matter", "x" * 257),
    ],
)
def test_external_request_ids_reject_empty_control_and_overlength_values(
    tmp_path: Path, target: str, value: str
) -> None:
    request = _request()
    request[target]["id"] = value

    with pytest.raises(build_packet.PacketBuildError):
        build_packet.compile_packet(request, tmp_path)
    assert not _schema_accepts(tmp_path, "timenarratives-request.schema.json", request)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("events", 0, "performedByActorId"), ""),
        (("events", 0, "namedTimekeeperActorId"), "ACTOR\n1"),
        (("events", 0, "matterId"), "x" * 257),
        (("clauses", 0, "clauseOwnerActorId"), " \t"),
    ],
)
def test_external_map_ids_reject_empty_control_and_overlength_values(
    tmp_path: Path, path: tuple[str, int, str], value: str
) -> None:
    _write_source(tmp_path / "source.eml")
    packet = build_packet.compile_packet(_request(), tmp_path)
    mapping = _map_for(packet)
    mapping[path[0]][path[1]][path[2]] = value

    assert not _schema_accepts(tmp_path, "timenarratives-map.schema.json", mapping)
    assert validate_structure("map", mapping)


def test_actor_name_and_client_boundary_values_round_trip(tmp_path: Path) -> None:
    _write_source(tmp_path / "source.eml")
    request = _request()
    request["actor"]["name"] = "A" * 200
    request["matter"]["client"] = "C" * 256

    packet = build_packet.compile_packet(request, tmp_path)

    assert packet["actor"]["name"] == "A" * 200
    assert packet["matter"]["client"] == "C" * 256
    assert _schema_accepts(tmp_path, "timenarratives-request.schema.json", request)
    assert _schema_accepts(tmp_path, "timenarratives-packet.schema.json", packet)


@pytest.mark.parametrize(
    ("target", "value"),
    [
        ("name", ""),
        ("name", " \t"),
        ("name", "Avery\nExample"),
        ("name", "A" * 201),
        ("client", ""),
        ("client", " \t"),
        ("client", "Client\x001"),
        ("client", "C" * 257),
    ],
)
def test_actor_name_and_client_reject_invalid_request_and_packet_values(
    tmp_path: Path, target: str, value: str
) -> None:
    request = _request()
    owner = request["actor"] if target == "name" else request["matter"]
    owner[target] = value

    with pytest.raises(build_packet.PacketBuildError):
        build_packet.compile_packet(request, tmp_path)
    assert not _schema_accepts(tmp_path, "timenarratives-request.schema.json", request)

    _write_source(tmp_path / "source.eml")
    packet = build_packet.compile_packet(_request(), tmp_path)
    packet_owner = packet["actor"] if target == "name" else packet["matter"]
    packet_owner[target] = value
    schema = json.loads(
        (SCHEMAS / "timenarratives-packet.schema.json").read_text(encoding="utf-8")
    )
    assert validate_schema_subset(packet, schema)
    assert not _schema_accepts(tmp_path, "timenarratives-packet.schema.json", packet)


@pytest.mark.parametrize(
    "author",
    [None, f"{'A' * 190} <avery@example.test>"],
)
def test_missing_or_overlength_email_author_cannot_produce_eligible_units(
    tmp_path: Path, author: str | None
) -> None:
    _write_source(tmp_path / "source.eml", author)

    packet = build_packet.compile_packet(_request(), tmp_path)

    assert packet["containers"][0]["sourceAuthor"] is None
    assert all(unit["eligibility"] != "eligible" for unit in packet["units"])
    assert packet["status"] == "requires_confirmation"
    assert "source_author_missing_or_invalid" in packet["limitations"]
