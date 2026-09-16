"""Mechanical floor for `evidence.py`: bounded, cited, honest-on-failure
lookups used by /lq-connect (code/page) and /lq-ask (search-builds,
resolve-member). Every case uses --fixture-raw/--fixture-html so nothing here
touches the network — see the script's own docstring for why that's the only
seam that needs stubbing.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / "skills" / "companion" / "legalquants" / "scripts" / "evidence.py"

BUILDS_FIXTURE = (
    '{\\"id\\":\\"11111111-1111-1111-1111-111111111111\\",'
    '\\"title\\":\\"Fixture Clause Bank\\",'
    '\\"description\\":\\"A fictional tool that extracts and organizes clauses\\",'
    '\\"practiceArea\\":null,\\"by\\":\\"Fictional Builder\\"},'
    '{\\"id\\":\\"22222222-2222-2222-2222-222222222222\\",'
    '\\"title\\":\\"Fixture Widget\\",'
    '\\"description\\":\\"An unrelated fictional widget\\",'
    '\\"practiceArea\\":\\"Litigation & Disputes\\",\\"by\\":\\"Someone Else\\"}'
)

COMMUNITY_FIXTURE = (
    '{\\"slug\\":\\"fictional-builder\\",\\"name\\":\\"Fictional Builder\\",'
    '\\"title\\":\\"Fixture Title\\",\\"tagline\\":\\"Fixture tagline\\",'
    '\\"location\\":null,\\"photoUrl\\":null,\\"country\\":null,\\"practice\\":null,'
    '\\"featuredWork\\":{\\"title\\":\\"Fixture Clause Bank\\",'
    '\\"url\\":\\"https://example.com/fixture\\",\\"screenshotUrl\\":null,'
    '\\"blurb\\":\\"A fictional tool that extracts and organizes clauses\\"},'
    '\\"worksCount\\":1,\\"workTitles\\":[\\"Fixture Clause Bank\\"],'
    '\\"contribCount\\":0,\\"membersOnly\\":false}'
)

DUPLICATE_NAME_FIXTURE = (
    '{\\"slug\\":\\"a-duplicate\\",\\"name\\":\\"Duplicate Name\\",'
    '\\"title\\":\\"\\",\\"tagline\\":\\"\\",\\"location\\":null,\\"photoUrl\\":null,'
    '\\"country\\":null,\\"practice\\":null,\\"featuredWork\\":null,'
    '\\"worksCount\\":0,\\"workTitles\\":[],\\"contribCount\\":0,\\"membersOnly\\":false},'
    '{\\"slug\\":\\"b-duplicate\\",\\"name\\":\\"Duplicate Name\\",'
    '\\"title\\":\\"\\",\\"tagline\\":\\"\\",\\"location\\":null,\\"photoUrl\\":null,'
    '\\"country\\":null,\\"practice\\":null,\\"featuredWork\\":null,'
    '\\"worksCount\\":0,\\"workTitles\\":[],\\"contribCount\\":0,\\"membersOnly\\":false}'
)


def run(*args: str):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args], capture_output=True, text=True
    )


# --- code -------------------------------------------------------------


def test_code_returns_the_requested_line_range(tmp_path):
    raw = tmp_path / "file.py"
    raw.write_text("\n".join(f"line {i}" for i in range(1, 11)))
    out = json.loads(
        run(
            "code",
            "--repo",
            "example/repo",
            "--path",
            "file.py",
            "--fixture-raw",
            str(raw),
            "--start-line",
            "3",
            "--end-line",
            "5",
        ).stdout
    )
    assert out["ok"] is True
    assert out["start_line"] == 3 and out["end_line"] == 5
    assert out["text"] == "line 3\nline 4\nline 5"


def test_code_caps_excerpt_at_120_lines(tmp_path):
    raw = tmp_path / "big.py"
    raw.write_text("\n".join(f"line {i}" for i in range(1, 501)))
    out = json.loads(
        run(
            "code",
            "--repo",
            "example/repo",
            "--path",
            "big.py",
            "--fixture-raw",
            str(raw),
        ).stdout
    )
    assert out["ok"] is True
    assert out["end_line"] - out["start_line"] + 1 == 120
    assert out["truncated"] is True


def test_code_refuses_excluded_paths():
    for path in ("node_modules/x.js", "pnpm-lock.yaml", ".env.production", "id_rsa"):
        out = json.loads(
            run(
                "code",
                "--repo",
                "example/repo",
                "--path",
                path,
                "--fixture-raw",
                "/dev/null",
            ).stdout
        )
        assert out == {"ok": False, "reason": "excluded_path", "path": path}


def test_code_refuses_a_malformed_repo():
    out = json.loads(run("code", "--repo", "not-a-repo", "--path", "x.py").stdout)
    assert out["ok"] is False and out["reason"] == "bad_repo"


def test_code_refuses_path_traversal():
    out = json.loads(
        run("code", "--repo", "example/repo", "--path", "../../etc/passwd").stdout
    )
    assert out["ok"] is False and out["reason"] == "bad_path"


# --- page ---------------------------------------------------------------


def test_page_extracts_visible_text_and_strips_scripts(tmp_path):
    page = tmp_path / "page.html"
    page.write_text(
        "<html><body><script>var x = 'not this';</script>"
        "<p>A fictional Substack post about clause automation.</p></body></html>"
    )
    out = json.loads(
        run("page", "--fixture-html", str(page), "--max-chars", "500").stdout
    )
    assert out["ok"] is True
    assert "not this" not in out["text"]
    assert "clause automation" in out["text"]


def test_page_reports_a_bot_challenge_instead_of_the_wall(tmp_path):
    page = tmp_path / "wall.html"
    page.write_text(
        "<html><body>Checking your browser before continuing...</body></html>"
    )
    out = json.loads(run("page", "--fixture-html", str(page)).stdout)
    assert out == {
        "ok": False,
        "reason": "bot_challenge",
        "matched": "checking your browser",
    }


def test_page_respects_the_max_chars_cap(tmp_path):
    page = tmp_path / "long.html"
    page.write_text(f"<html><body><p>{'x' * 30_000}</p></body></html>")
    out = json.loads(
        run("page", "--fixture-html", str(page), "--max-chars", "50000").stdout
    )
    assert out["ok"] is True
    assert len(out["text"]) == 16_000  # MAX_PAGE_CHARS_CAP wins over a larger request
    assert out["truncated"] is True


# --- search-builds --------------------------------------------------------


def test_search_builds_ranks_the_matching_fixture_record(tmp_path):
    page = tmp_path / "builds.html"
    page.write_text(f'<script>self.__next_f.push([1,"{BUILDS_FIXTURE}"])</script>')
    out = json.loads(
        run("search-builds", "clause bank", "--fixture-html", str(page)).stdout
    )
    assert out["ok"] is True
    assert out["total_records_parsed"] == 2
    assert out["matches"][0]["title"] == "Fixture Clause Bank"
    assert out["matches"][0]["by"] == "Fictional Builder"


def test_search_builds_reports_when_nothing_parses(tmp_path):
    page = tmp_path / "empty.html"
    page.write_text("<html><body>no builds here</body></html>")
    out = json.loads(
        run("search-builds", "clause bank", "--fixture-html", str(page)).stdout
    )
    assert out == {
        "ok": False,
        "reason": "no_records_parsed",
        "source": "https://www.legalquants.com/builds",
    }


# --- resolve-member ---------------------------------------------------------


def test_resolve_member_returns_the_slug_and_featured_work(tmp_path):
    page = tmp_path / "community.html"
    page.write_text(f'<script>self.__next_f.push([1,"{COMMUNITY_FIXTURE}"])</script>')
    out = json.loads(
        run("resolve-member", "Fictional Builder", "--fixture-html", str(page)).stdout
    )
    assert out == {
        "ok": True,
        "slug": "fictional-builder",
        "name": "Fictional Builder",
        "profile_url": "https://www.legalquants.com/profile/fictional-builder",
        "featured_work": {
            "title": "Fixture Clause Bank",
            "url": "https://example.com/fixture",
        },
    }


def test_resolve_member_refuses_to_guess_an_absent_name(tmp_path):
    page = tmp_path / "community.html"
    page.write_text(f'<script>self.__next_f.push([1,"{COMMUNITY_FIXTURE}"])</script>')
    out = json.loads(
        run("resolve-member", "Nobody Here", "--fixture-html", str(page)).stdout
    )
    assert out == {"ok": False, "reason": "not_found", "name": "Nobody Here"}


def test_resolve_member_refuses_to_guess_an_ambiguous_name(tmp_path):
    page = tmp_path / "community.html"
    page.write_text(
        f'<script>self.__next_f.push([1,"{DUPLICATE_NAME_FIXTURE}"])</script>'
    )
    out = json.loads(
        run("resolve-member", "Duplicate Name", "--fixture-html", str(page)).stdout
    )
    assert out["ok"] is False
    assert out["reason"] == "ambiguous"
    assert set(out["candidates"]) == {"a-duplicate", "b-duplicate"}
