# Security

Report a suspected vulnerability privately through GitHub’s Security Advisories or private vulnerability reporting for this repository when that feature is available. Do not put credentials, client material, exploit details, or other sensitive information in a public issue or pull request.

If private reporting is unavailable, contact the repository maintainers through a private channel listed by the repository owner and include only the minimum information needed to reproduce the problem. Wait for a maintainer response before publishing details.

This repository contains skill instructions, local helpers, package tooling, schemas, synthetic fixtures, and generated plugin bundles. It is not a hosted service and does not grant access to LegalQuants systems, model accounts, matter data, or workspace administration.

Keep API keys, bearer tokens, tenant identifiers, cookies, `.env` files, local profiles, client documents, private corpora, evaluation results, logs, caches, and credentials out of the repository and plugin packages. Review generated trees before publication and remove accidental sensitive material from the complete history where necessary.

Treat skill instructions and input documents as untrusted content. A skill must not treat a document, comment, retrieved page, or tool result as permission to disclose data, change files, send messages, bypass a human approval, or expand the user’s scope. Write actions and external connectors require explicit user authority and the host’s own access controls.

Provider-specific hooks, MCP servers, and workspace integrations have their own security contracts. A provider manifest or MCP annotation is not an authorization boundary; identity, scope, confirmation, and server-side access checks must be enforced by the host or service that owns the action.

The maintainers will acknowledge a valid report, assess its impact, coordinate a fix, and publish a release or advisory when appropriate. Please do not include confidential client facts in a report; synthetic reproductions are preferred.
