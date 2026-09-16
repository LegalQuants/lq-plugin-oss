import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";

const near = (actual, expected, label, tolerance = 2) =>
  assert(
    Math.abs(actual - expected) <= tolerance,
    `${label}: ${actual} expected ${expected}`,
  );
async function drag(page, x, y, dx, dy) {
  await page.mouse.move(x, y);
  await page.mouse.down();
  await page.mouse.move(x + dx, y + dy, { steps: 12 });
  await page.mouse.up();
}
async function resize(page, dx, dy = 0) {
  let edge = dy ? "se" : "e";
  if (!(await page.locator(`.ld-handle[data-handle="${edge}"]`).isVisible()))
    edge = dy ? "sw" : "w";
  const handle = await page
    .locator(`.ld-handle[data-handle="${edge}"]`)
    .boundingBox();
  assert(handle, "selection resize handle visible");
  await drag(
    page,
    handle.x + handle.width / 2,
    handle.y + handle.height / 2,
    edge.includes("w") ? -dx : dx,
    dy,
  );
}
async function selectNode(page, node) {
  const rect = node.locator("rect").first();
  await rect.click({ position: { x: 8, y: 8 } });
  // A semantic card click can also open its detail; closing preserves selection.
  const close = page.locator(".pop:visible .ld-popup-close");
  if (await close.count()) await close.click();
}

