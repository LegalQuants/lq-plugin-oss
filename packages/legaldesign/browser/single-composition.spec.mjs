import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { chromium } from "@playwright/test";

const repo = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const out = mkdtempSync(join(tmpdir(), "legaldesign-single-composition-"));
const names = [
  "stacked-explainer",
  "method-map",
  "slide-brief",
  "diligence-report",
];
const artifacts = new Map();
const sentinel = "PRIVATE_SINGLE_OUTPUT_PROBE_572913";
console.log(`Single-composition evidence: ${out}`);
for (const name of names) {
  const output = join(out, `${name}.html`);
  const result = spawnSync(
    process.env.LEGALDESIGN_PYTHON || "python3",
    [
      "skills/core/legaldesign/scripts/scaffold.py",
      "compose",
      "--plan",
      `packages/legaldesign/templates/${name}.plan.json`,
      "--spec-output",
      join(out, `${name}.spec.json`),
      "--output",
      output,
      "--artifact-id",
      `single-${name}`,
    ],
    { cwd: repo, encoding: "utf8" },
  );
  assert.equal(result.status, 0, result.stdout + result.stderr);
  artifacts.set(name, output);
}
const browser = await chromium.launch({
  headless: true,
  executablePath: [
    chromium.executablePath(),
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  ].find(existsSync),
});
const errors = [];
const measurements = [];
const near = (a, b, label, tolerance = 2) =>
  assert(Math.abs(a - b) <= tolerance, `${label}: ${a} versus ${b}`);
