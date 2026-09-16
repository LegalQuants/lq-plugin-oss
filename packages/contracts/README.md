# Contracts

JSON Schema 2020-12 is the language-neutral API. Generate TypeScript and
Python types from these files when a skill freezes a contract.

Do not let the TypeScript server, a Python worker, a skill, and a
marketplace listing describe four different shapes.

`work-unit-result.schema.json` is the shared floor: `unitId` and a non-empty
`status` are required. Skills may add fields and define their own status
vocabulary. A skill-owned schema should use `allOf` with a `$ref` to this file,
then declare its extra properties.
Do not set `additionalProperties: false` on this base — that would reject
every extended result.
