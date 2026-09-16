"""Validated, no-clobber response publication for optional local file adapters.

The lock is OS-owned (released after a crash); readiness is an atomic hard link
of a fully fsynced file, never the existence of a worker's draft. Every attempt
has a random identity and deadline. A terminal result is immutable by protocol.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from .review_packets import ReviewPacketError, validate_packet_response
from .stage_runner import normalize_response, valid_response_items


class ContractError(ValueError):
    """Publication infrastructure changed; response cannot be trusted."""


def dumps(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")


def read_json(path: Path) -> dict:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path.name}")
    return value


def atomic_create(path: Path, raw: bytes) -> None:
    """Publish complete bytes without replacing anything, including on Windows."""
    draft = path.with_name(f".{path.name}.{uuid.uuid4().hex}.private")
    with draft.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        os.link(draft, path)
    finally:
        draft.unlink()


@contextmanager
def locked(directory: Path):
    with (directory / ".publication.lock").open("a+b") as stream:
        stream.seek(0)
        if os.fstat(stream.fileno()).st_size == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        if os.name == "nt":
            import msvcrt

            deadline = time.monotonic() + 10
            while True:
                try:
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(0.01)
        else:
            import fcntl

            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def publication_contract(
    manifest: Path, packet: int, stage: str, timeout: float = 600
) -> dict:
    workspace = marked_root(manifest)
    return {
        "identity": uuid.uuid4().hex,
        "deadline": time.time() + timeout,
        "workspace": str(workspace),
        "manifest": str(manifest.resolve()),
        "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        "packet": packet,
        "stage": stage,
    }


def marked_root(path: Path) -> Path:
    from .workspace import WORKSPACE_MARKER, _read_marker

    resolved = path.resolve()
    for root in (resolved, *resolved.parents):
        if (root / WORKSPACE_MARKER).is_file():
            _read_marker(root)
            return root
    raise ValueError("publication requires a marked workspace")


def check_contract(queue: Path, request: dict) -> None:
    contract = request["publication_contract"]
    workspace = Path(contract["workspace"]).resolve()
    if (
        marked_root(Path(contract["manifest"])) != workspace
        or marked_root(queue) != workspace
    ):
        raise ValueError("queue and manifest must share the marked workspace")


def attempt_directory(queue: Path, stage: str, packet: int, attempt: int) -> Path:
    if stage not in {"discovery", "semantic", "reference", "occurrence"} or any(
        type(n) is not int or n < 1 for n in (packet, attempt)
    ):
        raise ValueError("invalid stage, packet or attempt")
    root = queue.resolve()
    candidate = root / stage / f"packet-{packet:03d}-attempt-{attempt}"
    if not candidate.resolve().is_relative_to(root):
        raise ValueError("attempt escapes queue root")
    return candidate


def validate(request: dict, response: object) -> None:
    contract = request["publication_contract"]
    manifest_path = Path(contract["manifest"])
    raw = manifest_path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != contract["manifest_sha256"]:
        raise ContractError("validation manifest changed")
    manifest = json.loads(raw)
    packet = contract["packet"]
    if (
        request["packet"]["packet"] != packet
        or request["packet"]["stage"] != contract["stage"]
    ):
        raise ContractError("attempt packet identity mismatch")
    canonical = normalize_response(manifest, packet, response)
    validate_packet_response(
        manifest, canonical, stage=contract["stage"], packet_ordinal=packet
    )
    correction = request.get("correction")
    if correction:
        before = valid_response_items(manifest, packet, correction.get("response"))
        after = valid_response_items(manifest, packet, response)
        if any(after.get(item) != row for item, row in before.items()):
            raise ReviewPacketError("correction changed a previously valid item")


def publish(
    queue: Path, stage: str, packet: int, attempt: int, identity: str, raw: bytes
) -> dict:
    directory = attempt_directory(queue, stage, packet, attempt)
    request = read_json(directory / "request.json")
    check_contract(queue, request)
    if (
        request.get("attempt") != attempt
        or request["packet"]["packet"] != packet
        or request["packet"]["stage"] != stage
    ):
        raise ValueError("request does not match attempt directory")
    if request["publication_contract"]["identity"] != identity:
        raise ValueError("stale attempt identity")
    # Retain precisely what the worker submitted, even when parsing fails.
    submission = uuid.uuid4().hex
    atomic_create(directory / f"submission-{submission}.json", raw)
    error = None
    fatal = False
    try:
        response = json.loads(raw)
        validate(request, response)
        serialized = dumps(response)
    except (ValueError, TypeError, KeyError, IndexError, OSError) as exc:
        error = str(exc)
        fatal = isinstance(exc, ContractError | OSError)
        serialized = raw
    with locked(directory):
        state = read_json(directory / "attempt.json")
        if state["identity"] != identity or time.time() >= min(
            state["deadline"], request["publication_contract"]["deadline"]
        ):
            raise ValueError("attempt expired")
        if (directory / "expired.json").exists() or (
            directory / "result.json"
        ).exists():
            raise ValueError("attempt already terminal; publication refused")
        result = {
            "identity": identity,
            "submission": submission,
            "error": error,
            "fatal": fatal,
            "sha256": hashlib.sha256(serialized).hexdigest(),
            "published_at": time.time(),
            "status": "rejected" if error else "validated",
        }
        atomic_create(directory / f"response-{submission}.committed.json", serialized)
        atomic_create(directory / "result.json", dumps(result))
        return result


def consume(directory: Path) -> tuple[bytes, dict] | None:
    with locked(directory):
        if not (directory / "result.json").exists():
            return None
        result = read_json(directory / "result.json")
        state = read_json(directory / "attempt.json")
        request = read_json(directory / "request.json")
        if (
            result["identity"] != state["identity"]
            or result["identity"] != request["publication_contract"]["identity"]
        ):
            raise ValueError("committed attempt identity mismatch")
        if (
            result["published_at"] >= state["deadline"]
            or (directory / "expired.json").exists()
        ):
            raise ValueError("committed attempt expired")
        raw = (
            directory / f"response-{result['submission']}.committed.json"
        ).read_bytes()
        if hashlib.sha256(raw).hexdigest() != result["sha256"]:
            raise ValueError("committed response changed after publication")
        # Retained consumption is authoritative even if external code later tampers.
        if not (directory / "consumed.json").exists():
            if (directory / "consumed.payload").exists():
                if (directory / "consumed.payload").read_bytes() != raw:
                    raise ValueError("consumed response is immutable")
            else:
                atomic_create(directory / "consumed.payload", raw)
            atomic_create(
                directory / "consumed.json",
                dumps({**result, "consumed_at": time.time()}),
            )
        elif (directory / "consumed.payload").read_bytes() != raw:
            raise ValueError("consumed response is immutable")
        return raw, result


def expire(directory: Path) -> None:
    with locked(directory):
        if (
            not (directory / "result.json").exists()
            and not (directory / "expired.json").exists()
        ):
            atomic_create(
                directory / "expired.json", dumps({"expired_at": time.time()})
            )
