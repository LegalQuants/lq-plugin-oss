"""Contract checks for the lawyer-facing authority-acquisition reference."""

import re
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).parents[4]
SKILL_ROOT = ROOT / "skills" / "litigation" / "cite-check"
PACKAGED_SKILL_ROOT = (
    ROOT / "plugins" / "legalquants-litigation" / "skills" / "cite-check"
)
REFERENCE = SKILL_ROOT / "references" / "getting-authorities.md"
JURISDICTION_REFERENCE_ROOT = REFERENCE.parent / "authority-sources"
JURISDICTION_REFERENCES = {
    "United States": JURISDICTION_REFERENCE_ROOT / "united-states.md",
    "United Kingdom": JURISDICTION_REFERENCE_ROOT / "united-kingdom.md",
    "New Zealand": JURISDICTION_REFERENCE_ROOT / "new-zealand.md",
    "Canada": JURISDICTION_REFERENCE_ROOT / "canada.md",
    "Australia": JURISDICTION_REFERENCE_ROOT / "australia.md",
}


def _reference_text() -> str:
    return REFERENCE.read_text(encoding="utf-8")


def _public_markdown(text: str) -> str:
    public = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL).replace("\n\n\n", "\n\n")
    return public.rstrip("\n") + "\n"


def _markdown_links(text: str) -> list[str]:
    return re.findall(r"\[[^\]]+\]\(([^)]+)\)", text)


def test_westlaw_workflow_preserves_acquisition_and_status_boundaries() -> None:
    text = _reference_text()
    assert "separate, complete, readable authority files" in text
    assert "underlying authority text" in text
    assert (
        "not only a result list, citation report, headnote, synopsis, or link" in text
    )
    assert "does not by itself establish" in text
    assert "complete and current KeyCite treatment" in text
    assert (
        "license permits using the downloaded material with external AI products"
        in text
    )
    assert "not affiliated with Thomson Reuters" in text
    assert "any applicable terms and conditions" in text
    assert "latest, authoritative cases from Westlaw" not in text
    assert "Go to **Tools**, then **Litigation Document Analyzer**." not in text
    assert "use Westlaw's Litigation Document Analyzer to produce" not in text


def test_reference_handles_alternatives_boundaries_and_source_failures() -> None:
    text = _reference_text()
    required_phrases = [
        "CourtListener, a Free Law Project service",
        "https://wiki.free.law/c/courtlistener/help/data-coverage/case-law",
        "citator such as KeyCite or Shepard's",
        "Public case search with CourtListener",
        "Never upload the client brief",
        "citation metadata",
        "Missing authority",
        "Ambiguous citation or match",
        "Duplicate files",
        "Paywalled source",
        "Scanned or image-only file",
        "Misleading filename",
        "rather than bundling it into the plugin or public fixtures",
        "Never ask the lawyer to provide service credentials in chat.",
    ]

    for phrase in required_phrases:
        assert phrase in text


def test_reference_explains_the_main_authority_categories() -> None:
    text = _reference_text()
    required_fragments = (
        "Case law",
        "precedential or nonprecedential",
        "Statutes and regulations",
        "Legislative and administrative materials",
        "legislative history",
        "administrative history",
        "administrative enforcement actions",
        "Case-specific materials",
        "certified administrative record",
        "pleadings on a motion to dismiss",
        "discovery record",
    )
    assert all(fragment in text for fragment in required_fragments)


def test_reference_prioritizes_case_law_and_routes_jurisdictional_acquisition() -> None:
    text = _reference_text()
    required_fragments = (
        "Most lawyers will want at least the cited case law",
        "Westlaw subscriber",
        "For United States case law, CourtListener",
        "other free case-law services",
        "Jurisdiction-specific authority sources",
        "Jurisdiction-specific acquisition rules",
    )
    assert all(fragment in text for fragment in required_fragments)

    for jurisdiction, path in JURISDICTION_REFERENCES.items():
        relative_link = path.relative_to(REFERENCE.parent).as_posix()
        assert f"[{jurisdiction}]({relative_link})" in text
        assert path.is_file()


