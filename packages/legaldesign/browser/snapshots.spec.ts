import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { pathToFileURL } from "node:url";

const HERE = dirname(new URL(import.meta.url).pathname);
const REPO = resolve(HERE, "../../..");
const LIBRARY = join(REPO, "skills/core/legaldesign/assets/library.html");
const SNAPSHOTS = join(REPO, "packages/legaldesign/fixtures/snapshots.json");
const LIBRARY_OUT = join(HERE, "out/library");
const LIBRARY_URL = pathToFileURL(LIBRARY).href;
const THEMES = ["light", "dark"];
const WIDTHS = ["laptop", "phone"];

function sha256(value) {
  return createHash("sha256").update(value, "utf8").digest("hex");
}

function snapshotPayload(renders) {
  const payload = {};
  for (const { id, theme, svg } of renders) {
    payload[id] ||= {};
    payload[id][theme] = sha256(svg);
  }
  return payload;
}

async function libraryPage(pageFor, options = {}) {
  return pageFor({
    url: LIBRARY_URL,
    viewport: options.viewport || { width: 1280, height: 900 },
    ready: () =>
      Array.isArray(window.LegalDesign?.registry) &&
      window.LibrarySamples &&
      Object.keys(window.LibrarySamples).length ===
        window.LegalDesign.registry.length,
  });
}

async function setTheme(page, theme) {
  const current = await page.locator("html").getAttribute("data-theme");
  if (current !== theme) await page.click("#theme-toggle");
  assert.equal(await page.locator("html").getAttribute("data-theme"), theme);
}

async function setWidth(page, width) {
  const current =
    (await page.locator("html").getAttribute("data-library-width")) || "laptop";
  if (current !== width) await page.click("#width-toggle");
  assert.equal(
    (await page.locator("html").getAttribute("data-library-width")) || "laptop",
    width,
  );
}

async function renderSnapshotStrings(page) {
  return page.evaluate(
    ({ themes }) => {
      const output = [];
      const catalog = JSON.parse(
        document.getElementById("library-components").textContent,
      ).components;
      for (const id of window.LegalDesign.registry) {
        const contract = catalog[id];
        if (!contract) throw new Error(`component contract missing for ${id}`);
        const data = window.LibrarySamples[id];
        if (!data) throw new Error(`library demo data missing for ${id}`);
        for (const theme of themes) {
          const opts = { theme };
          if (contract.kind === "chart") opts.width = "360";
          const svg = window.LegalDesign.render(id, data, opts);
          const repeated = window.LegalDesign.render(id, data, opts);
          if (svg !== repeated) throw new Error(`${id} is not deterministic`);
          output.push({ id, theme, svg });
        }
      }
      return output;
    },
    { themes: THEMES },
  );
}

async function appendCompatibilityTiles(page) {
  await page.evaluate(() => {
    const catalog = JSON.parse(
      document.getElementById("library-components").textContent,
    ).components;
    const grid = document.createElement("section");
    grid.id = "compatibility-test-tiles";
    grid.className = "library-grid";
    document.querySelector("main").append(grid);
    for (const id of window.LegalDesign.registry) {
      if (document.querySelector(`figure[data-component="${id}"]`)) continue;
      const tile = document.createElement("figure");
      tile.className = "library-tile";
      tile.dataset.component = id;
      tile.dataset.kind = catalog[id].kind;
      const caption = document.createElement("figcaption");
      caption.textContent = `${id} — compatibility coverage`;
      const stage = document.createElement("div");
      stage.className = "library-stage";
      stage.dataset.render = id;
      tile.append(caption, stage);
      grid.append(tile);
    }
    window.LibraryRenderAll();
  });
}

