#!/usr/bin/env python3
"""Submit a complete worker JSON file through validation and immutable publication."""

import argparse
import json
from pathlib import Path
from _runtime_gate import require_supported_python

require_supported_python()

from definition_check.response_publication import publish, marked_root


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue-dir", type=Path, required=True)
    parser.add_argument(
        "--stage",
        choices=["discovery", "semantic", "reference", "occurrence"],
        required=True,
    )
    parser.add_argument("--packet", type=int, required=True)
    parser.add_argument("--attempt", type=int, required=True)
    parser.add_argument("--identity", required=True)
    parser.add_argument("--input", type=Path, required=True)
    args = parser.parse_args()
    if marked_root(args.input) != marked_root(args.queue_dir):
        parser.error("draft must be inside the queue workspace")
    result = publish(
        args.queue_dir,
        args.stage,
        args.packet,
        args.attempt,
        args.identity,
        args.input.read_bytes(),
    )
    print(json.dumps(result))
    if result["error"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
