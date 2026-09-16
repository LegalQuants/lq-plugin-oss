import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { chromium } from "@playwright/test";

const repo = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const out = mkdtempSync(join(tmpdir(), "legaldesign-hub-direction-"));
const components = readFileSync(
  process.env.LEGALDESIGN_HUB_COMPONENTS ||
    join(repo, "packages/legaldesign/runtime/components.js"),
  "utf8",
);
const runtime = readFileSync(
  join(repo, "packages/legaldesign/runtime/runtime.js"),
  "utf8",
);
const params = {
  centre: "Service deployment",
  spokes: [
    {
      title: "Carrier partners",
      edge: "provide spectrum routes",
      detail: "e-core",
    },
    {
      title: "Device makers",
      edge: "enable compatibility",
      detail: "e-detail",
    },
    {
      title: "Country regulators",
      edge: "authorize service",
      detail: "e-action",
    },
    { title: "Network readiness", edge: "enables launch", detail: "e-core" },
  ],
};
const browser = await chromium.launch({
  headless: true,
  executablePath: [
    chromium.executablePath(),
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  ].find(existsSync),
});
const measurements = [];
const faults = [];

async function geometry(svg, toward, label) {
  const data = await svg.evaluate((node) => {
    const narrow = node.classList.contains("narrow-viz");
    const boxes = [...node.querySelectorAll("rect.box")].map((rect) => ({
      x: Number(rect.getAttribute("x")),
      y: Number(rect.getAttribute("y")),
      width: Number(rect.getAttribute("width")),
      height: Number(rect.getAttribute("height")),
    }));
    const paths = [...node.querySelectorAll("path.line,path.hair")];
    const heads = paths.filter((p) =>
      /^M[-\d.]+ [-\d.]+L[-\d.]+ [-\d.]+L[-\d.]+ [-\d.]+$/.test(
        p.getAttribute("d"),
      ),
    );
    const arrows = heads.map((p) => {
      const n = p
        .getAttribute("d")
        .match(/-?\d+(?:\.\d+)?/g)
        .map(Number);
      return { tipX: n[2], tipY: n[3], baseX: (n[0] + n[4]) / 2 };
    });
    const busX = narrow ? 200 : 236;
    const startY = narrow
      ? boxes[0].y + boxes[0].height
      : boxes[1].y + boxes[1].height / 2;
    const endY = boxes.at(-1).y + boxes.at(-1).height / 2;
    const points = paths
      .filter((p) => p.getAttribute("d").includes("V"))
      .flatMap((p) => {
        const steps = Math.ceil(p.getTotalLength() * 2);
        return Array.from({ length: steps + 1 }, (_, i) => {
          const point = p.getPointAtLength((p.getTotalLength() * i) / steps);
          return { x: point.x, y: point.y };
        });
      });
    const gaps = [];
    for (let y = startY; y <= endY; y += 2) {
      if (!points.some((p) => Math.hypot(p.x - busX, p.y - y) < 0.8))
        gaps.push(y);
    }
    return {
      narrow,
      arrows,
      boxes,
      gaps,
      labels: [...node.querySelectorAll("text.edge")].map((n) => n.textContent),
    };
  });
  measurements.push({ label, toward, ...data });
  assert.equal(
    data.arrows.length,
    data.boxes.length - 1,
    `${label}: one arrow per satellite`,
  );
  for (const arrow of data.arrows) {
    assert.equal(
      Math.sign(arrow.tipX - arrow.baseX),
      toward === "centre" ? -1 : 1,
      `${label}: actual arrowhead direction`,
    );
    const satellite = data.boxes.find(
      (box, i) => i > 0 && Math.abs(box.y + box.height / 2 - arrow.tipY) < 0.01,
    );
    assert(satellite, `${label}: arrow aligns to one satellite`);
    assert(
      arrow.tipX < satellite.x,
      `${label}: connector lies between satellite and shared center bus`,
    );
  }
  assert.deepEqual(
    data.gaps,
    [],
    `${label}: every satellite has a continuous bus to the center`,
  );
  assert.equal(
    data.labels.length,
    params.spokes.length,
    `${label}: preserve relationship labels`,
  );
  return data;
}