async function screenshotTiles(page, theme, width) {
  await setTheme(page, theme);
  await setWidth(page, width);
  assert.equal(
    await page.locator("[data-render].err").count(),
    0,
    `${theme} ${width}: a library component failed to render`,
  );
  const ids = await page
    .locator("figure.library-tile")
    .evaluateAll((tiles) => tiles.map((tile) => tile.dataset.component));
  assert.deepEqual(
    ids,
    await page.evaluate(() => window.LegalDesign.recommendedRegistry),
  );
  // The public catalog is small; screenshot coverage still includes every
  // renderer needed to reopen an old exported HTML file.
  await appendCompatibilityTiles(page);
  const allIds = await page.evaluate(() => window.LegalDesign.registry);
  const shots = [];
  for (const id of allIds) {
    assert.equal(typeof id, "string");
    const name = `${id}-${theme}-${width}.png`;
    await page.locator(`figure[data-component="${id}"]`).screenshot({
      path: join(LIBRARY_OUT, name),
      animations: "disabled",
    });
    shots.push(name);
  }
  await page
    .locator("#compatibility-test-tiles")
    .evaluate((node) => node.remove());
  return shots;
}

async function checkDiagramSurfaceIntegrity(page) {
  const hierarchy = page.locator('[data-render="hierarchy"]');
  const hierarchyLayout = await hierarchy.evaluate((root) => {
    const exactText = (value) =>
      [...root.querySelectorAll("text")].find(
        (node) =>
          node.textContent.replace(/\s+/g, "") === value.replace(/\s+/g, ""),
      );
    const sub = exactText("Principal terms");
    const leaves = [
      exactText("Disclosure schedules"),
      exactText("Officer certificate"),
    ].filter(Boolean);
    if (!sub || leaves.length !== 2) return null;
    const subBox = sub.getBoundingClientRect();
    return {
      subBottom: subBox.bottom,
      firstLeafTop: Math.min(
        ...leaves.map((node) => node.getBoundingClientRect().top),
      ),
    };
  });
  assert(hierarchyLayout, "hierarchy sample labels are missing");
  assert(
    hierarchyLayout.subBottom + 2 <= hierarchyLayout.firstLeafTop,
    `hierarchy branch subline overlaps its leaves (${JSON.stringify(hierarchyLayout)})`,
  );

  const hub = page.locator('[data-render="hub"]');
  const hubText = (await hub.locator("svg").textContent()).trim();
  assert.equal(
    /hub-(finance|operations|privacy|board)/.test(hubText),
    false,
    "hub leaked popup identifiers onto the visible surface",
  );
  assert.equal(
    await hub.locator('svg .hub-arrowhead[data-direction="centre"]').count(),
    4,
    "hub did not visibly encode every relationship toward the centre",
  );
}

async function chartMetrics(page, width) {
  await setWidth(page, width);
  return page.evaluate(() => {
    const overlaps = (nodes) => {
      let count = 0;
      const boxes = nodes.map((node) => node.getBoundingClientRect());
      for (let left = 0; left < boxes.length; left += 1) {
        for (let right = left + 1; right < boxes.length; right += 1) {
          const a = boxes[left];
          const b = boxes[right];
          const width = Math.min(a.right, b.right) - Math.max(a.left, b.left);
          const height = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
          if (width > 0.5 && height > 0.5) count += 1;
        }
      }
      return count;
    };
    return window.LegalDesign.registry
      .map((id) => {
        const tile = document.querySelector(
          `figure[data-component="${id}"][data-kind="chart"]`,
        );
        if (!tile) return null;
        const svg = tile.querySelector("svg");
        const labels = [...svg.querySelectorAll("text")];
        const dataLabels = [...svg.querySelectorAll(".data-label")];
        return {
          id,
          minLabelPx: Math.min(
            ...labels.map((label) =>
              Number.parseFloat(getComputedStyle(label).fontSize),
            ),
          ),
          overlaps: overlaps(dataLabels),
          baseline: svg.dataset.baseline || "not-declared",
          dataLabelCount: dataLabels.length,
        };
      })
      .filter(Boolean);
  });
}

async function checkHierarchyDetail(page) {
  const hierarchy = page.locator('[data-render="hierarchy"]');
  const triggers = hierarchy.locator("[data-detail]");
  const details = await triggers.evaluateAll((nodes) =>
    nodes.map((node) => node.getAttribute("data-detail")),
  );
  assert(
    details.length >= 3,
    "hierarchy demo must cover root, branch, and leaf detail",
  );
  assert.equal(new Set(details).size, details.length);
  for (const trigger of await triggers.all()) {
    await trigger.focus();
    assert.equal(
      await trigger.evaluate((node) => node === document.activeElement),
      true,
    );
    await page.keyboard.press("Enter");
    assert.equal(await page.locator("#popup-scrim").isVisible(), true);
    await page.keyboard.press("Escape");
    assert.equal(await page.locator("#popup-scrim").isHidden(), true);
    assert.equal(
      await trigger.evaluate((node) => node === document.activeElement),
      true,
    );
  }
}

