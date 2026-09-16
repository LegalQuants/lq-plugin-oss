from pathlib import Path

REFERENCE = (
    Path(__file__).parents[4]
    / "skills"
    / "litigation"
    / "cite-check"
    / "references"
    / "ethics-and-jurisdictions.md"
)


def test_ethics_reference_has_required_scope_and_examples() -> None:
    text = REFERENCE.read_text(encoding="utf-8")
    required_fragments = (
        "**Coverage date:** 2026-08-17",
        "## ABA Model Rules baseline",
        "## Representative jurisdiction matrix",
        "New York",
        "California",
        "Current through May 31, 2021",
        "## Worked civil-litigation examples",
        "Known controlling adverse case",
        "Permissible characterization",
        "Missing rebuttal as a judgment call",
        "## Non-U.S., unlisted, and local-rule boundary",
        "does not adjudicate professional responsibility",
    )
    assert all(fragment in text for fragment in required_fragments)


def test_ethics_reference_cites_primary_sources_and_retrieval_date() -> None:
    text = REFERENCE.read_text(encoding="utf-8")
    official_sources = (
        "https://www.americanbar.org/groups/professional_responsibility/publications/model_rules_of_professional_conduct/rule_1_3_diligence/",
        "https://www.americanbar.org/groups/professional_responsibility/publications/model_rules_of_professional_conduct/rule_1_3_diligence/comment_on_rule_1_3/",
        "https://www.americanbar.org/groups/professional_responsibility/publications/model_rules_of_professional_conduct/rule_3_1_meritorious_claims_contentions/",
        "https://www.americanbar.org/groups/professional_responsibility/publications/model_rules_of_professional_conduct/rule_3_1_meritorious_claims_contentions/comment_on_rule_3_1/",
        "https://www.americanbar.org/groups/professional_responsibility/publications/model_rules_of_professional_conduct/rule_3_3_candor_toward_the_tribunal/",
        "https://www.americanbar.org/groups/professional_responsibility/publications/model_rules_of_professional_conduct/rule_3_3_candor_toward_the_tribunal/comment_on_rule_3_3/",
        "https://www.americanbar.org/groups/professional_responsibility/publications/model_rules_of_professional_conduct/rule_3_4_fairness_to_opposing_party_counsel/",
        "https://www.americanbar.org/groups/professional_responsibility/publications/model_rules_of_professional_conduct/rule_3_4_fairness_to_opposing_party_counsel/comment_on_rule_3_4/",
        "https://www.americanbar.org/groups/professional_responsibility/publications/model_rules_of_professional_conduct/rule_4_1_truthfulness_in_statements_to_others/",
        "https://www.americanbar.org/groups/professional_responsibility/publications/model_rules_of_professional_conduct/rule_4_1_truthfulness_in_statements_to_others/comment_on_rule_4_1/",
        "https://govt.westlaw.com/nycrr/Index",
        "https://govt.westlaw.com/nycrr/Document/I7544f8911a4a11deab58fec8fbeb48b1",
        "https://www.calbar.ca.gov/Attorneys/Conduct-Discipline/Rules/Rules-of-Professional-Conduct/Current-Rules",
        "https://www.calbar.ca.gov/Portals/0/documents/rules/Rules-of-Professional-Conduct.pdf",
    )
    assert all(source in text for source in official_sources)
    assert text.count("retrieved 2026-08-17") >= len(official_sources)


def test_ethics_reference_reports_retrieval_limits_without_overclaiming_currency() -> (
    None
):
    text = REFERENCE.read_text(encoding="utf-8")
    required_fragments = (
        "official publishers, not to the reader",
        "not authenticated Westlaw or comprehensive currentness research",
        "Current through May 31, 2021",
        "The PDF is titled **2026 Current Rules**",
    )
    assert all(fragment in text for fragment in required_fragments)
