import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { chromium } from "@playwright/test";

const repo = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const out = mkdtempSync(join(tmpdir(), "legaldesign-detail-targets-"));
const plan = JSON.parse(
  readFileSync(
    join(
      repo,
      "packages/legaldesign/fixtures/case-06-novel-composition/plan.json",
    ),
  ),
);
plan.brief.form = "walkthrough";
const summary = plan.units.find((u) => u.id === "a-summary");
summary.detail = "e-input";
summary.detailAnchor = "legal source";
summary.evidence.push("e-input");
for (const approach of Object.values(plan.approaches))
  approach.composition.sections.forEach((s, i) => {
    s.indexLabel = `Topic ${i + 1}`;
  });
const planPath = join(out, "plan.json");
writeFileSync(planPath, JSON.stringify(plan));
const html = join(out, "working.html");
const build = spawnSync(
  process.env.LEGALDESIGN_PYTHON || "python3",
  [
    "skills/core/legaldesign/scripts/scaffold.py",
    "compose",
    "--plan",
    planPath,
    "--spec-output",
    join(out, "spec.json"),
    "--output",
    html,
    "--artifact-id",
    "detail-target-regression",
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
async function assertPopupProse(popup) {
  const colors = await popup.evaluate((node) => {
    const probe = document.createElement("span");
    probe.style.color = "var(--ink)";
    node.append(probe);
    const ink = getComputedStyle(probe).color;
    probe.remove();
    const prose = [
      ...node.querySelectorAll(".ld-popup-lede,.ld-popup-section p"),
    ];
    return { ink, prose: prose.map((n) => getComputedStyle(n).color) };
  });
  assert(
    colors.prose.length >= 2,
    "real introduction and section prose are checked",
  );
  assert(
    colors.prose.every((color) => color === colors.ink),
    "dark popup primary prose uses near-white ink, not metadata gray",
  );
  const lede = popup.locator(".ld-popup-lede");
  await lede.evaluate((node) => {
    node.style.color = "rgb(201, 32, 20)";
  });
  assert.equal(
    await lede.evaluate((node) => getComputedStyle(node).color),
    "rgb(201, 32, 20)",
    "explicit authored paint still takes precedence",
  );
  await lede.evaluate((node) => node.style.removeProperty("color"));
}
try {
  const page = await browser.newPage({
    viewport: { width: 1280, height: 720 },
  });
  page.setDefaultTimeout(5000);
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto(pathToFileURL(html).href);
  await page.waitForFunction(
    () => document.documentElement.dataset.legaldesignReady === "true",
  );
  const target = page.locator('[data-unit="a-summary"] .ld-inline-detail');
  assert.equal(await target.innerText(), "legal source");
  assert.equal(
    await page.locator('[data-unit="a-summary"]').getAttribute("data-detail"),
    null,
  );
  assert.equal(
    await page
      .locator('[data-unit="a-summary"] [data-variant-body]')
      .evaluate((n) => getComputedStyle(n).textDecorationLine),
    "none",
  );
  await target.click();
  assert(await page.locator("#e-input").isVisible());
  await page.evaluate(() => (document.documentElement.dataset.theme = "dark"));
  await assertPopupProse(page.locator("#e-input"));
  await page.screenshot({ path: join(out, "dark-popup-primary-prose.png") });
  await page.keyboard.press("Escape");
  await target.focus();
  await page.keyboard.press("Enter");
  assert(await page.locator("#e-input").isVisible());
  await page.keyboard.press("Escape");
  assert.equal(
    await page.locator('[data-report-section="0"]').innerText(),
    "1\nTopic 1",
  );
  assert(
    Number(
      await page
        .locator("html")
        .evaluate((n) => n.style.getPropertyValue("--ld-page-scale")),
    ) > 0.62,
    "short desktop should not retain unnecessary thumbnail scale",
  );

  // The actual failure: text-only compareTwo header groups previously had no
  // painted hit area because their text ignores pointer events in view mode.
  for (const narrow of [false, true]) {
    await page.evaluate((narrow) => {
      document.getElementById("detail-probe")?.remove();
      const probe = document.createElement("div");
      probe.id = "detail-probe";
      probe.style.cssText =
        "position:fixed;inset:90px 10px auto auto;width:600px;z-index:39;background:var(--bg)";
      probe.innerHTML = LegalDesign.render(
        "compareTwo",
        {
          a: "Option one",
          b: "Option two",
          aDetail: "e-input",
          bDetail: "e-output",
          highlight: "none",
          rows: [
            { label: "Scope", a: "Internal", b: "External", winner: "none" },
            { label: "Review", a: "Required", b: "Pending", winner: "none" },
          ],
        },
        { narrow },
      );
      document.body.appendChild(probe);
    }, narrow);
    for (const id of ["e-input", "e-output"]) {
      const heading = page.locator(`#detail-probe [data-detail="${id}"]`);
      await heading.click();
      assert(await page.locator(`#${id}`).isVisible());
      await page.keyboard.press("Escape");
      await heading.focus();
      await page.keyboard.press("Enter");
      assert(await page.locator(`#${id}`).isVisible());
      await page.keyboard.press("Escape");
    }
  }
  await page.evaluate(() => document.getElementById("detail-probe").remove());
  await page.setViewportSize({ width: 390, height: 844 });
  await page.locator("#ld-read-page").click();
  const readerTarget = page
    .locator("#ld-page-reader .ld-inline-detail")
    .first();
  await readerTarget.click();
  assert(await page.locator("#e-input").isVisible());
  await page.keyboard.press("Escape");
  assert(await page.locator("#ld-page-reader").isVisible());
  assert(await readerTarget.evaluate((n) => document.activeElement === n));
  await page.keyboard.press("Escape");
  assert(!(await page.locator("#ld-page-reader").isVisible()));
  await page.locator("[data-index-toggle]").click();
  assert(
    await page.locator("[data-index-toggle]").evaluate((n) => {
      const r = n.getBoundingClientRect();
      return n.contains(
        document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2),
      );
    }),
    "expanded phone contents toggle must not be obscured by the approach switch",
  );
  await page.locator("[data-index-toggle]").click();
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.waitForTimeout(100);
  const exports = await page.evaluate(() => ({
    client: LegalDesign.exportHTML(false),
    template: LegalDesign.exportTemplate(false),
  }));
  assert(!exports.template.includes('"detailAnchor":"legal source"'));
  assert(!exports.template.includes('data-index-label="Topic 1"'));
  for (const [kind, content] of Object.entries(exports)) {
    const file = join(out, `${kind}.html`);
    writeFileSync(file, content);
    const reopened = await browser.newPage({
      viewport: { width: 1280, height: 800 },
    });
    await reopened.goto(pathToFileURL(file).href);
    await reopened.waitForFunction(
      () => document.documentElement.dataset.legaldesignReady === "true",
    );
    const link = reopened
      .locator(".ld-fixed-page:not([hidden]) .ld-inline-detail")
      .first();
    if (kind === "template")
      assert.equal(
        await link.evaluate(
          (node) =>
            node
              .closest("section[data-unit]")
              .querySelectorAll("[data-variant-body] p").length,
        ),
        1,
        "template keeps the source link in its original paragraph slot",
      );
    await link.click();
    assert(
      await reopened.locator("#popup-scrim").isVisible(),
      `${kind} retains precise detail access`,
    );
    await reopened.evaluate(
      () => (document.documentElement.dataset.theme = "dark"),
    );
    await assertPopupProse(reopened.locator(".pop:visible").first());
    await reopened.close();
  }
  assert.deepEqual(errors, []);
  console.log(
    `PASS phrase targets, wide/narrow SVG hits, reader return, navigation and exports. Evidence: ${out}`,
  );
} finally {
  await browser.close();
}
