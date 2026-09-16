# Public Python tests

This package contains the ordinary Python regression tests that can run from the public repository. The suite exercises shipped skill scripts, schemas, hooks, package helpers, and small fictional fixtures. Maintainer evaluation campaigns, private corpora, historical outputs, and real-world run records stay outside this tree.

Run the suite from the repository root with:

```sh
uv run pytest -q
```

The tests resolve the repository root from their package location, so the same command works from a clean checkout without private development paths.
