import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import {
  copyFileSync,
  existsSync,
  mkdtempSync,
  readFileSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { chromium } from "@playwright/test";

// These are QA blueprints, not legal analysis. The optional authentic clip is
// read only from the operator's supplied sidecar and never embedded in this
// repository test. All generated matter-bearing copies stay in the temp run.
const repo = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const out = mkdtempSync(join(tmpdir(), "legaldesign-issue-layout-"));
const excerpt = "that has not been obtained on or prior to the date hereof.";
const sentinel = "SOURCE_PREVIEW_PROBE_904";
const exhibitPath = process.env.LEGALDESIGN_ISSUE_EXHIBIT;
if (exhibitPath)
  assert(existsSync(exhibitPath), "Configured optional exhibit path exists");
const exhibit = exhibitPath
  ? JSON.parse(readFileSync(exhibitPath, "utf8"))
  : null;
if (exhibit) {
  const bytes = Buffer.from(exhibit.data.split(",")[1], "base64");
  assert.equal(
    createHash("sha256").update(bytes).digest("hex"),
    exhibit.sha256,
    "Supplied clip checksum",
  );
}
const warnings = exhibit
  ? []
  : [
      "Optional authentic image sidecar unavailable; source-preview fixture uses the explicitly supplied exact excerpt, not a fabricated image.",
    ];
const readPlan = (name) =>
  JSON.parse(
    readFileSync(
      join(repo, `packages/legaldesign/templates/${name}.plan.json`),
      "utf8",
    ),
  );
function blueprint(plan, name) {
  plan.brief.title = `TEST BLUEPRINT — ${name}`;
  plan.brief.message =
    "Regression fixture only. The placeholder narrative is not completed legal analysis.";
  for (const section of plan.composition.sections) {
    const title = plan.units.find((unit) => unit.id === section.unitIds[0]);
    const tag = section === plan.composition.sections[0] ? "h1" : "h2";
    title.variants.a.html = `<${tag}>Test blueprint: ${section.indexLabel || section.purpose}</${tag}>`;
  }
  return plan;
}
const slide = blueprint(readPlan("slide-brief"), "slide issue layout");
const diligence = blueprint(
  readPlan("diligence-report"),
  "diligence issue layout",
);
const source = blueprint(
  readPlan("slide-brief"),
  "source-preview mechanics, not legal analysis",
);
source.brief.sources.push({
  id: "captured-test-source",
  label: "Supplied captured qualification used only for regression",
  status: "supplied",
});
source.claims
  .find((claim) => claim.id === "c-core")
  .sourceIds.push("captured-test-source");
const record = source.evidence.find((entry) => entry.id === "e-core");
Object.assign(record, {
  sourceId: "captured-test-source",
  cite: sentinel,
  locator:
    exhibit?.locator ||
    "Operator-supplied qualification only; not the full sentence",
  excerpt,
  detail:
    "Regression-only exact-source presentation. This does not support the placeholder narrative as legal analysis.",
  popup: {
    type: "source",
    title: "Source-preview mechanics — test only",
    lede: "This fixture tests a supplied exact quotation and source image. Its surrounding blueprint is not legal analysis.",
    sections: [
      { heading: "Exact qualification", body: excerpt },
      {
        heading: "Limits",
        body: "The displayed phrase is not the full sentence. No legal conclusion is offered by this regression fixture.",
      },
    ],
  },
  original: {
    availability: "unavailable",
    label: "Original-source access is outside this regression",
  },
});
if (exhibit) record.exhibit = exhibit;
function preview(id) {
  return {
    id,
    kind: "evidence",
    role: "summary",
    sourcePreview: true,
    claim: "Captured qualification — test only",
    claimRefs: ["c-core"],
    relationship: "containment",
    candidates: ["authentic source preview"],
    placeholder: "[Authentic supporting passage.]",
    evidence: ["e-core"],
    detail: "e-core",
    variants: {
      a: {
        axis: "framing",
        encoding:
          "The exact captured passage is source material, not a paraphrase of the blueprint.",
        why: "Tests the shared source-preview surface and popup without inventing a facsimile.",
      },
    },
  };
}
source.units.push(
  preview("source-preview-both"),
  preview("source-preview-only"),
);
source.composition.sections[1].unitIds.push("source-preview-both");
source.composition.sections[1].issueLayout.supportUnitIds.push(
  "source-preview-both",
);
source.composition.sections[2].unitIds = source.composition.sections[2].unitIds
  .filter((id) => id !== "compare")
  .concat("source-preview-only");
source.composition.sections[2].issueLayout.supportUnitIds = [
  "source-preview-only",
];
source.units = source.units.filter((unit) => unit.id !== "compare");

const fixtures = [
  { name: "slide", plan: slide },
  { name: "diligence", plan: diligence },
  { name: "source-preview", plan: source, sourcePreview: true },
];
for (const fixture of fixtures) {
  const planPath = join(out, `${fixture.name}.plan.json`);
  fixture.path = join(out, `${fixture.name}.html`);
  writeFileSync(planPath, JSON.stringify(fixture.plan, null, 2));
  const built = spawnSync(
    process.env.LEGALDESIGN_PYTHON || "python3",
    [
      "skills/core/legaldesign/scripts/scaffold.py",
      "compose",
      "--plan",
      planPath,
      "--spec-output",
      join(out, `${fixture.name}.spec.json`),
      "--output",
      fixture.path,
      "--artifact-id",
      `synthetic-issue-layout-${fixture.name}`,
    ],
    { cwd: repo, encoding: "utf8" },
  );
  assert.equal(built.status, 0, built.stdout + built.stderr);
}
console.log(`Issue-layout QA blueprints only: ${out}`);
const failures = [],
  errors = [],
  measurements = [],
  interactions = [],
  downloads = [],
  requests = [];
const browser = await chromium.launch({
  headless: true,
  executablePath: [
    chromium.executablePath(),
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  ].find(existsSync),
});
const sizes = [
  [1280, 800],
  [1440, 900],
  [2560, 1440],
  [390, 844],
];
const visibleSection = "[data-composition-section]:visible";
const settle = (page) =>
  page.evaluate(
    () =>
      new Promise((done) =>
        requestAnimationFrame(() => requestAnimationFrame(done)),
      ),
  );
async function state(page) {
  return page.evaluate(() =>
    JSON.parse(document.getElementById("legaldesign-state").textContent),
  );
}
async function open(path, width, height) {
  const page = await browser.newPage({
    viewport: { width, height },
    hasTouch: width <= 760,
    acceptDownloads: true,
  });
  page.setDefaultTimeout(6000);
  await page.addInitScript(() =>
    Object.defineProperty(window, "showSaveFilePicker", {
      configurable: true,
      value: undefined,
    }),
  );
  await page.route(/^https?:\/\//, async (route) => {
    requests.push({ path, type: route.request().resourceType() });
    await route.abort();
  });
  await page.context().setOffline(true);
  page.on("pageerror", (error) =>
    errors.push({ path, message: error.message }),
  );
  await page.goto(pathToFileURL(path).href);
  await page.waitForFunction(
    () => document.documentElement.dataset.legaldesignReady === "true",
  );
  await page.evaluate(() => document.fonts.ready);
  await settle(page);
  return page;
}
async function closeReader(page) {
  if (await page.locator("#ld-page-reader").isVisible())
    await page
      .getByRole("button", { name: "Close page reader", exact: true })
      .click();
}
async function navigate(page, index, phone) {
  await closeReader(page);
  const button = page.locator(`[data-report-section="${index}"]`);
  if (!(await button.isVisible()))
    await page.locator("[data-index-toggle]").click();
  await button.click();
  await settle(page);
  if (phone) {
    await page.locator("#ld-read-page").click();
    await page.locator("#ld-page-reader").waitFor({ state: "visible" });
    await settle(page);
  }
}
const activeScope = (page, phone) =>
  page.locator(phone ? "#ld-page-reader" : visibleSection);
