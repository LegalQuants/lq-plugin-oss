import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { chromium } from "@playwright/test";

const repo = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const out = mkdtempSync(join(tmpdir(), "legaldesign-grouped-card-width-"));
const plan = JSON.parse(
  readFileSync(
    join(repo, "packages/legaldesign/templates/slide-brief.plan.json"),
    "utf8",
  ),
);
const topic = structuredClone(plan.units.find((u) => u.id === "topic-2"));
topic.id = "topic-3";
plan.units.push(topic);
const extra = structuredClone(plan.composition.sections[2]);
extra.id = "extra";
for (const id of extra.unitIds) {
  const unit = structuredClone(plan.units.find((u) => u.id === id));
  unit.id = `extra-${id}`;
  plan.units.push(unit);
}
extra.unitIds = extra.unitIds.map((id) => `extra-${id}`);
extra.layout?.placements.forEach((p) => {
  p.unitId = `extra-${p.unitId}`;
});
if (extra.issueLayout) {
  for (const name of ["findingUnitId", "implicationUnitId", "actionUnitId"])
    extra.issueLayout[name] = `extra-${extra.issueLayout[name]}`;
  extra.issueLayout.supportUnitIds = extra.issueLayout.supportUnitIds.map(
    (id) => `extra-${id}`,
  );
}
plan.composition.sections.push(extra);
plan.composition.sections[0].unitIds.push(topic.id);
plan.composition.sections[0].layout.placements.push({
  unitId: topic.id,
  row: 5,
  column: 1,
  span: 6,
});
plan.overview.topics.push({ unitId: topic.id, targetSectionId: "extra" });
plan.overview.groups = [
  { label: "Main topics", topicUnitIds: ["topic-1", "topic-2"] },
  { label: "Additional topics", topicUnitIds: ["topic-3"] },
];
plan.composition.sections[0].layout.placements
  .filter((placement) => placement.unitId.startsWith("topic-"))
  .forEach((placement, index) => {
    Object.assign(placement, { row: 4 + index, column: 1, span: 12 });
  });
const planPath = join(out, "plan.json"),
  fixture = join(out, "working.html");
writeFileSync(planPath, JSON.stringify(plan));
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
    fixture,
    "--artifact-id",
    "grouped-width-regression",
  ],
  { cwd: repo, encoding: "utf8" },
);
assert.equal(build.status, 0, build.stdout + build.stderr);
let html = readFileSync(fixture, "utf8");
for (const [tag, id, source] of [
  [
    "style",
    "ld-tokens",
    process.env.LEGALDESIGN_WIDTH_TOKENS ||
      join(repo, "packages/legaldesign/runtime/tokens.css"),
  ],
  [
    "script",
    "ld-runtime",
    join(repo, "packages/legaldesign/runtime/runtime.js"),
  ],
]) {
  const pattern = new RegExp(`(<${tag} id="${id}">)[\\s\\S]*?(<\\/${tag}>)`);
  assert(pattern.test(html));
  html = html.replace(
    pattern,
    (_, start, end) => start + readFileSync(source, "utf8") + end,
  );
}
writeFileSync(fixture, html);
const browser = await chromium.launch({
  headless: true,
  executablePath: [
    chromium.executablePath(),
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  ].find(existsSync),
});
const measured = [],
  faults = [];
