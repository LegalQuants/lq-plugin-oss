# Capability Routing

Use the strongest available path and record the selected profile in the run output. This adapts `/definition-check`'s [capability-routing.md](../../definition-check/references/capability-routing.md) profile table for a two-document skill: `/conform` inherently needs two documents and both of their current ledgers, not one document, so a profile determination is made independently for the source side and the core side, and the run's effective profile is the lower of the two.

## Default selection direction

Build from deterministic foundations upward, but select runtime capabilities top-down. Attempt the fullest safe, available, already-authorized local workflow by default, including agentic mapping and HTML rendering. Degrade explicitly when a capability is absent or restricted. Do not silently leave available local parity features unused.

`C5_APPROVED_INTEGRATIONS` is attempted only when the relevant connector, network, DMS, or hosted-service data boundary is already authorized and appropriate to the lawyer's request. Top-down selection does not grant new permissions or authorize remote document processing.

## Profile table

| Profile | Runtime | Behavior |
|---|---|---|
| `C0_INSTRUCTION_ONLY` | Instructions and conversation only | `/conform` cannot run: it requires the packaged preflight to recompute and compare document hashes against ledger records, which needs local file access. Explain that a definition check and a conform both need local file access and ask the lawyer to run them in an environment that has it. |
| `C1_HOST_TEXT` | Complete host-extracted text for both documents, no executable runtime | Still cannot run the packaged preflight or hash comparison. State that `/conform` requires local command execution and cannot verify ledger freshness from pasted text alone. |
| `C2_LOCAL_COMMAND_NO_PYTHON` | Sandboxed commands, Python absent/restricted | Cannot run the packaged preflight or mapping engine. Stop; do not attempt a Python-free reimplementation of hash comparison or ledger validation. |
| `C3_PYTHON_STDLIB` | Python 3.12+ standard library plus workspace access | Run `conform_preflight.py` and, on success, the deterministic mapping engine with network off and no third-party dependencies. This is the minimum profile `/conform` can actually complete a run in. |
| `C4_FULL_LOCAL` | Approved local runtime, subagents/model workers, and artifact writes | Add the full agentic mapping path from `references/agentic-mapping-protocol.md`, `conform.html` rendering, and the clean-text deliverable. |
| `C5_APPROVED_INTEGRATIONS` | Explicitly authorized network/connectors/MCP/DMS | Add only the selected integration-backed features (for example, retrieving a source ledger from an authorized document store) and record remote processing. |

## Two-document profile determination

1. Determine the effective profile for the source document and its ledger independently of the core document and its ledger.
2. Determine the effective profile for the core document and its ledger the same way.
3. The run's effective `capability_profile` is the lower (weaker) of the two. A fully local core document paired with a source document only available as pasted text still caps the run at `C1_HOST_TEXT`, because the mapping and hash-comparison work is identical for both documents.
4. Record which document, if either, constrained the profile, so the lawyer understands why (for example: "I can verify the core document locally, but I only have pasted text for the precedent, so I can't confirm its ledger is current against the actual file").

## Required statuses

Same enumeration as `/definition-check`: `completed`, `completed_reduced_assurance`, `not_run_missing_capability`, `not_run_policy_restricted`, `not_run_unsupported_input`, `partial_input`, `insufficient_evidence`, `failed`.

## Invariants

- Hooks never alter the core correctness class.
- Python is optional to have installed generally, but `/conform` cannot complete a run below `C3_PYTHON_STDLIB`; unlike `/definition-check`, there is no reduced-assurance model-only path for the preflight itself, because the preflight's job is exactly the hash and schema comparison a model cannot reliably perform without executing code.
- Core mapping work never requires network access.
- Both source documents and the core document remain read-only.
- List parity-critical methods that did not run, per document.
- If original bytes are unavailable for a document, that document's contribution to `source_document.sha256` / `core_document.sha256` is `null`, and the preflight fails closed with `missing_ledger` or `hash_mismatch` rather than proceeding with an unverifiable identity.
