"""Initial delivery fidelity, not a policy for the lawyer's later Word edits."""

import copy
import importlib.util
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import pytest
from public_fixture import upgrade

ROOT = Path(__file__).resolve().parents[4]
SCRIPTS = ROOT / "skills/litigation/document-discovery/scripts"
INPUTS = ROOT / "packages/skill-tests/tests/document_discovery/fixtures"


def load(name, path=None):
    spec = importlib.util.spec_from_file_location(name, path or SCRIPTS / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


core = load("objection_review")
word = load("objection_word")


@pytest.fixture
def chain():
    review = upgrade(core.read(INPUTS / "review.json"), INPUTS / "served-requests.md")
    rows = []
    for index, request in enumerate(review["requests"]):
        choices = [
            {
                "component_id": f"choice-{index}-{n}",
                "entry_id": None,
                "params": {},
                "wording": text,
                "edited": True,
                "scope": "",
                "notes": "A review note excluded from Word.",
            }
            for n, text in enumerate(
                [
                    "First approved wording. Its qualification remains.",
                    "Second wording.",
                ]
                if index == 0
                else []
            )
        ]
        row = {
            "request_id": request["id"],
            "state": "reviewed",
            "notes": "Review note, not operative text.",
            "drafts": copy.deepcopy(choices),
            "selected_ids": [c["component_id"] for c in choices],
            "choices": choices,
            "action": {"kind": "individual", "at": "synthetic-test"},
        }
        row["action"]["reviewed_content_sha256"] = core.digest(
            core.reviewed_content(review, row)
        )
        rows.append(row)
    selections = {
        "kind": "objection-selections",
        "format_version": 2,
        "purpose": "assembly",
        "review_id": review["id"],
        "review_sha256": core.digest(review),
        "source_sha256": review["source"]["sha256"],
        "library_sha256": core.digest(review["library"]),
        "rows": rows,
    }
    assembly = core.materialize(review, selections)
    layout = {
        "kind": "objection-word-layout",
        "format_version": 1,
        "review_sha256": assembly["review_sha256"],
        "selections_sha256": assembly["selections_sha256"],
        "requests": [
            {
                "request_id": r["id"],
                "request_heading": r["label"],
                "response_heading": f"Response to {r['label']}",
                "drafting_prompt": f"[Substantive response for {r['id']} to complete.]",
            }
            for r in assembly["requests"]
        ],
        "after_responses": "Dated: [Date]",
    }
    return review, selections, assembly, layout


def paragraphs_for(assembly, layout):
    paragraphs = ["Caption from the supplied template."]
    for request, frame in zip(assembly["requests"], layout["requests"], strict=True):
        paragraphs.extend(
            [frame["request_heading"], request["text"], frame["response_heading"]]
        )
        paragraphs.extend(c["wording"] for c in request["components"])
        paragraphs.extend(["", frame["drafting_prompt"]])
    return [*paragraphs, layout["after_responses"], "Signature block from template."]


def docx(path, paragraphs, table_index=None, field_index=None):
    root = ET.Element(word.W + "document")
    body = ET.SubElement(root, word.W + "body")
    for i, text in enumerate(paragraphs):
        parent = body
        if i == table_index:
            parent = ET.SubElement(
                ET.SubElement(ET.SubElement(body, word.W + "tbl"), word.W + "tr"),
                word.W + "tc",
            )
        paragraph = ET.SubElement(parent, word.W + "p")
        # Run boundaries may split words. These must not change visible text.
        midpoint = len(text) // 2
        for part in (text[:midpoint], text[midpoint:]):
            run = ET.SubElement(paragraph, word.W + "r")
            ET.SubElement(run, word.W + "t").text = part
        if i == field_index:
            ET.SubElement(ET.SubElement(paragraph, word.W + "r"), word.W + "fldChar")
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", ET.tostring(root))
        archive.writestr("word/header1.xml", f'<w:hdr xmlns:w="{word.W[1:-1]}"/>')


def checked(chain, path):
    review, selections, assembly, layout = chain
    return word.bind(assembly, path, review, selections, layout)


def test_initial_word_exact_region_split_runs_and_later_edits(chain, tmp_path):
    _, _, assembly, layout = chain
    paragraphs = paragraphs_for(assembly, layout)
    original = tmp_path / "initial.docx"
    docx(original, paragraphs)
    before = original.read_bytes()
    bound = checked(chain, original)
    assert len(bound["baseline"]["mapping"]) == len(assembly["requests"])
    assert bound["baseline"]["other_stories"] == ["word/header1.xml"]
    assert original.read_bytes() == before
    paragraphs[paragraphs.index("Second wording.")] = "Later deliberate Word rewriting."
    returned = tmp_path / "returned.docx"
    docx(returned, paragraphs)
    observed = word.compare(bound, original, returned)
    assert observed["observations"][0]["after"] == "Later deliberate Word rewriting."
    assert original.read_bytes() == before


@pytest.mark.parametrize("where", ["before", "between", "after", "none", "last"])
def test_initial_word_rejects_extra_unselected_text(chain, tmp_path, where):
    _, _, assembly, layout = chain
    paragraphs = paragraphs_for(assembly, layout)
    first = paragraphs.index(assembly["requests"][0]["components"][0]["wording"])
    indexes = {
        "before": first,
        "between": first + 1,
        "after": first + 2,
        "none": paragraphs.index(layout["requests"][1]["drafting_prompt"]),
        "last": paragraphs.index(layout["after_responses"]),
    }
    paragraphs.insert(indexes[where], "Additional language that was never selected.")
    path = tmp_path / "extra.docx"
    docx(path, paragraphs)
    with pytest.raises(ValueError, match="Saved request/response region differs"):
        checked(chain, path)


@pytest.mark.parametrize("mutation", ["qualifier", "duplicate", "omit", "reorder"])
def test_initial_word_rejects_changed_components(chain, tmp_path, mutation):
    _, _, assembly, layout = chain
    paragraphs = paragraphs_for(assembly, layout)
    first = paragraphs.index(assembly["requests"][0]["components"][0]["wording"])
    if mutation == "qualifier":
        paragraphs[first] = "First approved wording."
    elif mutation == "duplicate":
        paragraphs.insert(first, paragraphs[first])
    elif mutation == "omit":
        paragraphs.pop(first)
    else:
        paragraphs[first], paragraphs[first + 1] = (
            paragraphs[first + 1],
            paragraphs[first],
        )
    path = tmp_path / "changed.docx"
    docx(path, paragraphs)
    with pytest.raises(ValueError, match="Saved request/response region differs"):
        checked(chain, path)


def test_initial_word_allows_paragraph_splits_and_blank_drafting_space(chain, tmp_path):
    _, _, assembly, layout = chain
    paragraphs = paragraphs_for(assembly, layout)
    text = assembly["requests"][0]["components"][0]["wording"]
    i = paragraphs.index(text)
    paragraphs[i : i + 1] = [
        "First approved wording.",
        "",
        "Its qualification remains.",
    ]
    path = tmp_path / "split.docx"
    docx(path, paragraphs)
    bound = checked(chain, path)
    assert bound["baseline"]["mapping"][0]["components"][0]["span"] == [i, i + 3]


def test_initial_word_revalidates_original_decisions_not_assembly(chain, tmp_path):
    review, selections, assembly, layout = chain
    altered = copy.deepcopy(assembly)
    altered["requests"][0]["components"][0]["wording"] = (
        "Independently altered assembly."
    )
    altered["requests"][0]["objection_text"] = "Independently altered assembly."
    path = tmp_path / "altered.docx"
    docx(path, paragraphs_for(altered, layout))
    with pytest.raises(ValueError, match="Assembly differs"):
        word.bind(altered, path, review, selections, layout)


def test_initial_word_requires_chain_and_matching_layout(chain, tmp_path):
    review, selections, assembly, layout = chain
    path = tmp_path / "initial.docx"
    docx(path, paragraphs_for(assembly, layout))
    with pytest.raises(ValueError, match="original review"):
        word.bind(assembly, path)
    layout["selections_sha256"] = "wrong"
    with pytest.raises(ValueError, match="different review or decisions"):
        word.bind(assembly, path, review, selections, layout)


def test_initial_word_layout_cannot_rename_served_request(chain, tmp_path):
    review, selections, assembly, layout = chain
    layout["requests"][0]["request_heading"] = "REQUEST FOR PRODUCTION NO. 999"
    path = tmp_path / "changed-heading.docx"
    docx(path, paragraphs_for(assembly, layout))
    with pytest.raises(ValueError, match="heading"):
        word.bind(assembly, path, review, selections, layout)


def test_initial_word_rejects_changed_selection_under_old_review_action(
    chain, tmp_path
):
    review, selections, assembly, layout = chain
    path = tmp_path / "initial.docx"
    docx(path, paragraphs_for(assembly, layout))
    row = selections["rows"][0]
    row["choices"][0]["wording"] = "Changed after review."
    row["drafts"][0]["wording"] = "Changed after review."
    # Matching altered assembly and layout hashes cannot restore the old approval.
    assembly["requests"][0]["components"][0]["wording"] = "Changed after review."
    assembly["selections_sha256"] = core.digest(selections)
    layout["selections_sha256"] = core.digest(selections)
    with pytest.raises(ValueError, match="changed after the recorded review"):
        word.bind(assembly, path, review, selections, layout)


@pytest.mark.parametrize("change", ["missing", "duplicate", "changed"])
def test_initial_word_request_occurrences_are_complete(chain, tmp_path, change):
    _, _, assembly, layout = chain
    paragraphs = paragraphs_for(assembly, layout)
    i = paragraphs.index(assembly["requests"][2]["text"])
    if change == "missing":
        paragraphs.pop(i)
    elif change == "duplicate":
        paragraphs.insert(i, paragraphs[i])
    else:
        paragraphs[i] += " Altered request."
    path = tmp_path / "requests.docx"
    docx(path, paragraphs)
    with pytest.raises(ValueError, match="request"):
        checked(chain, path)


@pytest.mark.parametrize("unsupported", ["table", "field"])
def test_initial_word_boundary_is_explicit(chain, tmp_path, unsupported):
    _, _, assembly, layout = chain
    paragraphs = paragraphs_for(assembly, layout)
    index = paragraphs.index("Second wording.")
    path = tmp_path / "unsupported.docx"
    docx(path, paragraphs, **{unsupported + "_index": index})
    with pytest.raises(ValueError, match="ordinary body paragraphs only"):
        checked(chain, path)


def test_initial_word_caption_table_remains_outside_check(chain, tmp_path):
    _, _, assembly, layout = chain
    path = tmp_path / "caption-table.docx"
    docx(path, paragraphs_for(assembly, layout), table_index=0)
    assert (
        checked(chain, path)["baseline"]["initial_fidelity"]["response_region"][0] == 1
    )


def test_initial_word_allows_deliberately_selected_equal_components(chain, tmp_path):
    review, selections, _, layout = chain
    row = selections["rows"][0]
    row["choices"][1]["wording"] = row["choices"][0]["wording"]
    row["drafts"] = copy.deepcopy(row["choices"])
    row["action"]["reviewed_content_sha256"] = core.digest(
        core.reviewed_content(review, row)
    )
    assembly = core.materialize(review, selections)
    layout["selections_sha256"] = assembly["selections_sha256"]
    path = tmp_path / "deliberate-repeat.docx"
    docx(path, paragraphs_for(assembly, layout))
    bound = word.bind(assembly, path, review, selections, layout)
    first, second = bound["baseline"]["mapping"][0]["components"]
    assert first["span"][1] == second["span"][0]
    assert first["component_id"] != second["component_id"]
