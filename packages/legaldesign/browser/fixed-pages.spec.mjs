import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { homedir, tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { chromium } from "@playwright/test";

const repo = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const runtimeDir = join(repo, "packages/legaldesign/runtime");
const temp = mkdtempSync(join(tmpdir(), "legaldesign-fixed-pages-"));
const planPath = join(
  repo,
  "packages/legaldesign/fixtures/case-06-novel-composition/plan.json",
);

function fixture(form = "one-page") {
  const plan = JSON.parse(readFileSync(planPath, "utf8"));
  plan.brief.form = form;
  const source = join(temp, form + ".json");
  const html = join(temp, form + ".html");
  writeFileSync(source, JSON.stringify(plan));
  const result = spawnSync(
    process.env.LEGALDESIGN_PYTHON || "python3",
    [
      join(repo, "skills/core/legaldesign/scripts/scaffold.py"),
      "compose",
      "--plan",
      source,
      "--spec-output",
      join(temp, form + ".spec.json"),
      "--output",
      html,
      "--artifact-id",
      "fixed-page-" + form,
    ],
    { cwd: repo, encoding: "utf8" },
  );
  assert.equal(result.status, 0, result.stderr + result.stdout);
  writeFileSync(html, injectRuntime(readFileSync(html, "utf8")));
  return html;
}

function injectRuntime(html) {
  const block = `<!-- legaldesign:runtime --><style id="ld-tokens">${readFileSync(join(runtimeDir, "tokens.css"), "utf8")}</style><script id="ld-components">${readFileSync(join(runtimeDir, "components.js"), "utf8")}</script><script id="ld-runtime">${readFileSync(join(runtimeDir, "runtime.js"), "utf8")}</script><!-- /legaldesign:runtime -->`;
  return html.replace(
    /<!-- legaldesign:runtime -->[\s\S]*?<!-- \/legaldesign:runtime -->/,
    () => block,
  );
}

async function readBounds(page) {
  return page.evaluate(() => {
    const stage = [...document.querySelectorAll(".ld-fixed-page")].find(
      (n) => !n.closest("[hidden]") && getComputedStyle(n).display !== "none",
    );
    const b = stage.getBoundingClientRect();
    const fit = LegalDesign.checkPageFit();
    return {
      ...fit,
      rect: {
        x: b.x,
        y: b.y,
        width: b.width,
        height: b.height,
        right: b.right,
        bottom: b.bottom,
      },
      viewport: { width: innerWidth, height: innerHeight },
      scroll: {
        width: document.documentElement.scrollWidth,
        height: document.documentElement.scrollHeight,
      },
      heading: getComputedStyle(stage.querySelector("h1,h2,h3") || stage)
        .fontSize,
      frame: stage.querySelector("svg")?.getAttribute("data-frame"),
      units: [...stage.querySelectorAll(".ld-unit")]
        .filter((n) => !n.closest("[hidden]"))
        .map((n) => ({
          id: n.dataset.unit,
          top: n.getBoundingClientRect().top - b.top,
          bottom: n.getBoundingClientRect().bottom - b.top,
          height: n.getBoundingClientRect().height,
        })),
    };
  });
}

export async function runFixedPageSuite() {
  const executable = [
    chromium.executablePath(),
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  ].find(existsSync);
  const browser = await chromium.launch({
    headless: true,
    executablePath: executable,
  });
  const single = fixture();
  const report = fixture("report");
  const walkthrough = fixture("walkthrough");
  try {
    for (const [width, height] of [
      [1920, 900],
      [1440, 1100],
      [390, 844],
    ]) {
      for (const name of [
        "method-map",
        "stacked-explainer",
        "diligence-report",
        "slide-brief",
      ]) {
        const file = join(temp, name + ".html");
        writeFileSync(
          file,
          injectRuntime(
            readFileSync(
              join(repo, "skills/core/legaldesign/assets", name + ".html"),
              "utf8",
            ),
          ),
        );
        const page = await browser.newPage({ viewport: { width, height } });
        page.on("pageerror", (e) => console.error(e.message));
        await page.goto(pathToFileURL(file).href);
        await page.waitForTimeout(200);
        assert(
          (
            await page.evaluate(() =>
              LegalDesign.checkPageFit({ allPages: true }),
            )
          ).valid,
          `${name} ${width}: every legacy output page must fit: ${JSON.stringify(await page.evaluate(() => LegalDesign.lastPageFitIssues))}`,
        );
        assert.equal((await readBounds(page)).visiblePages, 1);
        if (width === 1440) {
          for (const kind of ["HTML", "Template"]) {
            const exported = await page.evaluate(
              (kind) => LegalDesign["export" + kind](false),
              kind,
            );
            const reopenedPath = join(temp, `${name}-${kind}.html`);
            writeFileSync(reopenedPath, exported);
            const reopened = await browser.newPage({
              viewport: { width, height },
            });
            await reopened.goto(pathToFileURL(reopenedPath).href);
            await reopened.waitForTimeout(150);
            assert(
              (
                await reopened.evaluate(() =>
                  LegalDesign.checkPageFit({ allPages: true }),
                )
              ).valid,
              `${name}: ${kind} keeps every page within the frame: ${JSON.stringify(await reopened.evaluate(() => LegalDesign.lastPageFitIssues))}`,
            );
            if (name === "diligence-report") {
              assert.equal(
                await reopened.locator(".ld-reference-evidence").count(),
                3,
              );
              const missing = await reopened.evaluate(() =>
                [
                  ...document.querySelectorAll(
                    ".evidence-panel [data-evidence]",
                  ),
                ]
                  .map((n) => n.dataset.evidence)
                  .filter((id) => !document.getElementById(id)),
              );
              assert.deepEqual(
                missing,
                [],
                "nested source popups survive reference-panel export",
              );
            }
            await reopened.close();
          }
        }
        if (name === "method-map" || name === "stacked-explainer") {
          if (!(await page.locator('[data-report-section="1"]').isVisible()))
            await page.locator("[data-index-toggle]").click();
          await page.locator('[data-report-section="1"]').click();
          assert.equal((await readBounds(page)).visiblePages, 1);
          assert.equal(
            await page
              .locator(".ld-reference-page:not([hidden]) .ld-card")
              .count(),
            4,
            "repagination keeps all detailed cards",
          );
        }
        await page.close();
      }
    }
    console.log(
      "PASS all reference pages fit desktop and phone; overview/detail repagination preserves every card",
    );
    for (const [width, height] of [
      [1920, 900],
      [1440, 1100],
      [1280, 720],
      [390, 844],
      [844, 390],
    ]) {
      const context = await browser.newContext({ viewport: { width, height } });
      const page = await context.newPage();
      page.on("pageerror", (error) =>
        console.error("PAGE ERROR:", error.message),
      );
      await page.goto(pathToFileURL(single).href);
      await page.waitForFunction(() =>
        document.documentElement.hasAttribute("data-fixed-pages"),
      );
      await page.waitForTimeout(100);
      for (const variant of ["a", "b"]) {
        await page.locator(`[data-select-approach="${variant}"]`).click();
        await page.waitForTimeout(80);
        const bounds = await readBounds(page);
        assert.equal(
          bounds.valid,
          true,
          JSON.stringify({ variant, width, height, bounds }),
        );
        assert.equal(bounds.visiblePages, 1);
        assert.equal(bounds.ratio, "adaptive");
        assert.equal(bounds.authoringReference, "4:3");
        assert(
          Math.abs(bounds.rect.x - 12) < 1,
          "page is anchored to available left edge rather than centered in letterboxing",
        );
        assert(
          Math.abs(bounds.rect.right - (width - 12)) < 1,
          "page uses full available width",
        );
        assert(
          Math.abs(bounds.rect.bottom - (height - 64)) < 1,
          "page uses full available height above reader corner",
        );
        assert(bounds.rect.x >= 0 && bounds.rect.y >= 0);
        assert(
          bounds.rect.right <= width + 1 && bounds.rect.bottom <= height + 1,
        );
        assert(bounds.scroll.width <= width && bounds.scroll.height <= height);
        assert.equal(
          bounds.heading,
          "32px",
          "intrinsic heading size does not shrink on phone",
        );
        assert.equal(
          bounds.frame,
          "wide",
          "phone fits complete wide diagram, not tall stacking",
        );
        const book = page.getByRole("button", {
          name: "Read page",
          exact: true,
        });
        assert(await book.isVisible());
        const bookBox = await book.boundingBox();
        assert(bookBox.width >= 44 && bookBox.height >= 44);
        assert.equal(await book.locator("svg").count(), 1);
        assert.equal(
          (await book.textContent()).trim(),
          "",
          "reader uses a book icon rather than a text button",
        );
      }
      // Detail remains independently readable, not a scaled child of the page.
      await page.locator('[data-select-approach="a"]').click();
      await page
        .locator('.ld-fixed-page:not([hidden]) [data-detail="e-ask"]')
        .first()
        .click();
      const popup = page.locator(".pop:visible");
      assert(await popup.isVisible());
      assert(await popup.evaluate((n) => !n.closest(".ld-fixed-page")));
      await page.locator(".pop:visible .ld-popup-close").click();
      await page.locator('[data-select-approach="b"]').click();
      await page.locator("#theme-toggle").click();
      await page.locator('[data-select-approach="a"]').click();
      await page.locator('[data-select-approach="b"]').click();
      await page.evaluate(
        () =>
          new Promise((resolve) =>
            requestAnimationFrame(() => requestAnimationFrame(resolve)),
          ),
      );
      const titleInk = await page
        .locator('[data-unit="b-title"] h1')
        .evaluate((n) => {
          const range = document.createRange();
          range.selectNodeContents(n);
          const rect = range.getBoundingClientRect();
          const style = getComputedStyle(n);
          return {
            width: rect.width,
            height: rect.height,
            color: style.color,
            opacity: style.opacity,
            visibility: style.visibility,
          };
        });
      assert(
        titleInk.width > 10 &&
          titleInk.height > 5 &&
          titleInk.opacity !== "0" &&
          titleInk.visibility === "visible",
        JSON.stringify(titleInk),
      );
      assert.notEqual(
        titleInk.color,
        "rgb(0, 0, 0)",
        "dark title ink remains visible after stable A/B/theme/popup cycles",
      );
      await page.locator('[data-select-approach="a"]').click();
      if (width < 760 || height < 560) {
        // Exercise real SVG resource references, not a vacuous no-ID diagram.
        await page.evaluate(() => {
          const summary = document.querySelector('[data-unit="a-summary"]');
          summary.setAttribute(
            "data-detail",
            document.querySelector("#popup-scrim .pop").id,
          );
          summary.setAttribute("data-kind", "text");
          const svg = document.querySelector('[data-unit="a-flow"] svg');
          const ns = "http://www.w3.org/2000/svg";
          const defs = document.createElementNS(ns, "defs");
          defs.innerHTML =
            '<marker id="reader-probe-marker" markerWidth="6" markerHeight="6" refX="3" refY="3" orient="auto"><path d="M0 0L6 3L0 6Z"/></marker><clipPath id="reader-probe-clip"><rect width="2000" height="2000"/></clipPath>';
          svg.prepend(defs);
          const line = [...svg.querySelectorAll("path")].find(
            (n) => !n.closest("defs"),
          );
          line.setAttribute("marker-end", "url(#reader-probe-marker)");
          line.setAttribute("clip-path", "url(#reader-probe-clip)");
          svg
            .closest(".ld-diagram")
            .setAttribute("data-editor-preserve-dom", "");
        });
        const sourceText = await page
          .locator('[data-approach="a"] [data-unit="a-summary"] p')
          .textContent();
        const stateBefore = await page
          .locator("#legaldesign-state")
          .textContent();
        await page.locator("#ld-read-page").click();
        const reader = page.locator("#ld-page-reader");
        assert(await reader.isVisible());
        assert((await reader.textContent()).includes(sourceText));
        assert.equal(await reader.locator(".ld-reader-popup-text").count(), 1);
        assert.equal(
          await reader
            .locator(".ld-reader-popup-text")
            .evaluate((node) => getComputedStyle(node).textDecorationLine),
          "underline",
          "standalone popup text keeps its link affordance in the reader",
        );
        assert.equal(
          await reader
            .locator("[data-unit],[data-editable],[contenteditable]")
            .count(),
          0,
        );
        assert(
          await reader
            .locator("[id]")
            .evaluateAll((nodes) =>
              nodes.every(
                (n) =>
                  n instanceof SVGElement && n.id.startsWith("ld-reader-svg-"),
              ),
            ),
          "reader has only remapped SVG resource IDs",
        );
        assert.equal(await reader.locator("marker").count(), 1);
        assert.equal(await reader.locator("clipPath").count(), 1);
        assert(
          await reader
            .locator("svg")
            .evaluateAll((svgs) =>
              svgs.every((svg) =>
                [...svg.querySelectorAll("*")].every((n) =>
                  [...n.attributes].every((a) =>
                    [...a.value.matchAll(/url\(#([^)]*)\)/g)].every((m) =>
                      svg.querySelector('[id="' + m[1] + '"]'),
                    ),
                  ),
                ),
              ),
            ),
          "reader marker and clip-path references resolve inside their SVG",
        );
        assert.equal(
          await reader.locator(".ld-reader-unit").count(),
          4,
          "every visible source unit is represented",
        );
        assert.equal(
          await reader
            .locator("p")
            .first()
            .evaluate((n) => getComputedStyle(n).fontSize),
          "18px",
        );
        assert(
          await reader
            .locator("svg")
            .evaluate((svg) =>
              [...svg.querySelectorAll("text")].every(
                (n) =>
                  (parseFloat(getComputedStyle(n).fontSize) *
                    svg.getBoundingClientRect().width) /
                    svg.viewBox.baseVal.width >=
                  10.99,
              ),
            ),
          "reader diagram labels retain at least 11 screen pixels",
        );
        assert.equal(
          await page.locator("#legaldesign-state").textContent(),
          stateBefore,
          "read mode cannot mutate portable state",
        );
        assert(
          await page.evaluate(
            () => document.documentElement.scrollHeight === innerHeight,
          ),
        );
        const exported = await page.evaluate(() =>
          LegalDesign.exportHTML(false),
        );
        assert.equal(
          await page.evaluate(
            (html) =>
              new DOMParser()
                .parseFromString(html, "text/html")
                .getElementById("ld-page-reader"),
            exported,
          ),
          null,
          "transient reader copy excluded from exports",
        );
        await reader.locator(".ld-popup-close").click();
        assert.equal(
          await page.evaluate(() => document.activeElement.id),
          "ld-read-page",
        );
      }
      await context.close();
    }
    console.log(
      "PASS adaptive A/B pages fill desktop, short laptop, portrait and landscape phone; book reader remains accessible",
    );

    for (const source of [report, walkthrough]) {
      const context = await browser.newContext({
        viewport: { width: 1280, height: 800 },
        acceptDownloads: true,
      });
      const page = await context.newPage();
      await page.goto(pathToFileURL(source).href);
      await page.waitForFunction(
        () =>
          document.documentElement.getAttribute("data-legaldesign-ready") ===
          "true",
      );
      await page.locator("[data-walkthrough-next]").click();
      assert.equal((await readBounds(page)).visiblePages, 1);
      assert.equal(
        await page
          .locator('[data-report-section][aria-current="true"]')
          .getAttribute("data-report-section"),
        "1",
      );
      for (const kind of ["Save", "HTML", "Template"]) {
        let html;
        if (kind === "Save") {
          const downloaded = page.waitForEvent("download");
          await page.evaluate(() => {
            window.showSaveFilePicker = undefined;
            return LegalDesign.save();
          });
          html = readFileSync(await (await downloaded).path(), "utf8");
        } else
          html = await page.evaluate(
            (kind) => LegalDesign["export" + kind](false),
            kind,
          );
        const output = join(temp, `${kind}-${source.split("/").at(-1)}`);
        writeFileSync(output, html);
        const reopened = await context.newPage();
        await reopened.goto(pathToFileURL(output).href);
        await reopened.waitForFunction(
          () =>
            document.documentElement.getAttribute("data-legaldesign-ready") ===
            "true",
        );
        await reopened.waitForTimeout(80);
        const fit = await readBounds(reopened);
        assert(fit.valid, `${kind}: reopened frame overflows`);
        assert.equal(fit.visiblePages, 1, `${kind}: only one page displayed`);
        assert.equal(
          await reopened.locator("[data-report-section]").count(),
          2,
        );
        await reopened.close();
      }
      await context.close();
    }
    console.log(
      "PASS report and walkthrough page navigation, client and template exports",
    );

    const privacyContext = await browser.newContext({
      viewport: { width: 1280, height: 800 },
    });
    const privacyPage = await privacyContext.newPage();
    await privacyPage.goto(pathToFileURL(single).href);
    await privacyPage.waitForFunction(
      () => document.documentElement.dataset.legaldesignReady === "true",
    );
    await privacyPage.evaluate(() => {
      const popup = document.querySelector("#popup-scrim .pop");
      document
        .querySelector('[data-unit="a-summary"]')
        .setAttribute("data-detail", popup.id);
      for (const tag of ["p", "footer"]) {
        const source = document.createElement(tag);
        source.className = "ld-popup-source";
        source.textContent =
          "PRIVATE-SOURCE-SENTINEL · SKILL.md · Deliverable contract";
        popup.append(source);
      }
    });
    const clientWithSource = await privacyPage.evaluate(() =>
      LegalDesign.exportHTML(false),
    );
    assert(
      clientWithSource.includes("PRIVATE-SOURCE-SENTINEL"),
      "client export preserves source provenance",
    );
    const templateWithoutSource = await privacyPage.evaluate(() =>
      LegalDesign.exportTemplate(false),
    );
    assert(
      !templateWithoutSource.includes("PRIVATE-SOURCE-SENTINEL"),
      "template scrubs paragraph and footer source provenance",
    );
    assert(
      templateWithoutSource.includes("[Source, version, date retrieved.]"),
      "template retains a descriptive source placeholder",
    );
    const privacyOutput = join(temp, "popup-provenance.template.html");
    writeFileSync(privacyOutput, templateWithoutSource);
    await privacyPage.goto(pathToFileURL(privacyOutput).href);
    await privacyPage.waitForFunction(
      () => document.documentElement.dataset.legaldesignReady === "true",
    );
    const sourceText = await privacyPage
      .locator(".ld-popup-source")
      .allTextContents();
    assert(sourceText.length >= 2);
    assert(
      sourceText.every((text) => text === "[Source, version, date retrieved.]"),
    );
    await privacyContext.close();
    console.log(
      "PASS template popup provenance is scrubbed while client citations remain intact",
    );

    const context = await browser.newContext({
      viewport: { width: 1280, height: 800 },
    });
    const page = await context.newPage();
    await page.goto(pathToFileURL(single).href);
    await page.waitForFunction(
      () =>
        document.documentElement.getAttribute("data-legaldesign-ready") ===
        "true",
    );
    await page.getByRole("button", { name: "Edit", exact: true }).click();
    const target = page.locator('[data-unit="a-summary"] p');
    const before = await target.boundingBox();
    await page.mouse.move(before.x + 20, before.y + 10);
    await page.mouse.down();
    await page.mouse.move(before.x + 60, before.y + 25, { steps: 8 });
    await page.mouse.up();
    const after = await target.boundingBox();
    assert(
      Math.abs(after.x - before.x - 40) < 2,
      "HTML drag uses screen delta at scaled page",
    );
    const horizontalClip = await page.evaluate(() => {
      const p = document.querySelector('[data-unit="a-summary"] p');
      const saved = p.getAttribute("style");
      p.style.width = "24px";
      p.style.whiteSpace = "nowrap";
      p.style.overflowX = "hidden";
      const invalid = !LegalDesign.checkPageFit({ allPages: true }).valid;
      if (saved === null) p.removeAttribute("style");
      else p.setAttribute("style", saved);
      return invalid;
    });
    assert(
      horizontalClip,
      "in-bounds HTML with horizontally clipped text must fail page fit",
    );
    await page.evaluate(() => {
      const p = document.querySelector('[data-unit="a-summary"] p');
      p.style.height = "2000px";
    });
    const refused = await page.evaluate(() => {
      try {
        LegalDesign.exportHTML(false);
        return false;
      } catch (e) {
        return /4:3|available window/.test(e.message);
      }
    });
    assert(
      refused,
      "overfull page must refuse export instead of clipping content",
    );
    assert(await page.locator("#ld-page-fit-error").isVisible());
    assert(
      await page.locator('[data-unit="a-summary"] p').textContent(),
      "overflow guard retains content",
    );
    await context.close();
    console.log(
      "PASS scaled HTML editing and fail-closed overfull page export",
    );
  } finally {
    await browser.close();
  }
}

if (
  process.argv[1] &&
  resolve(process.argv[1]) === fileURLToPath(import.meta.url)
)
  await runFixedPageSuite();
