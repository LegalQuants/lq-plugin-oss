import assert from "node:assert/strict";

const FLOW = {
  stages: [
    { title: "Ask", sub: "Reader, purpose, audience", detail: "src-questions" },
    { title: "Ground", sub: "Claims and source record", detail: "src-brief" },
    {
      title: "Relate",
      sub: "Find the core relationship",
      detail: "src-relationship",
    },
    {
      title: "Design",
      sub: "Choose form and encoding",
      detail: "src-form",
      accentRole: "decision",
    },
    {
      title: "Compare",
      sub: "Build complete pages A and B",
      detail: "src-treatments",
    },
    {
      title: "Export",
      sub: "HTML or reusable template",
      detail: "src-exports",
    },
  ],
  edges: ["clarify", "source", "decide", "compose", "choose"],
};
const HIERARCHY = {
  root: "Communication goal",
  rootSub: "What must this reader understand or do?",
  branches: [
    {
      title: "Inputs",
      edge: "define",
      detail: "src-brief",
      leaves: [{ title: "Source record" }, { title: "Reader’s job" }],
    },
    {
      title: "Design judgment",
      edge: "shape",
      detail: "src-form",
      accentRole: "decision",
      leaves: [{ title: "Visual form" }, { title: "Position + structure" }],
    },
    {
      title: "Outputs",
      edge: "produce",
      detail: "src-exports",
      leaves: [{ title: "Selected HTML" }, { title: "Reusable template" }],
    },
  ],
};

async function renderFixture(page, component, params, narrow = false) {
  await page.evaluate(
    ({ component, params, narrow }) => {
      document.getElementById("diagram-refinement-probe")?.remove();
      // This is an isolated component probe, not the presentation stage.
      // The presentation stage must not cover or intercept its pointer targets.
      document
        .getElementById("slide-stage")
        ?.style.setProperty("display", "none");
      const probe = document.createElement("section");
      probe.id = "diagram-refinement-probe";
      probe.style.cssText =
        "width:800px;max-width:calc(100vw - 24px);margin:72px auto 32px;background:var(--bg)";
      probe.innerHTML = window.LegalDesign.render(component, params, {
        narrow,
      });
      document.body.append(probe);
      probe.scrollIntoView({ block: "start" });
    },
    { component, params, narrow },
  );
  return page.locator("#diagram-refinement-probe");
}

async function diagramMeasurements(probe) {
  return probe.evaluate((root) => {
    const rectangle = (node) => {
      const b = node.getBoundingClientRect();
      return { x: b.x, y: b.y, right: b.right, bottom: b.bottom };
    };
    const distance = (a, b) =>
      Math.hypot(
        Math.max(a.x - b.right, b.x - a.right, 0),
        Math.max(a.y - b.bottom, b.y - a.bottom, 0),
      );
    const boxes = [...root.querySelectorAll("rect.box")].map(rectangle);
    const labels = [...root.querySelectorAll("text.edge")];
    const connectorPoints = [
      ...root.querySelectorAll("path.line,path.hair"),
    ].flatMap((path) => {
      const matrix = path.getScreenCTM();
      const length = path.getTotalLength();
      const steps = Math.max(1, Math.ceil(length / 2));
      return Array.from({ length: steps + 1 }, (_, index) => {
        const p = path
          .getPointAtLength((length * index) / steps)
          .matrixTransform(matrix);
        return { x: p.x, y: p.y, right: p.x, bottom: p.y };
      });
    });
    return {
      labels: labels.map((label) => {
        const bounds = rectangle(label);
        return {
          text: label.textContent,
          boxClearance: Math.min(...boxes.map((box) => distance(bounds, box))),
          connectorClearance: Math.min(
            ...connectorPoints.map((point) => distance(bounds, point)),
          ),
        };
      }),
      centered: [...root.querySelectorAll("[data-diagram-object]")].flatMap(
        (group) => {
          const shape = group.querySelector(":scope > rect");
          if (!shape) return [];
          const center =
            Number(shape.getAttribute("x")) +
            Number(shape.getAttribute("width")) / 2;
          return [...group.querySelectorAll(":scope > text")].map((text) => ({
            text: text.textContent,
            anchor: text.getAttribute("text-anchor"),
            offset: Math.abs(Number(text.getAttribute("x")) - center),
          }));
        },
      ),
      colors: {
        ground: getComputedStyle(root).backgroundColor,
        card: getComputedStyle(root.querySelector("rect.box:not(.accent)"))
          .fill,
        outlineWidth: Number.parseFloat(
          getComputedStyle(root.querySelector("rect.box")).strokeWidth,
        ),
        connectorWidth: Number.parseFloat(
          getComputedStyle(root.querySelector("path.line")).strokeWidth,
        ),
      },
    };
  });
}

