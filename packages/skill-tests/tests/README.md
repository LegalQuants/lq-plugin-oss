# Tests

Put cross-skill integration tests under the directory for the skill they exercise, using the authored skill name: `tests/<skill-name>/`.

Repository-wide policy and build-configuration tests belong in `tests/repository/`. Tests owned by a package stay beside that boundary, such as `packages/pluginctl/tests/`; maintainer evaluation campaigns are kept outside this public test package.
