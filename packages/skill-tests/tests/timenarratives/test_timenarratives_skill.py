"""Provider-neutral product contract for the TimeNarratives skill."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SKILL = ROOT / "skills/core/timenarratives"


def _read(relative: str) -> str:
    return (SKILL / relative).read_text(encoding="utf-8")


def test_manifest_ships_every_portable_runtime_control() -> None:
    skill_md = _read("SKILL.md")
    assert "AUTO-GENERATED" not in skill_md
    assert not (SKILL / "skill.yaml").exists()
    assert not (SKILL / "evals").exists()
    assert not (SKILL / "PRD.md").exists()
    assert not (SKILL / "sections").exists()
    assert "internal stages" in skill_md.lower()
    assert "cli-contract.md" in skill_md
    assert "evidence-rules.md" in skill_md
    for path in (
        "scripts/build_packet.py",
        "scripts/validate_map.py",
        "scripts/render_deliverable.py",
        "scripts/docx_text.py",
        "scripts/email_attachments.py",
        "scripts/packet_filters.py",
        "scripts/packet_io.py",
        "scripts/packet_docx.py",
        "schemas/timenarratives-request.schema.json",
        "schemas/timenarratives-packet.schema.json",
        "schemas/timenarratives-map.schema.json",
        "schemas/timenarratives-confirmation.schema.json",
        "schemas/timenarratives-deliverable.schema.json",
        "references/evidence-rules.md",
        "references/user-journey.md",
        "references/cli-contract.md",
    ):
        assert (SKILL / path).is_file(), path


def test_cli_contract_keeps_helpers_internal_to_one_invocation() -> None:
    contract = _read("references/cli-contract.md")
    normalized = " ".join(contract.lower().split())
    assert "one `/timenarratives` action" in normalized
    assert "do not ask the user or the model to invoke" in normalized
    assert "first response" in normalized
    assert (
        "standalone command-line interfaces are maintenance and test surfaces"
        in normalized
    )
    assert "python scripts/" not in contract


def test_selected_packet_boundary_is_unambiguous() -> None:
    text = _read("SKILL.md")
    normalized = " ".join(text.lower().split())
    for phrase in (
        "explicitly selected",
        "do not search",
        "selected local packet",
        "complete workday",
        "date filter never expands",
    ):
        assert phrase in normalized
    for forbidden in ("search the mailbox", "search prior chats", "search the drive"):
        assert forbidden not in text.lower()


def test_notes_remain_attested_and_review_uses_plain_language() -> None:
    text = _read("SKILL.md")
    assert "user-attested" in text.lower()
    assert "use these" in text.lower()
    assert "bind that response to the current map" in text.lower()
    assert "confirm <emitted confirmationtoken>" not in text.lower()
    assert "copy a token" not in text.lower()
    assert "first 16 lowercase hex" not in text.lower()


def test_script_failure_is_only_an_unvalidated_preview() -> None:
    text = _read("SKILL.md").lower()
    assert "unvalidated preview" in text
    assert "do not call it copy-ready or final" in text
    assert "do not publish machine-readable artifacts" in text
    assert "in-memory, unposted draft" in text
    assert "only then publish the machine-readable" in text
    assert "validation and freshness checks" in text


def test_skill_never_claims_semantic_or_workday_proof() -> None:
    text = _read("SKILL.md").lower()
    assert "does not prove" in text
    assert "does not calculate time" in text
    assert "hallucination-free" not in text
    assert "whole workday" in text
    # Scope restrictions may mention permission; do not ban the word itself.
    assert "do not ask again" in text
    assert "clean-room" not in text
    assert "clean room" not in text


def test_prohibited_output_and_unposted_draft_are_visible() -> None:
    text = _read("SKILL.md").lower()
    for phrase in (
        "duration",
        "rates",
        "fees",
        "amounts",
        "billing codes",
        "billability",
        "posting",
        "unposted draft",
        "needs your check",
        (
            "checked only the sources you selected; this drafts narrative text for "
            "review and does not estimate time, decide billability, or post entries."
        ),
    ):
        assert phrase in text


def test_style_is_optional_without_profile_connector_or_provider_dependency() -> None:
    text = _read("SKILL.md").lower()
    for forbidden in (
        "lqprofile.md",
        "mailbox connector",
        "mcp__",
        "claude",
        "chatgpt",
    ):
        assert forbidden not in text
    assert "confirmed `[timenarratives]`" in text
    assert "neutral default" in text
    assert "conversation-context.md" in text
