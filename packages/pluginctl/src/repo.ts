import { existsSync } from "node:fs";
import { dirname, join } from "node:path";

export const RELEASE_FILE = "plugin.release.yaml";

export function findRepoRoot(start = process.cwd()) {
  let dir = start;

  while (true) {
    if (existsSync(join(dir, RELEASE_FILE))) {
      return dir;
    }

    const parent = dirname(dir);

    if (parent === dir) {
      throw new Error(
        `Could not find ${RELEASE_FILE} from ${start}. Run pluginctl from the repo.`,
      );
    }

    dir = parent;
  }
}
