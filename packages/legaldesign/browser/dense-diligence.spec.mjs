import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { chromium } from "@playwright/test";

const repo = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const out = mkdtempSync(join(tmpdir(), "legaldesign-dense-"));
const html = join(out, "dense-diligence.html");
const sourcePlan = join(
  repo,
  "packages/legaldesign/fixtures/case-08-dense-diligence/plan.json",
);
const plan = JSON.parse(readFileSync(sourcePlan, "utf8"));
const clip = plan.evidence[0].exhibit;
const build = spawnSync(
  process.env.LEGALDESIGN_PYTHON || "python3",
  [
    "skills/core/legaldesign/scripts/scaffold.py",
    "compose",
    "--plan",
    sourcePlan,
    "--spec-output",
    join(out, "plan.json"),
    "--output",
    html,
    "--artifact-id",
    "dense-diligence-regression",
  ],
  { cwd: repo, encoding: "utf8" },
);
assert.equal(build.status, 0, build.stdout + build.stderr);
const browser = await chromium.launch({
  headless: true,
  executablePath: [
    chromium.executablePath(),
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  ].find(existsSync),
});
let count = 0;
try {
  for (const [width, height] of [
    [1440, 900],
    [1280, 800],
    [430, 932],
    [390, 844],
  ]) {
    const page = await browser.newPage({
      viewport: { width, height },
      deviceScaleFactor: 2,
    });
    const errors = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await page.goto(pathToFileURL(html).href);
    await page.waitForFunction(
      () =>
        window.LegalDesign?.state &&
        document.documentElement.dataset.legaldesignReady === "true",
    );
    for (const theme of ["light", "dark"]) {
      if ((await page.locator("html").getAttribute("data-theme")) !== theme)
        await page.locator("#theme-toggle").click();
      for (const approach of ["a", "b"]) {
        await page.locator(`[data-select-approach="${approach}"]`).click();
        await page.evaluate(
          () =>
            new Promise((r) =>
              requestAnimationFrame(() => requestAnimationFrame(r)),
            ),
        );
        const fit = await page.evaluate(() =>
          window.LegalDesign.checkPageFit(),
        );
        await page.screenshot({
          path: join(out, `${width}-${theme}-${approach}.png`),
        });
        assert(fit.valid, JSON.stringify({ width, theme, approach, fit }));
        const active = page.locator(
          `.ld-page-approach[data-approach="${approach}"]`,
        );
        const text = await active.innerText();
        assert(
          text.split(/\s+/).length >= 200,
          `${approach}: dense sample is too thin`,
        );
        for (const marker of [
          "$0.52",
          "69 days",
          "March",
          "Fictional design sample",
        ])
          assert(text.includes(marker), marker);
        assert.equal(
          await active.locator("a[href],.eyebrow,.ld-kicker").count(),
          0,
        );
        await active
          .locator(
            `[data-unit="${approach === "a" ? "a-finding" : "b-register"}"]`,
          )
          .click();
        const pop = page.locator("#valuation-record");
        await pop.waitFor({ state: "visible" });
        assert.equal(
          await pop.locator("img.exhibit-shot").getAttribute("src"),
          clip.data,
        );
        assert(
          await pop
            .locator("img.exhibit-shot")
            .evaluate((i) => i.complete && i.naturalWidth > 0),
        );
        assert(
          (await pop.innerText()).includes(
            "Full consent and appraisal files were not supplied",
          ),
        );
        await page.screenshot({
          path: join(out, `${width}-${theme}-${approach}-source.png`),
        });
        await pop.locator(".ld-popup-close").click();
        if (width < 500) {
          await page
            .getByRole("button", { name: "Read page", exact: true })
            .click();
          const reader = page.locator("#ld-page-reader");
          // The visible reader API may use a dialog root; assert its unchanged copy.
          const readText = await reader.innerText();
          assert(
            readText.includes("$0.52") &&
              readText.includes("Fictional design sample"),
          );
          await page.keyboard.press("Escape");
        }
        count++;
      }
    }
    assert.deepEqual(errors, []);
    await page.close();
  }
  const page = await browser.newPage({
    viewport: { width: 1440, height: 900 },
  });
  await page.goto(pathToFileURL(html).href);
  await page.waitForFunction(
    () =>
      window.LegalDesign?.exportHTML &&
      document.documentElement.dataset.legaldesignReady === "true",
  );
  for (const mode of ["client", "template"]) {
    const exported = await page.evaluate(
      (mode) =>
        mode === "client"
          ? window.LegalDesign.exportHTML(false)
          : window.LegalDesign.exportTemplate(false),
      mode,
    );
    const target = join(out, `${mode}.html`);
    writeFileSync(target, exported);
    if (mode === "client") assert(exported.includes(clip.data));
    else
      for (const privateValue of [
        clip.data,
        clip.sha256,
        clip.sourceSha256,
        "$0.52",
        "6 May 2025",
        "55,000",
      ])
        assert(
          !exported.includes(privateValue),
          `template retained ${privateValue.slice(0, 30)}`,
        );
    const reopened = await browser.newPage({
      viewport: { width: 1440, height: 900 },
    });
    await reopened.goto(pathToFileURL(target).href);
    await reopened.waitForFunction(
      () =>
        window.LegalDesign?.state &&
        document.documentElement.dataset.legaldesignReady === "true",
    );
    await reopened.screenshot({ path: join(out, `${mode}-reopened.png`) });
    const fit = await reopened.evaluate(() =>
      window.LegalDesign.checkPageFit(),
    );
    assert(fit.valid, `${mode}: ${JSON.stringify(fit)}`);
    if (mode === "client") {
      await reopened.locator('[data-unit="a-finding"]').click();
      assert.equal(
        await reopened.locator("#valuation-record img").getAttribute("src"),
        clip.data,
      );
    } else {
      assert.equal(await reopened.locator("[data-select-approach]").count(), 2);
      assert.equal(await reopened.locator("img[src^='data:image']").count(), 0);
      const spans = await reopened
        .locator(".ld-composed-unit")
        .evaluateAll((nodes) =>
          nodes.map((n) => getComputedStyle(n).gridRowEnd),
        );
      assert(
        spans.includes("span 3"),
        "template lost spanning timeline geometry",
      );
    }
    await reopened.close();
  }
  console.log(
    `PASS: ${count} dense page states, exact supplied source clip, reader, and client/template reopen. Evidence: ${out}`,
  );
} finally {
  await browser.close();
}