async function open(file, width) {
  const page = await browser.newPage({
    viewport: { width, height: width < 760 ? 932 : 1100 },
    hasTouch: width < 760,
  });
  page.on("pageerror", (e) => faults.push(e.message));
  await page.goto(pathToFileURL(file).href);
  await page.waitForFunction(
    () => document.documentElement.dataset.legaldesignReady === "true",
  );
  return page;
}

async function resizeGeometry(page, toward, label) {
  for (const width of [1440, 1200, 1440]) {
    await page.setViewportSize({ width, height: 1100 });
    await page.evaluate(
      () =>
        new Promise((resolve) =>
          requestAnimationFrame(() => requestAnimationFrame(resolve)),
        ),
    );
    const g = await geometry(
      page.locator(".ld-page-approach svg").first(),
      toward,
      `${label}-resize-${width}`,
    );
    assert.equal(
      g.narrow,
      width === 1200,
      `${label}: responsive geometry updates immediately after genuine resize`,
    );
  }
}

try {
  // Direct renderer probes prove arrow geometry and topology independently of
  // generated captions or data-direction attributes.
  const page = await browser.newPage({
    viewport: { width: 1000, height: 900 },
  });
  await page.setContent(
    `<style>:root{--ink:#111;--card:#fff;--muted:#555;--line-strong:#aaa;--sans:Arial,sans-serif}body{font:16px sans-serif}svg{width:auto;max-width:880px;height:600px}.line,.hair{fill:none;stroke:black}.box{fill:white;stroke:black}</style><main></main>`,
  );
  await page.addScriptTag({ content: components });
  for (const toward of ["centre", "satellites"]) {
    for (const narrow of [false, true]) {
      await page.evaluate(
        ({ params, toward, narrow }) => {
          document.querySelector("main").innerHTML = LegalDesign.render(
            "hub",
            { ...params, toward },
            { narrow },
          );
        },
        { params, toward, narrow },
      );
      await page.screenshot({
        path: join(out, `direct-${toward}-${narrow ? "narrow" : "wide"}.png`),
      });
      await geometry(page.locator("svg"), toward, `direct-${toward}-${narrow}`);
    }
  }
  await page.close();

  for (const toward of ["centre", "satellites"]) {
    const plan = JSON.parse(
      readFileSync(
        join(repo, "packages/legaldesign/templates/method-map.plan.json"),
        "utf8",
      ),
    );
    const figure = plan.units.find((unit) => unit.kind === "figure");
    figure.relationship = "convergence";
    figure.candidates = ["hub"];
    figure.variants.a.component = "hub";
    figure.variants.a.params = { ...params, toward };
    plan.composition.sections[0].layout.placements.find(
      (placement) => placement.unitId === figure.id,
    ).span = 8;
    const planPath = join(out, `${toward}.plan.json`),
      html = join(out, `${toward}.html`);
    writeFileSync(planPath, JSON.stringify(plan));
    const build = spawnSync(
      process.env.LEGALDESIGN_PYTHON || "python3",
      [
        "skills/core/legaldesign/scripts/scaffold.py",
        "compose",
        "--plan",
        planPath,
        "--spec-output",
        join(out, `${toward}.spec.json`),
        "--output",
        html,
        "--artifact-id",
        `hub-${toward}`,
      ],
      { cwd: repo, encoding: "utf8" },
    );
    assert.equal(build.status, 0, build.stdout + build.stderr);
    let artifact = readFileSync(html, "utf8");
    for (const [id, script] of [
      ["ld-components", components],
      ["ld-runtime", runtime],
    ]) {
      const pattern = new RegExp(
        `(<script id="${id}">)[\\s\\S]*?(<\\/script>)`,
      );
      assert(pattern.test(artifact));
      artifact = artifact.replace(
        pattern,
        (_, start, end) => start + script + end,
      );
    }
    writeFileSync(html, artifact);
    const desktop = await open(html, 1440);
    await resizeGeometry(desktop, toward, "working");
    for (const theme of ["light", "dark"]) {
      if ((await desktop.locator("html").getAttribute("data-theme")) !== theme)
        await desktop.locator("#theme-toggle").click();
      await geometry(
        desktop.locator('[data-unit="workflow"] svg'),
        toward,
        `${toward}-desktop-${theme}`,
      );
      await desktop.screenshot({
        path: join(out, `${toward}-desktop-${theme}.png`),
      });
    }
    assert(
      (
        await desktop.evaluate(() =>
          LegalDesign.checkPageFit({ allPages: true }),
        )
      ).valid,
    );
    const exported = [];
    for (const [frame, width] of [
      ["wide", 1440],
      ["narrow", 1200],
    ]) {
      await desktop.setViewportSize({ width, height: 1100 });
      // Capture each authored export geometry from a cold, fitted viewport.
      // Resize scheduling is covered separately from component semantics.
      await desktop.reload();
      await desktop.waitForFunction(
        () => document.documentElement.dataset.legaldesignReady === "true",
      );
      await desktop.evaluate(
        () =>
          new Promise((resolve) =>
            requestAnimationFrame(() => requestAnimationFrame(resolve)),
          ),
      );
      const g = await geometry(
        desktop.locator('[data-unit="workflow"] svg'),
        toward,
        `${toward}-export-${frame}`,
      );
      assert.equal(
        g.narrow,
        frame === "narrow",
        "export fixture genuinely exercises each geometry",
      );
      assert(
        (
          await desktop.evaluate(() =>
            LegalDesign.checkPageFit({ allPages: true }),
          )
        ).valid,
      );
      for (const type of ["client", "template"]) {
        const path = join(out, `${toward}-${frame}-${type}.html`);
        writeFileSync(
          path,
          await desktop.evaluate(
            (type) =>
              type === "client"
                ? LegalDesign.exportHTML(false)
                : LegalDesign.exportTemplate(false),
            type,
          ),
        );
        exported.push([`${frame}-${type}`, path]);
      }
    }
    await desktop.close();
    for (const [surface, file] of [["working", html], ...exported]) {
      if (surface.endsWith("template")) {
        const reopened = await open(file, 1440);
        await resizeGeometry(reopened, toward, surface);
        await reopened.close();
      }
      for (const width of [390, 430]) {
        const phone = await open(file, width);
        await phone.locator("#ld-page-reader").waitFor({ state: "visible" });
        for (const theme of ["light", "dark"]) {
          if (
            (await phone.locator("html").getAttribute("data-theme")) !== theme
          ) {
            await phone.keyboard.press("Escape");
            await phone.locator("#theme-toggle").click();
            await phone.locator("#ld-read-page").click();
          }
          const svg = phone.locator("#ld-page-reader svg").first();
          const g = await geometry(
            svg,
            toward,
            `${toward}-${surface}-${width}-${theme}-reader`,
          );
          // Exports preserve the authored SVG so user geometry is not lost.
          // Working documents recompose the phone reader with narrow geometry.
          assert.equal(
            g.narrow,
            surface === "working" ||
              surface.endsWith("template") ||
              surface.startsWith("narrow-"),
            "reader respects responsive or preserved geometry",
          );
          await phone.screenshot({
            path: join(
              out,
              `${toward}-${surface}-${width}-${theme}-reader.png`,
            ),
          });
        }
        const target = phone
          .locator("#ld-page-reader svg [data-detail]")
          .first();
        const popup = phone.locator(
          `[id="${await target.getAttribute("data-detail")}"]`,
        );
        await target.click();
        await popup.waitFor({ state: "visible" });
        await phone.keyboard.press("Escape");
        assert(await phone.locator("#ld-page-reader").isVisible());
        await phone.keyboard.press("Escape");
        await geometry(
          phone.locator(".ld-page-approach svg").first(),
          toward,
          `${toward}-${surface}-${width}-canvas`,
        );
        await phone.close();
      }
    }
  }
  // A figure initially hidden behind the overview must be rendered against its
  // visible host width on first navigation, not the zero-width hidden host.
  const multiPlan = JSON.parse(
    readFileSync(
      join(repo, "packages/legaldesign/templates/slide-brief.plan.json"),
      "utf8",
    ),
  );
  const multiFigure = multiPlan.units.find((unit) => unit.id === "flow");
  multiFigure.relationship = "convergence";
  multiFigure.candidates = ["hub"];
  multiFigure.variants.a.component = "hub";
  multiFigure.variants.a.params = { ...params, toward: "centre" };
  const issueSection = multiPlan.composition.sections.find(
    (section) => section.id === "condition",
  );
  assert(issueSection.issueLayout.supportUnitIds.includes("flow"));
  assert.equal(
    issueSection.layout,
    undefined,
    "recipe owns derived coordinates",
  );
  const multiPlanPath = join(out, "multipage.plan.json"),
    recipeHtml = join(out, "multipage-recipe.html"),
    multiHtml = join(out, "multipage.html");
  writeFileSync(multiPlanPath, JSON.stringify(multiPlan));
  const multiBuild = spawnSync(
    process.env.LEGALDESIGN_PYTHON || "python3",
    [
      "skills/core/legaldesign/scripts/scaffold.py",
      "compose",
      "--plan",
      multiPlanPath,
      "--spec-output",
      join(out, "multipage.spec.json"),
      "--output",
      recipeHtml,
      "--artifact-id",
      "hub-first-navigation",
    ],
    { cwd: repo, encoding: "utf8" },
  );
  assert.equal(multiBuild.status, 0, multiBuild.stdout + multiBuild.stderr);
  // Exercise the shipping typed recipe before adapting a separate ordinary
  // composition to cross the wide breakpoint. A half-width support column is
  // intentionally narrow even on desktop; it must not be given fake coordinates.
  const normalized = JSON.parse(
    readFileSync(join(out, "multipage.spec.json"), "utf8"),
  );
  const normalizedSection = normalized.composition.sections.find(
    (section) => section.id === "condition",
  );
  assert.equal(
    normalizedSection.layout.placements.find(
      (placement) => placement.unitId === "flow",
    ).span,
    6,
  );
  const recipePage = await open(recipeHtml, 1440);
  await recipePage.locator('[data-unit="topic-1"]').click();
  const recipeGeometry = await geometry(
    recipePage.locator('[data-unit="flow"] svg'),
    "centre",
    "typed-recipe-first-navigation",
  );
  assert.equal(recipeGeometry.narrow, true);
  await recipePage.setViewportSize({ width: 1200, height: 1100 });
  await recipePage.setViewportSize({ width: 1440, height: 1100 });
  await recipePage.locator('[data-report-section="0"]').click();
  await recipePage.locator('[data-unit="topic-1"]').click();
  const recipeReturn = await geometry(
    recipePage.locator('[data-unit="flow"] svg'),
    "centre",
    "typed-recipe-resize-return",
  );
  assert.deepEqual(recipeReturn.boxes, recipeGeometry.boxes);
  assert.deepEqual(recipeReturn.arrows, recipeGeometry.arrows);
  await recipePage.close();

  // A normal, non-recipe detail page still needs the original wide -> narrow ->
  // wide hidden-page regression. Keep all template units and their content.
  const recipe = normalizedSection.issueLayout;
  delete normalizedSection.issueLayout;
  const analysis = [
    recipe.findingUnitId,
    recipe.implicationUnitId,
    recipe.actionUnitId,
  ];
  for (const placement of normalizedSection.layout.placements) {
    delete placement.rowSpan;
    if (analysis.includes(placement.unitId)) {
      Object.assign(placement, {
        row: 2,
        column: 1 + analysis.indexOf(placement.unitId) * 4,
        span: 4,
      });
    } else if (placement.unitId === "flow") {
      Object.assign(placement, { row: 3, column: 1, span: 10 });
    } else if (placement.row > 1) placement.row = 4;
  }
  writeFileSync(multiPlanPath, JSON.stringify(normalized));
  const wideBuild = spawnSync(
    process.env.LEGALDESIGN_PYTHON || "python3",
    [
      "skills/core/legaldesign/scripts/scaffold.py",
      "compose",
      "--plan",
      multiPlanPath,
      "--spec-output",
      join(out, "multipage-wide.spec.json"),
      "--output",
      multiHtml,
      "--artifact-id",
      "hub-first-navigation-wide",
    ],
    { cwd: repo, encoding: "utf8" },
  );
  assert.equal(wideBuild.status, 0, wideBuild.stdout + wideBuild.stderr);
  let multiArtifact = readFileSync(multiHtml, "utf8");
  for (const [id, script] of [
    ["ld-components", components],
    ["ld-runtime", runtime],
  ]) {
    const pattern = new RegExp(`(<script id="${id}">)[\\s\\S]*?(<\\/script>)`);
    assert(pattern.test(multiArtifact));
    multiArtifact = multiArtifact.replace(
      pattern,
      (_, start, end) => start + script + end,
    );
  }
  writeFileSync(multiHtml, multiArtifact);
  const multi = await open(multiHtml, 1440);
  const first = {};
  for (const width of [1440, 1200]) {
    const cold = await open(multiHtml, width);
    await cold.locator('[data-unit="topic-1"]').click();
    const g = await geometry(
      cold.locator('[data-unit="flow"] svg'),
      "centre",
      `multipage-first-navigation-${width}`,
    );
    assert.equal(
      g.narrow,
      width === 1200,
      "first navigation uses current visible width",
    );
    first[width] = g;
    await cold.screenshot({
      path: join(out, `multipage-first-navigation-${width}.png`),
    });
    await cold.close();
  }
  await multi.locator('[data-unit="topic-1"]').click();
  for (const width of [1200, 1440]) {
    await multi.setViewportSize({ width, height: 1100 });
    await multi.evaluate(
      () =>
        new Promise((resolve) =>
          requestAnimationFrame(() => requestAnimationFrame(resolve)),
        ),
    );
    const g = await geometry(
      multi.locator('[data-unit="flow"] svg'),
      "centre",
      `multipage-resize-return-${width}`,
    );
    assert.deepEqual(
      g.boxes,
      first[width].boxes,
      "resize-return matches first navigation at the same width",
    );
    assert.deepEqual(g.arrows, first[width].arrows);
    await multi.locator('[data-report-section="0"]').click();
    await multi.locator('[data-unit="topic-1"]').click();
    const returned = await geometry(
      multi.locator('[data-unit="flow"] svg'),
      "centre",
      `multipage-topic-return-${width}`,
    );
    assert.deepEqual(
      returned.boxes,
      first[width].boxes,
      "hiding and showing preserves correct current-width geometry",
    );
  }
  await multi.locator("#mode-toggle").click();
  const label = multi.locator(
    '[data-unit="flow"] svg text[data-param-path="/centre"]',
  );
  await label.dblclick();
  await multi.locator("#ld-svg-text-editor").fill("Edited deployment");
  await multi.locator("#ld-svg-text-editor").press("Enter");
  const originalInk = await label.evaluate(
    (node) => getComputedStyle(node).fill,
  );
  await multi.locator("#editor-text-palette").click();
  await multi.locator('#ld-color-palette [data-color-token="red"]').click();
  const ink = await label.evaluate((node) => getComputedStyle(node).fill);
  assert.notEqual(ink, originalInk, "explicit text paint applied");
  await multi.locator("#mode-toggle").click();
  await multi.locator('[data-report-section="0"]').click();
  await multi.locator('[data-unit="topic-1"]').click();
  assert.equal(await label.textContent(), "Edited deployment");
  assert.equal(
    await label.evaluate((node) => getComputedStyle(node).fill),
    ink,
    "visible-section rerender preserves user paint",
  );
  assert.equal(
    await multi.evaluate(
      () => LegalDesign.state().units.flow.variants.a.params.centre,
    ),
    "Edited deployment",
  );
  await multi.close();
  assert.deepEqual(faults, []);
  console.log(
    `PASS: ${measurements.length} hub geometry states; wide/narrow directions, continuous bus, phone reader/canvas and client/template exports. Evidence: ${out}`,
  );
} finally {
  writeFileSync(
    join(out, "measurements.json"),
    JSON.stringify(measurements, null, 2),
  );
  await browser.close();
  console.log(`Hub evidence: ${out}`);
}