export async function runEditorAuthoringSuite({
  run,
  pageFor,
  closeClean,
  composedFixture,
  sourceRuntimeAsset,
  downloadFrom,
}) {
  async function fresh() {
    const fixture = composedFixture();
    return pageFor({
      url: pathToFileURL(sourceRuntimeAsset(fixture.html)).href,
      viewport: { width: 1440, height: 1200 },
    });
  }

  await run(
    "dark HTML card surfaces preserve popup and user paint roles",
    async () => {
      const session = await fresh();
      const { page } = session;
      const result = await page.evaluate(() => {
        document.documentElement.dataset.theme = "dark";
        const probe = document.createElement("div");
        probe.innerHTML =
          '<div class="ld-card" data-detail="probe"><h3>Card label</h3></div><div class="sb-card accent"><p>Accent</p></div><div class="ld-card" data-fill-token="red" style="background: rgb(23, 42, 63)">Custom</div><div class="pop">Popup</div>';
        document.body.append(probe);
        const read = (selector) => {
          const style = getComputedStyle(probe.querySelector(selector));
          return {
            background: style.backgroundColor,
            color: style.color,
            underline: style.textDecorationLine,
            cursor: style.cursor,
            border: style.borderTopColor,
          };
        };
        const data = {
          general: read(".ld-card"),
          label: read("h3"),
          accent: read(".accent"),
          custom: read("[data-fill-token]"),
          popup: read(".pop"),
        };
        probe.remove();
        return data;
      });
      assert.equal(result.general.background, "rgb(17, 17, 17)");
      assert.equal(result.general.color, "rgb(255, 255, 255)");
      assert.equal(result.general.cursor, "pointer");
      assert.equal(result.label.underline, "none");
      assert.equal(result.accent.background, "rgb(17, 17, 17)");
      assert.equal(result.accent.color, "rgb(255, 255, 255)");
      assert.notEqual(result.accent.border, result.general.border);
      assert.equal(result.custom.background, "rgb(23, 42, 63)");
      assert.equal(result.popup.background, "rgb(17, 17, 17)");
      await closeClean(session);
    },
  );

  await run(
    "editor authoring full-width headings and popup resize",
    async () => {
      const session = await fresh();
      const { page } = session;
      for (const selector of [
        '[data-unit="a-title"] h1',
        '[data-unit="a-summary"] [data-editable]',
      ]) {
        const element = page.locator(selector).first();
        const widths = await element.evaluate((node) => {
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
        });
        near(
          widths.actual,
          widths.available,
          `${selector} uses available width`,
        );
      }
      await page.click("#mode-toggle");
      const heading = page.locator('[data-unit="a-title"] h1');
      await heading.click();
      const before = await heading.boundingBox();
      await resize(page, -100);
      near(
        (await heading.boundingBox()).width,
        before.width - 100,
        "main title width follows resize",
      );
      await page.click('[data-unit="a-flow"] [data-detail="e-ask"]');
      await page.click("#editor-popup");
      const pop = page.locator("#e-ask");
      const title = pop.locator("h2");
      const fullWidth = await title.evaluate((node) => {
        const p = node.parentElement,
          s = getComputedStyle(p);
        const scale = p.getBoundingClientRect().width / p.offsetWidth;
        return {
          actual: node.getBoundingClientRect().width,
          available:
            (p.clientWidth -
              parseFloat(s.paddingLeft) -
              parseFloat(s.paddingRight)) *
            scale,
        };
      });
      near(fullWidth.actual, fullWidth.available, "popup heading full width");
      await title.click();
      const popupBefore = await title.boundingBox();
      await resize(page, -80);
      near(
        (await title.boundingBox()).width,
        popupBefore.width - 80,
        "popup heading width follows resize",
      );
      await pop.locator(".ld-popup-close").click();
      const saved = await downloadFrom(
        page,
        "#ld-save",
        "authoring-heading-width-saved.html",
      );
      const reopened = await pageFor({
        url: pathToFileURL(saved).href,
        viewport: { width: 1440, height: 1200 },
      });
      near(
        (await reopened.page.locator('[data-unit="a-title"] h1').boundingBox())
          .width,
        before.width - 100,
        "main title resized width survives save",
      );
      await reopened.page.click('[data-unit="a-flow"] [data-detail="e-ask"]');
      near(
        (await reopened.page.locator("#e-ask h2").boundingBox()).width,
        popupBefore.width - 80,
        "popup heading resized width survives save",
      );
      await closeClean(reopened);
      await closeClean(session);
    },
  );

  await run(
    "editor authoring palettes enclosure group drag and cumulative SVG resize",
    async () => {
      const session = await fresh();
      const { page } = session;
      await page.click("#mode-toggle");
      const nodes = page.locator(
        '[data-unit="a-flow"] svg [data-diagram-object]',
      );
      assert(
        (await nodes.count()) >= 3,
        "flow exposes semantic editor objects",
      );
      const first = nodes.nth(0),
        second = nodes.nth(1),
        third = nodes.nth(2);
      await selectNode(page, first);
      const rect = first.locator("rect").first(),
        label = first.locator("text").first();
      const oldFill = await rect.evaluate((n) => getComputedStyle(n).fill);
      await page.click("#editor-fill-palette");
      await page.click('#ld-color-palette [data-color-token="tint"]');
      assert.notEqual(
        await rect.evaluate((n) => getComputedStyle(n).fill),
        oldFill,
        "fill swatch visibly changes SVG rect",
      );
      const oldText = await label.evaluate((n) => getComputedStyle(n).fill);
      await page.click("#editor-text-palette");
      await page.click('#ld-color-palette [data-color-token="red"]');
      assert.notEqual(
        await label.evaluate((n) => getComputedStyle(n).fill),
        oldText,
        "text swatch visibly changes SVG label",
      );
      await page.keyboard.press("Escape");
      const boxes = await Promise.all([
        first.boundingBox(),
        second.boundingBox(),
        third.boundingBox(),
      ]);
      const left = Math.min(boxes[0].x, boxes[1].x) - 4;
      const top = Math.min(boxes[0].y, boxes[1].y) - 4;
      const right = boxes[2].x + Math.min(10, boxes[2].width / 3);
      const bottom =
        Math.max(boxes[0].y + boxes[0].height, boxes[1].y + boxes[1].height) +
        4;
      await drag(page, left, top, right - left, bottom - top);
      assert.equal(
        await first.evaluate((n) => n.classList.contains("ld-selected")),
        true,
        "fully enclosed first node selected",
      );
      assert.equal(
        await second.evaluate((n) => n.classList.contains("ld-selected")),
        true,
        "fully enclosed second node selected",
      );
      assert.equal(
        await third.evaluate((n) => n.classList.contains("ld-selected")),
        false,
        "partially enclosed third node excluded",
      );
      const before = await Promise.all([
        first.boundingBox(),
        second.boundingBox(),
        third.boundingBox(),
      ]);
      await drag(page, before[0].x + 8, before[0].y + 8, 37, 24);
      const after = await Promise.all([
        first.boundingBox(),
        second.boundingBox(),
        third.boundingBox(),
      ]);
      for (let i = 0; i < 2; i++) {
        near(
          after[i].x - before[i].x,
          37,
          `scaled SVG node ${i} group screen delta x`,
        );
        near(
          after[i].y - before[i].y,
          24,
          `scaled SVG node ${i} group screen delta y`,
        );
      }
      near(after[2].x, before[2].x, "excluded node stays still");
      await page.keyboard.press("Escape");
      await selectNode(page, first);
      const initial = await first.boundingBox();
      await resize(page, 30);
      const once = await first.boundingBox();
      await resize(page, 25);
      const twice = await first.boundingBox();
      near(once.width, initial.width + 30, "first SVG resize");
      near(twice.width, initial.width + 55, "second SVG resize accumulates");
      await page.click("#editor-duplicate");
      const copy = page.locator('[data-unit="a-flow"] svg .ld-selected');
      assert.equal(await copy.count(), 1);
      const copied = await copy.boundingBox();
      const copyId = await copy.getAttribute("data-detail");
      near(copied.width, twice.width, "duplicate keeps resized geometry");
      assert.notEqual(
        await copy.getAttribute("data-detail"),
        await first.getAttribute("data-detail"),
        "duplicate owns independent popup",
      );
      await page.click("#editor-popup");
      const duplicateTitle = page.locator(".pop:visible h2");
      await duplicateTitle.dblclick();
      await duplicateTitle.fill("Independent duplicate explanation");
      await duplicateTitle.blur();
      assert.notEqual(
        await page.locator("#e-ask h2").textContent(),
        "Independent duplicate explanation",
        "editing cloned popup does not mutate original",
      );
      await page.locator(".pop:visible .ld-popup-close").click();
      const saved = await downloadFrom(
        page,
        "#ld-save",
        "authoring-svg-saved.html",
      );
      await page.click("#mode-toggle");
      const client = await downloadFrom(
        page,
        "#export-html",
        "authoring-svg-client.html",
      );
      const template = await downloadFrom(
        page,
        "#export-template",
        "authoring-svg-template.html",
      );
      for (const path of [saved, client]) {
        const reopened = await pageFor({
          url: pathToFileURL(path).href,
          viewport: { width: 1440, height: 1200 },
        });
        const restored = reopened.page.locator(
          `[data-unit="a-flow"] [data-detail="${copyId}"]`,
        );
        assert.equal(
          await restored.count(),
          1,
          "duplicate survives HTML serialization",
        );
        near(
          (await restored.boundingBox()).width,
          copied.width,
          "resized duplicate keeps geometry after reopen",
        );
        await restored
          .locator("rect")
          .first()
          .click({ position: { x: 8, y: 8 } });
        assert.equal(
          await reopened.page.locator(".pop:visible h2").textContent(),
          "Independent duplicate explanation",
        );
        await closeClean(reopened);
      }
      const reusable = await pageFor({
        url: pathToFileURL(template).href,
        viewport: { width: 1440, height: 1200 },
      });
      assert.equal(
        await reusable.page
          .locator(".ld-diagram:visible")
          .first()
          .locator("[data-diagram-object]")
          .count(),
        await nodes.count(),
        "template keeps duplicated semantic box",
      );
      assert(
        !readFileSync(template, "utf8").includes(
          "Independent duplicate explanation",
        ),
        "template replaces duplicate popup text",
      );
      await closeClean(reusable);
      await closeClean(session);
    },
  );

  await run(
    "editor authoring added textbox popup sections detach and export persistence",
    async () => {
      const session = await fresh();
      const { page } = session;
      await page.click("#mode-toggle");
      await page.click("#editor-add-text");
      const textbox = page.locator(".ld-added-text");
      assert.equal(await textbox.count(), 1);
      const affordance = (node) => ({
        cursor: getComputedStyle(node).cursor,
        underline:
          getComputedStyle(node).textDecorationLine.includes("underline"),
      });
      assert.equal((await textbox.evaluate(affordance)).underline, false);
      await textbox.fill("ZZ-AUTHORED-PRIVATE-TEXT-9081");
      await textbox.blur();
      await textbox.click();
      assert.equal(
        await page.locator("#editor-popup").textContent(),
        "Add popup",
      );
      await page.click("#editor-popup");
      const pop = page.locator(".pop:visible");
      const heading = pop.locator("h2");
      await heading.dblclick();
      await heading.fill("ZZ-AUTHORED-PRIVATE-POPUP-9081");
      await heading.blur();
      const originalSections = await pop.locator(".ld-popup-section").count();
      await pop
        .getByRole("button", { name: "Add section", exact: true })
        .click();
      assert.equal(
        await pop.locator(".ld-popup-section").count(),
        originalSections + 1,
      );
      const body = pop.locator(".ld-popup-section p").last();
      await body.dblclick();
      await body.fill("ZZ-AUTHORED-PRIVATE-SECTION-9081");
      await body.blur();
      await pop.locator(".ld-popup-close").click();
      const id = await textbox.getAttribute("data-detail");
      assert(id);
      assert.deepEqual(
        await textbox.evaluate(affordance),
        {
          cursor: "pointer",
          underline: true,
        },
        "attached text advertises its popup even while selected for editing",
      );
      const cardLabel = page
        .locator('[data-unit="a-flow"] [data-detail] text')
        .first();
      assert.equal(
        (await cardLabel.evaluate(affordance)).underline,
        false,
        "card labels do not receive text-link underlines",
      );
      await textbox.click();
      for (const [theme, expected] of [
        ["dark", "rgb(160, 160, 156)"],
        ["light", "rgb(118, 118, 118)"],
      ]) {
        await page.evaluate(
          (theme) => (document.documentElement.dataset.theme = theme),
          theme,
        );
        assert.equal(
          await page
            .locator("#ld-selection-box")
            .evaluate((node) => getComputedStyle(node).borderTopColor),
          expected,
          "selection uses the visible neutral interaction color",
        );
        const handle = page
          .locator("#ld-selection-box .ld-handle:visible")
          .first();
        assert(
          await handle.isVisible(),
          `${theme}: selection resize handle stays visible`,
        );
        assert.equal(
          await handle.evaluate(
            (node) => getComputedStyle(node).borderTopColor,
          ),
          expected,
        );
      }
      // Text selection opens no popup, so toolbar controls can detach the target.
      assert.equal(
        await page.locator("#editor-remove-popup").isDisabled(),
        false,
        JSON.stringify(
          await page.evaluate(() => ({
            selected: [...document.querySelectorAll(".ld-selected")].map((n) =>
              n.outerHTML.slice(0, 500),
            ),
            textbox: document.querySelector(".ld-added-text").outerHTML,
            mode: document.documentElement.dataset.mode,
          })),
        ),
      );
      await page.click("#editor-remove-popup");
      assert.equal(await textbox.getAttribute("data-detail"), null);
      assert.equal(
        (await textbox.evaluate(affordance)).underline,
        false,
        "detaching popup removes automatic underline",
      );
      await page.click("#editor-undo");
      assert.equal(
        await page.locator(".ld-added-text").getAttribute("data-detail"),
        id,
        "Undo recovers popup attachment",
      );
      await page.click("#mode-toggle");
      const client = await downloadFrom(
        page,
        "#export-html",
        "authoring-added-client.html",
      );
      const template = await downloadFrom(
        page,
        "#export-template",
        "authoring-added-template.html",
      );
      await page.click("#mode-toggle");
      const saved = await downloadFrom(
        page,
        "#ld-save",
        "authoring-added-saved.html",
      );
      for (const path of [client, saved]) {
        const reopened = await pageFor({ url: pathToFileURL(path).href });
        assert.equal(
          await reopened.page.locator(".ld-added-text").textContent(),
          "ZZ-AUTHORED-PRIVATE-TEXT-9081",
        );
        assert.deepEqual(
          await reopened.page.locator(".ld-added-text").evaluate(affordance),
          {
            cursor: "pointer",
            underline: true,
          },
          "popup text affordance survives working/client export",
        );
        await reopened.page.locator(".ld-added-text").click();
        assert.equal(
          await reopened.page.locator(".pop:visible h2").textContent(),
          "ZZ-AUTHORED-PRIVATE-POPUP-9081",
        );
        assert.match(
          await reopened.page.locator(".pop:visible").textContent(),
          /ZZ-AUTHORED-PRIVATE-SECTION-9081/,
        );
        await closeClean(reopened);
      }
      assert(
        !readFileSync(template, "utf8").includes("ZZ-AUTHORED-PRIVATE"),
        "template strips all authored matter content",
      );
      const blank = await pageFor({ url: pathToFileURL(template).href });
      assert.equal(
        await blank.page.locator(".ld-added-text").count(),
        1,
        "template retains authored textbox",
      );
      assert.deepEqual(
        await blank.page.locator(".ld-added-text").evaluate(affordance),
        {
          cursor: "pointer",
          underline: true,
        },
        "template popup placeholder is visibly interactive",
      );
      await blank.page.locator(".ld-added-text").click();
      assert.equal(
        await blank.page.locator(".pop:visible .ld-popup-section").count(),
        originalSections + 1,
        "template retains added popup section structure",
      );
      await closeClean(blank);
      await closeClean(session);
    },
  );

  await run(
    "editor authoring SVG label resize survives every export",
    async () => {
      const session = await fresh();
      const { page } = session;
      await page.click("#mode-toggle");
      const label = page
        .locator('[data-unit="a-flow"] text[data-param-path]:not(.edge)')
        .first();
      await label.dblclick();
      await page.locator("#ld-svg-text-editor").press("Enter");
      const before = await label.boundingBox();
      await resize(page, 24);
      await resize(page, 16);
      const resized = await label.boundingBox();
      near(
        resized.width,
        before.width + 40,
        "selected SVG text resizes cumulatively",
      );
      const scale = await label.getAttribute("data-editor-scale-x");
      assert(Number(scale) > 1);
      await page.click("#editor-text-palette");
      await page.click('#ld-color-palette [data-color-token="red"]');
      const edge = page.locator('[data-unit="a-flow"] text.edge').first();
      await edge.dblclick();
      await page.locator("#ld-svg-text-editor").press("Enter");
      const edgeBefore = await edge.boundingBox();
      await resize(page, 15);
      const edgeScale = await edge.getAttribute("data-editor-scale-x");
      near(
        (await edge.boundingBox()).width,
        edgeBefore.width + 15,
        "free connector label also resizes",
      );
      const saved = await downloadFrom(
        page,
        "#ld-save",
        "authoring-label-resized-saved.html",
      );
      await page.click("#mode-toggle");
      const client = await downloadFrom(
        page,
        "#export-html",
        "authoring-label-resized-client.html",
      );
      const template = await downloadFrom(
        page,
        "#export-template",
        "authoring-label-resized-template.html",
      );
      for (const [kind, path] of [
        ["saved", saved],
        ["client", client],
        ["template", template],
      ]) {
        const reopened = await pageFor({
          url: pathToFileURL(path).href,
          viewport: { width: 1440, height: 1200 },
        });
        const text = reopened.page
          .locator(".ld-diagram:visible")
          .first()
          .locator("text:not(.edge)")
          .first();
        const restoredEdge = reopened.page
          .locator(".ld-diagram:visible")
          .first()
          .locator("text.edge")
          .first();
        assert.equal(
          await text.getAttribute("data-text-token"),
          "red",
          `${kind}: label text color retained`,
        );
        if (kind !== "template")
          near(
            (await text.boundingBox()).width,
            resized.width,
            `${kind}: label width retained`,
          );
        else {
          assert.equal(
            await restoredEdge.getAttribute("data-editor-scale-x"),
            edgeScale,
            "template retains loose connector label geometry",
          );
          assert.equal(
            await text.getAttribute("data-editor-scale-x"),
            scale,
            "template retains label resize ratio while replacing matter text",
          );
          await reopened.page.click("#mode-toggle");
          await text.dblclick();
          await reopened.page.locator("#ld-svg-text-editor").press("Enter");
          const templateBefore = await text.boundingBox();
          await resize(reopened.page, 20);
          near(
            (await text.boundingBox()).width,
            templateBefore.width + 20,
            "reopened template label remains cumulatively resizable",
          );
        }
        await closeClean(reopened);
      }
      await closeClean(session);
    },
  );

  await run(
    "editor authoring left contents indexes survive approaches and exports",
    async () => {
      for (const form of ["walkthrough", "report"]) {
        const fixture = composedFixture({ form });
        // Use the actual composer output here: injecting the source runtime would
        // hide production regressions in CSS placement and template sanitization.
        const session = await pageFor({
          url: pathToFileURL(fixture.html).href,
          viewport: { width: 1440, height: 1000 },
        });
        const { page } = session;
        assert.equal(
          await page.locator("head #ld-tokens").count(),
          1,
          `${form}: production runtime CSS is trusted head content`,
        );
        assert.equal(
          await page.locator("body #ld-tokens").count(),
          0,
          `${form}: runtime CSS is not discarded as body content on template export`,
        );
        async function checkIndex(p, label) {
          const nav = p.locator("#ld-form-navigation");
          assert.equal(await nav.count(), 1, `${label}: one contents index`);
          const entries = nav.locator("[data-report-section]");
          const total = await entries.count();
          assert(
            total >= 2,
            `${label}: every multi-slide artifact has section navigation`,
          );
          const navBox = await nav.boundingBox();
          const bodyBox = await p
            .locator(".ld-composed-section:visible")
            .first()
            .boundingBox();
          assert(
            navBox.x + navBox.width <= bodyBox.x + 2,
            `${label}: contents stays left of page content; nav=${JSON.stringify(navBox)} content=${JSON.stringify(bodyBox)}`,
          );
          await entries.nth(total - 1).click();
          assert.equal(
            await entries.nth(total - 1).getAttribute("aria-current"),
            "true",
            `${label}: index navigates to selected section ${JSON.stringify(await p.evaluate(() => ({ approach: document.documentElement.dataset.pageApproach, review: LegalDesign.state().review, sections: [...document.querySelectorAll(".ld-page-approach:not([hidden]) .ld-composed-section")].map((n) => ({ id: n.dataset.compositionSection, hidden: n.hidden })), entries: [...document.querySelectorAll("#ld-form-navigation [data-report-section]")].map((n) => ({ text: n.textContent, current: n.getAttribute("aria-current") })) })))}`,
          );
          if (form === "walkthrough")
            assert.equal(
              await p.locator(".ld-composed-section:visible").count(),
              1,
              `${label}: exactly one current slide`,
            );
        }
        await checkIndex(page, `${form} A`);
        await page.click('[data-select-approach="b"]');
        await checkIndex(page, `${form} B`);
        await page.click("#mode-toggle");
        const saved = await downloadFrom(
          page,
          "#ld-save",
          `authoring-${form}-index-saved.html`,
        );
        await page.click("#mode-toggle");
        const client = await downloadFrom(
          page,
          "#export-html",
          `authoring-${form}-index-client.html`,
        );
        const template = await downloadFrom(
          page,
          "#export-template",
          `authoring-${form}-index-template.html`,
        );
        for (const [kind, path] of [
          ["saved", saved],
          ["client", client],
          ["template", template],
        ]) {
          const reopened = await pageFor({
            url: pathToFileURL(path).href,
            viewport: { width: 1440, height: 1000 },
          });
          await checkIndex(reopened.page, `${form} ${kind}`);
          if (kind !== "client") {
            await reopened.page.click('[data-select-approach="a"]');
            await checkIndex(reopened.page, `${form} ${kind} switched A`);
          }
          await closeClean(reopened);
        }
        await page.setViewportSize({ width: 430, height: 932 });
        const toggle = page.locator("#ld-form-navigation [data-index-toggle]");
        await page.waitForFunction(
          () =>
            document
              .querySelector("#ld-form-navigation [data-index-toggle]")
              ?.getAttribute("aria-expanded") === "false",
        );
        assert.equal(
          await toggle.getAttribute("aria-expanded"),
          "false",
          `${form}: phone starts compact`,
        );
        await toggle.click();
        assert.equal(await toggle.getAttribute("aria-expanded"), "true");
        await page
          .locator("#ld-form-navigation [data-report-section]")
          .first()
          .click();
        assert.equal(
          await toggle.getAttribute("aria-expanded"),
          "false",
          `${form}: choosing section collapses phone index`,
        );
        await closeClean(session);
      }
    },
  );
}
