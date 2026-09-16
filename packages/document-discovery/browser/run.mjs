import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
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
  path.join(os.tmpdir(), "objection-review-browser-"),
);
const script = path.join(
  root,
  "skills/litigation/document-discovery/scripts/objection_review.py",
);
const originalReview = path.join(
  root,
  "packages/document-discovery/fixtures/objection-review/inputs/review.json",
);
const html = path.join(temp, "review.html");
const python = path.join(root, ".venv/bin/python");
const review = path.join(temp, "review.json");
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
  review,
]);
const validateRecord = new Ajv2020({ strict: false }).compile(
  JSON.parse(
    await fs.readFile(
      path.join(
        root,
        "skills/litigation/document-discovery/schemas/objection-records.schema.json",
      ),
      "utf8",
    ),
  ),
);
assert.ok(
  validateRecord(JSON.parse(await fs.readFile(review, "utf8"))),
  JSON.stringify(validateRecord.errors),
);
execFileSync(python, [script, "render", "--review", review, "--out", html]);
// Deliberately fail if no test browser is available; never turn a skip into a pass.
const executablePath =
  process.env.OBJECTION_REVIEW_BROWSER_EXECUTABLE ||
  [
    chromium.executablePath(),
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  ].find(existsSync);
assert.ok(
  executablePath,
  "No Chromium test browser available; browser check is required.",
);
const browser = await chromium.launch({ headless: true, executablePath });
const errors = [];
const network = [];
try {
  const page = await browser.newPage({
    viewport: { width: 1360, height: 1000 },
  });
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("request", (r) => {
    if (/^https?:/.test(r.url())) network.push(r.url());
  });
  await page.goto(pathToFileURL(html).href);
  assert.equal(await page.locator("article.request").count(), 16);
  assert.match(await page.locator("#progress").innerText(), /0 of 16 reviewed/);
  assert.match(
    await page.locator("#request-15 .served").innerText(),
    /<\/script><img/,
  );
  assert.equal(await page.locator("#request-15 img").count(), 0);
  assert.equal(await page.locator("select").count(), 0);
  assert.equal(await page.locator("textarea").count(), 0);
  assert.equal(await page.locator(".detail-panel").count(), 0);
  assert.equal(await page.locator("#request-0 .tile").count(), 10);
  assert.equal(await page.locator("#request-0 .main-choices .tile").count(), 0);
  assert.equal(
    await page.locator("#request-0 .other-choices .tile").count(),
    10,
  );
  await expect(page.locator("#request-0 .other-library")).not.toHaveAttribute(
    "open",
    "",
  );
  assert.equal(
    await page.locator("#request-0").getByRole("checkbox").count(),
    0,
  );
  const tileOrder = await page
    .locator("#request-1 .tile")
    .evaluateAll((nodes) => nodes.map((n) => n.dataset.entry));
  const libraryOrder = JSON.parse(
    await fs.readFile(review, "utf8"),
  ).library.entries.map((entry) => entry.id);
  async function assertPaletteOrder(request, selected) {
    for (const [selector, included] of [
      [".main-choices .tile", true],
      [".other-choices .tile", false],
    ]) {
      assert.deepEqual(
        await request
          .locator(selector)
          .evaluateAll((nodes) => nodes.map((node) => node.dataset.entry)),
        libraryOrder.filter((id) => selected.includes(id) === included),
      );
    }
  }
  await page.screenshot({ path: path.join(temp, "initial-desktop.png") });
  const req1 = page.locator("#request-0");
  await req1
    .getByRole("button", { name: "Mark reviewed", exact: true })
    .click();
  const req2 = page.locator("#request-1");
  const scopeTile = req2.locator('[data-entry="scope"]');
  await scopeTile
    .getByRole("button", { name: "Unrelated scope", exact: true })
    .click();
  await expect(scopeTile.getByRole("checkbox")).toBeChecked();
  assert.equal(
    await req2.locator(".badge").innerText(),
    "Selected · included on export",
  );
  await expect(req2.locator(".library-wording")).toBeHidden();
  await req2.locator(".library-comparison > summary").click();
  await expect(req2.locator(".library-wording")).toBeVisible();
  assert.match(
    await req2.locator(".library-wording").innerText(),
    /\[the precise portion challenged\]/,
  );
  assert.match(
    await req2.locator(".request-wording").innerText(),
    /products other than Harbor/,
  );
  assert.equal(await req2.locator("textarea").count(), 0);
  const visibleDetail = await req2.locator(".detail-panel").boundingBox();
  assert.ok(
    visibleDetail &&
      visibleDetail.y >= 0 &&
      visibleDetail.y + visibleDetail.height <= 1000,
  );
  await page.screenshot({ path: path.join(temp, "inspect-wording.png") });
  await assertPaletteOrder(req2, ["scope"]);
  await req2.locator(".other-library > summary").click();
  const workTile = req2.locator('[data-entry="work-product"]');
  await workTile
    .getByRole("button", { name: "Work product", exact: true })
    .click();
  await expect(workTile.getByRole("checkbox")).not.toBeChecked();
  assert.equal(await req2.locator(".detail-panel").count(), 1);
  await workTile.getByRole("checkbox").check();
  await assertPaletteOrder(req2, ["scope", "work-product"]);
  await expect(
    workTile.getByRole("button", { name: "Work product", exact: true }),
  ).toHaveAttribute("aria-expanded", "true");
  await req2.getByRole("button", { name: "Arrange wording" }).click();
  await req2
    .locator(".order-list li")
    .first()
    .getByRole("button", { name: "Move down" })
    .click();
  assert.match(
    await req2.locator(".order-list li").first().innerText(),
    /Work product/,
  );
  await assertPaletteOrder(req2, ["scope", "work-product"]);
  await workTile.getByRole("checkbox").uncheck();
  assert.deepEqual(
    await req2
      .locator(".tile")
      .evaluateAll((nodes) => nodes.map((n) => n.dataset.entry)),
    tileOrder,
  );
  await scopeTile
    .getByRole("button", { name: "Unrelated scope", exact: true })
    .click();
  await req2.getByRole("button", { name: "Why Unrelated scope?" }).focus();
  assert.equal(await scopeTile.getByRole("tooltip").isVisible(), true);
  await req2
    .getByRole("button", { name: "Why Unrelated scope?" })
    .press("Escape");
  await expect(scopeTile.getByRole("tooltip")).not.toBeVisible();
  await expect(
    req2.getByRole("button", { name: "Why Unrelated scope?" }),
  ).toBeFocused();
  await req2
    .getByRole("button", { name: "Mark reviewed", exact: true })
    .click();
  await req2.getByRole("button", { name: "Edit wording", exact: true }).click();
  const wording = req2.getByLabel(
    "Wording to insert (edits apply to this request only)",
  );
  const acceptedText = `${await wording.inputValue()} Limited to non-Harbor product records.`;
  await wording.fill(acceptedText);
  assert.equal(
    await req2.locator(".badge").innerText(),
    "Selected · included on export",
  );
  await req2
    .getByRole("button", { name: "Mark reviewed", exact: true })
    .click();
  await page
    .locator("#request-5")
    .getByRole("button", { name: "Needs input", exact: true })
    .click();
  await page
    .locator("#request-13")
    .getByRole("button", { name: "Needs input", exact: true })
    .click();
  await page.locator("#tools > summary").click();
  await page.locator("#batch").click();
  assert.match(
    await page.locator("#progress").innerText(),
    /14 of 16 reviewed/,
  );

  async function download(button, filename) {
    if (
      button === "#save" &&
      (await page.locator("#tools").getAttribute("open")) === null
    ) {
      await page.locator("#tools > summary").click();
    }
    const waiting = page.waitForEvent("download");
    await page.locator(button).click();
    const downloaded = await waiting;
    const dest = path.join(temp, filename);
    await downloaded.saveAs(dest);
    return { path: dest, data: JSON.parse(await fs.readFile(dest, "utf8")) };
  }
  const progress = await download("#save", "progress.json");
  assert.equal(progress.data.purpose, "progress");
  await page.reload();
  assert.match(await page.locator("#progress").innerText(), /0 of 16 reviewed/);
  await page.locator("#tools > summary").click();
  await page.locator("#import").setInputFiles(progress.path);
  await expect(page.locator("#message")).toContainText("restored");
  await scopeTile
    .getByRole("button", { name: "Unrelated scope", exact: true })
    .click();
  assert.equal(
    await req2.locator(".request-wording").innerText(),
    acceptedText,
  );
  await req2.getByRole("button", { name: "Edit wording", exact: true }).click();
  assert.equal(await wording.inputValue(), acceptedText);

  const bad = structuredClone(progress.data);
  bad.review_sha256 = "0".repeat(64);
  const badPath = path.join(temp, "wrong.json");
  await fs.writeFile(badPath, JSON.stringify(bad));
  await page.locator("#tools > summary").click();
  await page.locator("#import").setInputFiles(badPath);
  await expect(page.locator("#message")).toContainText(
    "Import failed; current choices kept",
  );
  assert.match(
    await page.locator("#progress").innerText(),
    /14 of 16 reviewed/,
  );

  const selections = await download("#export", "selections.json");
  assert.equal(selections.data.rows[0].choices.length, 0);
  assert.equal(selections.data.rows[1].choices[0].wording, acceptedText);
  assert.equal(selections.data.rows[5].state, "needs_input");
  assert.equal(selections.data.rows[5].action, null);
  execFileSync(python, [
    script,
    "check-selections",
    "--review",
    review,
    "--selections",
    selections.path,
  ]);
  const assembly = path.join(temp, "assembly.json");
  execFileSync(python, [
    script,
    "materialize",
    "--review",
    review,
    "--selections",
    selections.path,
    "--out",
    assembly,
  ]);
  const assembled = JSON.parse(await fs.readFile(assembly, "utf8"));
  assert.ok(
    validateRecord(selections.data),
    JSON.stringify(validateRecord.errors),
  );
  assert.ok(validateRecord(assembled), JSON.stringify(validateRecord.errors));
  assert.equal(assembled.requests[5].objection_text, "");
  assert.equal(assembled.requests[1].objection_text, acceptedText);
  await page.screenshot({ path: path.join(temp, "desktop.png") });
  await page.emulateMedia({ colorScheme: "dark" });
  await expect(page.locator("#theme-toggle")).toHaveText("Use light theme");
  await page.locator("#theme-toggle").click();
  assert.equal(
    await page.evaluate(() =>
      getComputedStyle(document.documentElement)
        .getPropertyValue("--lq-background")
        .trim(),
    ),
    "#f4f1ea",
  );
  await page.locator("#theme-toggle").click();
  assert.equal(
    await page.evaluate(() =>
      getComputedStyle(document.documentElement)
        .getPropertyValue("--lq-background")
        .trim(),
    ),
    "#151718",
  );
  await req2.scrollIntoViewIfNeeded();
  await page.screenshot({ path: path.join(temp, "dark.png") });
  await page.setViewportSize({ width: 390, height: 844 });
  assert.equal(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
    true,
  );
  await page.locator("#request-12").scrollIntoViewIfNeeded();
  await page.screenshot({ path: path.join(temp, "mobile.png") });
  await page.setViewportSize({ width: 320, height: 740 });
  assert.equal(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
    true,
  );
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.screenshot({ path: path.join(temp, "narrow.png") });

  // Check one-off creation, ordering and invalid wording without changing saved decisions.
  await req1.getByRole("button", { name: "Add custom objection" }).click();
  await req1
    .getByLabel("Wording to insert (edits apply to this request only)")
    .fill("One-off test wording.");
  await req1
    .getByRole("button", { name: "Mark reviewed", exact: true })
    .click();
  await req1
    .getByLabel("Wording to insert (edits apply to this request only)")
    .fill("");
  await page.locator("#export").click();
  await expect(page.locator("#message")).toContainText(
    "Complete the selected wording",
  );
  const unfinished = await download("#save", "unfinished-selections.json");
  assert.equal(unfinished.data.rows[0].state, "not_reviewed");
  assert.equal(unfinished.data.rows[0].drafts.at(-1).wording, "");
  assert.equal(unfinished.data.rows[0].action, null);
  assert.deepEqual(network, []);
  assert.deepEqual(errors, []);
  console.log(
    JSON.stringify(
      {
        status: "passed",
        browser: await browser.version(),
        artifacts: temp,
        checks:
          "tiles and independent selection/inspection, exact library/request wording, edit reset, download/import, partial review, source binding, escaped text, keyboard explanation, explicit themes, no network, responsive layout",
      },
      null,
      2,
    ),
  );
} finally {
  await browser.close();
}
