import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readdirSync,
  readFileSync,
  writeFileSync,
} from "node:fs";
import { homedir, tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { chromium } from "@playwright/test";
import Ajv2020 from "ajv/dist/2020.js";
import { runDiagramRefinementSuite } from "./diagram-refinement.spec.mjs";
import { runEditorAuthoringSuite } from "./editor-authoring.spec.mjs";
import { runSnapshotSuite } from "./snapshots.spec.ts";

const HERE = dirname(new URL(import.meta.url).pathname);
const REPO = resolve(HERE, "../../..");
const ASSETS = {
  stacked: join(REPO, "skills/core/legaldesign/assets/stacked-explainer.html"),
  walkthrough: join(REPO, "skills/core/legaldesign/assets/slide-brief.html"),
  report: join(REPO, "skills/core/legaldesign/assets/diligence-report.html"),
  method: join(REPO, "skills/core/legaldesign/assets/method-map.html"),
  library: join(REPO, "skills/core/legaldesign/assets/library.html"),
};
const TEMPLATE_ASSETS = {
  stacked: join(
    REPO,
    "skills/core/legaldesign/assets/templates/stacked-explainer.template.html",
  ),
  walkthrough: join(
    REPO,
    "skills/core/legaldesign/assets/templates/slide-brief.template.html",
  ),
  report: join(
    REPO,
    "skills/core/legaldesign/assets/templates/diligence-report.template.html",
  ),
  method: join(
    REPO,
    "skills/core/legaldesign/assets/templates/method-map.template.html",
  ),
};
const TEMPLATE_IMPORT = JSON.parse(
  readFileSync(
    join(
      REPO,
      "packages/legaldesign/fixtures/case-05-template-import/units.json",
    ),
    "utf8",
  ),
);
const SCAFFOLD = join(REPO, "skills/core/legaldesign/scripts/scaffold.py");
const NOVEL_COMPOSITION_PLAN = join(
  REPO,
  "packages/legaldesign/fixtures/case-06-novel-composition/plan.json",
);
const MATTER_TERMS = JSON.parse(
  readFileSync(
    join(REPO, "packages/legaldesign/fixtures/matter-terms.json"),
    "utf8",
  ),
);
const TERMS = MATTER_TERMS;
const TEMPLATE_BANS = JSON.parse(
  readFileSync(
    join(REPO, "packages/legaldesign/fixtures/mechanical-contract.json"),
    "utf8",
  ),
).templates.ban_list;
const STATE_SCHEMA = JSON.parse(
  readFileSync(
    join(REPO, "skills/core/legaldesign/schemas/state.schema.json"),
    "utf8",
  ),
);
const BUILD_SPEC_SCHEMA = JSON.parse(
  readFileSync(
    join(REPO, "skills/core/legaldesign/schemas/build-spec.schema.json"),
    "utf8",
  ),
);
const VALID_V2_SPEC = JSON.parse(
  readFileSync(
    join(REPO, "packages/legaldesign/fixtures/valid-build-spec.json"),
    "utf8",
  ),
);
const validateState = new Ajv2020({ allErrors: true, strict: false }).compile(
  STATE_SCHEMA,
);
const validateBuildSpec = new Ajv2020({
  allErrors: true,
  strict: false,
}).compile(BUILD_SPEC_SCHEMA);
const OUT = join(HERE, "out");
const EXPORTS_OUT = join(OUT, "exports");
const SOURCE_RUNTIME_OUT = join(OUT, "source-runtime");
const GROUP_FILTER = process.env.LEGALDESIGN_BROWSER_GROUP;
const GROUP_FROM = process.env.LEGALDESIGN_BROWSER_FROM;
let reachedStartGroup = !GROUP_FROM;
const WALKTHROUGH_URL = pathToFileURL(ASSETS.walkthrough).href;
const bundledExecutable = chromium.executablePath();
const systemExecutables = [
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  "/Applications/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
  "/Applications/Chromium.app/Contents/MacOS/Chromium",
];
const executable = existsSync(bundledExecutable)
  ? bundledExecutable
  : systemExecutables.find(existsSync);
const cache = join(homedir(), "Library/Caches/ms-playwright");

if (!executable) {
  console.log(
    `SKIP: LegalDesign browser tests: Chromium is not installed (${bundledExecutable}; cache ${cache}).`,
  );
  process.exit(0);
}

mkdirSync(OUT, { recursive: true });
mkdirSync(EXPORTS_OUT, { recursive: true });
mkdirSync(SOURCE_RUNTIME_OUT, { recursive: true });
const results = [];

function sourceRuntimeAsset(asset) {
  const start = "<!-- legaldesign:runtime -->";
  const end = "<!-- /legaldesign:runtime -->";
  const source = readFileSync(asset, "utf8");
  const from = source.indexOf(start);
  const to = source.indexOf(end, from + start.length);
  assert(from >= 0 && to > from, `${asset}: runtime markers are missing`);
  const runtimeRoot = join(REPO, "packages/legaldesign/runtime");
  const tokens = `<style id="ld-tokens">\n${readFileSync(join(runtimeRoot, "tokens.css"), "utf8").trimEnd()}\n</style>`;
  const block = `${start}\n<script id="ld-components">\n${readFileSync(join(runtimeRoot, "components.js"), "utf8").trimEnd()}\n</script>\n<script id="ld-runtime">\n${readFileSync(join(runtimeRoot, "runtime.js"), "utf8").trimEnd()}\n</script>\n${end}`;
  const path = join(
    SOURCE_RUNTIME_OUT,
    `${createHash("sha256").update(asset).digest("hex").slice(0, 12)}-${asset.split("/").at(-1)}`,
  );
  // The exporter intentionally discards styles outside the trusted head. Source
  // fixtures must install runtime CSS there, even when script markers are in body.
  const composed =
    source.slice(0, from) + block + source.slice(to + end.length);
  writeFileSync(path, composed.replace("</head>", `${tokens}\n</head>`));
  return path;
}

async function waitForLegalDesignReady(page, predicate) {
  await page.waitForFunction(
    predicate ||
      (() =>
        document.documentElement.getAttribute("data-legaldesign-ready") ===
        "true"),
  );
}

async function pageFor(options = {}) {
  // A browser per case keeps each fixture isolated without relying on Chromium's
  // single-process mode, which can close the target before page creation on Linux.
  const browser = await chromium.launch({
    headless: true,
    executablePath: executable,
  });
  const context = await browser.newContext({
    acceptDownloads: true,
    viewport: options.viewport || { width: 1280, height: 800 },
    colorScheme: options.colorScheme || "light",
    hasTouch: options.hasTouch || false,
  });
  await context.addInitScript(() => {
    Object.defineProperty(window, "showSaveFilePicker", {
      configurable: true,
      value: undefined,
    });
  });
  if (options.clearStorage !== false) {
    await context.addInitScript(() => {
      try {
        localStorage.clear();
      } catch {
        // A host may deny storage on file: URLs; the runtime has its own fallback.
      }
    });
  }
  const page = await context.newPage();
  const faults = [];
  page.on("console", (message) => {
    if (["error", "warning"].includes(message.type()))
      faults.push(`console ${message.type()}: ${message.text()}`);
  });
  page.on("pageerror", (error) => faults.push(`pageerror: ${error.message}`));
  await page.route("**/*", async (route) => {
    const protocol = new URL(route.request().url()).protocol;
    if (["file:", "data:", "blob:"].includes(protocol)) await route.continue();
    else {
      faults.push(`network: ${route.request().url()}`);
      await route.abort("blockedbyclient");
    }
  });
  const asset = ASSETS[options.asset || "stacked"];
  const pageAsset = options.sourceRuntime ? sourceRuntimeAsset(asset) : asset;
  await page.goto(options.url || pathToFileURL(pageAsset).href, {
    waitUntil: "load",
  });
  await waitForLegalDesignReady(page, options.ready);
  return { browser, context, page, faults };
}

async function closeClean(session) {
  await session.context.close();
  await session.browser.close();
  assert.deepEqual(session.faults, []);
}

async function run(name, body) {
  if (GROUP_FILTER && name !== GROUP_FILTER) return;
  if (!reachedStartGroup) {
    if (name !== GROUP_FROM) return;
    reachedStartGroup = true;
  }
  const started = Date.now();
  try {
    await body();
    const line = `PASS: ${name} (${Date.now() - started}ms)`;
    results.push(line);
    console.log(line);
  } catch (error) {
    console.error(`FAIL: ${name}`);
    throw error;
  }
}

async function downloadFrom(page, selector, name) {
  const pending = page.waitForEvent("download");
  pending.catch(() => {});
  await page.click(selector);
  if (await page.locator("[data-export-fit-error]:visible").count()) {
    assert.fail(
      `Export blocked by available-window fit: ${JSON.stringify(await page.evaluate(() => window.LegalDesign.lastPageFitIssues))}`,
    );
  }
  const download = await pending;
  const path = join(EXPORTS_OUT, name);
  await download.saveAs(path);
  return path;
}

async function stateFrom(page) {
  return page.evaluate(() =>
    JSON.parse(document.getElementById("legaldesign-state").textContent),
  );
}

function assertValidState(state, label) {
  assert(
    validateState(state),
    `${label}: ${JSON.stringify(validateState.errors, null, 2)}`,
  );
}

async function showUnit(page, unitId) {
  const frame = await page
    .locator(`[data-unit="${unitId}"]`)
    .evaluate((node) => {
      const legacy = node.closest("[data-frame]");
      if (legacy) return legacy.dataset.frame;
      const composed = node.closest("[data-composition-section]");
      return composed
        ? [
            ...composed.parentElement.querySelectorAll(
              ":scope > [data-composition-section]",
            ),
          ].indexOf(composed) + 1
        : null;
    });
  if (frame) {
    const navigation = page.locator(
      `.ld-slide-index [data-report-section="${Number(frame) - 1}"]`,
    );
    if (await navigation.count()) {
      if (!(await navigation.isVisible()))
        await page.locator(".ld-index-toggle").click();
      await navigation.click();
      return;
    }
  }
  await page.evaluate((id) => {
    const section = document.querySelector(`[data-unit="${id}"]`);
    const frame = section?.closest("[data-frame]")?.dataset.frame;
    if (!frame) return;
    if (typeof window.reportGoTo === "function")
      window.reportGoTo(Number(frame));
    else if (window.LegalDesignWalkthrough?.showFrame)
      window.LegalDesignWalkthrough.showFrame(Number(frame), true);
  }, unitId);
}

async function assertPageApproachContract(page, label = "artifact") {
  const switcher = page.locator("#ld-page-approach");
  assert.equal(await switcher.count(), 1, `${label}: page approach control`);
  assert.deepEqual(
    await switcher
      .locator("[data-select-approach]")
      .evaluateAll((buttons) =>
        buttons.map((button) => button.getAttribute("data-select-approach")),
      ),
    ["a", "b"],
    `${label}: page approach choices`,
  );
  assert.deepEqual(
    await page
      .locator("[data-approach]")
      .evaluateAll((roots) =>
        roots.map((root) => root.getAttribute("data-approach")),
      ),
    ["a", "b"],
    `${label}: full page approach roots`,
  );
  assert.equal(
    await page
      .locator(
        "section.ld-unit [data-select-variant],section.ld-unit > .ld-ab,section.ld-unit > .ld-unit-tools .ld-ab,section.ld-unit > .ld-why,section.ld-unit > .ld-unit-tools .ld-why-toggle",
      )
      .count(),
    0,
    `${label}: per-unit A/B controls remain`,
  );
}

async function selectPageApproach(page, approach, label = "artifact") {
  const button = page.locator(
    `#ld-page-approach [data-select-approach="${approach}"]`,
  );
  await button.click();
  assert.equal(
    (await stateFrom(page)).review.approach,
    approach,
    `${label}: portable approach state`,
  );
  assert.equal(
    await button.getAttribute("aria-pressed"),
    "true",
    `${label}: pressed approach`,
  );
  assert.equal(
    await page
      .locator(`[data-approach="${approach}"]`)
      .evaluate(
        (node) => !node.hidden && getComputedStyle(node).display !== "none",
      ),
    true,
    `${label}: selected approach root`,
  );
  assert(
    (await page
      .locator(
        `[data-approach="${approach}"].ld-fixed-page:visible, [data-approach="${approach}"] .ld-fixed-page:visible`,
      )
      .count()) > 0,
    `${label}: selected approach has no visible adaptive page`,
  );
  const other = approach === "a" ? "b" : "a";
  assert.equal(
    await page
      .locator(`[data-approach="${other}"]`)
      .evaluate((node) => node.hidden),
    true,
    `${label}: unselected approach root`,
  );
}

async function resetVisualCaptureState(page) {
  await page.evaluate(() => {
    window.LegalDesign?.closePopup?.();
    window.getSelection()?.removeAllRanges();
    if (typeof document.activeElement?.blur === "function")
      document.activeElement.blur();
    window.scrollTo(0, 0);
  });
  await page.waitForFunction(() => Math.abs(window.scrollY) < 1);
}

async function assertInteractionFocusContract(locator, label) {
  const focus = await locator.evaluate((node) => {
    node.focus();
    const style = getComputedStyle(node);
    const probe = document.createElement("span");
    probe.style.color = node.matches(
      "[data-detail],[data-evidence],[data-section-target]",
    )
      ? "var(--detail-feedback)"
      : "var(--interaction)";
    document.body.append(probe);
    const interaction = getComputedStyle(probe).color;
    probe.style.color = "var(--red)";
    const accent = getComputedStyle(probe).color;
    probe.remove();
    const shape = node.querySelector(
      ":scope > rect,:scope > path,:scope > circle,:scope > ellipse,:scope > polygon,:scope > polyline",
    );
    return {
      active: node === document.activeElement,
      outlineColor: style.outlineColor,
      outlineStyle: style.outlineStyle,
      outlineWidth: Number.parseFloat(style.outlineWidth) || 0,
      shapeStroke: shape ? getComputedStyle(shape).stroke : null,
      interaction,
      accent,
    };
  });
  assert.equal(focus.active, true, `${label}: target is not focused`);
  assert(
    (focus.outlineStyle !== "none" &&
      focus.outlineWidth >= 2 &&
      focus.outlineColor === focus.interaction) ||
      focus.shapeStroke === focus.interaction,
    `${label}: focus treatment is not the independent interaction color (${JSON.stringify(focus)})`,
  );
  assert.notEqual(
    focus.interaction,
    focus.accent,
    `${label}: focus and accent must be distinct`,
  );
  assert.notEqual(
    focus.outlineColor,
    "rgb(0, 122, 255)",
    `${label}: browser-blue focus leaked through`,
  );
  assert.notEqual(
    focus.shapeStroke,
    "rgb(0, 122, 255)",
    `${label}: browser-blue SVG focus leaked through`,
  );
}

async function assertPopupGeometry(popup, viewport, label) {
  await popup.waitFor({ state: "visible" });
  const box = await popup.boundingBox();
  assert(box, `${label}: popup has no rendered geometry`);
  assert(
    box.width >= Math.min(300, viewport.width - 32) && box.height >= 180,
    `${label}: popup is too small to be usable (${JSON.stringify(box)})`,
  );
  assert(
    box.x >= -1 &&
      box.y >= -1 &&
      box.x + box.width <= viewport.width + 1 &&
      box.y + box.height <= viewport.height + 1,
    `${label}: popup falls outside the viewport (${JSON.stringify(box)})`,
  );
  assert(
    (await popup.innerText()).trim().length >= 80,
    `${label}: popup rendered without its explanatory content`,
  );
}

async function composedVisualMetrics(page) {
  return page.evaluate(() => {
    const isVisible = (node) => {
      if (!(node instanceof Element)) return false;
      const style = getComputedStyle(node);
      const box = node.getBoundingClientRect();
      return (
        style.display !== "none" &&
        style.visibility !== "hidden" &&
        box.width > 0 &&
        box.height > 0
      );
    };
    const approach = document.querySelector(
      ".ld-page-approach[data-approach]:not([hidden])",
    );
    if (!approach) throw new Error("selected page approach is missing");
    const approachBox = approach.getBoundingClientRect();
    const approachStyle = getComputedStyle(approach);
    const pageScale = approachBox.width / approach.offsetWidth;
    const title = approach.querySelector('section.ld-unit[data-role="title"]');
    if (!title) throw new Error("descriptive title unit is missing");
    const titleBox = title.getBoundingClientRect();
    const titleStyle = getComputedStyle(title);
    const titleHeading = title.querySelector("h1");
    const titleHeadingBox = titleHeading?.getBoundingClientRect();
    const titleHeadingStyle = titleHeading
      ? getComputedStyle(titleHeading)
      : null;
    const units = [
      ...approach.querySelectorAll("section.ld-unit[data-unit]"),
    ].filter(isVisible);
    const unitState = window.LegalDesign.state().units;
    const groundedByUnit = units
      .filter(
        (unit) => (unitState[unit.dataset.unit]?.evidence || []).length > 0,
      )
      .map((unit) => unit.dataset.unit);
    const detailByUnit = [...approach.querySelectorAll("[data-detail]")]
      .filter(isVisible)
      .map((trigger) => ({
        id: trigger.closest("section.ld-unit[data-unit]")?.dataset.unit || null,
        target: trigger.getAttribute("data-detail"),
        role: trigger.getAttribute("role"),
        tabindex: trigger.getAttribute("tabindex"),
        popup: trigger.getAttribute("aria-haspopup"),
        cursor: getComputedStyle(trigger).cursor,
      }));
    const genericEvidenceChrome = [
      ...approach.querySelectorAll(
        ".ld-evidence-trigger,.ld-evidence-disclosure,[data-evidence-ids],[data-evidence-disclosure]",
      ),
    ].filter(isVisible).length;
    const sourceText = [];
    const walker = document.createTreeWalker(approach, NodeFilter.SHOW_TEXT, {
      acceptNode(node) {
        if (!node.textContent?.trim() || !isVisible(node.parentElement))
          return NodeFilter.FILTER_REJECT;
        return NodeFilter.FILTER_ACCEPT;
      },
    });
    while (walker.nextNode()) {
      const text = walker.currentNode.textContent.trim();
      if (/^source\s*:/i.test(text)) sourceText.push(text);
    }
    const cardUnits = units.filter((unit) => unit.dataset.kind === "card");
    const figureUnits = units.filter((unit) => unit.dataset.kind === "figure");
    const parseColor = (value) => {
      const parts = value.match(/[\d.]+/g)?.map(Number) || [];
      return parts.length >= 3 ? parts.slice(0, 3) : null;
    };
    const luminance = (value) => {
      const rgb = parseColor(value);
      if (!rgb) return null;
      const channels = rgb.map((channel) => {
        const ratio = channel / 255;
        return ratio <= 0.04045
          ? ratio / 12.92
          : ((ratio + 0.055) / 1.055) ** 2.4;
      });
      return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2];
    };
    const contrast = (foreground, background) => {
      const first = luminance(foreground);
      const second = luminance(background);
      if (first === null || second === null) return 0;
      return (
        (Math.max(first, second) + 0.05) / (Math.min(first, second) + 0.05)
      );
    };
    const rootStyle = getComputedStyle(document.documentElement);
    const bodyStyle = getComputedStyle(document.body);
    const designedContrast = [...cardUnits, ...figureUnits].map((unit) => {
      const style = getComputedStyle(unit);
      const background =
        style.backgroundColor === "rgba(0, 0, 0, 0)"
          ? bodyStyle.backgroundColor
          : style.backgroundColor;
      return {
        id: unit.dataset.unit,
        ratio: contrast(style.color, background),
      };
    });
    const hasVisibleShadow = (unit) =>
      [unit, ...unit.querySelectorAll("*")]
        .filter(isVisible)
        .some((node) => getComputedStyle(node).boxShadow !== "none");
    const shadowedCardUnits = cardUnits.filter(hasVisibleShadow);
    const shadowedFigureUnits = figureUnits.filter(hasVisibleShadow);
    const planarFigureUnits = figureUnits.filter((unit) => {
      const style = getComputedStyle(unit);
      return (
        style.boxShadow === "none" &&
        [
          style.borderTopWidth,
          style.borderRightWidth,
          style.borderBottomWidth,
          style.borderLeftWidth,
        ].every((width) => Number.parseFloat(width) <= 1)
      );
    });
    const shadowedUnits = units.filter((unit) =>
      [unit, ...unit.querySelectorAll("*")]
        .filter(isVisible)
        .some((node) => getComputedStyle(node).boxShadow !== "none"),
    );
    const horizontalClipping = units
      .filter((unit) => {
        const box = unit.getBoundingClientRect();
        const style = getComputedStyle(unit);
        const clipsOwnContent = ["hidden", "clip"].includes(style.overflowX);
        return (
          box.left < -1 ||
          box.right > window.innerWidth + 1 ||
          (clipsOwnContent && unit.scrollWidth > unit.clientWidth + 1)
        );
      })
      .map((unit) => unit.dataset.unit);
    const verticalClipping = units
      .filter((unit) => {
        const style = getComputedStyle(unit);
        return (
          ["hidden", "clip"].includes(style.overflowY) &&
          unit.scrollHeight > unit.clientHeight + 1
        );
      })
      .map((unit) => unit.dataset.unit);
    const figureTypography = figureUnits.map((unit) => {
      const svg = unit.querySelector(".ld-diagram svg");
      if (!svg)
        return {
          id: unit.dataset.unit,
          textCount: 0,
          minFontPx: 0,
          textOverflow: ["missing-svg"],
          nodeLabelOverflow: ["missing-svg"],
        };
      const svgBox = svg.getBoundingClientRect();
      const texts = [...svg.querySelectorAll("text")].filter(isVisible);
      const physicalFontPx = texts.map((text) => {
        const matrix = text.getScreenCTM();
        const scaleY = matrix ? Math.hypot(matrix.b, matrix.d) : 0;
        return (
          (Number.parseFloat(getComputedStyle(text).fontSize) || 0) * scaleY
        );
      });
      const textOverflow = texts
        .filter((text) => {
          const box = text.getBoundingClientRect();
          return (
            box.left < svgBox.left - 1 ||
            box.right > svgBox.right + 1 ||
            box.top < svgBox.top - 1 ||
            box.bottom > svgBox.bottom + 1
          );
        })
        .map((text) => text.textContent.trim());
      const nodeLabelOverflow = [
        ...svg.querySelectorAll("rect.box,rect.leaf"),
      ].flatMap((rect) => {
        const labels = [];
        for (
          let node = rect.nextElementSibling;
          node;
          node = node.nextElementSibling
        ) {
          if (node.matches("rect,path,line,circle,ellipse,polygon,polyline"))
            break;
          if (node.matches("text")) labels.push(node);
        }
        const rectBox = rect.getBoundingClientRect();
        return labels
          .filter((label) => {
            const box = label.getBoundingClientRect();
            return (
              box.left < rectBox.left - 1 ||
              box.right > rectBox.right + 1 ||
              box.top < rectBox.top - 1 ||
              box.bottom > rectBox.bottom + 1
            );
          })
          .map((label) => label.textContent.trim());
      });
      return {
        id: unit.dataset.unit,
        textCount: texts.length,
        minFontPx: physicalFontPx.length ? Math.min(...physicalFontPx) : 0,
        textOverflow,
        nodeLabelOverflow,
      };
    });
    const externalLinks = [...document.querySelectorAll('a[href^="http"]')].map(
      (link) => ({
        href: link.href,
        popup: Boolean(link.closest(".pop[data-evidence-id]")),
      }),
    );
    return {
      approach: approach.dataset.approach,
      pageScale,
      pageInsets: {
        left: parseFloat(approachStyle.paddingLeft) * pageScale,
        right: parseFloat(approachStyle.paddingRight) * pageScale,
      },
      viewport: { width: window.innerWidth, height: window.innerHeight },
      documentWidth: document.documentElement.scrollWidth,
      approachBox: {
        left: approachBox.left,
        right: approachBox.right,
        top: approachBox.top,
        bottom: approachBox.bottom,
        width: approachBox.width,
        height: approachBox.height,
      },
      titleBox: {
        left: titleBox.left,
        right: titleBox.right,
        top: titleBox.top,
        bottom: titleBox.bottom,
        width: titleBox.width,
      },
      titleContent: {
        text: titleHeading?.textContent?.trim() || "",
        width: titleHeadingBox?.width || 0,
        height: titleHeadingBox?.height || 0,
        display: titleHeadingStyle?.display || "missing",
        visibility: titleHeadingStyle?.visibility || "missing",
        color: titleHeadingStyle?.color || "missing",
        fontSize: parseFloat(titleHeadingStyle?.fontSize) || 0,
      },
      titleSurface: {
        background: titleStyle.backgroundColor,
        borderTop: titleStyle.borderTopWidth,
        borderRight: titleStyle.borderRightWidth,
        borderBottom: titleStyle.borderBottomWidth,
        borderLeft: titleStyle.borderLeftWidth,
        radius: titleStyle.borderRadius,
        shadow: titleStyle.boxShadow,
        paddingLeft: titleStyle.paddingLeft,
        paddingRight: titleStyle.paddingRight,
      },
      shadowSoft: rootStyle.getPropertyValue("--shadow-soft").trim(),
      unitCount: units.length,
      cardUnitCount: cardUnits.length,
      figureUnitCount: figureUnits.length,
      shadowedCardUnitCount: shadowedCardUnits.length,
      shadowedFigureUnitCount: shadowedFigureUnits.length,
      planarFigureUnitCount: planarFigureUnits.length,
      shadowedUnitCount: shadowedUnits.length,
      rootBackground: rootStyle.backgroundColor,
      bodyBackground: bodyStyle.backgroundColor,
      designedContrast,
      groundedByUnit,
      detailByUnit,
      genericEvidenceChrome,
      sourceText,
      externalLinks,
      horizontalClipping,
      verticalClipping,
      figureTypography,
      scrollY: window.scrollY,
    };
  });
}

async function composedLiveIdentity(page) {
  return page.evaluate(() => {
    const root = document.querySelector(
      ".ld-page-approach[data-approach]:not([hidden])",
    );
    if (!root) throw new Error("selected page approach is missing");
    const visible = (node) => {
      const style = getComputedStyle(node);
      const box = node.getBoundingClientRect();
      return (
        style.display !== "none" &&
        style.visibility !== "hidden" &&
        box.width > 0 &&
        box.height > 0
      );
    };
    const fixed = (value) => Number(value.toFixed(2));
    const nodes = [
      ...root.querySelectorAll(
        "[data-composition-section],section.ld-unit[data-unit],h1,h2,h3,p,article,ul,ol,table,.ld-diagram,.ld-diagram svg,[data-detail]",
      ),
    ].filter(visible);
    const geometryAndStyle = nodes.map((node) => {
      const box = node.getBoundingClientRect();
      const style = getComputedStyle(node);
      return {
        tag: node.tagName.toLowerCase(),
        className: node.getAttribute("class") || "",
        unit: node.closest("section.ld-unit[data-unit]")?.dataset.unit || null,
        detail: node.getAttribute("data-detail"),
        role: node.getAttribute("role"),
        tabindex: node.getAttribute("tabindex"),
        box: [fixed(box.x), fixed(box.y), fixed(box.width), fixed(box.height)],
        display: style.display,
        gridColumn: style.gridColumn,
        gridRow: style.gridRow,
        fontFamily: style.fontFamily,
        fontSize: style.fontSize,
        fontWeight: style.fontWeight,
        lineHeight: style.lineHeight,
        letterSpacing: style.letterSpacing,
        borderRadius: style.borderRadius,
        boxShadow: style.boxShadow,
        cursor: style.cursor,
        userSelect: style.userSelect,
      };
    });
    const style = getComputedStyle(document.documentElement);
    const colors = Object.fromEntries(
      [
        "--bg",
        "--card",
        "--card-strong",
        "--ink",
        "--muted",
        "--faint",
        "--line",
        "--line-strong",
        "--red",
        "--red-strong",
        "--red-wash",
        "--tint",
      ].map((name) => [name, style.getPropertyValue(name).trim()]),
    );
    return {
      markup: root.innerHTML,
      popupMarkup: document.getElementById("popup-scrim")?.innerHTML || "",
      geometryAndStyle,
      colors,
    };
  });
}

async function revealUnitTools(_page, unit) {
  // A selected text box can put its resize handle exactly at the containing
  // unit's centre. Hover real interior space rather than the overlay handle.
  await unit.hover({ position: { x: 16, y: 16 } });
  await unit.locator(":scope > .ld-unit-tools").waitFor({ state: "visible" });
}

async function dragEditorHandle(page, name, dx, dy) {
  const handle = page.locator(`.ld-handle[data-handle="${name}"]`);
  const box = await handle.boundingBox();
  assert(box, `missing ${name} resize handle`);
  const x = box.x + box.width / 2;
  const y = box.y + box.height / 2;
  await page.mouse.move(x, y);
  await page.mouse.down();
  await page.mouse.move(x + dx, y + dy, { steps: 4 });
  await page.mouse.up();
}

async function focusByKeyboard(page, locator, label = "control") {
  await page.evaluate(() => {
    if (typeof document.activeElement?.blur === "function")
      document.activeElement.blur();
  });
  for (let index = 0; index < 128; index += 1) {
    await page.keyboard.press("Tab");
    if (await locator.evaluate((node) => node === document.activeElement))
      return;
  }
  assert.fail(`${label}: keyboard tab order did not reach the target`);
}

