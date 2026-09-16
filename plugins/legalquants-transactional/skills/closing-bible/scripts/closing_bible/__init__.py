"""closing-bible runtime: deterministic census, family grouping and reconciliation.

Standard library only, Python 3.12 or newer. Public entry point is
`../closing_bible.py`. Modules:

- `models`    — dataclasses mirroring `../../references/*.schema.json`, carrying the
                rules from `status-taxonomy.md` that must not move.
- `census`    — walk, hash, probe, duplicate groups → source-manifest.json.
- `families`  — group the manifest into document families → families.json.
- `reconcile` — validate inspection.json, match families to the expected set,
                write closing-index.json, selection-plan.json,
                execution-overview.json, closing-receipt.json, exceptions.md.
"""

from __future__ import annotations

from .models import SCHEMA_VERSION

__all__ = ["SCHEMA_VERSION"]
