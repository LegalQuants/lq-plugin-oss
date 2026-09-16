import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { chromium, expect } from "@playwright/test";
import { checkSelectedExport } from "./export-selected.mjs";

const root = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../../..",
);
const out = await fs.mkdtemp(path.join(os.tmpdir(), "objection-review-state-"));
const python = path.join(root, ".venv/bin/python");
const script = path.join(
  root,
  "skills/litigation/document-discovery/scripts/objection_review.py",
);
const originalReview = path.join(
  root,
  "packages/document-discovery/fixtures/objection-review/inputs/review.json",
);
const source = path.join(out, "review.json");
execFileSync(python, [
  path.join(
    root,
    "packages/document-discovery/fixtures/prepare_source_fixture.py",
  ),
  "--review",
  originalReview,
  "--source",
  path.join(path.dirname(originalReview), "served-requests.md"),
  "--out",
  source,
]);
const html = path.join(out, "review.html");
execFileSync(python, [script, "render", "--review", source, "--out", html]);
const executablePath = [
  chromium.executablePath(),
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
].find(existsSync);
assert.ok(executablePath, "A test browser must be available.");
const browser = await chromium.launch({ headless: true, executablePath });
const page = await browser.newPage({ viewport: { width: 1360, height: 1000 } });
const errors = [],
  network = [];
