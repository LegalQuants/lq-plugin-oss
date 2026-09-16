"""Deterministic, bounded discovery-seed generation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .models import Block, Location, SourceDocument, stable_id


@dataclass(frozen=True)
class SeedFragment:
    """A source fragment with offsets that refer to its original block."""

    text: str
    location: Location

    def to_dict(self) -> dict[str, Any]:
        return {"text": self.text, "location": self.location.__dict__.copy()}


@dataclass(frozen=True)
class DiscoverySeed:
    id: str
    document_id: str
    order: int
    start: int
    end: int
    fragments: tuple[SeedFragment, ...]
    outline: tuple[dict[str, Any], ...]
    max_characters: int
    overlap: int
    outline_truncated: bool
    outline_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "document_id": self.document_id,
            "order": self.order,
            "start": self.start,
            "end": self.end,
            "text": "\n\n".join(fragment.text for fragment in self.fragments),
            "fragments": [fragment.to_dict() for fragment in self.fragments],
            "outline": [dict(item) for item in self.outline],
            "outline_truncated": self.outline_truncated,
            "outline_count": self.outline_count,
            "max_characters": self.max_characters,
            "overlap": self.overlap,
        }


def _heading(block: Block) -> bool:
    text = block.text.strip()
    if block.kind == "heading":
        return True
    if re.match(
        r"^(?:(?:article|section)\s+(?:[ivxlcdm]+|\d+(?:\.\d+)*)|\d+(?:\.\d+)*)\b",
        text,
        re.I,
    ):
        return True
    letters = "".join(char for char in text if char.isalpha())
    return bool(
        letters
        and len(text) <= 100
        and len(text.split()) <= 14
        and letters == letters.upper()
    )


def _outline(
    source: SourceDocument, max_items: int, max_characters: int
) -> tuple[tuple[dict[str, Any], ...], bool, int]:
    all_headings = tuple(
        {
            "text": block.text.strip()[:160],
            "location": block.location(0, len(block.text)).__dict__.copy(),
        }
        for block in sorted(source.blocks, key=lambda item: item.order)
        if _heading(block)
    )
    selected: list[dict[str, Any]] = []
    used = 0
    for item in all_headings:
        item_size = len(item["text"])
        if len(selected) >= max_items or used + item_size > max_characters:
            break
        selected.append(item)
        used += item_size
    return tuple(selected), len(selected) < len(all_headings), len(all_headings)


def generate_discovery_seeds(
    source: SourceDocument,
    *,
    max_characters: int = 4000,
    overlap: int = 300,
    max_outline_items: int = 32,
    max_outline_characters: int = 4000,
) -> list[dict[str, Any]]:
    """Return stable JSON-ready, overlapping bounded regions for discovery.

    Blocks are windowed as source text and rendered with neutral separators
    between fragments, then mapped back to exact source-block locations.
    """
    if max_characters < 1:
        raise ValueError("max_characters must be positive")
    if overlap < 0 or overlap >= max_characters:
        raise ValueError("overlap must be non-negative and less than max_characters")
    if max_outline_items < 1 or max_outline_characters < 1:
        raise ValueError("outline limits must be positive")

    blocks = tuple(
        sorted(
            (block for block in source.blocks if block.text),
            key=lambda item: item.order,
        )
    )
    total = sum(len(block.text) for block in blocks)
    if not total:
        return []

    ranges: list[tuple[Block, int, int]] = []
    cursor = 0
    for block in blocks:
        ranges.append((block, cursor, cursor + len(block.text)))
        cursor += len(block.text)

    seeds: list[dict[str, Any]] = []
    start = 0
    order = 0
    outline, outline_truncated, outline_count = _outline(
        source, max_outline_items, max_outline_characters
    )
    while start < total:
        end = min(total, start + max_characters)
        # Separators are deliberately rendered between fragments. Shrink the
        # content window until the readable rendering still fits the budget.
        while True:
            fragments = []
            for block, block_start, block_end in ranges:
                left, right = max(start, block_start), min(end, block_end)
                if left >= right:
                    continue
                local_start, local_end = left - block_start, right - block_start
                fragments.append(
                    SeedFragment(
                        block.text[local_start:local_end],
                        block.location(local_start, local_end),
                    )
                )
            rendered = "\n\n".join(fragment.text for fragment in fragments)
            if len(rendered) <= max_characters or end <= start + 1:
                break
            end -= 1
        seed = DiscoverySeed(
            id=stable_id(
                "seed", source.document_id, start, end, max_characters, overlap
            ),
            document_id=source.document_id,
            order=order,
            start=start,
            end=end,
            fragments=tuple(fragments),
            outline=outline,
            max_characters=max_characters,
            overlap=overlap,
            outline_truncated=outline_truncated,
            outline_count=outline_count,
        )
        seeds.append(seed.to_dict())
        if end == total:
            break
        start = max(start + 1, end - overlap)
        order += 1
    return seeds
