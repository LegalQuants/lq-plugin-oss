import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readdirSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { chromium } from "@playwright/test";

const HERE = dirname(new URL(import.meta.url).pathname);
const REPO = resolve(HERE, "../../..");
const ASSETS = join(REPO, "skills/core/legaldesign/assets");
const TEMPLATES = join(ASSETS, "templates");
const BLUEPRINTS = join(REPO, "packages/legaldesign/templates");
const SCAFFOLD = join(REPO, "skills/core/legaldesign/scripts/scaffold.py");
const MATTER_TERMS = JSON.parse(
  readFileSync(
    join(REPO, "packages/legaldesign/fixtures/matter-terms.json"),
    "utf8",
  ),
);
const checkOnly = process.argv.includes("--check");
const bundledExecutable = chromium.executablePath();
const systemExecutables = [
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  "/Applications/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
  "/Applications/Chromium.app/Contents/MacOS/Chromium",
];
const executable = existsSync(bundledExecutable)
  ? bundledExecutable
  : systemExecutables.find(existsSync);
// Templates are already fully minified. This cap retains meaningful headroom
// after adding typed overview links, persisted popup editing, modal focus trapping,
// and fail-closed template privacy to the self-contained runtime.
// Includes the shared object editor, popup authoring and responsive slide index.
// Working templates carry a separately compiled, inert reader runtime so
// browser-only exports can physically omit file-writing code without a build tool.
const MAX_TEMPLATE_BYTES = 425_000;
assert.ok(
  executable,
  "Chromium or Google Chrome is required to build templates",
);

async function loadEsbuild() {
  const store = join(REPO, "node_modules/.pnpm");
  const entry = readdirSync(store)
    .filter((name) => /^esbuild@/.test(name))
    .sort()
    .at(-1);
  assert.ok(entry, "the repository's esbuild dependency is unavailable");
  return import(
    pathToFileURL(join(store, entry, "node_modules/esbuild/lib/main.js")).href
  );
}

async function compactExport(source) {
  const { transform } = await loadEsbuild();
  let html = source;
  const scripts = [...html.matchAll(/<script([^>]*)>([\s\S]*?)<\/script>/g)];
  for (const match of scripts.reverse()) {
    if (/application\/json/.test(match[1])) continue;
    const code = (
      await transform(match[2], {
        loader: "js",
        minify: true,
        target: "es2020",
      })
    ).code;
    html = `${html.slice(0, match.index)}<script${match[1]}>${code}</script>${html.slice((match.index || 0) + match[0].length)}`;
  }
  const styles = [...html.matchAll(/<style([^>]*)>([\s\S]*?)<\/style>/g)];
  for (const match of styles.reverse()) {
    const css = (
      await transform(match[2], {
        loader: "css",
        minify: true,
      })
    ).code;
    html = `${html.slice(0, match.index)}<style${match[1]}>${css}</style>${html.slice((match.index || 0) + match[0].length)}`;
  }
  return html
    .replaceAll("<!-- legaldesign:runtime -->", "")
    .replaceAll("<!-- /legaldesign:runtime -->", "")
    .replace(/<!-- \/?legaldesign:(?:composed-content|popups) -->/g, "")
    .replaceAll(' xmlns="http://www.w3.org/2000/svg"', "")
    .replaceAll(
      '"http://www.w3.org/2000/svg"',
      '"http:"+"//www.w3.org/2000/svg"',
    )
    .replace(/>\s+</g, "><");
}

