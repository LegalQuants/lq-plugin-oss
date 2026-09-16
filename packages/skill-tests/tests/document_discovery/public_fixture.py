"""Build the public synthetic objection review fixture with source binding."""

from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Any

import objection_review as core
import objection_source as source


def upgrade(review: dict[str, Any], path: Path) -> dict[str, Any]:
    """Attach an exact source census to the small public review fixture."""
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
    mapping: dict[str, list[dict[str, Any]]] = {
        "context": [],
        "requests": [],
        "other": [],
    }
    claimed: set[str] = set()
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
        core.require(
            "\n".join(block["text"] for block in text_blocks) == request["text"],
            "Fixture request text differs from source",
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
            "by": "public synthetic fixture adapter",
            "method": "Direct raw paragraph capture and exact comparison",
            "notes": (
                "Synthetic test source; no attorney approval or native rendering claim."
            ),
            "unresolved": [],
        },
    )
    result = source.attach(draft, census)
    result["legacy_review_sha256"] = core.digest(review)
    return result