async function assertFocusRing(locator, label = "control") {
  if (!(await locator.evaluate((node) => node === document.activeElement))) {
    let reached = false;
    for (let index = 0; index < 128; index += 1) {
      await locator.page().keyboard.press("Tab");
      if (await locator.evaluate((node) => node === document.activeElement)) {
        reached = true;
        break;
      }
    }
    assert(reached, `${label}: keyboard tab order did not reach the target`);
  }
  const ring = await locator.evaluate((node) => {
    const style = getComputedStyle(node);
    const namedWidths = { thin: 1, medium: 3, thick: 5 };
    const numericWidth = Number.parseFloat(style.outlineWidth);
    const shape = [
      ...node.querySelectorAll(
        ":scope > rect, :scope > path, :scope > circle, :scope > ellipse, :scope > polygon, :scope > polyline",
      ),
    ].find((candidate) => {
      const shapeStyle = getComputedStyle(candidate);
      return shapeStyle.stroke !== "none";
    });
    let shapeRing = false;
    if (shape) {
      const readShapeStyle = () => {
        const shapeStyle = getComputedStyle(shape);
        return {
          stroke: shapeStyle.stroke,
          strokeWidth: Number.parseFloat(shapeStyle.strokeWidth),
          filter: shapeStyle.filter,
        };
      };
      node.blur();
      const unfocused = readShapeStyle();
      node.focus();
      const focused = readShapeStyle();
      const focusVisible = node.matches(":focus-visible");
      const changed =
        focused.stroke !== unfocused.stroke ||
        focused.strokeWidth !== unfocused.strokeWidth ||
        focused.filter !== unfocused.filter;
      shapeRing =
        focusVisible &&
        changed &&
        focused.stroke !== "none" &&
        focused.strokeWidth >= 1.5;
    }
    return {
      active: node === document.activeElement,
      style: style.outlineStyle,
      width: Number.isNaN(numericWidth)
        ? namedWidths[style.outlineWidth] || 0
        : numericWidth,
      filter: style.filter,
      shapeRing,
    };
  });
  assert.equal(ring.active, true, `${label} is not focusable`);
  assert(
    (ring.style !== "none" && ring.width >= 2) ||
      ring.filter !== "none" ||
      ring.shapeRing,
    `${label} has no visible focus ring`,
  );
}

async function assertFocusReturned(page, target, label) {
  let returned = false;
  try {
    await page.waitForFunction(
      (expected) =>
        (document.activeElement?.getAttribute("data-detail") ||
          document.activeElement?.getAttribute("data-evidence")) === expected,
      target,
      { timeout: 1000 },
    );
    returned = true;
  } catch {
    // The assertion below supplies the stable concern-specific failure message.
  }
  const active = returned
    ? null
    : await page.evaluate(() => ({
        tag: document.activeElement?.tagName || null,
        id: document.activeElement?.id || null,
        className: document.activeElement?.getAttribute("class") || null,
        detail: document.activeElement?.getAttribute("data-detail") || null,
        evidence: document.activeElement?.getAttribute("data-evidence") || null,
      }));
  assert.equal(
    returned,
    true,
    `${label}: focus did not return; active element ${JSON.stringify(active)}`,
  );
}

function withoutRuntime(source) {
  return source
    .replace(
      /<script id="ld-client-runtime" type="application\/json">[\s\S]*?<\/script>/,
      "",
    )
    .replace(
      /<!-- legaldesign:runtime -->[\s\S]*?<!-- \/legaldesign:runtime -->/,
      "",
    );
}

function runScaffold(args) {
  const python =
    process.env.LEGALDESIGN_PYTHON ||
    process.env.PYTHON ||
    (process.platform === "win32" ? "python" : "python3");
  const result = spawnSync(python, [SCAFFOLD, ...args], {
    cwd: REPO,
    encoding: "utf8",
    env: process.env,
  });
  assert.equal(
    result.status,
    0,
    `${result.stdout || ""}${result.stderr || ""}`,
  );
  return result.stdout.trim() ? JSON.parse(result.stdout) : null;
}

function composedFixture({
  decision = false,
  multi = false,
  form = null,
  rich = false,
  design = false,
  approaches = false,
} = {}) {
  const directory = mkdtempSync(join(tmpdir(), "legaldesign-browser-"));
  let planPath = NOVEL_COMPOSITION_PLAN;
  if (decision || form || rich || design || approaches) {
    const plan = JSON.parse(readFileSync(NOVEL_COMPOSITION_PLAN, "utf8"));
    assert(plan.approaches?.a && plan.approaches?.b);
    assert(
      plan.units.every((unit) =>
        Object.keys(unit.variants || {}).every((key) => key === "a"),
      ),
      "v3 composed fixture must use one variant per approach-local unit",
    );
    if (decision) {
      const decisionUnit = plan.units.find((unit) => unit.id === "a-summary");
      assert(decisionUnit, "v3 fixture omitted the approach-A summary unit");
      Object.assign(decisionUnit, {
        kind: "decision",
        question: "Escalate for legal review?",
        selection_mode: multi ? "multiple" : "single",
        allow_custom: true,
        allow_note: true,
        options: [
          {
            key: "A",
            label: "Escalate now",
            consequence: "Legal review begins within the decision window.",
          },
          {
            key: "B",
            label: "Document and reassess",
            consequence: "The response team records the unmet trigger.",
          },
        ],
      });
    }
    if (form) plan.brief.form = form;
    if (rich) {
      plan.units.find((unit) => unit.id === "a-summary").variants.a.html =
        "<ul><li>ZZ-RICH-LIST-FIRST-7391</li><li>ZZ-RICH-LIST-SECOND-7391</li></ul>";
      plan.units.find((unit) => unit.id === "b-summary").variants.a.html =
        "<table><thead><tr><th>ZZ-RICH-HEADING-7391</th></tr></thead><tbody><tr><td>ZZ-RICH-VALUE-7391</td></tr></tbody></table>";
    }
    if (design) {
      const designPath = join(directory, "DESIGN.md");
      const authority = readFileSync(
        join(REPO, "skills/core/legaldesign/DESIGN.md"),
        "utf8",
      )
        .replace("status: unconfigured", "status: configured")
        .replace("--red #c92014", "--red #123456")
        .replace("--red #ff5a4e", "--red #ff8a80");
      writeFileSync(designPath, authority);
      plan.style = { source: "design-md", ref: designPath };
    }
    planPath = join(directory, "modified-plan.json");
    writeFileSync(planPath, `${JSON.stringify(plan, null, 2)}\n`);
  }
  const spec = join(directory, "artifact.spec.json");
  const html = join(directory, "artifact.html");
  const receipt = runScaffold([
    "compose",
    "--plan",
    planPath,
    "--spec-output",
    spec,
    "--output",
    html,
    "--artifact-id",
    [
      "browser",
      decision ? "decision" : "composition",
      multi ? "multi" : null,
      form,
      rich ? "rich" : null,
      design ? "design" : null,
      approaches ? "approaches" : null,
    ]
      .filter(Boolean)
      .join("-"),
  ]);
  return { directory, spec, html, receipt };
}

await run("v2 build schema excludes v3-only fields", async () => {
  assert.equal(
    validateBuildSpec(VALID_V2_SPEC),
    true,
    validateBuildSpec.errors,
  );
  const cases = [
    [
      "missing non-single v2 B variant",
      (spec) => delete spec.units[0].variants.b,
    ],
    ["composition", (spec) => (spec.composition = {})],
    ["approaches", (spec) => (spec.approaches = { a: {}, b: {} })],
    ["claims", (spec) => (spec.claims = [])],
    ["unit claimRefs", (spec) => (spec.units[0].claimRefs = ["claim-1"])],
    ["decision fields", (spec) => (spec.units[0].question = "Choose?")],
    [
      "variant encoding",
      (spec) => (spec.units[0].variants.a.encoding = "Reading order."),
    ],
    ["evidence fields", (spec) => (spec.evidence[0].sourceId = "memo")],
  ];
  for (const [label, mutate] of cases) {
    const spec = structuredClone(VALID_V2_SPEC);
    mutate(spec);
    assert.equal(
      validateBuildSpec(spec),
      false,
      `${label}: ${JSON.stringify(validateBuildSpec.errors)}`,
    );
  }
});

await run("v3 popup target and decision validator contract", async () => {
  const validateWithScaffold = (spec, name) => {
    const directory = mkdtempSync(join(tmpdir(), "legaldesign-validator-"));
    const path = join(directory, `${name}.json`);
    writeFileSync(path, `${JSON.stringify(spec, null, 2)}\n`);
    const python =
      process.env.LEGALDESIGN_PYTHON ||
      process.env.PYTHON ||
      (process.platform === "win32" ? "python" : "python3");
    const result = spawnSync(
      python,
      [SCAFFOLD, "validate", "--spec", path, "--json"],
      { cwd: REPO, encoding: "utf8", env: process.env },
    );
    assert.equal(
      result.status,
      1,
      `${name}: ${result.stdout || ""}${result.stderr || ""}`,
    );
    return JSON.parse(result.stdout);
  };

  const missingTargets = JSON.parse(
    readFileSync(NOVEL_COMPOSITION_PLAN, "utf8"),
  );
  let removed = 0;
  const removeDetails = (value) => {
    if (Array.isArray(value)) {
      value.forEach(removeDetails);
      return;
    }
    if (!value || typeof value !== "object") return;
    for (const key of Object.keys(value)) {
      if (key.toLowerCase().endsWith("detail")) {
        delete value[key];
        removed += 1;
      } else {
        removeDetails(value[key]);
      }
    }
  };
  for (const unit of missingTargets.units) {
    for (const variant of Object.values(unit.variants || {})) {
      if (variant.component) removeDetails(variant.params);
    }
  }
  assert(removed > 0);
  assert(missingTargets.units.some((unit) => unit.evidence?.length));
  const missingTargetReport = validateWithScaffold(
    missingTargets,
    "missing-component-popup-targets",
  );
  assert.equal(missingTargetReport.valid, false);
  for (const [approach, claim] of [
    ["a", "c-input"],
    ["a", "c-judgment"],
    ["b", "c-input"],
    ["b", "c-judgment"],
    ["b", "c-output"],
  ]) {
    assert(
      missingTargetReport.errors.some((error) =>
        error.includes(
          `$.approaches.${approach}: presented material claim '${claim}' has no actual popup target`,
        ),
      ),
      `${approach}/${claim}: ${JSON.stringify(missingTargetReport.errors)}`,
    );
  }

  const nearClone = JSON.parse(readFileSync(NOVEL_COMPOSITION_PLAN, "utf8"));
  const remap = {
    "a-title": "b-title",
    "a-summary": "b-summary",
    "a-flow": "b-hierarchy",
    "a-output": "b-output",
  };
  for (const [sourceId, targetId] of Object.entries(remap)) {
    const source = nearClone.units.find((unit) => unit.id === sourceId);
    const targetIndex = nearClone.units.findIndex(
      (unit) => unit.id === targetId,
    );
    assert(source && targetIndex >= 0);
    nearClone.units[targetIndex] = { ...structuredClone(source), id: targetId };
  }
  const mirroredComposition = structuredClone(
    nearClone.approaches.a.composition,
  );
  mirroredComposition.sections.forEach((section, index) => {
    section.id = `b-mirror-${index + 1}`;
    section.unitIds = section.unitIds.map((unitId) => remap[unitId]);
    section.layout.placements.forEach((placement) => {
      placement.unitId = remap[placement.unitId];
      if (placement.unitId === "b-output") {
        placement.column = 2;
        placement.span = 11;
      }
    });
  });
  nearClone.approaches.b.composition = mirroredComposition;
  const nearCloneReport = validateWithScaffold(
    nearClone,
    "near-clone-one-moved-box",
  );
  assert(
    nearCloneReport.errors.some(
      (error) =>
        error.includes("at least two independent structural dimensions") &&
        error.includes("differences found: placement topology"),
    ),
    JSON.stringify(nearCloneReport.errors),
  );

  const decisionSpec = JSON.parse(readFileSync(NOVEL_COMPOSITION_PLAN, "utf8"));
  const decision = decisionSpec.units.find((unit) => unit.id === "a-summary");
  assert(decision);
  Object.assign(decision, {
    kind: "decision",
    detail: "e-input",
    question: "Escalate for legal review?",
    selection_mode: "single",
    allow_custom: true,
    allow_note: true,
    options: [
      {
        key: "A",
        label: "Escalate now",
        consequence: "Legal review begins within the decision window.",
      },
      {
        key: "B",
        label: "Document and reassess",
        consequence: "The response team records the unmet trigger.",
      },
    ],
  });
  assert.equal(
    validateBuildSpec(decisionSpec),
    false,
    JSON.stringify(validateBuildSpec.errors),
  );
  const decisionReport = validateWithScaffold(
    decisionSpec,
    "decision-unit-popup-target",
  );
  assert(
    decisionReport.errors.some((error) =>
      error.includes("a decision unit must not use a unit-level popup target"),
    ),
    JSON.stringify(decisionReport.errors),
  );
});

await run("dark ground", async () => {
  for (const asset of Object.keys(ASSETS)) {
    const session = await pageFor({ asset });
    await session.page.click("#theme-toggle");
    const colors = await session.page.evaluate(() => [
      getComputedStyle(document.documentElement).backgroundColor,
      getComputedStyle(document.body).backgroundColor,
    ]);
    assert.deepEqual(
      colors,
      ["rgb(0, 0, 0)", "rgb(0, 0, 0)"],
      `${asset} dark ground`,
    );
    await closeClean(session);
  }
});

await run("component semantic accent contract", async () => {
  const session = await pageFor({ sourceRuntime: true });
  const result = await session.page.evaluate(() => {
    const render = (id, data, opts = {}) => {
      const host = document.createElement("div");
      host.innerHTML = window.LegalDesign.render(id, data, opts);
      document.body.append(host);
      return host;
    };
    const modes = [{}, { narrow: true }, { compact: true }];
    const structural = [
      [
        "beforeAfter",
        {
          orientation: "horizontal",
          beforeLabel: "Before",
          beforeSub: "Starting state",
          edge: "changes",
          afterLabel: "After",
          afterSub: "Arrival state",
        },
      ],
      [
        "hub",
        {
          centre: "Centre",
          toward: "centre",
          spokes: [
            { title: "A", edge: "a" },
            { title: "B", edge: "b" },
            { title: "C", edge: "c" },
          ],
        },
      ],
      [
        "funnel",
        {
          tiers: [{ title: "All" }, { title: "Filtered" }],
          edges: ["screen"],
          outcome: "Outcome",
        },
      ],
      [
        "loop",
        {
          centre: "Cycle",
          steps: [
            { title: "A", edge: "then" },
            { title: "B", edge: "then" },
            { title: "C", edge: "repeat" },
          ],
        },
      ],
    ];
    const structuralAccentCounts = structural.flatMap(([id, data]) =>
      modes.map((opts) => {
        const host = render(id, data, opts);
        const count = host.querySelectorAll(".accent,.open,.open-line").length;
        host.remove();
        return {
          id,
          mode: opts.compact ? "compact" : opts.narrow ? "narrow" : "wide",
          count,
        };
      }),
    );
    const compare = render(
      "compareTwo",
      {
        a: "A",
        b: "B",
        highlight: "a",
        rows: [
          { label: "One", a: "First", b: "Second", winner: "a" },
          { label: "Two", a: "Third", b: "Fourth", winner: "b" },
        ],
      },
      { narrow: true },
    );
    const compareMetrics = {
      accentCount: compare.querySelectorAll(".accent,.open,.open-line").length,
      neutralTintCount: compare.querySelectorAll(".box.tint").length,
    };
    compare.remove();
    const flowData = {
      stages: [
        { title: "Input" },
        { title: "Decision", accentRole: "decision" },
      ],
      edges: ["choose"],
    };
    const hierarchyData = {
      root: "Goal",
      branches: [
        { title: "Input", edge: "define" },
        { title: "Decision", edge: "shape", accentRole: "decision" },
      ],
    };
    const semanticCounts = [
      ...modes.map((opts) => {
        const host = render("flow", flowData, opts);
        const count = host.querySelectorAll(
          '.box.accent[data-accent-role="decision"]',
        ).length;
        host.remove();
        return { id: "flow", count };
      }),
      ...modes.map((opts) => {
        const host = render("hierarchy", hierarchyData, opts);
        const count = host.querySelectorAll(
          '.box.accent[data-accent-role="decision"]',
        ).length;
        host.remove();
        return { id: "hierarchy", count };
      }),
    ];
    const timeline = render(
      "timeline",
      {
        marks: [
          { when: "Now", title: "A" },
          { when: "Next", title: "B" },
          { when: "Later", title: "C" },
        ],
        nowAt: 1,
      },
      { compact: true },
    );
    const timelineActive = timeline.querySelectorAll(
      '[data-accent-role="active"]',
    ).length;
    timeline.remove();
    let invalidRejected = false;
    try {
      window.LegalDesign.render("flow", {
        stages: [
          { title: "Input" },
          { title: "Outcome", accentRole: "outcome" },
        ],
        edges: ["then"],
      });
    } catch {
      invalidRejected = true;
    }
    const darkFlow = render("flow", flowData, { theme: "dark" });
    const darkAccent = darkFlow.querySelector(".box.accent");
    const darkNeutral = darkFlow.querySelector(".box:not(.accent)");
    const darkFlowStyles = {
      accentFill: getComputedStyle(darkAccent).fill,
      neutralFill: getComputedStyle(darkNeutral).fill,
      accentStroke: getComputedStyle(darkAccent).stroke,
      neutralStroke: getComputedStyle(darkNeutral).stroke,
    };
    darkFlow.remove();
    const darkChart = render(
      "rungBars",
      {
        items: [
          { label: "Open", value: 2, open: true },
          { label: "Closed", value: 2 },
        ],
        unit: "items",
        yAxisTitle: "Count",
        sourceNote: "Supplied record",
      },
      { theme: "dark" },
    );
    const darkChartOpen = darkChart.querySelector(".fill.open");
    const darkChartNeutral = darkChart.querySelector(".fill:not(.open)");
    const darkChartStyles = {
      accentFill: getComputedStyle(darkChartOpen).fill,
      neutralFill: getComputedStyle(darkChartNeutral).fill,
      accentStroke: getComputedStyle(darkChartOpen).stroke,
      neutralStroke: getComputedStyle(darkChartNeutral).stroke,
    };
    darkChart.remove();
    return {
      structuralAccentCounts,
      compareMetrics,
      semanticCounts,
      timelineActive,
      invalidRejected,
      darkFlowStyles,
      darkChartStyles,
    };
  });
  assert(
    result.structuralAccentCounts.every(({ count }) => count === 0),
    JSON.stringify(result.structuralAccentCounts),
  );
  assert.deepEqual(result.compareMetrics, {
    accentCount: 0,
    neutralTintCount: 2,
  });
  assert(
    result.semanticCounts.every(({ count }) => count === 1),
    JSON.stringify(result.semanticCounts),
  );
  assert(result.timelineActive >= 1);
  assert.equal(result.invalidRejected, true);
  assert.equal(
    result.darkFlowStyles.neutralFill,
    "rgb(17, 17, 17)",
    "dark diagram neutral nodes must use the raised card fill",
  );
  assert.equal(
    result.darkFlowStyles.accentFill,
    "rgb(17, 17, 17)",
    "dark diagram semantic accent must keep the raised card fill",
  );
  assert.notEqual(
    result.darkFlowStyles.accentStroke,
    result.darkFlowStyles.neutralStroke,
    "dark diagram semantic accent outline must differ from neutral nodes",
  );
  assert.equal(
    result.darkChartStyles.accentFill,
    result.darkChartStyles.neutralFill,
    "chart quantitative fill encoding stays intact",
  );
  for (const [label, styles] of [
    ["diagram", result.darkFlowStyles],
    ["chart", result.darkChartStyles],
  ]) {
    assert.notEqual(
      styles.accentStroke,
      styles.neutralStroke,
      `${label} semantic outline`,
    );
  }
  await closeClean(session);
});

await run("controls and keyboard", async () => {
  const session = await pageFor({ sourceRuntime: true });
  const { page } = session;
  const visibleIds = await page
    .locator("button:visible")
    .evaluateAll((buttons) =>
      buttons.map((button) => button.id).filter(Boolean),
    );
  assert.deepEqual(visibleIds, [
    "mode-toggle",
    "theme-toggle",
    "export-html",
    "export-template",
    "ld-read-page",
  ]);
  await page.focus("#mode-toggle");
  assert.match(
    await page
      .locator("#mode-toggle")
      .evaluate((node) => getComputedStyle(node).outline),
    /2px/,
  );
  await page.keyboard.press("Enter");
  await page.waitForFunction(
    () => document.documentElement.dataset.mode === "edit",
  );
  assert.equal(
    await page
      .locator(
        ".ld-review,.ld-reaction,.ld-comment,.ld-sheet-open,.ld-bottom-save,.ld-phone-sheet,.ld-selection-popover",
      )
      .count(),
    0,
  );
  assert.equal(await page.locator(".ld-unit-tools:visible").count(), 0);
  assert.equal(await page.locator('[contenteditable="true"]').count(), 0);
  const contextualUnit = page
    .locator("section.ld-unit:has(.ld-unit-tools)")
    .first();
  const contextualBefore = await contextualUnit.boundingBox();
  await contextualUnit.hover();
  const contextualTools = contextualUnit.locator(":scope > .ld-unit-tools");
  assert.equal(await contextualTools.isVisible(), true);
  const contextualHeights = await contextualTools
    .locator("button")
    .evaluateAll((nodes) =>
      nodes.map((node) => node.getBoundingClientRect().height),
    );
  assert(contextualHeights.every((height) => height >= 25 && height <= 30));
  const contextualAfter = await contextualUnit.boundingBox();
  assert.equal(contextualAfter.width, contextualBefore.width);
  assert.equal(contextualAfter.height, contextualBefore.height);
  await page.locator("#mode-toggle").hover();
  assert.equal(await page.locator(".ld-unit-tools:visible").count(), 0);
  for (const id of [
    "ld-save",
    "editor-undo",
    "editor-redo",
    "editor-duplicate",
    "editor-delete",
    "editor-bold",
    "editor-italic",
    "editor-underline",
    "editor-font-up",
    "editor-font-down",
    "editor-reset",
    "editor-fill-palette",
    "editor-text-palette",
    "editor-add-text",
    "editor-popup",
    "editor-remove-popup",
  ]) {
    await assert.doesNotReject(() =>
      page.locator(`#${id}`).waitFor({ state: "visible" }),
    );
  }
  await page.focus("#theme-toggle");
  await page.keyboard.press("Space");
  assert.equal(await page.locator("html").getAttribute("data-theme"), "dark");
  await page.screenshot({
    path: join(OUT, "stacked-editor-1280x800-dark.png"),
    fullPage: false,
  });
  await closeClean(session);
});

await run("toolbar controls normalize across authored assets", async () => {
  for (const asset of Object.keys(ASSETS).filter(
    (name) => name !== "library",
  )) {
    const session = await pageFor({ asset, sourceRuntime: true });
    const titleWidths = await session.page
      .locator(
        ".ld-title h1:visible,.sb-title h1:visible,.sb-title .sb-sub:visible,.subtitle:visible",
      )
      .evaluateAll((nodes) =>
        nodes.map((node) => {
          const parent = node.parentElement;
          const style = getComputedStyle(parent);
          const scale =
            parent.getBoundingClientRect().width / parent.offsetWidth;
          return {
            actual: node.getBoundingClientRect().width,
            available:
              (parent.clientWidth -
                parseFloat(style.paddingLeft) -
                parseFloat(style.paddingRight)) *
              scale,
          };
        }),
      );
    assert(titleWidths.length > 0, `${asset}: no page title/subtitle checked`);
    for (const reserved of await session.page
      .locator(".sb-title:visible")
      .evaluateAll((nodes) =>
        nodes.map((node) => parseFloat(getComputedStyle(node).paddingRight)),
      ))
      assert.equal(
        reserved,
        0,
        `${asset}: obsolete title control gutter remains`,
      );
    for (const width of titleWidths)
      assert(
        Math.abs(width.actual - width.available) <= 2,
        `${asset}: title/subtitle must fill its available frame (${JSON.stringify(width)})`,
      );
    assert.deepEqual(
      await session.page
        .locator(".ld-controls > button:visible")
        .evaluateAll((buttons) => buttons.map((button) => button.id)),
      ["mode-toggle", "theme-toggle", "export-html", "export-template"],
      `${asset}: top controls diverged`,
    );
    assert.equal(
      await session.page.locator("#editor-overflow-toggle").textContent(),
      "More",
      `${asset}: overflow label diverged`,
    );
    const editorTokens = {
      "editor-fill-token": ["", "card", "card-strong", "tint", "bg", "none"],
      "editor-text-token": ["", "ink", "muted", "faint", "red", "red-strong"],
    };
    for (const [id, expected] of Object.entries(editorTokens)) {
      assert.deepEqual(
        await session.page
          .locator(`#${id} option`)
          .evaluateAll((options) => options.map((option) => option.value)),
        expected,
        `${asset}: palette diverged`,
      );
    }
    if (asset === "stacked-explainer") {
      await session.page.click("#mode-toggle");
      const target = session.page.locator("[data-editable]:visible").first();
      await target.click();
      await session.page.evaluate(() => {
        const fill = document.getElementById("editor-fill-token");
        const text = document.getElementById("editor-text-token");
        fill.insertAdjacentHTML(
          "beforeend",
          '<option value="red">red</option>',
        );
        fill.value = "red";
        fill.dispatchEvent(new Event("change", { bubbles: true }));
        text.insertAdjacentHTML(
          "beforeend",
          '<option value="line">line</option>',
        );
        text.value = "line";
        text.dispatchEvent(new Event("change", { bubbles: true }));
      });
      assert.equal(await target.getAttribute("data-fill-token"), null);
      assert.equal(await target.getAttribute("data-text-token"), null);
    }
    assert.deepEqual(
      await session.page.locator("*").evaluateAll((nodes) =>
        nodes
          .filter((node) => {
            const style = getComputedStyle(node);
            return (
              style.animationName !== "none" ||
              style.transitionDuration
                .split(",")
                .some((duration) => Number.parseFloat(duration) > 0)
            );
          })
          .map((node) => node.id || node.className || node.tagName),
      ),
      [],
      `${asset}: motion remains enabled`,
    );
    await closeClean(session);
  }
});

await run(
  "editor units and contextual treatments are keyboard reachable",
  async () => {
    const session = await pageFor({ sourceRuntime: true });
    const { page } = session;
    await page.focus("#mode-toggle");
    await page.keyboard.press("Space");
    await page.focus("#export-template");
    await page.keyboard.press("Tab");
    const firstUnit = page
      .locator("section.ld-unit[data-unit]:visible")
      .first();
    for (let index = 0; index < 64; index++) {
      if (await firstUnit.evaluate((node) => node === document.activeElement))
        break;
      const inNavigation = await page
        .locator(":focus")
        .evaluate((node) => !!node.closest(".ld-slide-index"));
      assert(
        inNavigation,
        "only the explicit page-navigation controls may precede the first editable unit",
      );
      await page.keyboard.press("Tab");
    }
    const activeAfterToolbar = await page
      .locator(":focus")
      .evaluate((node) => ({
        id: node.id,
        className: node.className,
        tagName: node.tagName,
        unit: node.getAttribute("data-unit"),
      }));
    assert.equal(
      await firstUnit.evaluate((node) => node === document.activeElement),
      true,
      `unexpected tab stop after toolbar: ${JSON.stringify(activeAfterToolbar)}`,
    );
    assert.equal(
      await firstUnit
        .locator(":scope > .ld-unit-tools")
        .evaluate((node) => getComputedStyle(node).display),
      "flex",
    );
    await page.keyboard.press("Enter");
    const selected = firstUnit.locator(".ld-selected").first();
    assert.equal(await selected.count(), 1);
    assert.equal(await page.locator("#editor-delete").isDisabled(), false);
    await page.keyboard.press("Enter");
    assert.equal(
      await firstUnit.locator('[contenteditable="true"]').count(),
      1,
    );
    await page.keyboard.press("Escape");
    await closeClean(session);
  },
);

