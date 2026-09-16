import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { chromium } from "@playwright/test";

const repo = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const out = mkdtempSync(join(tmpdir(), "legaldesign-first-paint-"));
const fixture = join(out, "composed.html");
const build = spawnSync(
  process.env.LEGALDESIGN_PYTHON || "python3",
  [
    join(repo, "skills/core/legaldesign/scripts/scaffold.py"),
    "compose",
    "--plan",
    join(
      repo,
      "packages/legaldesign/fixtures/case-06-novel-composition/plan.json",
    ),
    "--spec-output",
    join(out, "composed.spec.json"),
    "--output",
    fixture,
    "--artifact-id",
    "first-paint",
  ],
  { encoding: "utf8", cwd: repo },
);
assert.equal(build.status, 0, build.stderr + build.stdout);
const runtime = join(repo, "packages/legaldesign/runtime");
const block = `<!-- legaldesign:runtime --><style id="ld-tokens">${readFileSync(join(runtime, "tokens.css"), "utf8")}</style><script id="ld-components">${readFileSync(join(runtime, "components.js"), "utf8")}</script><script id="ld-runtime">${readFileSync(join(runtime, "runtime.js"), "utf8")}</script><!-- /legaldesign:runtime -->`;
const source = readFileSync(fixture, "utf8").replace(
  /<!-- legaldesign:runtime -->[\s\S]*?<!-- \/legaldesign:runtime -->/,
  () => block,
);
const executablePath = [
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  chromium.executablePath(),
].find(existsSync);
const browser = await chromium.launch({ executablePath, headless: true });
let checks = 0;

async function assertStablePaint(context, path, label) {
  const page = await context.newPage();
  await page.goto(pathToFileURL(path).href, { waitUntil: "load" });
  await page.waitForFunction(
    () => document.documentElement.dataset.legaldesignReady === "true",
  );
  // Capture pixels BEFORE any pointer, fitting API, theme switch, or label
  // measurement. SVG getBBox reported correct geometry even in the broken v20
  // renderer while the actual glyphs were painted with the old transform.
  const before = await page.screenshot({
    path: join(out, label + "-cold.png"),
  });
  const diagram = page.locator(".ld-diagram:visible").first();
  const box = await diagram.boundingBox();
  assert(box, label + ": missing visible diagram");
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.move(2, 2);
  const after = await page.screenshot({
    path: join(out, label + "-hovered.png"),
  });
  const changed = before.equals(after)
    ? 0
    : await page.evaluate(
        async (encoded) => {
          const images = await Promise.all(
            encoded.map(
              (value) =>
                new Promise((resolve, reject) => {
                  const image = new Image();
                  image.onload = () => resolve(image);
                  image.onerror = reject;
                  image.src = "data:image/png;base64," + value;
                }),
            ),
          );
          const pixels = images.map((image) => {
            const canvas = document.createElement("canvas");
            canvas.width = image.width;
            canvas.height = image.height;
            const context = canvas.getContext("2d");
            context.drawImage(image, 0, 0);
            return context.getImageData(0, 0, canvas.width, canvas.height).data;
          });
          let changed = 0;
          for (let i = 0; i < pixels[0].length; i += 4) {
            if (
              Math.max(
                ...[0, 1, 2].map((channel) =>
                  Math.abs(pixels[0][i + channel] - pixels[1][i + channel]),
                ),
              ) > 32
            )
              changed++;
          }
          return changed;
        },
        [before.toString("base64"), after.toString("base64")],
      );
  // Tolerate a few antialiasing pixels, not displaced glyphs. The reproduced
  // stale-transform failure moves whole labels and changes thousands of pixels.
  assert(
    changed <= 32,
    `${label}: ${changed} changed paint pixels; inspect evidence PNGs`,
  );
  checks++;
  console.log("PASS: " + label);
  return page;
}

try {
  for (const [width, height, dpr] of [
    [1280, 800, 1],
    [1280, 800, 2],
    [1440, 900, 1],
    [1306, 1005, 2],
    [390, 844, 2],
  ]) {
    const context = await browser.newContext({
      viewport: { width, height },
      deviceScaleFactor: dpr,
    });
    for (const theme of ["light", "dark"]) {
      for (const approach of ["a", "b"]) {
        const label = `${width}-${height}-${dpr}-${theme}-${approach}`;
        const path = join(out, label + ".html");
        const html = source.replace(
          /(<script id="legaldesign-state" type="application\/json">)([\s\S]*?)(<\/script>)/,
          (_, open, json, close) => {
            const state = JSON.parse(json);
            state.review.theme = theme;
            state.review.approach = approach;
            return (
              open + JSON.stringify(state).replace(/</g, "\\u003c") + close
            );
          },
        );
        writeFileSync(path, html);
        const page = await assertStablePaint(context, path, label);
        if (width === 1280 && dpr === 2) {
          for (const [kind, operation] of [
            ["client", "exportHTML"],
            ["template", "exportTemplate"],
          ]) {
            const exported = await page.evaluate(
              (operation) => LegalDesign[operation](false),
              operation,
            );
            const exportPath = join(out, label + "-" + kind + ".html");
            writeFileSync(exportPath, exported);
            const reopened = await assertStablePaint(
              context,
              exportPath,
              label + "-" + kind,
            );
            await reopened.close();
          }
        }
        await page.close();
      }
    }
    await context.close();
  }
  console.log(
    `PASS: ${checks} cold/hover raster pairs (Retina, phone, A/B, themes, reopened exports). Evidence: ${out}`,
  );
} finally {
  await browser.close();
}
