"""Self-contained HTML redline and independent clean-text rendering.

Both renderers consume the same ordered `Replacement` sequence but build their
output through separate code paths: `render_clean_text` is not a stripped-tags
derivative of `render_redline_html`. Neither renderer references any remote
font, script, stylesheet, image, or analytics resource; the HTML is valid
standalone markup with no external resource references, matching the
constraint already governing definition-check's dashboard.
"""

from __future__ import annotations

import html
from dataclasses import dataclass

from .redline_theme import REDLINE_STYLE


class RedlineError(ValueError):
    """Raised when a replacement set cannot be safely rendered."""


@dataclass(frozen=True)
class Replacement:
    """One proposed edit to `source_text`, at a fixed, validated offset span."""

    start: int
    end: int
    original_text: str
    proposed_text: str
    mapping_id: str
    mapping_type: str

    def __post_init__(self) -> None:
        if self.start < 0 or self.end < self.start:
            raise RedlineError(f"replacement {self.mapping_id} has invalid offsets")
        if not self.mapping_id.strip():
            raise RedlineError("replacement mapping_id must not be empty")


def _validate_replacements(
    source_text: str, replacements: tuple[Replacement, ...]
) -> tuple[Replacement, ...]:
    ordered = tuple(sorted(replacements, key=lambda item: (item.start, item.end)))
    previous_end = 0
    for replacement in ordered:
        if replacement.start < previous_end:
            raise RedlineError(
                f"replacement {replacement.mapping_id} overlaps a preceding replacement"
            )
        if replacement.end > len(source_text):
            raise RedlineError(
                f"replacement {replacement.mapping_id} extends past the end of source_text"
            )
        actual = source_text[replacement.start : replacement.end]
        if actual != replacement.original_text:
            raise RedlineError(
                f"replacement {replacement.mapping_id} original_text does not match "
                f"source_text[{replacement.start}:{replacement.end}]"
            )
        previous_end = replacement.end
    return ordered


def render_redline_html(
    source_text: str,
    replacements: tuple[Replacement, ...],
    *,
    heading: str = "Conform Redline",
    scope_note: str = (
        "Only the document body and tables were checked, matching the scope "
        "of each /definition-check review. Notes, footnotes, headers, "
        "comments, and tracked changes were excluded."
    ),
    mode_label: str = "Conform selected text",
) -> str:
    """Render one self-contained HTML page showing del/ins around each replacement."""

    ordered = _validate_replacements(source_text, replacements)
    pieces: list[str] = []
    cursor = 0
    for replacement in ordered:
        if replacement.start > cursor:
            pieces.append(html.escape(source_text[cursor : replacement.start]))
        pieces.append(f"<del>{html.escape(replacement.original_text)}</del>")
        if replacement.proposed_text:
            pieces.append(f"<ins>{html.escape(replacement.proposed_text)}</ins>")
        cursor = replacement.end
    if cursor < len(source_text):
        pieces.append(html.escape(source_text[cursor:]))
    clause_html = "".join(pieces) if pieces else html.escape(source_text)

    rows = "".join(
        "<tr>"
        f"<td>{html.escape(replacement.original_text)}</td>"
        f"<td>{html.escape(replacement.proposed_text) or '&mdash;'}</td>"
        f"<td>{html.escape(replacement.mapping_type)}</td>"
        "</tr>"
        for replacement in ordered
    )
    table_section = ""
    if rows:
        table_section = (
            "<h2>Proposed changes</h2>"
            "<table><thead><tr><th>Source</th><th>Proposed</th><th>Mapping</th></tr>"
            f"</thead><tbody>{rows}</tbody></table>"
        )

    return (
        "<!doctype html>\n"
        '<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{html.escape(heading)}</title>"
        f"<style>{REDLINE_STYLE}</style></head><body>"
        '<header><span class="mode-badge">'
        f"{html.escape(mode_label)}</span>"
        f"<h1>{html.escape(heading)}</h1>"
        f'<p class="scope-note">{html.escape(scope_note)}</p></header>'
        f'<main><div class="clause">{clause_html}</div>{table_section}</main>'
        "</body></html>"
    )


def render_clean_text(source_text: str, replacements: tuple[Replacement, ...]) -> str:
    """Return exact copy-pasteable prose with every replacement applied.

    Built independently from `render_redline_html`: this function walks the
    same validated replacement offsets but emits plain proposed text with no
    markup at all, rather than stripping tags from rendered HTML.
    """

    ordered = _validate_replacements(source_text, replacements)
    pieces: list[str] = []
    cursor = 0
    for replacement in ordered:
        if replacement.start > cursor:
            pieces.append(source_text[cursor : replacement.start])
        pieces.append(replacement.proposed_text)
        cursor = replacement.end
    if cursor < len(source_text):
        pieces.append(source_text[cursor:])
    return "".join(pieces)
