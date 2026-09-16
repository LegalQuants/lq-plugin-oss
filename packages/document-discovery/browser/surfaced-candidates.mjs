import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync } from "node:fs";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { chromium, expect } from "@playwright/test";

// Independently authored synthetic UI data. The simulated library approval and
// scripted review actions are regression inputs, never an attorney acceptance run.
const root = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../../..",
);
const out = await fs.mkdtemp(
  path.join(os.tmpdir(), "discovery-surfaced-candidates-"),
);
const python = path.join(root, ".venv/bin/python");
const script = path.join(
  root,
  "skills/litigation/document-discovery/scripts/objection_review.py",
);
const entry = (id, label, wording, condition, locator) => ({
  id,
  family: id,
  label,
  variant: "Qualified starting wording",
  wording,
  fields: {},
  guidance:
    "Synthetic starting language for interface regression, not legal advice.",
  conditions: [condition],
  exclusions: [],
  sources: [{ source_id: "independently-authored-corpus", locator }],
  status: "approved",
  approval: {
    record: "Simulated development-fixture approval; no attorney decision.",
  },
});
const library = {
  kind: "objection-library",
  format_version: 1,
  id: "synthetic-surfacing-library",
  version: 1,
  entries: [
    entry(
      "privilege",
      "Attorney-client privilege",
      "Responding Party objects only to confidential communications for legal advice, without extending the objection to underlying facts or existing business records.",
      "Actual confidential legal-advice communications and no applicable waiver.",
      "Prior response 12",
    ),
    entry(
      "restoration",
      "Archive restoration burden",
      "Responding Party objects to restoration only to the extent established restoration burdens outweigh the demonstrated need for that source.",
      "Supported restoration work, cost, availability elsewhere, and need must be assessed.",
      "Prior response 6",
    ),
    entry(
      "scope",
      "Unrelated product scope",
      "Responding Party objects to records concerning product lines outside the transaction, to the extent they have no connection to the issues in dispute.",
      "Other product lines lack a demonstrated connection to the dispute.",
      "Prior responses 3 and 18",
    ),
    entry(
      "work-product",
      "Opinion work product",
      "Responding Party objects to counsel’s litigation assessments to the extent they disclose protected legal opinions or strategy prepared for litigation.",
      "Litigation preparation and opinion content, with applicable exceptions assessed.",
      "Prior response 17",
    ),
    entry(
      "privacy",
      "Unrelated medical information",
      "Responding Party objects to disclosure of unrelated personal medical information; this wording does not address medical information placed in issue.",
      "Unrelated medical details actually appear in responsive material.",
      "Prior response 22",
    ),
  ],
};
const possible = (entry_id, rationale, basis, missing = []) => ({
  entry_id,
  params: {},
  rationale,
  basis: [basis],
  missing,
  preselected: false,
});
const texts = [
  "Produce confidential communications with counsel seeking legal advice about the disputed license.",
  "Produce the transaction messages stored on the retired archive drives.",
  "Produce all product-line records, including counsel’s confidential legal advice, for every product sold since 1980.",
  "Produce counsel’s written litigation strategy assessments for the pending license dispute.",
  "Produce the executed license agreement and its signed amendments.",
  "Produce the invoice identified in the attached payment schedule.",
];
const notes = [
  "The request expressly targets legal advice. The privilege type is a primary possibility; inclusion still depends on protection and waiver.",
  "The named retired drives support considering restoration burden even though cost and access facts are not yet available.",
  "Both the all-product scope and the express demand for confidential advice warrant separate consideration. Medical privacy is less apparent because no medical material is requested.",
  "The current request targets counsel’s litigation strategy. The source wording came from prior response 17; that different number does not limit reuse.",
  "No approved entry has a supported connection to the identified executed agreement and amendments on the supplied facts. This is not a finding that no objection could ever apply.",
];
const suggestions = [
  [
    possible(
      "privilege",
      "The request expressly seeks confidential counsel communications for legal advice.",
      "Current request text; prior response 12 supplies reusable wording.",
      [
        "Confirm confidentiality and waiver; governing privilege law has not been checked.",
      ],
    ),
  ],
  [
    possible(
      "restoration",
      "The request names retired archive drives whose restoration may impose a material burden.",
      "Current request identifies a retired source; retirement alone does not prove burden.",
      [
        "Restoration steps, cost, and availability from other sources are unknown.",
      ],
    ),
  ],
  [
    possible(
      "privilege",
      "Confidential legal advice is expressly included within the broader demand.",
      "Current request text; source qualifications remain operative.",
      ["Confirm privilege elements and waiver."],
    ),
    possible(
      "scope",
      "Every product line since 1980 may extend beyond the disputed license transaction.",
      "Current request breadth compared with the supplied license-dispute context.",
      [
        "Determine which other product lines have a material connection to the dispute.",
      ],
    ),
  ],
  [
    possible(
      "work-product",
      "Counsel’s litigation strategy assessments may reveal protected opinions.",
      "Current request text and the reusable type from prior response 17, not matching request numbers.",
      ["Confirm litigation preparation and any governing exceptions."],
    ),
  ],
  [],
  [],
];
const raw = `${texts
  .map((text, i) => `REQUEST FOR PRODUCTION NO. ${i + 1}\n\n${text}`)
  .join("\n\n")}\n`;
