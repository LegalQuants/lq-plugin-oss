#!/usr/bin/env sh
# Type-check all authored skills and public packages, including their tests,
# hook scripts, and build tools. Extra search paths make skill-script packages resolve the
# same way packaged entry points do.
set -eu

root=${TYPECHECK_ROOT:-$(CDPATH= cd -- "$(dirname "$0")/../../.." && pwd)}
cd "$root"

set -- skills packages

# Hyphenated test directories contain sibling fixture modules.
for tests in packages/skill-tests/tests/*; do
  [ -d "$tests" ] || continue
  set -- "$@" --extra-search-path "$tests"
done

# Skill packages keep their importable Python modules beneath scripts/.
# Pass each discovered scripts directory to ty so relative imports resolve
# exactly as they do when the packaged entry point runs from that directory.
for scripts in skills/*/*/scripts; do
  [ -d "$scripts" ] || continue
  set -- "$@" --extra-search-path "$scripts"
done

# Shared runtimes execute from their own directory and may intentionally use
# bare sibling imports. Give the type checker the same lookup path.
for shared in skills/*/*/scripts/shared; do
  [ -d "$shared" ] || continue
  set -- "$@" --extra-search-path "$shared"
done

if [ "${TYPECHECK_PY_PRINT:-}" = "1" ]; then
  printf '%s\n' "$@"
  exit 0
fi

exec uv run ty check "$@"