async function pageSignature(page) {
  await page.waitForFunction(() => window.LegalDesign?.state);
  return page.evaluate(() => {
    function checksum(value) {
      let hash = 2166136261;
      for (let index = 0; index < value.length; index += 1) {
        hash ^= value.charCodeAt(index);
        hash = Math.imul(hash, 16777619);
      }
      return `${(hash >>> 0).toString(16)}:${value.length}`;
    }
    const state = JSON.parse(
      document.getElementById("legaldesign-state").textContent,
    );
    const normalizedState = structuredClone(state);
    delete normalizedState.savedAt;
    if (document.documentElement.dataset.templateBlueprintId)
      normalizedState.artifactId =
        document.documentElement.dataset.templateBlueprintId;
    const units = Object.fromEntries(
      Object.entries(state.units).map(([id, unit]) => [
        id,
        {
          variants: Object.keys(unit.variants),
          placeholder: unit.placeholder || null,
          placeholder_title: unit.placeholder_title || null,
          placeholder_sub: unit.placeholder_sub || null,
          why: Object.fromEntries(
            Object.entries(unit.variants).map(([key, variant]) => [
              key,
              variant.why,
            ]),
          ),
        },
      ]),
    );
    const visiblePlaceholders = [];
    const walker = document.createTreeWalker(
      document.body,
      NodeFilter.SHOW_TEXT,
    );
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      const parent = node.parentElement;
      if (
        !parent ||
        parent.closest("script,style,[hidden],[aria-hidden='true']")
      )
        continue;
      const value = node.textContent.replace(/\s+/g, " ").trim();
      if (/\[[^\]]+\]/.test(value)) visiblePlaceholders.push(value);
    }
    return {
      units,
      evidenceKeys: Object.keys(state.evidence),
      visiblePlaceholders,
      runtime: Object.fromEntries(
        ["ld-runtime", "ld-components", "ld-tokens"].map((id) => [
          id,
          checksum(document.getElementById(id)?.textContent || ""),
        ]),
      ),
      toolbar: checksum(
        [".ld-controls", ".ld-editor-tools"]
          .map((selector) => document.querySelector(selector)?.outerHTML || "")
          .join("\n"),
      ),
      portableState: checksum(JSON.stringify(normalizedState)),
      templateIdentity: {
        kind: document.documentElement.dataset.templateKind || null,
        blueprintId:
          document.documentElement.dataset.templateBlueprintId || null,
      },
    };
  });
}

