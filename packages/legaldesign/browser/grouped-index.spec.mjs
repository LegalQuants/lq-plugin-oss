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

// Repository-only synthetic regression. Use the shipping composer and shell;
// never copy private example text or inject replacement runtime/CSS.
const repo = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const out = mkdtempSync(join(tmpdir(), "legaldesign-grouped-index-"));
const sentinel = "NAV582613";
const plan = JSON.parse(
  readFileSync(
    join(repo, "packages/legaldesign/templates/slide-brief.plan.json"),
  ),
);
const bases = new Map(plan.units.map((unit) => [unit.id, unit]));
const unit = (base, id, html, role = "summary") => {
  const copy = structuredClone(bases.get(base));
  Object.assign(copy, { id, role, claim: `Synthetic ${id}.` });
  copy.variants.a.html = html;
  return copy;
};
plan.brief.title = "Synthetic grouped contents";
plan.brief.reader =
  "A test operator inspecting a synthetic navigation fixture.";
plan.brief.action = "Open each synthetic destination from its subject group.";
plan.brief.message = "This fixture contains no private matter or legal advice.";
plan.claims = plan.claims.filter((claim) =>
  ["c-title", "c-core", "c-overview"].includes(claim.id),
);
plan.evidence = plan.evidence.filter((evidence) => evidence.id === "e-core");
plan.units = [
  unit(
    "overview-title",
    "overview-title",
    "<h1>Synthetic grouped contents</h1>",
    "title",
  ),
  unit("facts", "facts", "<p>Facts: fifty-four synthetic topics.</p>"),
  unit(
    "question",
    "question",
    "<p>Question: which subject should be opened?</p>",
  ),
  unit(
    "overview-answer",
    "overview-answer",
    "<p>Answer: choose a group and a topic.</p>",
    "answer",
  ),
];
const overview = structuredClone(plan.composition.sections[0]);
overview.unitIds = plan.units.map((entry) => entry.id);
overview.layout.placements = [
  { unitId: "overview-title", row: 1, column: 1, span: 12 },
  { unitId: "facts", row: 2, column: 1, span: 6 },
  { unitId: "question", row: 2, column: 7, span: 6 },
  { unitId: "overview-answer", row: 3, column: 1, span: 12 },
];
plan.composition.sections = [overview];
plan.composition.shape =
  "Six subject groups whose order differs from page order";
plan.overview.topics = [];
// Interleave destinations across subjects, then reorder the subjects. Neither
// group position nor DOM button position can stand in for a section index.
const groupNumbers = [3, 6, 1, 5, 2, 4].map((first) =>
  Array.from({ length: 9 }, (_, index) => first + index * 6),
);
plan.overview.groups = groupNumbers.map((numbers, index) => ({
  label: `${sentinel} group ${index + 1}`,
  topicUnitIds: numbers.map(
    (number) => `topic-${String(number).padStart(2, "0")}`,
  ),
}));
for (let number = 1; number <= 54; number++) {
  const suffix = String(number).padStart(2, "0");
  plan.units.push(
    unit(
      "topic-1",
      `topic-${suffix}`,
      `<h2>Topic ${suffix}</h2><p>Inspect item ${suffix}.</p>`,
    ),
    unit("overview-title", `title-${suffix}`, `<h1>Destination ${suffix}</h1>`),
    unit(
      "overview-answer",
      `body-${suffix}`,
      `<p>Synthetic item ${suffix}: check its condition.</p>`,
      "answer",
    ),
  );
  plan.composition.sections.push({
    id: `destination-${suffix}`,
    purpose: `Inspect synthetic item ${suffix}`,
    indexLabel: `Topic ${suffix}`,
    unitIds: [`title-${suffix}`, `body-${suffix}`],
    layout: {
      columns: 12,
      placements: [
        { unitId: `title-${suffix}`, row: 1, column: 1, span: 12 },
        { unitId: `body-${suffix}`, row: 2, column: 1, span: 12 },
      ],
    },
  });
}
for (const [index, number] of groupNumbers.flat().entries()) {
  const suffix = String(number).padStart(2, "0");
  const topicId = `topic-${suffix}`;
  overview.unitIds.push(topicId);
  overview.layout.placements.push({
    unitId: topicId,
    row: index + 4,
    column: 1,
    span: 12,
  });
  plan.overview.topics.push({
    unitId: topicId,
    targetSectionId: `destination-${suffix}`,
  });
}
const fixture = join(out, "grouped-index.html");
const planPath = join(out, "grouped-index.plan.json");
writeFileSync(planPath, JSON.stringify(plan, null, 2));
const composed = spawnSync(
  process.env.LEGALDESIGN_PYTHON || "python3",
  [
    "skills/core/legaldesign/scripts/scaffold.py",
    "compose",
    "--plan",
    planPath,
    "--spec-output",
    join(out, "grouped-index.spec.json"),
    "--output",
    fixture,
    "--artifact-id",
    "synthetic-grouped-index-regression",
  ],
  { cwd: repo, encoding: "utf8" },
);
assert.equal(composed.status, 0, composed.stdout + composed.stderr);
console.log(`Grouped-index evidence: ${out}`);

