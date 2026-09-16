import assert from "node:assert/strict";
import { execFileSync, spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { chromium, expect } from "@playwright/test";
import Ajv2020 from "ajv/dist/2020.js";

const root = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../../..",
);
const temp = await fs.mkdtemp(
  path.join(os.tmpdir(), "objection-library-browser-"),
);
const python = path.join(root, ".venv/bin/python");
const scripts = path.join(root, "skills/litigation/document-discovery/scripts");
const script = path.join(scripts, "objection_library.py");
const catalogPath = path.join(temp, "catalog.json");
const html = path.join(temp, "catalog.html");
// Reuse the small contract fixture, not the independent raw-source model output.
execFileSync(python, [
  "-c",
  `
import importlib.util, json, pathlib, sys
spec=importlib.util.spec_from_file_location('curation_test',sys.argv[1])
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
catalog=module.catalog.__wrapped__()
catalog['passages'][0]['original'] += ' Literal source text: </script><img src=x onerror=alert(1)>'
catalog['proposals']['items'][1]['after']['variant']='Alternative with additional qualification'
pathlib.Path(sys.argv[2]).write_text(json.dumps(catalog))
`,
  path.join(
    root,
    "packages/skill-tests/tests/document_discovery/test_objection_library.py",
  ),
  catalogPath,
]);
const catalog = JSON.parse(await fs.readFile(catalogPath, "utf8"));
const schemaPath = path.join(
  root,
  "skills/litigation/document-discovery/schemas",
);
const ajv = new Ajv2020({ strict: false });
ajv.addSchema(
  JSON.parse(
    await fs.readFile(
      path.join(schemaPath, "objection-records.schema.json"),
      "utf8",
    ),
  ),
  "objection-records.schema.json",
);
const validate = ajv.compile(
  JSON.parse(
    await fs.readFile(
      path.join(schemaPath, "objection-library-curation.schema.json"),
      "utf8",
    ),
  ),
);
assert.ok(validate(catalog), JSON.stringify(validate.errors));
execFileSync(python, [
  script,
  "render",
  "--catalog",
  catalogPath,
  "--out",
  html,
]);
const executablePath =
  process.env.OBJECTION_REVIEW_BROWSER_EXECUTABLE ||
  [
    chromium.executablePath(),
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  ].find(existsSync);
assert.ok(executablePath, "A Chromium test browser is required.");
const browser = await chromium.launch({ executablePath, headless: true });
const errors = [];
const network = [];
try {
  const page = await browser.newPage({
    viewport: { width: 1360, height: 1000 },
  });
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("request", (request) => {
    if (/^https?:/.test(request.url())) network.push(request.url());
  });
  await page.goto(pathToFileURL(html).href);
  assert.equal(await page.locator(".candidate-tile").count(), 3);
  assert.equal(await page.locator("select").count(), 0);
  assert.equal(await page.locator("textarea").count(), 0);
  assert.match(await page.locator("#progress").innerText(), /0 approved/);
  await page.screenshot({ path: path.join(temp, "initial-desktop.png") });
  const initialOrder = await page
    .locator(".candidate-tile")
    .evaluateAll((tiles) => tiles.map((tile) => tile.id));
  await page.locator("#candidate-0").focus();
  await page.keyboard.press("Enter");
  let panel = page.locator("#candidate-panel-0");
  await expect(page.locator("#candidate-0")).toHaveAttribute(
    "aria-expanded",
    "true",
  );
  assert.match(
    await panel.locator(".source-original").innerText(),
    /<\/script><img/,
  );
  assert.equal(await page.locator("img").count(), 0);
  assert.match(
    await panel.locator(".proposed-wording").innerText(),
    /\[Identify the unrelated subject\]/,
  );
  assert.match(await page.locator("#progress").innerText(), /0 approved/);
  await page.screenshot({ path: path.join(temp, "source-comparison.png") });
  await panel.locator(".curation-note summary").click();
  await panel
    .getByLabel("Decision note", { exact: true })
    .fill("Synthetic browser regression decision; not attorney approval.");
  await panel
    .getByRole("button", { name: "Approve for reuse", exact: true })
    .click();
  await expect(page.locator("#progress")).toContainText("1 approved");
  await panel
    .getByRole("button", { name: "Edit proposed entry", exact: true })
    .click();
  const editedWording = `${catalog.proposals.items[0].after.wording} Only that portion is disputed.`;
  await panel
    .getByLabel("Proposed reusable wording", { exact: true })
    .fill(editedWording);
  await expect(page.locator("#progress")).toContainText("0 approved");
  await panel.locator(".candidate-editor details summary").click();
  await panel
    .getByLabel("When to use this wording", { exact: true })
    .fill(
      "Identify the disputed portion. Retain unrelated-source variants separately.",
    );
  await panel
    .getByRole("button", { name: "Finish editing", exact: true })
    .click();
  await panel.locator(".usage-guidance summary").click();
  await expect(panel.locator(".usage-guidance")).toContainText(
    "Retain unrelated-source variants separately.",
  );
  await panel
    .getByRole("button", { name: "Approve for reuse", exact: true })
    .click();
  await expect(page.locator("#progress")).toContainText("1 approved");
  await panel.getByRole("button", { name: "Close", exact: true }).click();
  await expect(page.locator("#candidate-0")).toBeFocused();
  await page.locator("#candidate-1").click();
  panel = page.locator("#candidate-panel-1");
  await panel
    .getByRole("button", { name: "Edit proposed entry", exact: true })
    .click();
  await panel
    .getByLabel("Proposed reusable wording", { exact: true })
    .fill("A draft with {{new_field}}.");
  await expect(
    panel.getByRole("button", { name: "Approve for reuse", exact: true }),
  ).toBeDisabled();
  async function download(selector, name) {
    const pending = page.waitForEvent("download");
    await page.locator(selector).click();
    const output = path.join(temp, name);
    await (await pending).saveAs(output);
    return output;
  }
  await page.locator("#tools > summary").click();
  const progressPath = await download("#save", "incomplete-progress.json");
  const progress = JSON.parse(await fs.readFile(progressPath, "utf8"));
  assert.ok(validate(progress), JSON.stringify(validate.errors));
  execFileSync(python, [
    script,
    "check-decisions",
    "--catalog",
    catalogPath,
    "--decisions",
    progressPath,
  ]);
  const invalidApply = spawnSync(
    python,
    [
      script,
      "reconcile",
      "--catalog",
      catalogPath,
      "--decisions",
      progressPath,
      "--out",
      path.join(temp, "must-not-apply.json"),
    ],
    { encoding: "utf8" },
  );
  assert.equal(invalidApply.status, 2);
  assert.match(invalidApply.stderr, /Progress/);
  assert.ok(!existsSync(path.join(temp, "must-not-apply.json")));
  await page.locator("#tools > summary").click();
  await panel
    .getByRole("button", { name: "Restore proposed entry", exact: true })
    .click();
  panel = page.locator("#candidate-panel-1");
  await panel.getByRole("button", { name: "Defer", exact: true }).click();
  await expect(page.locator("#candidate-1")).toContainText("Deferred");
  await page.locator("#candidate-2").click();
  const other = page.locator("#candidate-panel-2");
  assert.equal(
    await other
      .getByRole("button", { name: "Approve for reuse", exact: true })
      .count(),
    0,
  );
  await other.getByRole("button", { name: "Exclude", exact: true }).click();
  await expect(page.locator("#candidate-2")).toContainText("Excluded");
  const decisionsPath = await download("#export", "decisions.json");
  const decisions = JSON.parse(await fs.readFile(decisionsPath, "utf8"));
  assert.ok(validate(decisions), JSON.stringify(validate.errors));
  assert.equal(decisions.rows[0].after.wording, editedWording);
  assert.deepEqual(
    decisions.rows.map((row) => row.decision),
    ["accept", "defer", "reject"],
  );
  const proposalsPath = path.join(temp, "decided-proposals.json");
  const libraryPath = path.join(temp, "library-v1.json");
  const updatedPath = path.join(temp, "library-v2.json");
  await fs.writeFile(libraryPath, JSON.stringify(catalog.library));
  execFileSync(python, [
    script,
    "reconcile",
    "--catalog",
    catalogPath,
    "--decisions",
    decisionsPath,
    "--out",
    proposalsPath,
  ]);
  execFileSync(python, [
    script,
    "apply",
    "--catalog",
    catalogPath,
    "--decisions",
    decisionsPath,
    "--out",
    updatedPath,
  ]);
  const updated = JSON.parse(await fs.readFile(updatedPath, "utf8"));
  assert.equal(updated.entries.length, 1);
  assert.equal(updated.entries[0].wording, editedWording);
  const continuedPath = path.join(temp, "remaining-catalog.json");
  execFileSync(python, [
    script,
    "continue",
    "--catalog",
    catalogPath,
    "--decisions",
    decisionsPath,
    "--library",
    updatedPath,
    "--out",
    continuedPath,
  ]);
  const continued = JSON.parse(await fs.readFile(continuedPath, "utf8"));
  assert.ok(validate(continued), JSON.stringify(validate.errors));
  assert.equal(continued.proposals.items.length, 1);
  assert.equal(continued.proposals.items[0].id, catalog.proposals.items[1].id);
  assert.equal(continued.proposals.items[0].decision, "pending");
  await page.reload();
  await page.locator("#tools > summary").click();
  await page.locator("#import").setInputFiles(decisionsPath);
  await expect(page.locator("#message")).toContainText("restored");
  assert.match(await page.locator("#progress").innerText(), /1 approved/);
  const wrongPath = path.join(temp, "wrong.json");
  for (const change of [
    (data) => {
      data.catalog_sha256 = "0".repeat(64);
    },
    (data) => {
      data.rows[0].after.wording += " Unreviewed change.";
    },
    (data) => {
      data.rows[1].decision = "accept";
    },
    (data) => {
      data.rows[1].decision = "accept";
      data.rows[1].action.decision = "accept";
    },
    (data) => {
      data.rows[0].after.sources[0].source_id = "wrong-source";
    },
    (data) => {
      data.rows.reverse();
    },
  ]) {
    const wrong = structuredClone(decisions);
    change(wrong);
    await fs.writeFile(wrongPath, JSON.stringify(wrong));
    await page.locator("#import").setInputFiles(wrongPath);
    await expect(page.locator("#message")).toContainText("Could not restore");
    assert.match(await page.locator("#progress").innerText(), /1 approved/);
  }
  const afterWrong = await download("#export", "after-wrong-import.json");
  assert.deepEqual(
    JSON.parse(await fs.readFile(afterWrong, "utf8")).rows,
    decisions.rows,
  );
  const legacy = structuredClone(decisions);
  legacy.format_version = 1;
  for (const row of legacy.rows) {
    if (row.action) {
      row.action = {
        kind: "individual",
        at: row.action.at,
        after_sha256: "a".repeat(64),
      };
    }
  }
  const legacyPath = path.join(temp, "legacy-decisions.json");
  await fs.writeFile(legacyPath, JSON.stringify(legacy));
  await page.locator("#import").setInputFiles(legacyPath);
  await expect(page.locator("#message")).toContainText(
    "Legacy drafts restored",
  );
  await expect(page.locator("#progress")).toContainText("0 approved");
  const migratedPath = await download("#export", "legacy-as-current.json");
  const migrated = JSON.parse(await fs.readFile(migratedPath, "utf8"));
  assert.ok(validate(migrated), JSON.stringify(validate.errors));
  assert.ok(
    migrated.rows.every(
      (row) => row.decision === "pending" && row.action === null,
    ),
  );
  assert.deepEqual(
    migrated.rows.map((row) => row.after),
    decisions.rows.map((row) => row.after),
  );
  assert.deepEqual(
    migrated.rows.map((row) => row.legacy.decision),
    ["accept", "defer", "reject"],
  );
  const noApproval = spawnSync(
    python,
    [
      script,
      "apply",
      "--catalog",
      catalogPath,
      "--decisions",
      migratedPath,
      "--out",
      path.join(temp, "legacy-must-not-apply.json"),
    ],
    { encoding: "utf8" },
  );
  assert.equal(noApproval.status, 2);
  assert.match(noApproval.stderr, /No accepted/);
  await page.locator("#import").setInputFiles(decisionsPath);
  await expect(page.locator("#message")).toContainText(
    "Saved decisions restored",
  );
  assert.deepEqual(
    await page
      .locator(".candidate-tile")
      .evaluateAll((tiles) => tiles.map((tile) => tile.id)),
    initialOrder,
  );
  await page.locator("#tools > summary").click();
  await page.locator("#candidate-0").click();
  await page.locator("#theme-toggle").click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.screenshot({ path: path.join(temp, "dark.png") });
  await page.locator("#theme-toggle").click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  for (const width of [390, 320]) {
    await page.setViewportSize({ width, height: 900 });
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth > window.innerWidth,
    );
    assert.equal(overflow, false, `No horizontal overflow at ${width}px`);
    await page.screenshot({
      path: path.join(temp, `mobile-${width}.png`),
      fullPage: true,
    });
  }
  // A replacement and a new variant can share visible wording while having
  // different persistence effects. Show that effect and apply either order.
  const feedback = structuredClone(catalog);
  feedback.id = "feedback-catalog";
  feedback.library = updated;
  feedback.proposals.id = "feedback-batch";
  for (const [index, classification] of [
    "replacement",
    "new_variant",
  ].entries()) {
    const item = feedback.proposals.items[index];
    item.classification = classification;
    item.target_id = updated.entries[0].id;
    item.before = structuredClone(updated.entries[0]);
    item.after = structuredClone(updated.entries[0]);
    item.after.wording += " A further reviewed qualification.";
    if (index === 1) item.after.id += "-variant";
    item.reason =
      "Review the same wording with the intended library operation.";
  }
  const feedbackPath = path.join(temp, "feedback-catalog.json");
  await fs.writeFile(feedbackPath, JSON.stringify(feedback));
  execFileSync(python, [
    "-c",
    "import sys;sys.path.insert(0,sys.argv[1]);import objection_review as c;p=c.read(sys.argv[2]);p['proposals']['base_sha256']=c.digest(p['library']);open(sys.argv[2],'w').write(__import__('json').dumps(p))",
    scripts,
    feedbackPath,
  ]);
  const feedbackHtml = path.join(temp, "feedback.html");
  execFileSync(python, [
    script,
    "render",
    "--catalog",
    feedbackPath,
    "--out",
    feedbackHtml,
  ]);
  await page.setViewportSize({ width: 1360, height: 1000 });
  await page.goto(pathToFileURL(feedbackHtml).href);
  for (const index of [0, 1]) {
    await page.locator(`#candidate-${index}`).click();
    const current = page.locator(`#candidate-panel-${index}`);
    await expect(current.locator(".decision-effect")).toContainText(
      index === 0 ? "replaces" : "keeps",
    );
    await current
      .getByRole("button", { name: "Approve for reuse", exact: true })
      .click();
    await expect(page.locator("#progress")).toContainText(
      `${index + 1} approved`,
    );
  }
  const feedbackDecisions = await download(
    "#export",
    "feedback-decisions.json",
  );
  execFileSync(python, [
    script,
    "reconcile",
    "--catalog",
    feedbackPath,
    "--decisions",
    feedbackDecisions,
    "--out",
    path.join(temp, "feedback-proposals.json"),
  ]);
  assert.deepEqual(errors, []);
  assert.deepEqual(network, []);
  console.log(
    JSON.stringify(
      {
        status: "passed",
        browser: browser.version(),
        artifacts: temp,
        checks:
          "source/proposal inspection, individual decisions, edit resets, guidance preview, incomplete progress, real export/import, exact approved subset, continuation, wrong-file and tamper preservation, visible replacement/variant scope and compatible approvals, schema validation, keyboard, dark/light, 320/390px, literal text, zero network",
      },
      null,
      2,
    ),
  );
} finally {
  await browser.close();
}
