"""Immutable Definition Check matter snapshots and bounded projections.

The existing schema 0.12.0 ledger remains the canonical single-document output.
This module is an additive, standard-library-only migration path to the matter
snapshot contract.  It never extracts archive members to disk.
"""

from __future__ import annotations

import copy
import hashlib
import html
import json
import os
import posixpath
import re
import tempfile
import zipfile
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any

from .term_identity import term_key

MATTER_SCHEMA_VERSION = "1.1.0"
LEGACY_SCHEMA_VERSION = "0.12.0"
SUPPORTED_LEDGER_SCHEMA_VERSIONS = {LEGACY_SCHEMA_VERSION, "0.13.0", "0.14.0"}
SNAPSHOT_MEDIA_TYPE = "application/vnd.legalquants.definition-check+zip"
MANIFEST_PATH = "manifest.json"
MAX_MEMBERS = 256
MAX_MEMBER_BYTES = 16 * 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024
MAX_COMPRESSION_RATIO = 100.0

DOCUMENT_ROLES = frozenset(
    {
        "agreement",
        "schedule",
        "exhibit",
        "amendment",
        "ancillary",
        "incorporated_document",
        "precedent",
        "other",
    }
)
RELATIONSHIP_TYPES = frozenset(
    {
        "schedule_of",
        "exhibit_to",
        "amends",
        "incorporates",
        "ancillary_to",
        "precedent_for",
    }
)
COMPONENT_ROLES = frozenset(
    {
        "document_metadata",
        "canonical_defined_term_registry",
        "canonical_usage_index",
        "document_findings",
        "lexical_observations",
        "candidate_proposals",
        "adjudications",
        "review_provenance",
        "version_lineage",
        "cross_document_findings",
    }
)
PUBLIC_COMPONENT_ROLES = frozenset(
    {
        "document_metadata",
        "canonical_defined_term_registry",
        "canonical_usage_index",
        "document_findings",
        "version_lineage",
        "cross_document_findings",
    }
)
COMPLETION_STATES = frozenset({"complete", "incomplete", "failed"})
COMPARISON_STATES = frozenset(
    {
        "added",
        "removed",
        "renamed",
        "moved",
        "materially_changed",
        "unchanged",
        "changed_usage",
        "unresolved",
    }
)
CROSS_DOCUMENT_STATES = frozenset(
    {
        "valid_cross_document_definition",
        "conflicting_definitions",
        "missing_selected_companion",
        "broken_selected_scope_reference",
        "out_of_scope",
        "unresolved",
    }
)
ID_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,127}$")


class MatterSnapshotError(ValueError):
    """Raised when a matter snapshot cannot be trusted or projected."""


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _jsonl_bytes(rows: Iterable[object]) -> bytes:
    return b"".join(_json_bytes(row) for row in rows)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def snapshot_sha256(path: str | os.PathLike[str]) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def qualified_id(
    matter_id: str, document_id: str, version_id: str, local_id: str
) -> str:
    """Return a collision-resistant, reproducible ID retaining its local suffix."""

    for label, value in (
        ("matter_id", matter_id),
        ("document_id", document_id),
        ("version_id", version_id),
        ("local_id", local_id),
    ):
        _require_id(value, label)
    digest = hashlib.sha256(
        "\x1f".join((matter_id, document_id, version_id, local_id)).encode("utf-8")
    ).hexdigest()[:20]
    return f"qid:{digest}:{local_id}"


def qualify_location(
    location: Mapping[str, Any],
    *,
    matter_id: str,
    document_id: str,
    version_id: str,
) -> dict[str, Any]:
    result = copy.deepcopy(dict(location))
    result.update(
        {
            "matter_id": matter_id,
            "document_id": document_id,
            "version_id": version_id,
        }
    )
    _validate_location(result)
    return result


def _require_id(value: object, label: str) -> str:
    if not isinstance(value, str) or not ID_PATTERN.fullmatch(value):
        raise MatterSnapshotError(f"{label} is not a valid stable identifier")
    return value


def _require_string(value: object, label: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise MatterSnapshotError(f"{label} must be a non-empty string")
    return value


def _require_array(value: object, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise MatterSnapshotError(f"{label} must be an array")
    return value


def _require_keys(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    missing = expected - set(value)
    extra = set(value) - expected
    if missing or extra:
        raise MatterSnapshotError(f"{label} fields are incomplete or unsupported")


def _safe_member_path(value: object) -> str:
    path = _require_string(value, "component path")
    if (
        "\\" in path
        or "\x00" in path
        or path.startswith("/")
        or re.match(r"^[A-Za-z]:/", path)
    ):
        raise MatterSnapshotError("component path must be normalized and relative")
    pure = PurePosixPath(path)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise MatterSnapshotError("component path must be normalized and relative")
    normalized = posixpath.normpath(path)
    if normalized != path or normalized == MANIFEST_PATH:
        raise MatterSnapshotError("component path must be unique and normalized")
    return path


def _validate_location(value: object) -> None:
    if not isinstance(value, Mapping):
        raise MatterSnapshotError("qualified location must be an object")
    for field in ("matter_id", "document_id", "version_id", "block_id"):
        _require_id(value.get(field), f"location.{field}")
    _require_string(value.get("part"), "location.part")
    for field in ("block_order", "char_start", "char_end"):
        item = value.get(field)
        if not isinstance(item, int) or isinstance(item, bool) or item < 0:
            raise MatterSnapshotError(
                f"location.{field} must be a non-negative integer"
            )
    if value["char_end"] < value["char_start"]:
        raise MatterSnapshotError("location offsets must be ordered")


def _record_count(path: str, data: bytes) -> int:
    if path.endswith(".jsonl"):
        rows = [line for line in data.splitlines() if line.strip()]
        for line in rows:
            try:
                json.loads(line)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise MatterSnapshotError(f"invalid JSONL component: {path}") from exc
        return len(rows)
    try:
        value = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MatterSnapshotError(f"invalid JSON component: {path}") from exc
    if isinstance(value, list):
        return len(value)
    if isinstance(value, dict):
        for key in ("records", "definitions", "findings", "mappings"):
            if isinstance(value.get(key), list):
                return len(value[key])
        return 1
    raise MatterSnapshotError(f"component must contain a JSON object or array: {path}")


def _decode_component(path: str, data: bytes) -> Any:
    try:
        if path.endswith(".jsonl"):
            return [json.loads(line) for line in data.splitlines() if line.strip()]
        return json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MatterSnapshotError(f"component is not valid UTF-8 JSON: {path}") from exc


def _component_bytes(path: str, value: object) -> bytes:
    if isinstance(value, bytes):
        data = value
    elif path.endswith(".jsonl"):
        if not isinstance(value, list):
            raise MatterSnapshotError(
                f"JSONL component must be an array of rows: {path}"
            )
        data = _jsonl_bytes(value)
    else:
        data = _json_bytes(value)
    _record_count(path, data)
    return data


def _component_path(document_id: str, version_id: str, leaf: str) -> str:
    return f"documents/{document_id}/{version_id}/{leaf}"


def validate_manifest(manifest: object) -> dict[str, Any]:
    if not isinstance(manifest, dict):
        raise MatterSnapshotError("manifest must be a JSON object")
    _require_keys(
        manifest,
        {
            "schema_version",
            "media_type",
            "matter",
            "snapshot",
            "scope",
            "documents",
            "document_versions",
            "document_relationships",
            "components",
        },
        "manifest",
    )
    if manifest.get("schema_version") != MATTER_SCHEMA_VERSION:
        raise MatterSnapshotError("unsupported matter snapshot schema version")
    if manifest.get("media_type") != SNAPSHOT_MEDIA_TYPE:
        raise MatterSnapshotError("unsupported matter snapshot media type")

    matter = manifest.get("matter")
    snapshot = manifest.get("snapshot")
    scope = manifest.get("scope")
    if (
        not isinstance(matter, dict)
        or not isinstance(snapshot, dict)
        or not isinstance(scope, dict)
    ):
        raise MatterSnapshotError("manifest matter, snapshot, and scope are required")
    _require_keys(matter, {"matter_id", "matter_type", "display_name"}, "matter")
    _require_keys(
        snapshot,
        {
            "snapshot_id",
            "created_at",
            "parent_snapshot_sha256",
            "completion_state",
        },
        "snapshot",
    )
    _require_keys(
        scope,
        {
            "primary_document_version_id",
            "selected_document_version_ids",
            "missing_selected_companions",
        },
        "scope",
    )
    matter_id = _require_id(matter.get("matter_id"), "matter_id")
    _require_string(matter.get("matter_type"), "matter_type")
    _require_string(matter.get("display_name"), "matter.display_name")
    _require_id(snapshot.get("snapshot_id"), "snapshot_id")
    _require_string(snapshot.get("created_at"), "snapshot.created_at")
    if not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z",
        snapshot["created_at"],
    ):
        raise MatterSnapshotError(
            "snapshot.created_at must be an RFC 3339 UTC timestamp"
        )
    parent_hash = snapshot.get("parent_snapshot_sha256")
    if parent_hash is not None and (
        not isinstance(parent_hash, str)
        or not re.fullmatch(r"[0-9a-f]{64}", parent_hash)
    ):
        raise MatterSnapshotError("parent snapshot hash is invalid")
    if snapshot.get("completion_state") not in COMPLETION_STATES:
        raise MatterSnapshotError("snapshot completion state is invalid")
    for missing_companion in _require_array(
        scope.get("missing_selected_companions"),
        "scope.missing_selected_companions",
    ):
        _require_string(missing_companion, "missing selected companion")

    documents = _require_array(manifest.get("documents"), "documents")
    versions = _require_array(manifest.get("document_versions"), "document_versions")
    relationships = _require_array(
        manifest.get("document_relationships"), "document_relationships"
    )
    components = _require_array(manifest.get("components"), "components")
    if not documents or not versions or not components:
        raise MatterSnapshotError(
            "snapshot must declare documents, versions, and components"
        )

    document_by_id: dict[str, dict[str, Any]] = {}
    family_by_document: dict[str, str] = {}
    for item in documents:
        if not isinstance(item, dict):
            raise MatterSnapshotError("document declaration must be an object")
        _require_keys(
            item,
            {"document_id", "document_family_id", "role", "display_name"},
            "document",
        )
        document_id = _require_id(item.get("document_id"), "document_id")
        if document_id in document_by_id:
            raise MatterSnapshotError("document IDs must be unique")
        family_id = _require_id(item.get("document_family_id"), "document_family_id")
        if item.get("role") not in DOCUMENT_ROLES:
            raise MatterSnapshotError("unsupported document role")
        _require_string(item.get("display_name"), "document display_name")
        document_by_id[document_id] = item
        family_by_document[document_id] = family_id

    version_by_id: dict[str, dict[str, Any]] = {}
    for item in versions:
        if not isinstance(item, dict):
            raise MatterSnapshotError("document version declaration must be an object")
        _require_keys(
            item,
            {
                "version_id",
                "document_id",
                "parent_version_id",
                "supersedes",
                "source_sha256",
                "status",
            },
            "document version",
        )
        version_id = _require_id(item.get("version_id"), "version_id")
        document_id = _require_id(item.get("document_id"), "version.document_id")
        if version_id in version_by_id or document_id not in document_by_id:
            raise MatterSnapshotError("document version references are invalid")
        source_hash = item.get("source_sha256")
        if source_hash is not None and (
            not isinstance(source_hash, str)
            or not re.fullmatch(r"[0-9a-f]{64}", source_hash)
        ):
            raise MatterSnapshotError("document version source hash is invalid")
        parent = item.get("parent_version_id")
        if parent is not None:
            _require_id(parent, "parent_version_id")
        supersedes = item.get("supersedes")
        if supersedes is not None:
            _require_id(supersedes, "supersedes")
        if item.get("status") not in {"prior", "current", "selected", "unknown"}:
            raise MatterSnapshotError("document version status is invalid")
        version_by_id[version_id] = item

    for item in version_by_id.values():
        for field in ("parent_version_id", "supersedes"):
            parent_id = item.get(field)
            if parent_id is None:
                continue
            parent = version_by_id.get(parent_id)
            if parent is None:
                raise MatterSnapshotError(f"{field} references an unknown version")
            if (
                family_by_document[parent["document_id"]]
                != family_by_document[item["document_id"]]
            ):
                raise MatterSnapshotError(
                    "version lineage must remain within one document family"
                )
        if item.get("parent_version_id") != item.get("supersedes"):
            raise MatterSnapshotError("parent_version_id and supersedes must agree")

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(version_id: str) -> None:
        if version_id in visiting:
            raise MatterSnapshotError("version lineage contains a cycle")
        if version_id in visited:
            return
        visiting.add(version_id)
        parent_id = version_by_id[version_id].get("parent_version_id")
        if parent_id is not None:
            visit(parent_id)
        visiting.remove(version_id)
        visited.add(version_id)

    for version_id in version_by_id:
        visit(version_id)

    selected = _require_array(
        scope.get("selected_document_version_ids"),
        "scope.selected_document_version_ids",
    )
    if (
        not selected
        or len(selected) != len(set(selected))
        or set(selected) - set(version_by_id)
    ):
        raise MatterSnapshotError("selected document-version scope is invalid")
    primary = _require_id(
        scope.get("primary_document_version_id"),
        "scope.primary_document_version_id",
    )
    if primary not in selected:
        raise MatterSnapshotError("primary document version must be selected")

    relationship_ids: set[str] = set()
    for item in relationships:
        if not isinstance(item, dict):
            raise MatterSnapshotError("document relationship must be an object")
        _require_keys(
            item,
            {
                "relationship_id",
                "from_document_id",
                "to_document_id",
                "type",
                "authority",
                "evidence_ids",
            },
            "document relationship",
        )
        relationship_id = _require_id(item.get("relationship_id"), "relationship_id")
        if relationship_id in relationship_ids:
            raise MatterSnapshotError("relationship IDs must be unique")
        relationship_ids.add(relationship_id)
        if item.get("type") not in RELATIONSHIP_TYPES:
            raise MatterSnapshotError("unsupported document relationship type")
        if (
            item.get("from_document_id") not in document_by_id
            or item.get("to_document_id") not in document_by_id
        ):
            raise MatterSnapshotError(
                "document relationship references an unknown document"
            )
        if item.get("from_document_id") == item.get("to_document_id"):
            raise MatterSnapshotError(
                "document relationships must connect distinct documents"
            )
        if item.get("authority") not in {"user_asserted", "reviewed", "unresolved"}:
            raise MatterSnapshotError("document relationship authority is invalid")
        evidence_ids = _require_array(
            item.get("evidence_ids"), "relationship evidence_ids"
        )
        for evidence_id in evidence_ids:
            _require_id(evidence_id, "relationship evidence_id")

    paths: set[str] = set()
    required_roles: dict[str, set[str]] = defaultdict(set)
    for item in components:
        if not isinstance(item, dict):
            raise MatterSnapshotError("component declaration must be an object")
        _require_keys(
            item,
            {
                "path",
                "role",
                "authority",
                "document_id",
                "version_id",
                "sha256",
                "record_count",
            },
            "component",
        )
        path = _safe_member_path(item.get("path"))
        if path in paths:
            raise MatterSnapshotError("component paths must be unique")
        paths.add(path)
        role = item.get("role")
        if role not in COMPONENT_ROLES:
            raise MatterSnapshotError("unsupported component role")
        if not isinstance(item.get("record_count"), int) or item["record_count"] < 0:
            raise MatterSnapshotError("component record count is invalid")
        if not isinstance(item.get("sha256"), str) or not re.fullmatch(
            r"[0-9a-f]{64}", item["sha256"]
        ):
            raise MatterSnapshotError("component hash is invalid")
        document_id = item.get("document_id")
        version_id = item.get("version_id")
        if document_id is not None or version_id is not None:
            if document_id not in document_by_id or version_id not in version_by_id:
                raise MatterSnapshotError("component document/version scope is invalid")
            if version_by_id[version_id]["document_id"] != document_id:
                raise MatterSnapshotError(
                    "component version does not belong to its document"
                )
            if not path.startswith(f"documents/{document_id}/{version_id}/"):
                raise MatterSnapshotError(
                    "component path disagrees with its document version"
                )
            required_roles[version_id].add(role)
        if item.get("authority") not in {"canonical", "provenance", "comparison"}:
            raise MatterSnapshotError("component authority is invalid")

    if snapshot.get("completion_state") == "complete":
        required = {
            "document_metadata",
            "canonical_defined_term_registry",
            "canonical_usage_index",
            "document_findings",
        }
        for selected_version in selected:
            if not required.issubset(required_roles[selected_version]):
                raise MatterSnapshotError(
                    "complete snapshot lacks a required selected-version component"
                )
    if matter_id != manifest.get("matter", {}).get("matter_id"):
        raise MatterSnapshotError("manifest matter identity is inconsistent")
    return manifest


def build_manifest(
    *,
    matter: Mapping[str, Any],
    snapshot: Mapping[str, Any],
    scope: Mapping[str, Any],
    documents: list[dict[str, Any]],
    document_versions: list[dict[str, Any]],
    document_relationships: list[dict[str, Any]],
    component_values: Mapping[str, object],
    component_metadata: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, Any], dict[str, bytes]]:
    components: dict[str, bytes] = {}
    declarations: list[dict[str, Any]] = []
    for path in sorted(component_values):
        safe_path = _safe_member_path(path)
        metadata = dict(component_metadata.get(safe_path, {}))
        if not metadata:
            raise MatterSnapshotError(f"component metadata is missing: {safe_path}")
        data = _component_bytes(safe_path, component_values[safe_path])
        components[safe_path] = data
        declarations.append(
            {
                "path": safe_path,
                "role": metadata.get("role"),
                "authority": metadata.get("authority"),
                "document_id": metadata.get("document_id"),
                "version_id": metadata.get("version_id"),
                "sha256": _sha256(data),
                "record_count": _record_count(safe_path, data),
            }
        )
    manifest = {
        "schema_version": MATTER_SCHEMA_VERSION,
        "media_type": SNAPSHOT_MEDIA_TYPE,
        "matter": copy.deepcopy(dict(matter)),
        "snapshot": copy.deepcopy(dict(snapshot)),
        "scope": copy.deepcopy(dict(scope)),
        "documents": copy.deepcopy(documents),
        "document_versions": copy.deepcopy(document_versions),
        "document_relationships": copy.deepcopy(document_relationships),
        "components": declarations,
    }
    validate_manifest(manifest)
    return manifest, components


def write_snapshot(
    path: str | os.PathLike[str],
    manifest: Mapping[str, Any],
    components: Mapping[str, object],
    *,
    expected_parent_snapshot_sha256: str | None = None,
) -> str:
    """Validate and atomically publish a deterministic immutable snapshot."""

    target = Path(path)
    if target.exists():
        raise MatterSnapshotError("completed matter snapshots are immutable")
    manifest_value = validate_manifest(copy.deepcopy(dict(manifest)))
    parent_hash = manifest_value["snapshot"].get("parent_snapshot_sha256")
    if (
        expected_parent_snapshot_sha256 is not None
        and parent_hash != expected_parent_snapshot_sha256
    ):
        raise MatterSnapshotError("stale parent snapshot linkage")
    component_data = {
        _safe_member_path(component_path): _component_bytes(component_path, value)
        for component_path, value in components.items()
    }
    declared = {item["path"]: item for item in manifest_value["components"]}
    if set(component_data) != set(declared):
        raise MatterSnapshotError("declared and supplied snapshot components differ")
    for component_path, data in component_data.items():
        declaration = declared[component_path]
        if declaration["sha256"] != _sha256(data) or declaration[
            "record_count"
        ] != _record_count(component_path, data):
            raise MatterSnapshotError("component hash or record count is stale")

    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        with zipfile.ZipFile(
            temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
        ) as archive:
            for member_path, data in [
                *sorted(component_data.items()),
                (MANIFEST_PATH, _json_bytes(manifest_value)),
            ]:
                info = zipfile.ZipInfo(member_path, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o600 << 16
                info.create_system = 3
                archive.writestr(
                    info, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9
                )
        read_snapshot(
            temporary,
            expected_parent_snapshot_sha256=expected_parent_snapshot_sha256,
        )
        os.replace(temporary, target)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return snapshot_sha256(target)


def read_snapshot(
    path: str | os.PathLike[str],
    *,
    expected_snapshot_sha256: str | None = None,
    expected_parent_snapshot_sha256: str | None = None,
    max_members: int = MAX_MEMBERS,
    max_member_bytes: int = MAX_MEMBER_BYTES,
    max_total_bytes: int = MAX_TOTAL_BYTES,
    max_compression_ratio: float = MAX_COMPRESSION_RATIO,
) -> dict[str, Any]:
    source = Path(path)
    actual_snapshot_hash = snapshot_sha256(source)
    if (
        expected_snapshot_sha256 is not None
        and actual_snapshot_hash != expected_snapshot_sha256
    ):
        raise MatterSnapshotError("stale or substituted matter snapshot")
    try:
        with zipfile.ZipFile(source, "r") as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            if len(infos) > max_members or len(names) != len(set(names)):
                raise MatterSnapshotError("snapshot has too many or duplicate members")
            for name in names:
                if name == MANIFEST_PATH:
                    continue
                _safe_member_path(name)
            if names.count(MANIFEST_PATH) != 1:
                raise MatterSnapshotError("snapshot must contain exactly one manifest")
            total = 0
            for info in infos:
                if info.is_dir() or info.flag_bits & 0x1:
                    raise MatterSnapshotError(
                        "directories and encrypted members are unsupported"
                    )
                if info.file_size > max_member_bytes:
                    raise MatterSnapshotError("snapshot member exceeds the size limit")
                total += info.file_size
                if total > max_total_bytes:
                    raise MatterSnapshotError("snapshot exceeds the total size limit")
                compressed = max(info.compress_size, 1)
                if info.file_size / compressed > max_compression_ratio:
                    raise MatterSnapshotError(
                        "snapshot member exceeds the compression-ratio limit"
                    )
            manifest = json.loads(archive.read(MANIFEST_PATH))
            validate_manifest(manifest)
            declarations = {item["path"]: item for item in manifest["components"]}
            if set(names) != {MANIFEST_PATH, *declarations}:
                raise MatterSnapshotError(
                    "snapshot contains missing or undeclared members"
                )
            component_bytes: dict[str, bytes] = {}
            component_values: dict[str, Any] = {}
            for member_path, declaration in declarations.items():
                data = archive.read(member_path)
                if _sha256(data) != declaration["sha256"]:
                    raise MatterSnapshotError("snapshot component hash mismatch")
                if _record_count(member_path, data) != declaration["record_count"]:
                    raise MatterSnapshotError(
                        "snapshot component record count mismatch"
                    )
                component_bytes[member_path] = data
                component_values[member_path] = _decode_component(member_path, data)
    except MatterSnapshotError:
        raise
    except (OSError, KeyError, ValueError, zipfile.BadZipFile, RuntimeError) as exc:
        raise MatterSnapshotError("snapshot is corrupt or unreadable") from exc
    parent_hash = manifest["snapshot"].get("parent_snapshot_sha256")
    if (
        expected_parent_snapshot_sha256 is not None
        and parent_hash != expected_parent_snapshot_sha256
    ):
        raise MatterSnapshotError("stale parent snapshot linkage")
    _validate_component_references(manifest, component_values)
    return {
        "manifest": manifest,
        "components": component_values,
        "component_bytes": component_bytes,
        "snapshot_sha256": actual_snapshot_hash,
    }


def _walk_locations(value: object) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        if {
            "matter_id",
            "document_id",
            "version_id",
            "block_id",
            "part",
            "block_order",
            "char_start",
            "char_end",
        }.issubset(value):
            yield value
        for child in value.values():
            yield from _walk_locations(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_locations(child)


def _validate_component_references(
    manifest: Mapping[str, Any], components: Mapping[str, Any]
) -> None:
    matter_id = manifest["matter"]["matter_id"]
    version_to_document = {
        item["version_id"]: item["document_id"]
        for item in manifest["document_versions"]
    }
    ids: set[str] = set()
    by_version_role: dict[tuple[str, str], Any] = {}
    for declaration in manifest["components"]:
        value = components[declaration["path"]]
        if declaration.get("version_id") is not None:
            key = (declaration["version_id"], declaration["role"])
            if key in by_version_role:
                raise MatterSnapshotError(
                    "document-version component roles must be unique"
                )
            by_version_role[key] = value
        for location in _walk_locations(value):
            _validate_location(location)
            if location["matter_id"] != matter_id:
                raise MatterSnapshotError("component location has the wrong matter")
            if (
                version_to_document.get(location["version_id"])
                != location["document_id"]
            ):
                raise MatterSnapshotError(
                    "component location has the wrong document version"
                )
        rows = value if isinstance(value, list) else []
        if isinstance(value, dict):
            for field in ("definitions", "findings", "records", "mappings"):
                if isinstance(value.get(field), list):
                    rows.extend(value[field])
        for row in rows:
            if not isinstance(row, dict):
                continue
            row_id = row.get("qualified_id") or row.get("id")
            if isinstance(row_id, str) and row_id.startswith("qid:"):
                if row_id in ids:
                    raise MatterSnapshotError("qualified record IDs must be unique")
                ids.add(row_id)
                local_id = row.get("local_id") or row.get("id") or row.get("review_id")
                declaration_document = declaration.get("document_id")
                declaration_version = declaration.get("version_id")
                if (
                    isinstance(local_id, str)
                    and declaration_document is not None
                    and declaration_version is not None
                    and row_id
                    != qualified_id(
                        matter_id,
                        declaration_document,
                        declaration_version,
                        local_id,
                    )
                ):
                    raise MatterSnapshotError("qualified record ID is not reproducible")

    def normalize(value: object) -> str:
        return term_key(str(value))

    for version_id in manifest["scope"]["selected_document_version_ids"]:
        registry = by_version_role.get((version_id, "canonical_defined_term_registry"))
        usages = by_version_role.get((version_id, "canonical_usage_index"))
        adjudications = by_version_role.get((version_id, "adjudications"), [])
        if not isinstance(registry, dict) or not isinstance(usages, list):
            raise MatterSnapshotError("selected version lacks canonical records")
        definitions = registry.get("definitions")
        if not isinstance(definitions, list):
            raise MatterSnapshotError("defined-term registry is invalid")
        accepted_terms: set[str] = set()
        definition_ids: set[str] = set()
        for definition in definitions:
            if not isinstance(definition, dict):
                raise MatterSnapshotError("defined-term registry record is invalid")
            definition_ids.add(_require_string(definition.get("id"), "definition id"))
            accepted_terms.add(normalize(definition.get("normalized_term")))
            accepted_terms.update(
                normalize(alias) for alias in definition.get("aliases", [])
            )
            if not list(_walk_locations(definition)):
                raise MatterSnapshotError(
                    "accepted definition lacks exact qualified evidence"
                )
        adjudication_by_id = {
            item.get("id"): item
            for item in adjudications
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        }
        for adjudication_id in registry.get("authorized_by_adjudication_ids", []):
            decision = adjudication_by_id.get(adjudication_id, {}).get("decision")
            if decision not in {"confirmed_defined", "confirmed_alias"}:
                raise MatterSnapshotError(
                    "defined-term registry lacks accepted adjudication authority"
                )
        if definitions and not registry.get("authorized_by_adjudication_ids"):
            raise MatterSnapshotError(
                "accepted definitions require adjudication authority"
            )
        for usage in usages:
            if (
                not isinstance(usage, dict)
                or normalize(usage.get("normalized_term")) not in accepted_terms
            ):
                raise MatterSnapshotError(
                    "authoritative usage index references a non-accepted term"
                )
            if not list(_walk_locations(usage)):
                raise MatterSnapshotError(
                    "authoritative usage lacks exact qualified evidence"
                )


def _qualified_record(
    value: Mapping[str, Any], matter_id: str, document_id: str, version_id: str
) -> dict[str, Any]:
    result = copy.deepcopy(dict(value))
    local_id = result.get("id") or result.get("review_id")
    if isinstance(local_id, str):
        result["local_id"] = local_id
        result["qualified_id"] = qualified_id(
            matter_id, document_id, version_id, local_id
        )
    for key, child in list(result.items()):
        if key == "location" and isinstance(child, Mapping):
            result[key] = qualify_location(
                child,
                matter_id=matter_id,
                document_id=document_id,
                version_id=version_id,
            )
        elif key in {
            "locations",
            "evidence",
            "competing_locations",
            "definition_spans",
        } and isinstance(child, list):
            updated = []
            for item in child:
                if (
                    key == "definition_spans"
                    and isinstance(item, Mapping)
                    and isinstance(item.get("location"), Mapping)
                ):
                    span = copy.deepcopy(dict(item))
                    span["location"] = qualify_location(
                        item["location"],
                        matter_id=matter_id,
                        document_id=document_id,
                        version_id=version_id,
                    )
                    updated.append(span)
                elif isinstance(item, Mapping):
                    updated.append(
                        qualify_location(
                            item,
                            matter_id=matter_id,
                            document_id=document_id,
                            version_id=version_id,
                        )
                    )
                else:
                    updated.append(item)
            result[key] = updated
        elif isinstance(child, dict):
            result[key] = _qualify_nested_locations(
                child, matter_id, document_id, version_id
            )
    return result


def _qualify_nested_locations(
    value: object, matter_id: str, document_id: str, version_id: str
) -> Any:
    if isinstance(value, list):
        return [
            _qualify_nested_locations(item, matter_id, document_id, version_id)
            for item in value
        ]
    if not isinstance(value, dict):
        return copy.deepcopy(value)
    if {"part", "block_id", "block_order", "char_start", "char_end"}.issubset(value):
        return qualify_location(
            value,
            matter_id=matter_id,
            document_id=document_id,
            version_id=version_id,
        )
    return {
        key: _qualify_nested_locations(child, matter_id, document_id, version_id)
        for key, child in value.items()
    }


def import_legacy_ledger(
    ledger: Mapping[str, Any],
    *,
    matter_id: str,
    document_id: str,
    version_id: str,
    snapshot_id: str,
    created_at: str,
    matter_display_name: str | None = None,
    parent_snapshot_sha256: str | None = None,
) -> tuple[dict[str, Any], dict[str, bytes]]:
    """Import one complete 0.12.0 ledger without making the snapshot canonical."""

    value = copy.deepcopy(dict(ledger))
    if value.get("schema_version") not in SUPPORTED_LEDGER_SCHEMA_VERSIONS:
        raise MatterSnapshotError("only complete schema 0.12.0 ledgers can be imported")
    required = {
        "engine_version",
        "run_status",
        "capability_profile",
        "source",
        "methods_run",
        "methods_not_run",
        "definitions",
        "term_variants",
        "usages",
        "findings",
        "evidence",
        "lexical_observations",
        "candidate_proposals",
        "context_requests",
        "review_traces",
        "term_candidates",
        "semantic_adjudications",
        "semantic_review",
        "occurrence_candidates",
        "occurrence_collisions",
        "occurrence_adjudications",
        "occurrence_review",
        "reference_candidates",
        "reference_adjudications",
        "reference_review",
        "limitations",
    }
    if set(value) != {"schema_version", *required}:
        raise MatterSnapshotError("legacy ledger fields are incomplete or unsupported")
    if value.get("run_status") not in {"completed", "completed_reduced_assurance"}:
        raise MatterSnapshotError(
            "incomplete legacy ledgers cannot become complete snapshots"
        )
    for summary_name, queue_name, decision_name in (
        ("semantic_review", "term_candidates", "semantic_adjudications"),
        ("occurrence_review", "occurrence_candidates", "occurrence_adjudications"),
        ("reference_review", "reference_candidates", "reference_adjudications"),
    ):
        summary = value.get(summary_name)
        if not isinstance(summary, dict) or summary.get("status") != "complete":
            raise MatterSnapshotError(f"legacy {summary_name} is not complete")
        if summary.get("queue_count") != len(value[queue_name]) or summary.get(
            "decided_count"
        ) != len(value[decision_name]):
            raise MatterSnapshotError(f"legacy {summary_name} counts are inconsistent")

    for label, stable in (
        ("matter_id", matter_id),
        ("document_id", document_id),
        ("version_id", version_id),
        ("snapshot_id", snapshot_id),
    ):
        _require_id(stable, label)
    source = value["source"]
    if not isinstance(source, dict):
        raise MatterSnapshotError("legacy source is invalid")

    def qualify(row: Mapping[str, Any]) -> dict[str, Any]:
        return _qualified_record(row, matter_id, document_id, version_id)

    registry_path = _component_path(
        document_id, version_id, "defined-term-registry.json"
    )
    usage_path = _component_path(document_id, version_id, "usage-index.jsonl")
    findings_path = _component_path(document_id, version_id, "findings.json")
    metadata_path = _component_path(document_id, version_id, "document-metadata.json")
    provenance_base = _component_path(document_id, version_id, "review-provenance")

    definition_rows = [qualify(item) for item in value["definitions"]]
    usage_rows = [qualify(item) for item in value["usages"]]
    finding_rows = [qualify(item) for item in value["findings"]]
    mapping: dict[str, str] = {}
    for key in (
        "definitions",
        "term_variants",
        "usages",
        "findings",
        "evidence",
        "lexical_observations",
        "candidate_proposals",
        "context_requests",
        "review_traces",
        "term_candidates",
        "semantic_adjudications",
        "occurrence_candidates",
        "occurrence_collisions",
        "occurrence_adjudications",
        "reference_candidates",
        "reference_adjudications",
    ):
        for row in value[key]:
            local_id = row.get("id") or row.get("review_id")
            if isinstance(local_id, str):
                mapping[local_id] = qualified_id(
                    matter_id, document_id, version_id, local_id
                )

    component_values: dict[str, object] = {
        metadata_path: {
            "legacy_schema_version": value["schema_version"],
            "engine_version": value["engine_version"],
            "run_status": value["run_status"],
            "capability_profile": value["capability_profile"],
            "source": source,
            "methods_run": value["methods_run"],
            "methods_not_run": value["methods_not_run"],
            "review_completion": {
                "semantic_review": value["semantic_review"],
                "occurrence_review": value["occurrence_review"],
                "reference_review": value["reference_review"],
            },
            "limitations": value["limitations"],
            "legacy_id_mappings": mapping,
        },
        registry_path: {
            "schema_version": MATTER_SCHEMA_VERSION,
            "matter_id": matter_id,
            "document_id": document_id,
            "version_id": version_id,
            "authority": "accepted_definitions_only",
            "definitions": definition_rows,
            "term_variants": [qualify(item) for item in value["term_variants"]],
            "authorized_by_adjudication_ids": [
                item.get("id")
                for item in value["semantic_adjudications"]
                if item.get("decision") in {"confirmed_defined", "confirmed_alias"}
            ],
        },
        usage_path: usage_rows,
        findings_path: {
            "schema_version": MATTER_SCHEMA_VERSION,
            "matter_id": matter_id,
            "document_id": document_id,
            "version_id": version_id,
            "findings": finding_rows,
            "evidence": [qualify(item) for item in value["evidence"]],
        },
        f"{provenance_base}/lexical-observations.jsonl": [
            qualify(item) for item in value["lexical_observations"]
        ],
        f"{provenance_base}/candidate-proposals.jsonl": [
            qualify(item) for item in value["candidate_proposals"]
        ],
        f"{provenance_base}/adjudications.jsonl": [
            *[qualify(item) for item in value["semantic_adjudications"]],
            *[qualify(item) for item in value["occurrence_adjudications"]],
            *[qualify(item) for item in value["reference_adjudications"]],
        ],
        f"{provenance_base}/review-provenance.json": {
            "context_requests": [qualify(item) for item in value["context_requests"]],
            "review_traces": [qualify(item) for item in value["review_traces"]],
            "term_candidates": [qualify(item) for item in value["term_candidates"]],
            "occurrence_candidates": [
                qualify(item) for item in value["occurrence_candidates"]
            ],
            "occurrence_collisions": [
                qualify(item) for item in value["occurrence_collisions"]
            ],
            "reference_candidates": [
                qualify(item) for item in value["reference_candidates"]
            ],
        },
    }
    metadata: dict[str, Mapping[str, Any]] = {
        metadata_path: {
            "role": "document_metadata",
            "authority": "canonical",
            "document_id": document_id,
            "version_id": version_id,
        },
        registry_path: {
            "role": "canonical_defined_term_registry",
            "authority": "canonical",
            "document_id": document_id,
            "version_id": version_id,
        },
        usage_path: {
            "role": "canonical_usage_index",
            "authority": "canonical",
            "document_id": document_id,
            "version_id": version_id,
        },
        findings_path: {
            "role": "document_findings",
            "authority": "canonical",
            "document_id": document_id,
            "version_id": version_id,
        },
        f"{provenance_base}/lexical-observations.jsonl": {
            "role": "lexical_observations",
            "authority": "provenance",
            "document_id": document_id,
            "version_id": version_id,
        },
        f"{provenance_base}/candidate-proposals.jsonl": {
            "role": "candidate_proposals",
            "authority": "provenance",
            "document_id": document_id,
            "version_id": version_id,
        },
        f"{provenance_base}/adjudications.jsonl": {
            "role": "adjudications",
            "authority": "provenance",
            "document_id": document_id,
            "version_id": version_id,
        },
        f"{provenance_base}/review-provenance.json": {
            "role": "review_provenance",
            "authority": "provenance",
            "document_id": document_id,
            "version_id": version_id,
        },
    }
    return build_manifest(
        matter={
            "matter_id": matter_id,
            "matter_type": "deal",
            "display_name": matter_display_name or source.get("name") or document_id,
        },
        snapshot={
            "snapshot_id": snapshot_id,
            "created_at": created_at,
            "parent_snapshot_sha256": parent_snapshot_sha256,
            "completion_state": "complete",
        },
        scope={
            "primary_document_version_id": version_id,
            "selected_document_version_ids": [version_id],
            "missing_selected_companions": [],
        },
        documents=[
            {
                "document_id": document_id,
                "document_family_id": f"family:{document_id}",
                "role": "agreement",
                "display_name": source.get("name") or document_id,
            }
        ],
        document_versions=[
            {
                "version_id": version_id,
                "document_id": document_id,
                "parent_version_id": None,
                "supersedes": None,
                "source_sha256": source.get("sha256"),
                "status": "current",
            }
        ],
        document_relationships=[],
        component_values=component_values,
        component_metadata=metadata,
    )


def assemble_legacy_ledgers(
    entries: Sequence[Mapping[str, Any]],
    *,
    matter: Mapping[str, Any],
    snapshot: Mapping[str, Any],
    scope: Mapping[str, Any],
    document_relationships: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, bytes]]:
    """Assemble completed legacy ledgers into one declared immutable matter."""

    if not entries:
        raise MatterSnapshotError(
            "matter assembly requires at least one document version"
        )
    matter_id = _require_id(matter.get("matter_id"), "matter_id")
    documents: dict[str, dict[str, Any]] = {}
    versions: list[dict[str, Any]] = []
    component_values: dict[str, object] = {}
    component_metadata: dict[str, Mapping[str, Any]] = {}
    for entry in entries:
        ledger = entry.get("ledger")
        if not isinstance(ledger, Mapping):
            raise MatterSnapshotError("matter assembly ledger must be a JSON object")
        document_id = _require_id(entry.get("document_id"), "document_id")
        version_id = _require_id(entry.get("version_id"), "version_id")
        document = {
            "document_id": document_id,
            "document_family_id": _require_id(
                entry.get("document_family_id"), "document_family_id"
            ),
            "role": entry.get("role"),
            "display_name": _require_string(
                entry.get("display_name"), "document display_name"
            ),
        }
        if document_id in documents and documents[document_id] != document:
            raise MatterSnapshotError("document declarations disagree across versions")
        documents[document_id] = document
        imported_manifest, imported_components = import_legacy_ledger(
            ledger,
            matter_id=matter_id,
            document_id=document_id,
            version_id=version_id,
            snapshot_id=_require_id(snapshot.get("snapshot_id"), "snapshot_id"),
            created_at=_require_string(
                snapshot.get("created_at"), "snapshot.created_at"
            ),
            matter_display_name=_require_string(
                matter.get("display_name"), "matter.display_name"
            ),
            parent_snapshot_sha256=snapshot.get("parent_snapshot_sha256"),
        )
        if set(component_values) & set(imported_components):
            raise MatterSnapshotError("document-version component paths collide")
        component_values.update(imported_components)
        for declaration in imported_manifest["components"]:
            component_metadata[declaration["path"]] = {
                "role": declaration["role"],
                "authority": declaration["authority"],
                "document_id": declaration["document_id"],
                "version_id": declaration["version_id"],
            }
        versions.append(
            {
                "version_id": version_id,
                "document_id": document_id,
                "parent_version_id": entry.get("parent_version_id"),
                "supersedes": entry.get("supersedes"),
                "source_sha256": ledger.get("source", {}).get("sha256"),
                "status": entry.get("status", "selected"),
            }
        )
    return build_manifest(
        matter=matter,
        snapshot=snapshot,
        scope=scope,
        documents=list(documents.values()),
        document_versions=versions,
        document_relationships=document_relationships,
        component_values=component_values,
        component_metadata=component_metadata,
    )


def derive_snapshot(
    source_snapshot: Mapping[str, Any],
    *,
    snapshot_id: str,
    created_at: str,
    version_comparison: Mapping[str, Any] | None = None,
    companion_review: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, bytes]]:
    """Create a new manifest/components pair linked to a validated parent."""

    parent_manifest = validate_manifest(copy.deepcopy(source_snapshot.get("manifest")))
    parent_hash = source_snapshot.get("snapshot_sha256")
    if not isinstance(parent_hash, str) or not re.fullmatch(
        r"[0-9a-f]{64}", parent_hash
    ):
        raise MatterSnapshotError("derived snapshot requires a validated parent hash")
    component_values: dict[str, object] = copy.deepcopy(
        dict(source_snapshot.get("components", {}))
    )
    metadata: dict[str, Mapping[str, Any]] = {
        item["path"]: {
            "role": item["role"],
            "authority": item["authority"],
            "document_id": item.get("document_id"),
            "version_id": item.get("version_id"),
        }
        for item in parent_manifest["components"]
    }
    if version_comparison is not None:
        if (
            version_comparison.get("matter_id")
            != parent_manifest["matter"]["matter_id"]
        ):
            raise MatterSnapshotError("version comparison belongs to another matter")
        path = "comparisons/version-lineage.json"
        component_values[path] = copy.deepcopy(dict(version_comparison))
        metadata[path] = {
            "role": "version_lineage",
            "authority": "comparison",
            "document_id": None,
            "version_id": None,
        }
    if companion_review is not None:
        if companion_review.get("matter_id") != parent_manifest["matter"]["matter_id"]:
            raise MatterSnapshotError("companion review belongs to another matter")
        path = "comparisons/cross-document-findings.json"
        component_values[path] = copy.deepcopy(dict(companion_review))
        metadata[path] = {
            "role": "cross_document_findings",
            "authority": "comparison",
            "document_id": None,
            "version_id": None,
        }
    return build_manifest(
        matter=parent_manifest["matter"],
        snapshot={
            "snapshot_id": _require_id(snapshot_id, "snapshot_id"),
            "created_at": _require_string(created_at, "snapshot.created_at"),
            "parent_snapshot_sha256": parent_hash,
            "completion_state": "complete",
        },
        scope=parent_manifest["scope"],
        documents=parent_manifest["documents"],
        document_versions=parent_manifest["document_versions"],
        document_relationships=parent_manifest["document_relationships"],
        component_values=component_values,
        component_metadata=metadata,
    )


def _component_by_role(
    snapshot: Mapping[str, Any], role: str, version_id: str | None = None
) -> list[tuple[dict[str, Any], Any]]:
    result = []
    components = snapshot["components"]
    for declaration in snapshot["manifest"]["components"]:
        if declaration["role"] != role:
            continue
        if version_id is not None and declaration.get("version_id") != version_id:
            continue
        result.append((declaration, components[declaration["path"]]))
    return result


def project_view(
    snapshot: Mapping[str, Any],
    *,
    view_type: str,
    document_id: str | None = None,
    version_id: str | None = None,
    authorized_provenance: bool = False,
) -> dict[str, Any]:
    """Project the smallest authorized typed view from a validated snapshot."""

    manifest = validate_manifest(copy.deepcopy(snapshot.get("manifest")))
    if "components" not in snapshot or "snapshot_sha256" not in snapshot:
        raise MatterSnapshotError("projector requires a fully validated snapshot")
    version_by_id = {item["version_id"]: item for item in manifest["document_versions"]}
    if version_id is None:
        version_id = manifest["scope"]["primary_document_version_id"]
    if version_id not in version_by_id:
        raise MatterSnapshotError("projected version is not declared")
    expected_document_id = version_by_id[version_id]["document_id"]
    if document_id is None:
        document_id = expected_document_id
    if document_id != expected_document_id:
        raise MatterSnapshotError("projected document/version scope is inconsistent")
    if version_id not in manifest["scope"]["selected_document_version_ids"]:
        raise MatterSnapshotError(
            "projector cannot access an unselected document version"
        )

    role_map = {
        "defined_term_registry": ["canonical_defined_term_registry"],
        "usage_index": ["canonical_usage_index"],
        "findings": ["document_findings"],
        "lawyer_report": [
            "document_metadata",
            "canonical_defined_term_registry",
            "canonical_usage_index",
            "document_findings",
            "version_lineage",
            "cross_document_findings",
        ],
        "agent_review": [
            "canonical_defined_term_registry",
            "canonical_usage_index",
            "document_findings",
        ],
        "developer_audit": list(COMPONENT_ROLES),
        "version_comparison": ["version_lineage"],
        "companion_review": ["cross_document_findings"],
    }
    if view_type == "legacy_single_document":
        return project_legacy_ledger(snapshot, version_id=version_id)
    if view_type not in role_map:
        raise MatterSnapshotError("unsupported projector view type")
    if view_type == "developer_audit" and not authorized_provenance:
        raise MatterSnapshotError(
            "developer provenance requires explicit authorization"
        )
    allowed_roles = set(role_map[view_type])
    if not authorized_provenance:
        allowed_roles &= PUBLIC_COMPONENT_ROLES
    projected: list[dict[str, Any]] = []
    for declaration in manifest["components"]:
        if declaration["role"] not in allowed_roles:
            continue
        declared_version = declaration.get("version_id")
        if declared_version is not None and declared_version != version_id:
            continue
        projected.append(
            {
                "role": declaration["role"],
                "document_id": declaration.get("document_id"),
                "version_id": declared_version,
                "records": copy.deepcopy(snapshot["components"][declaration["path"]]),
            }
        )
    return {
        "package_schema": "matter-view-v1",
        "view_type": view_type,
        "authority": "canonical_read_only",
        "matter_id": manifest["matter"]["matter_id"],
        "document_id": document_id,
        "version_id": version_id,
        "snapshot_sha256": snapshot["snapshot_sha256"],
        "selected_document_version_ids": copy.deepcopy(
            manifest["scope"]["selected_document_version_ids"]
        ),
        "missing_selected_companions": copy.deepcopy(
            manifest["scope"].get("missing_selected_companions", [])
        ),
        "components": projected,
    }


def _strip_qualification(value: object) -> Any:
    if isinstance(value, list):
        return [_strip_qualification(item) for item in value]
    if not isinstance(value, dict):
        return copy.deepcopy(value)
    result = {}
    for key, child in value.items():
        if key in {
            "qualified_id",
            "local_id",
            "matter_id",
            "document_id",
            "version_id",
        }:
            continue
        result[key] = _strip_qualification(child)
    return result


def project_legacy_ledger(
    snapshot: Mapping[str, Any], *, version_id: str | None = None
) -> dict[str, Any]:
    """Reproduce the supported 0.12.0 consumer shape from an imported snapshot."""

    manifest = snapshot["manifest"]
    if len(manifest["scope"]["selected_document_version_ids"]) != 1:
        raise MatterSnapshotError(
            "legacy projection requires a single selected version"
        )
    version_id = version_id or manifest["scope"]["primary_document_version_id"]
    metadata_rows = _component_by_role(snapshot, "document_metadata", version_id)
    registry_rows = _component_by_role(
        snapshot, "canonical_defined_term_registry", version_id
    )
    usage_rows = _component_by_role(snapshot, "canonical_usage_index", version_id)
    finding_rows = _component_by_role(snapshot, "document_findings", version_id)
    provenance_rows = _component_by_role(snapshot, "review_provenance", version_id)
    adjudication_rows = _component_by_role(snapshot, "adjudications", version_id)
    lexical_rows = _component_by_role(snapshot, "lexical_observations", version_id)
    proposal_rows = _component_by_role(snapshot, "candidate_proposals", version_id)
    if not all(
        len(rows) == 1
        for rows in (
            metadata_rows,
            registry_rows,
            usage_rows,
            finding_rows,
            provenance_rows,
            adjudication_rows,
            lexical_rows,
            proposal_rows,
        )
    ):
        raise MatterSnapshotError(
            "snapshot lacks a unique legacy compatibility component set"
        )
    metadata = metadata_rows[0][1]
    registry = registry_rows[0][1]
    findings = finding_rows[0][1]
    provenance = provenance_rows[0][1]
    adjudications = adjudication_rows[0][1]
    semantic_ids = {item.get("id") for item in provenance["term_candidates"]}
    semantic = [
        item
        for item in adjudications
        if item.get("review_id")
        in {row.get("review_id") for row in provenance["term_candidates"]}
    ]
    occurrence = [
        item
        for item in adjudications
        if item.get("review_id")
        in {row.get("review_id") for row in provenance["occurrence_candidates"]}
    ]
    reference = [
        item
        for item in adjudications
        if item.get("review_id")
        in {row.get("review_id") for row in provenance["reference_candidates"]}
    ]
    del semantic_ids
    completion = metadata["review_completion"]
    value = {
        "schema_version": metadata["legacy_schema_version"],
        "engine_version": metadata["engine_version"],
        "run_status": metadata["run_status"],
        "capability_profile": metadata["capability_profile"],
        "source": metadata["source"],
        "methods_run": metadata["methods_run"],
        "methods_not_run": metadata["methods_not_run"],
        "definitions": registry["definitions"],
        "term_variants": registry["term_variants"],
        "usages": usage_rows[0][1],
        "findings": findings["findings"],
        "evidence": findings["evidence"],
        "lexical_observations": lexical_rows[0][1],
        "candidate_proposals": proposal_rows[0][1],
        "context_requests": provenance["context_requests"],
        "review_traces": provenance["review_traces"],
        "term_candidates": provenance["term_candidates"],
        "semantic_adjudications": semantic,
        "semantic_review": completion["semantic_review"],
        "occurrence_candidates": provenance["occurrence_candidates"],
        "occurrence_collisions": provenance["occurrence_collisions"],
        "occurrence_adjudications": occurrence,
        "occurrence_review": completion["occurrence_review"],
        "reference_candidates": provenance["reference_candidates"],
        "reference_adjudications": reference,
        "reference_review": completion["reference_review"],
        "limitations": metadata["limitations"],
    }
    projected = _strip_qualification(value)
    # ``source.document_id`` is a legacy field, not matter qualification.
    projected["source"] = copy.deepcopy(metadata["source"])
    return projected


def compare_versions(
    snapshot: Mapping[str, Any],
    *,
    prior_version_id: str,
    current_version_id: str,
    reviewed_mappings: list[Mapping[str, Any]],
) -> dict[str, Any]:
    """Compare two explicitly linked versions using only reviewed term mappings."""

    manifest = snapshot["manifest"]
    versions = {item["version_id"]: item for item in manifest["document_versions"]}
    if prior_version_id not in versions or current_version_id not in versions:
        raise MatterSnapshotError("comparison versions are not declared")
    current = versions[current_version_id]
    if (
        current.get("parent_version_id") != prior_version_id
        or current.get("supersedes") != prior_version_id
    ):
        raise MatterSnapshotError(
            "comparison requires explicit parent/supersedes lineage"
        )
    prior_registry = _component_by_role(
        snapshot, "canonical_defined_term_registry", prior_version_id
    )
    current_registry = _component_by_role(
        snapshot, "canonical_defined_term_registry", current_version_id
    )
    if len(prior_registry) != 1 or len(current_registry) != 1:
        raise MatterSnapshotError(
            "comparison requires complete registries for both versions"
        )
    prior_definitions = {
        item["qualified_id"]: item for item in prior_registry[0][1]["definitions"]
    }
    current_definitions = {
        item["qualified_id"]: item for item in current_registry[0][1]["definitions"]
    }
    used_prior: set[str] = set()
    used_current: set[str] = set()
    records: list[dict[str, Any]] = []
    for mapping in reviewed_mappings:
        state = mapping.get("state")
        if state not in COMPARISON_STATES - {"added", "removed"}:
            raise MatterSnapshotError("term mapping has an invalid reviewed state")
        prior_id = _require_id(
            mapping.get("prior_definition_id"), "prior_definition_id"
        )
        current_id = _require_id(
            mapping.get("current_definition_id"), "current_definition_id"
        )
        if prior_id not in prior_definitions or current_id not in current_definitions:
            raise MatterSnapshotError("term mapping references an unknown definition")
        if prior_id in used_prior or current_id in used_current:
            raise MatterSnapshotError(
                "term mappings must be one-to-one in a comparison"
            )
        evidence = mapping.get("evidence")
        if not isinstance(evidence, list) or len(evidence) < 2:
            raise MatterSnapshotError(
                "term mapping needs exact evidence from both versions"
            )
        evidence_versions = {
            item.get("version_id") for item in evidence if isinstance(item, dict)
        }
        if {prior_version_id, current_version_id} - evidence_versions:
            raise MatterSnapshotError("term mapping evidence must cover both versions")
        for location in evidence:
            _validate_location(location)
        used_prior.add(prior_id)
        used_current.add(current_id)
        records.append(
            {
                "mapping_id": mapping.get("mapping_id")
                or f"mapping:{hashlib.sha256(f'{prior_id}\x1f{current_id}'.encode()).hexdigest()[:20]}",
                "state": state,
                "prior_definition_id": prior_id,
                "current_definition_id": current_id,
                "evidence": copy.deepcopy(evidence),
                "adjudication_id": _require_id(
                    mapping.get("adjudication_id"), "comparison adjudication_id"
                ),
                "reviewer_note": _require_string(
                    mapping.get("reviewer_note"), "comparison reviewer_note"
                ),
            }
        )
    for definition_id, definition in prior_definitions.items():
        if definition_id not in used_prior:
            records.append(
                {
                    "mapping_id": f"removed:{definition_id}",
                    "state": "removed",
                    "prior_definition_id": definition_id,
                    "current_definition_id": None,
                    "evidence": [copy.deepcopy(definition["location"])],
                    "adjudication_id": None,
                    "reviewer_note": "No reviewed mapping to the current version.",
                }
            )
    for definition_id, definition in current_definitions.items():
        if definition_id not in used_current:
            records.append(
                {
                    "mapping_id": f"added:{definition_id}",
                    "state": "added",
                    "prior_definition_id": None,
                    "current_definition_id": definition_id,
                    "evidence": [copy.deepcopy(definition["location"])],
                    "adjudication_id": None,
                    "reviewer_note": "No reviewed mapping from the prior version.",
                }
            )
    state_order = {
        state: index for index, state in enumerate(sorted(COMPARISON_STATES))
    }
    records.sort(key=lambda row: (state_order[row["state"]], row["mapping_id"]))
    return {
        "schema_version": MATTER_SCHEMA_VERSION,
        "view_type": "version_comparison",
        "authority": "reviewed_comparison",
        "matter_id": manifest["matter"]["matter_id"],
        "document_id": current["document_id"],
        "version_id": current_version_id,
        "prior_version_id": prior_version_id,
        "mappings": records,
    }


def review_companions(
    snapshot: Mapping[str, Any],
    *,
    conclusions: list[Mapping[str, Any]],
) -> dict[str, Any]:
    """Validate reviewed conclusions against the explicitly selected matter scope."""

    manifest = snapshot["manifest"]
    selected = set(manifest["scope"]["selected_document_version_ids"])
    versions = {item["version_id"]: item for item in manifest["document_versions"]}
    findings: list[dict[str, Any]] = []
    for conclusion in conclusions:
        state = conclusion.get("state")
        if state not in CROSS_DOCUMENT_STATES:
            raise MatterSnapshotError("unsupported cross-document conclusion")
        affected = conclusion.get("document_version_ids")
        if not isinstance(affected, list) or not affected:
            raise MatterSnapshotError(
                "cross-document conclusion needs affected versions"
            )
        unknown = set(affected) - set(versions)
        if unknown:
            raise MatterSnapshotError(
                "cross-document conclusion references an unknown version"
            )
        outside = set(affected) - selected
        if outside and state != "out_of_scope":
            raise MatterSnapshotError(
                "cross-document review cannot claim an unselected version"
            )
        evidence = conclusion.get("evidence", [])
        if outside and evidence:
            raise MatterSnapshotError(
                "out-of-scope documents cannot contribute reviewed evidence"
            )
        if state not in {"missing_selected_companion", "out_of_scope"} and not evidence:
            raise MatterSnapshotError(
                "cross-document conclusion requires exact evidence"
            )
        for location in evidence:
            _validate_location(location)
            if location["version_id"] not in affected:
                raise MatterSnapshotError(
                    "cross-document evidence is outside the finding scope"
                )
        findings.append(
            {
                "finding_id": _require_id(
                    conclusion.get("finding_id"), "cross-document finding_id"
                ),
                "state": state,
                "document_version_ids": list(affected),
                "evidence": copy.deepcopy(evidence),
                "adjudication_id": conclusion.get("adjudication_id"),
                "reviewer_note": _require_string(
                    conclusion.get("reviewer_note"), "cross-document reviewer_note"
                ),
            }
        )
    return {
        "schema_version": MATTER_SCHEMA_VERSION,
        "view_type": "companion_review",
        "authority": "reviewed_selected_scope_only",
        "matter_id": manifest["matter"]["matter_id"],
        "document_id": versions[manifest["scope"]["primary_document_version_id"]][
            "document_id"
        ],
        "version_id": manifest["scope"]["primary_document_version_id"],
        "selected_document_version_ids": sorted(selected),
        "missing_selected_companions": copy.deepcopy(
            manifest["scope"].get("missing_selected_companions", [])
        ),
        "findings": findings,
        "coverage_statement": "Only the explicitly selected document versions were reviewed.",
    }


def build_review_packet(
    *,
    snapshot_sha256_value: str,
    prompt_sha256: str,
    view_type: str,
    matter_id: str,
    document_id: str,
    version_id: str,
    items: list[dict[str, Any]],
    comparison_version_id: str | None = None,
) -> dict[str, Any]:
    """Build the deliberately versioned, document-aware worker packet contract."""

    for label, value in (
        ("matter_id", matter_id),
        ("document_id", document_id),
        ("version_id", version_id),
    ):
        _require_id(value, label)
    if comparison_version_id is not None:
        _require_id(comparison_version_id, "comparison_version_id")
    for label, value in (
        ("snapshot_sha256", snapshot_sha256_value),
        ("prompt_sha256", prompt_sha256),
    ):
        if not re.fullmatch(r"[0-9a-f]{64}", value):
            raise MatterSnapshotError(f"{label} is invalid")
    packet = {
        "package_schema": "review-packet-v3",
        "view_type": _require_string(view_type, "view_type"),
        "authority": "proposal_only",
        "matter_id": matter_id,
        "document_id": document_id,
        "version_id": version_id,
        "comparison_version_id": comparison_version_id,
        "snapshot_sha256": snapshot_sha256_value,
        "prompt_sha256": prompt_sha256,
        "items": copy.deepcopy(items),
    }
    for ordinal, item in enumerate(packet["items"], start=1):
        if not isinstance(item, dict) or item.get("item_ordinal") != ordinal:
            raise MatterSnapshotError(
                "packet item ordinals must be contiguous from one"
            )
        forbidden = {
            "detector",
            "detector_version",
            "rank",
            "score",
            "confidence",
            "private_manifest",
            "review_trace",
        }
        if forbidden & set(item):
            raise MatterSnapshotError(
                "worker packet contains supervisor-only provenance"
            )
    packet["packet_sha256"] = _sha256(_json_bytes(packet))
    return packet


def validate_review_response(
    packet: Mapping[str, Any],
    response: Mapping[str, Any],
    *,
    current_snapshot_sha256: str,
    current_prompt_sha256: str,
) -> None:
    """Reject stale worker results before supervisor reconciliation."""

    if packet.get("package_schema") != "review-packet-v3":
        raise MatterSnapshotError("unsupported review packet version")
    if packet.get("snapshot_sha256") != current_snapshot_sha256:
        raise MatterSnapshotError("stale review packet snapshot hash")
    if packet.get("prompt_sha256") != current_prompt_sha256:
        raise MatterSnapshotError("stale review packet prompt hash")
    expected_fields = {
        "schema_version",
        "packet_sha256",
        "authority",
        "matter_id",
        "document_id",
        "version_id",
        "comparison_version_id",
        "proposals",
    }
    if set(response) != expected_fields:
        raise MatterSnapshotError(
            "matter review response fields do not match its schema"
        )
    if response.get("schema_version") != "matter-review-response-v1":
        raise MatterSnapshotError("unsupported matter review response version")
    if response.get("packet_sha256") != packet.get("packet_sha256"):
        raise MatterSnapshotError("review response does not match its packet")
    for field in ("matter_id", "document_id", "version_id"):
        if response.get(field) != packet.get(field):
            raise MatterSnapshotError(
                "review response document scope is stale or invalid"
            )
    if response.get("authority") != "proposal_only":
        raise MatterSnapshotError("worker responses cannot claim canonical authority")
    if response.get("comparison_version_id") != packet.get("comparison_version_id"):
        raise MatterSnapshotError(
            "review response comparison scope is stale or invalid"
        )
    proposals = response.get("proposals")
    items = packet.get("items")
    if not isinstance(proposals, list) or not isinstance(items, list):
        raise MatterSnapshotError("review response proposals must be an array")
    if len(proposals) != len(items):
        raise MatterSnapshotError("review response must cover every packet item")
    for expected_ordinal, (item, proposal) in enumerate(
        zip(items, proposals, strict=True), start=1
    ):
        if not isinstance(proposal, Mapping) or set(proposal) != {
            "item_ordinal",
            "decision",
            "evidence",
            "reviewer_note",
        }:
            raise MatterSnapshotError("matter review proposal fields are invalid")
        if proposal.get("item_ordinal") != expected_ordinal:
            raise MatterSnapshotError("review response item order is invalid")
        decision = _require_string(proposal.get("decision"), "proposal.decision")
        allowed_decisions = item.get("allowed_decisions")
        if allowed_decisions is not None and (
            not isinstance(allowed_decisions, list) or decision not in allowed_decisions
        ):
            raise MatterSnapshotError("review response decision is not allowed")
        note = _require_string(proposal.get("reviewer_note"), "proposal.reviewer_note")
        if len(note) > 2000:
            raise MatterSnapshotError("proposal.reviewer_note exceeds 2000 characters")
        evidence = proposal.get("evidence")
        if not isinstance(evidence, list):
            raise MatterSnapshotError("proposal.evidence must be an array")
        seen_evidence = set()
        for location in evidence:
            _validate_location(location)
            if any(
                location.get(field) != response.get(field)
                for field in ("matter_id", "document_id", "version_id")
            ):
                raise MatterSnapshotError(
                    "review response evidence crosses its document scope"
                )
            key = _json_bytes(location)
            if key in seen_evidence:
                raise MatterSnapshotError("proposal.evidence must be unique")
            seen_evidence.add(key)


def render_lawyer_matter_html(snapshot: Mapping[str, Any]) -> str:
    """Render a read-only, document-qualified matter summary.

    This is intentionally a projection, not a correction surface.  It never
    renders provenance components and every evidence anchor carries its exact
    matter/document/version/block coordinates for host-side navigation.
    """

    view = project_view(snapshot, view_type="lawyer_report")
    manifest = snapshot["manifest"]
    versions = {item["version_id"]: item for item in manifest["document_versions"]}
    documents = {item["document_id"]: item for item in manifest["documents"]}
    selected = view["selected_document_version_ids"]

    def evidence_anchor(location: Mapping[str, Any]) -> str:
        _validate_location(location)
        label = (
            f"{location['document_id']} / {location['version_id']} / "
            f"{location['block_id']}:{location['char_start']}-{location['char_end']}"
        )
        attributes = " ".join(
            f'data-{key.replace("_", "-")}="{html.escape(str(location[key]), quote=True)}"'
            for key in (
                "matter_id",
                "document_id",
                "version_id",
                "block_id",
                "char_start",
                "char_end",
            )
        )
        return f'<button class="evidence" type="button" {attributes}>{html.escape(label)}</button>'

    sections: list[str] = []
    for component in view["components"]:
        role = component["role"]
        records = component["records"]
        if role == "document_findings":
            cards = []
            for finding in records.get("findings", []):
                anchors = "".join(
                    evidence_anchor(location)
                    for location in finding.get("evidence", [])
                )
                cards.append(
                    '<article class="finding">'
                    f"<h3>{html.escape(str(finding.get('message') or finding.get('rule_id') or 'Finding'))}</h3>"
                    f'<p class="scope">Document-local fact · {html.escape(component["document_id"])} · {html.escape(component["version_id"])}</p>'
                    f"<div>{anchors}</div></article>"
                )
            sections.append(
                f"<section><h2>Document findings</h2>{''.join(cards) or '<p>No displayed findings.</p>'}</section>"
            )
        elif role in {"version_lineage", "cross_document_findings"}:
            rows = (
                records.get("mappings", records.get("findings", []))
                if isinstance(records, dict)
                else records
            )
            cards = []
            for record in rows:
                anchors = "".join(
                    evidence_anchor(location) for location in record.get("evidence", [])
                )
                cards.append(
                    '<article class="finding comparison">'
                    f"<h3>{html.escape(str(record.get('state', 'Comparison conclusion')).replace('_', ' ').title())}</h3>"
                    '<p class="scope">Reviewed comparison conclusion</p>'
                    f"<div>{anchors}</div></article>"
                )
            title = (
                "Version comparison"
                if role == "version_lineage"
                else "Companion-document review"
            )
            sections.append(
                f"<section><h2>{title}</h2>{''.join(cards) or '<p>No displayed conclusions.</p>'}</section>"
            )

    scope_items = []
    for version_id in selected:
        version = versions[version_id]
        document = documents[version["document_id"]]
        scope_items.append(
            f"<li>{html.escape(document['display_name'])} <span>{html.escape(version_id)}</span></li>"
        )
    missing = view["missing_selected_companions"]
    missing_html = (
        "<ul>"
        + "".join(f"<li>{html.escape(str(item))}</li>" for item in missing)
        + "</ul>"
        if missing
        else "<p>None declared.</p>"
    )
    title = html.escape(manifest["matter"]["display_name"])
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} — Definition Check</title>
<style>
body{{font:16px/1.5 system-ui,sans-serif;margin:0;color:#1f2937;background:#f6f7f9}}main{{max-width:1000px;margin:auto;padding:2rem}}
header,section{{background:white;border:1px solid #d9dde3;border-radius:12px;padding:1.25rem;margin-bottom:1rem}}h1,h2,h3{{line-height:1.2}}
.scope,li span{{color:#596579}}.finding{{border-top:1px solid #e5e7eb;padding:1rem 0}}.evidence{{display:block;margin:.4rem 0;padding:.55rem .7rem;border:1px solid #8b95a5;border-radius:7px;background:#fff;text-align:left;cursor:pointer}}
.notice{{border-left:4px solid #7857d8;padding-left:.8rem}}@media(max-width:600px){{main{{padding:.75rem}}}}
</style></head><body><main>
<header><h1>{title}</h1><p class="notice">Only the explicitly selected document versions listed below were reviewed. Comparison conclusions are distinct from document-local facts.</p>
<h2>Selected scope</h2><ul>{"".join(scope_items)}</ul><h2>Missing selected companions</h2>{missing_html}</header>
{"".join(sections)}
</main></body></html>"""
