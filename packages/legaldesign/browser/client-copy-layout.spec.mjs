import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { chromium } from "@playwright/test";

const repo = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const out = mkdtempSync(join(tmpdir(), "legaldesign-client-copy-"));
const source = join(out, "working.html");
const built = spawnSync(
  process.env.LEGALDESIGN_PYTHON || "python3",
  [
    "skills/core/legaldesign/scripts/scaffold.py",
    "compose",
    "--plan",
    "packages/legaldesign/fixtures/case-08-dense-diligence/plan.json",
    "--spec-output",
    join(out, "spec.json"),
    "--output",
    source,
    "--artifact-id",
    "client-copy-layout-regression",
  ],
  { cwd: repo, encoding: "utf8" },
);
assert.equal(built.status, 0, built.stdout + built.stderr);
let html = readFileSync(source, "utf8");
for (const [id, file, tag] of [
  ["ld-runtime", "runtime.js", "script"],
  ["ld-tokens", "tokens.css", "style"],
]) {
  const contents = readFileSync(
    join(repo, "packages/legaldesign/runtime", file),
    "utf8",
  );
  html = html.replace(
    new RegExp(`<${tag} id="${id}">[\\s\\S]*?</${tag}>`),
    () => `<${tag} id="${id}">${contents}</${tag}>`,
  );
}
writeFileSync(source, html);
const browser = await chromium.launch({
  headless: true,
  executablePath: [
    chromium.executablePath(),
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  ].find(existsSync),
});
try {
  for (const approach of ["a", "b"]) {
    const page = await browser.newPage({
      viewport: { width: 1440, height: 900 },
      deviceScaleFactor: 2,
    });
    await page.goto(pathToFileURL(source).href);
    await page.waitForFunction(
      () => document.documentElement.dataset.legaldesignReady === "true",
    );
    await page.locator(`[data-select-approach="${approach}"]`).click();
    assert(
      await page.evaluate(() => LegalDesign.checkPageFit().valid),
      "working page fits before export",
    );
    const margins = await page.evaluate(() => {
      const scope = document.querySelector(".ld-page-approach:not([hidden])");
      const paragraph = scope.querySelector("[data-variant-body] p");
      paragraph.style.color = "rgb(90, 50, 120)";
      paragraph.setAttribute("data-editable", "");
      paragraph.setAttribute("data-editor-x", "0");
      return [
        ...scope.querySelectorAll(
          "[data-variant-body] h2,[data-variant-body] p",
        ),
      ].map((node) => ({
        marginTop: getComputedStyle(node).marginTop,
        marginBottom: getComputedStyle(node).marginBottom,
      }));
    });
    const clientHTML = await page.evaluate(() => LegalDesign.exportHTML(false));
    const target = join(out, `${approach}-client.html`);
    writeFileSync(target, clientHTML);
    const client = await browser.newPage({
      viewport: { width: 1440, height: 900 },
      deviceScaleFactor: 2,
    });
    await client.goto(pathToFileURL(target).href);
    await client.waitForFunction(
      () => document.documentElement.dataset.legaldesignReady === "true",
    );
    await client.screenshot({ path: join(out, `${approach}-cold.png`) });
    const observed = await client.evaluate(() => {
      const scope = document.querySelector(".ld-page-approach:not([hidden])");
      return {
        fit: LegalDesign.checkPageFit({ allPages: true }),
        issues: LegalDesign.lastPageFitIssues,
        margins: [
          ...scope.querySelectorAll(
            "[data-variant-body] h2,[data-variant-body] p",
          ),
        ].map((node) => ({
          marginTop: getComputedStyle(node).marginTop,
          marginBottom: getComputedStyle(node).marginBottom,
        })),
        color: getComputedStyle(scope.querySelector("[data-variant-body] p"))
          .color,
        authoringAttributes: scope.querySelectorAll(
          "[data-editable],[data-editor-x]",
        ).length,
      };
    });
    assert(observed.fit.valid, JSON.stringify(observed.issues));
    assert.deepEqual(
      observed.margins,
      margins,
      "client keeps canonical copy spacing",
    );
    assert.equal(
      observed.color,
      "rgb(90, 50, 120)",
      "client preserves user-painted copy",
    );
    assert.equal(
      observed.authoringAttributes,
      0,
      "client boot does not restore authoring attributes from serialized edits",
    );
    await client.close();
    await page.close();
  }
  console.log(
    `PASS client copy spacing, cold page fit, and frozen user overrides; evidence ${out}`,
  );
} finally {
  await browser.close();
}
