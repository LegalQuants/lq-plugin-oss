import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { chromium } from "@playwright/test";

const repo = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const out = resolve(
  process.env.LEGALDESIGN_ZOOM_OUT ||
    mkdtempSync(join(tmpdir(), "legaldesign-pinch-zoom-")),
);
mkdirSync(out, { recursive: true });
console.log("Pinch-zoom evidence: " + out);
const source = join(out, "working.html");
const result = spawnSync(
  process.env.LEGALDESIGN_PYTHON || "python3",
  [
    "skills/core/legaldesign/scripts/scaffold.py",
    "compose",
    "--plan",
    "packages/legaldesign/templates/slide-brief.plan.json",
    "--spec-output",
    join(out, "spec.json"),
    "--output",
    source,
    "--artifact-id",
    "pinch-zoom-regression",
  ],
  { cwd: repo, encoding: "utf8" },
);
assert.equal(result.status, 0, result.stdout + result.stderr);
// Exercise canonical source without rebuilding or modifying packaged assets.
// A maintainer can rerun against a saved pre-fix artifact to establish a red test.
const scriptPattern = /(<script id="ld-runtime">)[\s\S]*?(<\/script>)/;
let runtime = readFileSync(
  join(repo, "packages/legaldesign/runtime/runtime.js"),
  "utf8",
);
if (process.env.LEGALDESIGN_ZOOM_RUNTIME_HTML) {
  const prior = readFileSync(process.env.LEGALDESIGN_ZOOM_RUNTIME_HTML, "utf8");
  const match = prior.match(/<script id="ld-runtime">([\s\S]*?)<\/script>/);
  assert(match, "prior artifact contains trusted runtime script");
  runtime = match[1];
}
assert(scriptPattern.test(readFileSync(source, "utf8")));
writeFileSync(
  source,
  readFileSync(source, "utf8").replace(
    scriptPattern,
    (_, start, end) => start + runtime + end,
  ),
);
const browser = await chromium.launch({
  headless: true,
  executablePath: [
    chromium.executablePath(),
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  ].find(existsSync),
});
const measurements = [],
  faults = [];
const near = (a, b, label, tolerance = 0.001) =>
  assert(
    Math.abs(Number(a) - Number(b)) <= tolerance,
    label + ": " + a + " vs " + b,
  );