def test_jurisdiction_pages_are_source_specific_and_scope_limited() -> None:
    expected_source_hosts = {
        "United States": (
            "www.supremecourt.gov",
            "www.uscourts.gov",
            "www.govinfo.gov",
            "pacer.uscourts.gov",
            "www.courtlistener.com",
            "guides.loc.gov",
            "uscode.house.gov",
            "www.congress.gov",
            "www.ecfr.gov",
            "www.federalregister.gov",
            "www.regulations.gov",
        ),
        "United Kingdom": (
            "caselaw.nationalarchives.gov.uk",
            "www.legislation.gov.uk",
            "www.bailii.org",
            "www.scotcourts.gov.uk",
            "www.judiciaryni.uk",
        ),
        "New Zealand": (
            "www.courtsofnz.govt.nz",
            "jdo.justice.govt.nz",
            "www.legislation.govt.nz",
            "www.nzlii.org",
        ),
        "Canada": (
            "www.scc-csc.ca",
            "www.canlii.org",
            "www.fct-cf.ca",
            "www.fca-caf.ca",
            "laws-lois.justice.gc.ca",
        ),
        "Australia": (
            "www.fedcourt.gov.au",
            "www.hcourt.gov.au",
            "www.austlii.edu.au",
            "www.legislation.gov.au",
        ),
    }

    for jurisdiction, path in JURISDICTION_REFERENCES.items():
        text = path.read_text(encoding="utf-8")
        assert f"# {jurisdiction}" in text
        assert "## Case law" in text
        assert "## Legislation and regulations" in text
        assert "## Case-specific materials" in text
        assert "Do not assume complete coverage" in text
        assert "does not establish currentness" in text
        assert "citation metadata" in text
        assert "confidential" in text
        links = _markdown_links(text)
        remote_links = [link for link in links if link.startswith("https://")]
        assert remote_links
        linked_hosts = {urlparse(link).hostname for link in remote_links}
        assert set(expected_source_hosts[jurisdiction]) <= linked_hosts

    new_zealand = JURISDICTION_REFERENCES["New Zealand"].read_text(encoding="utf-8")
    assert "[Judicial Decisions Online](https://jdo.justice.govt.nz/)" in new_zealand


def test_united_states_route_uses_official_sources_and_bounds_public_repositories() -> (
    None
):
    text = JURISDICTION_REFERENCES["United States"].read_text(encoding="utf-8")
    required_fragments = (
        "Supreme Court opinions page",
        "United States Courts Opinions collection",
        "selected United States appellate, district, and bankruptcy courts",
        "CourtListener",
        "American case law",
        "supplementary locator",
        "PACER",
        "RECAP Archive",
        "Office of the Law Revision Counsel",
        "Statutes at Large",
        "authoritative but unofficial",
        "Federal Register",
        "Regulations.gov",
        "Current Rules of Practice and Procedure",
        "state or territory",
    )
    assert all(fragment in text for fragment in required_fragments)

    getting_authorities = _reference_text()
    assert "public source for United States case law" in getting_authorities
    assert (
        "[jurisdiction-specific authority sources]"
        "(#jurisdiction-specific-authority-sources)" in getting_authorities
    )

    unit_review = (SKILL_ROOT / "references" / "unit-review-prompt.md").read_text(
        encoding="utf-8"
    )
    assert "For United States case law, that source may be CourtListener" in unit_review
    assert (
        "[jurisdiction-specific authority sources]"
        "(getting-authorities.md#jurisdiction-specific-authority-sources)"
        in unit_review
    )


def test_authority_reference_links_are_well_formed_and_local_targets_exist() -> None:
    for path in (REFERENCE, *JURISDICTION_REFERENCES.values()):
        for link in _markdown_links(path.read_text(encoding="utf-8")):
            assert " " not in link
            if link.startswith("https://"):
                assert urlparse(link).hostname
                continue
            target, _, _fragment = link.partition("#")
            if target:
                assert (path.parent / target).resolve().is_file()


