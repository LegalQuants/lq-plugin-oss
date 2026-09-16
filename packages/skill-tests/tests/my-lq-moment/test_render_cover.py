"""The cover renderer: template embedded, two sentences set, fixed filenames."""

from __future__ import annotations

import base64
import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
SKILL = ROOT / "skills/companion/my-lq-moment"
SCRIPT = SKILL / "scripts" / "render_cover.py"
TEMPLATE = SKILL / "assets" / "cover-template.png"


def _load():
    spec = importlib.util.spec_from_file_location("render_cover", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MODULE = _load()
BEFORE = "Twelve markups used to mean a four-hour spreadsheet slog."
AFTER = "Now: one checked issue map the whole deal team works from."
LONG_AFTER = (
    "Now it is one issue map, checked against the source, "
    "that the whole deal team can work from."
)


def test_template_ships_as_a_1200_square_png() -> None:
    data = TEMPLATE.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    width = int.from_bytes(data[16:20], "big")
    height = int.from_bytes(data[20:24], "big")
    assert (width, height) == (1200, 1200)


def test_wrap_never_splits_words_and_respects_width() -> None:
    lines = MODULE.wrap(AFTER, 72, True, MODULE.RIGHT - MODULE.LEFT)
    assert " ".join(lines) == AFTER
    assert len(lines) >= 2
    for line in lines:
        assert MODULE.estimate_width(line, 72, True) <= MODULE.RIGHT - MODULE.LEFT


def test_layout_uses_fixed_sizes_and_never_shrinks() -> None:
    plan = MODULE.layout(BEFORE, AFTER)
    assert plan["fits"]
    assert plan["before"]["size"] == MODULE.BEFORE_SIZE
    assert plan["after"]["size"] == MODULE.AFTER_SIZE
    assert len(plan["before"]["lines"]) <= MODULE.MAX_BEFORE_LINES
    assert len(plan["after"]["lines"]) <= MODULE.MAX_AFTER_LINES
    assert plan["y"] >= MODULE.TOP
    total = (
        len(plan["before"]["lines"]) * plan["before"]["line_height"]
        + plan["gap"]
        + len(plan["after"]["lines"]) * plan["after"]["line_height"]
    )
    assert plan["y"] + total <= MODULE.BOTTOM


def test_svg_embeds_the_template_and_escapes_the_sentences() -> None:
    svg = MODULE.build_svg(
        "Before & after <one>.", "The lawyer's call, still.", TEMPLATE.read_bytes()
    )
    assert base64.b64encode(TEMPLATE.read_bytes()).decode("ascii") in svg
    assert "Before &amp; after &lt;one&gt;." in svg
    assert "The lawyer's call, still." in svg
    assert svg.count("<text") >= 2
    assert 'width="1200" height="1200"' in svg


def test_practice_cover_is_permanently_labelled() -> None:
    svg = MODULE.build_svg(BEFORE, AFTER, TEMPLATE.read_bytes(), practice=True)
    assert MODULE.PRACTICE_LABEL in svg


@pytest.mark.parametrize(
    "before, after, fragment",
    [
        ("", AFTER, "empty"),
        ("x" * 200, AFTER, "too long for the cover"),
        (BEFORE, LONG_AFTER, "too long for the cover: cut about"),
        ("One sentence. Two sentences. Three.", AFTER, "more than one sentence"),
        (
            "Wwwwwwwwww Mmmmmmmmmm Wwwwwwwwww Mmmmmmmmmm Wwwwwwwwww Mmmmmmmm",
            AFTER,
            "wraps to",
        ),
    ],
)
def test_bad_sentences_are_refused(
    tmp_path: Path, capsys, before: str, after: str, fragment: str
) -> None:
    code = MODULE.main(
        ["--before", before, "--after", after, "--out-dir", str(tmp_path)]
    )
    assert code == 2
    assert fragment in json.loads(capsys.readouterr().out)["message"]
    assert not list(tmp_path.iterdir())


def test_refusal_names_the_word_budget(capsys, tmp_path: Path) -> None:
    code = MODULE.main(
        ["--before", BEFORE, "--after", LONG_AFTER, "--out-dir", str(tmp_path)]
    )
    assert code == 2
    message = json.loads(capsys.readouterr().out)["message"]
    assert "limit 12 words, 90 characters" in message


def test_svg_only_writes_a_fixed_filename(tmp_path: Path, capsys) -> None:
    code = MODULE.main(
        ["--before", BEFORE, "--after", AFTER, "--out-dir", str(tmp_path), "--svg-only"]
    )
    assert code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["svg"] == str(tmp_path / "my-lq-moment-cover.svg")
    assert out["png"] is None
    assert sorted(p.name for p in tmp_path.iterdir()) == ["my-lq-moment-cover.svg"]


def test_no_renderer_leaves_the_svg_and_says_so(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    monkeypatch.setattr(MODULE.shutil, "which", lambda name: None)
    monkeypatch.setattr(MODULE.platform, "system", lambda: "Linux")
    code = MODULE.main(
        ["--before", BEFORE, "--after", AFTER, "--out-dir", str(tmp_path)]
    )
    assert code == 3
    out = json.loads(capsys.readouterr().out)
    assert out["png"] is None and out["renderer"] is None
    assert "no SVG renderer" in out["message"]
    assert (tmp_path / "my-lq-moment-cover.svg").exists()
    assert out["attempts"] == []


def test_svg_only_removes_a_stale_png(tmp_path: Path, capsys) -> None:
    stale = tmp_path / "my-lq-moment-cover.png"
    stale.write_bytes(TEMPLATE.read_bytes())
    code = MODULE.main(
        ["--before", BEFORE, "--after", AFTER, "--out-dir", str(tmp_path), "--svg-only"]
    )
    assert code == 0
    capsys.readouterr()
    assert not stale.exists()


def _only_the_fake(monkeypatch, fake: Path) -> None:
    """Make `rsvg-convert` resolve to the fake and every other renderer to nothing."""

    real_which = MODULE.shutil.which

    def which(name: str, *args, **kwargs):
        if name == "rsvg-convert":
            return str(fake)
        if name in ("sh", "cp"):
            return real_which(name, *args, **kwargs)
        return None

    monkeypatch.setattr(MODULE.shutil, "which", which)
    monkeypatch.setattr(MODULE, "_chromium_candidates", lambda: [])


def test_a_failing_renderer_is_recorded_with_its_reason(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake = fake_bin / "rsvg-convert"
    fake.write_text("#!/bin/sh\necho 'sandbox: operation not permitted' >&2\nexit 1\n")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setattr(MODULE.platform, "system", lambda: "Linux")
    # Only the fake renderer exists: the chain must not fall through to a real
    # ImageMagick, Inkscape or browser on the machine running the tests.
    _only_the_fake(monkeypatch, fake)
    code = MODULE.main(
        ["--before", BEFORE, "--after", AFTER, "--out-dir", str(tmp_path / "out")]
    )
    assert code == 3
    out = json.loads(capsys.readouterr().out)
    assert out["png"] is None
    assert out["attempts"][0]["renderer"] == "rsvg-convert"
    assert out["attempts"][0]["status"] == 1
    assert "operation not permitted" in out["attempts"][0]["stderr_tail"]
    assert "escalated permission" in out["message"]


def test_failed_renderer_cannot_reuse_or_leave_a_png(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake = fake_bin / "rsvg-convert"
    fake.write_text(
        "#!/bin/sh\n"
        'out=""; while [ $# -gt 1 ]; do '
        'if [ "$1" = "-o" ]; then out="$2"; fi; shift; done\n'
        f'cp "{TEMPLATE}" "$out"\nexit 1\n'
    )
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", str(fake_bin))
    monkeypatch.setattr(MODULE.platform, "system", lambda: "Linux")
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    stale = out_dir / "my-lq-moment-cover.png"
    stale.write_bytes(TEMPLATE.read_bytes())
    code = MODULE.main(
        ["--before", BEFORE, "--after", AFTER, "--out-dir", str(out_dir)]
    )
    assert code == 3
    out = json.loads(capsys.readouterr().out)
    assert out["png"] is None
    assert out["attempts"][0]["status"] == 1
    assert not stale.exists()


def test_renderer_rejects_a_fresh_png_with_the_wrong_dimensions(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake = fake_bin / "rsvg-convert"
    wrong_size = bytearray(TEMPLATE.read_bytes())
    wrong_size[16:20] = (600).to_bytes(4, "big")
    wrong_size[20:24] = (600).to_bytes(4, "big")
    wrong_png = tmp_path / "wrong.png"
    wrong_png.write_bytes(wrong_size)
    fake.write_text(
        "#!/bin/sh\n"
        'out=""; while [ $# -gt 1 ]; do '
        'if [ "$1" = "-o" ]; then out="$2"; fi; shift; done\n'
        f'cp "{wrong_png}" "$out"\n'
    )
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setattr(MODULE.platform, "system", lambda: "Linux")
    # Only the fake renderer exists: the chain must not fall through to a real
    # ImageMagick, Inkscape or browser on the machine running the tests.
    _only_the_fake(monkeypatch, fake)
    out_dir = tmp_path / "out"
    code = MODULE.main(
        ["--before", BEFORE, "--after", AFTER, "--out-dir", str(out_dir)]
    )
    assert code == 3
    out = json.loads(capsys.readouterr().out)
    assert out["attempts"][0]["status"] == 0
    assert out["attempts"][0]["png_written"] is False
    assert not (out_dir / "my-lq-moment-cover.png").exists()


def test_practice_flag_marks_the_written_svg(tmp_path: Path, capsys) -> None:
    code = MODULE.main(
        [
            "--before",
            BEFORE,
            "--after",
            AFTER,
            "--out-dir",
            str(tmp_path),
            "--practice",
            "--svg-only",
        ]
    )
    assert code == 0
    capsys.readouterr()
    svg = (tmp_path / "my-lq-moment-cover.svg").read_text()
    assert MODULE.PRACTICE_LABEL in svg


def test_a_png_that_exists_after_a_timeout_still_counts(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake = fake_bin / "rsvg-convert"
    fake.write_text(
        "#!/bin/sh\n"
        'out=""; while [ $# -gt 1 ]; do '
        'if [ "$1" = "-o" ]; then out="$2"; fi; shift; done\n'
        f'cp "{TEMPLATE}" "$out"\nsleep 5\n'
    )
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setattr(MODULE.platform, "system", lambda: "Linux")
    monkeypatch.setattr(MODULE, "RENDER_TIMEOUT", 1)
    code = MODULE.main(
        ["--before", BEFORE, "--after", AFTER, "--out-dir", str(tmp_path / "out")]
    )
    assert code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["renderer"] == "rsvg-convert"
    assert out["attempts"][0]["status"] == "timeout"


def test_a_renderer_on_path_produces_the_png(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake = fake_bin / "rsvg-convert"
    fake.write_text(
        "#!/bin/sh\n"
        'out=""; while [ $# -gt 1 ]; do '
        'if [ "$1" = "-o" ]; then out="$2"; fi; shift; done\n'
        f'cp "{TEMPLATE}" "$out"\n'
    )
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setattr(MODULE.platform, "system", lambda: "Linux")
    out_dir = tmp_path / "out"
    code = MODULE.main(
        ["--before", BEFORE, "--after", AFTER, "--out-dir", str(out_dir)]
    )
    assert code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["renderer"] == "rsvg-convert"
    assert Path(out["png"]).name == "my-lq-moment-cover.png"
    assert Path(out["png"]).stat().st_size > 0


def test_script_imports_only_the_standard_library() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(("import ", "from ")):
            module = stripped.split()[1].split(".")[0]
            assert module in sys.stdlib_module_names, module