async function freshTemplate(browser, sourceName, outputName) {
  const scratch = mkdtempSync(join(tmpdir(), "legaldesign-template-build-"));
  const source = join(scratch, sourceName);
  try {
    execFileSync(
      process.env.PYTHON || "python3",
      [
        SCAFFOLD,
        "compose",
        "--plan",
        join(BLUEPRINTS, sourceName.replace(/\.html$/, ".plan.json")),
        "--spec-output",
        join(scratch, "validated.spec.json"),
        "--output",
        source,
        "--artifact-id",
        `legaldesign-blueprint-${sourceName.replace(/\.html$/, "")}`,
      ],
      { cwd: REPO, stdio: "pipe" },
    );
  } catch (error) {
    rmSync(scratch, { recursive: true, force: true });
    throw new Error(
      "Template blueprint failed: " +
        (error.stderr?.toString() || error.message),
    );
  }
  const context = await browser.newContext({
    viewport: { width: 1280, height: 800 },
  });
  const page = await context.newPage();
  const faults = [];
  page.on("console", (message) => {
    if (message.type() === "error") faults.push(`console: ${message.text()}`);
  });
  page.on("pageerror", (error) => faults.push(`pageerror: ${error.message}`));
  await page.goto(pathToFileURL(source).href, { waitUntil: "load" });
  await page.waitForFunction(() => window.LegalDesign?.exportTemplate);
  const templateId = `legaldesign-template-${sourceName
    .replace(/\.html$/, "")
    .replace(/[^a-z0-9]+/gi, "-")
    .toLowerCase()}`;
  await page.evaluate(() => {
    const probe = window.LegalDesign.state();
    probe.brief.message = "PRIVATE_TEMPLATE_PROBE_836104";
    const item = Object.values(probe.evidence)[0];
    item.popup.lede = "PRIVATE_TEMPLATE_PROBE_836104";
    window.LegalDesign.setState(probe);
    const title = document.querySelector(".ld-matter");
    if (title) title.textContent = "PRIVATE_TEMPLATE_PROBE_836104";
  });
  const exported = await page.evaluate(
    (id) => window.LegalDesign.exportTemplate(false, id),
    templateId,
  );
  assert.ok(
    !exported.includes("PRIVATE_TEMPLATE_PROBE_836104"),
    "Template export leaked source state or visible matter",
  );
  const matterScan = exported
    // This inert payload is compiled solely from the shared runtime, not matter.
    .replace(
      /<script id="ld-client-runtime" type="application\/json">[\s\S]*?<\/script>/,
      "",
    )
    .replace(
      /<!-- legaldesign:runtime -->[\s\S]*?<!-- \/legaldesign:runtime -->/,
      "",
    )
    .replace(/<!-- \/?legaldesign:(?:composed-content|popups) -->/g, "");
  for (const term of MATTER_TERMS[sourceName] || [])
    assert.ok(
      !matterScan.toLowerCase().includes(term.toLowerCase()),
      `${outputName} contains matter term ${term}`,
    );
  const html = await compactExport(exported);
  assert.match(html, /<html[^>]+data-exported="template"/);
  const htmlBytes = Buffer.byteLength(html);
  assert.ok(
    htmlBytes < MAX_TEMPLATE_BYTES,
    `${outputName} exceeds ${MAX_TEMPLATE_BYTES / 1000} KB (${htmlBytes} bytes)`,
  );
  if (!checkOnly) writeFileSync(join(TEMPLATES, outputName), html);
  const rendered = await context.newPage();
  rendered.on("console", (message) => {
    if (message.type() === "error") faults.push(`console: ${message.text()}`);
  });
  rendered.on("pageerror", (error) =>
    faults.push(`pageerror: ${error.message}`),
  );
  await rendered.setContent(html, { waitUntil: "load" });
  const figureStructure = await rendered
    .locator("section.ld-unit[data-kind='figure'] .ld-variant")
    .evaluateAll((variants) =>
      variants.map((variant) => {
        const bodies = [...variant.children].filter((child) =>
          child.hasAttribute("data-variant-body"),
        );
        const diagrams = [...variant.querySelectorAll(".ld-diagram")];
        return {
          bodies: bodies.length,
          diagrams: diagrams.length,
          diagramsOutsideBody: diagrams.filter(
            (diagram) => !bodies[0]?.contains(diagram),
          ).length,
        };
      }),
    );
  assert.ok(
    figureStructure.every(
      ({ bodies, diagrams, diagramsOutsideBody }) =>
        bodies === 1 && diagrams === 1 && diagramsOutsideBody === 0,
    ),
    `${outputName} has a non-canonical figure body: ${JSON.stringify(figureStructure)}`,
  );
  assert.equal(
    await rendered
      .locator(
        ".ld-review,.ld-reaction,.ld-comment,.ld-sheet-open,.ld-bottom-save,.ld-phone-sheet,.ld-selection-popover",
      )
      .count(),
    0,
    `${outputName} kept retired review chrome`,
  );
  const current = await rendered.evaluate(() => ({
    version: window.LegalDesign.state().sourceSchemaVersion,
    approaches: Object.keys(window.LegalDesign.state().approaches || {}),
    globalControls: document.querySelectorAll(
      "#ld-page-approach [data-select-approach]",
    ).length,
    eyebrows: document.querySelectorAll("[class*=eyebrow],[class*=kicker]")
      .length,
    unitVariants: Object.values(window.LegalDesign.state().units).map((unit) =>
      Object.keys(unit.variants),
    ),
  }));
  assert.equal(current.version, "legaldesign.build.v4");
  assert.deepEqual(current.approaches, []);
  assert.equal(current.globalControls, 0);
  assert.equal(current.eyebrows, 0);
  assert.ok(
    current.unitVariants.every((keys) => keys.length === 1 && keys[0] === "a"),
  );
  assert.equal(
    await rendered.evaluate(
      () => window.LegalDesign.checkPageFit({ allPages: true }).valid,
    ),
    true,
  );
  const signature = await pageSignature(rendered);
  await rendered.close();
  assert.deepEqual(faults, []);
  await context.close();
  rmSync(scratch, { recursive: true, force: true });
  return signature;
}

async function committedSignature(browser, outputName) {
  const context = await browser.newContext({
    viewport: { width: 1280, height: 800 },
  });
  const page = await context.newPage();
  await page.goto(pathToFileURL(join(TEMPLATES, outputName)).href, {
    waitUntil: "load",
  });
  const signature = await pageSignature(page);
  await context.close();
  return signature;
}

