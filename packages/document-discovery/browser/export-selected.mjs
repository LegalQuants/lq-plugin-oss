import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import fs from "node:fs/promises";
import path from "node:path";
import { expect } from "@playwright/test";

// Invoked by review-state.mjs with the independently authored synthetic fixture.
// Every action here is mechanical regression coverage, never attorney acceptance.
export async function checkSelectedExport({
  page,
  out,
  python,
  script,
  source,
  download,
}) {
  await page.reload();
  const first = page.locator("#request-0");
  const second = page.locator("#request-1");
  const empty = page.locator("#request-2");
  const deferred = page.locator("#request-5");
  const wordingLabel = "Wording to insert (edits apply to this request only)";
  const customText =
    "Selected synthetic wording — qualification retained.\nSecond paragraph.";
  const initial = await download("#save", "export-initial-progress.json");
  assert.ok(initial.data.rows.every((row) => row.action === null));
  assert.ok(initial.data.rows.some((row) => row.choices.length));
  await expect(
    page.getByRole("button", { name: "Mark all reviewed", exact: true }),
  ).toBeVisible();
  assert.equal(await page.locator("#tools #batch").count(), 0);
  await first
    .getByRole("button", { name: "Add custom objection", exact: true })
    .click();
  await first.getByLabel(wordingLabel).fill(customText);
  await deferred.locator('[data-entry="backup"]').getByRole("checkbox").check();
  await deferred
    .getByRole("button", { name: "Needs input", exact: true })
    .click();
  await expect(first.locator(".wording-status")).toContainText(
    "No separate review click is needed",
  );
  const selected = await download("#save", "selected-progress.json");
  assert.ok(selected.data.rows.every((row) => row.action === null));
  assert.equal(selected.data.rows[0].state, "not_reviewed");
  await page.evaluate(() => scrollTo(0, 0));
  await page.screenshot({
    path: path.join(out, "export-selected-desktop.png"),
  });
  const exported = await download(
    "#export",
    "selected-without-review-click.json",
  );
  for (const index of [0, 1]) {
    assert.equal(exported.data.rows[index].state, "reviewed");
    assert.equal(exported.data.rows[index].action.kind, "batch");
    assert.equal(exported.data.rows[index].action.trigger, "export-selected");
    assert.ok(exported.data.rows[index].action.reviewed_content_sha256);
  }
  assert.equal(exported.data.rows[2].state, "not_reviewed");
  assert.equal(exported.data.rows[2].action, null);
  assert.equal(exported.data.rows[5].state, "needs_input");
  assert.equal(exported.data.rows[5].action, null);
  assert.equal(exported.data.rows[0].choices[0].wording, customText);
  const assemblyPath = path.join(
    out,
    "selected-without-review-click-assembly.json",
  );
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
  assert.equal(assembly.requests[0].objection_text, customText);
  assert.equal(
    assembly.requests[1].objection_text,
    selected.data.rows[1].choices[0].wording,
  );
  assert.equal(assembly.requests[2].open_review, true);
  assert.equal(assembly.requests[5].objection_text, "");
  await page.locator("#batch").click();
  await expect(empty.locator(".badge")).toHaveText("Reviewed · no objections");
  const batch = await download("#save", "all-reviewed-progress.json");
  assert.equal(batch.data.rows[2].action.kind, "batch");
  assert.equal(batch.data.rows[2].action.trigger, "mark-all");
  assert.equal(batch.data.rows[2].choices.length, 0);
  assert.equal(batch.data.rows[5].state, "needs_input");
  assert.equal(batch.data.rows[5].action, null);

  // A later operative edit clears the old record; the next export binds the edit.
  const laterText = `${customText}\nA deliberate later change.`;
  await first.getByLabel(wordingLabel).fill(laterText);
  const afterEdit = await download(
    "#save",
    "edited-after-export-progress.json",
  );
  assert.equal(afterEdit.data.rows[0].action, null);
  const reexported = await download("#export", "edited-after-export.json");
  assert.equal(reexported.data.rows[0].choices[0].wording, laterText);
  assert.notEqual(
    reexported.data.rows[0].action.reviewed_content_sha256,
    exported.data.rows[0].action.reviewed_content_sha256,
  );
  await first.locator(".detail-inclusion input").uncheck();
  const deselected = await download(
    "#save",
    "edited-deselected-after-export.json",
  );
  assert.equal(deselected.data.rows[0].choices.length, 0);
  assert.equal(deselected.data.rows[0].drafts[0].wording, laterText);
  await page.reload();
  await page.locator("#import").setInputFiles(deselected.file);
  await expect(page.locator("#message")).toContainText("restored");
  await first
    .getByRole("button", { name: "Custom objection", exact: true })
    .click();
  await expect(first.locator(".request-wording")).toHaveText(laterText);
  await expect(first.locator(".detail-inclusion input")).not.toBeChecked();

  // A failed export or batch action is atomic, including when earlier rows were valid.
  await page.reload();
  await first
    .getByRole("button", { name: "Add custom objection", exact: true })
    .click();
  await first.getByLabel(wordingLabel).fill(customText);
  await second
    .getByRole("button", { name: "Unrelated scope", exact: true })
    .click();
  await second
    .getByRole("button", { name: "Edit wording", exact: true })
    .click();
  await second.getByLabel(wordingLabel).fill("");
  let downloads = 0;
  const countDownload = () => downloads++;
  page.on("download", countDownload);
  await page.locator("#export").click();
  await expect(page.locator("#message")).toContainText(
    "Complete or deselect the wording",
  );
  const sourceRecord = JSON.parse(await fs.readFile(source, "utf8"));
  await expect(page.locator("#message")).toContainText(
    sourceRecord.requests[1].label,
  );
  assert.equal(downloads, 0);
  await page.locator("#batch").click();
  await expect(page.locator("#message")).toContainText(
    "No new review actions were recorded",
  );
  const incomplete = await download("#save", "incomplete-export-progress.json");
  assert.ok(incomplete.data.rows.every((row) => row.action === null));
  assert.equal(incomplete.data.rows[0].choices[0].wording, customText);
  assert.equal(incomplete.data.rows[1].choices[0].wording, "");
  await second
    .getByRole("button", { name: "Needs input", exact: true })
    .click();
  const partial = await download(
    "#export",
    "incomplete-needs-input-assembly.json",
  );
  assert.equal(partial.data.rows[0].state, "reviewed");
  assert.equal(partial.data.rows[1].state, "needs_input");
  assert.equal(partial.data.rows[1].choices[0].wording, "");
  assert.equal(partial.data.rows[1].action, null);
  page.off("download", countDownload);

  async function pauseDigest() {
    await page.evaluate(() => {
      const original = crypto.subtle.digest.bind(crypto.subtle);
      crypto.subtle.digest = async (...args) => {
        crypto.subtle.digest = original;
        await new Promise((resolve) => {
          globalThis.releaseExportDigest = resolve;
        });
        return original(...args);
      };
    });
  }
  async function waitForDigest() {
    await expect
      .poll(() => page.evaluate(() => typeof globalThis.releaseExportDigest))
      .toBe("function");
  }
  for (const control of ["#export", "#batch"]) {
    await page.reload();
    await second
      .getByRole("button", { name: "Unrelated scope", exact: true })
      .click();
    await second
      .getByRole("button", { name: "Edit wording", exact: true })
      .click();
    await pauseDigest();
    await page.locator(control).click();
    await waitForDigest();
    await second
      .getByLabel(wordingLabel)
      .fill(`Newest synthetic wording during ${control}.`);
    await page.evaluate(() => globalThis.releaseExportDigest());
    await expect(page.locator("#message")).toContainText("Work changed");
    const raced = await download(
      "#save",
      `${control.slice(1)}-race-progress.json`,
    );
    assert.ok(raced.data.rows.every((row) => row.action === null));
    assert.equal(
      raced.data.rows[1].choices[0].wording,
      `Newest synthetic wording during ${control}.`,
    );
  }

  // Even an identical resume while hashing invalidates the in-flight action.
  await page.reload();
  await pauseDigest();
  await page.locator("#export").click();
  await waitForDigest();
  await page.locator("#import").setInputFiles(initial.file);
  await expect(page.locator("#message")).toContainText("restored");
  await page.evaluate(() => globalThis.releaseExportDigest());
  await expect(page.locator("#message")).toContainText("Work changed");
  const importRace = await download(
    "#save",
    "import-during-export-progress.json",
  );
  assert.ok(importRace.data.rows.every((row) => row.action === null));
  for (const width of [1360, 390, 320]) {
    await page.setViewportSize({ width, height: 844 });
    await empty.evaluate((node) => node.scrollIntoView({ block: "start" }));
    await expect
      .poll(async () => {
        const heading = await empty.locator("h2").boundingBox();
        const toolbarBottom = await page
          .locator(".toolbar")
          .evaluate((node) =>
            getComputedStyle(node).position === "sticky"
              ? node.getBoundingClientRect().bottom
              : 0,
          );
        return heading.y >= toolbarBottom && heading.y < 844;
      })
      .toBe(true);
    await page.evaluate(() => scrollTo(0, 0));
    assert.equal(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
      true,
    );
    await expect(
      page.getByRole("button", { name: "Mark all reviewed", exact: true }),
    ).toBeVisible();
    await page.screenshot({
      path: path.join(out, `export-selected-${width}.png`),
    });
  }
}
