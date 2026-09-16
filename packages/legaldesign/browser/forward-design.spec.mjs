import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { chromium } from "@playwright/test";

const repo = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const out = mkdtempSync(join(tmpdir(), "legaldesign-forward-"));
const html = join(out, "contract-transfer.html");
const build = spawnSync(
  process.env.LEGALDESIGN_PYTHON || "python3",
  [
    "skills/core/legaldesign/scripts/scaffold.py",
    "compose",
    "--plan",
    "packages/legaldesign/fixtures/case-07-forward-design/plan.json",
    "--spec-output",
    join(out, "plan.json"),
    "--output",
    html,
    "--artifact-id",
    "legaldesign-forward-contract-transfer",
  ],
  { cwd: repo, encoding: "utf8" },
);
assert.equal(build.status, 0, build.stdout + build.stderr);
const executablePath = [
  chromium.executablePath(),
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
].find(existsSync);
const browser = await chromium.launch({ headless: true, executablePath });
const results = [];
try {
  for (const [width, height] of [
    [1440, 900],
    [1280, 800],
    [430, 932],
    [390, 844],
  ]) {
    const page = await browser.newPage({ viewport: { width, height } });
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.goto(pathToFileURL(html).href);
    await page.waitForFunction(
      () => document.documentElement.dataset.legaldesignReady === "true",
    );
    for (const theme of ["light", "dark"]) {
      if ((await page.locator("html").getAttribute("data-theme")) !== theme)
        await page.locator("#theme-toggle").click();
      for (const approach of ["a", "b"]) {
        await page.locator(`[data-select-approach="${approach}"]`).click();
        await page.evaluate(
          () =>
            new Promise((resolve) =>
              requestAnimationFrame(() => requestAnimationFrame(resolve)),
            ),
        );
        const active = page.locator(
          `.ld-page-approach[data-approach="${approach}"]`,
        );
        const surface = await active.innerText();
        for (const fact of [
          "fictional example",
          "£18,000",
          "1 October",
          "uncertain",
          "novation",
        ])
          assert(
            surface.includes(fact),
            `Approach ${approach} omitted ${fact}`,
          );
        assert(!surface.includes("Source:"));
        assert(!surface.includes("Loxoto"));
        if (approach === "a") {
          assert.equal(
            await active
              .locator('[data-unit="a-status"] [data-variant-body]')
              .evaluate((node) => getComputedStyle(node).textDecorationLine),
            "none",
          );
          assert.equal(
            await active
              .locator('[data-unit="a-status"] .ld-inline-detail')
              .evaluate((node) => getComputedStyle(node).textDecorationLine),
            "underline",
          );
          assert(
            await active
              .locator('[data-unit="a-liability"]')
              .evaluate(
                (node) => parseFloat(getComputedStyle(node).paddingLeft) >= 18,
              ),
          );
        }
        const metrics = await page.evaluate(() => {
          const stage = document.querySelector(
            ".ld-page-approach:not([hidden])",
          );
          const rect = stage.getBoundingClientRect();
          return {
            fit: LegalDesign.checkPageFit({ allPages: true }),
            bounds: rect.toJSON(),
            viewport: { width: innerWidth, height: innerHeight },
            layout: document.documentElement.dataset.pageLayout,
            scrollX: document.documentElement.scrollWidth - innerWidth,
            scrollY: document.documentElement.scrollHeight - innerHeight,
            labels: [...stage.querySelectorAll("svg text")].map((node) => {
              const matrix = node.getScreenCTM();
              return (
                parseFloat(getComputedStyle(node).fontSize) *
                Math.hypot(matrix.a, matrix.b)
              );
            }),
          };
        });
        assert(
          metrics.fit.valid,
          JSON.stringify({ width, theme, approach, metrics }),
        );
        assert.equal(metrics.layout, "adaptive");
        assert(
          Math.abs(metrics.bounds.right - (metrics.viewport.width - 12)) <= 1 &&
            Math.abs(metrics.bounds.bottom - (metrics.viewport.height - 64)) <=
              1 &&
            metrics.bounds.left >= 12 &&
            metrics.bounds.width >= metrics.viewport.width - 240 &&
            metrics.bounds.height >= metrics.viewport.height * 0.7,
          `Approach ${approach} does not fill the available window: ${JSON.stringify(metrics)}`,
        );
        assert(metrics.scrollX <= 1 && metrics.scrollY <= 1);
        await page.screenshot({
          path: join(out, `${width}-${theme}-${approach}.png`),
        });
        const target = active.locator('[data-detail="gate"]').first();
        await target.click();
        const popup = page.locator("#gate");
        assert(await popup.isVisible());
        assert((await popup.innerText()).includes("not supplied"));
        await page.screenshot({
          path: join(out, `${width}-${theme}-${approach}-popup.png`),
        });
        await popup.locator(".ld-popup-close").click();
        if (width < 760) {
          await page.locator("#ld-read-page").click();
          const reader = page.locator("#ld-page-reader");
          assert((await reader.innerText()).includes("£18,000"));
          if (approach === "a") {
            const status = reader
              .locator('.ld-inline-detail[data-detail="gate"]')
              .first();
            assert.equal(
              await status.evaluate(
                (node) => getComputedStyle(node).textDecorationLine,
              ),
              "underline",
              "Reader must preserve the precise popup-text affordance",
            );
          }
          await page.screenshot({
            path: join(out, `${width}-${theme}-${approach}-reader.png`),
          });
          await reader.locator(".ld-popup-close").click();
        }
        for (const kind of ["HTML", "Template"]) {
          const exported = await page.evaluate(
            (kind) => LegalDesign[`export${kind}`](false),
            kind,
          );
          const file = join(out, `${width}-${theme}-${approach}-${kind}.html`);
          writeFileSync(file, exported);
          const copy = await browser.newPage({ viewport: { width, height } });
          await copy.goto(pathToFileURL(file).href);
          await copy.waitForFunction(
            () => document.documentElement.dataset.legaldesignReady === "true",
          );
          assert(
            await copy.evaluate(
              () => LegalDesign.checkPageFit({ allPages: true }).valid,
            ),
            `${kind} export fit`,
          );
          if (kind === "HTML") {
            assert.equal(await copy.locator("[data-approach]").count(), 1);
            assert(
              (await copy.locator("body").innerText()).includes("£18,000"),
            );
          } else {
            assert.equal(await copy.locator("[data-approach]").count(), 2);
            assert(
              !readFileSync(file, "utf8").includes("£18,000"),
              "template leaked fee",
            );
          }
          await copy.close();
        }
        results.push({
          width,
          theme,
          approach,
          minimumOverviewLabel: Math.min(...metrics.labels),
          allPageFit: true,
        });
      }
    }
    assert.deepEqual(errors, []);
    await page.close();
  }
} finally {
  await browser.close();
}
writeFileSync(join(out, "results.json"), JSON.stringify(results, null, 2));
console.log(
  `PASS: forward design, 16 overview states, 32 export/reopen checks. Evidence: ${out}`,
);
console.log(JSON.stringify(results, null, 2));
