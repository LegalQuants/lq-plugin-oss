"""Recall-oriented lexical candidate discovery.

This module deliberately does not parse definitions. Legal drafting permits too
many syntactic forms for a deterministic antecedent/body parser to be reliable.
The scanner only preserves quoted labels as semantic-review candidates. A model
must decide whether a candidate is a defined term and identify its exact source
span; reconciliation validates that span before creating a Definition record.
"""

from __future__ import annotations

import re
from .models import LexicalCandidateObservation, SourceDocument, stable_id
from .term_identity import term_key

QUOTED_LABEL_DETECTOR = "quoted_label_regex"
QUOTED_LABEL_DETECTOR_VERSION = "1"

_SPACE = re.compile(r"\s+", re.UNICODE)
_QUOTED_LABEL = re.compile(
    r"(?<!\w)(?:"
    r'"(?P<straight>[^\"\r\n]{1,120})"'
    r"|\u201c(?P<curly>[^\u201c\u201d\r\n]{1,120})\u201d"
    r"|\u00ab(?P<guillemet>[^\u00ab\u00bb\r\n]{1,120})\u00bb"
    r")"
)
QUOTED_LABEL_FORMATS = (
    '"Definition"',
    "\u201cDefinition\u201d",
    "\u00abDefinition\u00bb",
    '("Definition")',
    '("Definition 1", and collectively, "Definition 2")',
)
QUOTED_LABEL_EXCLUSIONS = (
    "(Definition)",
    "'Definition'",
    "\u2018Definition\u2019",
    "multiline quoted text",
    "quoted text containing no letters",
    "quoted labels longer than 120 characters",
)


def normalize_term(text: str) -> str:
    """Compatibility alias for the canonical internal term identity."""

    return term_key(text)


def _valid_label(value: str) -> bool:
    value = _SPACE.sub(" ", value).strip()
    return bool(value and any(character.isalpha() for character in value))


def extract_quoted_observations(
    source: SourceDocument,
) -> list[LexicalCandidateObservation]:
    """Return quoted-label observations without agent or judgment fields."""

    observations: list[LexicalCandidateObservation] = []
    seen: set[tuple[str, int, int]] = set()
    for block in sorted(source.blocks, key=lambda item: (item.order, item.id)):
        for match in _QUOTED_LABEL.finditer(block.text):
            group = next(
                name
                for name in ("straight", "curly", "guillemet")
                if match.group(name) is not None
            )
            term = match.group(group)
            start, end = match.span(group)
            key = (block.id, start, end)
            if key in seen or not _valid_label(term):
                continue
            seen.add(key)
            normalized = normalize_term(term)
            observation_id = stable_id(
                "lexical-observation",
                QUOTED_LABEL_DETECTOR,
                QUOTED_LABEL_DETECTOR_VERSION,
                source.document_id,
                block.id,
                str(start),
                str(end),
            )
            observations.append(
                LexicalCandidateObservation(
                    id=observation_id,
                    term=term,
                    normalized_term=normalized,
                    location=block.location(start, end),
                    detector=QUOTED_LABEL_DETECTOR,
                    detector_version=QUOTED_LABEL_DETECTOR_VERSION,
                    observation_type="quoted_label",
                )
            )
    return observations
