#!/usr/bin/env python3
"""Validate source-routing metadata. Does not authenticate, fetch, or confer access."""

import argparse
import datetime as dt
import json
from pathlib import Path


def route(capability=None, trusted=False, clock=None):
    fallback = {
        "mode": "public",
        "member_access": False,
        "reason": "No trusted authenticated LQ Brain connection.",
    }
    if not trusted or not isinstance(capability, dict):
        return fallback
    if capability.get("connected") is not True:
        return {**fallback, "reason": "Connection unavailable."}
    if capability.get("authenticated") is not True:
        return {**fallback, "reason": "Reconnect to authenticate member access."}
    try:
        expires = dt.datetime.fromisoformat(
            capability["expires_at"].replace("Z", "+00:00")
        )
        current = clock or dt.datetime.now(dt.UTC)
        if expires.tzinfo is None or expires <= current:
            return {**fallback, "reason": "Member access expired; reconnect."}
    except (ValueError, KeyError, TypeError, AttributeError):
        return {**fallback, "reason": "Member access expiry could not be verified."}
    scopes = capability.get("scopes", [])
    policy = capability.get("citation_policy")
    if (
        not isinstance(scopes, list)
        or "member:read" not in scopes
        or policy not in {"link_only", "paraphrase", "quote"}
    ):
        return {
            **fallback,
            "reason": "Required read scope or citation policy is missing.",
        }
    return {
        "mode": "member",
        "member_access": True,
        "citation_policy": policy,
        "reason": "Trusted metadata permits routing; service must still "
        "enforce access on each fetch.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capabilities", type=Path)
    parser.add_argument("--trusted-host-response", action="store_true")
    args = parser.parse_args()
    try:
        data = json.loads(args.capabilities.read_text()) if args.capabilities else None
        result = route(data, args.trusted_host_response)
    except (OSError, ValueError):
        result = route()
    print(json.dumps(result))


if __name__ == "__main__":
    main()