async function inspect(page, recipe, phone, label) {
  const info = await activeScope(page, phone).evaluate((scope) => {
    const box = (node) => node.getBoundingClientRect().toJSON();
    const body = scope.querySelector(".ld-issue-body"),
      left = body.querySelector(".ld-issue-analysis"),
      right = body.querySelector(".ld-issue-support");
    const text = (node) => ({
      box: box(node),
      size: getComputedStyle(node).fontSize,
      line: getComputedStyle(node).lineHeight,
    });
    const item = (node) => ({
      box: box(node),
      unit: node.dataset.unit || null,
      kind: node.dataset.kind || null,
      padding: getComputedStyle(node).padding,
      border: getComputedStyle(node).border,
      transform: getComputedStyle(node).transform,
      heading: node.querySelector("h1,h2,h3")
        ? text(node.querySelector("h1,h2,h3"))
        : null,
      prose: [...node.querySelectorAll("p")].map(text),
      source: [...node.querySelectorAll(".ld-source-preview")].map(
        (preview) => ({
          box: box(preview),
          caption: preview.querySelector("figcaption")
            ? text(preview.querySelector("figcaption"))
            : null,
          images: [...preview.querySelectorAll("img,svg")].map((image) => {
            const bounds = box(image),
              style = getComputedStyle(image);
            // The existing exhibit shot has a paper border. Compare the
            // actual pixel area, not that decorated outer border box.
            const content = [
              bounds.width -
                parseFloat(style.borderLeftWidth) -
                parseFloat(style.borderRightWidth) -
                parseFloat(style.paddingLeft) -
                parseFloat(style.paddingRight),
              bounds.height -
                parseFloat(style.borderTopWidth) -
                parseFloat(style.borderBottomWidth) -
                parseFloat(style.paddingTop) -
                parseFloat(style.paddingBottom),
            ];
            return {
              tag: image.tagName,
              box: bounds,
              content,
              natural:
                image.tagName === "IMG"
                  ? [image.naturalWidth, image.naturalHeight]
                  : [image.viewBox.baseVal.width, image.viewBox.baseVal.height],
            };
          }),
        }),
      ),
    });
    const active = [
      ...document.querySelectorAll("[data-composition-section]"),
    ].find((node) => !node.hidden);
    return {
      viewport: [innerWidth, innerHeight],
      fit: LegalDesign.checkPageFit(),
      page: box(active),
      pageTransform: getComputedStyle(active).transform,
      title: text(scope.querySelector("h1,h2")),
      body: box(body),
      left: box(left),
      right: box(right),
      columns: getComputedStyle(body).gridTemplateColumns,
      gap: getComputedStyle(body).gap,
      cards: [...left.children].map(item),
      supports: [...right.children].map(item),
      documentWidth: [
        document.documentElement.clientWidth,
        document.documentElement.scrollWidth,
      ],
      readerWidth:
        scope.id === "ld-page-reader"
          ? [scope.clientWidth, scope.scrollWidth]
          : null,
    };
  });
  measurements.push({ label, ...info });
  assert.equal(info.cards.length, 3, `${label}: exactly three analysis cards`);
  assert.equal(
    info.supports.length,
    recipe.supportUnitIds.length,
    `${label}: support count`,
  );
  assert(
    info.documentWidth[1] <= info.documentWidth[0] + 1,
    `${label}: document horizontal overflow`,
  );
  if (phone) {
    assert(
      info.readerWidth[1] <= info.readerWidth[0] + 1,
      `${label}: reader horizontal overflow`,
    );
    assert(
      info.right.top >= info.left.bottom - 1,
      `${label}: phone support follows all three analysis cards`,
    );
    for (const card of info.cards)
      for (const prose of card.prose)
        assert.equal(prose.size, "18px", `${label}: phone reading type`);
  } else {
    assert(info.fit.valid, `${label}: page fit`);
    assert.equal(
      info.pageTransform,
      "matrix(1, 0, 0, 1, 0, 0)",
      `${label}: no desktop fit scaling`,
    );
    assert.equal(info.title.size, "28px", `${label}: stable page title`);
    assert(
      Math.abs(info.left.width - info.right.width) < 1,
      `${label}: equal issue columns`,
    );
    assert(
      Math.abs(info.left.top - info.right.top) < 1,
      `${label}: support top alignment`,
    );
    assert(
      info.right.left > info.left.right,
      `${label}: distinct columns with gutter`,
    );
    assert(
      info.body.bottom <= info.page.bottom + 1,
      `${label}: issue body contained in page`,
    );
    assert(
      Math.abs(info.title.box.width - info.body.width) < 1,
      `${label}: full-width title`,
    );
    assert.deepEqual(
      info.cards.map((card) => card.unit),
      [recipe.findingUnitId, recipe.implicationUnitId, recipe.actionUnitId],
      `${label}: typed analysis slots`,
    );
    assert.deepEqual(
      info.supports.map((support) => support.unit),
      recipe.supportUnitIds,
      `${label}: typed support slots`,
    );
    for (const card of info.cards) {
      assert(
        Math.abs(card.box.width - info.left.width) < 1,
        `${label}: card fills analysis track`,
      );
      assert.equal(card.heading.size, "20px", `${label}: stable card heading`);
      for (const prose of card.prose)
        assert.equal(prose.size, "16px", `${label}: stable body type`);
    }
    for (const support of info.supports)
      assert(
        Math.abs(support.box.width - info.right.width) < 1,
        `${label}: support fills track`,
      );
  }
  for (let index = 1; index < info.cards.length; index++)
    assert(
      info.cards[index].box.top >= info.cards[index - 1].box.bottom - 1,
      `${label}: separate non-overlapping cards`,
    );
  for (const support of info.supports)
    for (const preview of support.source)
      for (const image of preview.images) {
        assert(
          image.box.width <= preview.box.width + 1,
          `${label}: source image inside preview`,
        );
        assert(
          image.content[0] <= image.natural[0] + 1,
          `${label}: source image not upscaled`,
        );
        assert(
          Math.abs(
            image.content[0] / image.content[1] -
              image.natural[0] / image.natural[1],
          ) < 0.1,
          `${label}: source aspect ratio retained`,
        );
      }
}
async function checkBlueAffordance(page, phone, label) {
  if (phone) return;
  const card = activeScope(page, false)
    .locator(
      ".ld-issue-analysis > .ld-composed-unit:is([data-detail],[data-evidence])",
    )
    .first();
  assert.equal(await card.count(), 1, `${label}: clickable recipe card`);
  const handle = await card.elementHandle();
  const neutral = async (input) => {
    await page.waitForFunction((node) => {
      const style = getComputedStyle(node);
      const expected =
        document.documentElement.dataset.theme === "dark"
          ? "rgb(160, 160, 156)"
          : "rgb(118, 118, 118)";
      return [
        style.borderTopColor,
        style.borderRightColor,
        style.borderBottomColor,
        style.borderLeftColor,
      ].every((color) => color === expected);
    }, handle);
    interactions.push({
      label,
      input,
      affordance: "neutral recipe-card border",
    });
  };
  await card.hover();
  await neutral("hover");
  await page.mouse.move(0, 0);
  await card.focus();
  await page.keyboard.press("Tab");
  await page.keyboard.press("Shift+Tab");
  assert(
    await card.evaluate(
      (node) =>
        document.activeElement === node && node.matches(":focus-visible"),
    ),
    `${label}: keyboard-visible focus`,
  );
  await neutral("keyboard focus");
}
async function exerciseTargets(page, phone, label) {
  const scope = activeScope(page, phone);
  const targets = scope.locator("[data-detail],[data-evidence]");
  const count = await targets.count();
  assert(count >= 3, `${label}: purposeful detail targets present`);
  for (let index = 0; index < count; index++) {
    const target = targets.nth(index);
    if (!(await target.isVisible())) continue;
    const expected = await target.evaluate(
      (node) => node.dataset.detail || node.dataset.evidence,
    );
    assert.equal(
      await target.locator("[data-detail],[data-evidence]").count(),
      0,
      `${label}: no nested competing detail target`,
    );
    // Pointer is the primary coverage. Also exercise keyboard activation on
    // one actual card per state, without forced/programmatic dispatch.
    await target.scrollIntoViewIfNeeded();
    const readerBefore = phone
      ? await page.locator("#ld-page-reader").evaluate((node) => node.scrollTop)
      : null;
    await target.click();
    await settle(page);
    const pop = page.locator("#popup-scrim > .pop:visible");
    assert.equal(await pop.count(), 1, `${label}: one active popup`);
    assert.equal(
      await pop.evaluate(
        (node) => node.getAttribute("data-evidence-id") || node.id,
      ),
      expected,
      `${label}: exact target popup`,
    );
    const popupBox = await pop.boundingBox();
    assert(
      popupBox.x >= -1 &&
        popupBox.y >= -1 &&
        popupBox.x + popupBox.width <= page.viewportSize().width + 1 &&
        popupBox.y + popupBox.height <= page.viewportSize().height + 1,
      `${label}: popup inside window`,
    );
    await page.keyboard.press("Escape");
    await settle(page);
    assert(
      await target.evaluate((node) => document.activeElement === node),
      `${label}: Escape returns exact target focus`,
    );
    if (phone) {
      assert(
        await page.locator("#ld-page-reader").isVisible(),
        `${label}: reader restored`,
      );
      assert(
        Math.abs(
          (await page
            .locator("#ld-page-reader")
            .evaluate((node) => node.scrollTop)) - readerBefore,
        ) < 2,
        `${label}: reader scroll restored`,
      );
    }
    interactions.push({ label, target: index, expected, input: "pointer" });
    if (index === 0) {
      await target.press("Enter");
      await settle(page);
      assert.equal(
        await page
          .locator("#popup-scrim > .pop:visible")
          .evaluate((node) => node.getAttribute("data-evidence-id") || node.id),
        expected,
        `${label}: keyboard popup`,
      );
      await page.keyboard.press("Escape");
      await settle(page);
      interactions.push({ label, target: index, expected, input: "Enter" });
    }
  }
}
async function matrix(path, fixture, kind) {
  for (const [width, height] of sizes)
    for (const theme of ["light", "dark"]) {
      const label = `${fixture.name}-${kind}-${width}-${theme}`;
      await attempt(label, async () => {
        const phone = width <= 760,
          page = await open(path, width, height);
        try {
          await closeReader(page);
          if ((await page.locator("html").getAttribute("data-theme")) !== theme)
            await page.locator("#theme-toggle").click();
          const data = await state(page);
          const issuePages = data.composition.sections
            .map((section, index) => ({ section, index }))
            .filter(({ section }) => section.issueLayout);
          assert.equal(
            issuePages.length,
            fixture.plan.composition.sections.length - 1,
            `${label}: issueLayout retained after reopen`,
          );
          for (const { section, index } of issuePages) {
            await navigate(page, index, phone);
            const pageLabel = `${label}-page-${index}`;
            // Capture first painted issue layout before hover or target clicks.
            await page.screenshot({ path: join(out, `${pageLabel}-cold.png`) });
            await inspect(page, section.issueLayout, phone, pageLabel);
            await checkBlueAffordance(page, phone, pageLabel);
            await exerciseTargets(page, phone, pageLabel);
          }
          console.log(
            `PASS ${label}: ${issuePages.length} issue pages and real popup targets`,
          );
        } catch (error) {
          await page.screenshot({ path: join(out, `${label}-failure.png`) });
          throw error;
        } finally {
          await page.close();
        }
      });
    }
}
async function attempt(label, action) {
  try {
    await action();
  } catch (error) {
    failures.push({ label, error: error.stack || String(error) });
    console.error(`FAIL ${label}: ${error.message}`);
  }
}
async function download(page, selector, name) {
  const [result] = await Promise.all([
    page.waitForEvent("download", { timeout: 15000 }),
    page.locator(selector).click(),
  ]);
  assert.equal(await result.failure(), null);
  const actual = await result.path();
  assert(actual && existsSync(actual));
  const target = join(out, name);
  copyFileSync(actual, target);
  downloads.push({ name, path: target });
  return target;
}
function checkPreviewPrivacy(html, kind) {
  const inert = JSON.parse(
    html.match(
      /<script[^>]*id="legaldesign-state"[^>]*>([\s\S]*?)<\/script>/,
    )[1],
  );
  if (kind === "template") {
    for (const value of [
      excerpt,
      sentinel,
      exhibit?.data,
      exhibit?.sha256,
      exhibit?.sourceSha256,
      exhibit?.locator,
      exhibit?.captureMethod,
    ].filter(Boolean)) {
      assert(
        !html.includes(value),
        "Template raw bytes retain source preview content/provenance",
      );
      assert(
        !JSON.stringify(inert).includes(value),
        "Template inert state retains source preview content/provenance",
      );
    }
  } else {
    assert(html.includes(excerpt), "Client retains exact source quotation");
    if (exhibit)
      assert(
        html.includes(exhibit.data),
        "Client retains permitted actual source pixels",
      );
  }
}
try {
  for (const fixture of fixtures) {
    await matrix(fixture.path, fixture, "working");
    await attempt(`${fixture.name}-save-and-exports`, async () => {
      const page = await open(fixture.path, 1440, 900);
      let saved;
      try {
        await navigate(page, 1, false);
        await page.locator("#mode-toggle").click();
        saved = await download(page, "#ld-save", `${fixture.name}-saved.html`);
      } finally {
        await page.close();
      }
      const reopened = await open(saved, 1440, 900);
      try {
        assert.equal(
          (await state(reopened)).review.location,
          1,
          "Save/reopen preserves issue location",
        );
        await reopened.reload();
        await settle(reopened);
        await inspect(
          reopened,
          (await state(reopened)).composition.sections[1].issueLayout,
          false,
          `${fixture.name}-saved-reload`,
        );
        await exerciseTargets(reopened, false, `${fixture.name}-saved-reload`);
      } finally {
        await reopened.close();
      }
      for (const kind of ["client", "template"]) {
        const exportPage = await open(saved, 1440, 900);
        let exported;
        try {
          exported = await download(
            exportPage,
            kind === "client" ? "#export-html" : "#export-template",
            `${fixture.name}-${kind}.html`,
          );
        } finally {
          await exportPage.close();
        }
        if (fixture.sourcePreview)
          checkPreviewPrivacy(readFileSync(exported, "utf8"), kind);
        await matrix(exported, fixture, kind);
      }
    });
  }
  assert.deepEqual(errors, [], "No browser runtime errors");
  assert.deepEqual(
    requests,
    [],
    "Standalone issue fixtures make no external requests",
  );
} catch (error) {
  failures.push({ label: "completion", error: error.stack || String(error) });
} finally {
  await browser.close();
  writeFileSync(
    join(out, "results.json"),
    JSON.stringify(
      {
        failures,
        errors,
        warnings,
        sourceImageTested: Boolean(exhibit),
        requests,
        downloads,
        measurements,
        interactions,
      },
      null,
      2,
    ),
  );
  writeFileSync(
    join(out, "report.md"),
    [
      `# Issue-layout browser regression: ${failures.length ? "FAIL" : "PASS"}`,
      "",
      "QA blueprints only — not completed legal analysis. Canonical slide-brief and diligence-report plans plus a supplied-source-preview variant. Original private design references and their content/assets are not included.",
      "",
      `${measurements.length} measured issue states; ${interactions.filter((entry) => entry.expected).length} real pointer/keyboard popup activations; ${interactions.filter((entry) => entry.affordance).length} neutral hover/focus checks; ${downloads.length} actual browser downloads. Runtime errors: ${errors.length}. External requests: ${requests.length}.`,
      `Optional supplied source image: ${exhibit ? "TESTED (explicit LEGALDESIGN_ISSUE_EXHIBIT)" : "NOT TESTED (no LEGALDESIGN_ISSUE_EXHIBIT supplied)"}.`,
      "",
      "Working, Save/reload, client and template copies are opened offline. Viewports: 1280×800, 1440×900, 2560×1440 and 390×844, both themes. Checks cover typed three-card analysis/support slots, first painted layout, stable type, track filling, source image aspect/native size, neutral hover/focus borders, popup targeting, Escape/focus/reader restoration, and template preview privacy in raw bytes and inert state.",
      "",
      ...warnings.map((warning) => `Limitation: ${warning}`),
      "",
      failures.length
        ? failures
            .map(({ label, error }) => `- ${label}: ${error.split("\n")[0]}`)
            .join("\n")
        : "All automated checks passed. Screenshots require the accompanying independent visual review; geometry alone is not visual approval.",
      "",
      "All browser contexts closed; no server or user browser tab was opened. Only the new repository test file was edited by this regression author.",
      "",
    ].join("\n"),
  );
}
console.log(
  `${failures.length ? "FAIL" : "PASS"}: issue-layout evidence ${out}`,
);
assert.equal(failures.length, 0, JSON.stringify(failures, null, 2));