page.on("pageerror", (error) => errors.push(error.message));
page.on("request", (request) => {
  if (/^https?:/.test(request.url())) network.push(request.url());
});
async function download(button, name) {
  const event = page.waitForEvent("download");
  await page.locator(button).click();
  const result = await event;
  const dest = path.join(out, name);
  await result.saveAs(dest);
  return { file: dest, data: JSON.parse(await fs.readFile(dest, "utf8")) };
}
async function resume(file) {
  await page.locator("#import").setInputFiles(file);
  await expect(page.locator("#message")).toContainText("restored");
}
try {
  await page.goto(pathToFileURL(html).href);
  const first = page.locator("#request-0"),
    second = page.locator("#request-1");
  const preview = second.locator(".wording-preview");
  assert.equal(await page.locator(".wording-for-word").count(), 16);
  const scope = second.locator('[data-entry="scope"]');
  await scope
    .getByRole("button", { name: "Unrelated scope", exact: true })
    .click();
  await second
    .getByRole("button", { name: "Edit wording", exact: true })
    .click();
  const libraryEdit =
    "A preserved request-specific qualification.\nA second line retained exactly.";
  await second
    .getByLabel("Wording to insert (edits apply to this request only)")
    .fill(libraryEdit);
  await expect(preview).toHaveText(libraryEdit);
  await second
    .getByRole("button", { name: "Done editing", exact: true })
    .click();
  await scope.getByRole("checkbox").uncheck();
  await expect(preview).toBeHidden();
  await first
    .getByRole("button", { name: "Add custom objection", exact: true })
    .click();
  const customText =
    "Custom objection retained after deselection — including its qualification.";
  await first
    .getByLabel("Wording to insert (edits apply to this request only)")
    .fill(customText);
  await first
    .getByRole("button", { name: "Done editing", exact: true })
    .click();
  const customTile = first.locator(".tile").filter({
    has: page.getByRole("button", { name: "Custom objection", exact: true }),
  });
  await customTile.getByRole("checkbox").uncheck();
  const saved = await download("#save", "deselected-progress.json");
  assert.equal(saved.data.format_version, 2);
  assert.equal(saved.data.rows[0].choices.length, 0);
  assert.equal(saved.data.rows[0].drafts[0].wording, customText);
  assert.equal(saved.data.rows[1].drafts[0].wording, libraryEdit);
  await page.reload();
  await resume(saved.file);
  await expect(customTile.getByRole("checkbox")).not.toBeChecked();
  await customTile.getByRole("checkbox").check();
  await expect(first.locator(".wording-preview")).toHaveText(customText);
  await scope.getByRole("checkbox").check();
  await expect(preview).toHaveText(libraryEdit);
  await first
    .getByRole("button", { name: "Custom objection", exact: true })
    .click();
  await first
    .getByRole("button", { name: "Edit wording", exact: true })
    .click();
  await first
    .getByLabel("Wording to insert (edits apply to this request only)")
    .fill("");
  const unfinished = await download("#save", "unfinished-progress.json");
  assert.equal(unfinished.data.rows[0].drafts[0].wording, "");
  await page.reload();
  await resume(unfinished.file);
  await first
    .getByRole("button", { name: "Mark reviewed", exact: true })
    .click();
  await expect(first.locator(".badge")).toHaveText(
    "Selected · needs completion",
  );
  await expect(page.locator("#message")).toContainText(
    "Complete the selected wording",
  );
  await first
    .locator(".tile")
    .filter({
      has: page.getByRole("button", { name: "Custom objection", exact: true }),
    })
    .getByRole("checkbox")
    .uncheck();
  await first
    .getByRole("button", { name: "Custom objection", exact: true })
    .click();
  await expect(first.locator(".request-wording")).toHaveText("");
  await first
    .getByRole("button", { name: "Mark reviewed", exact: true })
    .click();
  await expect(first.locator(".badge")).toHaveText("Reviewed · no objections");
  await second.locator(".other-library > summary").click();
  const work = second.locator('[data-entry="work-product"]');
  await work.getByRole("checkbox").check();
  await second
    .getByRole("button", { name: "Arrange wording", exact: true })
    .click();
  await second
    .locator(".order-list li")
    .first()
    .getByRole("button", { name: "Move down", exact: true })
    .click();
  const visible = await preview.innerText();
  assert.ok(visible.endsWith(libraryEdit));
  await second.getByRole("button", { name: "Add note", exact: true }).click();
  await second
    .getByLabel("Review notes — not included in Word")
    .fill("PRIVATE REVIEW NOTE NOT FOR WORD");
  await second
    .getByRole("button", { name: "Mark reviewed", exact: true })
    .click();
  await expect(second.locator(".badge")).toHaveText("Reviewed");
  await page
    .locator("#request-5")
    .getByRole("button", { name: "Needs input", exact: true })
    .click();
  const decisions = await download("#export", "decisions.json");
  assert.equal(
    decisions.data.rows[1].choices.map((choice) => choice.wording).join("\n\n"),
    visible,
  );
  assert.ok(decisions.data.rows[1].action.reviewed_content_sha256);
  const assemblyPath = path.join(out, "assembly.json");
  execFileSync(python, [
    script,
    "materialize",
    "--review",
    source,
    "--selections",
    decisions.file,
    "--out",
    assemblyPath,
  ]);
  const assembly = JSON.parse(await fs.readFile(assemblyPath, "utf8"));
  assert.equal(assembly.requests[1].objection_text, visible);
  assert.ok(
    !assembly.requests[1].objection_text.includes("PRIVATE REVIEW NOTE"),
  );
  assert.equal(assembly.requests[5].objection_text, "");
  assert.equal(assembly.requests[5].open_review, true);
  const needsFacts = page.locator("#request-5");
  await needsFacts
    .locator('[data-entry="backup"]')
    .getByRole("checkbox")
    .check();
  await needsFacts
    .getByRole("button", { name: "Mark reviewed", exact: true })
    .click();
  await expect(needsFacts.locator(".badge")).toHaveText("Reviewed");
  await needsFacts
    .getByRole("button", { name: "Needs input", exact: true })
    .click();
  const tampered = structuredClone(decisions.data);
  tampered.rows[1].choices[0].wording += " Added after review.";
  tampered.rows[1].choices[0].edited = true;
  const draft = tampered.rows[1].drafts.find(
    (item) => item.component_id === tampered.rows[1].choices[0].component_id,
  );
  Object.assign(draft, tampered.rows[1].choices[0]);
  const bad = path.join(out, "tampered.json");
  await fs.writeFile(bad, JSON.stringify(tampered));
  await page.locator("#import").setInputFiles(bad);
  await expect(page.locator("#message")).toContainText(
    "Wording changed after the recorded review",
  );
  await expect(preview).toHaveText(visible);
  await page
    .locator("#request-2")
    .getByRole("button", { name: "Add note", exact: true })
    .click();
  await page
    .locator("#request-2")
    .getByLabel("Review notes — not included in Word")
    .fill("Unsaved work to preserve before replacing this state.");
  await page.locator("#import").setInputFiles(saved.file);
  await expect(page.locator("#pending-import")).toBeVisible();
  await expect(preview).toHaveText(visible);
  await page.locator("#cancel-import").click();
  await expect(preview).toHaveText(visible);
  await page.screenshot({ path: path.join(out, "review-preview-desktop.png") });
  await page.setViewportSize({ width: 390, height: 844 });
  assert.equal(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
    true,
  );
  await second.scrollIntoViewIfNeeded();
  await page.screenshot({ path: path.join(out, "review-preview-narrow.png") });
  await page.setViewportSize({ width: 1360, height: 1000 });
  await second
    .getByRole("button", { name: "Undo review", exact: true })
    .click();
  await scope
    .getByRole("button", { name: "Unrelated scope", exact: true })
    .click();
  await second
    .getByRole("button", { name: "Edit wording", exact: true })
    .click();
  await page.evaluate(() => {
    const original = crypto.subtle.digest.bind(crypto.subtle);
    crypto.subtle.digest = async (...args) => {
      crypto.subtle.digest = original;
      await new Promise((resolve) => {
        globalThis.releaseReviewDigest = resolve;
      });
      return original(...args);
    };
  });
  await second
    .getByRole("button", { name: "Mark reviewed", exact: true })
    .click();
  await expect
    .poll(() => page.evaluate(() => typeof globalThis.releaseReviewDigest))
    .toBe("function");
  await second
    .getByLabel("Wording to insert (edits apply to this request only)")
    .fill("Changed during the review action.");
  await page.evaluate(() => globalThis.releaseReviewDigest());
  await expect(page.locator("#message")).toContainText(
    "Wording changed while recording review",
  );
  await expect(second.locator(".badge")).toHaveText(
    "Selected · included on export",
  );
  const legacy = structuredClone(decisions.data);
  legacy.format_version = 1;
  const reviewRecord = JSON.parse(await fs.readFile(source, "utf8"));
  legacy.review_sha256 = reviewRecord.legacy_review_sha256;
  for (const row of legacy.rows) {
    delete row.drafts;
    delete row.selected_ids;
    if (row.action) delete row.action.reviewed_content_sha256;
  }
  const legacyPath = path.join(out, "legacy-decisions.json");
  await fs.writeFile(legacyPath, JSON.stringify(legacy));
  await page.locator("#import").setInputFiles(legacyPath);
  await expect(page.locator("#pending-import")).toBeVisible();
  await page.locator("#confirm-import").click();
  await expect(page.locator("#message")).toContainText("as a legacy draft");
  await expect(second.locator(".badge")).toHaveText(
    "Selected · included on export",
  );
  await expect(preview).toHaveText(visible);
  const migrated = await download("#save", "legacy-as-progress.json");
  assert.ok(migrated.data.rows.every((row) => row.action === null));
  assert.ok(migrated.data.rows[1].legacy_action);
  await checkSelectedExport({ page, out, python, script, source, download });
  assert.deepEqual(errors, []);
  assert.deepEqual(network, []);
  console.log(
    JSON.stringify(
      {
        status: "passed",
        artifacts: out,
        browser: await browser.version(),
        checks: [
          "deselected drafts",
          "unfinished save",
          "preview/order/assembly equality",
          "reviewed-none",
          "partial assembly",
          "stale approval rejection",
          "approval snapshot race",
          "atomic import",
          "legacy migration",
          "390px layout",
          "selected export without individual review clicks",
          "visible mark all reviewed including no objections",
          "save never authorizes selection",
          "incomplete export and batch atomicity",
          "export, batch, and resume snapshot races",
        ],
      },
      null,
      2,
    ),
  );
} finally {
  await browser.close();
}