await run("editor parity selection text history and reset", async () => {
  const session = await pageFor({ sourceRuntime: true });
  const { page } = session;
  const selector =
    '[data-unit="u-title"] [data-variant="a"] [data-editable]:visible';
  const editable = page.locator(selector).first();
  await editable.evaluate((node) => {
    node.style.letterSpacing = "1.25px";
    node.setAttribute("data-text-token", "muted");
  });
  const authoredStyle = await editable.getAttribute("style");
  await page.click("#mode-toggle");
  assert.equal(await page.locator('[contenteditable="true"]').count(), 0);

  await editable.click();
  assert.equal(await editable.getAttribute("contenteditable"), null);
  assert.equal(
    await editable.evaluate((node) => node.classList.contains("ld-selected")),
    true,
  );
  assert.equal(
    await page
      .locator("#ld-selection-box")
      .evaluate((node) => getComputedStyle(node).display),
    "block",
  );
  assert.equal(
    await editable.evaluate((node) => getComputedStyle(node).outlineStyle),
    "none",
  );
  await page.keyboard.press("Escape");
  assert.equal(await page.locator(".ld-selected").count(), 0);
  assert.equal(
    await page
      .locator("#ld-selection-box")
      .evaluate((node) => getComputedStyle(node).display),
    "none",
  );

  await editable.dblclick();
  assert.equal(await page.locator('[contenteditable="true"]').count(), 1);
  await editable.fill("Edited title survives later rendering.");
  await editable.blur();
  assert.match(
    (await stateFrom(page)).units["u-title"].edits.a,
    /Edited title/,
  );

  await editable.click();
  const initialWeight = await editable.evaluate(
    (node) => getComputedStyle(node).fontWeight,
  );
  await page.click("#editor-bold");
  const toggledWeight = await editable.evaluate(
    (node) => node.style.fontWeight,
  );
  assert.notEqual(toggledWeight, initialWeight);
  await page.click("#editor-undo");
  assert.equal(
    await page
      .locator(selector)
      .first()
      .evaluate((node) => node.style.fontWeight),
    "",
  );
  await page.click("#editor-redo");
  assert.equal(
    await page
      .locator(selector)
      .first()
      .evaluate((node) => node.style.fontWeight),
    toggledWeight,
  );

  await page.locator(selector).first().click();
  await page.click("#editor-text-palette");
  await page.click('#ld-color-palette [data-color-token="red"]');
  await page.click("#editor-font-up");
  await page.click("#editor-reset");
  const reset = page.locator(selector).first();
  assert.equal(await reset.getAttribute("style"), authoredStyle);
  assert.equal(await reset.getAttribute("data-text-token"), "muted");

  await revealUnitTools(page, page.locator('[data-unit="u-title"]'));
  await page.click('[data-unit="u-title"] [data-select-variant="b"]');
  await page.click('[data-unit="u-title"] [data-select-variant="a"]');
  assert.equal(
    await reset.textContent(),
    "Edited title survives later rendering.",
  );
  assert.equal(await reset.getAttribute("style"), authoredStyle);

  await reset.click();
  await page.evaluate(() => document.activeElement?.blur());
  await page.keyboard.press("ArrowRight");
  assert.equal(await reset.getAttribute("data-editor-x"), "1");
  await page.click("#editor-undo");
  assert.equal(
    await page.locator(selector).first().getAttribute("data-editor-x"),
    null,
  );
  await page.click("#editor-redo");
  assert.equal(
    await page.locator(selector).first().getAttribute("data-editor-x"),
    "1",
  );
  await closeClean(session);
});

await run("editor parity duplicate delete and resize", async () => {
  const session = await pageFor({ sourceRuntime: true, clearStorage: false });
  const { page } = session;
  await page.click("#mode-toggle");
  const selector = '[data-unit="u-title"] [data-variant="a"] [data-editable]';
  const visible = page.locator(`${selector}:visible`).first();
  const initialCount = await page.locator(selector).count();
  await visible.click();
  await page.keyboard.press("Meta+d");
  assert.equal(await page.locator(selector).count(), initialCount + 1);
  await page.click("#editor-undo");
  assert.equal(await page.locator(selector).count(), initialCount);
  await page.click("#editor-redo");
  assert.equal(await page.locator(selector).count(), initialCount + 1);
  await page.locator(selector).last().click();
  await page.keyboard.press("Delete");
  assert.equal(await page.locator(selector).count(), initialCount);
  await page.click("#editor-undo");
  assert.equal(await page.locator(selector).count(), initialCount + 1);

  const text = page.locator(`${selector}:visible`).last();
  const before = await text.boundingBox();
  const pageScale = await text.evaluate(
    (node) => node.getBoundingClientRect().width / node.offsetWidth,
  );
  await text.click();
  await dragEditorHandle(page, "nw", 12, 8);
  const after = await text.boundingBox();
  assert(after.width < before.width);
  assert(after.x > before.x);
  assert(
    Math.abs(after.x - before.x - 12) < 1,
    "resize must follow the pointer in screen coordinates",
  );
  assert(
    Math.abs(
      Number(await text.getAttribute("data-editor-x")) - 12 / pageScale,
    ) < 0.2,
    "stored x offset uses intrinsic page coordinates",
  );
  assert(
    Math.abs(Number(await text.getAttribute("data-editor-y")) - 8 / pageScale) <
      0.2,
    "stored y offset uses intrinsic page coordinates",
  );
  await page.click("#editor-undo");
  assert.equal(
    await page
      .locator(`${selector}:visible`)
      .last()
      .getAttribute("data-editor-x"),
    null,
  );

  await page.evaluate(() => {
    const fixture = document.createElement("div");
    fixture.id = "editor-svg-fixture";
    fixture.className = "ld-unit";
    fixture.innerHTML =
      '<div class="ld-diagram"><svg width="260" height="90" viewBox="0 0 260 90"><g id="resize-g1" role="button"><rect width="70" height="60" fill="currentColor"/></g><g id="resize-g2" role="button" transform="translate(150 10)"><rect width="70" height="60" fill="currentColor"/></g></svg></div>';
    document.querySelector("main").append(fixture);
    window.LegalDesign.setMode(false);
    window.LegalDesign.setMode(true);
  });
  await page.locator("#resize-g1").click();
  await page.keyboard.down("Shift");
  await page.locator("#resize-g2").click();
  await page.keyboard.up("Shift");
  assert.equal(await page.locator(".ld-selected").count(), 2);
  await dragEditorHandle(page, "se", 40, 20);
  const svgGeometry = await page
    .locator("#editor-svg-fixture g")
    .evaluateAll((nodes) =>
      nodes.map((node) => ({
        x: Number(node.getAttribute("data-editor-x") || 0),
        transform: node.style.transform,
      })),
    );
  assert(svgGeometry.every((item) => item.transform.includes("scale(")));
  assert(svgGeometry[1].x > svgGeometry[0].x);
  await page.click("#editor-undo");
  assert.equal(
    await page.locator("#editor-svg-fixture g[style*='scale']").count(),
    0,
  );
  await page.locator("#resize-g1").click();
  await dragEditorHandle(page, "se", 24, 12);
  const recoveredTransform = await page
    .locator("#resize-g1")
    .evaluate((node) => node.style.transform);
  await page.reload();
  await page.locator("#ld-restore-banner [data-restore]").click();
  assert.equal(
    await page.locator("#resize-g1").evaluate((node) => node.style.transform),
    recoveredTransform,
  );
  await closeClean(session);
});

await run("diagram edits survive client and template exports", async () => {
  const session = await pageFor({ sourceRuntime: true });
  const { page } = session;
  await page.click("#mode-toggle");
  const figure = page.locator('section.ld-unit[data-kind="figure"]').first();
  const nodes = figure.locator(
    '.ld-variant:not([hidden]) .ld-diagram g[role="button"]',
  );
  const initialCount = await nodes.count();
  assert(initialCount >= 2);
  await nodes.first().click();
  await page.keyboard.press("Delete");
  assert.equal(await nodes.count(), initialCount - 1);
  await nodes.first().click();
  await page.keyboard.press("Meta+d");
  assert.equal(await nodes.count(), initialCount);
  await nodes.last().click();
  await page.keyboard.press("ArrowRight");
  assert.equal(await nodes.last().getAttribute("data-editor-x"), "1");

  const exported = await page.evaluate(() => ({
    client: window.LegalDesign.exportHTML(false),
    template: window.LegalDesign.exportTemplate(false),
  }));
  const clientPath = join(EXPORTS_OUT, "diagram-edits-client.html");
  const templatePath = join(EXPORTS_OUT, "diagram-edits-template.html");
  writeFileSync(clientPath, exported.client);
  writeFileSync(templatePath, exported.template);
  await closeClean(session);

  for (const [kind, path] of [
    ["client", clientPath],
    ["template", templatePath],
  ]) {
    const reopened = await pageFor({ url: pathToFileURL(path).href });
    const reopenedNodes = reopened.page.locator(
      'section.ld-unit[data-kind="figure"] .ld-variant:not([hidden]) .ld-diagram g[role="button"]',
    );
    assert.equal(await reopenedNodes.count(), initialCount, kind);
    assert(
      await reopenedNodes.evaluateAll((items) =>
        items.some((item) => item.style.transform.includes("translate")),
      ),
      `${kind}: moved diagram node was not preserved`,
    );
    await closeClean(reopened);
  }
});

await run(
  "edit mode opens and persists purposeful popup through UI",
  async () => {
    const fixture = composedFixture({ approaches: true });
    const session = await pageFor({
      url: pathToFileURL(sourceRuntimeAsset(fixture.html)).href,
    });
    const { page } = session;
    await page.click("#mode-toggle");

    const trigger = page
      .locator(
        '[data-approach="a"] [data-unit="a-flow"] [data-detail="e-ask"]:visible',
      )
      .first();
    const label = trigger
      .locator("[data-diagram-label][data-editable]")
      .first();
    const diagramSentinel = "Edited ask label through UI";
    await label.dblclick();
    const diagramEditor = page.locator("#ld-svg-text-editor");
    assert.equal(await diagramEditor.isVisible(), true);
    assert.equal(await page.locator("#popup-scrim").isHidden(), true);
    await diagramEditor.fill(diagramSentinel);
    await diagramEditor.press("Enter");

    // Click the card's empty surface, outside the selected label's resize handles.
    await trigger
      .locator(":scope > rect")
      .click({ position: { x: 12, y: 12 } });
    await page.click("#editor-popup");
    const popup = page.locator("#e-ask");
    assert.equal(
      await popup.isVisible(),
      true,
      "Edit popup did not open selected shape's purposeful popup",
    );
    const field = popup.locator("[data-evidence-field][data-editable]").first();
    const fieldName = await field.getAttribute("data-evidence-field");
    assert(fieldName);
    const popupSentinel = "Edited popup explanation through UI";
    await field.dblclick();
    assert.equal(await field.getAttribute("contenteditable"), "true");
    await field.fill(popupSentinel);
    await field.press("Tab");
    assert.equal(
      await page.evaluate(
        ({ id, path }) =>
          path
            .split(".")
            .reduce(
              (value, key) => value?.[key],
              window.LegalDesign.state().evidence[id],
            ),
        { id: "e-ask", path: fieldName },
      ),
      popupSentinel,
    );
    await popup.locator(".ld-popup-close,.pop-close").click();
    assert.equal(await page.locator("#popup-scrim").isHidden(), true);

    await trigger.focus();
    await trigger.press("Enter");
    assert.equal(
      await popup.isVisible(),
      true,
      "Edit-mode keyboard activation did not reopen the popup",
    );
    await popup.locator(".ld-popup-close,.pop-close").click();

    const savedPath = await downloadFrom(
      page,
      "#ld-save",
      "edit-popup-ui-saved.html",
    );
    await closeClean(session);

    const reopened = await pageFor({ url: pathToFileURL(savedPath).href });
    assert.equal(
      await reopened.page
        .locator(
          '[data-approach="a"] [data-unit="a-flow"] [data-diagram-label][data-param-path]:visible',
        )
        .evaluateAll(
          (nodes, expected) =>
            nodes.some((node) => node.textContent.includes(expected)),
          diagramSentinel,
        ),
      true,
    );
    const reopenedTrigger = reopened.page
      .locator(
        '[data-approach="a"] [data-unit="a-flow"] [data-detail="e-ask"]:visible',
      )
      .first();
    await reopenedTrigger.locator(":scope > rect").click();
    assert.equal(await reopened.page.locator("#e-ask").isVisible(), true);
    assert.equal(
      await reopened.page
        .locator(`#e-ask [data-evidence-field="${fieldName}"]`)
        .innerText(),
      popupSentinel,
    );
    const reopenedState = await stateFrom(reopened.page);
    assert.equal(reopenedState.evidence["e-ask"].status, "supplied");
    assert.equal(
      reopenedState.evidence["e-ask"].original.availability,
      "linked",
    );
    await reopened.page
      .locator("#e-ask .ld-popup-close,#e-ask .pop-close")
      .click();
    await closeClean(reopened);
  },
);

await run("popup modal traps Tab and Shift+Tab focus", async () => {
  const fixture = composedFixture({ approaches: true });
  const session = await pageFor({ url: pathToFileURL(fixture.html).href });
  const { page } = session;
  const trigger = page
    .locator('[data-approach="a"] [data-detail="e-ask"]:visible')
    .first();
  await trigger.locator(":scope > rect").click();
  const popup = page.locator("#e-ask");
  assert.equal(await popup.isVisible(), true);
  const focusables = popup.locator(
    'a[href],button:not(:disabled),input:not([type="hidden"]):not(:disabled),select:not(:disabled),textarea:not(:disabled),summary,[contenteditable="true"],[tabindex]:not([tabindex="-1"])',
  );
  assert(
    (await focusables.count()) >= 2,
    "focus-trap fixture needs at least two controls",
  );
  const first = focusables.first();
  const last = focusables.last();
  assert.equal(
    await first.evaluate((node) => node === document.activeElement),
    true,
    "popup did not focus its first control on open",
  );

  await first.focus();
  await page.keyboard.press("Shift+Tab");
  assert.equal(
    await last.evaluate((node) => node === document.activeElement),
    true,
    "Shift+Tab escaped before the first popup control",
  );
  await last.focus();
  await page.keyboard.press("Tab");
  assert.equal(
    await first.evaluate((node) => node === document.activeElement),
    true,
    "Tab escaped after the last popup control",
  );

  await page.locator("#theme-toggle").focus();
  await page.keyboard.press("Tab");
  assert.equal(
    await first.evaluate((node) => node === document.activeElement),
    true,
    "Tab did not recover focus programmatically moved behind the modal",
  );

  await popup
    .locator(
      'a[href],button,input,select,textarea,summary,[contenteditable="true"],[tabindex]',
    )
    .evaluateAll((nodes) => {
      nodes.forEach((node) => {
        if ("disabled" in node) node.disabled = true;
        node.removeAttribute("href");
        node.removeAttribute("contenteditable");
        node.setAttribute("tabindex", "-1");
      });
    });
  await page.locator("#theme-toggle").focus();
  await page.keyboard.press("Tab");
  assert.equal(
    await popup.evaluate((node) => node === document.activeElement),
    true,
    "a popup without controls did not retain fallback focus",
  );
  await page.keyboard.press("Escape");
  assert.equal(await page.locator("#popup-scrim").isHidden(), true);
  await assertFocusReturned(page, "e-ask", "modal focus trap after Escape");
  await closeClean(session);
});

await run(
  "interactive SVG preserves accessible detail buttons and keyboard activation",
  async () => {
    const fixture = composedFixture({ approaches: true });
    const session = await pageFor({ url: pathToFileURL(fixture.html).href });
    const { page } = session;
    const diagram = page
      .locator('[data-approach="a"] svg:has([data-detail]):visible')
      .first();
    assert.equal(await diagram.getAttribute("role"), "group");
    assert((await diagram.getAttribute("aria-label"))?.trim());

    const accessibleTree = await diagram.ariaSnapshot();
    assert.match(accessibleTree, /\bgroup\b/i);
    assert.match(
      accessibleTree,
      /\bbutton\b/i,
      "interactive SVG detail nodes were flattened out of the accessibility tree",
    );

    const detail = diagram.getByRole("button").first();
    assert(
      (await detail.count()) > 0,
      "interactive SVG exposes no button role",
    );
    assert.equal(await detail.getAttribute("tabindex"), "0");
    assert.equal(await detail.getAttribute("aria-haspopup"), "dialog");
    const target = await detail.getAttribute("aria-controls");
    assert(target, "interactive SVG detail button has no popup target");
    assert.equal(await detail.getAttribute("data-detail"), target);

    await focusByKeyboard(page, detail, "interactive SVG detail button");
    await detail.press("Enter");
    assert.equal(await page.locator(`#${target}`).isVisible(), true);
    await page.keyboard.press("Escape");
    await assertFocusReturned(
      page,
      target,
      "interactive SVG detail button after Escape",
    );

    const noninteractiveRole = await page.evaluate(() => {
      const host = document.createElement("div");
      host.innerHTML = window.LegalDesign.render(
        "flow",
        {
          stages: [{ title: "First" }, { title: "Second" }],
          edges: ["then"],
        },
        { ariaLabel: "A noninteractive flow diagram." },
      );
      return host.querySelector("svg")?.getAttribute("role");
    });
    assert.equal(noninteractiveRole, "img");
    await closeClean(session);
  },
);

await run(
  "diagram labels and purposeful popup copy persist through every working surface",
  async () => {
    const fixture = composedFixture({ approaches: true });
    const session = await pageFor({ url: pathToFileURL(fixture.html).href });
    const { page } = session;
    await assertPageApproachContract(page, "editable composed artifact");
    await page.click("#mode-toggle");

    const diagramSentinel = "Edited escalation threshold label";
    const label = page
      .locator(
        '[data-approach="a"] [data-diagram-label][data-editable][data-param-path]:not(.edge):visible',
      )
      .first();
    assert.equal(
      await label.count(),
      1,
      "composed figure has no editable label",
    );
    const labelBinding = {
      unitId: await label
        .locator("xpath=ancestor::section[@data-unit]")
        .getAttribute("data-unit"),
      paramPath: await label.getAttribute("data-param-path"),
    };
    assert(
      labelBinding.unitId,
      "diagram label is not owned by a portable unit",
    );
    assert.match(
      labelBinding.paramPath || "",
      /^\/(?:[^/]|~[01])+/,
      "diagram label lacks an RFC 6901 parameter path",
    );
    const originalLabel = (await label.textContent()).trim();
    await label.dblclick();
    const svgEditor = page.locator("#ld-svg-text-editor");
    await svgEditor.fill(diagramSentinel);
    await svgEditor.press("Enter");
    const boundDiagramValue = await page.evaluate(({ unitId, paramPath }) => {
      let value = window.LegalDesign.state().units[unitId].variants.a.params;
      for (const part of paramPath
        .slice(1)
        .split("/")
        .map((item) => item.replaceAll("~1", "/").replaceAll("~0", "~")))
        value = value[part];
      return value;
    }, labelBinding);
    assert.equal(boundDiagramValue, diagramSentinel);
    await page.click("#editor-undo");
    assert.equal((await label.textContent()).trim(), originalLabel);
    await page.click("#editor-redo");
    assert.equal((await label.textContent()).trim(), diagramSentinel);

    const detailId = await page
      .locator('[data-approach="a"] [data-detail]:visible')
      .first()
      .getAttribute("data-detail");
    assert(detailId, "composed artifact has no purposeful popup target");
    await page.evaluate((id) => window.LegalDesign.openPopup(id), detailId);
    const popup = page.locator(`#${detailId}`);
    const popupField = popup
      .locator("[data-evidence-field][data-editable]:visible")
      .first();
    assert.equal(
      await popupField.count(),
      1,
      "purpose-specific popup has no editable field",
    );
    const fieldName = await popupField.getAttribute("data-evidence-field");
    assert(fieldName, "popup field is not mapped to portable state");
    const originalPopupCopy = (await popupField.textContent()).trim();
    const popupSentinel = "Edited source explanation for the decision";
    await popupField.dblclick();
    await popupField.fill(popupSentinel);
    await popupField.blur();
    assert.equal(
      await page.evaluate(
        ({ id, path }) =>
          path
            .split(".")
            .reduce(
              (value, key) => value?.[key],
              window.LegalDesign.state().evidence[id],
            ),
        { id: detailId, path: fieldName },
      ),
      popupSentinel,
    );
    await page.evaluate(() => window.LegalDesign.closePopup());
    await page.click("#editor-undo");
    await page.evaluate((id) => window.LegalDesign.openPopup(id), detailId);
    assert.equal((await popupField.textContent()).trim(), originalPopupCopy);
    await page.evaluate(() => window.LegalDesign.closePopup());
    await page.click("#editor-redo");
    await page.evaluate((id) => window.LegalDesign.openPopup(id), detailId);
    assert.equal((await popupField.textContent()).trim(), popupSentinel);
    await page.evaluate(() => window.LegalDesign.closePopup());

    const savedPath = join(EXPORTS_OUT, "approach-edits-saved.html");
    writeFileSync(
      savedPath,
      await page.evaluate(() => window.LegalDesign.save()),
    );
    await closeClean(session);

    const reopened = await pageFor({ url: pathToFileURL(savedPath).href });
    assert.equal((await stateFrom(reopened.page)).review.approach, "a");
    assert.equal(
      (
        await reopened.page
          .locator(
            '[data-approach="a"] [data-diagram-label][data-param-path]:not(.edge):visible',
          )
          .first()
          .textContent()
      ).trim(),
      diagramSentinel,
    );
    await reopened.page.evaluate(
      (id) => window.LegalDesign.openPopup(id),
      detailId,
    );
    assert.equal(
      (
        await reopened.page
          .locator(`#${detailId} [data-evidence-field="${fieldName}"]`)
          .textContent()
      ).trim(),
      popupSentinel,
    );
    await reopened.page.evaluate(() => window.LegalDesign.closePopup());
    const exported = await reopened.page.evaluate(() => ({
      client: window.LegalDesign.exportHTML(false),
      template: window.LegalDesign.exportTemplate(false),
    }));
    const clientPath = join(EXPORTS_OUT, "approach-edits-client.html");
    const templatePath = join(EXPORTS_OUT, "approach-edits-template.html");
    writeFileSync(clientPath, exported.client);
    writeFileSync(templatePath, exported.template);
    await closeClean(reopened);

    const client = await pageFor({ url: pathToFileURL(clientPath).href });
    assert.deepEqual(
      await client.page
        .locator("[data-approach]")
        .evaluateAll((roots) =>
          roots.map((root) => root.getAttribute("data-approach")),
        ),
      ["a"],
      "client export retained the inactive page approach",
    );
    assert.match(
      await client.page.locator("body").innerText(),
      new RegExp(diagramSentinel, "i"),
    );
    await client.page.evaluate(
      (id) => window.LegalDesign.openPopup(id),
      detailId,
    );
    assert.match(
      await client.page.locator(`#${detailId}`).innerText(),
      new RegExp(popupSentinel),
    );
    await closeClean(client);

    const templateSource = withoutRuntime(readFileSync(templatePath, "utf8"));
    assert.doesNotMatch(templateSource, new RegExp(diagramSentinel, "i"));
    assert.doesNotMatch(templateSource, new RegExp(popupSentinel));
    assert.equal(
      templateSource.includes(`aria-controls="${detailId}"`),
      false,
      "template leaked an original evidence ID through aria-controls",
    );
    const template = await pageFor({ url: pathToFileURL(templatePath).href });
    await assertPageApproachContract(template.page, "template export");
    const templateLayout = await template.page
      .locator('[data-approach="a"] section.ld-unit')
      .evaluateAll((units) =>
        units.map((unit) => ({
          column: unit.style.getPropertyValue("--ld-column").trim(),
          span: unit.style.getPropertyValue("--ld-span").trim(),
          row: unit.style.getPropertyValue("--ld-row").trim(),
        })),
      );
    assert(
      templateLayout.every(
        (unit) =>
          unit.column === "1" &&
          unit.span === "12" &&
          /^[1-9]\d*$/.test(unit.row),
      ),
      "template must preserve the composed full-width grid placements",
    );
    assert.equal(
      await template.page
        .locator('[data-approach="a"] [data-role="title"]')
        .count(),
      1,
      "template preserves semantic title styling",
    );
    assert(
      await template.page
        .locator("[data-detail][aria-controls]")
        .evaluateAll((nodes) =>
          nodes.every((node) =>
            node
              .getAttribute("aria-controls")
              .split(/\s+/)
              .filter(Boolean)
              .every((id) => document.getElementById(id)),
          ),
        ),
      "template contains a broken popup aria-controls reference",
    );
    assert.equal(
      (await template.page
        .locator("[data-diagram-label][data-editable]")
        .count()) > 0,
      true,
      "template lost editable diagram labels",
    );
    assert.equal(
      (await template.page
        .locator("[data-evidence-field][data-editable]")
        .count()) > 0,
      true,
      "template lost editable popup fields",
    );
    assert(
      await template.page
        .locator(
          "[data-diagram-label][data-editable],[data-evidence-field][data-editable]",
        )
        .evaluateAll((nodes) =>
          nodes.every(
            (node) =>
              node.textContent.trim().length > 0 &&
              (node.getAttribute("data-placeholder") || "").trim().length > 0,
          ),
        ),
      "template edit targets need descriptive placeholder content",
    );

    await template.page.click("#mode-toggle");
    const safeDiagramText = "[Reusable threshold label.]";
    const templateLabel = template.page
      .locator(
        '[data-approach="a"] [data-diagram-label][data-editable][data-param-path]:not(.edge):visible',
      )
      .first();
    assert.match(await templateLabel.getAttribute("data-param-path"), /^\//);
    await templateLabel.dblclick();
    await template.page.locator("#ld-svg-text-editor").fill(safeDiagramText);
    await template.page.locator("#ld-svg-text-editor").press("Enter");
    const templateDetailId = await template.page
      .locator('[data-approach="a"] [data-detail]:visible')
      .first()
      .getAttribute("data-detail");
    assert(templateDetailId);
    await template.page.evaluate(
      (id) => window.LegalDesign.openPopup(id),
      templateDetailId,
    );
    const safePopupText = "[Reusable source explanation.]";
    const templateField = template.page
      .locator(`#${templateDetailId} [data-evidence-field][data-editable]`)
      .first();
    const templateFieldName = await templateField.getAttribute(
      "data-evidence-field",
    );
    assert(templateFieldName);
    await templateField.dblclick();
    await templateField.fill(safePopupText);
    await templateField.blur();
    await template.page.evaluate(() => window.LegalDesign.closePopup());
    const reusedPath = join(EXPORTS_OUT, "approach-template-edits-saved.html");
    writeFileSync(
      reusedPath,
      await template.page.evaluate(() => window.LegalDesign.save()),
    );
    await closeClean(template);

    const reused = await pageFor({ url: pathToFileURL(reusedPath).href });
    assert.equal(
      (
        await reused.page
          .locator(
            '[data-approach="a"] [data-diagram-label][data-param-path]:not(.edge):visible',
          )
          .first()
          .evaluate((node) => {
            const rows = [...node.querySelectorAll("tspan")]
              .map((row) => row.textContent.trim())
              .filter(Boolean);
            return rows.length ? rows.join(" ") : node.textContent.trim();
          })
      ).trim(),
      safeDiagramText,
    );
    await reused.page.evaluate(
      (id) => window.LegalDesign.openPopup(id),
      templateDetailId,
    );
    assert.equal(
      (
        await reused.page
          .locator(
            `#${templateDetailId} [data-evidence-field="${templateFieldName}"]`,
          )
          .textContent()
      ).trim(),
      safePopupText,
    );
    await closeClean(reused);
  },
);

await run("v2 per-unit A/B state and edit retention", async () => {
  for (const asset of ["stacked", "walkthrough", "report", "method"]) {
    const session = await pageFor({ asset, sourceRuntime: true });
    const { page } = session;
    await page.click("#mode-toggle");
    const units = await page
      .locator(
        "section.ld-unit:not([data-single]):has([data-select-variant='b'])",
      )
      .evaluateAll((nodes) => nodes.map((node) => node.dataset.unit));
    assert(units.length > 0, `${asset}: no switchable units`);
    for (const id of units) {
      await showUnit(page, id);
      const section = page.locator(`[data-unit="${id}"]`);
      await revealUnitTools(page, section);
      await section.locator('[data-select-variant="b"]').click();
      assert.equal(
        await section
          .locator(".ld-variant:not([hidden])")
          .getAttribute("data-variant"),
        "b",
        `${asset}:${id} pointer DOM`,
      );
      assert.equal((await stateFrom(page)).units[id].selected, "b");
      await section.locator(".ld-ab").focus();
      await page.keyboard.press("ArrowLeft");
      assert.equal((await stateFrom(page)).units[id].selected, "a");
      await section.locator(".ld-ab").focus();
      await page.keyboard.press("ArrowRight");
      assert.equal(
        (await stateFrom(page)).units[id].selected,
        "b",
        `${asset}:${id} keyboard right`,
      );
      await section.locator(".ld-ab").focus();
      await page.keyboard.press("ArrowLeft");
    }
    const editableUnit = await page
      .locator(
        "section.ld-unit:not([data-single]):has([data-select-variant='b']):has([data-variant='a'] [data-editable])",
      )
      .first()
      .getAttribute("data-unit");
    assert(editableUnit, `${asset}: no editable switchable unit`);
    await showUnit(page, editableUnit);
    const editable = page
      .locator(
        `[data-unit="${editableUnit}"] [data-variant="a"] [data-editable]`,
      )
      .first();
    const edited = `Edited ${asset} A survives a treatment switch.`;
    await editable.dblclick();
    assert.equal(await page.locator('[contenteditable="true"]').count(), 1);
    await editable.fill(edited);
    await editable.blur();
    await revealUnitTools(page, page.locator(`[data-unit="${editableUnit}"]`));
    await page
      .locator(`[data-unit="${editableUnit}"] [data-select-variant="b"]`)
      .click();
    await page
      .locator(`[data-unit="${editableUnit}"] [data-select-variant="a"]`)
      .click();
    assert.equal(await editable.textContent(), edited);
    assert.match(
      (await stateFrom(page)).units[editableUnit].edits.a,
      new RegExp(`Edited ${asset}`),
    );
    await closeClean(session);
  }
});

await run("save and reopen portable interaction state", async () => {
  const session = await pageFor({ sourceRuntime: true });
  const { page } = session;
  await page.click("#mode-toggle");
  const answer = page.locator(
    '[data-unit="u-answer"] [data-variant="a"] [data-editable]',
  );
  await answer.dblclick();
  await answer.fill("Portable edited answer.");
  await answer.blur();
  await page.evaluate(() => {
    const section = document.createElement("section");
    section.className = "ld-unit";
    section.dataset.unit = "u-save-decision";
    section.dataset.kind = "decision";
    section.innerHTML =
      '<div class="ld-variant" data-variant="a"><div class="ld-decision"><button type="button" value="approve" data-decision-option>Approve</button><button type="button" value="revise" data-decision-option>Revise</button></div></div>';
    document.querySelector("main > .sb-slide:not([hidden])").append(section);
    const next = window.LegalDesign.state();
    next.units["u-save-decision"] = {
      kind: "decision",
      selected: "a",
      variants: { a: { html: "Choose.", axis: "single", why: "" } },
      edits: { a: null },
      placeholder: "[Choose one option.]",
    };
    next.review.reactions = { "u-card-cover": ["👍"] };
    next.review.comments = [
      {
        id: "legacy-comment",
        unit: "u-card-cover",
        kind: "unit",
        text: "Preserve, but do not render.",
      },
    ];
    window.LegalDesign.setState(next);
    window.LegalDesign.bindDecisions();
  });
  await page.click('[data-unit="u-save-decision"] [value="approve"]');
  for (const id of ["u-title", "u-figure"]) {
    const unit = page.locator(`[data-unit="${id}"]`);
    await revealUnitTools(page, unit);
    await unit.locator('[data-select-variant="b"]').click();
  }
  await page.click("#theme-toggle");
  const savedPath = await downloadFrom(page, "#ld-save", "saved-reopen.html");
  const savedState = await stateFrom(page);
  const savedMarkup = readFileSync(savedPath, "utf8");
  assert.doesNotMatch(savedMarkup, /<html[^>]+data-mode="edit"/);
  assert.doesNotMatch(savedMarkup, /\scontenteditable="true"/);
  assert.doesNotMatch(savedMarkup, /id="ld-editor-layer"/);
  assert.doesNotMatch(savedMarkup, /class="[^"]*ld-selected/);
  assert.match(savedMarkup, /id="mode-toggle"[^>]*>Edit<\/button>/);
  await closeClean(session);
  const reopened = await pageFor({
    clearStorage: false,
    url: pathToFileURL(savedPath).href,
  });
  assert.deepEqual(await stateFrom(reopened.page), savedState);
  assert.equal(
    await reopened.page.locator("html").getAttribute("data-mode"),
    null,
  );
  assert.equal(
    await reopened.page.locator('[contenteditable="true"]').count(),
    0,
  );
  assert.equal(await reopened.page.locator("#ld-editor-layer").count(), 0);
  assert.equal(
    await reopened.page.locator("#mode-toggle").textContent(),
    "Edit",
  );
  assert.deepEqual((await stateFrom(reopened.page)).review.reactions, {
    "u-card-cover": ["👍"],
  });
  assert.equal(
    await reopened.page
      .locator(
        ".ld-review,.ld-reaction,.ld-comment,.ld-sheet-open,.ld-bottom-save,.ld-phone-sheet,.ld-selection-popover",
      )
      .count(),
    0,
  );
  await closeClean(reopened);
});

