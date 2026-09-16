"""Upgrade existing synthetic paragraph fixtures without altering old evidence.

This maintainer adapter recognizes the explicit headings in these fixtures. It
is not the production source parser and does not certify arbitrary extraction.
"""

import argparse
import copy
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "skills/litigation/document-discovery/scripts"))

import objection_review as core  # noqa: E402
import objection_source as source  # noqa: E402


def upgrade(review, path):
    extraction = source.capture(path)
    source.verify_source(extraction, path)
    core.require(
        review["source"] == extraction["source"], "Fixture source identity differs"
    )
    blocks = extraction["blocks"]
    heads = [
        i
        for i, block in enumerate(blocks)
        if re.fullmatch(
            r"(?:REQUEST FOR PRODUCTION NO\.|RFP)\s+\d+", block["text"].strip()
        )
    ]
    core.require(
        len(heads) == len(review["requests"]), "Fixture source/request count differs"
    )
    mapping = {"context": [], "requests": [], "other": []}
    claimed = set()
    for item in review["context"]:
        match = next((block for block in blocks if block["text"] == item["text"]), None)
        if match:
            mapping["context"].append(
                {
                    "id": item["id"],
                    "title": item["title"],
                    "spans": [{"block": match["id"]}],
                }
            )
            claimed.add(match["id"])
    context_ids = {item["id"] for item in mapping["context"]}
    draft = copy.deepcopy(review)
    for n, (offset, request) in enumerate(zip(heads, draft["requests"], strict=True)):
        end = heads[n + 1] if n + 1 < len(heads) else len(blocks)
        text_blocks = blocks[offset + 1 : end]
        text = "\n".join(block["text"] for block in text_blocks)
        core.require(
            text == request["text"], "Fixture request text differs from source"
        )
        original_number = re.search(r"\d+\s*$", request["label"])
        actual_number = re.search(r"\d+\s*$", blocks[offset]["text"])
        core.require(
            original_number
            and actual_number
            and original_number.group() == actual_number.group(),
            "Fixture printed request number differs",
        )
        request["label"] = blocks[offset]["text"]
        mapping["requests"].append(
            {
                "id": request["id"],
                "label_spans": [{"block": blocks[offset]["id"]}],
                "text_spans": [{"block": block["id"]} for block in text_blocks],
                "context_ids": [
                    key for key in request["context_ids"] if key in context_ids
                ],
            }
        )
        claimed.update(block["id"] for block in blocks[offset:end])
    for block in blocks:
        if block["id"] not in claimed:
            mapping["other"].append(
                {
                    "spans": [{"block": block["id"]}],
                    "reason": "Synthetic title/preamble before the requests",
                }
            )
    census = source.freeze(
        extraction,
        mapping,
        {
            "status": "checked",
            "by": "maintainer fixture adapter",
            "method": (
                "Direct raw paragraph capture, complete heading census "
                "and exact comparison with preserved fixture text"
            ),
            "notes": (
                "Development source check; no attorney approval or native rendering "
                "claim. Printed headings replace legacy abbreviated display labels."
            ),
            "unresolved": [],
        },
    )
    result = source.attach(draft, census)
    result["legacy_review_sha256"] = core.digest(review)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    core.write(args.out, upgrade(core.read(args.review), args.source))


if __name__ == "__main__":
    main()