def test_packaged_plugin_mirrors_authority_acquisition_guidance() -> None:
    canonical_paths = (
        SKILL_ROOT / "SKILL.md",
        SKILL_ROOT / "references" / "lawyer-workflow.md",
        REFERENCE,
        *JURISDICTION_REFERENCES.values(),
    )
    for canonical in canonical_paths:
        relative_path = canonical.relative_to(SKILL_ROOT)
        packaged = PACKAGED_SKILL_ROOT / relative_path
        assert packaged.read_text(encoding="utf-8") == _public_markdown(
            canonical.read_text(encoding="utf-8")
        )


def test_reference_does_not_claim_an_unverified_westlaw_click_path() -> None:
    text = _reference_text()
    required_fragments = (
        "products, subscriptions, and interfaces vary",
        "does not establish a universal click path",
        "outcome-based acquisition guidance",
        "rather than unverified interface instructions",
    )
    assert all(fragment in text for fragment in required_fragments)


def test_uk_route_operationalizes_public_source_reuse_limits() -> None:
    text = JURISDICTION_REFERENCES["United Kingdom"].read_text(encoding="utf-8")
    required_fragments = (
        "excludes Scottish and Northern Irish courts and tribunals",
        "Scottish Courts and Tribunals judgments service",
        "Judiciary NI judicial-decisions service",
        "only as a supplementary locator",
        "prohibit storing search results or HTML judgments",
        "incorporating them into another website or computer-program output",
        "without prior written consent",
        "do not use BAILII search results or HTML through this workflow",
        "issuing-court copy or another lawyer-supplied authorized copy",
        "document-specific copyright and reuse position",
    )
    assert all(fragment in text for fragment in required_fragments)


def test_supplementary_repository_evidence_is_age_and_scope_qualified() -> None:
    canada = JURISDICTION_REFERENCES["Canada"].read_text(encoding="utf-8")
    assert "last updated in 2019" in canada
    assert "does not establish current API availability" in canada
    assert "live terms were access-blocked and not verified" in canada

    for jurisdiction in ("New Zealand", "Australia"):
        text = JURISDICTION_REFERENCES[jurisdiction].read_text(encoding="utf-8")
        assert "robots.txt" in text
        assert "terms and model-mediated reuse permission were not verified" in text


def test_public_case_search_is_automatic_simple_and_source_bound() -> None:
    text = _reference_text()
    required_fragments = (
        "When a case does not match a supplied authority, search CourtListener",
        "the environment could not search",
        "it may be hallucinated",
        "case was found but was not supplied for substantive checking",
        "does not verify what the case says",
        "manifest `sourceId`",
        "matches it by readable content rather than filename",
        "may already be available through web search",
        "Model Context Protocol server",
        "https://wiki.free.law/c/courtlistener/help/api/mcp/",
        "CourtListener account is required",
        "standard API access is granted automatically",
        "Free Law Project membership or a commercial agreement",
    )
    assert all(fragment in text for fragment in required_fragments)
    assert "ask the lawyer immediately before initiating that lookup" not in text


def test_reference_defines_source_visible_authority_status_and_treatment_limit() -> (
    None
):
    text = _reference_text()
    required_fragments = (
        "Authority status and treatment evidence",
        "opinion component",
        "publication or precedential designation",
        "procedural posture",
        "Current validity, vacatur, overruling",
        "requires supplied treatment evidence",
        "outside the supplied source universe",
    )
    assert all(fragment in text for fragment in required_fragments)


def test_reference_does_not_request_or_embed_credentials_or_matter_content() -> None:
    text = _reference_text().lower()
    prohibited_request_patterns = (
        "send your password",
        "share your password",
        "provide your password",
        "send your token",
        "share your token",
        "provide your token",
        "send your credentials",
        "share your credentials",
        "provide your credentials",
    )

    for phrase in prohibited_request_patterns:
        assert phrase not in text

    assert "no client or subscription-service source text is included here" in text