export async function runSnapshotSuite({ run, pageFor, closeClean }) {
  assert(existsSync(LIBRARY), `missing ${LIBRARY}`);
  mkdirSync(LIBRARY_OUT, { recursive: true });

  await run("component SVG snapshot hashes", async () => {
    const session = await libraryPage(pageFor);
    const renders = await renderSnapshotStrings(session.page);
    const actual = snapshotPayload(renders);
    if (process.argv.includes("--update-snapshots"))
      writeFileSync(SNAPSHOTS, `${JSON.stringify(actual, null, 2)}\n`);
    assert(existsSync(SNAPSHOTS), `missing ${SNAPSHOTS}`);
    assert.deepEqual(
      actual,
      JSON.parse(readFileSync(SNAPSHOTS, "utf8")),
      "component markup changed; inspect it and run test:browser -- --update-snapshots",
    );
    assert.equal(Object.keys(actual).length, 31);
    await closeClean(session);
  });

  await run("hierarchy detail at every level", async () => {
    const session = await libraryPage(pageFor);
    await checkHierarchyDetail(session.page);
    await closeClean(session);
  });

  await run("library tile screenshots and chart metrics", async () => {
    const sessions = [];
    const shots = [];
    try {
      for (const width of WIDTHS) {
        const session = await libraryPage(pageFor, {
          viewport:
            width === "phone"
              ? { width: 430, height: 932 }
              : { width: 1280, height: 900 },
        });
        sessions.push(session);
        for (const theme of THEMES)
          shots.push(...(await screenshotTiles(session.page, theme, width)));
      }
      assert.equal(shots.length, 31 * THEMES.length * WIDTHS.length);
      for (const shot of shots)
        assert(existsSync(join(LIBRARY_OUT, shot)), shot);

      const metricsSession = sessions[0];
      await setTheme(metricsSession.page, "light");
      await setWidth(metricsSession.page, "laptop");
      await checkDiagramSurfaceIntegrity(metricsSession.page);
      await appendCompatibilityTiles(metricsSession.page);
      const card = await chartMetrics(metricsSession.page, "laptop");
      const narrow = await chartMetrics(metricsSession.page, "phone");
      assert.equal(card.length, 17);
      assert.equal(narrow.length, 17);
      console.log(
        "| chart | card min label | narrow min label | data-label overlaps | baseline |",
      );
      console.log("|---|---:|---:|---:|---|");
      for (const cardMetric of card) {
        const narrowMetric = narrow.find(({ id }) => id === cardMetric.id);
        assert(narrowMetric);
        assert(
          cardMetric.minLabelPx >= 11,
          `${cardMetric.id}: card labels below 11px`,
        );
        assert(
          narrowMetric.minLabelPx >= 11,
          `${cardMetric.id}: narrow labels below 11px`,
        );
        assert.equal(
          cardMetric.overlaps,
          0,
          `${cardMetric.id}: card data-label overlap`,
        );
        assert.equal(
          narrowMetric.overlaps,
          0,
          `${cardMetric.id}: narrow data-label overlap`,
        );
        assert.notEqual(
          cardMetric.baseline,
          "not-declared",
          `${cardMetric.id}: baseline missing`,
        );
        console.log(
          `| ${cardMetric.id} | ${cardMetric.minLabelPx.toFixed(2)}px | ${narrowMetric.minLabelPx.toFixed(2)}px | ${cardMetric.overlaps}/${narrowMetric.overlaps} | ${cardMetric.baseline} |`,
        );
      }
      console.log(`Library tile screenshots (${shots.length}): ${LIBRARY_OUT}`);
    } finally {
      for (const session of sessions) await closeClean(session);
    }
  });
}
