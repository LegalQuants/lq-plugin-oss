"""Parse-safe public-entry-point guard for Conform."""

import json
import sys

MINIMUM_PYTHON = (3, 12)


def require_supported_python():
    """Exit cleanly before importing modules that require modern syntax."""

    if sys.version_info >= MINIMUM_PYTHON:
        return
    found = ".".join(str(part) for part in sys.version_info[:3])
    required = ".".join(str(part) for part in MINIMUM_PYTHON)
    print(
        json.dumps(
            {
                "status": "failed",
                "error": (
                    "Conform requires Python "
                    + required
                    + " or newer; this launcher is Python "
                    + found
                    + ". Select a newer installed Python runtime."
                ),
            },
            sort_keys=True,
        ),
        file=sys.stderr,
    )
    raise SystemExit(2)
