import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { existsSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { chromium } from "@playwright/test";

const repo = resolve(new URL("../../..", import.meta.url).pathname);
const out = mkdtempSync(join(tmpdir(), "legaldesign-card-hub-"));
const source = join(out, "hub.html");
execFileSync(process.env.PYTHON || "python3", [
  join(repo, "skills/core/legaldesign/scripts/scaffold.py"),
  "compose",
  "--plan",
  join(repo, "packages/legaldesign/templates/card-hub.plan.json"),
  "--spec-output",
  join(out, "spec.json"),
  "--output",
  source,
  "--artifact-id",
  "card-hub-test",
]);
const browser = await chromium.launch({
  headless: true,
  executablePath: [
    chromium.executablePath(),
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  ].find(existsSync),
});
try {
  const page = await browser.newPage({
    viewport: { width: 1440, height: 900 },
  });
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto(pathToFileURL(source).href);
  await page.waitForFunction(() => window.LegalDesign?.state);
  for (const [width, height] of [
    [1280, 800],
    [1440, 900],
    [2560, 1440],
  ]) {
    await page.setViewportSize({ width, height });
    for (const theme of ["light", "dark"]) {
      if ((await page.locator("html").getAttribute("data-theme")) !== theme)
        await page.locator("#theme-toggle").click();
      const bounds = await page
        .locator('.ld-card-hub [data-kind="card"]')
        .evaluateAll((cards) =>
          cards.map((card) => {
            const r = card.getBoundingClientRect();
            return {
              x: r.x,
              y: r.y,
              width: r.width,
              bottom: r.bottom,
              overflow: card.scrollWidth > card.clientWidth + 1,
            };
          }),
        );
      assert.equal(bounds.length, 5);
      assert.ok(
        bounds
          .slice(0, 4)
          .every(
            (r) =>
              Math.abs(r.y - bounds[0].y) < 1 && r.width > 200 && !r.overflow,
          ),
      );
      assert.ok(
        bounds[4].bottom < height,
        `concluding card outside ${width}x${height}`,
      );
      assert.equal(
        await page
          .locator(".ld-fixed-page h1")
          .evaluate((el) => getComputedStyle(el).fontSize),
        "28px",
      );
      await page.screenshot({ path: join(out, `${width}-${theme}.png`) });
    }
  }
  for (const width of [390, 768, 1024]) {
    await page.setViewportSize({ width, height: 900 });
    await page.evaluate(
      () =>
        new Promise((resolve) =>
          requestAnimationFrame(() => requestAnimationFrame(resolve)),
        ),
    );
    const boxes = await page
      .locator('.ld-card-hub [data-kind="card"]')
      .evaluateAll((cards) =>
        cards.map((card) => {
          const box = card.getBoundingClientRect();
          return {
            x: box.x,
            right: box.right,
            y: box.y,
            overflow: card.scrollWidth > card.clientWidth + 1,
          };
        }),
      );
    assert.ok(
      boxes.every(
        (box) => box.x >= 0 && box.right <= width + 1 && !box.overflow,
      ),
      `${width}px card bounds: ${JSON.stringify(boxes)}`,
    );
    // Fixed one-pagers retain their overview composition on phones. The book
    // reader provides reflowed, full-size text, as on the other templates.
    if (width > 760) {
      assert.ok(Math.abs(boxes[0].y - boxes[1].y) < 1);
      assert.ok(
        boxes[2].y > boxes[0].y,
        `${width}px peer cards should form two rows`,
      );
      assert.equal(
        await page
          .locator(".ld-fixed-page h1")
          .evaluate((el) => getComputedStyle(el).fontSize),
        "28px",
      );
    }
    await page.locator("#ld-read-page").click();
    const reader = page.locator(".ld-page-reader:visible");
    assert.ok(await reader.isVisible());
    assert.equal(
      await reader.locator(".ld-popup-pencil,.ld-popup-size-grip").count(),
      0,
    );
    assert.ok(
      await reader
        .locator("p")
        .first()
        .evaluate((el) => parseFloat(getComputedStyle(el).fontSize) >= 16),
    );
    assert.ok(
      await reader.evaluate((el) => el.scrollWidth <= el.clientWidth + 1),
    );
    await reader.locator(".ld-popup-close,.pop-close").click();
    await page.screenshot({
      path: join(out, `${width}-responsive.png`),
      fullPage: true,
    });
  }
  await page.setViewportSize({ width: 1440, height: 900 });
  for (const card of await page
    .locator('.ld-card-hub [data-kind="card"]')
    .all()) {
    const target = await card.getAttribute("data-detail");
    await card.click();
    assert.ok(await page.locator(`#${target} .ld-popup-pencil`).isVisible());
    await page.locator(`#${target} .ld-popup-close`).click();
    await card.focus();
    await page.keyboard.press("Enter");
    assert.ok(await page.locator(`#${target}`).isVisible());
    await page.keyboard.press("Escape");
  }
  for (const kind of ["client", "template"]) {
    const html = await page.evaluate(
      (kind) =>
        kind === "client"
          ? window.LegalDesign.exportHTML(false)
          : window.LegalDesign.exportTemplate(false),
      kind,
    );
    if (kind === "client")
      assert.doesNotMatch(
        html,
        /showSaveFilePicker|createWritable|persistHTML|\.download\s*=/,
      );
    const path = join(out, `${kind}.html`);
    writeFileSync(path, html);
    const copy = await browser.newPage({
      viewport: { width: 1440, height: 900 },
    });
    await copy.goto(pathToFileURL(path).href);
    await copy.waitForFunction(() => window.LegalDesign?.state);
    assert.equal(
      await copy.locator('.ld-card-hub [data-kind="card"]').count(),
      5,
    );
    assert.equal(
      await copy.evaluate(
        () => window.LegalDesign.state().composition.sections[0].presentation,
      ),
      "card-hub",
    );
    for (const card of await copy
      .locator('.ld-card-hub [data-kind="card"]')
      .all()) {
      const target = await card.getAttribute("data-detail");
      await card.focus();
      await copy.keyboard.press("Enter");
      assert.ok(await copy.locator(`#${target}`).isVisible());
      await copy.keyboard.press("Escape");
    }
    await copy.close();
  }
  assert.deepEqual(errors, []);
  console.log(
    `PASS card-hub geometry, details, exports; visual evidence ${out}`,
  );
} finally {
  await browser.close();
}
