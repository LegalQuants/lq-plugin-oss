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
const fixtures = path.join(
  root,
  "packages/document-discovery/fixtures/objection-review/outputs",
);
const temp = await fs.mkdtemp(
  path.join(os.tmpdir(), "objection-contract-views-"),
);
const executablePath =
  process.env.OBJECTION_REVIEW_BROWSER_EXECUTABLE ||
  [
    chromium.executablePath(),
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  ].find(existsSync);
assert.ok(executablePath, "A Chromium test browser is required.");
const browser = await chromium.launch({ executablePath, headless: true });
const script = path.join(
  root,
  "skills/litigation/document-discovery/scripts/objection_review.py",
);
const python = path.join(root, ".venv/bin/python");
try {
  for (const name of [
    "review-second-set",
    "builder-review",
    "review-docx-source",
  ]) {
    const originalReview = path.join(fixtures, `${name}.json`);
    const oldReview = JSON.parse(await fs.readFile(originalReview, "utf8"));
    const reviewPath = path.join(temp, `${name}.json`);
    execFileSync(python, [
      path.join(
        root,
        "packages/document-discovery/fixtures/prepare_source_fixture.py",
      ),
      "--review",
      originalReview,
      "--source",
      path.join(path.dirname(fixtures), "inputs", oldReview.source.file),
      "--out",
      reviewPath,
    ]);
    const review = JSON.parse(await fs.readFile(reviewPath, "utf8"));
    const html = path.join(temp, `${name}.html`);
    execFileSync(python, [
      script,
      "render",
      "--review",
      reviewPath,
      "--out",
      html,
    ]);
    const page = await browser.newPage({
      viewport: { width: 1280, height: 950 },
    });
    await page.goto(pathToFileURL(html).href);
    assert.equal(
      await page.locator("article.request").count(),
      review.requests.length,
    );
    if (name === "review-second-set") {
      await page.locator('#request-0 [data-entry="scope"] .tile-name').click();
      assert.match(
        await page.locator("#request-0 .request-wording").innerText(),
        /This objection is limited to the identified portion/,
      );
    }
    if (name === "builder-review") {
      assert.equal(review.library.entries.length, 1);
      assert.equal(await page.locator(".main-choices .tile").count(), 1);
      assert.equal(await page.locator(".other-choices .tile").count(), 2);
      assert.equal(await page.getByRole("checkbox").count(), 1);
      assert.equal(
        await page.locator(".tile input[type=checkbox]").count(),
        review.requests.length,
      );
      for (const index of [1, 2]) {
        const request = page.locator(`#request-${index}`);
        await expect(request.locator(".other-library")).not.toHaveAttribute(
          "open",
          "",
        );
        await expect(
          request.locator(".tile input[type=checkbox]"),
        ).toBeHidden();
        await request.locator(".other-library > summary").click();
        await expect(request.getByRole("checkbox")).toBeVisible();
        await expect(request.getByRole("checkbox")).not.toBeChecked();
        await expect(request.locator(".tile")).toHaveAttribute(
          "data-entry",
          "scope",
        );
      }
      assert.equal(
        await page.getByRole("checkbox").count(),
        review.requests.length,
      );
    }
    await page.locator("#tools > summary").click();
    await page.locator("#batch").click();
    const pending = page.waitForEvent("download");
    await page.locator("#export").click();
    const selectionPath = path.join(temp, `${name}-selections.json`);
    await (await pending).saveAs(selectionPath);
    execFileSync(python, [
      script,
      "materialize",
      "--review",
      reviewPath,
      "--selections",
      selectionPath,
      "--out",
      path.join(temp, `${name}-assembly.json`),
    ]);
    await page.screenshot({ path: path.join(temp, `${name}.png`) });
    await page.close();
  }
  console.log(
    JSON.stringify(
      {
        status: "passed",
        artifacts: temp,
        checks:
          "second-set approved version, builder subset, DOCX-source review; real downloads and assembly for all three",
      },
      null,
      2,
    ),
  );
} finally {
  await browser.close();
}
