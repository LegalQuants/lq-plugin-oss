import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import {
  copyFileSync,
  existsSync,
  mkdtempSync,
  readFileSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { chromium } from "@playwright/test";

// Synthetic fixture only. Compose with the shipping shell; never patch assets
// or replace the renderer/runtime in the fixture being tested.
const repo = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const out = mkdtempSync(join(tmpdir(), "legaldesign-grouped-overview-"));
const sentinel = "PRIVATE_GROUP_PROBE_864219";
const topicCount = 54;
const groupCount = 6;
const plan = JSON.parse(
  readFileSync(
    join(repo, "packages/legaldesign/templates/slide-brief.plan.json"),
  ),
);
const originalUnits = new Map(plan.units.map((unit) => [unit.id, unit]));
const clone = (value) => structuredClone(value);
const simpleUnit = (base, id, html, claim, role = "summary") => {
  const unit = clone(originalUnits.get(base));
  Object.assign(unit, { id, claim, role });
  unit.variants.a.html = html;
  return unit;
};
plan.brief.title = "Synthetic review: 54 topics";
plan.brief.reader = "A test operator inspecting synthetic navigation content.";
plan.brief.action = "Open each numbered topic and verify its destination.";
plan.brief.message = "This fixture contains no private or legal matter.";
plan.claims = plan.claims.filter((claim) =>
  ["c-title", "c-core", "c-overview"].includes(claim.id),
);
plan.evidence = plan.evidence.filter((evidence) => evidence.id === "e-core");
plan.units = [
  simpleUnit(
    "overview-title",
    "overview-title",
    "<h1>Synthetic review: 54 topics</h1>",
    "Synthetic review: 54 topics",
    "title",
  ),
  simpleUnit(
    "facts",
    "facts",
    "<p>Facts: fifty-four synthetic topics require review.</p>",
    "Fifty-four synthetic topics require review.",
  ),
  simpleUnit(
    "question",
    "question",
    "<p>Question: which topic should the reader inspect?</p>",
    "Which synthetic topic should the reader inspect?",
  ),
  simpleUnit(
    "overview-answer",
    "overview-answer",
    "<p>Answer: choose a subject group, then open its topic.</p>",
    "Choose a subject group, then open its topic.",
    "answer",
  ),
];
const overview = clone(plan.composition.sections[0]);
overview.unitIds = plan.units.map((unit) => unit.id);
overview.layout.placements = [
  { unitId: "overview-title", row: 1, column: 1, span: 12 },
  { unitId: "facts", row: 2, column: 1, span: 6 },
  { unitId: "question", row: 2, column: 7, span: 6 },
  { unitId: "overview-answer", row: 3, column: 1, span: 12 },
];
plan.composition.sections = [overview];
plan.composition.shape = "Six subject groups linking to 54 synthetic pages";
plan.overview.topics = [];
plan.overview.groups = Array.from({ length: groupCount }, (_, index) => ({
  label: `${sentinel} subject ${index + 1}`,
  topicUnitIds: [],
}));
for (let index = 1; index <= topicCount; index++) {
  const suffix = String(index).padStart(2, "0");
  const topicId = `topic-${suffix}`;
  const sectionId = `destination-${suffix}`;
  const titleId = `title-${suffix}`;
  const bodyId = `body-${suffix}`;
  plan.units.push(
    simpleUnit(
      "topic-1",
      topicId,
      `<h2>Topic ${suffix}</h2><p>Inspect item ${suffix}.</p>`,
      `Inspect synthetic item ${suffix}.`,
    ),
    simpleUnit(
      "overview-title",
      titleId,
      `<h1>Destination ${suffix}</h1>`,
      `Destination ${suffix}`,
      "summary",
    ),
    simpleUnit(
      "overview-answer",
      bodyId,
      `<p>Synthetic destination ${suffix}: check its condition before acting.</p>`,
      `Check synthetic condition ${suffix} before acting.`,
      "answer",
    ),
  );
  overview.unitIds.push(topicId);
  overview.layout.placements.push({
    unitId: topicId,
    row: index + 3,
    column: 1,
    span: 12,
  });
  plan.composition.sections.push({
    id: sectionId,
    purpose: `Inspect synthetic topic ${suffix}`,
    indexLabel: `Topic ${suffix}`,
    unitIds: [titleId, bodyId],
    layout: {
      columns: 12,
      placements: [
        { unitId: titleId, row: 1, column: 1, span: 12 },
        { unitId: bodyId, row: 2, column: 1, span: 12 },
      ],
    },
  });
  plan.overview.topics.push({ unitId: topicId, targetSectionId: sectionId });
  plan.overview.groups[Math.floor((index - 1) / 9)].topicUnitIds.push(topicId);
}
const fixture = join(out, "grouped.html");
const planPath = join(out, "grouped.plan.json");
writeFileSync(planPath, JSON.stringify(plan, null, 2));
const composed = spawnSync(
  process.env.LEGALDESIGN_PYTHON || "python3",
  [
    "skills/core/legaldesign/scripts/scaffold.py",
    "compose",
    "--plan",
    planPath,
    "--spec-output",
    join(out, "grouped.spec.json"),
    "--output",
    fixture,
    "--artifact-id",
    "synthetic-grouped-regression",
  ],
  { cwd: repo, encoding: "utf8" },
);
assert.equal(composed.status, 0, composed.stdout + composed.stderr);
console.log(`Grouped-overview evidence: ${out}`);
const failures = [];
const measurements = [];
const coverage = [];
const errors = [];
const browser = await chromium.launch({
  headless: true,
  executablePath: [
    chromium.executablePath(),
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  ].find(existsSync),
});
const sizes = [
  [1280, 800],
  [1440, 900],
  [390, 844],
];
const sections = "[data-composition-section]:visible";
const groupSelector = ".ld-overview-groups > details.ld-overview-group";
async function settle(page) {
  await page.evaluate(
    () =>
      new Promise((done) =>
        requestAnimationFrame(() => requestAnimationFrame(done)),
      ),
  );
}
async function open(path, width, height) {
  const page = await browser.newPage({
    viewport: { width, height },
    acceptDownloads: true,
    hasTouch: width <= 760,
  });
  page.setDefaultTimeout(7000);
  await page.addInitScript(() =>
    Object.defineProperty(window, "showSaveFilePicker", {
      configurable: true,
      value: undefined,
    }),
  );
  page.on("pageerror", (error) => errors.push({ path, error: error.message }));
  await page.goto(pathToFileURL(path).href);
  await page.waitForFunction(
    () => document.documentElement.dataset.legaldesignReady === "true",
  );
  await settle(page);
  return page;
}
async function state(page) {
  return page.evaluate(() =>
    JSON.parse(document.getElementById("legaldesign-state").textContent),
  );
}
async function current(page) {
  return page.locator(sections).getAttribute("data-composition-section");
}
async function toOverview(page, phone) {
  const reader = page.locator("#ld-page-reader");
  if (await reader.isVisible())
    await page
      .getByRole("button", { name: "Close page reader", exact: true })
      .click();
  const button = page.locator('[data-report-section="0"]');
  if (!(await button.isVisible()))
    await page.locator("[data-index-toggle]").click();
  await button.click();
  await settle(page);
  if (phone) {
    await page.locator("#ld-read-page").click();
    await reader.waitFor({ state: "visible" });
  }
}
function scope(page, phone) {
  return page.locator(phone ? "#ld-page-reader" : sections);
}
async function chooseGroup(page, phone, index, keyboard = false) {
  const group = scope(page, phone).locator(groupSelector).nth(index);
  if (!(await group.evaluate((node) => node.open))) {
    if (keyboard) await group.locator("summary").press("Enter");
    else await group.locator("summary").click();
    await settle(page);
  }
  assert.equal(
    await scope(page, phone).locator(`${groupSelector}[open]`).count(),
    1,
    `one-open group ${index}`,
  );
  assert(
    await group.evaluate((node) => node.open),
    `chosen group ${index} opens`,
  );
  return group;
}
async function inspect(page, phone, label) {
  const info = await page.evaluate((phone) => {
    const active = [
      ...document.querySelectorAll("[data-composition-section]"),
    ].find((node) => node.getClientRects().length);
    const reader = document.querySelector("#ld-page-reader");
    const frame = phone ? reader : active;
    const group = frame.querySelector("details.ld-overview-group[open]");
    const grid = group.querySelector(".ld-overview-topic-grid");
    const box = (node) => node.getBoundingClientRect().toJSON();
    return {
      viewport: [innerWidth, innerHeight],
      fit: LegalDesign.checkPageFit(),
      issues: LegalDesign.lastPageFitIssues,
      scale: getComputedStyle(active).transform,
      document: [
        document.documentElement.scrollWidth,
        document.documentElement.scrollHeight,
      ],
      frame: box(frame),
      group: box(group),
      grid: box(grid),
      columns: getComputedStyle(grid).gridTemplateColumns,
      topics: [...grid.querySelectorAll("[data-section-target]")].map(
        (node) => ({
          box: box(node),
          target: node.dataset.sectionTarget,
          detail: node.dataset.detail || null,
          padding: getComputedStyle(node).padding,
          headingSize: getComputedStyle(node.querySelector("h2,h3")).fontSize,
          bodySize: getComputedStyle(node.querySelector("p")).fontSize,
        }),
      ),
      readerWidth: reader ? [reader.clientWidth, reader.scrollWidth] : null,
    };
  }, phone);
  measurements.push({ label, ...info });
  assert.equal(info.topics.length, 9, `${label}: nine real topic cards`);
  assert(
    info.topics.every((topic) => !topic.detail),
    `${label}: topic/popup collision`,
  );
  assert(info.fit.valid, `${label}: page fit ${JSON.stringify(info.issues)}`);
  assert(
    info.document[0] <= info.viewport[0] + 1 &&
      info.document[1] <= info.viewport[1] + 1,
    `${label}: document overflow`,
  );
  const columns = info.columns.split(" ").length;
  assert.equal(columns, phone ? 1 : 3, `${label}: expected topic grid columns`);
  for (const topic of info.topics) {
    assert.equal(
      topic.headingSize,
      phone ? "18px" : "16px",
      `${label}: topic heading size`,
    );
    assert.equal(
      topic.bodySize,
      phone ? "18px" : "16px",
      `${label}: topic body size`,
    );
    if (!phone)
      assert.equal(
        topic.padding,
        "10px 12px",
        `${label}: compact topic card padding`,
      );
  }
  if (phone)
    assert(
      info.readerWidth[1] <= info.readerWidth[0] + 1,
      `${label}: horizontal reader overflow`,
    );
  else {
    assert.equal(
      info.scale,
      "matrix(1, 0, 0, 1, 0, 0)",
      `${label}: stable desktop type`,
    );
    assert(
      info.group.bottom <= info.frame.bottom + 1,
      `${label}: expanded group exceeds page`,
    );
  }
}
async function traversal(path, kind, width, height) {
  const label = `${kind}-${width}`;
  const page = await open(path, width, height);
  const phone = width <= 760;
  try {
    const data = await state(page);
    assert.equal(data.composition.sections.length, 55, `${label}: 55 pages`);
    assert.equal(data.overview.topics.length, 54, `${label}: 54 topics`);
    assert.equal(data.overview.groups.length, 6, `${label}: six groups`);
    assert.deepEqual(
      data.overview.groups.flatMap((group) => group.topicUnitIds),
      data.overview.topics.map((topic) => topic.unitId),
      `${label}: remapped topic partition`,
    );
    if (kind === "template")
      assert(
        data.overview.groups.every((group) => !group.label.includes(sentinel)),
        `${label}: private group metadata`,
      );
    if (phone)
      await page.locator("#ld-page-reader").waitFor({ state: "visible" });
    await toOverview(page, phone);
    assert.equal(await scope(page, phone).locator(groupSelector).count(), 6);
    assert.deepEqual(
      await scope(page, phone)
        .locator(".ld-overview-group-label")
        .allTextContents(),
      data.overview.groups.map((group) => group.label),
      `${label}: visible group labels agree with metadata`,
    );
    assert.deepEqual(
      await scope(page, phone)
        .locator(".ld-overview-group-count")
        .allTextContents(),
      Array(groupCount).fill("9 topics"),
      `${label}: every summary retains its structural topic count`,
    );
    for (let groupIndex = 0; groupIndex < groupCount; groupIndex++) {
      await chooseGroup(page, phone, groupIndex, groupIndex % 2 === 1);
      await inspect(page, phone, `${label}-group-${groupIndex}`);
      if (groupIndex === 0 || groupIndex === 5)
        await page.screenshot({
          path: join(out, `${label}-group-${groupIndex}.png`),
        });
      // Every destination uses an actual pointer action, including reopened
      // client/template mappings. No force or programmatic dispatch.
      for (const unitId of data.overview.groups[groupIndex].topicUnitIds) {
        await chooseGroup(page, phone, groupIndex);
        const topic = data.overview.topics.find(
          (entry) => entry.unitId === unitId,
        );
        const trigger = scope(page, phone).locator(
          `[data-section-target="${topic.targetSectionId}"]`,
        );
        assert.equal(await trigger.count(), 1);
        await trigger.click();
        await settle(page);
        assert.equal(
          await current(page),
          topic.targetSectionId,
          `${label}: destination ${unitId}`,
        );
        if (phone) {
          assert(
            await page.locator("#ld-page-reader").isVisible(),
            `${label}: reader survives topic`,
          );
          const title = await page
            .locator(sections)
            .locator("h1,h2")
            .first()
            .innerText();
          assert(
            (await page.locator("#ld-page-reader").innerText()).includes(title),
            `${label}: reader destination matches`,
          );
        }
        coverage.push({
          kind,
          width,
          groupIndex,
          unitId,
          destination: topic.targetSectionId,
        });
        await toOverview(page, phone);
      }
    }
    const group = await chooseGroup(page, phone, 4);
    await group.locator("summary").press("Space");
    await settle(page);
    assert.equal(
      await group.evaluate((node) => node.open),
      false,
      `${label}: Space closes summary`,
    );
    await group.locator("summary").press("Enter");
    await settle(page);
    assert.equal(
      await group.evaluate((node) => node.open),
      true,
      `${label}: Enter opens summary`,
    );
    console.log(
      `PASS ${label}: all 54 destinations, six expanded groups, keyboard and one-open`,
    );
  } catch (error) {
    await page.screenshot({ path: join(out, `${label}-failure.png`) });
    throw error;
  } finally {
    await page.close();
  }
}
async function attempt(label, action) {
  try {
    await action();
  } catch (error) {
    failures.push({ label, error: error.stack || String(error) });
    console.error(`FAIL ${label}: ${error.message}`);
  }
}
async function downloadFile(page, selector, name) {
  const [download] = await Promise.all([
    page.waitForEvent("download", { timeout: 15000 }),
    page.locator(selector).click(),
  ]);
  assert.equal(await download.failure(), null);
  const actual = await download.path();
  assert(
    actual && existsSync(actual),
    `${name}: actual browser download exists`,
  );
  const target = join(out, name);
  copyFileSync(actual, target);
  return target;
}
try {
  for (const [width, height] of sizes)
    await attempt(`working-${width}`, () =>
      traversal(fixture, "working", width, height),
    );
  await attempt("save-and-exports", async () => {
    const page = await open(fixture, 1440, 900);
    try {
      await chooseGroup(page, false, 3);
      await page.locator("#mode-toggle").click();
      const saved = await downloadFile(page, "#ld-save", "saved-working.html");
      await page.locator("#mode-toggle").click();
      const reopened = await open(saved, 1440, 900);
      try {
        assert.equal(
          await reopened
            .locator(`${sections} ${groupSelector}`)
            .nth(3)
            .evaluate((node) => node.open),
          true,
          "Save/reopen preserves chosen group",
        );
        await reopened.reload();
        await settle(reopened);
        assert.equal(
          await reopened
            .locator(`${sections} ${groupSelector}`)
            .nth(3)
            .evaluate((node) => node.open),
          true,
          "Reload preserves chosen group",
        );
        await reopened.screenshot({ path: join(out, "saved-group-3.png") });
      } finally {
        await reopened.close();
      }
      // Reopen the clean saved bytes for each export so a transient result
      // banner cannot reduce the next export's measured page frame.
      for (const kind of ["client", "template"]) {
        const exportPage = await open(saved, 1440, 900);
        let exported;
        try {
          exported = await downloadFile(
            exportPage,
            kind === "client" ? "#export-html" : "#export-template",
            `${kind}.html`,
          );
          await settle(exportPage);
          assert.equal(
            await exportPage
              .locator(`${sections} ${groupSelector}`)
              .nth(3)
              .evaluate((node) => node.open),
            true,
            `${kind}: validation restores active group`,
          );
        } finally {
          await exportPage.close();
        }
        const html = readFileSync(exported, "utf8");
        assert.equal(
          html.includes(sentinel),
          kind === "client",
          `${kind}: group-label privacy sentinel`,
        );
        for (const [width, height] of sizes)
          await attempt(`${kind}-${width}`, () =>
            traversal(exported, kind, width, height),
          );
      }
    } finally {
      await page.close();
    }
  });
  await attempt("closed-group-overflow-rejected", async () => {
    const page = await open(fixture, 1440, 900);
    try {
      const before = await page
        .locator(`${sections} ${groupSelector}`)
        .evaluateAll((nodes) => nodes.map((node) => node.open));
      // Deliberately malformed presentation, confined to this disposable page.
      // The oversized last group stays closed throughout the export request.
      await page
        .locator(`${sections} ${groupSelector}`)
        .nth(5)
        .locator(".ld-overview-topic-grid > section")
        .first()
        .evaluate((node) => {
          node.style.height = "1800px";
        });
      assert.equal(
        await page
          .locator(`${sections} ${groupSelector}`)
          .nth(5)
          .evaluate((node) => node.open),
        false,
      );
      assert.equal(
        (await page.evaluate(() => LegalDesign.checkPageFit())).valid,
        true,
        "closed malformed content does not invalidate the visible group",
      );
      for (const method of ["exportHTML", "exportTemplate"]) {
        const result = await page.evaluate((method) => {
          try {
            LegalDesign[method](false);
            return { rejected: false };
          } catch (error) {
            return {
              rejected: true,
              message: error.message,
              issues: LegalDesign.lastPageFitIssues,
            };
          }
        }, method);
        assert(
          result.rejected,
          `${method}: closed-group overflow escaped export validation`,
        );
        assert.match(result.message, /exceeds|overflow/i);
        measurements.push({ label: `negative-${method}`, ...result });
        await settle(page);
        assert.deepEqual(
          await page
            .locator(`${sections} ${groupSelector}`)
            .evaluateAll((nodes) => nodes.map((node) => node.open)),
          before,
          `${method}: failed validation restores open states`,
        );
      }
      await page.screenshot({
        path: join(out, "closed-group-export-blocked.png"),
      });
      console.log(
        "PASS closed oversized group blocks both exports without changing open states",
      );
    } finally {
      await page.close();
    }
  });
  assert.deepEqual(errors, [], "No browser runtime errors");
  assert.equal(
    coverage.length,
    486,
    "All 54 destinations in all nine copy/viewport combinations",
  );
} catch (error) {
  failures.push({ label: "runtime", error: error.stack || String(error) });
} finally {
  writeFileSync(
    join(out, "results.json"),
    JSON.stringify({ failures, errors, measurements, coverage }, null, 2),
  );
  await browser.close();
  writeFileSync(
    join(out, "report.md"),
    [
      `# Grouped-overview browser regression: ${failures.length ? "FAIL" : "PASS"}`,
      "",
      "Synthetic, non-private fixture: 54 topics, 55 pages, six groups of nine. Composed from the shipping assets; no runtime or CSS injection.",
      "",
      `Completed ${coverage.length} real destination clicks across working, downloaded client and downloaded template copies at 1280×800, 1440×900 and 390×844. Browser runtime errors: ${errors.length}.`,
      "",
      "Checks include native Enter/Space summary controls, one-open behavior, per-group layout, save/download/reload state, neutral template labels, topic-ID remapping, and rejection of an oversized group while it is closed.",
      "",
      failures.length
        ? failures
            .map(({ label, error }) => `- ${label}: ${error.split("\n")[0]}`)
            .join("\n")
        : "All requested checks passed.",
      "",
      "Detailed measurements and destination coverage: results.json. Screenshots in this directory show the first and last group for each viewport/copy, the saved group, and blocked-export state; any interrupted traversal also has a failure screenshot.",
      "",
      "Cleanup: all isolated headless browser contexts closed. No server or user browser tab was opened. Original assets and demonstration artifacts were not modified by this regression.",
      "",
    ].join("\n"),
  );
}
console.log(
  `${failures.length ? "FAIL" : "PASS"}: ${coverage.length} real destination clicks; evidence ${out}`,
);
assert.equal(failures.length, 0, JSON.stringify(failures, null, 2));
