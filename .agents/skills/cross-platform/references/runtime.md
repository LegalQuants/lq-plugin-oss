# Runtime assumptions

Do not promise a scripted workflow, package installation, network access, or worker fan-out for a host until that capability has been observed on the current host. The presence of a command or a manifest proves only that a file exists.

For a hosted workspace, assume public internet access, package installation, elevated privileges, and handoff of a parent session’s model entitlement are unavailable unless the host documents and enables them. Use the host’s native document and worker capabilities when present, and keep a sequential path with the same output contract.

For local Codex or Claude Code work, test the current environment before relying on Python, Node, a scheduler, network access, or credentials. Do not infer support for another host from a local result. This repository documents the generated Codex and Claude Code adapters; other hosts require their own adapter and verification.

Local helpers should be standard-library first, use `pathlib`, emit UTF-8 JSONL or another documented stable format, send diagnostics to stderr, return stable exit codes, and avoid `sudo`. Always include a no-script fallback. Never require a package manager, shell-specific behavior, or an undocumented environment variable at skill invocation time.

When a script would invoke a model, licensed source, connector, or other paid service, require an explicit user or firm configuration choice and disclose the selected route. A failed canary or missing credential is an unavailable capability, not evidence that the workflow completed.