const failures = [];
const errors = [];
const coverage = [];
const measurements = [];
const checks = [];
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
const navSelector = "#ld-form-navigation";
const groupsSelector = `${navSelector} .ld-index-group`;
const settle = (page) =>
  page.evaluate(
    () =>
      new Promise((done) =>
        requestAnimationFrame(() => requestAnimationFrame(done)),
      ),
  );
async function state(page) {
  return page.evaluate(() =>
    JSON.parse(document.getElementById("legaldesign-state").textContent),
  );
}
async function open(path, width, height) {
  const page = await browser.newPage({
    viewport: { width, height },
    hasTouch: width <= 760,
    acceptDownloads: true,
  });
  page.setDefaultTimeout(7000);
  await page.addInitScript(() =>
    Object.defineProperty(window, "showSaveFilePicker", {
      configurable: true,
      value: undefined,
    }),
  );
  page.on("pageerror", (error) =>
    errors.push({ path, message: error.message }),
  );
  await page.goto(pathToFileURL(path).href);
  await page.waitForFunction(
    () => document.documentElement.dataset.legaldesignReady === "true",
  );
  await settle(page);
  return page;
}
async function contents(page) {
  const reader = page.locator("#ld-page-reader");
  if (await reader.isVisible())
    await page
      .getByRole("button", { name: "Close page reader", exact: true })
      .click();
  const toggle = page.locator(`${navSelector} [data-index-toggle]`);
  if ((await toggle.getAttribute("aria-expanded")) !== "true")
    await toggle.click();
  await settle(page);
}
async function openGroup(page, index, keyboard = false) {
  await contents(page);
  const group = page.locator(groupsSelector).nth(index);
  if (!(await group.evaluate((node) => node.open))) {
    if (keyboard) await group.locator("summary").press("Enter");
    else await group.locator("summary").click();
  }
  await settle(page);
  assert.deepEqual(
    await page
      .locator(groupsSelector)
      .evaluateAll((nodes) => nodes.map((node) => node.open)),
    Array.from({ length: 6 }, (_, candidate) => candidate === index),
    "One chosen contents group opens",
  );
  return group;
}
function mappedGroups(data) {
  const targets = new Map(
    data.overview.topics.map((topic) => [topic.unitId, topic.targetSectionId]),
  );
  return data.overview.groups.map((group) =>
    group.topicUnitIds.map((id) =>
      data.composition.sections.findIndex(
        (section) => section.id === targets.get(id),
      ),
    ),
  );
}
async function assertCurrent(page, data, expected, label) {
  const info = await page.evaluate(() => ({
    active: [...document.querySelectorAll("[data-composition-section]")]
      .filter((node) => !node.hidden)
      .map((node) => node.dataset.compositionSection),
    current: [
      ...document.querySelectorAll('#ld-form-navigation [aria-current="true"]'),
    ].map((node) => Number(node.dataset.reportSection)),
    status: document.querySelector("[data-walkthrough-status]").textContent,
    open: [
      ...document.querySelectorAll("#ld-form-navigation .ld-index-group"),
    ].map((node) => node.open),
    location: JSON.parse(
      document.getElementById("legaldesign-state").textContent,
    ).review.location,
  }));
  assert.deepEqual(
    info.active,
    [data.composition.sections[expected].id],
    `${label}: actual destination`,
  );
  assert.deepEqual(
    info.current,
    [expected],
    `${label}: unique current button uses true section index`,
  );
  assert.equal(info.status, `${expected + 1} / 55`, `${label}: pager count`);
  assert.equal(
    info.location ?? 0,
    expected,
    `${label}: saved semantic location`,
  );
  const owner = mappedGroups(data).findIndex((group) =>
    group.includes(expected),
  );
  assert.deepEqual(
    info.open,
    Array.from({ length: 6 }, (_, index) => index === owner),
    `${label}: navigation opens current subject only`,
  );
}
async function inspectGroup(page, phone, label) {
  const info = await page.locator(navSelector).evaluate((nav) => {
    const rect = (node) => node.getBoundingClientRect().toJSON();
    const group = nav.querySelector(".ld-index-group[open]");
    const summary = group.querySelector("summary");
    return {
      viewport: [innerWidth, innerHeight],
      nav: rect(nav),
      summary: rect(summary),
      rows: [...group.querySelectorAll("[data-report-section]")].map(
        (node) => ({
          section: Number(node.dataset.reportSection),
          box: rect(node),
          fontSize: getComputedStyle(node).fontSize,
        }),
      ),
      list: rect(nav.querySelector("[data-index-list]")),
      pager: rect(nav.querySelector(".ld-index-pager")),
      horizontal: [
        document.documentElement.clientWidth,
        document.documentElement.scrollWidth,
      ],
    };
  });
  measurements.push({ label, ...info });
  assert.equal(info.rows.length, 9, `${label}: nine topic rows`);
  for (const row of info.rows) {
    assert(
      row.box.height >= (phone ? 44 : 27.5),
      `${label}: minimum target height`,
    );
    if (!phone) {
      assert(
        row.box.height <= 30,
        `${label}: compact desktop row ${row.box.height}px`,
      );
      assert.equal(row.fontSize, "12px", `${label}: fixed compact type`);
    }
  }
  if (phone)
    assert(info.summary.height >= 44, `${label}: phone summary target`);
  assert(
    info.horizontal[1] <= info.horizontal[0] + 1,
    `${label}: document horizontal overflow`,
  );
  assert(
    info.pager.bottom <= info.nav.bottom + 1,
    `${label}: pager contained in rail`,
  );
}
async function clickIndex(page, section) {
  await contents(page);
  await page
    .locator(`${navSelector} [data-report-section="${section}"]`)
    .click();
  await settle(page);
}
async function walk(path, kind, width, height) {
  const label = `${kind}-${width}`;
  const phone = width <= 760;
  const page = await open(path, width, height);
  try {
    const data = await state(page);
    const mapping = mappedGroups(data);
    assert.equal(data.composition.sections.length, 55);
    assert.equal(data.overview.topics.length, 54);
    await contents(page);
    assert.equal(await page.locator(groupsSelector).count(), 6);
    assert.deepEqual(
      await page.locator(`${groupsSelector} > summary`).allTextContents(),
      data.overview.groups.map((group) => group.label),
    );
    assert.deepEqual(
      await page
        .locator(groupsSelector)
        .evaluateAll((groups) =>
          groups.map((group) =>
            [...group.querySelectorAll("[data-report-section]")].map((button) =>
              Number(button.dataset.reportSection),
            ),
          ),
        ),
      mapping,
      `${label}: grouped DOM preserves nonnumeric topic order`,
    );
    assert.notDeepEqual(
      mapping.flat(),
      Array.from({ length: 54 }, (_, index) => index + 1),
    );
    await assertCurrent(
      page,
      data,
      kind === "client" ? 30 : 0,
      `${label}: initial`,
    );
    if (kind === "template")
      assert(!JSON.stringify(data.overview.groups).includes(sentinel));
    await clickIndex(page, 0);
    await assertCurrent(page, data, 0, `${label}: overview groups closed`);
    await contents(page);
    await page.screenshot({ path: join(out, `${label}-overview.png`) });
    for (let groupIndex = 0; groupIndex < 6; groupIndex++) {
      await openGroup(page, groupIndex, groupIndex % 2 === 1);
      await inspectGroup(page, phone, `${label}-group-${groupIndex}`);
      if (groupIndex === 0 || groupIndex === 5)
        await page.screenshot({
          path: join(out, `${label}-group-${groupIndex}.png`),
        });
      for (const destination of mapping[groupIndex]) {
        await openGroup(page, groupIndex);
        await clickIndex(page, destination);
        await assertCurrent(
          page,
          data,
          destination,
          `${label}: destination ${destination}`,
        );
        if (phone)
          assert.equal(
            await page
              .locator(`${navSelector} [data-index-toggle]`)
              .getAttribute("aria-expanded"),
            "false",
            `${label}: phone drawer closes after navigation`,
          );
        coverage.push({ kind, width, groupIndex, destination });
      }
    }
    // Open/close native keyboard controls; collapse is an independent reader
    // choice and must survive repaint/theme/resize until location changes.
    const currentGroup = mapping.findIndex((group) => group.includes(54));
    await openGroup(page, currentGroup);
    await clickIndex(page, 54);
    await contents(page);
    const currentSummary = page
      .locator(groupsSelector)
      .nth(currentGroup)
      .locator("summary");
    await currentSummary.press("Space");
    await settle(page);
    assert.equal(
      await page.locator(`${groupsSelector}[open]`).count(),
      0,
      `${label}: Space collapses`,
    );
    await page.locator("#theme-toggle").click();
    await settle(page);
    assert.equal(
      await page.locator(`${groupsSelector}[open]`).count(),
      0,
      `${label}: theme does not undo manual collapse`,
    );
    await page.setViewportSize({ width: width + 2, height });
    await page.setViewportSize({ width, height });
    await settle(page);
    assert.equal(
      await page.locator(`${groupsSelector}[open]`).count(),
      0,
      `${label}: resize does not undo manual collapse`,
    );
    await contents(page);
    await page.locator("[data-walkthrough-previous]").click();
    await settle(page);
    await assertCurrent(
      page,
      data,
      53,
      `${label}: Previous opens different current group`,
    );
    await contents(page);
    await page.locator("[data-walkthrough-next]").click();
    await settle(page);
    await assertCurrent(page, data, 54, `${label}: Next opens correct group`);
    await contents(page);
    await page.screenshot({ path: join(out, `${label}-dark-next.png`) });
    checks.push({ label, passed: true, destinations: 54 });
    console.log(
      `PASS ${label}: all 54 destinations, compact groups, keyboard, Next and collapse independence`,
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
async function download(page, selector, name) {
  const [file] = await Promise.all([
    page.waitForEvent("download", { timeout: 15000 }),
    page.locator(selector).click(),
  ]);
  assert.equal(await file.failure(), null);
  const downloaded = await file.path();
  assert(
    downloaded && existsSync(downloaded),
    "Actual browser download exists",
  );
  const target = join(out, name);
  copyFileSync(downloaded, target);
  return target;
}
try {
  for (const [width, height] of sizes)
    await attempt(`working-${width}`, () =>
      walk(fixture, "working", width, height),
    );
  await attempt("save-and-exports", async () => {
    const page = await open(fixture, 1440, 900);
    let saved;
    try {
      const data = await state(page);
      await openGroup(
        page,
        mappedGroups(data).findIndex((group) => group.includes(30)),
      );
      await clickIndex(page, 30);
      await assertCurrent(page, data, 30, "before Save");
      await page.locator("#mode-toggle").click();
      saved = await download(page, "#ld-save", "saved-working.html");
    } finally {
      await page.close();
    }
    const reopened = await open(saved, 1440, 900);
    try {
      await assertCurrent(
        reopened,
        await state(reopened),
        30,
        "Saved copy reopens at correct section/group",
      );
      assert.deepEqual(
        await reopened.locator(`${groupsSelector} > summary`).allTextContents(),
        plan.overview.groups.map((group) => group.label),
      );
      await reopened.reload();
      await settle(reopened);
      await assertCurrent(
        reopened,
        await state(reopened),
        30,
        "Saved copy reload preserves correct current state",
      );
      await reopened.screenshot({ path: join(out, "saved-current-30.png") });
      checks.push({ label: "save-reload", passed: true });
    } finally {
      await reopened.close();
    }
    for (const kind of ["client", "template"]) {
      const exportPage = await open(saved, 1440, 900);
      let exported;
      try {
        exported = await download(
          exportPage,
          kind === "client" ? "#export-html" : "#export-template",
          `${kind}.html`,
        );
      } finally {
        await exportPage.close();
      }
      assert.equal(
        readFileSync(exported, "utf8").includes(sentinel),
        kind === "client",
        `${kind}: no private template group labels anywhere`,
      );
      checks.push({ label: `${kind}-download-and-privacy`, passed: true });
      for (const [width, height] of sizes)
        await attempt(`${kind}-${width}`, () =>
          walk(exported, kind, width, height),
        );
    }
  });
  assert.deepEqual(errors, [], "No browser runtime errors");
  assert.equal(
    coverage.length,
    486,
    "All destinations in nine working/client/template viewport combinations",
  );
} catch (error) {
  failures.push({ label: "completion", error: error.stack || String(error) });
} finally {
  await browser.close();
  writeFileSync(
    join(out, "results.json"),
    JSON.stringify(
      { failures, errors, checks, coverage, measurements },
      null,
      2,
    ),
  );
  writeFileSync(
    join(out, "report.md"),
    [
      `# Grouped contents regression: ${failures.length ? "FAIL" : "PASS"}`,
      "",
      "Synthetic six-group, 54-topic, 55-page fixture. Group order deliberately differs from numeric page order. Built with the canonical shipping shell, without injected runtime or CSS.",
      "",
      `${coverage.length} real destination clicks across working, downloaded client and downloaded template copies at 1280×800, 1440×900 and 390×844. Runtime errors: ${errors.length}.`,
      "",
      "Checks: compact desktop rows; 44px phone targets; native disclosure keyboard/click; one-open groups; exact active destination and pager; overview defaults; independent manual collapse through theme/resize; Previous/Next group reveal; Save/reload and exported group-label privacy.",
      "",
      failures.length
        ? failures
            .map(({ label, error }) => `- ${label}: ${error.split("\n")[0]}`)
            .join("\n")
        : "All requested checks passed.",
      "",
      "Screenshots and exact measurements are beside this report; results.json records full coverage. All isolated headless browser contexts are closed. No server or user tabs were opened. Only the new regression test file was changed.",
      "",
    ].join("\n"),
  );
}
console.log(
  `${failures.length ? "FAIL" : "PASS"}: ${coverage.length} destination clicks; evidence ${out}`,
);
assert.equal(failures.length, 0, JSON.stringify(failures, null, 2));
