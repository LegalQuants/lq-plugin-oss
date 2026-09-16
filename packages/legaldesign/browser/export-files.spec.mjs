import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import {
  copyFileSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  statSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { chromium } from "@playwright/test";

const repo = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const out = mkdtempSync(join(tmpdir(), "legaldesign-file-exports-"));
const downloads = join(out, "browser-downloads");
mkdirSync(downloads);
const source = join(
  repo,
  "skills/core/legaldesign/assets/stacked-explainer.html",
);
const original = readFileSync(source, "utf8");
const runtime = join(repo, "packages/legaldesign/runtime");
const block = `<!-- legaldesign:runtime --><style id="ld-tokens">${readFileSync(join(runtime, "tokens.css"), "utf8")}</style><script id="ld-components">${readFileSync(join(runtime, "components.js"), "utf8")}</script><script id="ld-runtime">${readFileSync(join(runtime, "runtime.js"), "utf8")}</script><!-- /legaldesign:runtime -->`;
const fixture = join(out, "source-copy.html");
const fixtureSource = original.replace(
  /<!-- legaldesign:runtime -->[\s\S]*?<!-- \/legaldesign:runtime -->/,
  () => block,
);
writeFileSync(fixture, fixtureSource);
const executablePath = [
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  chromium.executablePath(),
].find(existsSync);
assert(
  executablePath,
  "A local browser is required for actual file export verification",
);
const browser = await chromium.launch({
  executablePath,
  headless: true,
  downloadsPath: downloads,
});
const actions = [
  { kind: "client", selector: "#export-html" },
  { kind: "template", selector: "#export-template" },
  { kind: "working", selector: "#ld-save" },
];

async function open(
  mode = "fallback",
  sourcePath = fixture,
  viewport = { width: 1440, height: 900 },
) {
  const context = await browser.newContext({
    acceptDownloads: true,
    viewport,
  });
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.exposeFunction("writePickedHTML", (name, html) => {
    assert(/^[a-z0-9-]+\.html$/.test(name));
    writeFileSync(join(out, name), html);
  });
  await page.addInitScript(
    ({ mode }) => {
      localStorage.clear();
      window.pickerCalls = [];
      window.pickerMode = mode;
      window.pickedName = "picked.html";
      Object.defineProperty(window, "showSaveFilePicker", {
        configurable: true,
        value:
          mode === "fallback"
            ? undefined
            : async (options) => {
                window.pickerCalls.push({
                  name: options.suggestedName,
                  id: options.id,
                  startIn: options.startIn?.name || null,
                  active: navigator.userActivation.isActive,
                });
                if (window.pickerMode === "cancel")
                  throw new DOMException("Canceled", "AbortError");
                const name = window.pickedName;
                return {
                  name,
                  async createWritable() {
                    let value;
                    return {
                      async write(html) {
                        if (window.pickerMode === "write-error")
                          throw new DOMException(
                            "Read only",
                            "NotAllowedError",
                          );
                        value = html;
                      },
                      async close() {
                        await window.writePickedHTML(name, value);
                      },
                      async abort() {
                        window.writeAborted = true;
                      },
                    };
                  },
                };
              },
      });
    },
    { mode },
  );
  await page.goto(pathToFileURL(sourcePath).href);
  await page.waitForFunction(
    () =>
      window.LegalDesign?.ready === true ||
      (window.LegalDesign?.state && document.querySelector(".ld-diagram svg")),
  );
  return { page, context, errors, mode };
}

async function verifyFile(context, path, kind) {
  assert(existsSync(path), `${kind}: browser did not create a file`);
  assert(statSync(path).size > 10000, `${kind}: file is unexpectedly short`);
  const html = readFileSync(path, "utf8");
  assert.match(html, /<!doctype html/i);
  assert.doesNotMatch(html, /<a[^>]+class="ld-download-link"/);
  assert.doesNotMatch(html, /<div[^>]+class="ld-save-banner"/);
  if (kind === "client") {
    assert.doesNotMatch(
      html,
      /showSaveFilePicker|createWritable|persistHTML|\.download\s*=/,
    );
    assert.doesNotMatch(html, /id="ld-client-runtime"|id="ld-response-save"/);
  } else {
    assert.match(html, /showSaveFilePicker/);
  }
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto(pathToFileURL(path).href);
  await page.waitForFunction(
    () =>
      window.LegalDesign?.state && document.querySelector(".ld-diagram svg"),
  );
  assert.equal(
    await page.locator("html").getAttribute("data-exported"),
    kind === "working" ? null : kind,
  );
  assert((await page.locator(".ld-diagram svg").count()) > 0);
  if (kind === "client") {
    assert.deepEqual(
      await page.evaluate(() => [
        typeof LegalDesign.save,
        typeof LegalDesign.exportHTML,
        typeof LegalDesign.exportTemplate,
      ]),
      ["undefined", "undefined", "undefined"],
    );
    const theme = await page.locator("html").getAttribute("data-theme");
    await page.locator("#theme-toggle").click();
    assert.notEqual(
      await page.locator("html").getAttribute("data-theme"),
      theme,
    );
    const trigger = page
      .locator("[data-detail],[data-evidence]")
      .filter({ visible: true })
      .first();
    if (await trigger.count()) {
      await trigger.click();
      assert(await page.locator(".pop").filter({ visible: true }).count());
      await page.keyboard.press("Escape");
    }
  }
  assert.deepEqual(errors, [], `${kind}: downloaded file failed on reopen`);
  await page.close();
  return html;
}

async function verifyPreview(
  session,
  html,
  { keepOpen = false, approach } = {},
) {
  await session.page.evaluate(
    () =>
      new Promise((resolve) =>
        requestAnimationFrame(() => requestAnimationFrame(resolve)),
      ),
  );
  const geometry = await session.page.evaluate(() => {
    const box = (node) => node?.getBoundingClientRect().toJSON();
    const link = document.querySelector(".ld-export-preview");
    const rect = box(link);
    const hit = document.elementFromPoint(
      rect.left + rect.width / 2,
      rect.top + rect.height / 2,
    );
    return {
      bar: box(document.querySelector(".ld-bar")),
      ab: box(document.querySelector("#ld-page-approach")),
      notice: box(document.querySelector(".ld-save-banner")),
      pages: [...document.querySelectorAll(".ld-fixed-page")]
        .filter(
          (node) =>
            !node.closest("[hidden]") &&
            node.getBoundingClientRect().height > 0,
        )
        .map(box),
      link: rect,
      hit: hit === link || link.contains(hit),
      width: innerWidth,
      height: innerHeight,
    };
  });
  assert(
    geometry.notice.top >=
      Math.max(geometry.bar.bottom, geometry.ab?.bottom || 0) + 4,
    JSON.stringify(geometry),
  );
  assert(
    geometry.pages.every((box) => box.top >= geometry.notice.bottom + 9),
    JSON.stringify(geometry),
  );
  assert(
    geometry.link.height >= 44 &&
      geometry.link.left >= 0 &&
      geometry.link.right <= geometry.width &&
      geometry.link.bottom <= geometry.height &&
      geometry.hit,
    JSON.stringify(geometry),
  );
  const link = session.page.getByRole("link", {
    name: "Open exported HTML",
    exact: true,
  });
  assert.equal(await link.count(), 1);
  assert.equal(await link.getAttribute("target"), "_blank");
  assert.equal(await link.getAttribute("rel"), "noopener noreferrer");
  const url = await link.getAttribute("href");
  assert.equal(
    await session.page.evaluate(async (url) => (await fetch(url)).text(), url),
    html,
    "Client preview is not the exact saved/downloaded snapshot",
  );
  const pending = session.context.waitForEvent("page");
  await link.click();
  const preview = await pending;
  await preview.waitForLoadState("load");
  await preview.waitForFunction(
    () => document.documentElement.dataset.legaldesignReady === "true",
  );
  assert.equal(await preview.evaluate(() => window.opener), null);
  assert.equal(
    await preview.locator("html").getAttribute("data-exported"),
    "client",
  );
  assert.equal(
    await preview
      .locator(
        "[data-editor-only],#export-html,#export-template,.ld-export-preview",
      )
      .count(),
    0,
  );
  if (approach) {
    assert.deepEqual(
      await preview
        .locator("[data-approach]")
        .evaluateAll((nodes) => nodes.map((node) => node.dataset.approach)),
      [approach],
    );
  }
  if (!keepOpen) await preview.close();
  return { preview, url };
}

try {
  // Real isolated Chrome downloads: inspect its completed disk file before
  // making a named test copy. No synthetic Blob interception or saveAs rescue.
  const fallback = await open();
  await fallback.page.clock.install();
  await fallback.page.evaluate(() => {
    const note = document.createElement("div");
    note.id = "ld-restore-banner";
    note.textContent = "Recovery available";
    document.body.append(note);
  });
  for (const action of actions) {
    if (action.kind === "working") await fallback.page.click("#mode-toggle");
    const pending = fallback.page.waitForEvent("download");
    await fallback.page.click(action.selector);
    const download = await pending;
    if (action.kind === "client")
      assert.equal(download.suggestedFilename(), "source-copy.client.html");
    assert.equal(await download.failure(), null);
    const actualPath = await download.path();
    assert(
      actualPath && existsSync(actualPath),
      `${action.kind}: browser reported a download but no actual file exists`,
    );
    const named = join(out, `download-${action.kind}.html`);
    copyFileSync(actualPath, named);
    assert.equal(statSync(named).size, statSync(actualPath).size);
    const html = await verifyFile(fallback.context, named, action.kind);
    if (action.kind === "client") {
      await fallback.page.clock.fastForward(16001);
      await verifyPreview(fallback, html);
    } else
      assert.equal(
        await fallback.page.locator(".ld-export-preview").count(),
        0,
      );
    assert.match(
      await fallback.page.locator(".ld-save-banner").textContent(),
      /Download requested.*cannot confirm it reached disk/,
    );
    assert.equal(
      await fallback.page.locator("#ld-restore-banner").count(),
      1,
      "An unverified browser download must not dismiss recovery",
    );
  }
  assert.equal(await fallback.page.locator(".ld-download-link").count(), 3);
  assert(
    await fallback.page
      .locator(".ld-download-link")
      .first()
      .evaluate(async (link) => (await fetch(link.href)).ok),
    "Blob URL was revoked before the browser could finish using it",
  );
  await fallback.page.clock.fastForward(60001);
  assert.equal(
    await fallback.page.locator(".ld-download-link").count(),
    0,
    "Finished transfer anchors were not cleaned up",
  );
  assert.deepEqual(fallback.errors, []);
  await fallback.context.close();
  console.log(
    "PASS actual Chrome download files exist, have content and reopen: HTML, template and working Save; recovery retained",
  );

  // Contract test for the native picker: mocked dialog/handle, real filesystem
  // writes on close, with activation and independent export destinations.
  const picked = await open("picker");
  for (const action of actions) {
    await picked.page.evaluate((name) => {
      window.pickedName = name;
    }, `picked-${action.kind}.html`);
    if (action.kind === "working") await picked.page.click("#mode-toggle");
    await picked.page.click(action.selector);
    await picked.page.waitForFunction(
      (name) =>
        document
          .querySelector(".ld-save-banner")
          ?.textContent.startsWith(`Saved ${name}`),
      `picked-${action.kind}.html`,
    );
    const html = await verifyFile(
      picked.context,
      join(out, `picked-${action.kind}.html`),
      action.kind,
    );
    if (action.kind === "client") await verifyPreview(picked, html);
    else
      assert.equal(await picked.page.locator(".ld-export-preview").count(), 0);
  }
  const calls = await picked.page.evaluate(() => window.pickerCalls);
  assert.equal(calls.length, 3);
  assert.equal(calls[0].name, "source-copy.client.html");
  assert(calls.every((call) => call.id === "legaldesign-html"));
  assert.equal(calls[0].startIn, null);
  assert.equal(calls[1].startIn, "picked-client.html");
  assert(
    calls.every((call) => call.active),
    "Save picker was invoked without button activation",
  );
  const pure = await picked.page.evaluate(() => ({
    type: typeof window.LegalDesign.exportHTML(false),
    calls: window.pickerCalls.length,
  }));
  assert.deepEqual(pure, { type: "string", calls: 3 });
  await picked.page.click("#export-html");
  await picked.page.locator(".ld-export-preview").waitFor();
  assert.equal(
    await picked.page.evaluate(() => window.pickerCalls.at(-1).startIn),
    "picked-working.html",
  );
  await picked.page.evaluate(() => {
    window.pickerMode = "cancel";
  });
  await picked.page.click("#export-html");
  await picked.page.waitForFunction(() =>
    document
      .querySelector(".ld-save-banner")
      ?.textContent.includes("Save canceled"),
  );
  assert.equal(
    await picked.page.locator(".ld-export-preview").count(),
    0,
    "Canceled export offered a stale client snapshot",
  );
  assert.deepEqual(picked.errors, []);
  await picked.context.close();
  console.log(
    "PASS native-picker contract: activation, confirmed write/close, independent export locations and synchronous serializer",
  );

  const canceled = await open("cancel");
  let canceledDownloads = 0;
  canceled.page.on("download", () => canceledDownloads++);
  for (const action of actions) {
    if (action.kind === "working") await canceled.page.click("#mode-toggle");
    await canceled.page.click(action.selector);
    await canceled.page.waitForFunction(() =>
      document
        .querySelector(".ld-save-banner")
        ?.textContent.includes("Save canceled"),
    );
    assert.equal(await canceled.page.locator(".ld-export-preview").count(), 0);
  }
  assert.equal(
    await canceled.page.evaluate(() => window.pickerCalls.length),
    3,
  );
  assert.equal(canceledDownloads, 0);
  assert.equal(await canceled.page.locator(".ld-download-link").count(), 0);
  assert.deepEqual(canceled.errors, []);
  await canceled.context.close();
  console.log(
    "PASS picker cancellation does not trigger an unexpected download",
  );

  const failed = await open("write-error");
  const pending = failed.page.waitForEvent("download");
  await failed.page.click("#export-html");
  const download = await pending;
  assert.equal(await download.failure(), null);
  assert(await failed.page.evaluate(() => window.writeAborted));
  const path = join(out, "write-error-fallback.html");
  copyFileSync(await download.path(), path);
  const failedHTML = await verifyFile(failed.context, path, "client");
  await verifyPreview(failed, failedHTML);
  assert.match(
    await failed.page.locator(".ld-save-banner").textContent(),
    /Download requested/,
  );
  assert.deepEqual(failed.errors, []);
  await failed.context.close();
  assert.equal(
    readFileSync(fixture, "utf8"),
    fixtureSource,
    "Export changed the file that was open in the browser",
  );
  console.log(
    `PASS failed native write aborts safely and falls back to a real browser file. Evidence: ${out}`,
  );

  const composedPath = join(out, "approaches.html");
  const build = spawnSync(
    process.env.LEGALDESIGN_PYTHON || "python3",
    [
      "skills/core/legaldesign/scripts/scaffold.py",
      "compose",
      "--plan",
      "packages/legaldesign/fixtures/case-07-forward-design/plan.json",
      "--spec-output",
      join(out, "approaches.json"),
      "--output",
      composedPath,
      "--artifact-id",
      "export-preview-approaches",
    ],
    { cwd: repo, encoding: "utf8" },
  );
  assert.equal(build.status, 0, build.stdout + build.stderr);
  writeFileSync(
    composedPath,
    readFileSync(composedPath, "utf8").replace(
      /<!-- legaldesign:runtime -->[\s\S]*?<!-- \/legaldesign:runtime -->/,
      () => block,
    ),
  );
  const snapshots = await open("fallback", composedPath);
  let first;
  for (const approach of ["a", "b"]) {
    await snapshots.page
      .locator(`[data-select-approach="${approach}"]`)
      .click();
    const pending = snapshots.page.waitForEvent("download");
    await snapshots.page.click("#export-html");
    const transfer = await pending;
    assert.equal(await transfer.failure(), null);
    const html = readFileSync(await transfer.path(), "utf8");
    const opened = await verifyPreview(snapshots, html, {
      keepOpen: true,
      approach,
    });
    if (!first) first = opened;
    else {
      assert.notEqual(first.url, opened.url);
      assert.equal(
        await snapshots.page.evaluate(async (url) => {
          try {
            await fetch(url);
            return true;
          } catch {
            return false;
          }
        }, first.url),
        false,
        "Replacing the result should release the previous Blob URL",
      );
      assert.equal(
        await first.preview.locator('[data-approach="a"]').count(),
        1,
        "A later export changed the previously opened snapshot",
      );
      await opened.preview.close();
    }
  }
  await first.preview.close();
  const existingTransfers = await snapshots.page
    .locator(".ld-download-link")
    .count();
  let unexpectedDownloads = 0;
  snapshots.page.on("download", () => unexpectedDownloads++);
  await snapshots.page.evaluate(() => {
    const originalClick = HTMLAnchorElement.prototype.click;
    HTMLAnchorElement.prototype.click = function () {
      if (this.classList.contains("ld-download-link"))
        throw new DOMException("Transfer unavailable", "NotAllowedError");
      return originalClick.call(this);
    };
  });
  await snapshots.page.click("#export-html");
  await snapshots.page.waitForFunction(() =>
    document
      .querySelector(".ld-save-banner")
      ?.textContent.includes("could not be saved"),
  );
  assert.equal(
    await snapshots.page.locator(".ld-export-preview").count(),
    0,
    "Failed export offered a stale client snapshot",
  );
  assert.equal(unexpectedDownloads, 0);
  assert.equal(
    await snapshots.page.locator(".ld-download-link").count(),
    existingTransfers,
    "A failed transfer retained a new hidden anchor and Blob URL",
  );
  await snapshots.context.close();
  for (const mode of ["picker", "fallback"]) {
    for (const [width, height] of [
      [1440, 900],
      [390, 844],
    ]) {
      const sample = await open(mode, composedPath, { width, height });
      const name = `${mode}-${width}.html`;
      await sample.page.evaluate((name) => {
        window.pickedName = name;
      }, name);
      const pending =
        mode === "fallback" ? sample.page.waitForEvent("download") : null;
      await sample.page.click("#export-html");
      await sample.page.locator(".ld-export-preview").waitFor();
      const savedPath = pending
        ? await (await pending).path()
        : join(out, name);
      const opened = await verifyPreview(
        sample,
        readFileSync(savedPath, "utf8"),
        { keepOpen: true, approach: "a" },
      );
      await sample.page.screenshot({
        path: join(out, `result-${mode}-${width}.png`),
      });
      await opened.preview.screenshot({
        path: join(out, `opened-${mode}-${width}.png`),
      });
      await sample.context.close();
    }
  }
  const consecutive = await open("fallback", composedPath);
  await consecutive.page.evaluate(() => {
    document
      .querySelectorAll(".ld-fixed-page .ld-composed-grid")
      .forEach((grid) => {
        grid.style.minHeight = `${grid.closest(".ld-fixed-page").clientHeight - 56}px`;
      });
  });
  for (const selector of ["#export-html", "#export-template", "#export-html"]) {
    const transfer = consecutive.page.waitForEvent("download");
    await consecutive.page.click(selector);
    assert.equal(await (await transfer).failure(), null);
    await consecutive.page.locator(".ld-save-banner").waitFor();
    await consecutive.page.evaluate(
      () =>
        new Promise((resolve) =>
          requestAnimationFrame(() => requestAnimationFrame(resolve)),
        ),
    );
  }
  assert.deepEqual(
    consecutive.errors,
    [],
    "A prior save notice blocked the next export",
  );
  assert.equal(
    await consecutive.page.evaluate(() => {
      document.querySelector(
        ".ld-fixed-page .ld-composed-grid",
      ).style.minHeight = "3000px";
      try {
        LegalDesign.exportTemplate(false);
        return false;
      } catch {
        return true;
      }
    }),
    true,
    "Real overflow must still block export",
  );
  await consecutive.context.close();
  console.log(
    "PASS explicit client preview opens exact exported bytes, isolates its opener, retains selected approach, and keeps successive snapshots independent; notices do not block subsequent exports",
  );
} finally {
  await browser.close();
}