async function reopenAndExercise(browser, outputName) {
  const context = await browser.newContext({
    viewport: { width: 1280, height: 800 },
  });
  const page = await context.newPage();
  const faults = [];
  page.on("console", (message) => {
    if (message.type() === "error") faults.push(`console: ${message.text()}`);
  });
  page.on("pageerror", (error) => faults.push(`pageerror: ${error.message}`));
  await page.goto(pathToFileURL(join(TEMPLATES, outputName)).href, {
    waitUntil: "load",
  });
  await page.waitForFunction(() => window.LegalDesign?.state);
  assert.equal(
    await page
      .locator(
        ".ld-review,.ld-reaction,.ld-comment,.ld-sheet-open,.ld-bottom-save,.ld-phone-sheet,.ld-selection-popover",
      )
      .count(),
    0,
    `${outputName} reopened with retired review chrome`,
  );
  await page.click("#theme-toggle");
  assert.equal(await page.locator("html").getAttribute("data-theme"), "dark");
  await page.click("#mode-toggle");
  assert.equal(await page.locator("[data-select-approach]").count(), 0);
  assert.equal(
    await page.locator('.ld-ab [data-select-variant="b"]').count(),
    0,
  );
  const exported = await page.evaluate(() =>
    window.LegalDesign.exportTemplate(false),
  );
  const reopened = await context.newPage();
  await reopened.setContent(exported);
  await reopened.waitForFunction(() => window.LegalDesign?.state);
  assert.deepEqual(
    await reopened.evaluate(() =>
      Object.keys(window.LegalDesign.state().approaches || {}),
    ),
    [],
  );
  await exerciseOverview(reopened);
  await reopened.close();
  const privateHeadingExport = await page.evaluate(() => {
    const probe = window.LegalDesign.state();
    const title = Object.values(probe.units).find(
      (unit) => unit.role === "title",
    );
    title.placeholder = "[PRIVATE_HEADING_PROBE_820913]";
    title.placeholder_title = "[PRIVATE_HEADING_PROBE_820913]";
    window.LegalDesign.setState(probe);
    const heading = document.querySelector("h1");
    heading.setAttribute("data-placeholder", "[PRIVATE_HEADING_PROBE_820913]");
    heading.setAttribute(
      "data-placeholder-title",
      "[PRIVATE_HEADING_PROBE_820913]",
    );
    heading.textContent = "PRIVATE_HEADING_PROBE_820913";
    return window.LegalDesign.exportTemplate(false);
  });
  assert.ok(
    !privateHeadingExport.includes("PRIVATE_HEADING_PROBE_820913"),
    `${outputName} trusted a matter-bearing heading placeholder`,
  );
  assert.deepEqual(faults, []);
  await context.close();
}

async function exerciseOverview(page) {
  const structure = await page.evaluate(() => {
    const { composition, overview, brief } = window.LegalDesign.state();
    return { composition, overview, form: brief.form };
  });
  const { composition, overview, form } = structure;
  assert.ok(composition?.sections?.length);
  assert.equal(overview.sectionId, composition.sections[0].id);
  assert.equal(await page.locator('[data-approach="b"]').count(), 0);
  if (form === "one-page") {
    assert.equal(composition.sections.length, 1);
    assert.deepEqual(overview.topics, []);
    assert.equal(await page.locator("#ld-form-navigation").count(), 0);
    return;
  }
  assert.equal(form, "slide-brief");
  assert.equal(overview.topics.length, composition.sections.length - 1);
  for (const [index, topic] of overview.topics.entries()) {
    if (index) await page.locator('[data-report-section="0"]').click();
    const link = page.locator(
      `[data-section-target="${topic.targetSectionId}"]`,
    );
    assert.equal(await link.count(), 1);
    await link.click();
    const active = await page
      .locator("[data-composition-section]:visible")
      .getAttribute("data-composition-section");
    assert.equal(active, topic.targetSectionId);
  }
  await page.locator('[data-report-section="0"]').click();
  const firstLink = page.locator("[data-section-target]").first();
  await firstLink.focus();
  await page.keyboard.press("Enter");
  assert.equal(
    await page
      .locator("[data-composition-section]:visible")
      .getAttribute("data-composition-section"),
    overview.topics[0].targetSectionId,
  );
}

mkdirSync(TEMPLATES, { recursive: true });
async function launch() {
  return chromium.launch({
    headless: true,
    args: ["--single-process"],
    executablePath: executable,
  });
}

const jobs = [
  ["stacked-explainer.html", "stacked-explainer.template.html"],
  ["slide-brief.html", "slide-brief.template.html"],
  ["diligence-report.html", "diligence-report.template.html"],
  ["method-map.html", "method-map.template.html"],
  ["card-hub.html", "card-hub.template.html"],
];
for (const [source, output] of jobs) {
  const exportBrowser = await launch();
  const generated = await freshTemplate(exportBrowser, source, output);
  await exportBrowser.close();
  if (checkOnly) {
    const signatureBrowser = await launch();
    const committed = await committedSignature(signatureBrowser, output);
    await signatureBrowser.close();
    assert.deepEqual(
      generated,
      committed,
      `${output} is stale; run node packages/legaldesign/browser/make-templates.mjs`,
    );
  }
  const reopenBrowser = await launch();
  await reopenAndExercise(reopenBrowser, output);
  await reopenBrowser.close();
  console.log(`PASS: ${output}${checkOnly ? " is current" : ""}`);
}
