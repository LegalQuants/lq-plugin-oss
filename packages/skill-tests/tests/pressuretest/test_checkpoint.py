"""Checkpoint-overlap contract (method v2.8).

The map may be shown before the whole bundle is read, so the lawyer's wait
overlaps the remaining reading. The companion records what had been read
when the map was posted, the docket states it, and the receipt discloses
it. Run from the repo root: uv run pytest tests/pressuretest -q
"""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
SCRIPTS = REPO / "skills" / "litigation" / "pressuretest" / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import render_brief as rb  # noqa: E402
from render_fixtures import SOURCES, base  # noqa: E402

CLEAN_DOCKET = (
    "# Untested — questions I am about to test, not findings\n"
    "Read so far: C1.md, C4.md\n"
    "- Does the waiver period cover the assessment date? C4 2.1 — testing.\n"
)


def validate(deliverable, docket=None):
    tmp = Path(tempfile.mkdtemp(prefix="ptv28c_"))
    try:
        root = tmp / "input"
        root.mkdir()
        for name, text in SOURCES.items():
            (root / name).write_text(text, encoding="utf-8")
        dpath = tmp / "deliverable.json"
        dpath.write_text(json.dumps(deliverable), encoding="utf-8")
        cmd = [
            sys.executable,
            str(SCRIPTS / "validate_deliverable.py"),
            str(dpath),
            "--source-root",
            str(root),
        ]
        if docket is not None:
            kpath = tmp / "docket.md"
            kpath.write_text(docket, encoding="utf-8")
            cmd += ["--docket", str(kpath)]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        return proc.returncode, json.loads(proc.stdout)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def codes(payload):
    return [f["code"] for f in payload["faults"]]


class TestCheckpointContract(unittest.TestCase):
    def test_full_read_before_map_passes(self):
        code, out = validate(base())
        self.assertEqual(code, 0, out)

    def test_checkpoint_block_required(self):
        d = base()
        del d["checkpoint"]
        code, out = validate(d)
        self.assertEqual(code, 1)
        self.assertIn("missing_checkpoint", codes(out))

    def test_map_read_must_name_selected_documents(self):
        d = base()
        d["checkpoint"]["map_read"] = ["ghost.md"]
        code, out = validate(d)
        self.assertEqual(code, 1)
        self.assertIn("checkpoint_map_read_unknown", codes(out))

    def test_map_read_must_not_be_empty(self):
        d = base()
        d["checkpoint"]["map_read"] = []
        code, out = validate(d)
        self.assertEqual(code, 1)
        self.assertIn("checkpoint_map_read_empty", codes(out))

    def test_change_after_full_read_needs_a_note(self):
        d = base()
        d["checkpoint"]["map_read"] = ["C1.md"]
        d["checkpoint"]["map_changed_after_full_read"] = True
        code, out = validate(d)
        self.assertEqual(code, 1)
        self.assertIn("missing_change_note", codes(out))
        d["checkpoint"]["change_note"] = "C4 added an express override to the route."
        code, out = validate(d)
        self.assertEqual(code, 0, out)


class TestDocketReadList(unittest.TestCase):
    def test_docket_must_state_what_was_read(self):
        code, out = validate(base(), docket="# Untested\n- Does the waiver cover it?\n")
        self.assertEqual(code, 1)
        self.assertIn("docket_missing_read_list", codes(out))

    def test_docket_with_read_list_passes(self):
        code, out = validate(base(), docket=CLEAN_DOCKET)
        self.assertEqual(code, 0, out)


class TestReceiptDisclosure(unittest.TestCase):
    def test_partial_read_at_map_time_is_disclosed(self):
        d = base()
        d["checkpoint"]["map_read"] = ["C1.md"]
        text = rb.render(d)
        self.assertIn("shown after reading 1 of 2 documents (C1.md)", text)
        self.assertIn("the rest were read while the lawyer considered it", text)

    def test_full_read_at_map_time_is_stated(self):
        text = rb.render(base())
        self.assertIn("shown after reading all 2 documents", text)

    def test_change_note_is_rendered(self):
        d = base()
        d["checkpoint"]["map_read"] = ["C1.md"]
        d["checkpoint"]["map_changed_after_full_read"] = True
        d["checkpoint"]["change_note"] = "C4 added an express override to the route."
        text = rb.render(d)
        self.assertIn("The map changed after the full read:", text)
        self.assertIn("C4 added an express override to the route.", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
