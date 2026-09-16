import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { chromium, expect } from "@playwright/test";

const root = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../../..",
);
const out = await fs.mkdtemp(
  path.join(os.tmpdir(), "discovery-compact-choices-"),
);
const python = path.join(root, ".venv/bin/python");
const scripts = path.join(root, "skills/litigation/document-discovery/scripts");
const reviewPath = path.join(out, "review.json");
const original = path.join(
  root,
  "packages/document-discovery/fixtures/objection-review/inputs/review.json",
);
execFileSync(python, [
  path.join(
    root,
    "packages/document-discovery/fixtures/prepare_source_fixture.py",
  ),
  "--review",
  original,
  "--source",
  path.join(path.dirname(original), "served-requests.md"),
  "--out",
  reviewPath,
]);
const review = JSON.parse(await fs.readFile(reviewPath, "utf8"));
// Mechanical regression data only: no generated legal propositions or attorney approvals.
review.id = "compact-choice-regression";
review.title = "Synthetic interface regression";
review.library.entries = Array.from({ length: 48 }, (_, i) => ({
  id: `ground-${String(i + 1).padStart(2, "0")}`,
  family: `ground-type-${i + 1}`,
  label: `Ground ${i + 1}`,
  variant: "Mechanical fixture variant",
  wording: `Synthetic wording for ground ${i + 1}.`,
  fields: {},
  guidance: "Mechanical fixture only.",
  conditions: [],
  exclusions: [],
  sources: [{ source_id: "synthetic-regression", locator: `Item ${i + 1}` }],
  status: "approved",
  approval: { record: "Simulated development fixture; no attorney approval." },
}));
review.requests.forEach((r, i) => {
  r.suggestions = i
    ? []
    : [1, 2].map((n) => ({
        entry_id: `ground-0${n}`,
        params: {},
        rationale: "Synthetic suggestion for interface coverage.",
        basis: ["Mechanical fixture"],
        missing: [],
        preselected: n === 1,
      }));
});
await fs.writeFile(reviewPath, JSON.stringify(review));
const html = path.join(out, "review.html");
execFileSync(python, [
  path.join(scripts, "objection_review.py"),
  "render",
  "--review",
  reviewPath,
  "--out",
  html,
]);
const catalogPath = path.join(out, "catalog.json"),
  catalogHtml = path.join(out, "catalog.html");
execFileSync(python, [
  "-c",
  `
import importlib.util,json,pathlib,sys
spec=importlib.util.spec_from_file_location('curation_fixture',sys.argv[1]);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
c=m.catalog.__wrapped__(); c['passages'][0]['original']+=' Long source excerpt.'*120;c['passages'][0]['context']='Lengthy retained context. '*120
pathlib.Path(sys.argv[2]).write_text(json.dumps(c))
`,
  path.join(
    root,
    "packages/skill-tests/tests/document_discovery/test_objection_library.py",
  ),
  catalogPath,
]);
execFileSync(python, [
  path.join(scripts, "objection_library.py"),
  "render",
  "--catalog",
  catalogPath,
  "--out",
  catalogHtml,
]);
const executablePath =
  process.env.OBJECTION_REVIEW_BROWSER_EXECUTABLE ||
  [
    chromium.executablePath(),
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  ].find(existsSync);
assert.ok(executablePath, "A test browser is required.");
const browser = await chromium.launch({ headless: true, executablePath });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const errors = [],
  network = [];