await run("client and template exports reopen", async () => {
  const clientSession = await pageFor();
  const { page } = clientSession;
  await page.evaluate(() => {
    const section = document.createElement("section");
    section.className = "ld-unit";
    section.dataset.unit = "u-browser-decision";
    section.dataset.kind = "decision";
    section.innerHTML =
      '<div class="ld-variant" data-variant="a"><div class="ld-decision"><button type="button" value="one" data-decision-option>One</button><button type="button" value="two" data-decision-option>Two</button></div></div>';
    document.querySelector("main > .sb-slide:not([hidden])").append(section);
    const next = window.LegalDesign.state();
    next.units["u-browser-decision"] = {
      kind: "decision",
      selected: "a",
      variants: { a: { html: "Choose one.", axis: "single", why: "" } },
      edits: { a: null },
      placeholder: "[Choose one option.]",
    };
    window.LegalDesign.setState(next);
    window.LegalDesign.bindDecisions();
  });
  await page.click('[data-decision-option][value="one"]');
  const clientCopySentinel = "Client copy edit survives export.";
  await page.click("#mode-toggle");
  const editedCopy = page.locator("[data-editable]:visible").first();
  const editedUnitId = await editedCopy
    .locator("xpath=ancestor::section[@data-unit][1]")
    .getAttribute("data-unit");
  await editedCopy.dblclick();
  await editedCopy.fill(clientCopySentinel);
  await editedCopy.press("Tab");
  const figureNode = page
    .locator("section[data-kind='figure'] .ld-diagram svg [role='button']")
    .first();
  await figureNode.click();
  await dragEditorHandle(page, "se", 24, 12);
  const clientFigureTransform = await figureNode.evaluate(
    (node) => node.style.transform,
  );
  assert.match(clientFigureTransform, /scale\(/);
  await page.click("#mode-toggle");
  const clientPath = await downloadFrom(
    page,
    "#export-html",
    "client-export.html",
  );
  await closeClean(clientSession);
  const client = await pageFor({ url: pathToFileURL(clientPath).href });
  assert.equal(
    await client.page.locator("html").getAttribute("data-exported"),
    "client",
  );
  assert.equal(await client.page.locator("[data-editor-only]").count(), 0);
  assert.equal(await client.page.locator(".ld-ab,.ld-why").count(), 0);
  assert.equal(
    await client.page.locator("#export-html,#export-template").count(),
    0,
  );
  const variantCounts = await client.page
    .locator("section.ld-unit:has(.ld-variant)")
    .evaluateAll((nodes) =>
      nodes.map((node) => node.querySelectorAll(".ld-variant").length),
    );
  assert(variantCounts.every((count) => count === 1));
  assert.doesNotMatch(
    await client.page.locator("body").innerText(),
    /\[[^\]]+\]/,
  );
  assert.match(
    await client.page.locator("body").innerText(),
    /Client copy edit/,
  );
  const clientPortableState = await stateFrom(client.page);
  assertValidState(clientPortableState, "authored client export state");
  assert.match(
    clientPortableState.units[editedUnitId].edits[
      clientPortableState.units[editedUnitId].selected
    ],
    /Client copy edit survives export/,
  );
  assert.equal(
    await client.page
      .locator("section[data-kind='figure'] .ld-diagram svg [role='button']")
      .first()
      .evaluate((node) => node.style.transform),
    clientFigureTransform,
  );
  await client.page.click('[data-decision-option][value="two"]');
  assert.equal(
    (await stateFrom(client.page)).review.decisions["u-browser-decision"],
    "two",
  );
  await closeClean(client);

  const templateSession = await pageFor();
  let sourceState = await stateFrom(templateSession.page);
  const confidentialSentinel = "ZZ-CONFIDENTIAL-FIGURE-SENTINEL-7391";
  const confidentialUnitSentinel = "u-zz-confidential-client-unit-7391";
  const confidentialAriaSentinel = "ZZ-CONFIDENTIAL-ARIA-SENTINEL-7391";
  const confidentialNumberSentinel = 73917.31;
  const confidentialNumberMaxSentinel = 73917.39;
  const confidentialBracketedSentinel =
    "[The ZZ-CONFIDENTIAL-MATTER-7391 agreement]";
  await templateSession.page.evaluate(
    ({
      ariaSentinel,
      bracketedSentinel,
      numberMaxSentinel,
      numberSentinel,
      sentinel,
      unitSentinel,
    }) => {
      const next = window.LegalDesign.state();
      const entry = Object.entries(next.units).find(
        ([, unit]) => unit.kind === "figure",
      );
      if (!entry) throw new Error("fixture has no figure unit");
      const [id, unit] = entry;
      const variant = unit.variants[unit.selected];
      variant.component = "rungBars";
      variant.params = {
        items: [
          { label: sentinel, value: numberSentinel },
          {
            label: "ZZ-CONFIDENTIAL-NUMERIC-SECOND-7391",
            value: numberMaxSentinel,
          },
        ],
        unit: "confidential units",
        yAxisTitle: "confidential values",
        sourceNote: "confidential numeric source",
      };
      const section = document.querySelector(`[data-unit="${id}"]`);
      section.dataset.unit = unitSentinel;
      const host = section.querySelector(
        `[data-variant="${unit.selected}"] .ld-diagram`,
      );
      host.id = `diagram-${unitSentinel}-${unit.selected}`;
      next.units[unitSentinel] = unit;
      delete next.units[id];
      const copyEntry = Object.entries(next.units).find(
        ([, candidate]) => candidate.kind !== "figure",
      );
      if (!copyEntry) throw new Error("fixture has no copy unit");
      copyEntry[1].placeholder = bracketedSentinel;
      const copyPlaceholder = document.querySelector(
        `[data-unit="${copyEntry[0]}"] [data-placeholder]`,
      );
      if (copyPlaceholder) {
        copyPlaceholder.dataset.placeholder = bracketedSentinel;
        copyPlaceholder.textContent = bracketedSentinel;
      }
      window.LegalDesign.setState(next);
      host.insertAdjacentText("beforeend", sentinel);
      document
        .querySelector(".ld-foot")
        .setAttribute("aria-label", `Edit ${ariaSentinel}`);
    },
    {
      ariaSentinel: confidentialAriaSentinel,
      bracketedSentinel: confidentialBracketedSentinel,
      numberMaxSentinel: confidentialNumberMaxSentinel,
      numberSentinel: confidentialNumberSentinel,
      sentinel: confidentialSentinel,
      unitSentinel: confidentialUnitSentinel,
    },
  );
  sourceState = await stateFrom(templateSession.page);
  const templatePath = await downloadFrom(
    templateSession.page,
    "#export-template",
    "template-export.html",
  );
  await closeClean(templateSession);
  const template = await pageFor({ url: pathToFileURL(templatePath).href });
  assert.equal(
    await template.page.locator("html").getAttribute("data-exported"),
    "template",
  );
  const exportedTemplateState = await stateFrom(template.page);
  const sourceUnits = Object.values(sourceState.units);
  const exportedUnitIds = Object.keys(exportedTemplateState.units);
  assert.equal(exportedUnitIds.length, sourceUnits.length);
  for (const [index, unit] of sourceUnits.entries()) {
    const id = exportedUnitIds[index];
    const expected = unit.variants.b ? 2 : 1;
    assert.equal(
      await template.page.locator(`[data-unit="${id}"] .ld-variant`).count(),
      expected,
    );
    if (unit.variants.b) {
      assert.equal(
        await template.page
          .locator(`[data-unit="${id}"] .ld-why`)
          .textContent(),
        "[Why this treatment fits the reader and purpose.]",
      );
    }
  }
  const templateHTML = await template.page.content();
  const templateScan = withoutRuntime(readFileSync(templatePath, "utf8"));
  assert.doesNotMatch(templateScan, /\[data-unit=(?:"|')?u-/);
  assert.doesNotMatch(templateScan, /id=(?:"|')diagram-u-/);
  assert.doesNotMatch(templateScan, /data-zone-doc=/);
  const firstCardId = await template.page
    .locator("section.ld-unit.ld-card")
    .first()
    .getAttribute("data-unit");
  await showUnit(template.page, firstCardId);
  const cardBoxes = await template.page
    .locator("section.ld-unit.ld-card")
    .evaluateAll((cards) =>
      cards.map((card) => {
        const rect = card.getBoundingClientRect();
        return {
          x: rect.x,
          y: rect.y,
          right: rect.right,
          bottom: rect.bottom,
          width: rect.width,
          height: rect.height,
        };
      }),
    );
  assert(cardBoxes.every((box) => box.width > 0 && box.height > 0));
  for (let i = 0; i < cardBoxes.length; i++) {
    for (let j = i + 1; j < cardBoxes.length; j++) {
      const a = cardBoxes[i],
        b = cardBoxes[j];
      assert(
        a.right <= b.x + 1 ||
          b.right <= a.x + 1 ||
          a.bottom <= b.y + 1 ||
          b.bottom <= a.y + 1,
        `template cards ${i} and ${j} overlap after their identifiers are scrubbed`,
      );
    }
  }
  assert.doesNotMatch(templateScan, new RegExp(confidentialSentinel));
  assert.doesNotMatch(templateScan, new RegExp(confidentialUnitSentinel));
  assert.doesNotMatch(templateScan, new RegExp(confidentialAriaSentinel));
  assert(!templateScan.includes(String(confidentialNumberSentinel)));
  assert(!templateScan.includes(String(confidentialNumberMaxSentinel)));
  assert.doesNotMatch(templateScan, /ZZ-CONFIDENTIAL-MATTER-7391/);
  for (const ban of TEMPLATE_BANS)
    assert(
      !templateScan.toLowerCase().includes(ban.toLowerCase()),
      `stacked: template contains ${ban}`,
    );
  assert.match(templateHTML, /\[The claim|\[The answer|\[Figure labels/);
  assert.doesNotMatch(templateHTML, /data:image\/(?:png|jpeg|webp);base64/i);
  assert.doesNotMatch(
    templateHTML,
    /\{\{text_|\[Editable content\]|Visualization template/,
  );
  for (const term of TERMS["stacked-explainer.html"])
    assert(!templateHTML.toLowerCase().includes(term.toLowerCase()), term);
  await template.page.click("#mode-toggle");
  const switchableUnit = template.page
    .locator("section.ld-unit:has([data-select-variant='b'])")
    .first();
  const switchableId = await switchableUnit.getAttribute("data-unit");
  assert(switchableId);
  await showUnit(template.page, switchableId);
  await revealUnitTools(template.page, switchableUnit);
  await switchableUnit.locator('[data-select-variant="b"]').click();
  assert.equal(
    (await stateFrom(template.page)).units[switchableId].selected,
    "b",
  );
  await closeClean(template);
});

await run(
  "malformed figure refuses delivery but working Save preserves recovery",
  async () => {
    const session = await pageFor({ sourceRuntime: true });
    const invalid = await session.page.evaluate(() => {
      const next = window.LegalDesign.state();
      const id = Object.keys(next.units).find(
        (key) => next.units[key].kind === "figure",
      );
      const unit = next.units[id];
      unit.variants[unit.selected] = {
        component: "flow",
        axis: "form",
        why: "Imported malformed data",
        params: { "PRIVATE-UNKNOWN-KEY": "Keep this recovery data" },
      };
      let renderError;
      try {
        window.LegalDesign.setState(next);
      } catch (error) {
        renderError = error.message;
      }
      const errors = ["exportHTML", "exportTemplate"].map((method) => {
        try {
          window.LegalDesign[method](false);
          return null;
        } catch (error) {
          return error.message;
        }
      });
      return { id, renderError, errors };
    });
    assert.match(invalid.renderError, /unknown field/);
    assert(
      invalid.errors.every((error) => /unknown field/.test(error)),
      "Malformed diagrams must not become client or template deliverables",
    );
    const markup = await session.page.evaluate(() => window.LegalDesign.save());
    const recoveryState = JSON.parse(
      markup.match(
        /<script id="legaldesign-state" type="application\/json">(.*?)<\/script>/s,
      )[1],
    );
    const recoveredUnit = recoveryState.units[invalid.id];
    assert.equal(
      recoveredUnit.variants[recoveredUnit.selected].params[
        "PRIVATE-UNKNOWN-KEY"
      ],
      "Keep this recovery data",
    );
    assert.match(markup, /<svg/);
    await closeClean(session);
  },
);

await run("export privacy and collision regressions", async () => {
  const sourceRuntime = sourceRuntimeAsset(ASSETS.stacked);
  const privacyFixture = join(SOURCE_RUNTIME_OUT, "template-privacy.html");
  writeFileSync(
    privacyFixture,
    readFileSync(sourceRuntime, "utf8").replace(
      '<script id="ld-runtime">',
      '<style id="ld-template-collision-fixture">[data-unit="foo"]{--collision-a:1}[data-unit="unit-1"]{--collision-b:1}.ZZ-CLASS-SECRET-7391{letter-spacing:0}</style>\n<script id="ld-runtime">',
    ),
  );
  const session = await pageFor({ url: pathToFileURL(privacyFixture).href });
  const exported = await session.page.evaluate(() => {
    const next = window.LegalDesign.state();
    delete next.sourceSchemaVersion;
    delete next.composition;
    delete next.claims;
    next.brief.message = "ZZ-HIDDEN-BRIEF-7391";
    next.brief.run = { note: "ZZ-HIDDEN-RUN-7391" };
    const sourceEntries = Object.entries(next.units).slice(0, 4);
    const ids = ["foo", "unit-1", "constructor", "__proto__"];
    const units = Object.create(null);
    const sections = Array.from(
      document.querySelectorAll("section.ld-unit[data-unit]"),
    ).slice(0, 4);
    sourceEntries.forEach(([, unit], index) => {
      units[ids[index]] = unit;
      unit.evidence = [];
      sections[index].dataset.unit = ids[index];
    });
    units.foo.variants[units.foo.selected].html = "ZZ-OLD-VARIANT-7391";
    units.foo.variants[units.foo.selected].component =
      "ZZ-COMPONENT-SECRET-7391";
    units.foo.variants[units.foo.selected]["ZZ-VARIANT-KEY-SECRET-7391"] = "x";
    const figureIndex = sourceEntries.findIndex(
      ([, unit]) => unit.kind === "figure",
    );
    const figureUnit = units[ids[figureIndex]];
    figureUnit.relationship = "ZZ-RELATIONSHIP-SECRET-7391";
    figureUnit.variants[figureUnit.selected].layout = "ZZ-LAYOUT-SECRET-7391";
    figureUnit.variants[figureUnit.selected].component = "flow";
    figureUnit.variants[figureUnit.selected].params = {
      stages: [
        { title: "ZZ-PARAM-KEY-SECRET-7391" },
        { title: "Second stage" },
      ],
      edges: ["Next"],
    };
    units.foo.edits[units.foo.selected] =
      '<p data-editable="">Safe replacement.</p>';
    next.units = units;
    next.evidence = Object.create(null);
    next.evidence.foo = {
      cite: "First source",
      locator: "One",
      excerpt: "First excerpt",
      link: null,
      status: "supplied-unverified",
    };
    next.evidence["evidence-1"] = {
      cite: "Second source",
      locator: "Two",
      excerpt: "Second excerpt",
      link: null,
      status: "supplied-unverified",
    };
    try {
      window.LegalDesign.setState(next);
    } catch {
      // Rendering rejects an unregistered component. Export must still fail
      // closed if a legacy or hand-authored state contains one.
    }
    document
      .querySelectorAll("[data-evidence],[data-detail]")
      .forEach((node) => {
        node.removeAttribute("data-evidence");
        node.removeAttribute("data-detail");
      });
    const scrim = document.querySelector("#popup-scrim");
    scrim.replaceChildren();
    for (const id of ["foo", "evidence-1"]) {
      const trigger = document.createElement("button");
      trigger.dataset.evidence = id;
      trigger.textContent = `Open ${id}`;
      sections[0].append(trigger);
      const pop = document.createElement("section");
      pop.className = "pop";
      pop.id = id;
      pop.innerHTML =
        '<span class="tag">Source</span><h2>Heading</h2><p class="desc">Description</p><blockquote>Excerpt</blockquote>';
      scrim.append(pop);
    }
    const body = sections[0].querySelector("[data-variant-body]");
    body.id = "ZZ-BODY-ID-SECRET-7391";
    body.dataset.client = "ZZ-BODY-DATA-SECRET-7391";
    sections[0].id = "ZZ-SECTION-ID-SECRET-7391";
    sections[0].dataset.client = "ZZ-SECTION-DATA-SECRET-7391";
    sections[0].dataset.role = "ZZ-ROLE-SECRET-7391";
    sections[0].style.setProperty("--ld-row", "ZZ-GRID-SECRET-7391");
    sections[0].querySelector(".ld-variant").dataset.client =
      "ZZ-VARIANT-DATA-SECRET-7391";
    body.insertAdjacentHTML(
      "beforeend",
      '<span id="ZZ-ID-SECRET-7391" class="ZZ-CLASS-SECRET-7391" title="ZZ-TITLE-SECRET-7391" aria-description="ZZ-ARIA-SECRET-7391" data-client="ZZ-DATA-SECRET-7391">ZZ-UNMARKED-SECRET-7391</span><img src="data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22%3E%3Ctext%3EZZ-PATH-SECRET-7391%3C/text%3E%3C/svg%3E" alt="ZZ-ALT-SECRET-7391">',
    );
    const leakyAttributeNode = body.querySelector("#ZZ-ID-SECRET-7391");
    leakyAttributeNode.setAttribute(
      "style",
      '--matter-note:"ZZ-INLINE-STYLE-SECRET-7391";content:"ZZ-INLINE-CONTENT-SECRET-7391"',
    );
    leakyAttributeNode.setAttribute("value", "ZZ-VALUE-SECRET-7391");
    leakyAttributeNode.setAttribute(
      "placeholder",
      "ZZ-PLACEHOLDER-SECRET-7391",
    );
    leakyAttributeNode.setAttribute(
      "aria-valuetext",
      "ZZ-ARIA-VALUE-SECRET-7391",
    );
    leakyAttributeNode.setAttribute("aria-label", "ZZ-ARIA-LABEL-SECRET-7391");
    const figureHost = sections[figureIndex].querySelector(".ld-diagram");
    figureHost.innerHTML =
      '<svg viewBox="0 0 100 100"><text x="10" y="50">ZZ-FIGURE-DOM-SECRET-7391</text></svg>';
    const orphan = document.createElement("section");
    orphan.className = "ld-unit";
    orphan.dataset.unit = "orphan";
    orphan.textContent = "ZZ-ORPHAN-SECRET-7391";
    document.querySelector("main").append(orphan);
    const loose = document.createElement("p");
    loose.textContent = "ZZ-STATIC-SECRET-7391";
    document.querySelector("main").append(loose);
    document.querySelector("#ld-template-collision-fixture").textContent +=
      "/* ZZ-CSS-BASELINE-MUTATION-7391 */";
    const style = document.createElement("style");
    style.textContent =
      '/* ZZ-CSS-COMMENT-SECRET-7391 */.leak::before{content:"ZZ-CSS-CONTENT-SECRET-7391";background-image:url("data:image/svg+xml,ZZ-CSS-URL-SECRET-7391");--matter:"ZZ-CSS-CUSTOM-SECRET-7391"}';
    document.head.append(style);
    const nonHeadStyle = document.createElement("style");
    nonHeadStyle.textContent = '.leak{content:"ZZ-CSS-NONHEAD-SECRET-7391"}';
    document.body.append(nonHeadStyle);
    return {
      client: window.LegalDesign.exportHTML(false),
      template: window.LegalDesign.exportTemplate(false),
    };
  });
  await closeClean(session);

  for (const sentinel of [
    "ZZ-HIDDEN-BRIEF-7391",
    "ZZ-HIDDEN-RUN-7391",
    "ZZ-ORPHAN-SECRET-7391",
    "ZZ-OLD-VARIANT-7391",
  ])
    assert.doesNotMatch(exported.client, new RegExp(sentinel));
  for (const sentinel of [
    "ZZ-HIDDEN-BRIEF-7391",
    "ZZ-HIDDEN-RUN-7391",
    "ZZ-ORPHAN-SECRET-7391",
    "ZZ-STATIC-SECRET-7391",
    "ZZ-UNMARKED-SECRET-7391",
    "ZZ-TITLE-SECRET-7391",
    "ZZ-CLASS-SECRET-7391",
    "ZZ-ID-SECRET-7391",
    "ZZ-ARIA-SECRET-7391",
    "ZZ-DATA-SECRET-7391",
    "ZZ-PATH-SECRET-7391",
    "ZZ-ALT-SECRET-7391",
    "ZZ-BODY-ID-SECRET-7391",
    "ZZ-BODY-DATA-SECRET-7391",
    "ZZ-SECTION-ID-SECRET-7391",
    "ZZ-SECTION-DATA-SECRET-7391",
    "ZZ-ROLE-SECRET-7391",
    "ZZ-GRID-SECRET-7391",
    "ZZ-VARIANT-DATA-SECRET-7391",
    "ZZ-RELATIONSHIP-SECRET-7391",
    "ZZ-LAYOUT-SECRET-7391",
    "ZZ-COMPONENT-SECRET-7391",
    "ZZ-VARIANT-KEY-SECRET-7391",
    "ZZ-PARAM-KEY-SECRET-7391",
    "ZZ-FIGURE-DOM-SECRET-7391",
    "ZZ-INLINE-STYLE-SECRET-7391",
    "ZZ-INLINE-CONTENT-SECRET-7391",
    "ZZ-VALUE-SECRET-7391",
    "ZZ-PLACEHOLDER-SECRET-7391",
    "ZZ-ARIA-VALUE-SECRET-7391",
    "ZZ-ARIA-LABEL-SECRET-7391",
    "ZZ-CSS-BASELINE-MUTATION-7391",
    "ZZ-CSS-COMMENT-SECRET-7391",
    "ZZ-CSS-CONTENT-SECRET-7391",
    "ZZ-CSS-URL-SECRET-7391",
    "ZZ-CSS-CUSTOM-SECRET-7391",
    "ZZ-CSS-NONHEAD-SECRET-7391",
  ])
    assert.doesNotMatch(
      withoutRuntime(exported.template),
      new RegExp(sentinel),
    );
  assert.match(exported.template, /\[data-unit="unit-1"\]\{--collision-a:1\}/);
  assert.match(exported.template, /\[data-unit="unit-2"\]\{--collision-b:1\}/);
  const stateMatch = exported.template.match(
    /<script id="legaldesign-state" type="application\/json">(.*?)<\/script>/s,
  );
  assert(stateMatch);
  const templateState = JSON.parse(stateMatch[1]);
  assert.equal(Object.keys(templateState.units).length, 4);
  assert.deepEqual(Object.keys(templateState.evidence), [
    "evidence-1",
    "evidence-2",
  ]);
  assert.equal(
    new Set(
      Array.from(
        exported.template.matchAll(/data-evidence="(evidence-[12])"/g),
        (match) => match[1],
      ),
    ).size,
    2,
  );
  assert.match(exported.template, /id="evidence-1"/);
  assert.match(exported.template, /id="evidence-2"/);
});

await run("template diagram reference collisions stay one-to-one", async () => {
  const session = await pageFor({ sourceRuntime: true });
  const exported = await session.page.evaluate(() => {
    const next = window.LegalDesign.state();
    const figureId = Object.keys(next.units).find(
      (id) => next.units[id].kind === "figure",
    );
    const unit = next.units[figureId];
    unit.selected = "a";
    unit.evidence = ["foo", "evidence-1"];
    unit.variants.a = {
      axis: "form",
      why: "Two source-linked stages.",
      component: "flow",
      params: {
        stages: [
          { title: "First", detail: "foo" },
          { title: "Second", detail: "evidence-1" },
        ],
        edges: ["then"],
      },
    };
    next.evidence = {
      foo: {
        cite: "First source",
        locator: "One",
        excerpt: "First excerpt",
        link: null,
        status: "supplied-unverified",
      },
      "evidence-1": {
        cite: "Second source",
        locator: "Two",
        excerpt: "Second excerpt",
        link: null,
        status: "supplied-unverified",
      },
    };
    window.LegalDesign.setState(next);
    const scrim = document.querySelector("#popup-scrim");
    scrim.replaceChildren();
    for (const id of ["foo", "evidence-1"]) {
      const pop = document.createElement("section");
      pop.className = "pop";
      pop.id = id;
      pop.innerHTML =
        '<span class="tag">Source</span><h2>Heading</h2><p class="desc">Description</p><blockquote>Excerpt</blockquote>';
      scrim.append(pop);
    }
    return window.LegalDesign.exportTemplate(false);
  });
  await closeClean(session);
  const path = join(EXPORTS_OUT, "diagram-reference-collision.html");
  writeFileSync(path, exported);
  const reopened = await pageFor({ url: pathToFileURL(path).href });
  const refs = await reopened.page
    .locator(
      'section[data-kind="figure"] .ld-variant[data-variant="a"] .ld-diagram [data-detail]',
    )
    .evaluateAll((nodes) => nodes.map((node) => node.dataset.detail));
  assert.deepEqual(refs, ["evidence-1", "evidence-2"]);
  assert.equal(await reopened.page.locator("#evidence-1").count(), 1);
  assert.equal(await reopened.page.locator("#evidence-2").count(), 1);
  await closeClean(reopened);
});

await run(
  "template export preserves structural component parameters",
  async () => {
    const session = await pageFor({ sourceRuntime: true });
    const exported = await session.page.evaluate(() => {
      const next = window.LegalDesign.state();
      const figureId = Object.keys(next.units).find(
        (id) => next.units[id].kind === "figure",
      );
      const unit = next.units[figureId];
      unit.selected = "a";
      unit.variants = {
        a: {
          axis: "form",
          why: "The selected quadrant is part of the reusable structure.",
          component: "matrix",
          params: {
            xAxis: "Likelihood",
            yAxis: "Impact",
            quads: [
              { title: "Monitor", detail: "semantic-secret-id" },
              { title: "Plan" },
              { title: "Mitigate" },
              { title: "Escalate" },
            ],
            markAt: 3,
          },
        },
        b: {
          axis: "form",
          why: "The semantic accent is part of the reusable structure.",
          component: "flow",
          params: {
            stages: [
              { title: "Input" },
              { title: "Decision", accentRole: "decision" },
            ],
            edges: ["choose"],
          },
        },
      };
      unit.edits = { a: null, b: null };
      const host = document.querySelector(`[data-unit="${figureId}"]`);
      host.style.width = "480px";
      host.style.marginInline = "auto";
      window.LegalDesign.setState(next);
      try {
        return window.LegalDesign.exportTemplate(
          false,
          "legaldesign-template-structural-params",
        );
      } catch (error) {
        throw new Error(
          `${error.message}: ${JSON.stringify(window.LegalDesign.lastPageFitIssues)}`,
        );
      }
    });
    await closeClean(session);

    const stateMatch = exported.match(
      /<script id="legaldesign-state" type="application\/json">(.*?)<\/script>/s,
    );
    assert(stateMatch, "template export omitted portable state");
    const exportedState = JSON.parse(stateMatch[1]);
    assertValidState(exportedState, "structural-parameter template state");
    const figure = Object.values(exportedState.units).find(
      (unit) => unit.kind === "figure",
    );
    assert.equal(figure.variants.a.params.markAt, 3);
    assert.equal(
      Object.hasOwn(figure.variants.a.params.quads[0], "detail"),
      false,
    );
    assert.equal(exported.includes("semantic-secret-id"), false);
    assert.equal(figure.variants.b.params.stages[1].accentRole, "decision");

    const path = join(EXPORTS_OUT, "structural-parameter-template.html");
    writeFileSync(path, exported);
    const reopened = await pageFor({ url: pathToFileURL(path).href });
    assert.equal(await reopened.page.locator("[data-render].err").count(), 0);
    await closeClean(reopened);
  },
);

await run("max-capacity tick components survive template export", async () => {
  const session = await pageFor({ sourceRuntime: true });
  const exported = await session.page.evaluate(() => {
    const next = window.LegalDesign.state();
    const figureId = Object.keys(next.units).find(
      (id) => next.units[id].kind === "figure",
    );
    const unit = next.units[figureId];
    unit.selected = "a";
    unit.variants = {
      a: {
        axis: "form",
        why: "A six-part whole exercises the component limit.",
        component: "tickDonut",
        params: {
          parts: Array.from({ length: 6 }, (_, index) => ({
            label: `Part ${index + 1}`,
            value: 1,
          })),
          unit: "items",
          total: "6 items",
          sourceNote: "Fictional test data.",
        },
      },
      b: {
        axis: "form",
        why: "Eight rows exercise the component limit.",
        component: "tickRows",
        params: {
          items: Array.from({ length: 8 }, (_, index) => ({
            label: `Row ${index + 1}`,
            value: 1,
          })),
          unit: "items",
          xAxisTitle: "Count",
          sourceNote: "Fictional test data.",
        },
      },
    };
    unit.edits = { a: null, b: null };
    window.LegalDesign.setState(next);
    return window.LegalDesign.exportTemplate(
      false,
      "legaldesign-template-max-capacity-ticks",
    );
  });
  await closeClean(session);

  const stateMatch = exported.match(
    /<script id="legaldesign-state" type="application\/json">(.*?)<\/script>/s,
  );
  assert(stateMatch, "template export omitted portable state");
  const exportedState = JSON.parse(stateMatch[1]);
  assertValidState(exportedState, "max-capacity tick template state");
  const figure = Object.values(exportedState.units).find(
    (unit) => unit.kind === "figure",
  );
  const donutValues = figure.variants.a.params.parts.map((part) => part.value);
  const rowValues = figure.variants.b.params.items.map((item) => item.value);
  assert.equal(donutValues.reduce((sum, value) => sum + value, 0) <= 120, true);
  assert.equal(
    rowValues.every((value) => value <= 40),
    true,
  );

  const path = join(EXPORTS_OUT, "max-capacity-ticks-template.html");
  writeFileSync(path, exported);
  const reopened = await pageFor({ url: pathToFileURL(path).href });
  assert.equal(await reopened.page.locator("[data-render].err").count(), 0);
  await closeClean(reopened);
});

await run("client copies receive isolated identities", async () => {
  const session = await pageFor({ clearStorage: false });
  const { page } = session;
  await page.evaluate(() => localStorage.clear());
  await page.evaluate(() => {
    const section = document.createElement("section");
    section.className = "ld-unit";
    section.dataset.unit = "u-client-copy-decision";
    section.dataset.kind = "decision";
    section.innerHTML =
      '<div class="ld-variant" data-variant="a"><div class="ld-decision"><button type="button" value="one" data-decision-option>One</button><button type="button" value="two" data-decision-option>Two</button></div></div>';
    document.querySelector("main > .sb-slide:not([hidden])").append(section);
    const next = window.LegalDesign.state();
    next.units["u-client-copy-decision"] = {
      kind: "decision",
      selected: "a",
      variants: { a: { html: "Choose one.", axis: "single", why: "" } },
      edits: { a: null },
      placeholder: "[Choose one option.]",
    };
    window.LegalDesign.setState(next);
    window.LegalDesign.bindDecisions();
  });
  const exported = await page.evaluate(() =>
    window.LegalDesign.exportHTML(false),
  );
  const firstPath = join(EXPORTS_OUT, "client-copy-a.html");
  const secondPath = join(EXPORTS_OUT, "client-copy-b.html");
  writeFileSync(firstPath, exported);
  writeFileSync(secondPath, exported);

  await page.goto(pathToFileURL(firstPath).href, { waitUntil: "load" });
  await waitForLegalDesignReady(page);
  const firstId = (await stateFrom(page)).artifactId;
  await page.click('[data-decision-option][value="one"]');
  assert.equal(
    (await stateFrom(page)).review.decisions["u-client-copy-decision"],
    "one",
  );

  await page.goto(pathToFileURL(secondPath).href, { waitUntil: "load" });
  await waitForLegalDesignReady(page);
  const secondId = (await stateFrom(page)).artifactId;
  assert.notEqual(firstId, secondId);
  assert.equal(
    (await stateFrom(page)).review.decisions["u-client-copy-decision"],
    undefined,
  );

  await page.goto(pathToFileURL(firstPath).href, { waitUntil: "load" });
  await waitForLegalDesignReady(page);
  assert.equal((await stateFrom(page)).artifactId, firstId);
  assert.equal(
    (await stateFrom(page)).review.decisions["u-client-copy-decision"],
    "one",
  );
  await closeClean(session);
});

await run("exports across every authored asset", async () => {
  for (const asset of ["walkthrough", "report", "method"]) {
    const session = await pageFor({ asset });
    const { page } = session;
    const decision = page
      .locator('section.ld-unit[data-kind="decision"]')
      .first();
    let decisionId =
      (await decision.count()) > 0
        ? await decision.getAttribute("data-unit")
        : null;
    if (!decisionId) {
      decisionId = `u-${asset}-export-decision`;
      await page.evaluate((id) => {
        const section = document.createElement("section");
        section.className = "ld-unit";
        section.dataset.unit = id;
        section.dataset.kind = "decision";
        section.innerHTML =
          '<div class="ld-variant" data-variant="a"><div class="ld-decision"><button type="button" value="one" data-decision-option>One</button><button type="button" value="two" data-decision-option>Two</button></div></div>';
        (
          document.querySelector("main > .sb-slide:not([hidden])") ||
          document.querySelector("main")
        ).append(section);
        const next = window.LegalDesign.state();
        next.units[id] = {
          kind: "decision",
          selected: "a",
          variants: { a: { html: "Choose one.", axis: "single", why: "" } },
          edits: { a: null },
          placeholder: "[Choose one option.]",
        };
        window.LegalDesign.setState(next);
        window.LegalDesign.bindDecisions();
      }, decisionId);
    } else {
      await showUnit(page, decisionId);
    }
    const sourceDecision = page.locator(`[data-unit="${decisionId}"]`);
    const sourceOptions = sourceDecision.locator("[data-decision-option]");
    await sourceOptions.first().click();
    const clientPath = await downloadFrom(
      page,
      "#export-html",
      `${asset}-client-export.html`,
    );
    const templatePath = await downloadFrom(
      page,
      "#export-template",
      `${asset}-template-export.html`,
    );
    await closeClean(session);

    const client = await pageFor({
      clearStorage: false,
      url: pathToFileURL(clientPath).href,
    });
    assert.equal(await client.page.locator("[data-editor-only]").count(), 0);
    assert.equal(
      await client.page.locator("#export-html,#export-template").count(),
      0,
      `${asset}: client kept authoring export controls`,
    );
    const variantCounts = await client.page
      .locator("section.ld-unit:has(.ld-variant)")
      .evaluateAll((nodes) =>
        nodes.map(
          (node) => node.querySelectorAll(":scope > .ld-variant").length,
        ),
      );
    assert(
      variantCounts.every((count) => count === 1),
      `${asset}: client kept an unselected treatment`,
    );
    assert.doesNotMatch(
      await client.page.locator("body").innerText(),
      /\[[^\]]+\]/,
    );
    await showUnit(client.page, decisionId);
    const liveOptions = client.page.locator(
      `[data-unit="${decisionId}"] [data-decision-option]`,
    );
    assert(
      (await liveOptions.count()) >= 2,
      `${asset}: no live client decision`,
    );
    await liveOptions.nth(1).click();
    assert((await stateFrom(client.page)).review.decisions[decisionId]);
    await closeClean(client);

    const template = await pageFor({ url: pathToFileURL(templatePath).href });
    const templateScan = withoutRuntime(readFileSync(templatePath, "utf8"));
    for (const ban of TEMPLATE_BANS)
      assert(
        !templateScan.toLowerCase().includes(ban.toLowerCase()),
        `${asset}: template contains ${ban}`,
      );
    for (const term of TERMS[`${ASSETS[asset].split("/").at(-1)}`] || [])
      assert(
        !templateScan.toLowerCase().includes(term.toLowerCase()),
        `${asset}: template contains ${term}`,
      );
    await template.page.click("#mode-toggle");
    await revealUnitTools(
      template.page,
      template.page.locator("section.ld-unit:has(.ld-ab)").first(),
    );
    const switcher = template.page.locator("section.ld-unit .ld-ab").first();
    await switcher.locator('[data-select-variant="b"]').click();
    assert.equal(
      await switcher
        .locator('[data-select-variant="b"]')
        .getAttribute("aria-pressed"),
      "true",
    );
    await closeClean(template);
  }
});

await run(
  "new compositions use two global and structurally distinct approaches",
  async () => {
    const fixture = composedFixture({ approaches: true });
    const session = await pageFor({
      url: pathToFileURL(fixture.html).href,
      viewport: { width: 1280, height: 800 },
    });
    const { page } = session;
    await assertPageApproachContract(page, "composed artifact");
    assert.equal((await stateFrom(page)).review.approach, "a");

    const structures = await page
      .locator("[data-approach]")
      .evaluateAll((roots) =>
        Object.fromEntries(
          roots.map((root) => [
            root.getAttribute("data-approach"),
            [...root.querySelectorAll("[data-composition-section]")].map(
              (section) => ({
                units: [
                  ...section.querySelectorAll("section.ld-unit[data-unit]"),
                ].map((unit) => ({
                  kind: unit.getAttribute("data-kind"),
                  role: unit.getAttribute("data-role"),
                  row: unit.style.getPropertyValue("--ld-row"),
                  column: unit.style.getPropertyValue("--ld-column"),
                  span: unit.style.getPropertyValue("--ld-span"),
                })),
                semanticBlocks: [
                  ...section.querySelectorAll("article,table,ul,ol,svg"),
                ].map((node) => node.tagName.toLowerCase()),
              }),
            ),
          ]),
        ),
      );
    assert.notDeepEqual(
      structures.a,
      structures.b,
      "A and B must differ in page structure, not only wording",
    );

    const titles = await page.locator("[data-approach]").evaluateAll((roots) =>
      roots.map((root) => {
        const heading = root.querySelector("h1");
        const unit = heading?.closest('section[data-role="title"]');
        if (!heading || !unit) return null;
        return {
          approach: root.getAttribute("data-approach"),
          text: heading.textContent.trim(),
          span: unit.style.getPropertyValue("--ld-span"),
          row: unit.style.getPropertyValue("--ld-row"),
          column: unit.style.getPropertyValue("--ld-column"),
        };
      }),
    );
    assert.equal(titles.length, 2);
    for (const title of titles) {
      assert(title, "a page approach omitted its descriptive title");
      assert(title.text.length >= 24, `${title.approach}: title is too terse`);
      assert(title.text.split(/\s+/).length >= 4);
      assert.equal(title.span, "12");
      assert.equal(title.row, "1");
      assert.equal(title.column, "1");
    }
    assert.equal(
      await page
        .locator(
          ".ld-kicker,.ld-eyebrow,[data-kicker],[data-eyebrow],[class*='eyebrow']",
        )
        .count(),
      0,
      "new composition retained eyebrow or kicker chrome",
    );

    await page.click("#mode-toggle");
    const switcher = page.locator(
      '#ld-page-approach [data-select-approach="a"]',
    );
    await focusByKeyboard(page, switcher, "page approach switcher");
    await assertFocusRing(switcher, "page approach switcher");
    await assertInteractionFocusContract(switcher, "page approach switcher");
    await page.keyboard.press("ArrowRight");
    assert.equal((await stateFrom(page)).review.approach, "b");
    assert.equal(await page.locator('[data-approach="b"]').isVisible(), true);
    await switcher.focus();
    await page.keyboard.press("ArrowLeft");
    assert.equal((await stateFrom(page)).review.approach, "a");
    await selectPageApproach(page, "b", "composed artifact");
    const mouseFocus = await page
      .locator('#ld-page-approach [data-select-approach="b"]')
      .evaluate((node) => {
        const style = getComputedStyle(node);
        return {
          active: document.activeElement === node,
          outlineStyle: style.outlineStyle,
          outlineWidth: Number.parseFloat(style.outlineWidth) || 0,
        };
      });
    assert(
      !mouseFocus.active ||
        mouseFocus.outlineStyle === "none" ||
        mouseFocus.outlineWidth < 2,
      `page approach mouse click retained a keyboard-only halo (${JSON.stringify(mouseFocus)})`,
    );
    await selectPageApproach(page, "a", "composed artifact");
    await closeClean(session);
  },
);

await run(
  "composed v3 meets the product-level visual and responsive contract",
  async () => {
    const fixture = composedFixture({ approaches: true });
    const failures = [];
    const check = (condition, message) => {
      if (!condition) failures.push(message);
    };
    for (const viewport of [
      { width: 1440, height: 900 },
      { width: 1280, height: 800 },
      { width: 430, height: 932 },
      { width: 390, height: 844 },
    ]) {
      const themes = ["light", "dark"];
      for (const theme of themes) {
        const session = await pageFor({
          url: pathToFileURL(fixture.html).href,
          viewport,
          hasTouch: viewport.width <= 480,
        });
        const { page } = session;
        if (theme === "dark") await page.click("#theme-toggle");
        for (const approach of ["a", "b"]) {
          await selectPageApproach(
            page,
            approach,
            `composed ${viewport.width}x${viewport.height}`,
          );
          await resetVisualCaptureState(page);
          const metrics = await composedVisualMetrics(page);
          const context = `${approach} ${viewport.width}x${viewport.height} ${theme}`;

          if (approach === "a")
            check(
              (await page
                .locator('[data-unit="a-flow"] .step-no:visible')
                .count()) === 0,
              `${context}: decorative step-number eyebrows remain in the workflow`,
            );
          if (approach === "b") {
            const hierarchyTargets = await page
              .locator('[data-unit="b-hierarchy"] [data-detail]:visible')
              .evaluateAll((nodes) =>
                nodes.map((node) => ({
                  target: node.getAttribute("data-detail"),
                  accentRole: node
                    .querySelector(":scope > .box.accent")
                    ?.getAttribute("data-accent-role"),
                })),
              );
            check(
              JSON.stringify(hierarchyTargets) ===
                JSON.stringify([
                  { target: "e-input", accentRole: undefined },
                  { target: "e-judgment", accentRole: "decision" },
                  { target: "e-output", accentRole: undefined },
                ]),
              `${context}: hierarchy must expose exactly three unique branch popups and keep only Design judgment accented (${JSON.stringify(hierarchyTargets)})`,
            );
            const hierarchyAccentVisual = await page
              .locator('[data-unit="b-hierarchy"] .ld-diagram:visible')
              .evaluate((root) => {
                const accent = root.querySelector(
                  '[data-detail="e-judgment"] > .box.accent',
                );
                const neutral = root.querySelector(
                  '[data-detail="e-input"] > .box',
                );
                if (!accent || !neutral) return null;
                const accentStyle = getComputedStyle(accent);
                const neutralStyle = getComputedStyle(neutral);
                return {
                  accentFill: accentStyle.fill,
                  neutralFill: neutralStyle.fill,
                  accentStroke: accentStyle.stroke,
                  neutralStroke: neutralStyle.stroke,
                };
              });
            check(
              hierarchyAccentVisual !== null,
              `${context}: hierarchy accent geometry is missing`,
            );
            if (theme === "dark" && hierarchyAccentVisual)
              check(
                hierarchyAccentVisual.accentFill === "rgb(17, 17, 17)" &&
                  hierarchyAccentVisual.neutralFill === "rgb(17, 17, 17)" &&
                  hierarchyAccentVisual.accentStroke !==
                    hierarchyAccentVisual.neutralStroke,
                `${context}: dark nodes must use raised card fills and distinct semantic outlines (${JSON.stringify(hierarchyAccentVisual)})`,
              );
            check(
              metrics.detailByUnit.length === 3 &&
                new Set(metrics.detailByUnit.map((item) => item.target))
                  .size === 3,
              `${context}: page B must contain exactly three purposeful popup targets`,
            );
          }
          await page.screenshot({
            path: join(
              OUT,
              `composed-product-${approach}-${viewport.width}x${viewport.height}-${theme}.png`,
            ),
            fullPage: false,
          });

          if (theme === "dark")
            check(
              metrics.rootBackground === "rgb(0, 0, 0)" &&
                metrics.bodyBackground === "rgb(0, 0, 0)",
              `${context}: dark mode must use a pure-black page ground`,
            );
          check(
            Math.abs(metrics.scrollY) < 1,
            `${context}: screenshot state retained a ${metrics.scrollY}px page scroll`,
          );
          check(
            metrics.designedContrast.every((item) => item.ratio >= 4.5),
            `${context}: card or figure text falls below 4.5:1 contrast`,
          );

          check(
            metrics.documentWidth <= viewport.width + 1,
            `${approach} ${viewport.width}x${viewport.height}: document overflows horizontally`,
          );
          check(
            metrics.horizontalClipping.length === 0,
            `${approach} ${viewport.width}x${viewport.height}: units clip horizontally`,
          );
          check(
            metrics.verticalClipping.length === 0,
            `${approach} ${viewport.width}x${viewport.height}: units conceal clipped content`,
          );
          check(
            metrics.figureTypography.every(
              (figure) =>
                figure.textCount > 0 &&
                figure.minFontPx / metrics.pageScale >= 11,
            ),
            `${context}: SVG text falls below the 11px intrinsic-page floor (${JSON.stringify(
              metrics.figureTypography,
            )})`,
          );
          check(
            metrics.figureTypography.every(
              (figure) =>
                figure.textOverflow.length === 0 &&
                figure.nodeLabelOverflow.length === 0,
            ),
            `${context}: SVG labels overflow the figure or their node (${JSON.stringify(
              metrics.figureTypography,
            )})`,
          );
          check(
            Math.abs(metrics.approachBox.right - (viewport.width - 12)) <= 1 &&
              Math.abs(metrics.approachBox.bottom - (viewport.height - 64)) <=
                1 &&
              metrics.approachBox.left >= 12 &&
              metrics.approachBox.width >= viewport.width - 240 &&
              metrics.approachBox.height >= viewport.height * 0.7,
            `${approach} ${viewport.width}x${viewport.height}: composition does not fill the adaptive window inside its navigation and book-control gutters (${JSON.stringify(metrics.approachBox)})`,
          );
          if (viewport.width > 480)
            check(
              metrics.approachBox.bottom <= viewport.height + 1,
              `${approach} ${viewport.width}x${viewport.height}: one-page composition ends at ${Math.round(
                metrics.approachBox.bottom,
              )}px and is clipped below the ${viewport.height}px viewport`,
            );

          check(
            Math.abs(
              metrics.titleBox.left -
                metrics.approachBox.left -
                metrics.pageInsets.left,
            ) <= 1.5 &&
              Math.abs(
                metrics.titleBox.right -
                  metrics.approachBox.right +
                  metrics.pageInsets.right,
              ) <= 1.5,
            `${approach} ${viewport.width}x${viewport.height}: descriptive title is not full width`,
          );
          check(
            metrics.titleContent.text.split(/\s+/).length >= 4 &&
              metrics.titleContent.height / metrics.pageScale >= 28 &&
              metrics.titleContent.fontSize >= 24 &&
              metrics.titleContent.display !== "none" &&
              metrics.titleContent.visibility !== "hidden" &&
              metrics.titleBox.top >= metrics.approachBox.top - 1 &&
              metrics.titleBox.top < viewport.height,
            `${context}: descriptive title is not visibly rendered (${JSON.stringify(
              metrics.titleContent,
            )})`,
          );
          const bareTitle = {
            background: "rgba(0, 0, 0, 0)",
            borderTop: "0px",
            borderRight: "0px",
            borderBottom: "0px",
            borderLeft: "0px",
            radius: "0px",
            shadow: "none",
            paddingLeft: "0px",
            paddingRight: "0px",
          };
          check(
            JSON.stringify(metrics.titleSurface) === JSON.stringify(bareTitle),
            `${approach} ${viewport.width}x${viewport.height}: title is styled as a generic card`,
          );

          check(
            /\d+(?:\.\d+)?px/.test(metrics.shadowSoft),
            `${approach}: --shadow-soft is missing or not a usable shadow token`,
          );
          check(
            metrics.cardUnitCount >= 1 && metrics.figureUnitCount >= 1,
            `${approach}: composition lacks the card/figure surface hierarchy`,
          );
          if (theme === "light")
            check(
              metrics.shadowedCardUnitCount === metrics.cardUnitCount,
              `${approach}: light-mode raised point cards do not use soft elevation`,
            );
          check(
            metrics.shadowedFigureUnitCount === 0 &&
              metrics.planarFigureUnitCount === metrics.figureUnitCount,
            `${approach}: explanatory figures must stay planar with hairline structure`,
          );
          check(
            metrics.shadowedUnitCount < metrics.unitCount,
            `${approach}: elevation was applied indiscriminately to every box`,
          );

          check(
            metrics.sourceText.length === 0,
            `${approach}: visible surface copy exposes raw Source: labels`,
          );
          check(
            metrics.externalLinks.length > 0,
            `${approach}: source record has no original link`,
          );
          check(
            metrics.externalLinks.every((link) => link.popup),
            `${approach}: original source links must exist only inside evidence popups`,
          );
          check(
            metrics.groundedByUnit.length > 0,
            `${approach}: composition has no grounded surface units`,
          );
          check(
            metrics.genericEvidenceChrome === 0,
            `${approach}: generic Evidence badge or grouped disclosure leaked onto the surface`,
          );
          check(
            metrics.detailByUnit.length > 0 &&
              metrics.detailByUnit.every(
                (item) =>
                  item.role === "button" &&
                  item.tabindex === "0" &&
                  item.popup === "dialog" &&
                  item.cursor === "pointer",
              ),
            `${approach}: purpose-specific whole-box popup targets are missing their interaction contract`,
          );

          const firstDetailUnit = metrics.detailByUnit[0];
          if (firstDetailUnit) {
            const disclosure = page
              .locator(
                `[data-unit="${firstDetailUnit.id}"][data-detail="${firstDetailUnit.target}"], [data-unit="${firstDetailUnit.id}"] [data-detail="${firstDetailUnit.target}"]`,
              )
              .first();
            await focusByKeyboard(
              page,
              disclosure,
              `${context} semantic popup target`,
            );
            await assertInteractionFocusContract(
              disclosure,
              `${context} semantic popup target`,
            );
            await page.evaluate(() => window.getSelection()?.removeAllRanges());
            const child = disclosure.locator("h1,h2,h3,p,text").first();
            await child.click();
            const selection = await page.evaluate(() => ({
              text: window.getSelection()?.toString() || "",
              ranges: window.getSelection()?.rangeCount || 0,
            }));
            check(
              selection.text === "" && selection.ranges === 0,
              `${context}: mouse click selected popup-trigger copy (${JSON.stringify(selection)})`,
            );
            const popup = page.locator("#popup-scrim .pop:visible");
            check(
              (await popup.count()) === 1,
              `${approach}: whole semantic box does not open one popup`,
            );
            check(
              (await popup.getAttribute("data-evidence-id")) ===
                firstDetailUnit.target,
              `${approach}: whole box opens the wrong purposeful detail`,
            );
            check(
              !/^(evidence|more detail|source)$/i.test(
                (await popup.locator("h2").textContent())?.trim() || "",
              ),
              `${approach}: popup title is generic`,
            );
            check(
              (await popup.locator(".ld-popup-section").count()) >= 1,
              `${approach}: popup has no structured explanation`,
            );
            check(
              (await popup.locator('a[href^="http"]').count()) >= 1,
              `${approach}: purposeful popup omits the original source link`,
            );
            check(
              (await popup
                .locator("[data-evidence-step],.ld-evidence-sequence")
                .count()) === 0,
              `${approach}: rejected evidence carousel is still present`,
            );
            await assertPopupGeometry(popup, viewport, `${context} popup`);
            if (theme === "light" && [1440, 430].includes(viewport.width)) {
              await page.evaluate(() => window.scrollTo(0, 0));
              await popup.evaluate((node) => {
                node.scrollTop = 0;
              });
              await page.screenshot({
                path: join(
                  OUT,
                  `composed-popup-${approach}-${viewport.width}x${viewport.height}-${theme}.png`,
                ),
                fullPage: false,
              });
            }
            await page.keyboard.press("Escape");
          }
        }
        await closeClean(session);
      }
    }
    assert.deepEqual(failures, []);
  },
);

await run(
  "finished composed shell obeys placement and evidence contract",
  async () => {
    const fixture = composedFixture();
    const session = await pageFor({
      url: pathToFileURL(fixture.html).href,
      viewport: { width: 1280, height: 800 },
    });
    const { page } = session;
    assert.equal(
      await page.locator("html").getAttribute("data-composed-shell"),
      "",
    );
    await assertPageApproachContract(page, "finished composed shell");
    assert.equal(
      await page.locator("[data-composition-section]:visible").count(),
      2,
    );
    assert.deepEqual(
      await page
        .locator('[data-approach="a"] section.ld-unit[data-unit]')
        .evaluateAll((nodes) => nodes.map((node) => node.dataset.unit)),
      ["a-title", "a-summary", "a-flow", "a-output"],
    );
    const sourceState = await stateFrom(page);
    await page.evaluate(() => {
      const next = window.LegalDesign.state();
      next.units["a-flow"].variants.a.params.stages[0].title =
        "Updated first stage";
      window.LegalDesign.setState(next);
    });
    assert.match(
      await page
        .locator('[data-unit="a-flow"] .ld-variant:not([hidden]) .ld-diagram')
        .innerText(),
      /Updated first stage/i,
    );
    assert.equal(
      sourceState.approaches.a.composition.sections[0].layout.columns,
      12,
    );
    assert.deepEqual(
      sourceState.approaches.a.composition.sections[0].layout.placements,
      JSON.parse(readFileSync(NOVEL_COMPOSITION_PLAN, "utf8")).approaches.a
        .composition.sections[0].layout.placements,
    );
    const flowBox = await page.locator('[data-unit="a-flow"]').boundingBox();
    const outputBox = await page
      .locator('[data-unit="a-output"]')
      .boundingBox();
    assert(flowBox && outputBox);
    assert(flowBox.y + flowBox.height < outputBox.y);
    assert(Math.abs(flowBox.x - outputBox.x) < 2);
    assert(Math.abs(flowBox.width - outputBox.width) < 2);
    assert.equal(
      await page.evaluate(
        () =>
          document.documentElement.scrollWidth <=
          document.documentElement.clientWidth,
      ),
      true,
    );
    const inputTrigger = page
      .locator('[data-unit="a-flow"] [data-detail="e-ask"]')
      .first();
    await inputTrigger.focus();
    await inputTrigger.click();
    assert.equal(await page.locator("#e-ask").isVisible(), true);
    assert.equal(
      await page.locator("#e-ask h2").textContent(),
      sourceState.evidence["e-ask"].popup.title,
    );
    assert(
      (await page.locator("#e-ask .ld-popup-section").count()) >= 2,
      "purpose-specific popup omitted its explanatory sections",
    );
    assert.equal(await page.locator("#e-ask [data-evidence-step]").count(), 0);
    await page.keyboard.press("Escape");
    await assertFocusReturned(page, "e-ask", "composed Ask detail");
    const svgTextContract = await inputTrigger
      .locator("text")
      .first()
      .evaluate((node) => ({
        userSelect: getComputedStyle(node).userSelect,
        pointerEvents: getComputedStyle(node).pointerEvents,
      }));
    assert.equal(svgTextContract.userSelect, "none");
    assert.equal(svgTextContract.pointerEvents, "none");
    await page.screenshot({
      path: join(OUT, "composed-1280x800-light.png"),
      fullPage: true,
    });
    await page.click("#theme-toggle");
    assert.deepEqual(
      await page.evaluate(() => [
        getComputedStyle(document.documentElement).backgroundColor,
        getComputedStyle(document.body).backgroundColor,
      ]),
      ["rgb(0, 0, 0)", "rgb(0, 0, 0)"],
    );
    await page.screenshot({
      path: join(OUT, "composed-1280x800-dark.png"),
      fullPage: true,
    });
    await closeClean(session);

    for (const viewport of [
      { width: 430, height: 932 },
      { width: 390, height: 844 },
    ]) {
      const mobile = await pageFor({
        url: pathToFileURL(fixture.html).href,
        viewport,
        hasTouch: true,
      });
      const first = await mobile.page
        .locator('[data-unit="a-flow"]')
        .boundingBox();
      const second = await mobile.page
        .locator('[data-unit="a-output"]')
        .boundingBox();
      assert(first && second);
      assert(first.y + first.height < second.y);
      const leftAlignment = second.x - first.x;
      const rightAlignment = first.x + first.width - (second.x + second.width);
      assert(
        Math.abs(leftAlignment) < 1,
        `phone overview must preserve the authored left column alignment (${leftAlignment})`,
      );
      assert(
        Math.abs(rightAlignment) < 1,
        `phone overview must preserve the authored right column alignment (${rightAlignment})`,
      );
      assert.equal(
        await mobile.page.evaluate(
          () =>
            document.documentElement.scrollWidth <=
            document.documentElement.clientWidth,
        ),
        true,
      );
      await mobile.page.screenshot({
        path: join(
          OUT,
          `composed-${viewport.width}x${viewport.height}-light.png`,
        ),
        fullPage: true,
      });
      await mobile.page.click("#theme-toggle");
      assert.deepEqual(
        await mobile.page.evaluate(() => [
          getComputedStyle(document.documentElement).backgroundColor,
          getComputedStyle(document.body).backgroundColor,
        ]),
        ["rgb(0, 0, 0)", "rgb(0, 0, 0)"],
      );
      await mobile.page.screenshot({
        path: join(
          OUT,
          `composed-${viewport.width}x${viewport.height}-dark.png`,
        ),
        fullPage: true,
      });
      await closeClean(mobile);
    }
  },
);

await run(
  "composed walkthrough and report honor their reading forms",
  async () => {
    const sourceSections = JSON.parse(
      readFileSync(NOVEL_COMPOSITION_PLAN, "utf8"),
    ).approaches.a.composition.sections;
    const walkthroughFixture = composedFixture({ form: "walkthrough" });
    const walkthrough = await pageFor({
      url: pathToFileURL(walkthroughFixture.html).href,
    });
    assert.equal(
      await walkthrough.page.locator(".ld-composed-section:visible").count(),
      1,
    );
    assert.equal(
      await walkthrough.page.locator("[data-walkthrough-status]").textContent(),
      `1 / ${sourceSections.length}`,
    );
    await walkthrough.page.locator("[data-walkthrough-next]").click();
    assert.equal(
      await walkthrough.page
        .locator(".ld-composed-section:visible")
        .getAttribute("data-composition-section"),
      sourceSections[1].id,
    );
    assert.equal((await stateFrom(walkthrough.page)).review.location, 1);
    const walkthroughClientPath = await downloadFrom(
      walkthrough.page,
      "#export-html",
      "composed-walkthrough-client.html",
    );
    await closeClean(walkthrough);
    const walkthroughClient = await pageFor({
      url: pathToFileURL(walkthroughClientPath).href,
    });
    assertValidState(
      await stateFrom(walkthroughClient.page),
      "composed walkthrough client state",
    );
    assert.equal(
      await walkthroughClient.page
        .locator(".ld-composed-section:visible")
        .count(),
      1,
    );
    assert.equal(
      await walkthroughClient.page
        .locator("[data-walkthrough-status]")
        .textContent(),
      `2 / ${sourceSections.length}`,
    );
    await walkthroughClient.page.locator("[data-walkthrough-previous]").click();
    assert.equal(
      await walkthroughClient.page
        .locator(".ld-composed-section:visible")
        .getAttribute("data-composition-section"),
      sourceSections[0].id,
    );
    await closeClean(walkthroughClient);

    const reportFixture = composedFixture({ form: "report" });
    const report = await pageFor({
      url: pathToFileURL(reportFixture.html).href,
    });
    assert.equal(
      await report.page.locator(".ld-composed-section:visible").count(),
      1,
    );
    assert.deepEqual(
      await report.page
        .locator("[data-report-section] .ld-index-label")
        .evaluateAll((nodes) => nodes.map((node) => node.textContent.trim())),
      [
        "LegalQuants /legaldesign skill, explained",
        "Six stages from intake to export",
      ],
    );
    await report.page.locator('[data-report-section="1"]').click();
    assert.equal((await stateFrom(report.page)).review.location, 1);
    assert.equal(
      await report.page
        .locator('[data-report-section="1"]')
        .getAttribute("aria-current"),
      "true",
    );
    const reportClientPath = await downloadFrom(
      report.page,
      "#export-html",
      "composed-report-client.html",
    );
    const reportTemplatePath = await downloadFrom(
      report.page,
      "#export-template",
      "composed-report-template.html",
    );
    await closeClean(report);
    const reportClient = await pageFor({
      url: pathToFileURL(reportClientPath).href,
    });
    assertValidState(
      await stateFrom(reportClient.page),
      "composed report client state",
    );
    assert.equal(
      await reportClient.page.locator("[data-report-section]").count(),
      sourceSections.length,
    );
    assert.equal(
      await reportClient.page
        .locator('[data-report-section="1"]')
        .getAttribute("aria-current"),
      "true",
    );
    await reportClient.page.locator('[data-report-section="0"]').click();
    assert.equal((await stateFrom(reportClient.page)).review.location, 0);
    await closeClean(reportClient);
    const reportTemplateSource = withoutRuntime(
      readFileSync(reportTemplatePath, "utf8"),
    );
    for (const section of sourceSections)
      assert.doesNotMatch(reportTemplateSource, new RegExp(section.purpose));
    assert.match(reportTemplateSource, /\[Section 1\.\]/);
  },
);

await run(
  "composed decision state and exports survive end to end",
  async () => {
    const fixture = composedFixture({ decision: true, form: "report" });
    const session = await pageFor({ url: pathToFileURL(fixture.html).href });
    const { page } = session;
    const original = await stateFrom(page);
    await assertPageApproachContract(page, "composed decision");

    const decisionId = "a-summary";
    const decision = page.locator(`[data-unit="${decisionId}"]`);
    await decision.locator('[data-decision-option][value="A"]').click();
    await decision
      .locator("[data-decision-custom]")
      .fill("Confirmed credentials");
    await decision.locator("[data-decision-custom]").press("Tab");
    await decision
      .locator("[data-decision-note]")
      .fill("Counsel should review the source gap.");
    await decision.locator("[data-decision-note]").press("Tab");

    await page.click("#mode-toggle");
    const savedPath = await downloadFrom(
      page,
      "#ld-save",
      "composed-decision-saved.html",
    );
    const savedState = await stateFrom(page);
    await closeClean(session);

    const reopened = await pageFor({
      clearStorage: false,
      url: pathToFileURL(savedPath).href,
    });
    const reopenedState = await stateFrom(reopened.page);
    assert.deepEqual(reopenedState, savedState);
    assert.deepEqual(reopenedState.approaches, original.approaches);
    assert.deepEqual(reopenedState.review.decisions[decisionId], {
      choice: "A",
      custom: "Confirmed credentials",
      note: "Counsel should review the source gap.",
    });
    assert.equal(
      await reopened.page
        .locator(
          `[data-unit="${decisionId}"] [data-decision-option][value="A"]`,
        )
        .getAttribute("aria-pressed"),
      "true",
    );

    const clientPath = await downloadFrom(
      reopened.page,
      "#export-html",
      "composed-decision-client.html",
    );
    const templatePath = await downloadFrom(
      reopened.page,
      "#export-template",
      "composed-decision-template.html",
    );
    await closeClean(reopened);

    const client = await pageFor({
      clearStorage: false,
      url: pathToFileURL(clientPath).href,
    });
    const clientState = await stateFrom(client.page);
    assertValidState(clientState, "composed decision client state");
    assert.deepEqual(
      await client.page
        .locator("[data-approach]")
        .evaluateAll((roots) =>
          roots.map((root) => root.getAttribute("data-approach")),
        ),
      ["a"],
    );
    assert.equal(await client.page.locator("#ld-page-approach").count(), 0);
    assert.equal(await client.page.locator("[data-editor-only]").count(), 0);
    assert.equal(clientState.sourceSchemaVersion, "legaldesign.build.v3");
    assert.deepEqual(Object.keys(clientState.approaches), ["a"]);
    assert.equal("claims" in clientState, false);
    assert.equal(clientState.review.approach, "a");
    assert.deepEqual(clientState.review.decisions[decisionId], {
      choice: "A",
      custom: "Confirmed credentials",
      note: "Counsel should review the source gap.",
    });
    assert(
      Object.keys(clientState.units).every((unitId) => unitId.startsWith("a-")),
      "client state retained units from the inactive page approach",
    );
    await client.page
      .locator(`[data-unit="${decisionId}"] [data-decision-option][value="B"]`)
      .click();
    assert.equal(
      (await stateFrom(client.page)).review.decisions[decisionId].choice,
      "B",
    );
    await client.page.reload();
    assert.equal(
      (await stateFrom(client.page)).review.decisions[decisionId].choice,
      "B",
    );
    assert.equal(await client.page.locator("#ld-response-save").count(), 0);
    assert.equal(
      await client.page.evaluate(() => typeof LegalDesign.save),
      "undefined",
    );
    await closeClean(client);

    const templateSource = withoutRuntime(readFileSync(templatePath, "utf8"));
    assert.equal(templateSource.includes(original.brief.title), false);
    assert.equal(
      templateSource.includes(original.evidence["e-input"].cite),
      false,
    );
    const template = await pageFor({ url: pathToFileURL(templatePath).href });
    const templateState = await stateFrom(template.page);
    assertValidState(templateState, "composed decision template state");
    await assertPageApproachContract(template.page, "composed template");
    assert.deepEqual(Object.keys(templateState.approaches), ["a", "b"]);
    assert.deepEqual(templateState.review.decisions, {});
    const approachUnitIds = Object.fromEntries(
      Object.entries(templateState.approaches).map(([key, approach]) => [
        key,
        approach.composition.sections.flatMap((section) => section.unitIds),
      ]),
    );
    assert.equal(
      approachUnitIds.a.some((unitId) => approachUnitIds.b.includes(unitId)),
      false,
      "template approaches share units",
    );
    assert(
      Object.values(templateState.units).every(
        (unit) => Object.keys(unit.variants).length === 1,
      ),
      "v3 template reintroduced per-unit A/B",
    );

    const templateDecision = template.page
      .locator('section.ld-unit[data-kind="decision"]')
      .first();
    assert.equal(await templateDecision.count(), 1);
    await templateDecision.locator("[data-decision-option]").first().click();
    const mappedDecisionId = await templateDecision.getAttribute("data-unit");
    assert((await stateFrom(template.page)).review.decisions[mappedDecisionId]);

    const mappedEvidence = template.page.locator("[data-detail]").first();
    const evidenceId = await mappedEvidence.getAttribute("data-detail");
    assert(evidenceId);
    await showUnit(
      template.page,
      await mappedEvidence.evaluate(
        (node) => node.closest("[data-unit]").dataset.unit,
      ),
    );
    await mappedEvidence.click();
    assert.equal(
      await template.page.locator(`#${evidenceId}`).isVisible(),
      true,
    );
    await template.page.keyboard.press("Escape");
    await selectPageApproach(template.page, "b", "composed template");
    await closeClean(template);
  },
);

await run(
  "composed templates receive isolated non-matter identities",
  async () => {
    const ids = [];
    for (const form of ["walkthrough", "report"]) {
      const fixture = composedFixture({ form });
      const session = await pageFor({ url: pathToFileURL(fixture.html).href });
      for (let copy = 0; copy < 2; copy += 1) {
        const exported = await session.page.evaluate(() =>
          window.LegalDesign.exportTemplate(false),
        );
        const match = exported.match(
          /<script id="legaldesign-state" type="application\/json">(.*?)<\/script>/s,
        );
        assert(match, `${form} template omitted portable state`);
        const exportedState = JSON.parse(match[1]);
        assertValidState(exportedState, `${form} template state`);
        assert.match(
          exportedState.artifactId,
          /^legaldesign-template-[a-z0-9-]+$/,
        );
        assert.doesNotMatch(
          exportedState.artifactId,
          /browser|walkthrough|report/,
        );
        assert.match(
          exported,
          new RegExp(`data-template-id="${exportedState.artifactId}"`),
        );
        ids.push(exportedState.artifactId);
      }
      await closeClean(session);
    }
    assert.equal(new Set(ids).size, ids.length);
    assert.equal(
      new Set(ids.map((id) => `legaldesign:${id}:template:v1`)).size,
      ids.length,
    );
  },
);

await run("template copies receive isolated identities", async () => {
  const fixture = composedFixture();
  const source = await pageFor({ url: pathToFileURL(fixture.html).href });
  const exported = await source.page.evaluate(() =>
    window.LegalDesign.exportTemplate(false),
  );
  const stateMatch = exported.match(
    /<script id="legaldesign-state" type="application\/json">(.*?)<\/script>/s,
  );
  assert(stateMatch, "template export omitted portable state");
  const blueprintId = JSON.parse(stateMatch[1]).artifactId;
  await closeClean(source);
  const firstPath = join(fixture.directory, "template-copy-one.html");
  const secondPath = join(fixture.directory, "template-copy-two.html");
  writeFileSync(firstPath, exported);
  writeFileSync(secondPath, exported);

  const first = await pageFor({ url: pathToFileURL(firstPath).href });
  const second = await pageFor({ url: pathToFileURL(secondPath).href });
  assert.equal(
    await first.page.locator("html").getAttribute("data-template-kind"),
    "exported",
  );
  assert.equal(
    await first.page.locator("html").getAttribute("data-template-blueprint-id"),
    blueprintId,
  );
  const firstId = (await stateFrom(first.page)).artifactId;
  const secondId = (await stateFrom(second.page)).artifactId;
  assert.match(firstId, new RegExp(`^${blueprintId}-copy-[a-z0-9]+$`));
  assert.match(secondId, new RegExp(`^${blueprintId}-copy-[a-z0-9]+$`));
  assert.notEqual(firstId, secondId);
  assert.notEqual(
    `legaldesign:${firstId}:template:v1`,
    `legaldesign:${secondId}:template:v1`,
  );
  await first.page.evaluate(() => {
    history.replaceState(null, "", "?frame=2#source-detail");
  });
  await first.page.reload({ waitUntil: "load" });
  assert.equal((await stateFrom(first.page)).artifactId, firstId);
  await closeClean(first);
  await closeClean(second);
});

await run("composed templates preserve rich semantic topology", async () => {
  const fixture = composedFixture({ rich: true });
  const source = await pageFor({ url: pathToFileURL(fixture.html).href });
  const exported = await source.page.evaluate(() =>
    window.LegalDesign.exportTemplate(false),
  );
  await closeClean(source);
  for (const sentinel of [
    "ZZ-RICH-LIST-FIRST-7391",
    "ZZ-RICH-LIST-SECOND-7391",
    "ZZ-RICH-HEADING-7391",
    "ZZ-RICH-VALUE-7391",
  ])
    assert.doesNotMatch(withoutRuntime(exported), new RegExp(sentinel));
  const templatePath = join(fixture.directory, "rich-template.html");
  writeFileSync(templatePath, exported);
  const template = await pageFor({ url: pathToFileURL(templatePath).href });
  assert.equal(
    await template.page
      .locator('[data-approach="a"] [data-variant="a"] ul')
      .count(),
    1,
  );
  assert.equal(
    await template.page
      .locator('[data-approach="a"] [data-variant="a"] li')
      .count(),
    2,
  );
  assert.equal(
    await template.page
      .locator('[data-approach="b"] [data-variant="a"] table')
      .count(),
    1,
  );
  assert.equal(
    await template.page
      .locator('[data-approach="b"] [data-variant="a"] th')
      .count(),
    1,
  );
  assert.equal(
    await template.page
      .locator('[data-approach="b"] [data-variant="a"] td')
      .count(),
    1,
  );
  assert.deepEqual(
    await template.page
      .locator('[data-approach="a"] li')
      .evaluateAll((nodes) => nodes.map((node) => node.textContent.trim())),
    ["[List item.]", "[List item.]"],
  );
  assert.equal(
    await template.page.locator('[data-approach="b"] th').textContent(),
    "[Column heading.]",
  );
  assert.equal(
    await template.page.locator('[data-approach="b"] td').textContent(),
    "[Table value.]",
  );
  await closeClean(template);
});

await run("composed design authority wins the token cascade", async () => {
  const standardFixture = composedFixture({ approaches: true });
  const customFixture = composedFixture({ design: true });
  for (const viewport of [
    { width: 1280, height: 800 },
    { width: 430, height: 932 },
  ]) {
    const standard = await pageFor({
      url: pathToFileURL(standardFixture.html).href,
      viewport,
      hasTouch: viewport.width <= 480,
    });
    const custom = await pageFor({
      url: pathToFileURL(customFixture.html).href,
      viewport,
      hasTouch: viewport.width <= 480,
    });
    for (const theme of ["light", "dark"]) {
      if (theme === "dark") {
        await standard.page.click("#theme-toggle");
        await custom.page.click("#theme-toggle");
      }
      for (const approach of ["a", "b"]) {
        await selectPageApproach(
          standard.page,
          approach,
          `standard ${viewport.width}px ${theme}`,
        );
        await selectPageApproach(
          custom.page,
          approach,
          `custom ${viewport.width}px ${theme}`,
        );
        await resetVisualCaptureState(standard.page);
        await resetVisualCaptureState(custom.page);
        const standardIdentity = await composedLiveIdentity(standard.page);
        const customIdentity = await composedLiveIdentity(custom.page);
        assert.equal(
          customIdentity.markup,
          standardIdentity.markup,
          `${approach} ${viewport.width}px ${theme}: custom palette changed page structure`,
        );
        assert.equal(
          customIdentity.popupMarkup,
          standardIdentity.popupMarkup,
          `${approach} ${viewport.width}px ${theme}: custom palette changed popup structure`,
        );
        assert.deepEqual(
          customIdentity.geometryAndStyle,
          standardIdentity.geometryAndStyle,
          `${approach} ${viewport.width}px ${theme}: custom palette changed geometry, type, radii, shadows, or interaction affordances`,
        );
        assert.notEqual(
          customIdentity.colors["--red"],
          standardIdentity.colors["--red"],
          `${approach} ${viewport.width}px ${theme}: custom accent was not applied`,
        );
        assert.equal(
          customIdentity.colors["--red"],
          theme === "dark" ? "#ff8a80" : "#123456",
          `${approach} ${viewport.width}px ${theme}: wrong custom accent`,
        );
      }
    }
    await closeClean(standard);
    await closeClean(custom);
  }
});

await run("chart enum parameters survive template reopen", async () => {
  const directory = mkdtempSync(join(tmpdir(), "legaldesign-enum-"));
  const source = await pageFor();
  await source.page.evaluate(() => {
    const next = window.LegalDesign.state();
    const entry = Object.entries(next.units).find(
      ([, unit]) => unit.kind === "figure" && unit.variants.b,
    );
    if (!entry) throw new Error("fixture has no two-variant figure");
    const [, unit] = entry;
    unit.variants.a = {
      component: "hairlineLine",
      params: {
        points: [
          { x: 1, y: 2, label: "First" },
          { x: 2, y: 3, label: "Second" },
          { x: 3, y: 4, label: "Third" },
        ],
        xLabels: ["First", "Second", "Third"],
        xAxisTitle: "Sequence",
        yAxisTitle: "Measure",
        unit: "items",
        baselineZero: "yes",
        sourceNote: "Neutral test data.",
      },
      axis: "form",
      why: "Tests a zero-baseline enum.",
    };
    unit.variants.b = {
      component: "tickGauge",
      params: {
        value: 72,
        max: 100,
        label: "Review complete",
        unit: "percent",
        open: "no",
        sourceNote: "Neutral test data.",
      },
      axis: "form",
      why: "Tests a yes-or-no open-state enum.",
    };
    window.LegalDesign.setState(next);
  });
  const exported = await source.page.evaluate(() =>
    window.LegalDesign.exportTemplate(false),
  );
  await closeClean(source);
  const templatePath = join(directory, "enum-template.html");
  writeFileSync(templatePath, exported);
  const template = await pageFor({ url: pathToFileURL(templatePath).href });
  const state = await stateFrom(template.page);
  const figureEntry = Object.entries(state.units).find(
    ([, unit]) => unit.kind === "figure" && unit.variants.b,
  );
  assert(figureEntry, "template omitted the chart unit");
  const [figureId, figure] = figureEntry;
  assert.equal(figure.variants.a.params.baselineZero, "yes");
  assert.equal(figure.variants.b.params.open, "no");
  assert.equal(
    await template.page.locator(`[data-unit="${figureId}"] svg`).count(),
    2,
  );
  await template.page.click("#mode-toggle");
  await revealUnitTools(
    template.page,
    template.page.locator(`[data-unit="${figureId}"]`),
  );
  await template.page
    .locator(`[data-unit="${figureId}"] [data-select-variant="b"]`)
    .click();
  assert.equal(
    await template.page
      .locator(`[data-unit="${figureId}"] [data-variant="b"] svg`)
      .isVisible(),
    true,
  );
  await closeClean(template);
});

await run(
  "multi-select decisions retain choices with custom text and notes",
  async () => {
    const fixture = composedFixture({ decision: true, multi: true });
    const session = await pageFor({ url: pathToFileURL(fixture.html).href });
    const decision = session.page.locator('[data-unit="a-summary"]');
    await decision.locator('[data-decision-option][value="A"]').click();
    await decision.locator('[data-decision-option][value="B"]').click();
    await decision.locator("[data-decision-custom]").fill("Escalate in phases");
    await decision.locator("[data-decision-custom]").press("Tab");
    await decision
      .locator("[data-decision-note]")
      .fill("Preserve both triggers.");
    await decision.locator("[data-decision-note]").press("Tab");
    assert.deepEqual(
      (await stateFrom(session.page)).review.decisions["a-summary"],
      {
        choices: ["A", "B"],
        custom: "Escalate in phases",
        note: "Preserve both triggers.",
      },
    );
    assert.deepEqual(
      await decision
        .locator('[data-decision-option][aria-pressed="true"]')
        .evaluateAll((nodes) => nodes.map((node) => node.value)),
      ["A", "B"],
    );
    await session.page.click("#mode-toggle");
    const saved = await downloadFrom(
      session.page,
      "#ld-save",
      "composed-multi-decision.html",
    );
    await closeClean(session);
    const reopened = await pageFor({ url: pathToFileURL(saved).href });
    assert.deepEqual(
      (await stateFrom(reopened.page)).review.decisions["a-summary"],
      {
        choices: ["A", "B"],
        custom: "Escalate in phases",
        note: "Preserve both triggers.",
      },
    );
    await closeClean(reopened);
  },
);

await run("phone editor keeps compact contextual controls", async () => {
  for (const viewport of [
    { width: 430, height: 932 },
    { width: 390, height: 844 },
  ]) {
    for (const theme of ["light", "dark"]) {
      const session = await pageFor({
        viewport,
        hasTouch: true,
        sourceRuntime: true,
      });
      const { page } = session;
      if (theme === "dark") await page.click("#theme-toggle");
      await page.click("#mode-toggle");
      assert.equal(
        await page.evaluate(() => document.documentElement.scrollWidth),
        viewport.width,
      );
      const undersized = await page
        .locator("button:visible,input:visible,select:visible")
        .evaluateAll((nodes) =>
          nodes
            .filter((node) => {
              const box = node.getBoundingClientRect();
              return box.width < 44 || box.height < 44;
            })
            .map(
              (node) =>
                `${node.id || node.getAttribute("aria-label")}:${node.getBoundingClientRect().width}x${node.getBoundingClientRect().height}`,
            ),
        );
      assert.deepEqual(undersized, []);
      assert.equal(
        await page.locator("#popup-scrim > .pop").count(),
        await page.locator(".pop").count(),
      );
      assert.equal(
        await page
          .locator(
            ".ld-review,.ld-reaction,.ld-comment,.ld-sheet-open,.ld-bottom-save,.ld-phone-sheet,.ld-selection-popover",
          )
          .count(),
        0,
      );
      const tools = page.locator('[data-unit="u-title"] .ld-unit-tools');
      await page
        .locator('[data-unit="u-title"] [data-editable]:visible')
        .first()
        .tap();
      assert.equal(await tools.isVisible(), true);
      const contextualSizes = await tools
        .locator("button")
        .evaluateAll((nodes) =>
          nodes.map((node) => node.getBoundingClientRect().height),
        );
      assert(contextualSizes.every((height) => height >= 44));
      await tools.locator('[data-select-variant="b"]').tap();
      assert.equal((await stateFrom(page)).units["u-title"].selected, "b");
      await closeClean(session);
    }
  }
});

await run(
  "phone contracts across walkthrough, report, and method map",
  async () => {
    for (const asset of ["walkthrough", "report", "method"]) {
      for (const viewport of [
        { width: 430, height: 932 },
        { width: 390, height: 844 },
      ]) {
        for (const theme of ["light", "dark"]) {
          const session = await pageFor({
            asset,
            viewport,
            hasTouch: true,
            sourceRuntime: true,
          });
          const { page } = session;
          if (theme === "dark") await page.click("#theme-toggle");
          await page.click("#mode-toggle");
          assert.equal(
            await page.evaluate(() => document.documentElement.scrollWidth),
            viewport.width,
            `${asset} ${viewport.width} ${theme}: horizontal overflow`,
          );
          const undersized = await page
            .locator(
              "button:visible,input:visible,select:visible,[role='button']:visible",
            )
            .evaluateAll((nodes) =>
              nodes
                .filter((node) => {
                  const box = node.getBoundingClientRect();
                  const frame = node.closest(".ld-fixed-page");
                  const scale = frame
                    ? frame.getBoundingClientRect().width / frame.offsetWidth
                    : 1;
                  return box.width / scale < 44 || box.height / scale < 44;
                })
                .map((node) => {
                  const box = node.getBoundingClientRect();
                  return `${node.id || node.getAttribute("aria-label") || node.textContent.trim()}:${box.width}x${box.height}`;
                }),
            );
          assert.deepEqual(
            undersized,
            [],
            `${asset} ${viewport.width} ${theme}: chrome controls below44 physical px or page controls below44 intrinsic px`,
          );
          assert.equal(
            await page.locator("#popup-scrim > .pop").count(),
            await page.locator(".pop").count(),
          );
          assert.equal(
            await page
              .locator(
                ".ld-review,.ld-reaction,.ld-comment,.ld-sheet-open,.ld-bottom-save,.ld-phone-sheet,.ld-selection-popover",
              )
              .count(),
            0,
          );
          const targetUnit = page
            .locator("section.ld-unit:visible:has(.ld-unit-tools)")
            .first();
          const editable = targetUnit
            .locator("[data-editable]:visible")
            .first();
          if (await editable.count()) await editable.tap();
          else await targetUnit.tap({ position: { x: 4, y: 4 } });
          const unitTools = targetUnit.locator(":scope > .ld-unit-tools");
          assert.equal(await unitTools.isVisible(), true);
          const variantB = unitTools.locator('[data-select-variant="b"]');
          if (await variantB.count()) {
            await page.evaluate(
              () =>
                new Promise((resolve) =>
                  requestAnimationFrame(() => requestAnimationFrame(resolve)),
                ),
            );
            const geometry = await variantB.evaluate((node) => ({
              button: node.getBoundingClientRect().toJSON(),
              bar: document
                .querySelector(".ld-bar")
                .getBoundingClientRect()
                .toJSON(),
              scrollY,
              position: getComputedStyle(document.querySelector(".ld-bar"))
                .position,
            }));
            assert(
              geometry.button.y >= geometry.bar.bottom,
              `${asset} ${viewport.width} ${theme}: contextual controls obscured by toolbar ${JSON.stringify(geometry)}`,
            );
            await variantB.tap();
            const unitId = await targetUnit.getAttribute("data-unit");
            assert.equal(
              (await stateFrom(page)).units[unitId].selected,
              "b",
              `${asset} ${viewport.width} ${theme}: touch selects variant B`,
            );
          }
          await closeClean(session);
        }
      }
    }
  },
);

await run("authored diagram detail references resolve", async () => {
  let references = 0;
  for (const [asset, path] of Object.entries(ASSETS)) {
    const html = readFileSync(path, "utf8");
    const source = JSON.parse(
      html.match(
        /<script id="legaldesign-state" type="application\/json">(.*?)<\/script>/s,
      )[1],
    );
    const visit = (value, location) => {
      if (!value || typeof value !== "object") return;
      for (const [key, child] of Object.entries(value)) {
        if (/detail$/i.test(key) && typeof child === "string" && child) {
          references++;
          assert(
            Object.hasOwn(source.evidence || {}, child),
            `${asset} ${location}.${key} refers to missing evidence ${child}`,
          );
          assert(
            html.includes(`id="${child}"`),
            `${asset} ${location}.${key} has no authored popup ${child}`,
          );
        } else visit(child, `${location}.${key}`);
      }
    };
    for (const [id, unit] of Object.entries(source.units || {}))
      for (const [variant, value] of Object.entries(unit.variants || {}))
        visit(value.params, `${id}.${variant}`);
  }
  assert(references > 0, "Source popup-reference audit checked no references");
});

await run("card and figure evidence popups", async () => {
  const session = await pageFor({ viewport: { width: 1440, height: 900 } });
  const { page } = session;
  const clickAndClose = async (locator) => {
    await showUnit(
      page,
      await locator.evaluate(
        (node) => node.closest("[data-unit]").dataset.unit,
      ),
    );
    await locator.focus();
    const focused = await locator.evaluate(
      (node) => node === document.activeElement,
    );
    await page.keyboard.press("Enter");
    assert.equal(await page.locator("#popup-scrim").isVisible(), true);
    await page.keyboard.press("Escape");
    assert.equal(await page.locator("#popup-scrim").isHidden(), true);
    if (focused)
      assert.equal(
        await locator.evaluate((node) => {
          const active = document.activeElement;
          if (node === active) return true;
          const expected =
            node.getAttribute("data-evidence") ||
            node.getAttribute("data-detail");
          return (
            expected &&
            (active?.getAttribute("data-evidence") ||
              active?.getAttribute("data-detail")) === expected
          );
        }),
        true,
      );
  };
  for (const card of await page.locator(".ld-card[data-evidence]").all())
    await clickAndClose(card);
  await showUnit(page, "u-figure");
  for (const detail of await page
    .locator('[data-unit="u-figure"] [data-detail]:visible')
    .all())
    await clickAndClose(detail);
  await page.click("#mode-toggle");
  const figureUnit = page.locator('[data-unit="u-figure"]');
  await revealUnitTools(page, figureUnit);
  await figureUnit.locator('[data-select-variant="b"]').click();
  await page.click("#mode-toggle");
  for (const detail of await page
    .locator('[data-unit="u-figure"] [data-detail]:visible')
    .all())
    await clickAndClose(detail);
  await closeClean(session);
});

await run("keyboard reachability and popup focus return", async () => {
  for (const asset of [
    "stacked",
    "walkthrough",
    "report",
    "method",
    "library",
  ]) {
    const session = await pageFor({ asset, sourceRuntime: true });
    const { page } = session;
    for (const id of [
      "mode-toggle",
      "theme-toggle",
      "export-html",
      "export-template",
    ])
      await assertFocusRing(page.locator(`#${id}`));
    await page.focus("#theme-toggle");
    await page.keyboard.press("Enter");
    await waitForLegalDesignReady(page);
    assert.equal(await page.locator("html").getAttribute("data-theme"), "dark");
    await page.focus("#mode-toggle");
    await page.keyboard.press("Enter");
    assert.equal(await page.locator("html").getAttribute("data-mode"), "edit");

    if (asset !== "library") {
      const switchUnits = await page
        .locator("section.ld-unit:not([data-single]):has(.ld-ab)")
        .evaluateAll((nodes) => nodes.map((node) => node.dataset.unit));
      for (const unitId of switchUnits) {
        await showUnit(page, unitId);
        const unit = page.locator(`[data-unit="${unitId}"]`);
        await revealUnitTools(page, unit);
        const group = unit.locator(".ld-ab");
        await assertFocusRing(group);
        await page.keyboard.press("ArrowRight");
        assert.equal((await stateFrom(page)).units[unitId].selected, "b");
        await group.focus();
        await page.keyboard.press("ArrowLeft");
        assert.equal((await stateFrom(page)).units[unitId].selected, "a");
      }
    }
    await page.focus("#mode-toggle");
    await page.keyboard.press("Enter");
    assert.equal(await page.locator("html").getAttribute("data-mode"), null);

    const triggers = await page
      .locator("[data-detail],.ld-card[data-evidence]")
      .evaluateAll((nodes) =>
        nodes.map((node, index) => ({
          key: String(index),
          unit: node.closest("[data-unit]")?.dataset.unit || null,
          variant: node.closest("[data-variant]")?.dataset.variant || null,
          target:
            node.getAttribute("data-detail") ||
            node.getAttribute("data-evidence"),
          card: node.matches(".ld-card[data-evidence]"),
        })),
      );
    for (const trigger of triggers) {
      if (asset === "library" && trigger.key !== "0") {
        await page.reload({ waitUntil: "load" });
        await waitForLegalDesignReady(page);
      }
      if (trigger.unit) await showUnit(page, trigger.unit);
      if (trigger.unit && trigger.variant && asset !== "library") {
        await page.click("#mode-toggle");
        const unit = page.locator(`[data-unit="${trigger.unit}"]`);
        await revealUnitTools(page, unit);
        const button = unit.locator(
          `[data-select-variant="${trigger.variant}"]`,
        );
        if (await button.count()) await button.click();
        await page.click("#mode-toggle");
      }
      const locator = page
        .locator(
          asset === "library"
            ? "[data-detail]"
            : trigger.card
              ? `.ld-card[data-evidence="${trigger.target}"]:visible`
              : `[data-detail="${trigger.target}"]:visible`,
        )
        .nth(asset === "library" ? Number(trigger.key) : 0);
      if (!(await locator.isVisible())) continue;
      await focusByKeyboard(page, locator, `${asset} detail ${trigger.key}`);
      await assertFocusRing(locator, `${asset} detail ${trigger.key}`);
      await locator.press("Enter");
      const scrim = page.locator("#popup-scrim");
      assert.equal(
        await scrim.isVisible(),
        true,
        `${asset}: detail ${trigger.key} (${trigger.target}) did not open`,
      );
      const close = scrim.locator(".ld-popup-close:visible").first();
      await assertFocusRing(close);
      await close.press("Enter");
      assert.equal(await scrim.isHidden(), true);
      await assertFocusReturned(
        page,
        trigger.target,
        `${asset} detail ${trigger.key} (${trigger.target}) after close`,
      );
      await locator.press("Enter");
      assert.equal(
        await scrim.isVisible(),
        true,
        `${asset}: detail ${trigger.key} (${trigger.target}) did not reopen`,
      );
      await page.keyboard.press("Escape");
      assert.equal(await scrim.isHidden(), true);
      await assertFocusReturned(
        page,
        trigger.target,
        `${asset} detail ${trigger.key} (${trigger.target}) after Escape`,
      );
    }
    await closeClean(session);
  }
});

await run("shared runtime controls on every asset at phone width", async () => {
  const expectedLabels = ["Edit", "Theme", "Export HTML", "Export template"];
  for (const asset of [
    "stacked",
    "walkthrough",
    "report",
    "method",
    "library",
  ]) {
    const session = await pageFor({
      asset,
      viewport: { width: 430, height: 932 },
    });
    const { page } = session;
    assert.deepEqual(
      await page
        .locator(".ld-controls > button:visible")
        .evaluateAll((buttons) => buttons.map((button) => button.id)),
      ["mode-toggle", "theme-toggle", "export-html", "export-template"],
      asset,
    );
    const controls = await page
      .locator(".ld-controls > button:visible")
      .evaluateAll((buttons) =>
        buttons.map((button) => ({
          label: button.getAttribute("aria-label") || button.textContent.trim(),
          fontSize: Number.parseFloat(getComputedStyle(button).fontSize),
          height: button.getBoundingClientRect().height,
          left: button.getBoundingClientRect().left,
          right: button.getBoundingClientRect().right,
        })),
      );
    assert.deepEqual(
      controls.map((control) => control.label),
      expectedLabels,
      `${asset}: phone control labels`,
    );
    for (const control of controls) {
      assert(
        control.fontSize >= 11,
        `${asset}: ${control.label} is below 11px`,
      );
      assert(control.height >= 44, `${asset}: ${control.label} is below 44px`);
      assert(
        control.left >= 0 && control.right <= 430,
        `${asset}: ${control.label} is outside the phone viewport`,
      );
    }
    if ((await page.locator("html").getAttribute("data-theme")) === "dark")
      await page.click("#theme-toggle");
    assert.equal(
      await page.locator("html").getAttribute("data-theme"),
      "light",
    );
    await page.click("#theme-toggle");
    assert.equal(await page.locator("html").getAttribute("data-theme"), "dark");
    assert.deepEqual(
      await page.evaluate(() => [
        getComputedStyle(document.documentElement).backgroundColor,
        getComputedStyle(document.body).backgroundColor,
      ]),
      ["rgb(0, 0, 0)", "rgb(0, 0, 0)"],
      asset,
    );
    await page.click("#mode-toggle");
    assert.equal(await page.locator("html").getAttribute("data-mode"), "edit");
    await closeClean(session);
  }
});

await run("report rail, query navigation, and register links", async () => {
  const querySession = await pageFor({
    asset: "report",
    url: `${pathToFileURL(ASSETS.report).href}?frame=3`,
  });
  assert.equal(
    await querySession.page.locator(".sb-slide.on").getAttribute("id"),
    "p3",
  );
  assert.equal(
    await querySession.page
      .locator('.rail-i[aria-current="true"]')
      .getAttribute("data-page"),
    "p3",
  );
  await querySession.page.locator('[data-frame-button="4"]').click();
  assert.equal(
    await querySession.page.locator(".sb-slide.on").getAttribute("id"),
    "p4",
  );
  await querySession.page.click("#nav-prev");
  assert.equal(
    await querySession.page.locator(".sb-slide.on").getAttribute("id"),
    "p3",
  );
  await querySession.page.keyboard.press("ArrowRight");
  assert.equal(
    await querySession.page.locator(".sb-slide.on").getAttribute("id"),
    "p4",
  );
  await closeClean(querySession);

  const linkSession = await pageFor({ asset: "report" });
  const { page } = linkSession;
  const inertRows = await page
    .locator(
      '.rrow .register-action:not([data-page]),.rrow[role="button"]:not(:has([data-page])),.rrow[tabindex="0"]:not(:has([data-page]))',
    )
    .count();
  assert.equal(inertRows, 0);
  for (const frame of [2, 5]) {
    await page.evaluate((next) => window.reportGoTo(next), frame);
    const links = await page
      .locator(".sb-slide.on .rrow[data-open] .register-action")
      .all();
    for (const link of links) {
      const target = await link.getAttribute("data-page");
      await link.click();
      assert.equal(
        await page.locator(".sb-slide.on").getAttribute("id"),
        target,
      );
      await page.evaluate((next) => window.reportGoTo(next), frame);
    }
  }
  await closeClean(linkSession);
});

await run("report location survives Save and reopen", async () => {
  const session = await pageFor({ asset: "report" });
  const { page } = session;
  await page.evaluate(() => window.reportGoTo(3));
  assert.equal((await stateFrom(page)).review.location, "p3");
  await page.click("#mode-toggle");
  const savedPath = await downloadFrom(
    page,
    "#ld-save",
    "report-saved-reopen.html",
  );
  await closeClean(session);

  const reopened = await pageFor({
    clearStorage: false,
    url: pathToFileURL(savedPath).href,
  });
  assert.equal((await stateFrom(reopened.page)).review.location, "p3");
  assert.equal(
    await reopened.page.locator(".sb-slide.on").getAttribute("id"),
    "p3",
  );
  await closeClean(reopened);
});

await run("report figure details open authored evidence", async () => {
  const session = await pageFor({
    asset: "report",
    viewport: { width: 1440, height: 900 },
  });
  const { page } = session;
  for (const frame of [3, 4, 6]) {
    await page.evaluate((next) => window.reportGoTo(next), frame);
    const details = await page
      .locator(".sb-slide.on .ld-diagram [data-detail]:visible")
      .all();
    assert(
      details.length > 0,
      `page ${frame} has no interactive figure detail`,
    );
    for (const detail of details) {
      const target = await detail.getAttribute("data-detail");
      await detail.click();
      assert.equal(await page.locator(`#${target}`).isVisible(), true, target);
      await page.keyboard.press("Escape");
    }
  }
  await closeClean(session);
});

await run("report template dashboard placeholders and leak scan", async () => {
  const session = await pageFor({ asset: "report" });
  const { page } = session;
  const sourceCounts = {
    cards: await page.locator("#p1 .issue-card").count(),
    register: await page.locator("#p1 .area-row").count(),
  };
  await page.locator("#rail-handle").click();
  assert.equal(
    await page.locator("#rail-handle").getAttribute("aria-label"),
    "Expand contents",
  );
  const templatePath = await downloadFrom(
    page,
    "#export-template",
    "report-template-export.html",
  );
  await closeClean(session);
  const exportedReportMarkup = withoutRuntime(
    readFileSync(templatePath, "utf8"),
  );
  assert.match(
    exportedReportMarkup,
    /id="rail-handle"[^>]*aria-label="Expand contents"/,
  );

  const template = await pageFor({ url: pathToFileURL(templatePath).href });
  const templateCards =
    '#p1 .ld-unit[data-kind="card"] .ld-variant:not([hidden]) article';
  const templateRegister =
    '#p1 .ld-unit[data-kind="table"]:has(small) .ld-variant:not([hidden]) [data-variant-body] > div > :is(a, div)';
  assert.equal(
    await template.page.locator(templateCards).count(),
    sourceCounts.cards,
  );
  assert.equal(
    await template.page.locator(templateRegister).count(),
    sourceCounts.register,
  );
  assert.equal(
    await template.page.locator("#rail").getAttribute("aria-label"),
    "Contents",
  );
  assert.equal(
    await template.page.locator("#rail-handle").getAttribute("aria-label"),
    "Collapse contents",
  );
  assert.equal(
    await template.page.locator("#nav-prev").getAttribute("aria-label"),
    "Previous page",
  );
  assert.equal(
    await template.page.locator("#nav-next").getAttribute("aria-label"),
    "Next page",
  );
  for (const selector of [templateCards, templateRegister]) {
    const values = await template.page
      .locator(`${selector} [data-editable]`)
      .evaluateAll((nodes) => nodes.map((node) => node.textContent.trim()));
    assert(
      values.length > 0 && values.every((value) => value.startsWith("[")),
      selector,
    );
  }
  const templateHTML = await template.page.content();
  for (const placeholder of [
    "[Document name.]",
    "[Column heading.]",
    "[STATUS]",
    "[Value from the data room.]",
    "[What was found, with the date.]",
  ])
    assert.match(
      templateHTML,
      new RegExp(placeholder.replace(/[[\].]/g, "\\$&")),
    );
  await template.page.evaluate(() => window.reportGoTo(1));
  const issueLink = template.page
    .locator(
      '#p1 .ld-unit[data-kind="card"] .ld-variant[data-variant="b"] a[data-page]',
    )
    .first();
  assert((await issueLink.evaluate((node) => node.children.length)) > 1);
  assert.doesNotMatch(await issueLink.textContent(), /^\s*\[Link\.\]\s*$/);
  const issueTarget = await issueLink.getAttribute("data-page");
  await issueLink.evaluate((node) => node.click());
  assert.equal(
    await template.page.locator(`#${issueTarget}`).isVisible(),
    true,
  );
  await template.page.locator(".ld-reference-evidence:visible").click();
  const evidenceLink = template.page
    .locator("a[data-evidence]:visible")
    .first();
  assert.match(
    await evidenceLink.textContent(),
    /Open the clause in the source document/,
  );
  const evidenceTarget = await evidenceLink.getAttribute("data-evidence");
  await evidenceLink.click();
  assert.equal(
    await template.page.locator(`#${evidenceTarget}`).isVisible(),
    true,
  );
  await template.page.keyboard.press("Escape");
  for (const term of MATTER_TERMS["diligence-report.html"])
    assert(!templateHTML.toLowerCase().includes(term.toLowerCase()), term);
  assert.doesNotMatch(
    templateHTML,
    /data:image|General Legal|Brex|Wells Fargo|Carta/i,
  );
  await closeClean(template);
});

await run("report phone rail and footer clearance", async () => {
  const session = await pageFor({
    asset: "report",
    viewport: { width: 430, height: 932 },
  });
  const { page } = session;
  assert.equal(await page.locator("body").getAttribute("data-rail"), "closed");
  assert.equal(await page.locator("#rail-toggle").isVisible(), true);
  assert.equal(await page.locator(".rail").isHidden(), true);
  assert.equal(await page.locator(".rail-g").first().isHidden(), true);
  assert.equal(
    await page
      .locator(".stage")
      .evaluate((node) =>
        Number.parseFloat(getComputedStyle(node).paddingLeft),
      ),
    10,
  );
  assert.equal(
    await page.evaluate(() => document.documentElement.scrollWidth),
    430,
  );
  await page.locator("#rail-toggle").click();
  assert.equal(await page.locator("body").getAttribute("data-rail"), "open");
  assert.equal(await page.locator(".rail").isVisible(), true);
  assert.equal(await page.locator(".rail-g").first().isVisible(), true);
  const railBox = await page.locator(".rail").boundingBox();
  assert(
    railBox && railBox.x >= 0 && railBox.x + railBox.width <= 430,
    "report contents disclosure extends outside the phone viewport",
  );
  await page.locator("#rail-toggle").click();
  assert.equal(await page.locator(".rail").isHidden(), true);
  for (const frame of [1, 2, 3, 4, 5, 6]) {
    await page.evaluate((next) => window.reportGoTo(next), frame);
    const overlap = await page.evaluate(() => {
      const slide = document.querySelector(".sb-slide.on");
      const foot = slide.querySelector(".foot").getBoundingClientRect();
      const contentBottom = [...slide.children]
        .filter((node) => !node.classList.contains("foot"))
        .reduce(
          (bottom, node) =>
            Math.max(bottom, node.getBoundingClientRect().bottom),
          -Infinity,
        );
      return {
        overlaps: contentBottom > foot.top,
        contentBottom,
        footerTop: foot.top,
        children: [...slide.children]
          .filter((node) => !node.classList.contains("foot"))
          .map((node) => ({
            className: node.className,
            bottom: node.getBoundingClientRect().bottom,
          })),
      };
    });
    assert.equal(
      overlap.overlaps,
      false,
      `page ${frame} content overlaps its foot: ${JSON.stringify(overlap)}`,
    );
  }
  await closeClean(session);
});

await run("report screenshot matrix", async () => {
  const shots = [];
  for (const viewport of [
    { width: 1440, height: 900 },
    { width: 1280, height: 800 },
    { width: 430, height: 932 },
  ]) {
    for (const theme of ["light", "dark"]) {
      const session = await pageFor({ asset: "report", viewport });
      if (theme === "dark") await session.page.click("#theme-toggle");
      for (const frame of [1, 2, 3, 4, 5, 6]) {
        await session.page.evaluate((next) => window.reportGoTo(next), frame);
        const minText = await session.page.evaluate(() => {
          const walker = document.createTreeWalker(
            document.body,
            NodeFilter.SHOW_TEXT,
          );
          let minimum = Number.POSITIVE_INFINITY;
          while (walker.nextNode()) {
            if (!walker.currentNode.textContent.trim()) continue;
            const parent = walker.currentNode.parentElement;
            if (!parent || !parent.getClientRects().length) continue;
            if (parent.closest("[hidden],script,style,template")) continue;
            let size = Number.parseFloat(getComputedStyle(parent).fontSize);
            if (parent instanceof SVGTextElement) {
              const matrix = parent.getScreenCTM();
              if (matrix) size *= Math.hypot(matrix.b, matrix.d);
            }
            minimum = Math.min(minimum, size);
          }
          return minimum;
        });
        assert(
          minText >= 10.99,
          `report page ${frame} at ${viewport.width}px ${theme}: ${minText.toFixed(2)}px text`,
        );
        const name = `report-p${frame}-${viewport.width}x${viewport.height}-${theme}.png`;
        await session.page.screenshot({
          path: join(OUT, name),
          fullPage: true,
        });
        shots.push(name);
      }
      await closeClean(session);
    }
  }
  const popupSession = await pageFor({
    asset: "report",
    viewport: { width: 1280, height: 800 },
  });
  const popupIds = await popupSession.page
    .locator("#popup-scrim > .pop")
    .evaluateAll((nodes) => nodes.map((node) => node.id));
  const openPopup = async (id, ancestors = []) => {
    assert(
      !ancestors.includes(id),
      `Circular popup route: ${[...ancestors, id].join(" → ")}`,
    );
    const sourceLink = popupSession.page
      .locator(`.pop [data-evidence="${id}"]`)
      .first();
    const trigger = (await sourceLink.count())
      ? sourceLink
      : popupSession.page
          .locator(`[data-evidence="${id}"],[data-detail="${id}"]`)
          .first();
    const route = await trigger.evaluate((node) => ({
      frame: node.closest("[data-frame]")?.dataset.frame,
      parentPopup: node.closest(".pop")?.id,
    }));
    if (route.parentPopup)
      await openPopup(route.parentPopup, [...ancestors, id]);
    else {
      assert(route.frame, `No page or parent popup reaches ${id}`);
      await popupSession.page.evaluate(
        (next) => window.reportGoTo(Number(next)),
        route.frame,
      );
    }
    await trigger.click();
    assert.equal(await popupSession.page.locator(`#${id}`).isVisible(), true);
  };
  for (const id of popupIds) {
    await openPopup(id);
    assert.equal(await popupSession.page.locator(`#${id}`).isVisible(), true);
    const name = `report-popup-${id}.png`;
    await popupSession.page.screenshot({
      path: join(OUT, name),
      fullPage: true,
    });
    shots.push(name);
    await popupSession.page.keyboard.press("Escape");
    // A nested source now returns to its parent detail instead of discarding
    // the reader's place. Exit that deliberate trail before the next route.
    for (let depth = 0; depth < popupIds.length; depth++) {
      if (!(await popupSession.page.locator("#popup-scrim").isVisible())) break;
      await popupSession.page.keyboard.press("Escape");
    }
    assert(!(await popupSession.page.locator("#popup-scrim").isVisible()));
  }
  await popupSession.page.evaluate(() => window.reportGoTo(1));
  const clientPath = await downloadFrom(
    popupSession.page,
    "#export-html",
    "report-screenshot-client.html",
  );
  const templatePath = await downloadFrom(
    popupSession.page,
    "#export-template",
    "report-screenshot-template.html",
  );
  await closeClean(popupSession);
  for (const [kind, path] of [
    ["client", clientPath],
    ["template", templatePath],
  ]) {
    const exported = await pageFor({ url: pathToFileURL(path).href });
    const name = `report-export-${kind}.png`;
    await exported.page.screenshot({ path: join(OUT, name), fullPage: true });
    shots.push(name);
    await closeClean(exported);
  }
  assert.equal(shots.length, 36 + popupIds.length + 2);
  for (const shot of shots) assert(existsSync(join(OUT, shot)), shot);
  console.log(`Report screenshots (${shots.length}): ${shots.join(", ")}`);
});

await run("screenshot matrix", async () => {
  const shots = [];
  for (const viewport of [
    { width: 1440, height: 900 },
    { width: 1280, height: 800 },
    { width: 430, height: 932 },
  ]) {
    for (const theme of ["light", "dark"]) {
      const session = await pageFor({ viewport });
      if (theme === "dark") await session.page.click("#theme-toggle");
      const name = `stacked-${viewport.width}x${viewport.height}-${theme}.png`;
      await session.page.screenshot({ path: join(OUT, name), fullPage: true });
      shots.push(name);
      await closeClean(session);
    }
  }
  const popupSession = await pageFor({
    viewport: { width: 1280, height: 800 },
  });
  for (const id of await popupSession.page
    .locator("#popup-scrim > .pop")
    .evaluateAll((nodes) => nodes.map((node) => node.id))) {
    const trigger = popupSession.page
      .locator(`[data-evidence="${id}"],[data-detail="${id}"]`)
      .first();
    await showUnit(
      popupSession.page,
      await trigger.evaluate(
        (node) => node.closest("[data-unit]").dataset.unit,
      ),
    );
    await trigger.click();
    const name = `stacked-popup-${id}.png`;
    await popupSession.page.screenshot({
      path: join(OUT, name),
      fullPage: true,
    });
    shots.push(name);
    await popupSession.page.keyboard.press("Escape");
  }
  const clientPath = await downloadFrom(
    popupSession.page,
    "#export-html",
    "screenshot-client.html",
  );
  const templatePath = await downloadFrom(
    popupSession.page,
    "#export-template",
    "screenshot-template.html",
  );
  await closeClean(popupSession);
  for (const [kind, path] of [
    ["client", clientPath],
    ["template", templatePath],
  ]) {
    const exported = await pageFor({ url: pathToFileURL(path).href });
    const name = `stacked-export-${kind}.png`;
    await exported.page.screenshot({ path: join(OUT, name), fullPage: true });
    shots.push(name);
    await closeClean(exported);
  }
  assert.equal(shots.length, 17);
  for (const shot of shots) assert(existsSync(join(OUT, shot)), shot);
  console.log(`Screenshots (${shots.length}): ${shots.join(", ")}`);
});

await run(
  "figure text size, view-mode geometry, evidence entries",
  async () => {
    for (const viewport of [
      { width: 1440, height: 900 },
      { width: 1280, height: 800 },
      { width: 430, height: 932 },
    ]) {
      for (const colorScheme of ["light", "dark"]) {
        const session = await pageFor({ viewport, colorScheme });
        await session.page.waitForTimeout(150);
        const measured = await session.page.evaluate(() => {
          const out = {
            minText: 999,
            minTextDetail: null,
            overlaps: 0,
            cardGap: 0,
            evidence: [],
          };
          for (const svg of document.querySelectorAll(
            ".ld-variant:not([hidden]) svg",
          )) {
            const frame = svg.closest(".ld-fixed-page");
            const pageScale = frame
              ? frame.getBoundingClientRect().width / frame.offsetWidth
              : 1;
            const rects = [...svg.querySelectorAll("rect")].map((r) =>
              r.getBoundingClientRect(),
            );
            for (const t of svg.querySelectorAll("text")) {
              const r = t.getBoundingClientRect();
              const bb = t.getBBox();
              const size =
                (parseFloat(getComputedStyle(t).fontSize) *
                  (r.height / (bb.height || 1))) /
                pageScale;
              if (r.width > 0 && size < out.minText) {
                out.minText = size;
                out.minTextDetail = {
                  text: t.textContent.trim(),
                  className: t.getAttribute("class") || "",
                  nominal: parseFloat(getComputedStyle(t).fontSize),
                };
              }
              for (const rr of rects) {
                const crossesEdge =
                  r.top < rr.bottom &&
                  r.bottom > rr.bottom &&
                  r.left < rr.right &&
                  r.right > rr.left &&
                  r.top > rr.top;
                if (crossesEdge) out.overlaps += 1;
              }
            }
          }
          const card = document.querySelector("[data-unit=u-card-cover]");
          out.cardGap =
            card.querySelector("h3").getBoundingClientRect().top -
            card.getBoundingClientRect().top;
          const state = window.LegalDesign.state();
          for (const [id, entry] of Object.entries(state.evidence)) {
            const pop = document.getElementById(id);
            const clean = (node) =>
              node ? node.textContent.replace(/\s+/g, " ").trim() : "";
            out.evidence.push({
              id,
              cite: entry.cite === clean(pop.querySelector(".tag")),
              excerpt: entry.excerpt === clean(pop.querySelector(".doc-text")),
              link: entry.link === pop.querySelector(".out a")?.href,
            });
          }
          return out;
        });
        await showUnit(session.page, "u-card-cover");
        measured.cardGap = await session.page
          .locator("[data-unit=u-card-cover]")
          .evaluate((card) => {
            const frame = card.closest(".ld-fixed-page");
            const scale =
              frame.getBoundingClientRect().width / frame.offsetWidth;
            return (
              (card.querySelector("h3").getBoundingClientRect().top -
                card.getBoundingClientRect().top) /
              scale
            );
          });
        assert(
          measured.minText >= 11,
          `${viewport.width} ${colorScheme}: figure text ${measured.minText.toFixed(1)}px ${JSON.stringify(measured.minTextDetail)}`,
        );
        assert.equal(
          measured.overlaps,
          0,
          `${viewport.width} ${colorScheme}: text crossing a box edge`,
        );
        assert(
          measured.cardGap <= 24,
          `${viewport.width} ${colorScheme}: card title ${measured.cardGap}px below the card top`,
        );
        for (const e of measured.evidence)
          assert(
            e.cite && e.excerpt && e.link,
            `evidence ${e.id} differs from its popup`,
          );
        console.log(
          `  ${viewport.width} ${colorScheme}: min text ${measured.minText.toFixed(1)}px, card gap ${Math.round(measured.cardGap)}px, ${measured.evidence.length} evidence entries match`,
        );
        await closeClean(session);
      }
    }
  },
);

await run("shared runtime parity by asset", async () => {
  for (const asset of ["stacked", "walkthrough", "method"]) {
    const session = await pageFor({ asset });
    const { page } = session;
    assert.deepEqual(
      await page
        .locator(".ld-controls > button:visible")
        .evaluateAll((nodes) => nodes.map((node) => node.id)),
      ["mode-toggle", "theme-toggle", "export-html", "export-template"],
      asset,
    );
    await page.click("#theme-toggle");
    assert.equal(await page.locator("html").getAttribute("data-theme"), "dark");
    await page.click("#mode-toggle");
    const unit = page.locator("section.ld-unit:not([data-single])").first();
    await revealUnitTools(page, unit);
    await unit.locator('[data-select-variant="b"]').click();
    assert.equal(
      (await stateFrom(page)).units[await unit.getAttribute("data-unit")]
        .selected,
      "b",
    );
    assert.equal(
      await page.locator("#popup-scrim > .pop").count(),
      await page.locator(".pop").count(),
    );
    await closeClean(session);
  }
});

await run("method map evidence and recorded intake", async () => {
  const session = await pageFor({
    asset: "method",
    viewport: { width: 1440, height: 900 },
  });
  const { page } = session;
  const state = await stateFrom(page);
  assert.deepEqual(state.brief.run.questions_asked, []);
  assert.match(state.brief.run.note, /not a record of user answers/);
  for (const trigger of await page.locator(".ld-card[data-evidence]").all()) {
    const target = await trigger.getAttribute("data-evidence");
    await showUnit(page, await trigger.getAttribute("data-unit"));
    await trigger.click();
    assert.equal(await page.locator(`#${target}`).isVisible(), true, target);
    await page.keyboard.press("Escape");
  }
  await showUnit(page, "u-figure");
  const details = await page
    .locator('[data-unit="u-figure"] [data-detail]:visible')
    .all();
  assert.deepEqual(
    await Promise.all(
      details.map((trigger) => trigger.getAttribute("data-detail")),
    ),
    ["src-relationship", "src-form", "src-brief"],
  );
  for (const trigger of details) {
    const target = await trigger.getAttribute("data-detail");
    await trigger.click();
    assert.equal(await page.locator(`#${target}`).isVisible(), true, target);
    await page.keyboard.press("Escape");
  }
  await closeClean(session);
});

await run("method map and shipped template screenshot matrix", async () => {
  const shots = [];
  for (const viewport of [
    { width: 1440, height: 900 },
    { width: 1280, height: 800 },
    { width: 430, height: 932 },
  ]) {
    for (const theme of ["light", "dark"]) {
      const session = await pageFor({ asset: "method", viewport });
      if (theme === "dark") await session.page.click("#theme-toggle");
      const name = `method-map-${viewport.width}x${viewport.height}-${theme}.png`;
      await session.page.screenshot({ path: join(OUT, name), fullPage: true });
      shots.push(name);
      await closeClean(session);
    }
  }
  const popupSession = await pageFor({
    asset: "method",
    viewport: { width: 1280, height: 800 },
  });
  for (const id of await popupSession.page
    .locator("#popup-scrim > .pop")
    .evaluateAll((nodes) => nodes.map((node) => node.id))) {
    await popupSession.page.evaluate(
      (popupId) => window.LegalDesign.openPopup(popupId),
      id,
    );
    const shot = `method-map-popup-${id}.png`;
    await popupSession.page.screenshot({
      path: join(OUT, shot),
      fullPage: true,
    });
    shots.push(shot);
    await popupSession.page.keyboard.press("Escape");
  }
  const methodClient = await downloadFrom(
    popupSession.page,
    "#export-html",
    "method-screenshot-client.html",
  );
  const methodTemplate = await downloadFrom(
    popupSession.page,
    "#export-template",
    "method-screenshot-template.html",
  );
  await closeClean(popupSession);
  for (const [kind, path] of [
    ["client", methodClient],
    ["template", methodTemplate],
  ]) {
    const exported = await pageFor({ url: pathToFileURL(path).href });
    const shot = `method-map-export-${kind}.png`;
    await exported.page.screenshot({ path: join(OUT, shot), fullPage: true });
    shots.push(shot);
    await closeClean(exported);
  }
  for (const [name, path] of Object.entries(TEMPLATE_ASSETS)) {
    for (const theme of ["light", "dark"]) {
      const session = await pageFor({
        url: pathToFileURL(path).href,
        viewport: { width: 1280, height: 800 },
      });
      assert.equal(
        await session.page.locator("html").getAttribute("data-exported"),
        "template",
      );
      if (theme === "dark") await session.page.click("#theme-toggle");
      await session.page.click("#mode-toggle");
      const current = await stateFrom(session.page);
      assert.equal(current.sourceSchemaVersion, "legaldesign.build.v4");
      assert.equal("approaches" in current, false);
      assert(current.composition.sections.length);
      assert.equal(
        current.overview.sectionId,
        current.composition.sections[0].id,
      );
      assert.equal(
        await session.page
          .locator(
            '#ld-page-approach,[data-approach="b"],[data-select-approach]',
          )
          .count(),
        0,
      );
      assert.equal(await session.page.locator(".ld-ab").count(), 0);
      await session.page.click("#mode-toggle");
      assert.equal(
        await session.page.evaluate(
          () => window.LegalDesign.checkPageFit().valid,
        ),
        true,
        `${name} current single-output template must fit after opening and closing Edit`,
      );
      const shot = `template-${name}-1280x800-${theme}.png`;
      await session.page.screenshot({ path: join(OUT, shot), fullPage: true });
      shots.push(shot);
      await closeClean(session);
    }
  }
  assert.equal(shots.length, 22);
  for (const shot of shots) assert(existsSync(join(OUT, shot)), shot);
  console.log(
    `Method/template screenshots (${shots.length}): ${shots.join(", ")}`,
  );
});

await run(
  "legacy stacked template imports without placeholder leaks",
  async () => {
    const original = await pageFor({ asset: "stacked" });
    const legacyTemplate = await downloadFrom(
      original.page,
      "#export-template",
      "legacy-stacked-import.template.html",
    );
    await closeClean(original);
    const session = await pageFor({
      url: pathToFileURL(legacyTemplate).href,
    });
    const clientHTML = await session.page.evaluate((fixture) => {
      const state = window.LegalDesign.state();
      state.artifactId = "fictional-fee-options";
      state.brief = fixture.brief;
      const ids = Object.keys(state.units);
      const fills = Object.values(fixture.units);
      if (ids.length !== fills.length)
        throw new Error("template import unit topology changed");
      for (const [index, fill] of fills.entries()) {
        const id = ids[index];
        const unit = state.units[id];
        unit.claim = fill.claim;
        unit.relationship = fill.relationship;
        for (const key of Object.keys(fill.variants)) {
          if (unit.kind === "figure") {
            unit.variants[key].component = fill.variants[key].component;
            unit.variants[key].params = fill.variants[key].params;
          } else {
            unit.edits[key] = fill.variants[key];
          }
        }
      }
      for (const id of Object.keys(state.evidence)) {
        state.evidence[id] = {
          ...fixture.evidence,
          link: null,
          image: { status: "frame" },
        };
      }
      window.LegalDesign.setState(state);
      const figure = document.querySelector(
        'section.ld-unit[data-kind="figure"]',
      );
      figure.querySelector("h2").textContent =
        "Three fee options trade predictability against flexibility.";
      figure.querySelector(".ld-source-note").textContent =
        "Fictional fee-options memo.";
      const matter = document.querySelector(".ld-matter");
      matter.textContent = fixture.matter;
      document.querySelector(".ld-kicker")?.remove();
      const foot = document.querySelectorAll(".ld-foot p");
      foot.forEach((node, index) => {
        node.textContent = fixture.foot[index];
      });
      document.querySelectorAll("#popup-scrim .pop").forEach((pop) => {
        pop.querySelector(".tag").textContent = fixture.evidence.cite;
        pop.querySelector("h2").textContent = "The three fee options";
        pop.querySelector(".desc").textContent =
          "The supplied memo states each price and the scope condition.";
        pop.querySelectorAll(".doc-text").forEach((node) => {
          node.textContent = fixture.evidence.excerpt;
        });
        pop.querySelectorAll(".doc-cl,.doc-foot").forEach((node) => {
          node.textContent = fixture.evidence.locator;
        });
        pop.querySelectorAll(".out").forEach((node) => {
          node.textContent = "The supplied fee-options memo";
        });
        pop.querySelectorAll("svg text").forEach((node) => {
          node.textContent = "The supplied fee-options memo";
        });
        pop.querySelectorAll("svg[aria-label],img[alt]").forEach((node) => {
          if (node.hasAttribute("aria-label"))
            node.setAttribute("aria-label", "The supplied fee-options memo");
          if (node.hasAttribute("alt"))
            node.setAttribute("alt", "The supplied fee-options memo");
        });
      });
      return window.LegalDesign.exportHTML(false);
    }, TEMPLATE_IMPORT);
    const path = join(EXPORTS_OUT, "template-import-client.html");
    writeFileSync(path, clientHTML);
    await closeClean(session);

    const client = await pageFor({ url: pathToFileURL(path).href });
    assert.doesNotMatch(
      await client.page.locator("body").innerText(),
      /\[[^\]]+\]/,
    );
    const portableState = await client.page.evaluate(() => {
      const state = window.LegalDesign.state();
      const strings = [];
      const visit = (value) => {
        if (typeof value === "string") strings.push(value);
        else if (Array.isArray(value)) value.forEach(visit);
        else if (value && typeof value === "object")
          Object.values(value).forEach(visit);
      };
      Object.values(state.units).forEach((unit) => {
        visit(unit.edits);
        Object.values(unit.variants || {}).forEach((variant) => {
          visit(variant.html);
        });
      });
      return {
        brief: state.brief,
        placeholderLeaks: strings.flatMap((value) =>
          Array.from(
            value.matchAll(/\[(?:[A-Z0-9§][^[\]\r\n]{2,199})\]/g),
            (match) => match[0],
          ),
        ),
      };
    });
    assert.deepEqual(portableState.placeholderLeaks, []);
    assert.equal(
      portableState.brief.reader,
      "[Reader described by the visible artifact.]",
    );
    assert.equal(
      portableState.brief.action,
      "[Action described by the visible artifact.]",
    );
    assert.equal(
      portableState.brief.message,
      "[Message stated in the visible artifact.]",
    );
    await closeClean(client);
  },
);

await run(
  "shipped v4 stacked template imports without placeholder leaks",
  async () => {
    const session = await pageFor({
      url: pathToFileURL(TEMPLATE_ASSETS.stacked).href,
    });
    const imported = await session.page.evaluate((fixture) => {
      const state = window.LegalDesign.state();
      if (
        state.sourceSchemaVersion !== "legaldesign.build.v4" ||
        state.approaches
      )
        throw new Error("shipped template must be a single v4 composition");
      state.artifactId = "fictional-v4-fee-options";
      state.brief = fixture.brief;
      const overview = state.overview;
      const facts = new Set(overview.contextUnitIds);
      const firstEvidence = Object.keys(state.evidence)[0];
      const remapDetails = (value) => {
        if (Array.isArray(value)) return value.map(remapDetails);
        if (value && typeof value === "object")
          return Object.fromEntries(
            Object.entries(value).map(([key, item]) => [
              key,
              key === "detail" ? firstEvidence : remapDetails(item),
            ]),
          );
        return value;
      };
      for (const section of state.composition.sections) {
        section.purpose =
          "Compare fees before choosing an engagement structure.";
        for (const id of section.unitIds) {
          const unit = state.units[id];
          if (Object.keys(unit.variants).join() !== "a")
            throw new Error("current units must contain one rendering");
          let html;
          if (unit.kind === "figure") {
            const figure = fixture.units["u-figure"];
            // The supplied choice hierarchy fits a single overview page with
            // actual context and a question; the taller Zones rendering does not.
            unit.claim = "Choose one of three fee options before signing.";
            unit.relationship = "hierarchy";
            unit.variants.a.component = figure.variants.b.component;
            unit.variants.a.params = remapDetails(figure.variants.b.params);
            continue;
          }
          if (unit.role === "title") {
            unit.claim = fixture.units["u-title"].claim;
            html = "<h1>Choose a fee structure</h1>";
          } else if (facts.has(id)) {
            unit.claim = "Three fee options cover a six-week contract review.";
            html =
              "<h2>Relevant facts</h2><p>The six-week contract review offers three fee structures.</p>";
          } else if (id === overview.questionUnitId) {
            unit.claim =
              "The reader must choose among the supplied fee arrangements.";
            html =
              "<h2>Question</h2><p>Which fee structure best balances predictability and flexibility?</p>";
          } else if (id === overview.answerUnitId) {
            unit.claim = fixture.units["u-answer"].claim;
            html =
              "<h2>Answer</h2><p>Fixed fees prioritize predictability; hourly prioritizes flexibility. Capped hourly preserves flexibility with a $15,000 ceiling.</p>";
          } else throw new Error(`Unmapped current template unit ${id}`);
          unit.variants.a.html = html;
          unit.edits = { a: html };
        }
      }
      for (const id of Object.keys(state.evidence)) {
        state.evidence[id] = {
          ...fixture.evidence,
          link: null,
          image: { status: "frame" },
          popup: {
            type: "explainer",
            title: "The three fee options",
            lede: "The supplied memo states each price and scope condition.",
            sections: [
              { heading: "Prices", body: fixture.evidence.excerpt },
              {
                heading: "Scope",
                body: "The fixed fee covers only the stated six-week review.",
              },
            ],
          },
        };
      }
      // This fixture explicitly replaces the template's entire illustration,
      // rather than editing labels in its saved geometry. Release only that
      // diagram's preservation flag so setState renders the newly chosen form.
      document
        .querySelectorAll('section.ld-unit[data-kind="figure"] .ld-diagram')
        .forEach((host) => {
          host.removeAttribute("data-editor-preserve-dom");
        });
      window.LegalDesign.setState(state);
      document.querySelector(".ld-matter").textContent = fixture.matter;
      document.querySelectorAll("section.ld-unit").forEach((unit) => {
        unit.setAttribute("aria-label", state.units[unit.dataset.unit].claim);
        if (unit.dataset.kind === "figure" && unit.querySelector("h2"))
          unit.querySelector("h2").textContent =
            "Predictability and flexibility";
      });
      document
        .querySelectorAll(".ld-detail-linkline .ld-inline-detail")
        .forEach((node) => {
          node.textContent = "How fee options differ";
        });
      document.querySelectorAll("#popup-scrim .pop").forEach((popup) => {
        const evidence = state.evidence[popup.id];
        popup.querySelectorAll("[data-evidence-field]").forEach((node) => {
          const value = node.dataset.evidenceField
            .split(".")
            .reduce((value, key) => value[key], evidence);
          node.textContent = value;
        });
        popup.querySelector(".ld-popup-source").textContent =
          fixture.evidence.locator;
        popup
          .querySelector(".ld-popup-close")
          .setAttribute("aria-label", "Close detail");
      });
      return {
        count: Object.keys(state.units).length,
        overview: state.overview,
      };
    }, TEMPLATE_IMPORT);
    assert.equal(
      imported.count,
      5,
      "facts, question, answer, title and figure all filled by semantic role",
    );
    await session.page.evaluate(
      () =>
        new Promise((resolve) =>
          requestAnimationFrame(() => requestAnimationFrame(resolve)),
        ),
    );
    assert.equal(
      await session.page.evaluate(() => LegalDesign.checkPageFit().valid),
      false,
      "the taller imported choice graphic does not fit the short overview window",
    );
    await assert.rejects(
      session.page.evaluate(() => LegalDesign.exportHTML(false)),
      /Page exceeds the available window/,
      "export must not clip the imported figure",
    );
    await session.page.screenshot({
      path: join(OUT, "current-template-import-fit-gate.png"),
    });
    await session.page.setViewportSize({ width: 1440, height: 900 });
    await session.page.evaluate(
      () =>
        new Promise((resolve) =>
          requestAnimationFrame(() => requestAnimationFrame(resolve)),
        ),
    );
    assert.equal(
      await session.page.evaluate(() => LegalDesign.checkPageFit().valid),
      true,
      "the complete imported page fits a supported roomier desktop window",
    );
    assert.equal(
      await session.page
        .locator('#ld-page-approach,[data-approach="b"]')
        .count(),
      0,
    );
    const path = await downloadFrom(
      session.page,
      "#export-html",
      "v4-template-import-client.html",
    );
    const client = await pageFor({
      url: pathToFileURL(path).href,
      viewport: { width: 1440, height: 900 },
    });
    assert.doesNotMatch(
      await client.page.locator("body").innerText(),
      /\[[^\]]+\]/,
    );
    const result = await client.page.evaluate(() => {
      const state = window.LegalDesign.state();
      const surface = Object.values(state.units)
        .flatMap((unit) => [
          ...Object.values(unit.edits || {}),
          ...Object.values(unit.variants || {}).flatMap((variant) => [
            variant.html,
            JSON.stringify(variant.params),
          ]),
        ])
        .filter(Boolean)
        .join("\n");
      return {
        surface,
        fits: window.LegalDesign.checkPageFit().valid,
        schema: state.sourceSchemaVersion,
        hasApproaches: "approaches" in state,
        overview: state.overview,
        sections: state.composition.sections.length,
      };
    });
    assert.doesNotMatch(result.surface, /\[[A-Z][^[\]\r\n]{2,199}\]/);
    assert.match(result.surface, /\$12,000/);
    assert.match(result.surface, /\$15,000/);
    assert.match(result.surface, /six-week contract review/);
    assert.match(result.surface, /Which fee structure/);
    assert.equal(result.schema, "legaldesign.build.v4");
    assert.equal(result.hasApproaches, false);
    assert.equal(result.sections, 1);
    assert.deepEqual(result.overview, imported.overview);
    assert.equal(result.fits, true, "filled single-output client fits");
    const trigger = client.page.locator("[data-detail]:visible").first();
    await trigger.click();
    const popup = await client.page
      .locator("#popup-scrim .pop:visible")
      .innerText();
    assert.match(popup, /Fee options memo/);
    assert.match(popup, /\$400 per hour/);
    await closeClean(client);
    await closeClean(session);
  },
);

await run("walkthrough slide navigation and portable location", async () => {
  const session = await pageFor({ asset: "walkthrough" });
  const { page } = session;
  await page.click('#ld-legacy-slide-index [data-report-section="2"]');
  assert.equal(
    await page.locator(".sb-slide.is-current").getAttribute("data-frame"),
    "3",
  );
  await page.keyboard.press("ArrowRight");
  assert.equal(
    await page.locator(".sb-slide.is-current").getAttribute("data-frame"),
    "4",
  );
  assert.equal((await stateFrom(page)).review.location, 4);
  await page.click("#mode-toggle");
  const savedPath = await downloadFrom(
    page,
    "#ld-save",
    "walkthrough-location-save.html",
  );
  await closeClean(session);

  const reopened = await pageFor({
    clearStorage: false,
    url: pathToFileURL(savedPath).href,
  });
  assert.equal((await stateFrom(reopened.page)).review.location, 4);
  assert.equal(
    await reopened.page
      .locator(".sb-slide.is-current")
      .getAttribute("data-frame"),
    "4",
  );
  await closeClean(reopened);

  const deep = await pageFor({ url: `${WALKTHROUGH_URL}?frame=4` });
  assert.equal(
    await deep.page.locator(".sb-slide.is-current").getAttribute("data-frame"),
    "4",
  );
  await closeClean(deep);
});

await run("walkthrough decisions save and reopen", async () => {
  const session = await pageFor({ asset: "walkthrough" });
  const { page } = session;
  await page.click('#ld-legacy-slide-index [data-report-section="4"]');
  for (const id of ["d-74", "d-91", "d-112"]) {
    const decision = page.locator(`[data-unit="${id}"]`);
    await decision.locator('[data-decision-option][value="B"]').click();
    const note = decision.locator("[data-decision-note]");
    await note.fill(`Note for ${id}`);
    await note.dispatchEvent("change");
    assert.equal(await decision.getAttribute("data-answered"), "");
  }
  await page.click("#mode-toggle");
  const savedPath = await downloadFrom(
    page,
    "#ld-save",
    "walkthrough-decisions-save.html",
  );
  await closeClean(session);

  const reopened = await pageFor({ url: pathToFileURL(savedPath).href });
  const saved = await stateFrom(reopened.page);
  for (const id of ["d-74", "d-91", "d-112"]) {
    assert.equal(saved.review.decisions[id].choice, "B");
    assert.equal(saved.review.decisions[id].note, `Note for ${id}`);
    const decision = reopened.page.locator(`[data-unit="${id}"]`);
    assert.equal(
      await decision
        .locator('[data-decision-option][value="B"]')
        .getAttribute("aria-pressed"),
      "true",
    );
    assert.equal(
      await decision.locator("[data-decision-note]").inputValue(),
      `Note for ${id}`,
    );
  }
  await closeClean(reopened);
});

await run("walkthrough client and template decisions", async () => {
  const clientSession = await pageFor({ asset: "walkthrough" });
  await clientSession.page.click(
    '#ld-legacy-slide-index [data-report-section="4"]',
  );
  for (const id of ["d-74", "d-91", "d-112"])
    await clientSession.page
      .locator(`[data-unit="${id}"] [data-decision-option][value="B"]`)
      .click();
  const clientPath = await downloadFrom(
    clientSession.page,
    "#export-html",
    "walkthrough-client-export.html",
  );
  await closeClean(clientSession);

  const client = await pageFor({ url: pathToFileURL(clientPath).href });
  assert.equal(
    await client.page.locator("html").getAttribute("data-exported"),
    "client",
  );
  assert.equal(await client.page.locator('[data-kind="decision"]').count(), 3);
  await client.page.click('#ld-legacy-slide-index [data-report-section="4"]');
  await client.page
    .locator('[data-unit="d-74"] [data-decision-option][value="C"]')
    .click();
  assert.equal((await stateFrom(client.page)).review.decisions["d-74"], "C");
  assert.match(
    await client.page.locator("#legaldesign-state").textContent(),
    /"d-74":"C"/,
  );
  await closeClean(client);

  const templateSession = await pageFor({ asset: "walkthrough" });
  const templatePath = await downloadFrom(
    templateSession.page,
    "#export-template",
    "walkthrough-template-export.html",
  );
  await closeClean(templateSession);
  const template = await pageFor({ url: pathToFileURL(templatePath).href });
  assert.equal(
    await template.page.locator("html").getAttribute("data-exported"),
    "template",
  );
  assert.equal(
    await template.page.locator('[data-kind="decision"]').count(),
    3,
  );
  for (const decision of await template.page
    .locator('[data-kind="decision"]')
    .all()) {
    assert.equal(
      await decision.locator("h2").textContent(),
      "[The choice the reader makes, as a question.]",
    );
    assert.equal(await decision.locator("[data-decision-option]").count(), 3);
    assert.deepEqual(
      await decision
        .locator("[data-decision-option] b")
        .evaluateAll((nodes) => nodes.map((node) => node.textContent)),
      ["[Option 1.]", "[Option 2.]", "[Option 3.]"],
    );
    assert.deepEqual(
      await decision
        .locator("[data-decision-option]")
        .evaluateAll((nodes) => nodes.map((node) => node.value)),
      ["option-1", "option-2", "option-3"],
    );
  }
  const templateHTML = await template.page.content();
  for (const term of TERMS["slide-brief.html"])
    assert(!templateHTML.toLowerCase().includes(term.toLowerCase()), term);
  await closeClean(template);
});

await run("walkthrough phone track has no horizontal scroll", async () => {
  for (const viewport of [
    { width: 430, height: 932 },
    { width: 390, height: 844 },
  ]) {
    const session = await pageFor({ asset: "walkthrough", viewport });
    const { page } = session;
    assert.deepEqual(
      await page
        .locator(".ld-controls > button:visible")
        .evaluateAll((nodes) => nodes.map((node) => node.id)),
      ["mode-toggle", "theme-toggle", "export-html", "export-template"],
    );
    await page.evaluate(() => {
      const state = window.LegalDesign.state();
      state.units["u-s1-body"].selected = "b";
      window.LegalDesign.setState(state);
    });
    assert.equal(
      await page.evaluate(() => document.documentElement.scrollWidth),
      viewport.width,
    );
    assert.equal(
      await page
        .locator(".sb-track:visible")
        .evaluate((node) => node.scrollWidth <= node.clientWidth),
      true,
    );
    await closeClean(session);
  }
});

await run("walkthrough slides fit the laptop viewport", async () => {
  for (const viewport of [
    { width: 1440, height: 900 },
    { width: 1280, height: 800 },
  ]) {
    const session = await pageFor({ asset: "walkthrough", viewport });
    const { page } = session;
    for (let frame = 1; frame <= 6; frame += 1) {
      await page.evaluate(
        (next) => window.LegalDesignWalkthrough.showFrame(next, true),
        frame,
      );
      const measured = await page.evaluate(() => {
        const slide = document.querySelector(".sb-slide.is-current");
        const foot = slide.querySelector(".sb-foot").getBoundingClientRect();
        const pageScale =
          slide.getBoundingClientRect().width / slide.offsetWidth;
        let minFigureText = Number.POSITIVE_INFINITY;
        for (const text of slide.querySelectorAll(
          ".ld-variant:not([hidden]) svg text",
        )) {
          if (text.getBoundingClientRect().width <= 0) continue;
          const matrix = text.getScreenCTM();
          const scale = matrix ? Math.hypot(matrix.b, matrix.d) : 0;
          minFigureText = Math.min(
            minFigureText,
            (parseFloat(getComputedStyle(text).fontSize) * scale) / pageScale,
          );
        }
        return {
          documentHeight: document.documentElement.scrollHeight,
          footBottom: foot.bottom,
          innerHeight: window.innerHeight,
          minFigureText,
        };
      });
      assert(
        measured.footBottom <= measured.innerHeight,
        `${viewport.width}x${viewport.height} slide ${frame}: foot bottom ${measured.footBottom.toFixed(1)}px`,
      );
      assert(
        measured.documentHeight <= measured.innerHeight,
        `${viewport.width}x${viewport.height} slide ${frame}: document ${measured.documentHeight}px tall`,
      );
      assert(
        measured.minFigureText >= 11,
        `${viewport.width}x${viewport.height} slide ${frame}: intrinsic figure text ${measured.minFigureText.toFixed(1)}px`,
      );
    }
    await closeClean(session);
  }
});

await run("walkthrough screenshot matrix", async () => {
  const shots = [];
  for (const viewport of [
    { width: 1440, height: 900 },
    { width: 1280, height: 800 },
    { width: 430, height: 932 },
  ]) {
    for (const theme of ["light", "dark"]) {
      const session = await pageFor({ asset: "walkthrough", viewport });
      if (theme === "dark") await session.page.click("#theme-toggle");
      for (let frame = 1; frame <= 6; frame += 1) {
        if (viewport.width <= 480) {
          await session.page.evaluate((next) => {
            window.LegalDesignWalkthrough.showFrame(next, true);
          }, frame);
          const clearance = await session.page.evaluate((next) => {
            const barBottom = document
              .querySelector(".ld-bar")
              .getBoundingClientRect().bottom;
            const currentTop = document
              .querySelector(`[data-frame="${next}"]`)
              .getBoundingClientRect().top;
            const previousFoot = document.querySelector(
              `[data-frame="${next - 1}"] .sb-foot`,
            );
            return {
              barBottom,
              currentTop,
              previousFootBottom: previousFoot
                ? previousFoot.getBoundingClientRect().bottom
                : null,
            };
          }, frame);
          assert(
            clearance.currentTop >= clearance.barBottom - 1,
            `walkthrough slide ${frame} begins under the phone bar`,
          );
          if (clearance.previousFootBottom !== null)
            assert(
              clearance.previousFootBottom <= clearance.barBottom,
              `walkthrough slide ${frame} leaves the prior footer below the phone bar`,
            );
        } else {
          await session.page.click(
            `#ld-legacy-slide-index [data-report-section="${frame - 1}"]`,
          );
        }
        const name = `walkthrough-slide-${frame}-${viewport.width}x${viewport.height}-${theme}.png`;
        await session.page.screenshot({ path: join(OUT, name) });
        shots.push(name);
      }
      await closeClean(session);
    }
  }

  const popupSession = await pageFor({
    asset: "walkthrough",
    viewport: { width: 1280, height: 800 },
  });
  for (const id of ["p74", "p91", "p112"]) {
    await popupSession.page.evaluate(
      (popupId) => window.LegalDesign.openPopup(popupId),
      id,
    );
    const name = `walkthrough-popup-${id}.png`;
    await popupSession.page.screenshot({ path: join(OUT, name) });
    shots.push(name);
    await popupSession.page.keyboard.press("Escape");
  }
  const clientPath = await downloadFrom(
    popupSession.page,
    "#export-html",
    "walkthrough-screenshot-client.html",
  );
  const templatePath = await downloadFrom(
    popupSession.page,
    "#export-template",
    "walkthrough-screenshot-template.html",
  );
  await closeClean(popupSession);
  for (const [kind, path] of [
    ["client", clientPath],
    ["template", templatePath],
  ]) {
    const exported = await pageFor({ url: pathToFileURL(path).href });
    const name = `walkthrough-export-${kind}.png`;
    await exported.page.screenshot({ path: join(OUT, name) });
    shots.push(name);
    await closeClean(exported);
  }
  assert.equal(shots.length, 41);
  for (const shot of shots) assert(existsSync(join(OUT, shot)), shot);
  console.log(`Walkthrough screenshots (${shots.length}): ${shots.join(", ")}`);
});

await runEditorAuthoringSuite({
  run,
  pageFor,
  closeClean,
  composedFixture,
  sourceRuntimeAsset,
  downloadFrom,
  stateFrom,
});
await runDiagramRefinementSuite({ run, pageFor, closeClean });
await runSnapshotSuite({ run, pageFor, closeClean });

await run("shipped templates are current", async () => {
  const result = spawnSync(
    process.execPath,
    [join(HERE, "make-templates.mjs"), "--check"],
    { cwd: REPO, encoding: "utf8", env: process.env },
  );
  assert.equal(
    result.status,
    0,
    `${result.stdout || ""}${result.stderr || ""}`,
  );
  assert.match(result.stdout, /stacked-explainer\.template\.html is current/);
  assert.match(result.stdout, /method-map\.template\.html is current/);
});

function countScreenshots(directory) {
  return readdirSync(directory, { withFileTypes: true }).reduce(
    (count, entry) =>
      count +
      (entry.isDirectory()
        ? countScreenshots(join(directory, entry.name))
        : entry.name.endsWith(".png")
          ? 1
          : 0),
    0,
  );
}

console.log(`PASS: ${results.length} LegalDesign browser groups`);
console.log(
  `PASS: ${countScreenshots(OUT)} LegalDesign screenshots written under ${OUT}`,
);
