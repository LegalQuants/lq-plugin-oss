"""Adversarial and boundary tests for the Playbook Engine runtime.

These cover the failure modes a lawyer would meet in practice rather than the
happy path: hostile text in the Word export, multi-paragraph redrafts, the
executive tally, the privileged versus external cuts, structural warnings,
misdated exports, governing-law date detection, and over-confident playbook
matching.
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

import pytest

ROOT = Path(__file__).resolve().parents[4]
BUILDER = ROOT / "skills/transactional/playbook-builder"
REVIEWER = ROOT / "skills/transactional/playbook-review"
sys.path.insert(0, str(BUILDER / "scripts"))

from shared.playbook_runtime import (  # noqa: E402
    CLASSIFICATION_TALLY_ORDER,
    REVIEW_CLASSIFICATIONS,
    PlaybookError,
    build_markup_segments,
    detect_date_style,
    format_display_date,
    format_issue_tally,
    match_playbook_candidate,
    populate_issues_markup,
    render_issues_docx,
    render_issues_html,
    summarise_issue_counts,
    validate_issues_list,
    validate_structural_warnings,
)

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _issue(**overrides: Any) -> dict[str, Any]:
    issue: dict[str, Any] = {
        "issueId": "iss-1",
        "playbookIssueId": "liability-cap",
        "classification": "deviation",
        "materiality": "high",
        "documentSha256": "c" * 64,
        "elementId": "el-1",
        "clauseRef": "12.1",
        "originalText": "Liability is capped at 50% of fees.",
        "proposedText": "Liability is capped at 100% of fees.",
        "draftingProvenance": "approved-playbook",
        "rationale": "Below the house floor; we have leverage on renewal.",
        "externalComment": "We propose aligning the cap with annual fees.",
        "lawyerReview": "pending",
    }
    issue.update(overrides)
    if "markupSegments" not in overrides:
        issue["markupSegments"] = build_markup_segments(
            issue["originalText"], issue["proposedText"]
        )
    return issue


def _issues_list(issues: list[dict[str, Any]], **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "artifactType": "issues-list",
        "schemaVersion": "1.0",
        "runId": "run-hardening",
        "sourceManifestSha256": "a" * 64,
        "playbookId": "saas-customer",
        "playbookVersion": "1.0.0",
        "effectiveStanceSha256": "b" * 64,
        "generatedAt": "2026-09-06T12:00:00Z",
        "issues": issues,
    }
    payload.update(overrides)
    return payload


def _playbook(**overrides: Any) -> dict[str, Any]:
    playbook: dict[str, Any] = {
        "playbookId": "saas-customer",
        "title": "Customer SaaS playbook",
        "governingLaw": "England and Wales",
    }
    playbook.update(overrides)
    return playbook


def _render(
    tmp_path: Path, issues: dict[str, Any], name: str, **kwargs: Any
) -> tuple[str, ET.Element]:
    out = tmp_path / f"{name}.docx"
    render_issues_docx(issues, out, **kwargs)
    with zipfile.ZipFile(out) as zf:
        xml = zf.read("word/document.xml").decode("utf-8")
    root = ET.fromstring(xml)
    for cell in root.iter(W + "tc"):
        assert cell.find(W + "p") is not None, "every table cell needs a paragraph"
    return xml, root


def _text_nodes(root: ET.Element) -> list[str]:
    return [node.text or "" for node in root.iter(W + "t")]


# --- Word export: hostile text and layout -----------------------------------


def test_docx_escapes_xml_hostile_text(tmp_path: Path) -> None:
    original = "A & B < C > D \"quoted\" 'apos' \x0b\x0c\x00 end"
    proposed = "]]> <w:t>injected</w:t> &amp; done"
    issue = _issue(
        originalText=original,
        proposedText=proposed,
        # One delete run and one insert run, so each text stays contiguous.
        markupSegments=[
            {"op": "delete", "text": original},
            {"op": "insert", "text": proposed},
        ],
        rationale="Cap of £500k > €400k & rising \U0001f600",
        externalComment='She said "no" & left',
    )
    xml, root = _render(
        tmp_path, _issues_list([issue]), "hostile", playbook=_playbook()
    )

    # Nothing from the payload became markup: the parser saw only our elements.
    assert "<w:t>injected</w:t>" not in xml
    assert xml.count("<w:body>") == 1
    assert "\x0b" not in xml and "\x00" not in xml
    # Segments split text across runs, so compare the reassembled text.
    joined = "".join(_text_nodes(root))
    assert "]]> <w:t>injected</w:t> &amp; done" in joined
    assert "A & B < C > D \"quoted\" 'apos'" in joined
    assert "£500k > €400k & rising \U0001f600" in joined


def test_docx_multiline_text_uses_word_line_breaks(tmp_path: Path) -> None:
    original = "Para one.\nPara two."
    proposed = "Para one amended.\n\nPara two amended.\n(a)\tsub-paragraph"
    issue = _issue(
        originalText=original,
        proposedText=proposed,
        markupSegments=[
            {"op": "delete", "text": original},
            {"op": "insert", "text": proposed},
        ],
        rationale="Line A\nLine B",
        externalComment="Comment line 1\r\nComment line 2",
    )
    xml, root = _render(tmp_path, _issues_list([issue]), "multiline")

    assert not any("\n" in text or "\r" in text for text in _text_nodes(root))
    assert not any("\t" in text for text in _text_nodes(root))
    assert len(list(root.iter(W + "br"))) >= 5
    assert len(list(root.iter(W + "tab"))) == 1
    # The redraft's words all survive; only the breaks moved into <w:br/>.
    joined = "".join(_text_nodes(root))
    assert "Para one amended." in joined
    assert "sub-paragraph" in joined
    assert "Comment line 1" in joined and "Comment line 2" in joined


def test_docx_omits_rule_label_when_issue_has_no_playbook_rule(
    tmp_path: Path,
) -> None:
    gap = _issue(
        issueId="gap-1",
        playbookIssueId=None,
        classification="playbook-gap",
        draftingProvenance="none",
        proposedText="Liability is capped at 50% of fees.",
        markupSegments=[{"op": "equal", "text": "Liability is capped at 50% of fees."}],
    )
    xml, _ = _render(tmp_path, _issues_list([gap]), "no-rule")
    assert "Rule:" not in xml
    assert "Uncovered Issue" in xml


def test_docx_column_header_is_mode_neutral(tmp_path: Path) -> None:
    xml, _ = _render(tmp_path, _issues_list([_issue()]), "header")
    assert "Contract Wording (As Drafted)" in xml
    assert "Inbound Wording (Counterparty)" not in xml


# --- Executive tally ---------------------------------------------------------


def test_tally_order_covers_every_classification() -> None:
    assert set(CLASSIFICATION_TALLY_ORDER) == REVIEW_CLASSIFICATIONS


def test_summarise_issue_counts_counts_everything() -> None:
    issues = [
        _issue(
            issueId=f"i-{index}", classification=classification, materiality="medium"
        )
        for index, classification in enumerate(sorted(REVIEW_CLASSIFICATIONS))
    ]
    tally = summarise_issue_counts(issues)
    assert tally["total"] == len(REVIEW_CLASSIFICATIONS)
    assert sum(tally["byClassification"].values()) == tally["total"]
    assert tally["byMateriality"]["medium"] == tally["total"]


def test_docx_tally_never_drops_actionable_categories(tmp_path: Path) -> None:
    def quiet(issue_id: str, classification: str) -> dict[str, Any]:
        return _issue(
            issueId=issue_id,
            classification=classification,
            materiality="medium",
            draftingProvenance="none",
            proposedText="Liability is capped at 50% of fees.",
            markupSegments=[
                {"op": "equal", "text": "Liability is capped at 50% of fees."}
            ],
        )

    issues = [
        quiet("i1", "unclear"),
        quiet("i2", "extra-obligation"),
        quiet("i3", "playbook-gap"),
        quiet("i4", "playbook-conflict"),
        quiet("i5", "not-applicable"),
    ]
    xml, _ = _render(tmp_path, _issues_list(issues), "tally")
    assert "Executive Summary: 5 Total Issues" in xml
    assert "0 Redlines Required" in xml
    assert "1 Onerous / Non-Standard" in xml
    assert "1 Uncovered Issue" in xml
    assert "1 Playbook Conflict" in xml
    assert "1 Ambiguous Drafting" in xml
    assert "1 Not Applicable" in xml
    assert "5 Medium Risk" in xml


def test_format_issue_tally_pluralises_and_counts_warnings() -> None:
    tally = summarise_issue_counts(
        [
            _issue(issueId="a"),
            _issue(issueId="b"),
            _issue(issueId="c", materiality="none"),
        ]
    )
    line = format_issue_tally(tally, warning_count=2)
    assert "3 Redlines Required" in line
    assert "1 Not Rated" in line
    assert "2 Structural Warnings" in line


# --- Audience cuts -----------------------------------------------------------


def test_internal_cut_is_marked_privileged(tmp_path: Path) -> None:
    xml, _ = _render(
        tmp_path, _issues_list([_issue()]), "internal", playbook=_playbook()
    )
    assert "INTERNAL - PRIVILEGED AND CONFIDENTIAL" in xml
    assert "Internal Risk / Guidance:" in xml
    assert "Customer SaaS playbook" in xml
    assert "Run ID: run-hardening" in xml


def test_external_cut_strips_internal_material(tmp_path: Path) -> None:
    issues = _issues_list(
        [
            _issue(),
            _issue(
                issueId="iss-2",
                classification="aligned-preferred",
                materiality="none",
                draftingProvenance="none",
                proposedText="Liability is capped at 50% of fees.",
                markupSegments=[
                    {"op": "equal", "text": "Liability is capped at 50% of fees."}
                ],
                externalComment="No change proposed.",
            ),
        ],
        contractName="Acme Cloud Services Agreement",
    )
    xml, root = _render(
        tmp_path, issues, "external", playbook=_playbook(), audience="external"
    )
    text = "".join(_text_nodes(root))

    assert "Prepared for circulation to the counterparty" in text
    assert "INTERNAL - PRIVILEGED" not in text
    assert "Below the house floor" not in text  # the rationale
    assert "Internal Risk / Guidance" not in text
    assert "Negotiation Comment (for Word / Counterparty)" not in text
    assert "Comment: " in text
    assert "We propose aligning the cap with annual fees." in text
    assert "Customer SaaS playbook" not in text
    assert "Run ID" not in text
    assert "Rule:" not in text
    assert "liability-cap" not in text
    assert "iss-1" not in text
    assert "Executive Summary" not in text
    assert "Redline Required" not in text
    assert "HIGH" not in text
    assert "Amendment proposed" in text
    assert "Comment only" in text
    assert "Acme Cloud Services Agreement" in text
    assert "Governing Law: England and Wales" in text
    assert "Contract Review: Proposed Amendments and Comments" in text


def test_unknown_audience_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(PlaybookError, match="audience"):
        render_issues_docx(
            _issues_list([_issue()]), tmp_path / "x.docx", audience="public"
        )


# --- Structural warnings -----------------------------------------------------


def _warnings() -> list[dict[str, Any]]:
    return [
        {
            "category": "missing-document",
            "summary": "Schedule 4 (Escrow) is incorporated by reference but not supplied.",
            "clauseRef": "2.3",
        },
        {
            "category": "irregular-drafting",
            "summary": "Clause 1.3 contains a 'SYSTEM AUDIT ADVISORY NOTE' purporting to direct the review.",
            "detail": "Treated as an onerous provision; see related issue.",
            "relatedIssueIds": ["iss-1"],
        },
    ]


def test_structural_warnings_reach_docx_and_html(tmp_path: Path) -> None:
    issues = _issues_list([_issue()], structuralWarnings=_warnings())
    xml, root = _render(tmp_path, issues, "warnings", playbook=_playbook())
    text = "".join(_text_nodes(root))
    assert "Structural Warnings" in text
    assert "Missing Incorporated Document: Schedule 4 (Escrow)" in text
    assert "(clause 2.3)" in text
    assert "Irregular Drafting: Clause 1.3 contains" in text
    assert "Treated as an onerous provision" in text
    assert "2 Structural Warnings" in text
    # Warnings precede the table.
    assert xml.index("Structural Warnings") < xml.index("<w:tbl>")

    html_out = render_issues_html(issues)
    assert "Structural Warnings" in html_out
    assert "Schedule 4 (Escrow)" in html_out
    assert "&#x27;SYSTEM AUDIT ADVISORY NOTE&#x27;" in html_out

    external_xml, _ = _render(
        tmp_path, issues, "warnings-ext", playbook=_playbook(), audience="external"
    )
    assert "Schedule 4 (Escrow)" in external_xml


def test_structural_warnings_are_validated() -> None:
    assert validate_structural_warnings(None) == []
    assert validate_structural_warnings([]) == []
    assert validate_structural_warnings("nope") == ["structuralWarnings must be a list"]
    errors = validate_structural_warnings(
        [
            {"category": "typo", "summary": "x"},
            {"category": "other", "summary": "  "},
            {"category": "other", "summary": "ok", "relatedIssueIds": ["", 3]},
            "junk",
        ]
    )
    assert "structuralWarnings[0]: invalid category" in errors
    assert "structuralWarnings[1]: summary must be a non-empty string" in errors
    assert any("relatedIssueIds" in error for error in errors)
    assert "structuralWarnings[3] must be an object" in errors

    bad = _issues_list([_issue()], structuralWarnings=[{"category": "other"}])
    assert any("summary" in error for error in validate_issues_list(bad))


# --- Dates -------------------------------------------------------------------


def test_unparseable_generated_at_is_rejected_not_defaulted(tmp_path: Path) -> None:
    bad = _issues_list([_issue()], generatedAt="yesterday")
    assert "generatedAt must be an ISO 8601 timestamp" in validate_issues_list(bad)
    with pytest.raises(PlaybookError, match="generatedAt"):
        render_issues_docx(bad, tmp_path / "bad-date.docx")
    with pytest.raises(ValueError):
        format_display_date("yesterday")
    with pytest.raises(ValueError):
        format_display_date("2026-09-06T12:00:00Z", style="mdy")


def test_generated_at_preserves_stated_calendar_date() -> None:
    # The date written is the date in the timestamp, not the run machine's day.
    assert format_display_date("2026-09-06T23:30:00+01:00") == "6 September 2026"
    assert format_display_date("2026-09-07T00:30:00+05:00") == "7 September 2026"


@pytest.mark.parametrize(
    ("governing_law", "expected"),
    [
        ("Lusaka, Zambia", "uk"),
        ("England and Wales", "uk"),
        ("Yorkshire and the Humber", "uk"),
        ("Province of Ontario", "uk"),
        ("Commonwealth of Massachusetts", "us"),
        ("State of Washington", "us"),
        ("Florida", "us"),
        ("New York Law", "us"),
        ("Laws of the State of Delaware, USA", "us"),
        ("U.S. federal law", "us"),
        (None, "uk"),
        ("", "uk"),
    ],
)
def test_date_style_detection_uses_word_boundaries(
    governing_law: str | None, expected: str
) -> None:
    assert detect_date_style(governing_law) == expected


def test_playbook_date_style_overrides_detection(tmp_path: Path) -> None:
    playbook = _playbook(governingLaw="State of Delaware", dateStyle="iso")
    xml, _ = _render(tmp_path, _issues_list([_issue()]), "iso", playbook=playbook)
    assert "Date: 2026-09-06" in xml
    assert "September 6, 2026" not in xml


def test_populate_issues_markup_stamps_generated_at() -> None:
    issues = _issues_list([_issue()])
    del issues["generatedAt"]
    populated = populate_issues_markup(copy.deepcopy(issues))
    assert populated["generatedAt"].endswith("Z")
    assert validate_issues_list(populated) == []
    kept = populate_issues_markup(copy.deepcopy(_issues_list([_issue()])))
    assert kept["generatedAt"] == "2026-09-06T12:00:00Z"


# --- Comment field -----------------------------------------------------------


def test_counterparty_comment_is_not_a_fallback_field(tmp_path: Path) -> None:
    issue = _issue()
    del issue["externalComment"]
    issue["counterpartyComment"] = "Should be ignored"
    html_out = render_issues_html(_issues_list([issue]))
    assert "Should be ignored" not in html_out
    assert "Negotiation Comment" not in html_out
    xml, _ = _render(tmp_path, _issues_list([issue]), "no-fallback")
    assert "Should be ignored" not in xml


# --- Playbook matching -------------------------------------------------------


def _library(*families: str) -> list[dict[str, Any]]:
    names = {
        "NDA": ("nda-standard", "Standard NDA", "NDA", "mutual"),
        "DPA": ("dpa-controller", "Controller DPA", "DPA", "controller"),
        "Licence": ("licence-vendor", "Vendor Software Licence", "Licence", "licensor"),
        "MSA": ("msa-supplier", "Master Services Agreement", "MSA", "supplier"),
        "SaaS": ("saas-customer", "Customer SaaS Agreement", "SaaS", "customer"),
    }
    return [
        {
            "playbookId": names[f][0],
            "playbookName": names[f][1],
            "agreementFamily": names[f][2],
            "perspective": names[f][3],
            "issueCount": 10,
            "version": "1.0.0",
        }
        for f in families
    ]


MSA_TEXT = (
    "MASTER SERVICES AGREEMENT dated 6 September 2026 between Acme Limited, a "
    "company registered in England and Wales, and Beta plc. "
    "BACKGROUND: The Supplier provides the Services and the Customer wishes to "
    "procure them on the terms below. "
    "1. Definitions. 2. Services. 3. Charges. 4. Term. 5. Warranties. "
    "12. Confidentiality. Each party shall keep confidential all Confidential "
    "Information. 13. Licence. Supplier grants a non-exclusive licence. "
    "14. Data protection. The parties shall comply with Data Protection Legislation."
)


def test_generic_clause_headings_are_not_family_aliases() -> None:
    # Short documents put clause headings inside the title region, so bare
    # heading words must not identify a family on their own.
    for text in (
        "SHORT AGREEMENT. 1. Confidentiality. 2. Licence. 3. Data protection.",
        "TERMS. Each party shall keep confidential all information disclosed.",
    ):
        assert (
            match_playbook_candidate(
                _library("NDA", "DPA", "Licence"),
                source_names=["draft.docx"],
                sample_text=text,
            )
            is None
        )


def test_matcher_ignores_body_clause_vocabulary() -> None:
    # An MSA against a library holding only an NDA playbook is not an NDA.
    assert (
        match_playbook_candidate(
            _library("NDA"),
            source_names=["Acme_Master_Services_Agreement.docx"],
            sample_text=MSA_TEXT,
        )
        is None
    )
    # A subscription agreement is neither a DPA nor a software licence because
    # its body has a data protection clause and a licence grant.
    assert (
        match_playbook_candidate(
            _library("DPA", "Licence"),
            source_names=["Cloud_Subscription_Terms.docx"],
            sample_text="SUBSCRIPTION AGREEMENT. 1. Licence. Supplier grants a licence. "
            "9. Data protection. The parties shall comply.",
        )
        is None
    )
    # With the right playbook in the library the title still matches.
    match = match_playbook_candidate(
        _library("NDA", "MSA"),
        source_names=["Contract_Draft_v1.docx"],
        sample_text=MSA_TEXT,
    )
    assert match is not None
    assert match["playbook"]["playbookId"] == "msa-supplier"
    assert match["detectedFamily"] == "MSA"


def test_matcher_reads_only_the_title_region() -> None:
    padding = "This Agreement sets out the terms on which the parties will trade. " * 12
    body_only = padding + "NON-DISCLOSURE AGREEMENT"
    assert (
        match_playbook_candidate(
            _library("NDA"), source_names=["draft.docx"], sample_text=body_only
        )
        is None
    )
    title_first = "NON-DISCLOSURE AGREEMENT " + padding
    match = match_playbook_candidate(
        _library("NDA"), source_names=["draft.docx"], sample_text=title_first
    )
    assert match is not None
    assert match["detectedFamily"] == "NDA"


def test_matcher_still_uses_perspective_from_wider_text() -> None:
    text = "MASTER SERVICES AGREEMENT. " + ("The Supplier shall perform. " * 30)
    match = match_playbook_candidate(
        _library("MSA"), source_names=["Acme_MSA.docx"], sample_text=text
    )
    assert match is not None
    assert match["score"] >= 130  # family plus perspective bonus


def test_matcher_returns_none_without_family_evidence() -> None:
    assert (
        match_playbook_candidate(_library("MSA"), source_names=["Minutes.txt"]) is None
    )
    assert match_playbook_candidate(_library("MSA")) is None
    assert match_playbook_candidate([], source_names=["Acme_MSA.docx"]) is None


# --- CLI ---------------------------------------------------------------------


def _run_cli(*arguments: object) -> subprocess.CompletedProcess[str]:
    script = REVIEWER / "scripts/playbook_review.py"
    return subprocess.run(
        [sys.executable, str(script), *(str(argument) for argument in arguments)],
        capture_output=True,
        check=False,
        encoding="utf-8",
    )


def test_cli_export_docx_audience_flag(tmp_path: Path) -> None:
    issues_file = tmp_path / "issues-list.json"
    issues_file.write_text(json.dumps(_issues_list([_issue()])), encoding="utf-8")
    playbook_file = tmp_path / "playbook.json"
    playbook_file.write_text(json.dumps(_playbook()), encoding="utf-8")

    external_out = tmp_path / "external.docx"
    result = _run_cli(
        "export-docx",
        issues_file,
        "--playbook",
        playbook_file,
        "--contract-name",
        "Halcyon MSA",
        "--audience",
        "external",
        "--out",
        external_out,
    )
    assert result.returncode == 0, result.stderr
    assert "external cut" in result.stdout
    with zipfile.ZipFile(external_out) as zf:
        xml = zf.read("word/document.xml").decode("utf-8")
    assert "Halcyon MSA" in xml
    assert "Below the house floor" not in xml

    # `--contract` is a file path on discover-playbooks; it is not accepted here.
    rejected = _run_cli(
        "export-docx", issues_file, "--contract", "X", "--out", tmp_path / "y.docx"
    )
    assert rejected.returncode == 2
    assert "unrecognized arguments" in rejected.stderr


# --- Packaging parity --------------------------------------------------------


def test_shared_runtime_and_schema_copies_are_identical() -> None:
    runtime_copies = [
        REVIEWER / "scripts/shared/playbook_runtime.py",
        BUILDER / "scripts/shared/playbook_runtime.py",
    ]
    schema_copies = [
        ROOT / "packages/contracts/schemas/playbook-engine.schema.json",
        REVIEWER / "schemas/playbook-engine.schema.json",
        BUILDER / "schemas/playbook-engine.schema.json",
    ]
    for group in (runtime_copies, schema_copies):
        contents = {path.read_bytes() for path in group}
        assert len(contents) == 1, f"copies differ: {[str(p) for p in group]}"


def test_schema_has_one_comment_field_and_structural_warnings() -> None:
    schema = json.loads(
        (ROOT / "packages/contracts/schemas/playbook-engine.schema.json").read_text(
            encoding="utf-8"
        )
    )
    review_issue = schema["$defs"]["reviewIssue"]["properties"]
    assert "externalComment" in review_issue
    assert "counterpartyComment" not in review_issue
    issues_list = schema["$defs"]["issuesList"]["properties"]
    assert issues_list["generatedAt"]["format"] == "date-time"
    assert issues_list["structuralWarnings"]["items"]["$ref"].endswith(
        "structuralWarning"
    )
    assert "governingLaw" not in issues_list
    assert schema["$defs"]["playbook"]["properties"]["dateStyle"]["enum"] == [
        "uk",
        "us",
        "iso",
    ]
