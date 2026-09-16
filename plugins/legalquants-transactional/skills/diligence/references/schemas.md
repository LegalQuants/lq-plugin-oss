# /diligence data contracts

Exact shapes for every artifact the scripts exchange. Scripts validate on read and write. Deterministic artifacts carry no timestamps, no absolute paths, and no machine names; run metadata lives in the run log, never in these files. Keys sort alphabetically on serialization (`json.dumps(..., sort_keys=True, indent=2)`), documents sort by `id`.

## manifest.json (build_manifest.py)

```json
{
  "root_label": "<basename of the data-room folder>",
  "documents": [
    {
      "id": "sha256:9f3a1c04b2d7",
      "path": "3.2 Supplier Agreements/acme-msa.pdf",
      "bytes": 184223,
      "ext": "pdf",
      "pages": 42,
      "readability": "native",
      "text_yield": 0.97,
      "review_role": "substantive"
    }
  ],
  "counts": {
    "files": 15,
    "native": 12,
    "scanned": 2,
    "encrypted": 0,
    "corrupt": 1
  }
}
```

- `id`: `sha256:` plus the first 12 hex of the file's SHA-256. The stable doc ID everywhere.
- `path`: relative to root, forward slashes.
- `pages`: integer for paginated formats, null otherwise.
- `readability`: `native` (text_yield >= 0.5), `scanned` (extractable pages but yield < 0.5), `encrypted`, `corrupt`.
- `review_role`: optional `substantive | runner-control`, defaulting to `substantive`. A request list, schedule, or instruction file is marked `runner-control` only after the lawyer confirms it governs the review rather than being an agreement to review. It stays in the file census and source table but is excluded from agreement families, sampling, and the issue/unit matrix.
- Invariant: `counts.files == len(documents)` and equals the walk count; the script exits nonzero otherwise.

## metadata/<id>.json (model workers; prep stubs from extract_metadata_prep.py)

```json
{
  "id": "sha256:9f3a1c04b2d7",
  "doc_type": "amendment",
  "title": "Amendment No. 2 to Master Services Agreement",
  "parties": ["Acme Corp", "Bolt Industries LLC"],
  "dated": "2023-01-05",
  "references": [
    {
      "text": "Master Services Agreement dated January 5, 2023 between Acme Corp and Bolt Industries",
      "quote": "this Amendment No. 2 to the Master Services Agreement dated January 5, 2023",
      "source": "regex"
    }
  ],
  "status": "complete"
}
```

- `source`: `regex` or `model`. Model-sourced fields must carry `quote`; verify_quotes.py parks the file (`status: "quote-unverified"`) when a quote fails to match.
- `status`: `complete`, `metadata-incomplete`, `quote-unverified`. Parked files stay in the manifest counts.
- `dated`: ISO date or null.
- Runner-control files do not receive metadata stubs and never enter `worklist.json`.

## candidates.json (block_candidates.py)

Candidate blocks contain substantive document IDs only; runner-control files remain in the manifest but do not enter blocks or pairs.

```json
{
  "blocks": [
    {
      "block_id": "b001",
      "basis": ["party:acme corp", "title:master services agreement"],
      "members": ["sha256:9f3a1c04b2d7", "sha256:aa10b2c9d001"]
    }
  ],
  "pairs": [
    {"a": "sha256:9f3a1c04b2d7", "b": "sha256:aa10b2c9d001", "block": "b001"}
  ]
}
```

## families.json (build_families.py)

```json
{
  "families": [
    {
      "family_id": "sha256:aa10b2c9d001",
      "members": [
        {"id": "sha256:aa10b2c9d001", "role": "base", "order": 0},
        {"id": "sha256:9f3a1c04b2d7", "role": "amendment", "order": 1}
      ],
      "edges": [
        {
          "src": "sha256:9f3a1c04b2d7",
          "dst": "sha256:aa10b2c9d001",
          "relation": "amends",
          "provenance": "rule",
          "quote": "this Amendment No. 2 to the Master Services Agreement dated January 5, 2023"
        }
      ]
    }
  ],
  "orphans": ["sha256:0c77d1e2f3a4"]
}
```

- `relation`: `amends | sow-under | schedule-of | guarantees | supersedes | duplicate-of`.
- `provenance`: `rule` (reference-string match, no model) or `model` (quote-verified before entry).
- `family_id`: the base agreement's doc ID; families sort by `family_id`, members by `order` (base first, then by `dated`, then id).
- `families` and `orphans` account for substantive documents only. Runner-control files are accounted for by the manifest and crosswalk source table instead.

## gap-report.json (reconcile_index.py + build_manifest.py + build_families.py contributions)

```json
{
  "entries": [
    {
      "type": "index-missing",
      "detail": "Index row 3.2.4 'Amendment No 3' has no matching file",
      "evidence": "index.csv row 17"
    },
    {"type": "referenced-absent", "detail": "...", "evidence": "<quote>"},
    {"type": "unreadable", "detail": "...", "evidence": "readability=corrupt"},
    {"type": "duplicate", "detail": "...", "evidence": "same sha256 as sha256:aa10b2c9d001"}
  ]
}
```

## Gate 1 surface (render_gate1.py)

Input: manifest.json, metadata/, families.json, gap-report.json, and framework-readback.json. The renderer requires metadata coverage for every substantive unit and uses complete, quote-verified metadata for lawyer-facing titles and dates without changing the hash-bound manifest. Output: one self-contained `gate1.html`, no external requests, readable in light and dark, model-proposed edges rendered as PROPOSED with their quotes, rule edges rendered as grouped. The lawyer's confirmation is recorded by the orchestrator writing `families.confirmed.json` (same schema plus `"confirmed": true`); downstream stages read only the confirmed file.
