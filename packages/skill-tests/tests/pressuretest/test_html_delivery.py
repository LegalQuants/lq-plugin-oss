"""HTML delivery preserves adjudications and cannot execute supplied text."""

import json
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[4] / "skills/litigation/pressuretest/scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(Path(__file__).parent))

from render_brief import RenderError, render  # noqa: E402
from render_fixtures import SOURCES, base  # noqa: E402
from test_chat_delivery import all_findings, chat_fixture  # noqa: E402


class Page(HTMLParser):
    def __init__(self, value):
        super().__init__()
        self.tags = []
        self.words = []
        self.feed(value)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))

    def handle_data(self, data):
        self.words.append(data)

    @property
    def text(self):
        return "".join(self.words)


def test_every_finding_field_and_quote_survives_html():
    data = chat_fixture(verdict="pressure_points", findings=all_findings())
    data["brief"].update(
        established="Established detail",
        follows="Consequence detail",
        context_items=["Scope qualification"],
    )
    for n, finding in enumerate(data["findings"]):
        for field in (
            "statement",
            "test_applied",
            "survives",
            "smallest_change",
            "what_would_close",
            "next_step",
        ):
            finding[field] = f"Unique {field} for finding {n}"
    page = Page(render(data, "html"))
    assert len([t for t, _ in page.tags if t == "details"]) == len(data["findings"])
    for f in data["findings"]:
        for field in (
            "title",
            "statement",
            "hits",
            "test_applied",
            "survives",
            "flip_statement",
            "defect_statement",
            "dispositive_anchor_note",
            "smallest_change",
            "what_would_close",
            "next_step",
        ):
            if f.get(field) and (
                field != "hits"
                or f["classification"] in ("breaks_position", "internal_defect")
            ):
                assert f[field] in page.text, field
        assert page.text.count(f["statement"]) == 1
        for anchor in f["anchors"]:
            assert anchor["quote"] in page.text
            assert anchor["locator"] in page.text
            assert data["sources"][anchor["source"]]["name"] in page.text
    assert data["strongest_route"]["summary"] in page.text
    for field in ("summary", "established", "follows"):
        assert data["brief"][field] in page.text
    assert "Scope qualification" in page.text


@pytest.mark.parametrize("verdict", ["position_holds", "pressure_points", "incomplete"])
def test_verdict_and_incomplete_limit_are_prominent(verdict):
    data = chat_fixture(
        verdict=verdict, incomplete_reason="Missing annex prevents completion."
    )
    page = Page(render(data, "html"))
    if verdict == "incomplete":
        assert page.text.index(data["incomplete_reason"]) < page.text.index(
            "Position tested"
        )
    elif verdict == "position_holds":
        assert "withstands the objections tested" in page.text
    else:
        assert "contradictions that need correction" in page.text
    assert (
        "not an additional problem or proof that the whole position is correct"
        in page.text
    )


def test_adverse_findings_open_and_answered_objections_are_separate():
    data = chat_fixture(verdict="pressure_points", findings=all_findings())
    output = render(data, "html")
    page = Page(output)
    for tag, attrs in page.tags:
        if tag == "details":
            expected = any(
                cls in attrs["class"] for cls in ("breaks_position", "internal_defect")
            )
            assert ("open" in attrs) == expected
    assert output.index('id="breaks_position"') < output.index('id="defeated"')
    attention = output.split('<ul class="attention">')[1].split("</ul>")[0]
    for f in data["findings"]:
        if f["classification"] in ("defeated", "weakens_route"):
            assert f["title"] not in attention


def test_source_and_model_text_cannot_create_html_or_scripts():
    data = chat_fixture()
    payload = (
        '</script><img src="https://evil.invalid" onerror="alert(1)">& <b>text</b>'
    )
    data["brief"]["summary"] = payload
    data["brief"]["position_name"] = "{{CONTENT}} " + payload
    data["findings"][0]["anchors"][0]["quote"] = payload
    data["sources"]["C1.md"]["name"] = payload
    page = Page(render(data, "html"))
    assert payload in page.text
    assert not any(t in ("img", "b", "iframe") for t, _ in page.tags)
    assert len([t for t, _ in page.tags if t == "script"]) == 1
    assert not any("src" in a or "onerror" in a for _, a in page.tags)


def test_existing_sources_link_but_missing_and_outside_sources_do_not(tmp_path):
    data = chat_fixture()
    (tmp_path / "C1.md").write_text("source", encoding="utf-8")
    page = Page(render(data, "html", tmp_path))
    links = [a["href"] for t, a in page.tags if t == "a"]
    assert (tmp_path / "C1.md").as_uri() in links
    assert not any("C4.md" in link for link in links)
    for filename in ("../outside.md", "https://evil.invalid/file"):
        data["coverage"]["selected"].append(filename)
        data["coverage"]["excluded"].append(filename)
        data["sources"][filename] = {"name": "Outside file", "date": None}
    output = render(data, "html", tmp_path)
    assert "evil.invalid" not in output
    assert "../outside.md" not in output


def test_short_handoff_does_not_repeat_detailed_findings():
    data = chat_fixture(verdict="pressure_points", findings=all_findings())
    output = render(data, "handoff")
    assert data["brief"]["summary"] in output
    for f in data["findings"]:
        assert f["statement"] not in output
    assert "Open the report linked below" in output


def test_html_rejects_legacy_and_unknown_sources():
    with pytest.raises(RenderError):
        render(base(), "html")
    data = chat_fixture()
    data["findings"][0]["anchors"][0]["source"] = "unknown.md"
    with pytest.raises(RenderError):
        render(data, "html")


def test_cli_html_and_handoff_binding_detects_omitted_or_changed_content(tmp_path):
    data = chat_fixture()
    record = tmp_path / "deliverable.json"
    record.write_text(json.dumps(data), encoding="utf-8")
    for name, content in SOURCES.items():
        (tmp_path / name).write_text(content, encoding="utf-8")
    outputs = []
    for fmt in ("html", "handoff"):
        path = tmp_path / f"result.{fmt}"
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "render_brief.py"),
                str(record),
                "--format",
                fmt,
                "--source-root",
                str(tmp_path),
                "--out",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, result.stderr
        outputs += [f"--{fmt}", str(path)]
    command = [
        sys.executable,
        str(SCRIPTS / "validate_deliverable.py"),
        str(record),
        "--source-root",
        str(tmp_path),
        *outputs,
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout
    path = tmp_path / "result.html"
    original = path.read_text(encoding="utf-8")
    path.write_text(
        original.replace(data["findings"][0]["statement"], "Omitted finding"),
        encoding="utf-8",
    )
    result = subprocess.run(command, capture_output=True, text=True, timeout=30)
    assert result.returncode == 1
    assert "result_record_mismatch" in result.stdout
    path.write_text(original, encoding="utf-8")
    summary = tmp_path / "result.handoff"
    summary.write_text("Everything is fine.\n", encoding="utf-8")
    result = subprocess.run(command, capture_output=True, text=True, timeout=30)
    assert result.returncode == 1
    assert "result_record_mismatch" in result.stdout