async function settle(page) {
  await page.evaluate(
    () =>
      new Promise((resolve) =>
        requestAnimationFrame(() => requestAnimationFrame(resolve)),
      ),
  );
}
async function open(path, width = 1440, height = 900) {
  const page = await browser.newPage({
    viewport: { width, height },
    deviceScaleFactor: 2,
    acceptDownloads: true,
    hasTouch: width <= 760,
  });
  await page.addInitScript(() =>
    Object.defineProperty(window, "showSaveFilePicker", {
      configurable: true,
      value: undefined,
    }),
  );
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto(pathToFileURL(path).href);
  await page.waitForFunction(
    () => document.documentElement.dataset.legaldesignReady === "true",
  );
  await settle(page);
  if (width <= 760) {
    const reader = page.locator("#ld-page-reader");
    await reader.waitFor({ state: "visible" });
    const fonts = await reader
      .locator("p:not(.ld-detail-linkline)")
      .evaluateAll((nodes) =>
        nodes.map((node) => Number.parseFloat(getComputedStyle(node).fontSize)),
      );
    assert(
      fonts.length && fonts.every((font) => font >= 18),
      "phone opens with readable18px content",
    );
    const data = await state(page);
    const topic = data.overview.topics[0];
    if (topic) {
      const trigger = reader.locator(
        `[data-section-target="${topic.targetSectionId}"]`,
      );
      await trigger.click();
      await settle(page);
      assert.equal(
        await currentSection(page),
        topic.targetSectionId,
        "reader topic changes actual page",
      );
      assert(
        await page.locator("#ld-page-reader").isVisible(),
        "reader persists after topic navigation",
      );
      const heading = await page
        .locator(
          "[data-composition-section]:visible h1,[data-composition-section]:visible h2",
        )
        .first()
        .innerText();
      assert(
        (await page.locator("#ld-page-reader").innerText()).includes(heading),
        "reader refreshes destination content",
      );
    }
    await page.getByRole("button", { name: "Close page reader" }).click();
    await overview(page);
  }
  return page;
}
async function state(page) {
  return page.evaluate(() =>
    JSON.parse(document.getElementById("legaldesign-state").textContent),
  );
}
async function currentSection(page) {
  return page
    .locator("[data-composition-section]:visible")
    .getAttribute("data-composition-section");
}
async function overview(page) {
  const index = page.locator('[data-report-section="0"]');
  if (!(await index.count())) return;
  if (!(await index.isVisible()))
    await page.locator("[data-index-toggle]").click();
  await index.click();
  await settle(page);
}
async function inspect(page, label) {
  const info = await page.evaluate(() => {
    const root = document.documentElement;
    const data = JSON.parse(
      document.getElementById("legaldesign-state").textContent,
    );
    const section = [
      ...document.querySelectorAll("[data-composition-section]"),
    ].find((n) => n.getClientRects().length);
    const grid = section.querySelector(".ld-composed-grid");
    const rail = document.getElementById("ld-form-navigation");
    const scale = Number(root.style.getPropertyValue("--ld-page-scale"));
    const paragraphs = [
      ...section.querySelectorAll("[data-variant-body] p"),
    ].filter(
      (n) =>
        n.getClientRects().length &&
        !n.matches(".ld-detail-linkline") &&
        !n.closest('[data-role="scope"]'),
    );
    return {
      schema: data.sourceSchemaVersion,
      hasApproaches: "approaches" in data,
      hasReviewApproach: "approach" in data.review,
      b: document.querySelectorAll('[data-approach="b"],[data-select-approach]')
        .length,
      scale,
      width:
        Number.parseFloat(root.style.getPropertyValue("--ld-page-width")) *
        scale,
      fonts: paragraphs.map(
        (p) => Number.parseFloat(getComputedStyle(p).fontSize) * scale,
      ),
      captions: [...section.querySelectorAll(".ld-detail-linkline")].map(
        (node) => ({
          font: Number.parseFloat(getComputedStyle(node).fontSize) * scale,
          inScope: Boolean(node.closest('[data-role="scope"]')),
        }),
      ),
      scopes: [
        ...section.querySelectorAll(
          '[data-role="scope"] p:not(.ld-detail-linkline)',
        ),
      ].map(
        (node) => Number.parseFloat(getComputedStyle(node).fontSize) * scale,
      ),
      railBottom: rail?.getBoundingClientRect().bottom,
      gridBottom: grid?.getBoundingClientRect().bottom,
      fit: LegalDesign.checkPageFit(),
      issues: LegalDesign.lastPageFitIssues,
      scroll: [root.scrollWidth, root.scrollHeight, innerWidth, innerHeight],
    };
  });
  measurements.push({ label, ...info });
  if (!info.fit.valid)
    await page.screenshot({ path: join(out, `${label}-overflow.png`) });
  assert.equal(info.schema, "legaldesign.build.v4", label);
  assert.equal(
    info.hasApproaches,
    false,
    `${label}: no duplicated composition state`,
  );
  assert.equal(
    info.hasReviewApproach,
    false,
    `${label}: no approach selection state`,
  );
  assert.equal(info.b, 0, `${label}: no A/B UI or B surface`);
  assert(info.fit.valid, `${label}: ${JSON.stringify(info.issues)}`);
  assert(
    info.scroll[0] <= info.scroll[2] + 1 &&
      info.scroll[1] <= info.scroll[3] + 1,
    `${label}: main document must not scroll: ${info.scroll}`,
  );
  if (info.scroll[2] > 760) {
    near(info.scale, 1, `${label}: stable desktop scale`, 0.001);
    assert(
      info.width <= 1440.5,
      `${label}: bounded reading width ${info.width}`,
    );
    assert(info.fonts.length, `${label}: non-vacuous body typography`);
    for (const font of info.fonts)
      near(font, 16, `${label}: effective body text`, 0.05);
    for (const font of info.scopes)
      near(font, 12, `${label}: stable scope caption`, 0.05);
    for (const caption of info.captions)
      near(
        caption.font,
        caption.inScope ? 10.2 : 13.6,
        `${label}: stable source-action caption`,
        0.05,
      );
    if (info.railBottom != null)
      near(info.railBottom, info.gridBottom, `${label}: rail ends at content`);
  }
}
async function links(page, label) {
  const data = await state(page);
  const sections = data.composition.sections.map((s) => s.id);
  const ids = Object.keys(data.units);
  assert.equal(data.overview.sectionId, sections[0]);
  for (const id of [
    ...data.overview.contextUnitIds,
    data.overview.questionUnitId,
    data.overview.answerUnitId,
  ])
    assert(ids.includes(id), `${label}: overview reference resolves ${id}`);
  for (const [index, topic] of data.overview.topics.entries()) {
    assert(
      ids.includes(topic.unitId) && sections.includes(topic.targetSectionId),
    );
    await overview(page);
    const trigger = page.locator(
      `[data-composition-section]:visible [data-section-target="${topic.targetSectionId}"]`,
    );
    assert.equal(await trigger.count(), 1, `${label}: one topic action`);
    assert.equal(
      await trigger.getAttribute("data-detail"),
      null,
      `${label}: no popup/navigation collision`,
    );
    if (index % 2) {
      await trigger.focus();
      await page.keyboard.press("Enter");
    } else await trigger.click();
    await settle(page);
    assert.equal(
      await currentSection(page),
      topic.targetSectionId,
      `${label}: topic activation`,
    );
    await inspect(page, `${label}-topic-${index}`);
  }
  await overview(page);
  assert.equal(await currentSection(page), sections[0]);
}
try {
  for (const name of names) {
    for (const [width, height] of [
      [1280, 800],
      [1440, 900],
      [2560, 1440],
      [390, 844],
    ]) {
      const page = await open(artifacts.get(name), width, height);
      for (const theme of ["light", "dark"]) {
        if ((await page.locator("html").getAttribute("data-theme")) !== theme)
          await page.locator("#theme-toggle").click();
        await settle(page);
        const label = `${name}-${width}-${theme}`;
        await inspect(page, label);
        await links(page, label);
        await page.screenshot({ path: join(out, `${label}.png`) });
        if (width <= 760) {
          const book = page.locator("#ld-read-page");
          const box = await book.boundingBox();
          assert(box.width >= 44 && box.height >= 44, "book touch target");
          assert(await book.getAttribute("aria-label"), "book accessible name");
          await book.click();
          const reader = page.locator("#ld-page-reader");
          await reader.waitFor({ state: "visible" });
          const data = await state(page);
          for (const id of data.overview.contextUnitIds) {
            const text = await page
              .locator(`[data-unit="${id}"] [data-variant-body]`)
              .innerText();
            assert(
              (await reader.innerText()).includes(text),
              "reader preserves fact pattern",
            );
          }
          const fonts = await reader
            .locator("p")
            .evaluateAll((nodes) =>
              nodes.map((n) => parseFloat(getComputedStyle(n).fontSize)),
            );
          assert(
            fonts.length && fonts.every((font) => font >= 14),
            "unscaled readable detail",
          );
          await reader.screenshot({ path: join(out, `${label}-reader.png`) });
          await reader
            .getByRole("button", { name: "Close page reader" })
            .click();
        }
      }
      await page.close();
    }
  }
  const page = await open(artifacts.get("diligence-report"));
  const before = await state(page);
  await page.locator("#mode-toggle").click();
  const editable = page.locator('[data-unit="facts"] [data-editable]').first();
  await editable.dblclick();
  await editable.fill(`The reviewed record contains ${sentinel}.`);
  await page.locator("#mode-toggle").click();
  await settle(page);
  await page.locator("#mode-toggle").click();
  const [download] = await Promise.all([
    page.waitForEvent("download", { timeout: 10000 }),
    page.locator("#ld-save").click(),
  ]);
  const saved = join(out, "saved-working.html");
  await download.saveAs(saved);
  await page.locator("#mode-toggle").click();
  const client = join(out, "client.html"),
    template = join(out, "template.html");
  writeFileSync(
    client,
    await page.evaluate(() => LegalDesign.exportHTML(false)),
  );
  writeFileSync(
    template,
    await page.evaluate(() => LegalDesign.exportTemplate(false)),
  );
  assert(readFileSync(saved, "utf8").includes(sentinel));
  assert(readFileSync(client, "utf8").includes(sentinel));
  assert(
    !readFileSync(template, "utf8").includes(sentinel),
    "template scrubs edited matter text",
  );
  await page.close();
  for (const [name, path] of [
    ["saved", saved],
    ["client", client],
    ["template", template],
  ]) {
    for (const [width, height] of [
      [1440, 900],
      [390, 844],
    ]) {
      const reopened = await open(path, width, height);
      await inspect(reopened, `${name}-${width}`);
      await links(reopened, `${name}-${width}`);
      const data = await state(reopened);
      if (name === "template") {
        assert(
          data.composition.sections.every(
            (s) => !before.composition.sections.some((old) => old.id === s.id),
          ),
          "template section IDs are remapped, not retained matter identifiers",
        );
        assert(
          data.overview.topics.every(
            (t) =>
              !before.overview.topics.some((old) => old.unitId === t.unitId),
          ),
          "template topic IDs remapped coherently",
        );
      } else
        assert(
          (await reopened.locator('[data-unit="facts"]').innerText()).includes(
            sentinel,
          ),
          `${name}: edited facts persist`,
        );
      await reopened.close();
    }
  }
  assert.deepEqual(errors, []);
  console.log(
    "PASS: single composition, stable type, bounded layout, aligned rail, overview navigation, phone reader, editor Save and both export/reopen contracts.",
  );
} finally {
  writeFileSync(
    join(out, "measurements.json"),
    JSON.stringify(measurements, null, 2),
  );
  await browser.close();
}