async function settle(page) {
  await page.evaluate(
    () =>
      new Promise((resolve) =>
        requestAnimationFrame(() => requestAnimationFrame(resolve)),
      ),
  );
}
async function open(path) {
  const context = await browser.newContext({
    viewport: { width: 390, height: 844 },
    deviceScaleFactor: 2,
    isMobile: true,
    hasTouch: true,
  });
  const page = await context.newPage();
  page.on("pageerror", (e) => faults.push(e.message));
  await page.addInitScript(() => {
    window.zoomEvents = [];
    window.visualViewport.addEventListener("resize", () =>
      window.zoomEvents.push({ type: "visual", scale: visualViewport.scale }),
    );
    window.addEventListener("resize", () =>
      window.zoomEvents.push({ type: "window", scale: visualViewport.scale }),
    );
  });
  await page.goto(pathToFileURL(path).href);
  await page.waitForFunction(
    () => document.documentElement.dataset.legaldesignReady === "true",
  );
  await page.locator("#ld-page-reader").waitFor({ state: "visible" });
  await settle(page);
  return { context, page, cdp: await context.newCDPSession(page) };
}
async function measure(page, label, screenshot = false) {
  await settle(page);
  const data = await page.evaluate(() => {
    const root = document.documentElement,
      reader = document.getElementById("ld-page-reader");
    const stage = document.querySelector(".ld-fixed-page");
    return {
      layout: { width: root.clientWidth, height: root.clientHeight },
      inner: { width: innerWidth, height: innerHeight },
      visual: {
        width: visualViewport.width,
        height: visualViewport.height,
        scale: visualViewport.scale,
      },
      stage: Object.fromEntries(
        ["scale", "width", "height", "left", "top"].map((key) => [
          key,
          parseFloat(root.style.getPropertyValue("--ld-page-" + key)),
        ]),
      ),
      reader: {
        font: parseFloat(getComputedStyle(reader.querySelector("p")).fontSize),
        width: reader.getBoundingClientRect().width,
        visible: !!reader.getClientRects().length,
      },
      bodyFont: parseFloat(
        getComputedStyle(stage.querySelector("[data-variant-body]")).fontSize,
      ),
      state: JSON.stringify(LegalDesign.state()),
      events: window.zoomEvents,
      meta: document.querySelector('meta[name="viewport"]').content,
    };
  });
  measurements.push({ label, ...data });
  if (screenshot) await page.screenshot({ path: join(out, label + ".png") });
  return data;
}
function unchanged(base, value, label) {
  assert.deepEqual(
    value.layout,
    base.layout,
    label + ": pinch does not change layout viewport",
  );
  for (const key of Object.keys(base.stage))
    near(value.stage[key], base.stage[key], label + ": stage " + key);
  near(value.reader.font, base.reader.font, label + ": reader CSS font");
  if (base.reader.visible)
    near(value.reader.width, base.reader.width, label + ": reader width");
  assert.equal(
    value.state,
    base.state,
    label + ": zoom must not edit/rewrite document state",
  );
  assert(
    !/user-scalable\s*=\s*(?:no|0)|maximum-scale\s*=\s*1(?:[,\s]|$)/i.test(
      value.meta,
    ),
    "native pinch accessibility must not be disabled",
  );
}
async function webkitContract(page) {
  // WebKit bug245361 documents innerWidth/innerHeight following the visual
  // viewport during pinch. Chromium's native behavior differs, so this shim
  // models only that API contract while CDP supplies actual browser page-scale.
  // This is not a Safari or physical iPhone test.
  await page.evaluate(() => {
    Object.defineProperty(window, "innerWidth", {
      configurable: true,
      get: () => visualViewport.width,
    });
    Object.defineProperty(window, "innerHeight", {
      configurable: true,
      get: () => visualViewport.height,
    });
    visualViewport.addEventListener("resize", () =>
      dispatchEvent(new Event("resize")),
    );
  });
}
async function zoomSeries(session, label, compatibility) {
  const { page, cdp } = session;
  if (compatibility) await webkitContract(page);
  const base = await measure(page, label + "-baseline", true);
  for (let cycle = 0; cycle < 2; cycle++) {
    for (const scale of [1.5, 2, 3, 1]) {
      await cdp.send("Emulation.setPageScaleFactor", {
        pageScaleFactor: scale,
      });
      const value = await measure(
        page,
        label + "-" + cycle + "-" + scale,
        cycle === 0 && scale === 3,
      );
      near(value.visual.scale, scale, label + ": browser zoom applied");
      unchanged(base, value, label + " cycle" + cycle + " scale" + scale);
      near(
        value.stage.scale * value.visual.scale,
        base.stage.scale * scale,
        label + ": visible page magnifies",
      );
    }
  }
  return base;
}
try {
  const original = await open(source);
  await zoomSeries(original, "native-reader", false);
  // Dispatch two real touch contacts. synthesizePinchGesture can acknowledge
  // without changing page scale in headless Chromium, even on a plain page.
  await original.cdp.send("Input.dispatchTouchEvent", {
    type: "touchStart",
    touchPoints: [
      { id: 0, x: 150, y: 350 },
      { id: 1, x: 210, y: 350 },
    ],
  });
  for (let step = 1; step <= 12; step += 1) {
    await original.cdp.send("Input.dispatchTouchEvent", {
      type: "touchMove",
      touchPoints: [
        { id: 0, x: 150 - step * 6, y: 350 },
        { id: 1, x: 210 + step * 6, y: 350 },
      ],
    });
    await settle(original.page);
  }
  await original.cdp.send("Input.dispatchTouchEvent", {
    type: "touchEnd",
    touchPoints: [],
  });
  await original.page.waitForFunction(() => visualViewport.scale > 1.8);
  const touch = await measure(original.page, "native-touch-pinch", true);
  assert(
    touch.visual.scale > 1.8,
    "synthesized native touch pinch actually zoomed",
  );
  near(touch.reader.font, 18, "native pinch retains readable reader CSS type");
  await original.cdp.send("Emulation.setPageScaleFactor", {
    pageScaleFactor: 1,
  });
  await original.page.keyboard.press("Escape");
  const canvasBase = await zoomSeries(original, "webkit-contract-canvas", true);
  await original.page.locator("#ld-read-page").click();
  await zoomSeries(original, "webkit-contract-reader", false);
  await original.page.keyboard.press("Escape");

  // A real viewport resize still refits, even if the browser is currently zoomed.
  await original.cdp.send("Emulation.setPageScaleFactor", {
    pageScaleFactor: 2,
  });
  await original.page.setViewportSize({ width: 430, height: 932 });
  const resized = await measure(original.page, "resized-while-zoomed", true);
  assert.equal(resized.layout.width, 430);
  assert(
    resized.stage.scale > canvasBase.stage.scale,
    "real wider viewport changes fit",
  );
  near(
    resized.stage.scale,
    (430 - 80) / 1200,
    "real resize uses layout width, not zoomed visual width",
  );
  await original.cdp.send("Emulation.setPageScaleFactor", {
    pageScaleFactor: 1,
  });
  const restored = await measure(original.page, "resized-zoom-reset");
  for (const key of Object.keys(resized.stage))
    near(restored.stage[key], resized.stage[key], "unzoom after resize " + key);

  // On desktop, crossing760 visual pixels must not activate the phone layout.
  await original.page.setViewportSize({ width: 1280, height: 800 });
  const desktop = await measure(original.page, "desktop-baseline", true);
  near(desktop.stage.scale, 1, "stable desktop scale");
  near(desktop.bodyFont, 16, "stable desktop16px type");
  await original.cdp.send("Emulation.setPageScaleFactor", {
    pageScaleFactor: 2,
  });
  const desktopZoom = await measure(original.page, "desktop-zoom2", true);
  unchanged(
    desktop,
    desktopZoom,
    "desktop pinch across phone visual breakpoint",
  );
  await original.cdp.send("Emulation.setPageScaleFactor", {
    pageScaleFactor: 1,
  });

  // Keep a real actively edited node and its value during visual-only resizes.
  await original.page.locator("#mode-toggle").click();
  const editable = original.page
    .locator('[data-unit="facts"] [data-editable]')
    .first();
  await editable.dblclick();
  await editable.fill("Reviewed facts retained during native zoom.");
  await editable.evaluate((node) => {
    window.zoomEditingNode = node;
  });
  await original.cdp.send("Emulation.setPageScaleFactor", {
    pageScaleFactor: 2,
  });
  await settle(original.page);
  assert(
    await original.page.evaluate(
      () =>
        window.zoomEditingNode.isConnected &&
        document.activeElement === window.zoomEditingNode,
    ),
    "pinch does not rerender or blur the active editor",
  );
  assert.match(await editable.innerText(), /Reviewed facts retained/);
  await original.cdp.send("Emulation.setPageScaleFactor", {
    pageScaleFactor: 1,
  });
  await original.page.locator("#mode-toggle").click();
  const client = join(out, "client.html"),
    template = join(out, "template.html");
  writeFileSync(
    client,
    await original.page.evaluate(() => LegalDesign.exportHTML(false)),
  );
  writeFileSync(
    template,
    await original.page.evaluate(() => LegalDesign.exportTemplate(false)),
  );
  await original.context.close();
  for (const [label, path] of [
    ["client", client],
    ["template", template],
  ]) {
    const session = await open(path);
    await zoomSeries(session, label + "-native-reader", false);
    await session.page.keyboard.press("Escape");
    await zoomSeries(session, label + "-webkit-contract-canvas", true);
    await session.context.close();
  }
  assert.deepEqual(faults, []);
  console.log(
    "PASS: native page-scale/touch pinch; repeated WebKit-contract zoom; real viewport resize; desktop type; active editor; client/template reopen. No physical-device verification.",
  );
} finally {
  writeFileSync(
    join(out, "measurements.json"),
    JSON.stringify(measurements, null, 2),
  );
  await browser.close();
}