page.on("pageerror", (error) => errors.push(error.message));
page.on("request", (request) => {
  if (/^https?:/.test(request.url())) network.push(request.url());
});
async function download(selector, name) {
  const event = page.waitForEvent("download");
  await page.locator(selector).click();
  const result = await event,
    file = path.join(out, name);
  await result.saveAs(file);
  return { file, data: JSON.parse(await fs.readFile(file, "utf8")) };
}
async function before(a, b) {
  assert.ok(
    await a.evaluate(
      (node, target) =>
        Boolean(
          node.compareDocumentPosition(document.querySelector(target)) &
            Node.DOCUMENT_POSITION_FOLLOWING,
        ),
      b,
    ),
    `${await a.getAttribute("class")} must precede ${b}`,
  );
}
try {
  await page.goto(pathToFileURL(html).href);
  const request = page.locator("#request-0");
  await expect(request.locator(".main-choices .tile")).toHaveCount(2);
  await expect(request.locator(".other-choices .tile")).toHaveCount(46);
  await expect(request.locator(".other-library")).not.toHaveAttribute(
    "open",
    "",
  );
  await before(request.locator(".review-actions"), "#request-0 .main-choices");
  await page.screenshot({ path: path.join(out, "review-initial.png") });
  const first = request.locator('[data-entry="ground-01"]');
  const second = request.locator('[data-entry="ground-02"]');
  await second.getByRole("button", { name: "Ground 2", exact: true }).click();
  await expect(second.getByRole("checkbox")).not.toBeChecked();
  await expect(second).toHaveClass(/inspecting/);
  await expect(request.locator(".badge")).toHaveText(
    "Selected · included on export",
  );
  await before(request.locator(".detail-panel"), "#request-0 .main-choices");
  await before(
    request.locator(".request-wording"),
    "#request-0 .library-comparison",
  );
  await expect(request.locator(".request-wording")).toHaveText(
    "Synthetic wording for ground 2.",
  );
  await request.locator(".library-comparison > summary").click();
  await expect(request.locator(".library-wording")).toBeVisible();
  await request.locator(".detail-inclusion input").check();
  await expect(request.locator(".wording-preview")).toHaveText(
    "Synthetic wording for ground 1.\n\nSynthetic wording for ground 2.",
  );
  await request
    .getByRole("button", { name: "Arrange wording", exact: true })
    .click();
  await request
    .locator(".order-list li")
    .nth(1)
    .getByRole("button", { name: "Move up", exact: true })
    .click();
  await expect(request.locator(".wording-preview")).toHaveText(
    "Synthetic wording for ground 2.\n\nSynthetic wording for ground 1.",
  );
  await expect(request.locator(".main-choices .tile")).toHaveCount(2);
  assert.deepEqual(
    await request
      .locator(".main-choices .tile")
      .evaluateAll((xs) => xs.map((x) => x.dataset.entry)),
    ["ground-01", "ground-02"],
  );
  // Keyboard focus, inspection, selection and attorney review remain separate states.
  await first.getByRole("button", { name: "Ground 1", exact: true }).focus();
  await page.keyboard.press("Tab");
  await page.keyboard.press("Shift+Tab");
  assert.equal(
    await first
      .getByRole("button", { name: "Ground 1", exact: true })
      .evaluate((node) => getComputedStyle(node).outlineStyle),
    "dashed",
  );
  await expect(first).not.toHaveClass(/inspecting/);
  await request.locator(".other-library > summary").click();
  const far = request.locator('[data-entry="ground-48"]');
  await far.getByRole("button", { name: "Ground 48", exact: true }).click();
  await expect(request.locator(".request-wording")).toHaveText(
    "Synthetic wording for ground 48.",
  );
  await before(request.locator(".detail-panel"), "#request-0 .other-choices");
  await request.locator(".detail-inclusion input").check();
  await expect(
    request.locator('.main-choices [data-entry="ground-48"]'),
  ).toBeVisible();
  await request
    .getByRole("button", { name: "Edit wording", exact: true })
    .click();
  const edit = "Edited synthetic ground 48 — qualification retained.";
  await request
    .getByLabel("Wording to insert (edits apply to this request only)")
    .fill(edit);
  await request
    .getByRole("button", { name: "Done editing", exact: true })
    .click();
  await request.locator(".detail-inclusion input").uncheck();
  await request
    .getByRole("button", { name: "Add custom objection", exact: true })
    .click();
  const customWording = "Custom synthetic draft retained while unselected.";
  await request
    .getByLabel("Wording to insert (edits apply to this request only)")
    .fill(customWording);
  await request
    .getByRole("button", { name: "Done editing", exact: true })
    .click();
  const customTile = request.locator(".main-choices .tile").filter({
    has: page.getByRole("button", { name: "Custom objection", exact: true }),
  });
  await customTile.getByRole("checkbox").uncheck();
  await expect(customTile).toBeVisible();
  const saved = await download("#save", "progress.json");
  assert.equal(
    saved.data.rows[0].drafts.find((c) => c.entry_id === null).wording,
    customWording,
  );
  assert.equal(
    saved.data.rows[0].drafts.find((c) => c.entry_id === "ground-48").wording,
    edit,
  );
  assert.ok(
    !saved.data.rows[0].choices.some((c) => c.entry_id === "ground-48"),
  );
  await page.reload();
  await page.locator("#import").setInputFiles(saved.file);
  await expect(page.locator("#message")).toContainText("restored");
  await expect(customTile).toBeVisible();
  await expect(customTile.getByRole("checkbox")).not.toBeChecked();
  await request.locator(".other-library > summary").click();
  await far.getByRole("button", { name: "Ground 48", exact: true }).click();
  await expect(request.locator(".request-wording")).toHaveText(edit);
  await request.locator(".detail-inclusion input").check();
  await request
    .getByRole("button", { name: "Mark reviewed", exact: true })
    .click();
  const exported = await download("#export", "assembly-decisions.json");
  execFileSync(python, [
    path.join(scripts, "objection_review.py"),
    "check-selections",
    "--review",
    reviewPath,
    "--selections",
    exported.file,
  ]);
  assert.equal(exported.data.rows[0].action.kind, "individual");
  assert.equal(
    await request.locator(".wording-preview").innerText(),
    exported.data.rows[0].choices.map((c) => c.wording).join("\n\n"),
  );
  await page.screenshot({ path: path.join(out, "review-desktop.png") });
  for (const width of [390, 320]) {
    await page.setViewportSize({ width, height: 844 });
    assert.equal(
      await page.evaluate(
        () => document.documentElement.scrollWidth > innerWidth,
      ),
      false,
    );
    await before(
      request.locator(".review-actions"),
      "#request-0 .main-choices",
    );
    assert.equal(
      await request.evaluate((node) =>
        [...node.querySelectorAll("section,div,details")].some(
          (x) =>
            ["auto", "scroll"].includes(getComputedStyle(x).overflowY) &&
            x.scrollHeight > x.clientHeight,
        ),
      ),
      false,
    );
  }
  await request.locator(".review-actions").scrollIntoViewIfNeeded();
  await page.screenshot({ path: path.join(out, "review-narrow.png") });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto(pathToFileURL(catalogHtml).href);
  await page.locator("#candidate-0").click();
  const candidate = page.locator("#candidate-panel-0");
  await expect(
    candidate.getByRole("button", { name: "Approve for reuse", exact: true }),
  ).toBeVisible();
  await before(
    candidate.locator(".decision-actions"),
    "#candidate-panel-0 .source-evidence",
  );
  await before(
    candidate.locator(".decision-actions"),
    "#candidate-panel-0 .candidate-editor",
  );
  await before(candidate, ".family .tile-grid");
  assert.ok(
    (await candidate.locator(".decision-actions").boundingBox()).y <
      (await candidate.locator(".source-evidence").boundingBox()).y,
  );
  await candidate.getByRole("button", { name: "Defer", exact: true }).click();
  await expect(candidate.locator(".decision-status")).toContainText("Deferred");
  await page.screenshot({ path: path.join(out, "curation-actions.png") });
  assert.deepEqual(errors, []);
  assert.deepEqual(network, []);
  console.log(
    JSON.stringify(
      {
        result: "PASS",
        browser: browser.version(),
        out,
        libraryEntries: 48,
        simulation: "Mechanical regression only; no attorney approval",
        checks: [
          "compact relevant palette",
          "stable library order",
          "actions before grids",
          "wording before source",
          "separate selection/inspection/focus",
          "saved deselected edit",
          "preview/export equality",
          "320/390px overflow and no nested scrolling",
        ],
      },
      null,
      2,
    ),
  );
} finally {
  await browser.close();
}
