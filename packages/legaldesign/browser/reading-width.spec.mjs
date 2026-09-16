import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { existsSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { chromium } from "@playwright/test";

const repo = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
// A maintainer can supply an approved historical artifact for exact visual
// geometry comparison. Ordinary repository runs need no machine-local files.
const baseline = process.env.LEGALDESIGN_READING_BASELINE;
if (baseline)
  assert(
    existsSync(baseline),
    `Pinned layout reference not found: ${baseline}`,
  );
const out = mkdtempSync(join(tmpdir(), "legaldesign-reading-width-"));
console.log(`Reading-width evidence: ${out}`);
const source = join(out, "working.html");
const built = spawnSync(
  process.env.LEGALDESIGN_PYTHON || "python3",
  [
    "skills/core/legaldesign/scripts/scaffold.py",
    "compose",
    "--plan",
    "packages/legaldesign/fixtures/case-08-dense-diligence/plan.json",
    "--spec-output",
    join(out, "spec.json"),
    "--output",
    source,
    "--artifact-id",
    "reading-width-regression",
  ],
  { cwd: repo, encoding: "utf8" },
);
assert.equal(built.status, 0, built.stdout + built.stderr);
const browser = await chromium.launch({
  headless: true,
  executablePath: [
    chromium.executablePath(),
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  ].find(existsSync),
});
const errors = [];
const fitFailures = [];
const near = (actual, expected, label, tolerance = 1) =>
  assert(
    Math.abs(actual - expected) <= tolerance,
    `${label}: ${actual} instead of ${expected}`,
  );
async function settle(page) {
  await page.evaluate(
    () =>
      new Promise((resolve) =>
        requestAnimationFrame(() => requestAnimationFrame(resolve)),
      ),
  );
}
async function open(path, width, height) {
  const page = await browser.newPage({
    viewport: { width, height },
    deviceScaleFactor: 2,
    acceptDownloads: true,
  });
  // Exercise the supported browser download path without an OS file picker.
  await page.addInitScript(() =>
    Object.defineProperty(window, "showSaveFilePicker", {
      configurable: true,
      value: undefined,
    }),
  );
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto(pathToFileURL(path).href);
  await page.waitForFunction(
    () => document.documentElement.dataset.legaldesignReady === "true",
  );
  return page;
}
async function select(page, theme, approach) {
  if ((await page.locator("html").getAttribute("data-theme")) !== theme)
    await page.locator("#theme-toggle").click();
  const toggle = page.locator(`[data-select-approach="${approach}"]`);
  if (await toggle.count()) await toggle.click();
  await settle(page);
}
async function geometry(page) {
  return page.evaluate(() => {
    const active = document.querySelector(".ld-page-approach:not([hidden])");
    return [...active.querySelectorAll("section.ld-unit,h1,h2,p,svg")].map(
      (node) => {
        const rect = node.getBoundingClientRect();
        return {
          tag: node.tagName,
          id: node.getAttribute("data-unit") || "",
          text:
            node.tagName === "SECTION" || node.tagName === "svg"
              ? ""
              : node.textContent,
          x: rect.x,
          y: rect.y,
          width: rect.width,
          height: rect.height,
        };
      },
    );
  });
}
async function readingWidths(page, label) {
  const result = await page.evaluate(() => {
    const active = document.querySelector(".ld-page-approach:not([hidden])");
    const scale = Number(
      document.documentElement.style.getPropertyValue("--ld-page-scale"),
    );
    const widths = [...active.querySelectorAll('[data-kind="card"]')].map(
      (card) => {
        const probe = document.createElement("span");
        probe.style.cssText =
          "position:absolute;visibility:hidden;width:72ch;display:block";
        card.append(probe);
        const measure = probe.getBoundingClientRect().width / scale;
        probe.remove();
        const body = card.querySelector("[data-variant-body]");
        return {
          id: card.dataset.unit,
          width: card.getBoundingClientRect().width / scale,
          measure,
          body: body.getBoundingClientRect().width / scale,
        };
      },
    );
    return {
      widths,
      cappedCards: matchMedia("(min-width:1600px) and (min-aspect-ratio:8/5)")
        .matches,
      portraits: [
        ...active.querySelectorAll(
          "section:has(> .ld-variant svg.timeline-vertical)",
        ),
      ].map((node) => ({
        width: node.getBoundingClientRect().width / scale,
        svg: node.querySelector("svg").getBoundingClientRect().width / scale,
      })),
      fit: LegalDesign.checkPageFit(),
      issues: LegalDesign.lastPageFitIssues,
      scroll: {
        width: document.documentElement.scrollWidth,
        height: document.documentElement.scrollHeight,
        viewportWidth: innerWidth,
        viewportHeight: innerHeight,
      },
    };
  });
  assert(
    result.widths.length > 0,
    `${label}: non-vacuous card reading-width check`,
  );
  for (const card of result.cappedCards ? result.widths : []) {
    assert(
      card.width <= card.measure + 40.75,
      `${label} ${card.id}: ${JSON.stringify(card)}`,
    );
    assert(
      card.body <= card.measure + 0.75,
      `${label} ${card.id}: body exceeds72ch`,
    );
  }
  for (const portrait of result.portraits) {
    assert(
      portrait.width <= 510.75,
      `${label}: portrait panel ${portrait.width}`,
    );
    assert(portrait.svg <= 470.75, `${label}: portrait SVG ${portrait.svg}`);
  }
  if (!result.fit.valid)
    await page.screenshot({ path: join(out, `${label}-failure.png`) });
  if (!result.fit.valid)
    fitFailures.push(
      `${label}: ${JSON.stringify({ fit: result.fit, issues: result.issues })}`,
    );
  assert(
    result.scroll.width <= result.scroll.viewportWidth + 1,
    `${label}: main horizontal scroll`,
  );
  assert(
    result.scroll.height <= result.scroll.viewportHeight + 1,
    `${label}: main vertical scroll`,
  );
  return result;
}
async function sourcePopup(page, label) {
  await page
    .locator('.ld-page-approach:not([hidden]) [data-detail="valuation-record"]')
    .first()
    .click();
  const popup = page.locator("#valuation-record");
  await popup.waitFor({ state: "visible" });
  const result = await popup.evaluate((node) => {
    const rect = node.getBoundingClientRect();
    const img = node.querySelector("img.exhibit-shot"),
      image = img.getBoundingClientRect();
    const imageStyle = getComputedStyle(img);
    return {
      x: rect.x,
      y: rect.y,
      width: rect.width,
      height: rect.height,
      imageWidth:
        image.width -
        parseFloat(imageStyle.borderLeftWidth) -
        parseFloat(imageStyle.borderRightWidth),
      imageHeight:
        image.height -
        parseFloat(imageStyle.borderTopWidth) -
        parseFloat(imageStyle.borderBottomWidth),
      naturalWidth: img.naturalWidth,
      naturalHeight: img.naturalHeight,
      viewportWidth: innerWidth,
      viewportHeight: innerHeight,
      overflowX: node.scrollWidth - node.clientWidth,
      paragraphs: [...node.querySelectorAll(".ld-popup-section p")].map((p) => {
        const probe = document.createElement("span");
        probe.style.cssText =
          "position:absolute;visibility:hidden;width:72ch;display:block";
        p.append(probe);
        const max = probe.getBoundingClientRect().width;
        probe.remove();
        return { actual: p.getBoundingClientRect().width, max };
      }),
    };
  });
  assert(result.width <= 880.75, `${label}: source popup wider than880`);
  assert(
    result.x >= -1 && result.x + result.width <= result.viewportWidth + 1,
    `${label}: popup offscreen`,
  );
  assert(
    result.y >= -1 && result.y + result.height <= result.viewportHeight + 1,
    `${label}: popup outside viewport height`,
  );
  assert(result.overflowX <= 1, `${label}: popup has horizontal clipping`);
  assert(
    result.naturalWidth > 0 && result.imageWidth > 0,
    `${label}: source image loaded`,
  );
  near(
    result.imageWidth / result.imageHeight,
    result.naturalWidth / result.naturalHeight,
    `${label}: source image aspect ratio`,
    0.005,
  );
  assert(result.imageWidth <= result.width, `${label}: image wider than popup`);
  assert(
    result.imageWidth >= result.width * 0.7,
    `${label}: source image needlessly tiny`,
  );
  assert(
    result.paragraphs.length >= 2,
    `${label}: source-detail prose present`,
  );
  for (const paragraph of result.paragraphs)
    assert(
      paragraph.actual <= paragraph.max + 0.75,
      `${label}: popup paragraph wider than72ch`,
    );
  await page.screenshot({ path: join(out, `${label}-source.png`) });
  await popup.locator(".ld-popup-close").click();
}

try {
  for (const theme of ["light", "dark"]) {
    const before = baseline ? await open(baseline, 1280, 1000) : null;
    const after = await open(source, 1280, 1000);
    await select(after, theme, "b");
    if (before) {
      await select(before, theme, "b");
      const reference = await geometry(before),
        current = await geometry(after);
      assert.equal(
        current.length,
        reference.length,
        "pinned B retains its complete content structure",
      );
      for (const [index, expected] of reference.entries()) {
        const actual = current[index];
        for (const field of ["id", "tag", "text"])
          assert.equal(actual[field], expected[field]);
        for (const field of ["x", "y", "width", "height"])
          near(
            actual[field],
            expected[field],
            `pinned B ${theme} ${index}/${expected.id} ${field}`,
          );
      }
      await before.screenshot({
        path: join(out, `1280-${theme}-b-baseline.png`),
      });
      await before.close();
    }
    await readingWidths(after, `compact-${theme}-b`);
    await after.screenshot({ path: join(out, `1280-${theme}-b-current.png`) });
    await after.close();
    for (const approach of ["a", "b"]) {
      const page = await open(source, 2560, 1440);
      await select(page, theme, approach);
      const result = await readingWidths(page, `wide-${theme}-${approach}`);
      if (approach === "a")
        assert.equal(result.portraits.length, 1, "timeline panel measured");
      await page.screenshot({
        path: join(out, `wide-${theme}-${approach}.png`),
      });
      await sourcePopup(page, `wide-${theme}-${approach}`);
      const client = join(out, `${theme}-${approach}-client.html`);
      writeFileSync(
        client,
        await page.evaluate(() => LegalDesign.exportHTML(false)),
      );
      await page.setViewportSize({ width: 1280, height: 1000 });
      await settle(page);
      await readingWidths(page, `working-1280-${theme}-${approach}`);
      for (const [width, height] of [
        [2560, 1440],
        [1280, 1000],
        [390, 844],
      ]) {
        const reopened = await open(client, width, height);
        await readingWidths(reopened, `client-${width}-${theme}-${approach}`);
        if (width === 390)
          await sourcePopup(reopened, `phone-${theme}-${approach}`);
        await reopened.close();
      }
      await page.close();
    }
  }
  const editor = await open(source, 2560, 1440);
  await editor.locator("#mode-toggle").click();
  const card = editor.locator('[data-unit="a-finding"]');
  await card.click({ position: { x: 8, y: 8 } });
  const initial = await card.boundingBox();
  const handle = await editor
    .locator('.ld-handle[data-handle="e"]')
    .boundingBox();
  assert(handle, "whole-card resize handle is reachable");
  await editor.mouse.move(
    handle.x + handle.width / 2,
    handle.y + handle.height / 2,
  );
  await editor.mouse.down();
  await editor.mouse.move(
    handle.x + handle.width / 2 + 80,
    handle.y + handle.height / 2,
    { steps: 12 },
  );
  await editor.mouse.up();
  await settle(editor);
  const enlarged = await card.boundingBox();
  near(
    enlarged.width,
    initial.width + 80,
    "explicit editor resize can exceed default reading cap",
    2,
  );
  assert.equal(await card.evaluate((node) => node.style.maxWidth), "none");
  const download = editor.waitForEvent("download", { timeout: 10000 });
  await editor.locator("#ld-save").click();
  const saved = join(out, "resized-working.html");
  await (await download).saveAs(saved);
  await editor.locator("#mode-toggle").click();
  const delivered = join(out, "resized-client.html");
  writeFileSync(
    delivered,
    await editor.evaluate(() => LegalDesign.exportHTML(false)),
  );
  for (const path of [saved, delivered]) {
    const reopened = await open(path, 2560, 1440);
    const node = reopened.locator('[data-unit="a-finding"]');
    near(
      (await node.boundingBox()).width,
      enlarged.width,
      "explicit resize persists on reopen",
      2,
    );
    assert.equal(await node.evaluate((node) => node.style.maxWidth), "none");
    await reopened.close();
  }
  await editor.close();
  assert.deepEqual(errors, []);
  assert.deepEqual(
    fitFailures,
    [],
    "every tested working/client viewport must fit",
  );
  console.log(
    `PASS: ${baseline ? "pinned B geometry; " : ""}wide card/timeline reading measure; source popup/image; both themes; client/reopen; explicit editor resize. Screenshots: ${out}`,
  );
} finally {
  await browser.close();
}
