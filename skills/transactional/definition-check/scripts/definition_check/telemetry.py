"""Opt-in local timing and payload telemetry for definition-check runs."""

from __future__ import annotations

import json
import math
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, is_dataclass
from pathlib import Path
from time import perf_counter
from typing import Any


def _json_default(value: object) -> object:
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


class DebugTelemetry:
    """Collect deterministic phase timings and clearly labelled token estimates."""

    def __init__(self) -> None:
        self._started = perf_counter()
        self.phase_timings_ms: dict[str, float] = {}
        self.payloads: dict[str, dict[str, Any]] = {}
        self.counts: dict[str, int] = {}

    @contextmanager
    def phase(self, name: str) -> Iterator[None]:
        started = perf_counter()
        try:
            yield
        finally:
            elapsed = (perf_counter() - started) * 1000
            self.phase_timings_ms[name] = round(
                self.phase_timings_ms.get(name, 0.0) + elapsed, 3
            )

    def record_payload(self, name: str, value: object) -> None:
        serialized = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=_json_default,
        )
        characters = len(serialized)
        self.payloads[name] = {
            "characters": characters,
            "utf8_bytes": len(serialized.encode("utf-8")),
            "estimated_tokens": math.ceil(characters / 4),
            "estimate_method": "ceil(serialized_json_characters / 4)",
            "actual_tokens": None,
        }

    def record_count(self, name: str, value: int) -> None:
        self.counts[name] = value

    def to_dict(self, *, source_sha256: str | None) -> dict[str, Any]:
        return {
            "schema_version": "0.1.0",
            "source_sha256": source_sha256,
            "total_pipeline_ms": round((perf_counter() - self._started) * 1000, 3),
            "phase_timings_ms": self.phase_timings_ms,
            "counts": self.counts,
            "model_payloads": self.payloads,
            "actual_model_token_usage": {
                "status": "unavailable_from_host",
                "input_tokens": None,
                "cached_input_tokens": None,
                "output_tokens": None,
                "reasoning_output_tokens": None,
                "total_tokens": None,
                "note": (
                    "The packaged skill does not receive provider token counters. "
                    "Payload estimates cover serialized review envelopes only, not "
                    "system instructions, tool traffic, cache effects, or model output."
                ),
            },
        }


def write_debug_telemetry(path: str | Path, payload: dict[str, Any]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise FileExistsError(
            f"refusing to overwrite existing debug telemetry: {destination.name}"
        )
    fd, temporary = tempfile.mkstemp(
        prefix=f".{destination.name}.", dir=destination.parent
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise
