"""Create and safely remove definition-check internal run workspaces."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .prompts import prompt_inventory
from .term_identity import TERM_NORMALIZATION_VERSION

WORKSPACE_SCHEMA_VERSION = "definition-check-workspace-v3"
WORKSPACE_MARKER = ".definition-check-workspace.json"


class WorkspaceError(ValueError):
    """Raised when an internal run workspace cannot be trusted."""


def require_within_workspace(
    path: str | Path, workspace: str | Path, *, label: str
) -> Path:
    """Resolve one internal artifact path and require workspace containment."""

    resolved = Path(path).resolve()
    root = Path(workspace).resolve()
    if resolved == root or not resolved.is_relative_to(root):
        raise WorkspaceError(
            f"{label} is outside the definition-check workspace: {resolved}"
        )
    return resolved


def require_disjoint_paths(output_dir: str | Path, work_dir: str | Path) -> None:
    """Prevent public output and private workspace trees from overlapping."""

    output = Path(output_dir).resolve()
    workspace = Path(work_dir).resolve()
    if (
        output == workspace
        or output.is_relative_to(workspace)
        or workspace.is_relative_to(output)
    ):
        raise WorkspaceError(
            "--output-dir and --work-dir must be disjoint directory trees"
        )


def temporary_workspace_root(workspace_root: str | Path | None = None) -> Path:
    approved = (
        Path(tempfile.gettempdir()) if workspace_root is None else Path(workspace_root)
    )
    approved = approved.resolve()
    return (approved / "definition-check").resolve()


def _private_mkdir(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if os.name != "nt":
        path.chmod(0o700)


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _read_marker(root: Path) -> dict[str, Any]:
    marker_path = root / WORKSPACE_MARKER
    try:
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkspaceError(
            f"invalid definition-check workspace marker: {marker_path}"
        ) from exc
    if not isinstance(marker, dict):
        raise WorkspaceError("definition-check workspace marker must be an object")
    if marker.get("schema_version") != WORKSPACE_SCHEMA_VERSION:
        raise WorkspaceError("unsupported definition-check workspace marker")
    if Path(str(marker.get("path", ""))).resolve() != root:
        raise WorkspaceError("definition-check workspace marker path does not match")
    if marker.get("run_id") != root.name:
        raise WorkspaceError("definition-check workspace run ID does not match")
    return marker


def ensure_workspace(
    path: str | Path,
    *,
    source_sha256: str | None = None,
    cleanup_base: str | Path | None = None,
) -> tuple[Path, dict[str, Any]]:
    """Create or validate a workspace and its fixed internal directory layout."""

    root = Path(path).resolve()
    if root == temporary_workspace_root():
        raise WorkspaceError(
            "the reserved definition-check temp root is not a run workspace"
        )
    existed = root.exists()
    _private_mkdir(root)
    marker_path = root / WORKSPACE_MARKER
    if marker_path.exists():
        marker = _read_marker(root)
        if marker.get("prompt_inventory") != prompt_inventory():
            raise WorkspaceError(
                "workspace packaged prompt inventory does not match; create a new "
                "workspace after updating the installed skill"
            )
        if marker.get("normalization_version") != TERM_NORMALIZATION_VERSION:
            raise WorkspaceError(
                "workspace term normalization version does not match; create a new workspace"
            )
        recorded_source = marker.get("source_sha256")
        if source_sha256 and recorded_source not in (None, source_sha256):
            raise WorkspaceError("workspace source fingerprint does not match")
        if source_sha256 and recorded_source is None:
            marker["source_sha256"] = source_sha256
            _atomic_json(marker_path, marker)
    else:
        if existed and any(root.iterdir()):
            raise WorkspaceError(
                "refusing to mark a non-empty directory as a definition-check workspace"
            )
        marker = {
            "schema_version": WORKSPACE_SCHEMA_VERSION,
            "run_id": root.name,
            "path": str(root),
            "created_at": datetime.now(UTC).isoformat(),
            "source_sha256": source_sha256,
            "prompt_inventory": prompt_inventory(),
            "normalization_version": TERM_NORMALIZATION_VERSION,
            "lifecycle_state": "active",
            "cleanup_base": str(Path(cleanup_base).resolve()) if cleanup_base else None,
        }
        _atomic_json(marker_path, marker)
    for relative in (
        "packets/discovery",
        "packets/semantic",
        "packets/occurrence",
        "packets/reference",
        "private",
        "responses/discovery",
        "responses/semantic",
        "responses/occurrence",
        "responses/reference",
        "bundles",
    ):
        _private_mkdir(root / relative)
    return root, marker


def create_workspace(
    *, source_sha256: str | None = None, workspace_root: str | Path | None = None
) -> tuple[Path, dict[str, Any]]:
    """Create a new marked child beneath temp or an explicitly approved root."""

    base = temporary_workspace_root(workspace_root)
    try:
        _private_mkdir(base)
    except OSError as exc:
        if workspace_root is None:
            raise WorkspaceError(f"temporary_workspace_unavailable: {base}") from exc
        raise WorkspaceError(f"approved_workspace_root_unavailable: {base}") from exc
    run_id = f"run-{uuid.uuid4().hex}"
    return ensure_workspace(
        base / run_id, source_sha256=source_sha256, cleanup_base=base
    )


def cleanup_workspace(path: str | Path) -> Path:
    """Delete one exact, marked workspace beneath the definition-check temp root."""

    root = Path(path).resolve()
    marker = _read_marker(root)
    raw_base = marker.get("cleanup_base")
    if not isinstance(raw_base, str) or not raw_base:
        raise WorkspaceError("workspace marker has no validated cleanup base")
    base = Path(raw_base).resolve()
    if base.name != "definition-check" or root == base or not root.is_relative_to(base):
        raise WorkspaceError(
            "cleanup is restricted to the marked definition-check root"
        )
    marker["lifecycle_state"] = "cleanup_started"
    marker["cleanup_started_at"] = datetime.now(UTC).isoformat()
    _atomic_json(root / WORKSPACE_MARKER, marker)
    shutil.rmtree(root)
    return root
