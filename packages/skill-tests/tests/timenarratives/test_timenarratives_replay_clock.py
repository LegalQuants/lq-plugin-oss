"""Replay clocks stay explicit and validated rather than altering source dates."""

from __future__ import annotations

import pytest
from test_timenarratives_start_run import packet_core, start_run


def test_explicit_replay_clock_is_preserved_and_validated() -> None:
    request = start_run.build_request(
        lawyer="Alex Hart",
        matter="Cedar",
        paths=[],
        notes=["I analysed the liability cap."],
        as_of="2026-09-06T20:00:00+01:00",
    )
    assert request["filters"]["asOf"] == "2026-09-06T20:00:00+01:00"
    assert request["filters"]["since"] is None
    assert request["filters"]["until"] is None


def test_invalid_replay_clock_does_not_default_silently() -> None:
    with pytest.raises(packet_core.PacketBuildError, match="RFC3339"):
        start_run.build_request(
            lawyer="Alex Hart", matter="Cedar", paths=["note.txt"], as_of="yesterday"
        )
