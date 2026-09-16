# Deterministic Rule Catalog

| Rule ID | Finding | Initial implementation |
|---|---|---|
| `DEF-001` | Used but not defined | A semantically confirmed contractual label has no local definition. A rejected single-word noun is also retained when the source uses it with unexplained mid-sentence capitalization and uses the same word lowercase elsewhere; sentence starts, list starts, headings, and titles remain excluded. `possible_inherited_definition` preserves a source-backed outside-document qualifier without treating the term as defined. |
| `DEF-002` | Defined but unused | Definition has no usage outside its own defining span. |
| `DEF-003` | Duplicate definition | One normalized term has more than one definition location. Exact duplicate text remains visible but lower priority. |
| `DEF-004` | Inconsistent capitalization or variant | A defined term appears in a non-canonical case/spacing form that is not an allowed alias. |
| `DEF-005` | Used before definition | A usage precedes its first definition in document order. |
| `DEF-006` | Unresolved definition reference | A complete scoped reference review determines that a definition delegates meaning to an intended internal target that cannot be resolved in the supplied scope. |
| `DEF-007` | Referenced document not checked | A specifically identified outside document was not supplied for this check. Informational only; it is not an undefined term. |

## Rule behavior

- Compute canonical facts once; do not emit duplicate findings for the same fact.
- Findings are deterministic observations, not legal conclusions.
- Stable IDs include rule ID, source identity, normalized term, and primary evidence location.
- Common-term and entity-name suppression must be configurable and visible.
- Unsupported structures cause coverage limitations, not passes.
- DEF-006 is not emitted by raw deterministic rule execution. It is emitted only for a `broken` reference adjudication after exact queue reconciliation. `resolved` and `out_of_scope` produce no finding; external and omitted companion references must be `out_of_scope`.
- An incomplete reference queue fails closed: no DEF-006 conclusion and no lawyer-facing dashboard.