const rawPath = path.join(out, "synthetic-served-requests.md");
await fs.writeFile(rawPath, raw);
const review = {
  kind: "objection-review",
  format_version: 1,
  id: "synthetic-candidate-surfacing",
  title: "Synthetic candidate-surfacing regression",
  source: {
    file: path.basename(rawPath),
    sha256: createHash("sha256").update(raw).digest("hex"),
  },
  library,
  context: [],
  requests: texts.map((text, i) => ({
    id: `request-${i + 1}`,
    label: `REQUEST FOR PRODUCTION NO. ${i + 1}`,
    text,
    locator: `Request ${i + 1}`,
    context_ids: [],
    suggestions: suggestions[i],
    ...(notes[i] ? { candidate_note: notes[i] } : {}),
  })),
};
const unbound = path.join(out, "unbound-review.json"),
  source = path.join(out, "review.json"),
  html = path.join(out, "review.html");
await fs.writeFile(unbound, JSON.stringify(review));
execFileSync(python, [
  path.join(
    root,
    "packages/document-discovery/fixtures/prepare_source_fixture.py",
  ),
  "--review",
  unbound,
  "--source",
  rawPath,
  "--out",
  source,
]);
const boundReview = JSON.parse(await fs.readFile(source, "utf8"));
boundReview.requests.forEach((request, i) => {
  assert.equal(request.candidate_note, notes[i]);
});
execFileSync(python, [script, "render", "--review", source, "--out", html]);
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
page.on("pageerror", (e) => errors.push(e.message));
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
async function screenshotRequest(i, name) {
  // Let the toolbar's ResizeObserver account for a newly displayed download
  // receipt before positioning the request below the sticky controls.
  await page.evaluate(
    () =>
      new Promise((resolve) =>
        requestAnimationFrame(() => requestAnimationFrame(resolve)),
      ),
  );
  await page
    .locator(`#request-${i}`)
    .evaluate((node) => node.scrollIntoView({ block: "start" }));
  await page.screenshot({ path: path.join(out, name) });
}
try {
  await page.goto(pathToFileURL(html).href);
  const primaryIds = await page
    .locator(".request")
    .evaluateAll((nodes) =>
      nodes.map((node) =>
        [...node.querySelectorAll(".main-choices .tile")].map(
          (tile) => tile.dataset.entry,
        ),
      ),
    );
  assert.deepEqual(primaryIds, [
    ["privilege"],
    ["restoration"],
    ["privilege", "scope"],
    ["work-product"],
    [],
    [],
  ]);
  await expect(page.locator(".tile input:checked")).toHaveCount(0);
  assert.equal(await page.locator(".wording-preview:visible").count(), 0);
  for (const [i, text] of texts.entries())
    await expect(page.locator(`#request-${i} .served`)).toHaveText(text);
  const apparent = page.locator("#request-0"),
    conditional = page.locator("#request-1"),
    multiple = page.locator("#request-2"),
    cross = page.locator("#request-3"),
    unsupported = page.locator("#request-4"),
    unassessed = page.locator("#request-5");
  await expect(apparent.locator(".suggested")).toHaveText("For consideration");
  await expect(apparent.locator(".wording-status")).toContainText(
    "No wording selected",
  );
  await expect(apparent.locator(".wording-status")).toContainText(
    "Surfaced possibilities remain unchecked",
  );
  await expect(
    multiple.locator('.other-choices [data-entry="privacy"]'),
  ).toBeHidden();
  await expect(multiple.locator(".candidate-note")).toContainText(
    "Medical privacy is less apparent",
  );
  await expect(unsupported.locator(".candidate-note")).toContainText(
    "No approved entry has a supported connection",
  );
  await expect(unsupported.locator(".wording-status")).toContainText(
    "No wording selected",
  );
  await expect(unassessed.locator(".palette-empty")).toContainText(
    "that alone does not establish that no objection could apply",
  );
  const opening = await download("#save", "opening-progress.json");
  assert.ok(
    opening.data.rows.every(
      (row) => row.action === null && !row.choices.length,
    ),
  );
  await screenshotRequest(0, "apparent-unchecked.png");
  await conditional
    .getByRole("button", {
      name: "Why Archive restoration burden?",
      exact: true,
    })
    .focus();
  await expect(conditional.locator(".reason")).toBeVisible();
  await expect(conditional.locator(".reason")).toContainText(
    "retired archive drives",
  );
  await expect(conditional.locator(".reason")).toContainText(
    "Restoration steps, cost",
  );
  await page.keyboard.press("Escape");
  await expect(conditional.locator(".reason")).toBeHidden();
  await conditional
    .getByRole("button", { name: "Archive restoration burden", exact: true })
    .click();
  await expect(conditional.locator(".candidate-reason")).toContainText(
    "retirement alone does not prove burden",
  );
  await expect(conditional.locator(".candidate-reason")).toContainText(
    "not included in Word",
  );
  await expect(
    conditional.locator(".detail-inclusion input"),
  ).not.toBeChecked();
  await expect(conditional.locator(".wording-preview")).toBeHidden();
  await screenshotRequest(1, "conditional-inspected-unchecked.png");
  await cross
    .getByRole("button", { name: "Opinion work product", exact: true })
    .click();
  await expect(cross.locator(".candidate-reason")).toContainText(
    "prior response 17, not matching request numbers",
  );
  await screenshotRequest(3, "cross-precedent-ground.png");
  await multiple
    .locator('.main-choices [data-entry="privilege"] input')
    .check();
  await multiple.locator('.main-choices [data-entry="scope"] input').check();
  const selectedWording = [
    library.entries[0].wording,
    library.entries[2].wording,
  ].join("\n\n");
  await expect(multiple.locator(".wording-preview")).toHaveText(
    selectedWording,
  );
  assert.ok(
    !(await multiple.locator(".wording-preview").innerText()).includes(
      "Confirm privilege",
    ),
  );
  const saved = await download("#save", "selected-progress.json");
  assert.ok(saved.data.rows.every((row) => row.action === null));
  assert.equal(saved.data.rows[2].choices.length, 2);
  await screenshotRequest(2, "multiple-selected-preview.png");
  await page.reload();
  await page.locator("#import").setInputFiles(saved.file);
  await expect(page.locator("#message")).toContainText("restored");
  await expect(multiple.locator(".wording-preview")).toHaveText(
    selectedWording,
  );
  await expect(
    conditional.locator('.main-choices [data-entry="restoration"] input'),
  ).not.toBeChecked();
  const exported = await download("#export", "selected-assembly.json");
  assert.equal(exported.data.rows[2].action.trigger, "export-selected");
  assert.equal(
    exported.data.rows[2].choices.map((c) => c.wording).join("\n\n"),
    selectedWording,
  );
  assert.ok(
    exported.data.rows
      .filter((_, i) => i !== 2)
      .every((row) => row.action === null && !row.choices.length),
  );
  execFileSync(python, [
    script,
    "check-selections",
    "--review",
    source,
    "--selections",
    exported.file,
  ]);
  const assemblyPath = path.join(out, "assembly.json");
  execFileSync(python, [
    script,
    "materialize",
    "--review",
    source,
    "--selections",
    exported.file,
    "--out",
    assemblyPath,
  ]);
  const assembly = JSON.parse(await fs.readFile(assemblyPath, "utf8"));
  assert.equal(assembly.requests[2].objection_text, selectedWording);
  assert.equal(assembly.requests[1].objection_text, "");
  await screenshotRequest(4, "no-supported-connection.png");
  await page.setViewportSize({ width: 390, height: 844 });
  await conditional
    .getByRole("button", { name: "Archive restoration burden", exact: true })
    .click();
  await expect(conditional.locator(".candidate-reason")).toBeVisible();
  assert.equal(
    await page.evaluate(
      () => document.documentElement.scrollWidth > innerWidth,
    ),
    false,
  );
  await screenshotRequest(1, "conditional-narrow.png");
  await page.setViewportSize({ width: 320, height: 740 });
  assert.equal(
    await page.evaluate(
      () => document.documentElement.scrollWidth > innerWidth,
    ),
    false,
  );
  assert.deepEqual(errors, []);
  assert.deepEqual(network, []);
  const result = {
    result: "PASS",
    browser: browser.version(),
    out,
    simulation:
      "Independently authored synthetic mechanical regression; scripted actions are not attorney acceptance.",
    primaryIds,
    checks: [
      "apparent approved type surfaced unchecked",
      "conditional type retained with missing facts and no invented burden",
      "multiple separate grounds with exact combined preview",
      "different prior-response number not a restriction",
      "less apparent medical alternative remains collapsed",
      "no supported connection distinct from no selected wording and absent assessment",
      "inspection and save do not authorize",
      "resume retains selections",
      "deliberate export binds selected wording only",
      "mobile 390/320px no horizontal overflow",
    ],
  };
  await fs.writeFile(
    path.join(out, "checks.json"),
    JSON.stringify(result, null, 2),
  );
  console.log(JSON.stringify(result, null, 2));
} finally {
  await browser.close();
}
