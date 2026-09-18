import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { existsSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { chromium } from "@playwright/test";

const repo = resolve(new URL("../../..", import.meta.url).pathname);
const out = mkdtempSync(join(tmpdir(), "legaldesign-popup-palette-"));
const source = join(out, "source.html");
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
  "popup-palette-test",
]);
const browser = await chromium.launch({
  headless: true,
  executablePath: [
    chromium.executablePath(),
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  ].find(existsSync),
});
const context = await browser.newContext({
  viewport: { width: 1440, height: 900 },
});
const page = await context.newPage();
await page.addInitScript(() =>
  Object.defineProperty(window, "showSaveFilePicker", {
    value: undefined,
    configurable: true,
  }),
);
page.setDefaultTimeout(5000);
const errors = [];
page.on("pageerror", (error) => errors.push(error.message));
async function drag(locator, dx, dy) {
  const box = await locator.boundingBox();
  assert.ok(box, "drag target must be visible");
  const x = box.x + box.width / 2;
  const y = box.y + box.height / 2;
  await page.mouse.move(x, y);
  await page.mouse.down();
  await page.mouse.move(x + dx, y + dy, { steps: 5 });
  await page.mouse.up();
}
try {
  await page.goto(pathToFileURL(source).href);
  await page.waitForFunction(() => window.LegalDesign?.state);
  if ((await page.locator("html").getAttribute("data-mode")) !== "edit")
    await page.locator("#mode-toggle").click();
  if (await page.locator("#editor-overflow-toggle").isVisible())
    await page.locator("#editor-overflow-toggle").click();
  await page.locator(".ld-palette-choices > button").click();
  const paletteGrounds = new Map();
  for (const palette of ["lavender", "mint", "sand", "default", "lavender"]) {
    await page.locator(`[data-palette-choice="${palette}"]`).click();
    assert.equal(
      await page.locator("html").getAttribute("data-palette"),
      palette,
    );
    assert.equal(
      await page.evaluate(() => window.LegalDesign.state().review.palette),
      palette,
    );
    for (const theme of ["dark", "light"]) {
      if ((await page.locator("html").getAttribute("data-theme")) !== theme)
        await page.locator("#theme-toggle").click();
      const ratios = await page.evaluate(() => {
        const style = getComputedStyle(document.documentElement);
        const ctx = document.createElement("canvas").getContext("2d");
        const luminance = (token) => {
          ctx.fillStyle = style.getPropertyValue(token).trim();
          ctx.fillRect(0, 0, 1, 1);
          const rgb = [...ctx.getImageData(0, 0, 1, 1).data]
            .slice(0, 3)
            .map((v) => {
              const c = v / 255;
              return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
            });
          return rgb[0] * 0.2126 + rgb[1] * 0.7152 + rgb[2] * 0.0722;
        };
        return ["--ink", "--muted", "--faint", "--red"].flatMap((foreground) =>
          ["--bg", "--card"].map((background) => {
            const a = luminance(foreground),
              b = luminance(background);
            return {
              foreground,
              background,
              ratio: (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05),
            };
          }),
        );
      });
      assert.ok(
        ratios.every(({ ratio }) => ratio >= 4.5),
        `${palette}/${theme} contrast: ${JSON.stringify(ratios)}`,
      );
      if (theme === "light")
        paletteGrounds.set(
          palette,
          await page.evaluate(
            () => getComputedStyle(document.body).backgroundColor,
          ),
        );
      await page.screenshot({ path: join(out, `${palette}-${theme}.png`) });
    }
  }
  assert.equal(
    new Set(paletteGrounds.values()).size,
    4,
    "Each palette must produce a distinct ground",
  );
  await page.evaluate(() => {
    const authority = document.createElement("style");
    authority.id = "test-firm-authority";
    authority.textContent = ":root { --bg: #ededeb; --red: #962d31; }";
    document.head.appendChild(authority);
  });
  await page.locator('[data-palette-choice="default"]').click();
  assert.equal(
    await page.evaluate(() => getComputedStyle(document.body).backgroundColor),
    "rgb(237, 237, 235)",
  );
  await page.locator('[data-palette-choice="lavender"]').click();
  assert.notEqual(
    await page.evaluate(() => getComputedStyle(document.body).backgroundColor),
    "rgb(237, 237, 235)",
  );
  await page.evaluate(() =>
    document.getElementById("test-firm-authority").remove(),
  );
  await page.locator("#mode-toggle").click();
  await page
    .locator("[data-detail]:visible,[data-evidence]:visible")
    .first()
    .click();
  const pop = page.locator("#popup-scrim .pop:visible");
  const popId = await pop.getAttribute("id");
  await pop.locator(".ld-popup-pencil").click();
  assert.equal(await page.locator("html").getAttribute("data-mode"), "edit");
  assert.equal(await page.locator(".ld-editor-tools").isVisible(), false);
  const text = pop.locator("h2[data-editable]").first();
  await text.dblclick();
  await page.keyboard.press("Meta+a");
  await page.keyboard.insertText("Edited popup heading");
  await pop.locator(".ld-popup-pencil").click();
  assert.equal(await text.textContent(), "Edited popup heading");
  await pop.locator(".ld-popup-pencil").click();
  const grip = pop.locator(".ld-popup-size-grip");
  const before = await pop.boundingBox();
  await grip.focus();
  await page.keyboard.press("ArrowLeft");
  assert.ok((await pop.boundingBox()).width < before.width);
  const keyboardWidth = (await pop.boundingBox()).width;
  await drag(grip, -15, -10);
  assert.ok((await pop.boundingBox()).width < keyboardWidth);
  const paragraph = pop.locator("[data-editable]").nth(1);
  const originalBox = await paragraph.boundingBox();
  await drag(paragraph, 14, 9);
  const movedBox = await paragraph.boundingBox();
  assert.ok(Math.abs(movedBox.x - originalBox.x - 14) < 1);
  assert.ok(Math.abs(movedBox.y - originalBox.y - 9) < 1);
  await drag(page.locator('.ld-handle[data-handle="e"]'), -25, 0);
  assert.ok((await paragraph.boundingBox()).width < movedBox.width - 20);
  await page.keyboard.press("Meta+z");
  await page.keyboard.press("Meta+z");
  assert.ok(Math.abs((await paragraph.boundingBox()).x - originalBox.x) < 1);
  const beforeCount = await pop.locator("[data-editable]").count();
  await paragraph.click();
  await page.keyboard.press("Delete");
  assert.equal(await pop.locator("[data-editable]").count(), beforeCount - 1);
  await page.keyboard.press("Meta+z");
  assert.equal(await pop.locator("[data-editable]").count(), beforeCount);
  const sectionCount = await pop.locator(".ld-popup-section").count();
  await pop
    .locator(".ld-popup-section h3")
    .first()
    .click({ modifiers: ["Alt"] });
  await page.keyboard.press("Delete");
  assert.equal(
    await pop.locator(".ld-popup-section").count(),
    sectionCount - 1,
  );
  const savedWidth = await pop.evaluate((el) => el.style.width);
  await page.screenshot({ path: join(out, "popup.png") });
  await pop.locator(".ld-popup-pencil").click();
  await pop.locator(".ld-popup-close,.pop-close").click();
  const download = page.waitForEvent("download");
  await page.evaluate(() => window.LegalDesign.save());
  const saved = join(out, "working.html");
  await (await download).saveAs(saved);
  const working = await context.newPage();
  await working.goto(pathToFileURL(saved).href);
  await working.waitForFunction(() => window.LegalDesign?.state);
  assert.equal(
    await working.locator("html").getAttribute("data-palette"),
    "lavender",
  );
  await working.locator(`[data-detail="${popId}"]`).click();
  assert.equal(
    await working.locator(`#${popId} .ld-popup-section`).count(),
    sectionCount - 1,
  );
  assert.equal(
    await working.locator(`#${popId}`).evaluate((el) => el.style.width),
    savedWidth,
  );
  assert.equal(await working.locator(`#${popId} .ld-popup-pencil`).count(), 1);
  await working.locator(`#${popId} .ld-popup-close`).click();
  await working.locator("#mode-toggle").click();
  await working.locator(`[data-detail="${popId}"]`).click();
  await working.locator("#editor-popup").click();
  await working.locator(`#${popId} .ld-popup-pencil`).click();
  assert.equal(await working.locator(".ld-editor-tools").isVisible(), false);
  await working.locator(`#${popId} .ld-popup-pencil`).click();
  await working.locator(`#${popId} .ld-popup-close`).click();
  assert.equal(
    await working.locator("html").getAttribute("data-mode"),
    "edit",
    "popup edit must restore the preceding page-edit mode",
  );
  await working.close();
  const reusable = await page.evaluate(() =>
    window.LegalDesign.exportTemplate(false),
  );
  writeFileSync(join(out, "template.html"), reusable);
  const template = await context.newPage();
  await template.goto(pathToFileURL(join(out, "template.html")).href);
  await template.waitForFunction(() => window.LegalDesign?.state);
  assert.equal(
    await template.locator("html").getAttribute("data-palette"),
    "lavender",
  );
  await template.locator('.ld-card-hub [data-kind="card"]').first().click();
  assert.equal(
    await template.locator(".pop:visible .ld-popup-pencil").count(),
    1,
  );
  assert.equal(
    await template.locator(".pop:visible").evaluate((el) => el.style.width),
    savedWidth,
  );
  await template.close();
  const client = await page.evaluate(() =>
    window.LegalDesign.exportHTML(false),
  );
  assert.doesNotMatch(
    client,
    /showSaveFilePicker|createWritable|persistHTML|\.download\s*=/,
  );
  assert.doesNotMatch(
    client,
    /class="ld-popup-pencil"|class="ld-popup-size-grip"/,
  );
  writeFileSync(join(out, "client.html"), client);
  const reopened = await context.newPage();
  await reopened.goto(pathToFileURL(join(out, "client.html")).href);
  await reopened.waitForFunction(() => window.LegalDesign?.state);
  assert.equal(
    await reopened.locator("html").getAttribute("data-palette"),
    "lavender",
  );
  await reopened
    .locator(`[data-detail="${popId}"],[data-evidence="${popId}"]`)
    .first()
    .click();
  assert.match(
    await reopened.locator(`#${popId}`).textContent(),
    /Edited popup heading/,
  );
  assert.equal(await reopened.locator(".ld-popup-pencil").count(), 0);
  assert.equal(
    await reopened.locator(`#${popId} .ld-popup-section`).count(),
    sectionCount - 1,
  );
  assert.equal(
    await reopened.locator(`#${popId}`).evaluate((el) => el.style.width),
    savedWidth,
  );
  assert.deepEqual(errors, []);
  console.log(
    `PASS popup-local text/resize/delete/undo, palette and reader export; evidence ${out}`,
  );
} finally {
  await browser.close();
}
