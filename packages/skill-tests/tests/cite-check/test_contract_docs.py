"""Contract-layer docs must advertise the shipped v2 result contract."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SKILL = ROOT / "skills/litigation/cite-check"

# Distinctive retired v1 status tokens. Do not ban English words such as
# "supported" or "unsupported" in ethics prose or authority text.
RETIRED_STATUS_TOKENS = (
    "partially_supported",
    "needs_lawyer_review",
    "source_unreadable",
    "insufficient_coverage",
)
V1_STATUS_LIST = "`supported`, `partially_supported`, `unsupported`, `contradicted`"
CURRENT_CONTRACT_MARKERS = (
    "citation_kind",
    "source_resolution",
    "fabrication_indicators",
    "accuracy_of_source_characterization",
    "disposition",
)


def _read(relative: str) -> str:
    return (SKILL / relative).read_text(encoding="utf-8")


def test_live_contract_docs_do_not_advertise_v1_status_tokens() -> None:
    paths = (
        ("SKILL.md", _read),
        ("references/openai-codex-runtime.md", _read),
    )
    for relative, reader in paths:
        text = reader(relative)
        for token in RETIRED_STATUS_TOKENS:
            assert token not in text, f"{relative} still advertises {token}"
        assert V1_STATUS_LIST not in text, f"{relative} still lists the v1 status enum"


def test_prd_and_skill_describe_the_shipped_field_contract() -> None:
    skill = _read("SKILL.md")
    for text in (skill,):
        for marker in CURRENT_CONTRACT_MARKERS:
            assert marker in text


def test_runtime_doc_matches_packaged_runner_and_fallbacks() -> None:
    runtime = _read("references/openai-codex-runtime.md")
    assert "probe_environment.py" in runtime
    assert "The packaged runner is the normal cite-check path" in runtime
    execution_steps = (
        "Packaged runner: one fresh `codex exec` session per prepared unit.",
        (
            "Native host workers with the same one-unit assignments when the "
            "packaged runner is unavailable."
        ),
        "One-at-a-time processing of the same units when workers are unavailable.",
    )
    offsets = [runtime.index(step) for step in execution_steps]
    assert offsets == sorted(offsets)
    assert "nested `codex exec` runner is reserved and disabled" not in runtime
    assert (
        "it does not read the target or authorities and makes no model call" in runtime
    )
    assert "disposable CLI canary must prove" not in runtime
    assert "final reconciliation" not in runtime
    assert "gpt-5.6-sol" not in runtime
    assert (
        "verified, contradicted, unresolved, inaccessible, and incomplete"
        not in runtime
    )
    assert (
        "The Python orchestration script starts one local `codex exec` process "
        "per unit."
    ) in runtime
    for private_runtime_detail in (
        "CODEX_HOME",
        "CODEX_API_KEY",
        "saved-login",
        "input_tokens=",
        "cachedInputTokens",
        "codex-cli 0.",
    ):
        assert private_runtime_detail not in runtime


def test_skill_owns_review_scope_and_requires_a_final_message_reminder() -> None:
    skill = _read("SKILL.md")
    flat_skill = " ".join(skill.split())
    assert "Uploaded-source review answers a narrower question" in skill
    assert "It is not Shepard's, KeyCite, or equivalent currentness research." in skill
    assert "final message" in skill
    assert (
        "Checks citations against the sources supplied for this run; it does "
        "not check later case history or replace full legal research." in flat_skill
    )


def test_report_instructions_prefer_aggregator_without_requiring_local_scripts() -> (
    None
):
    paths = (
        "SKILL.md",
        "references/lawyer-workflow.md",
        "references/parent-fanout.md",
    )
    for relative in paths:
        text = _read(relative)
        assert "scripts/aggregate_report.py" in text
        assert "host-native capabilities" in text
        assert (
            "Do not hand-author replacement HTML unless the user requests "
            "a custom report." in text
        )