async function outlineState(target) {
  return target.evaluate((node) => ({
    primary: getComputedStyle(node.querySelector(":scope > rect")).stroke,
    leaves: [...node.querySelectorAll(".leaf")].map(
      (leaf) => getComputedStyle(leaf).stroke,
    ),
    accent: getComputedStyle(document.documentElement)
      .getPropertyValue("--red")
      .trim(),
  }));
}

const TRANSPARENT = "rgba(0, 0, 0, 0)";

export async function runDiagramRefinementSuite({ run, pageFor, closeClean }) {
  await run(
    "vertical timeline preserves narrative chronology and popup access",
    async () => {
      const session = await pageFor({ asset: "method", sourceRuntime: true });
      const { page } = session;
      const marks = [
        {
          when: "1 October 2026",
          title: "The proposed transfer starts with consent outstanding",
          sub: "The customer must first receive the written transfer proposal and the complete list of services that remain with the seller until consent is recorded.",
          detail: "src-questions",
        },
        {
          when: "After written customer consent",
          title: "A signed novation confirms who carries the obligation",
          sub: "The parties record the effective date and responsibility for support. No assumption is made that consent alone transfers liability.",
          detail: "src-brief",
        },
        {
          when: "The agreed effective date",
          title: "The buyer takes responsibility under the signed agreement",
          sub: "This third event deliberately uses longer supporting prose to verify that event height expands without clipping, truncation, or an overlap with its date or title.",
          detail: "src-exports",
        },
      ];
      for (const theme of ["light", "dark"]) {
        await page.evaluate((theme) => {
          document.documentElement.dataset.theme = theme;
        }, theme);
        for (const width of [320, 400]) {
          const probe = await renderFixture(page, "timeline", {
            orientation: "vertical",
            marks,
            nowAt: 1,
          });
          await probe.evaluate((node, width) => {
            node.style.width = `${width}px`;
          }, width);
          const metrics = await probe.evaluate((host) => {
            const svg = host.querySelector("svg"),
              view = svg.viewBox.baseVal;
            const events = [...svg.querySelectorAll("[data-timeline-event]")];
            return {
              width: view.width,
              height: view.height,
              rail: svg.querySelector(".timeline-rail").getAttribute("d"),
              targets: events.map((event) => ({
                detail: event.dataset.detail,
                role: event.getAttribute("role"),
                tab: event.getAttribute("tabindex"),
                nested: event.querySelectorAll("[data-detail]").length,
              })),
              ink: getComputedStyle(svg.querySelector("text")).fill,
              active: svg.querySelectorAll('[data-accent-role="active"]')
                .length,
              boxes: svg.querySelectorAll(".box,.leaf,.band").length,
              overflow: events.flatMap((event) => {
                const hit = event.querySelector(".timeline-hit").getBBox();
                return [...event.querySelectorAll("text")].flatMap((text) => {
                  const b = text.getBBox();
                  return b.x < hit.x ||
                    b.x + b.width > hit.x + hit.width ||
                    b.y < hit.y ||
                    b.y + b.height > hit.y + hit.height ||
                    b.y + b.height > view.height
                    ? [text.textContent]
                    : [];
                });
              }),
              textGaps: events.flatMap((event) => {
                const boxes = [...event.querySelectorAll("text")].map((node) =>
                  node.getBBox(),
                );
                return boxes
                  .slice(1)
                  .map(
                    (box, index) =>
                      box.y - (boxes[index].y + boxes[index].height),
                  );
              }),
              eventGaps: events
                .slice(1)
                .map(
                  (event, index) =>
                    event.getBBox().y -
                    (events[index].getBBox().y +
                      events[index].getBBox().height),
                ),
            };
          });
          assert.equal(metrics.width, 400);
          assert(
            metrics.height > 400,
            "Narrative event heights must expand beyond a fixed square",
          );
          assert.match(metrics.rail, /^M28 [\d.]+V[\d.]+$/);
          assert.deepEqual(
            metrics.targets.map((target) => target.detail),
            marks.map((mark) => mark.detail),
          );
          assert(
            metrics.targets.every(
              (target) =>
                target.role === "button" &&
                target.tab === "0" &&
                target.nested === 0,
            ),
          );
          assert.equal(metrics.boxes, 0);
          assert.equal(metrics.active, 1);
          assert.deepEqual(metrics.overflow, []);
          assert(
            metrics.textGaps.every((gap) => gap >= 4),
            JSON.stringify(metrics),
          );
          assert(
            metrics.eventGaps.every((gap) => gap >= 10),
            JSON.stringify(metrics),
          );
          if (theme === "dark") assert.equal(metrics.ink, "rgb(255, 255, 255)");
          const target = probe.locator('[data-detail="src-brief"]');
          await page.keyboard.press("Tab");
          await target.focus();
          await page.keyboard.press("Enter");
          assert.equal(await page.locator("#src-brief").isVisible(), true);
          await page.keyboard.press("Escape");
          assert.equal(
            await target.evaluate((node) => node === document.activeElement),
            true,
          );
        }
      }
      const capacity = await page.evaluate((marks) => {
        const data = {
          marks: [...marks, ...marks.slice(0, 2)],
          orientation: "vertical",
        };
        const host = document.createElement("div");
        host.innerHTML = LegalDesign.render("timeline", data);
        let rejected = false;
        try {
          LegalDesign.render("timeline", { ...data, orientation: "diagonal" });
        } catch {
          rejected = true;
        }
        return {
          count: host.querySelectorAll("[data-timeline-event]").length,
          rejected,
        };
      }, marks);
      assert.deepEqual(capacity, { count: 5, rejected: true });
      await closeClean(session);
    },
  );
  await run("diagram catalog and semantic preservation", async () => {
    const session = await pageFor({ asset: "library", sourceRuntime: true });
    const result = await session.page.evaluate(() => {
      const LD = window.LegalDesign,
        host = document.createElement("section");
      host.style.cssText = "width:800px";
      document.body.append(host);
      const failures = [];
      // Compact is not permission to omit stages, dates, labels, or details.
      for (const id of LD.registry) {
        const data = window.LibrarySamples[id];
        if (LD.render(id, data) !== LD.render(id, data, { compact: true }))
          failures.push(`${id}: compact output changes supplied content`);
      }
      const stages = Array.from({ length: 6 }, (_, i) => ({
        title: `Stage ${i}`,
        sub: `Description ${i}`,
        detail: `detail-${i}`,
      }));
      const flow = {
        stages,
        edges: stages.slice(1).map((_, i) => `Transition ${i}`),
      };
      host.innerHTML = LD.render("flow", flow, { compact: true });
      const retained = [...host.querySelectorAll("[data-detail]")].map(
        (node) => node.dataset.detail,
      );
      host.innerHTML = LD.render("flow", {
        stages: stages.slice(0, 5),
        edges: flow.edges.slice(0, 4),
      });
      const fiveStage = {
        paths: host.querySelectorAll("path.line").length,
        labels: host.querySelectorAll("text.edge").length,
      };
      const hierarchy = {
        root: "Parent",
        branches: Array.from({ length: 4 }, (_, i) => ({
          title: `Branch ${i}`,
          edge: `Owns ${i}`,
          leaves: [
            { title: `Child ${i}a` },
            { title: `Child ${i}b`, detail: `leaf-${i}` },
          ],
        })),
      };
      host.innerHTML = LD.render("hierarchy", hierarchy, { narrow: true });
      const topology = {
        bus: host.querySelectorAll(".hierarchy-root-bus").length,
        parents: [...host.querySelectorAll(".hierarchy-branch-link")].map(
          (n) => n.dataset.parent,
        ),
        leaves: host.querySelectorAll(".leaf").length,
      };
      const hub = {
        centre: "Principal",
        toward: "centre",
        spokes: Array.from({ length: 6 }, (_, i) => ({
          title: `Party ${i}`,
          edge: `Reports ${i}`,
          detail: `party-${i}`,
        })),
      };
      const directions = [];
      for (const toward of ["centre", "satellites"]) {
        host.innerHTML = LD.render("hub", { ...hub, toward });
        directions.push(
          [...host.querySelectorAll("[data-relationship='spoke']")].map(
            (n) => n.dataset.direction,
          ),
        );
        for (const text of host.querySelectorAll("text.edge"))
          if (getComputedStyle(text).textTransform !== "none")
            failures.push("edge labels force uppercase");
      }
      host.innerHTML = LD.render("dotHeat", {
        rows: ["A", "B"],
        cols: ["X", "Y"],
        values: [
          [0, 1],
          [4, 9],
        ],
        rowAxisTitle: "Row",
        colAxisTitle: "Column",
        unit: "items",
        sourceNote: "Illustrative",
      });
      const radii = [...host.querySelectorAll("circle")].map((n) =>
        Number(n.getAttribute("r")),
      );
      host.remove();
      return {
        failures,
        retained,
        fiveStage,
        topology,
        directions,
        radii,
        recommended: LD.recommendedRegistry,
      };
    });
    assert.deepEqual(result.failures, []);
    assert.deepEqual(result.recommended, [
      "flow",
      "timeline",
      "hierarchy",
      "zones",
      "beforeAfter",
      "hub",
      "compareTwo",
      "rungBars",
      "hairlineLine",
      "stackedRungs",
      "rangeBars",
    ]);
    assert.equal(result.retained.length, 6);
    assert.deepEqual(result.fiveStage, { paths: 8, labels: 4 });
    assert.equal(result.topology.bus, 1);
    assert.deepEqual(result.topology.parents, ["root", "root", "root", "root"]);
    assert.equal(result.topology.leaves, 8);
    assert.deepEqual(result.directions, [
      Array(6).fill("centre"),
      Array(6).fill("satellites"),
    ]);
    assert.equal(result.radii[0], 0, "zero must not have positive dot area");
    assert(
      Math.abs(result.radii[2] / result.radii[1] - 2) < 0.01,
      "quadruple value must have double radius, not quadruple radius",
    );
    await closeClean(session);
  });

  await run(
    "dark diagram surface palette and text contrast across registry",
    async () => {
      const session = await pageFor({ asset: "library", sourceRuntime: true });
      const { page } = session;
      const result = await page.evaluate(() => {
        document.documentElement.setAttribute("data-theme", "dark");
        const host = document.createElement("div");
        host.style.cssText = "width:800px;background:#000";
        document.body.append(host);
        const luminance = (color) => {
          const channels = color
            .match(/[\d.]+/g)
            .slice(0, 3)
            .map(Number)
            .map((n) => {
              const value = n / 255;
              return value <= 0.04045
                ? value / 12.92
                : ((value + 0.055) / 1.055) ** 2.4;
            });
          return (
            channels[0] * 0.2126 + channels[1] * 0.7152 + channels[2] * 0.0722
          );
        };
        const ratio = (a, b) => {
          const x = luminance(a),
            y = luminance(b);
          return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05);
        };
        const failures = [],
          measured = [];
        const catalog = JSON.parse(
          document.getElementById("library-components").textContent,
        ).components;
        const ids = window.LegalDesign.registry.filter(
          (id) => catalog[id].kind !== "chart",
        );
        for (const id of ids)
          for (const mode of ["normal", "narrow", "compact"]) {
            host.innerHTML = window.LegalDesign.render(
              id,
              window.LibrarySamples[id],
              mode === "normal" ? {} : { [mode]: true },
            );
            const svg = host.querySelector("svg");
            const shapes = [
              ...svg.querySelectorAll(".box,.leaf,.band,.tint,.inkfill"),
            ].filter((node) => typeof node.isPointInFill === "function");
            for (const shape of shapes) {
              const style = getComputedStyle(shape);
              const expected = "#111111";
              const swatch = document.createElement("span");
              swatch.style.color = expected;
              host.append(swatch);
              const color = getComputedStyle(swatch).color;
              swatch.remove();
              if (style.fill !== color || Number(style.fillOpacity) !== 1)
                failures.push(
                  `${id}/${mode} ${shape.tagName}.${shape.getAttribute("class")}: ${style.fill} opacity${style.fillOpacity}, expected${color}`,
                );
              const expectedStroke = shape.matches(".accent,.open")
                ? "rgb(255, 90, 78)"
                : "rgb(153, 153, 153)";
              if (style.stroke !== expectedStroke)
                failures.push(
                  `${id}/${mode}: outline ${style.stroke}, expected ${expectedStroke}`,
                );
              if (Number.parseFloat(style.strokeWidth) !== 2)
                failures.push(`${id}/${mode}: node outline must be 2px`);
            }
            for (const node of svg.querySelectorAll("text,.line,.hair")) {
              const style = getComputedStyle(node);
              const color = node.tagName === "text" ? style.fill : style.stroke;
              if (color !== "rgb(255, 255, 255)")
                failures.push(
                  `${id}/${mode}: ${node.tagName} is ${color}, expected white`,
                );
            }
            let count = 0,
              minContrast = 100;
            for (const text of svg.querySelectorAll("text")) {
              const b = text.getBoundingClientRect();
              const center = new DOMPoint(
                b.x + b.width / 2,
                b.y + b.height / 2,
              );
              const shape = shapes
                .toReversed()
                .find((candidate) =>
                  candidate.isPointInFill(
                    center.matrixTransform(candidate.getScreenCTM().inverse()),
                  ),
                );
              if (!shape) continue;
              const contrast = ratio(
                getComputedStyle(text).fill,
                getComputedStyle(shape).fill,
              );
              minContrast = Math.min(minContrast, contrast);
              count += 1;
              if (contrast < 4.5)
                failures.push(
                  `${id}/${mode} ${text.textContent}: contrast${contrast.toFixed(2)} on${getComputedStyle(shape).fill}`,
                );
            }
            measured.push({
              id,
              mode,
              shapes: shapes.length,
              text: count,
              minContrast,
            });
          }
        host.remove();
        return { ids, failures, measured };
      });
      assert.equal(
        result.ids.length,
        14,
        "all fourteen diagram families must use the shared surface contract",
      );
      assert.deepEqual(result.failures, [], JSON.stringify(result.measured));
      assert(
        result.measured.some((item) => item.id === "flow" && item.text > 0),
        "contrast scan omitted node text",
      );

      const probe = await renderFixture(page, "flow", FLOW);
      const paint = await probe.evaluate((node) => {
        const group = node.querySelector("[data-diagram-object]");
        const shape = group.querySelector("rect");
        group.setAttribute("data-fill-token", "tint");
        group.setAttribute("data-text-token", "red");
        const tokenFill = getComputedStyle(shape).fill;
        const tokenText = getComputedStyle(group.querySelector("text")).fill;
        group.removeAttribute("data-fill-token");
        shape.style.fill = "#00aabb";
        return {
          tokenFill,
          tokenText,
          inlineFill: getComputedStyle(shape).fill,
        };
      });
      assert.equal(
        paint.tokenFill,
        "rgb(22, 22, 22)",
        "explicit editor fill token must override the default dark card",
      );
      assert.equal(
        paint.tokenText,
        "rgb(255, 90, 78)",
        "explicit editor text token must override automatic contrasting text",
      );
      assert.equal(
        paint.inlineFill,
        "rgb(0, 170, 187)",
        "custom inline fill must be preserved",
      );
      await closeClean(session);
    },
  );

  await run("diagram refinement geometry and centered contents", async () => {
    for (const narrow of [false, true]) {
      const session = await pageFor({
        asset: "method",
        sourceRuntime: true,
        viewport: narrow
          ? { width: 430, height: 932 }
          : { width: 1440, height: 900 },
      });
      const { page } = session;
      for (const theme of ["light", "dark"]) {
        await page.evaluate(
          (theme) => document.documentElement.setAttribute("data-theme", theme),
          theme,
        );
        for (const [component, params] of [
          ["flow", FLOW],
          ["hierarchy", HIERARCHY],
        ]) {
          const probe = await renderFixture(page, component, params, narrow);
          const measurements = await diagramMeasurements(probe);
          const label = `${component} ${narrow ? "phone" : "desktop"} ${theme}`;
          assert(
            measurements.labels.length > 0,
            `${label}: relationship labels missing`,
          );
          for (const edge of measurements.labels) {
            assert(
              edge.boxClearance >= 12,
              `${label} ${edge.text}: only ${edge.boxClearance}px from a card`,
            );
            const narrowBreak = component === "hierarchy" && !narrow;
            assert(
              edge.connectorClearance >= (narrowBreak ? 1 : 12),
              `${label} ${edge.text}: only ${edge.connectorClearance}px from a connector`,
            );
            if (narrowBreak)
              assert(
                edge.connectorClearance <= 6,
                `${label} ${edge.text}: connector break too wide (${edge.connectorClearance}px)`,
              );
          }
          assert(
            measurements.centered.length > 0,
            `${label}: no semantic labels measured`,
          );
          for (const text of measurements.centered) {
            assert.equal(
              text.anchor,
              "middle",
              `${label} ${text.text}: node label not centered`,
            );
            assert(
              text.offset < 0.01,
              `${label} ${text.text}: node label center drifted`,
            );
          }
          if (theme === "dark") {
            assert.equal(
              measurements.colors.ground,
              "rgb(0, 0, 0)",
              `${label}: ground must be pure black`,
            );
            assert.equal(
              measurements.colors.card,
              "rgb(17, 17, 17)",
              `${label}: diagram nodes must use the raised dark card fill`,
            );
            assert.equal(measurements.colors.outlineWidth, 2);
            assert.equal(measurements.colors.connectorWidth, 1.5);
          }
        }
      }
      await closeClean(session);
    }
  });

  await run(
    "diagram refinement popup target highlighting and focus",
    async () => {
      const session = await pageFor({ asset: "method", sourceRuntime: true });
      const { page } = session;
      for (const theme of ["light", "dark"]) {
        await page.evaluate(
          (theme) => document.documentElement.setAttribute("data-theme", theme),
          theme,
        );
        const probe = await renderFixture(page, "hierarchy", HIERARCHY);
        const INTERACTION =
          theme === "dark" ? "rgb(160, 160, 156)" : "rgb(118, 118, 118)";
        const output = probe.locator('[data-detail="src-exports"]');
        const neutralStroke =
          theme === "dark" ? "rgb(153, 153, 153)" : TRANSPARENT;
        await output.hover();
        const hover = await outlineState(output);
        assert.equal(
          hover.primary,
          INTERACTION,
          `${theme}: hovered popup must use the interaction outline`,
        );
        assert(
          hover.leaves.every((stroke) => stroke !== hover.primary),
          `${theme}: child cards with shared popup must not highlight separately`,
        );
        await output.click();
        assert.equal(await page.locator("#src-exports").isVisible(), true);
        await page.locator("#src-exports .ld-popup-close").click();
        await page.mouse.move(1, 1);
        assert.equal(
          await output.evaluate((node) => node === document.activeElement),
          true,
          "closing a popup must restore focus",
        );
        assert.equal(
          (await outlineState(output)).primary,
          neutralStroke,
          `${theme}: pointer-opened popup must restore its neutral outline`,
        );
        await page.keyboard.press("Tab");
        await output.focus();
        assert.equal(
          (await outlineState(output)).primary,
          INTERACTION,
          `${theme}: keyboard focus has no indicator`,
        );
        assert(
          (await outlineState(output)).leaves.every(
            (stroke) => stroke !== hover.primary,
          ),
          `${theme}: keyboard focus highlights unrelated leaves`,
        );
        await page.keyboard.press("Enter");
        assert.equal(await page.locator("#src-exports").isVisible(), true);
        await page.keyboard.press("Escape");
        assert.equal(
          await output.evaluate((node) => node === document.activeElement),
          true,
        );
        assert.equal(
          (await outlineState(output)).primary,
          INTERACTION,
          `${theme}: keyboard return focus lost its indicator`,
        );

        const independent = structuredClone(HIERARCHY);
        independent.branches[2].leaves[0].detail = "src-treatments";
        const ownProbe = await renderFixture(page, "hierarchy", independent);
        const ownLeaf = ownProbe.locator('[data-detail="src-treatments"]');
        const ownOutput = ownProbe.locator('[data-detail="src-exports"]');
        assert.equal(
          await ownOutput.locator('[data-detail="src-treatments"]').count(),
          0,
          "independent popup targets must not be nested",
        );
        await ownLeaf.hover();
        assert.equal((await outlineState(ownLeaf)).primary, INTERACTION);
        assert.equal(
          (await outlineState(ownOutput)).primary,
          neutralStroke,
          "independent child hover must not highlight parent",
        );
        await ownLeaf.click();
        assert.equal(
          await page.locator("#src-treatments").isVisible(),
          true,
          "independent child opens wrong popup",
        );
        await page.locator("#src-treatments .ld-popup-close").click();
      }
      await closeClean(session);
    },
  );

  await run("diagram refinement selectable nodes without popups", async () => {
    const session = await pageFor({ asset: "method", sourceRuntime: true });
    const { page } = session;
    const plain = structuredClone(FLOW);
    plain.stages.forEach((stage) => {
      delete stage.detail;
    });
    const probe = await renderFixture(page, "flow", plain);
    const nodes = probe.locator("svg > [data-diagram-object]");
    assert.equal(
      await nodes.count(),
      plain.stages.length,
      "every semantic node must be available to the editor",
    );
    const attributes = await nodes.evaluateAll((nodes) =>
      nodes.map((node) => ({
        detail: node.getAttribute("data-detail"),
        role: node.getAttribute("role"),
        cursor: getComputedStyle(node).cursor,
        title: node.querySelector("text")?.textContent,
        shape: !!node.querySelector(":scope > rect"),
      })),
    );
    for (const node of attributes) {
      assert.equal(node.detail, null);
      assert.equal(
        node.role,
        null,
        `${node.title}: no-popup node should not pretend to be a button`,
      );
      assert.notEqual(
        node.cursor,
        "pointer",
        `${node.title}: no-popup node falsely signals a click action`,
      );
      assert.equal(
        node.shape,
        true,
        `${node.title}: node group omitted its card`,
      );
    }
    await closeClean(session);
  });
}
