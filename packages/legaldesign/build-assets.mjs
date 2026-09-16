#!/usr/bin/env node

import { createHash } from "node:crypto";
import { readdir, readFile, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = dirname(fileURLToPath(import.meta.url));
const runtimeRoot = join(root, "runtime");
const assetsRoot = join(
  root,
  "..",
  "..",
  "skills",
  "core",
  "legaldesign",
  "assets",
);
const start = "<!-- legaldesign:runtime -->";
const end = "<!-- /legaldesign:runtime -->";
const check = process.argv.includes("--check");
const catalogOpen = '<script id="library-components" type="application/json">';
const catalogClose = "</script>";

async function loadEsbuild() {
  try {
    return await import("esbuild");
  } catch (error) {
    throw new Error(
      "The LegalDesign asset builder requires the package's esbuild dependency; run pnpm install.",
      { cause: error },
    );
  }
}

const [tokens, components, runtime, catalog] = await Promise.all([
  readFile(join(runtimeRoot, "tokens.css"), "utf8"),
  readFile(join(runtimeRoot, "components.js"), "utf8"),
  readFile(join(runtimeRoot, "runtime.js"), "utf8"),
  readFile(join(assetsRoot, "..", "references", "components.json"), "utf8"),
]);
const compactCatalog = JSON.stringify(JSON.parse(catalog));
const { transform } = await loadEsbuild();
const clientRuntime = (
  await transform(runtime, {
    loader: "js",
    minify: true,
    target: "es2020",
    define: { LEGALDESIGN_CLIENT_BUILD: "true" },
    treeShaking: true,
  })
).code.trimEnd();
if (
  /showSaveFilePicker|createWritable|persistHTML|\.download\s*=/.test(
    clientRuntime,
  )
)
  throw new Error("Client runtime still contains file-writing code");
const clientPayload = `<script id="ld-client-runtime" type="application/json">${JSON.stringify(clientRuntime).replaceAll("<", "\\u003c")}</script>`;
const compactComponents = (
  await transform(components, {
    loader: "js",
    minify: true,
    target: "es2020",
  })
).code.trimEnd();
const compactTokens = (
  await transform(tokens, {
    loader: "css",
    minify: true,
    target: "es2020",
  })
).code.trimEnd();
const compactRuntime = (
  await transform(runtime, { loader: "js", minify: true, target: "es2020" })
).code.trimEnd();
function digest(value) {
  return createHash("sha256").update(value).digest("hex");
}
function runtimeBlock(
  componentSource,
  componentAttributes = "",
  tokenSource = tokens.trimEnd(),
  tokenAttributes = "",
  runtimeSource = runtime.trimEnd(),
  runtimeAttributes = "",
) {
  return `${start}\n<style id="ld-tokens"${tokenAttributes}>\n${tokenSource}\n</style>\n<script id="ld-components"${componentAttributes}>\n${componentSource}\n</script>\n<script id="ld-runtime"${runtimeAttributes}>\n${runtimeSource}\n</script>\n${end}`;
}
const built = runtimeBlock(components.trimEnd());
const compactLibraryBuilt = runtimeBlock(
  compactComponents,
  ` data-source-sha256="${digest(components)}" data-output-sha256="${digest(compactComponents)}"`,
  compactTokens,
  ` data-source-sha256="${digest(tokens.trimEnd())}" data-output-sha256="${digest(compactTokens)}"`,
  compactRuntime,
  ` data-source-sha256="${digest(runtime.trimEnd())}" data-output-sha256="${digest(compactRuntime)}"`,
);

const names = (await readdir(assetsRoot))
  .filter((name) => name.endsWith(".html"))
  .sort();
const drift = new Set();
for (const name of names) {
  const path = join(assetsRoot, name);
  let source = await readFile(path, "utf8");
  let changed = false;
  const payloadPattern =
    /<script id="ld-client-runtime" type="application\/json">[\s\S]*?<\/script>/;
  const existingPayload = source.match(payloadPattern)?.[0];
  if (existingPayload !== clientPayload) {
    if (check) drift.add(`${name} (reader runtime)`);
    else {
      source = existingPayload
        ? source.replace(payloadPattern, () => clientPayload)
        : source.replace("</head>", `${clientPayload}\n</head>`);
      changed = true;
    }
  }
  if (name === "library.html") {
    const from = source.indexOf(catalogOpen);
    const to = source.indexOf(catalogClose, from + catalogOpen.length);
    if (from < 0 || to < from)
      throw new Error("library.html: component catalog block is missing");
    const expected = `${catalogOpen}${compactCatalog}${catalogClose}`;
    const actual = source.slice(from, to + catalogClose.length);
    if (actual !== expected) {
      if (check) drift.add("library.html (component catalog)");
      else {
        source =
          source.slice(0, from) +
          expected +
          source.slice(to + catalogClose.length);
        changed = true;
      }
    }
  }
  const from = source.indexOf(start);
  const to = source.indexOf(end);
  if (from < 0 && to < 0) continue;
  if (from < 0 || to < from)
    throw new Error(`${name}: unmatched legaldesign runtime markers`);
  const actual = source.slice(from, to + end.length);
  const expectedRuntime = name === "library.html" ? compactLibraryBuilt : built;
  if (actual !== expectedRuntime) {
    if (check) drift.add(name);
    else {
      source =
        source.slice(0, from) + expectedRuntime + source.slice(to + end.length);
      changed = true;
    }
  }
  // Export trusts styles declared in head. Keep the complete shared block
  // there, including on composed shells whose original marker was in body.
  // Runtime boot already waits for DOMContentLoaded, so scripts remain safe.
  const runtimeFrom = source.indexOf(start);
  const runtimeTo = source.indexOf(end, runtimeFrom) + end.length;
  const headEnd = source.indexOf("</head>");
  if (headEnd < 0) throw new Error(`${name}: document head is missing`);
  if (runtimeFrom > headEnd) {
    if (check) drift.add(`${name} (runtime must be in head)`);
    else {
      const block = source.slice(runtimeFrom, runtimeTo);
      source =
        source.slice(0, runtimeFrom).replace(/[ \t]+$/, "") +
        source.slice(runtimeTo);
      source = source.replace("</head>", `${block}\n</head>`);
      changed = true;
    }
  }
  if (!check && changed) await writeFile(path, source);
}

if (drift.size) {
  console.error(`LegalDesign asset drift: ${[...drift].join(", ")}`);
  process.exitCode = 1;
} else {
  console.log(
    check
      ? "LegalDesign runtime blocks are current."
      : "LegalDesign runtime blocks rebuilt.",
  );
}
