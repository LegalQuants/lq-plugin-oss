# Capability Routing

Use the strongest available path and record the selected profile in the run output.

## Default selection direction

Build the implementation from deterministic foundations upward, but select runtime capabilities from the top downward. Attempt the fullest safe, available, and already-authorized local workflow by default, including agentic review, document search, and artifact rendering. Degrade explicitly when a capability is absent or restricted. Do not silently leave available local parity features unused.

`C5_APPROVED_INTEGRATIONS` is attempted only when the relevant connector, network, DMS, or hosted-service data boundary is already authorized and appropriate to the user's request. Top-down selection does not grant new permissions or authorize remote document processing.

| Profile | Runtime | Behavior |
|---|---|---|
| `C0_INSTRUCTION_ONLY` | Instructions and conversation only | Analyze only content actually exposed by the host. Request pasted/exported text if the DOCX body is inaccessible. Never claim deterministic parity. |
| `C1_HOST_TEXT` | Complete host-extracted text, no executable runtime | Perform reduced-assurance model review. State structural, exact-location, tracked-change, and non-body omissions. |
| `C2_LOCAL_COMMAND_NO_PYTHON` | Sandboxed commands, Python absent/restricted | Use an approved packaged alternative only if present. Otherwise fall back to host text or stop the deterministic path without installing anything. |
| `C3_PYTHON_STDLIB` | Python 3.12+ standard library plus workspace access | Run the packaged DOCX checker with network off and no third-party dependencies. Older Python launchers fail before checker imports and route to a lower profile. |
| `C4_FULL_LOCAL` | Approved local runtime and artifact writes | Add local reports/rendering while preserving the source. |
| `C5_APPROVED_INTEGRATIONS` | Explicitly authorized network/connectors/MCP/DMS | Add only the selected integration-backed features and record remote processing. |

## Required statuses

- `completed`
- `completed_reduced_assurance`
- `not_run_missing_capability`
- `not_run_policy_restricted`
- `not_run_unsupported_input`
- `partial_input`
- `insufficient_evidence`
- `failed`

## Invariants

- Hooks never alter the core correctness class.
- Python is optional; never install it or packages during ordinary use. The packaged Python path requires version 3.12 or newer.
- Core single-document checking never requires network access.
- The source remains read-only.
- List parity-critical methods that did not run.
- If original bytes are unavailable, `source_hash` is `null`.

The product rationale and validation details are maintained separately from this distributed skill.