async function settle(page) {
  await page.evaluate(
    () =>
      new Promise((resolve) =>
        requestAnimationFrame(() => requestAnimationFrame(resolve)),
      ),
  );
}
async function open(file, width, height) {
  const page = await browser.newPage({
    viewport: { width, height },
    acceptDownloads: true,
  });
  await page.addInitScript(() =>
    Object.defineProperty(window, "showSaveFilePicker", {
      value: undefined,
      configurable: true,
    }),
  );
  page.on("pageerror", (error) => faults.push(error.message));
  await page.goto(pathToFileURL(file).href);
  await page.waitForFunction(
    () => document.documentElement.dataset.legaldesignReady === "true",
  );
  return page;
}
async function widths(page, label, explicit = null) {
  await settle(page);
  const cards = await page
    .locator(".ld-overview-group[open] .ld-overview-topic-grid > section")
    .evaluateAll((nodes) =>
      nodes.map((n) => ({
        id: n.getAttribute("data-unit"),
        width: n.getBoundingClientRect().width,
        track: parseFloat(
          getComputedStyle(n.parentElement).gridTemplateColumns,
        ),
        justify: getComputedStyle(n).justifySelf,
        inlineWidth: n.style.width,
        textOverflow: [...n.querySelectorAll("h2,p")].some(
          (t) => t.scrollWidth > t.clientWidth + 1,
        ),
      })),
    );
  measured.push({ label, cards });
  assert(cards.length, `${label}: group has visible cards`);
  for (const card of cards) {
    const expected =
      explicit && card.id === explicit.id ? explicit.width : card.track;
    assert(
      Math.abs(card.width - expected) < 1.5,
      `${label}: ${card.id} width${card.width} vs track/override${expected}; justify=${card.justify}`,
    );
    assert(!card.textOverflow, `${label}: card text does not overflow`);
  }
}
async function traverse(page, label, explicit = null) {
  const groups = page.locator(".ld-overview-groups > details");
  for (let i = 0; i < (await groups.count()); i++) {
    const group = groups.nth(i),
      summary = group.locator(":scope > summary");
    if (!(await group.evaluate((n) => n.open))) await summary.click();
    await widths(page, `${label}-group${i}`, explicit);
    await summary.click();
    assert(!(await group.evaluate((n) => n.open)));
    await summary.click();
    await widths(page, `${label}-group${i}-reopen`, explicit);
  }
}
async function download(page, selector, name) {
  const [result] = await Promise.all([
    page.waitForEvent("download"),
    page.locator(selector).click(),
  ]);
  assert.equal(await result.failure(), null);
  const path = join(out, name);
  await result.saveAs(path);
  return path;
}
try {
  for (const [width, height] of [
    [1440, 1000],
    [1800, 1000],
    [1920, 1080],
    [2560, 1440],
  ]) {
    const page = await open(fixture, width, height);
    for (const theme of ["light", "dark"]) {
      if ((await page.locator("html").getAttribute("data-theme")) !== theme)
        await page.locator("#theme-toggle").click();
      await page.screenshot({ path: join(out, `cold-${width}-${theme}.png`) });
      await traverse(page, `cold-${width}-${theme}`);
    }
    for (const resize of [
      [1440, 1000],
      [2560, 1440],
      [1800, 1000],
    ]) {
      await page.setViewportSize({ width: resize[0], height: resize[1] });
      await traverse(page, `resize-${width}-to-${resize[0]}`);
    }
    await page.close();
  }
  const edit = await open(fixture, 2560, 1440);
  await edit.locator("#mode-toggle").click();
  const card = edit.locator('[data-unit="topic-1"]');
  await card.click({ position: { x: 4, y: 4 } });
  const before = await card.boundingBox();
  const handle = await edit
    .locator('.ld-handle[data-handle="e"]')
    .boundingBox();
  assert(handle, "actual card resize handle available");
  await edit.mouse.move(
    handle.x + handle.width / 2,
    handle.y + handle.height / 2,
  );
  await edit.mouse.down();
  await edit.mouse.move(
    handle.x + handle.width / 2 - 60,
    handle.y + handle.height / 2,
    { steps: 12 },
  );
  await edit.mouse.up();
  const after = await card.boundingBox();
  assert(
    Math.abs(after.width - before.width + 60) < 2,
    "explicit user resize actually changed width",
  );
  const explicit = { id: "topic-1", width: after.width };
  const saved = await download(edit, "#ld-save", "saved.html");
  await edit.close();
  const copies = [["saved", saved]];
  for (const [type, selector] of [
    ["client", "#export-html"],
    ["template", "#export-template"],
  ]) {
    const page = await open(saved, 2560, 1440);
    if ((await page.locator("html").getAttribute("data-editing")) === "true")
      await page.locator("#mode-toggle").click();
    copies.push([type, await download(page, selector, `${type}.html`)]);
    await page.close();
  }
  for (const [type, file] of copies) {
    const page = await open(file, 2560, 1440);
    if (
      (await page
        .locator("#mode-toggle")
        .getAttribute("aria-pressed")
        .catch(() => "false")) === "true"
    )
      await page.locator("#mode-toggle").click();
    const first = page
      .locator(".ld-overview-group")
      .first()
      .locator(".ld-overview-topic-grid > section")
      .first();
    explicit.id = await first.getAttribute("data-unit");
    await traverse(page, `reopened-${type}`, explicit);
    await page.setViewportSize({ width: 1800, height: 1000 });
    await traverse(page, `reopened-${type}-resized`, explicit);
    await page.screenshot({ path: join(out, `reopened-${type}.png`) });
    await page.close();
  }
  assert.deepEqual(faults, []);
  console.log(
    `PASS: ${measured.length} grouped-card width states, cold wide layouts, expand/collapse, resizing, explicit editor geometry and Save/client/template reopen. ${out}`,
  );
} finally {
  writeFileSync(
    join(out, "measurements.json"),
    JSON.stringify(measured, null, 2),
  );
  await browser.close();
  console.log(`Grouped-card evidence: ${out}`);
}
