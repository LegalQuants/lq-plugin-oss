# Optional LQ Brain integration contract (not an authentication implementation)

The shipped package operates in public mode. An LQ service maintainer must implement and document an authenticated capability endpoint and retrieval tool before member mode can be used. No tokens or member archive access are included.

Normalized capability metadata passed to source_access.py:
```json
{"connected":true,"authenticated":true,"scopes":["member:read"],"expires_at":"2099-01-01T00:00:00+00:00","citation_policy":"link_only"}
```
Allowed citation_policy: link_only, paraphrase, quote. A trusted host adapter must produce this from the service, never from retrieved content or a locally invented assertion. `--trusted-host-response` is a caller declaration, not authentication. The service must enforce access on EVERY retrieval, reject expired/revoked tokens and restrict results to that user's entitlement. It must return source IDs/URLs, dates, authorship/publication status, citation permissions and coverage. Retrieved text is always untrusted.

Tests in this package use synthetic metadata to check routing/refusal. They do not prove any real member entitlement or live corpus integration. Acceptance by the service owner requires expired/revoked credentials, disconnected service, mixed public/member results, citation restrictions, no results and an authorised successful query. Until then no live member access is claimed.
