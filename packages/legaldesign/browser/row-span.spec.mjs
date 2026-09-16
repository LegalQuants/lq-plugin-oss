import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";
import Ajv2020 from "ajv/dist/2020.js";

const repo = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const schema = JSON.parse(
  readFileSync(
    resolve(repo, "skills/core/legaldesign/schemas/build-spec.schema.json"),
    "utf8",
  ),
);
const layoutSchema =
  schema.properties.composition.properties.sections.items.properties.layout;
const validate = new Ajv2020({ strict: false }).compile(layoutSchema);
const layout = {
  columns: 12,
  placements: [
    { unitId: "title", row: 1, column: 1, span: 12 },
    { unitId: "finding", row: 2, column: 1, span: 6 },
    { unitId: "consequence", row: 3, column: 1, span: 6 },
    { unitId: "recommendation", row: 4, column: 1, span: 6 },
    { unitId: "timeline", row: 2, column: 7, span: 6, rowSpan: 3 },
  ],
};
assert(validate(layout), JSON.stringify(validate.errors));
for (const rowSpan of [0, -1, 13, 1.5, true, "3", null]) {
  const invalid = structuredClone(layout);
  invalid.placements.at(-1).rowSpan = rowSpan;
  assert(
    !validate(invalid),
    `schema rejects invalid rowSpan ${JSON.stringify(rowSpan)}`,
  );
}

const python = resolve(repo, ".venv/bin/python");
const rendered = spawnSync(
  existsSync(python) ? python : "python3",
  [
    "-c",
    `
import importlib.util, json, sys
from pathlib import Path
path=Path("skills/core/legaldesign/scripts/scaffold.py")
loader=importlib.util.spec_from_file_location("row_span_scaffold", path)
module=importlib.util.module_from_spec(loader)
sys.modules[loader.name]=module
loader.loader.exec_module(module)
layout=json.loads(sys.stdin.read())
units=[]
for placement in layout["placements"]:
    name=placement["unitId"]
    content=("<h1>Review overview and timeline</h1>" if name=="title" else
             "<h2>"+name.title()+"</h2><p>The reader can compare this point with the events alongside it. The explanation belongs to this narrative card.</p>")
    units.append({"id":name,"kind":"figure" if name=="timeline" else "text", "claim":name.title(),
                  "variants":{"a":{"component":"timeline"} if name=="timeline" else {"html":content}}})
section={"id":"review","purpose":"Review overview","unitIds":[u["id"] for u in units],"layout":layout}
print(module._render_composition({"brief":{"form":"one-page"},"units":units}, {"sections":[section]}, "a"))
`,
  ],
  { cwd: repo, input: JSON.stringify(layout), encoding: "utf8" },
);
assert.equal(rendered.status, 0, rendered.stderr);
const tokens = readFileSync(
  resolve(repo, "packages/legaldesign/runtime/tokens.css"),
  "utf8",
);
const components = readFileSync(
  resolve(repo, "packages/legaldesign/runtime/components.js"),
  "utf8",
);
const browser = await chromium.launch({
  headless: true,
  executablePath: [
    chromium.executablePath(),
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  ].find(existsSync),
});
try {
  const page = await browser.newPage({
    viewport: { width: 1400, height: 1200 },
  });
  await page.setContent(
    `<html data-fixed-pages="4:3"><head><style>${tokens}</style></head><body>${rendered.stdout}<script>${components}</script></body></html>`,
  );
  await page.evaluate(() => {
    document.querySelector('[data-unit="timeline"] .ld-diagram').innerHTML =
      LegalDesign.render("timeline", {
        orientation: "vertical",
        marks: [
          {
            when: "Stage 1",
            title: "Source delivered",
            sub: "A source is available for review.",
          },
          {
            when: "Stage 2",
            title: "Questions recorded",
            sub: "The reader identifies the unresolved points.",
          },
          {
            when: "Stage 3",
            title: "Decision made",
            sub: "The response and its support are retained.",
          },
        ],
      });
  });
  const geometry = await page.evaluate(() =>
    Object.fromEntries(
      [...document.querySelectorAll("[data-unit]")].map((node) => [
        node.dataset.unit,
        {
          ...node.getBoundingClientRect().toJSON(),
          start: getComputedStyle(node).gridRowStart,
          end: getComputedStyle(node).gridRowEnd,
        },
      ]),
    ),
  );
  assert.equal(geometry.timeline.start, "2");
  assert.equal(geometry.timeline.end, "span 3");
  assert.equal(geometry.title.end, "span 1");
  assert(Math.abs(geometry.timeline.top - geometry.finding.top) < 1);
  assert(
    geometry.timeline.bottom > geometry.recommendation.top,
    "timeline occupies the height beside all three narrative rows",
  );
  for (const card of ["finding", "consequence", "recommendation"]) {
    assert(
      geometry[card].right < geometry.timeline.left,
      `${card} stays left of the timeline`,
    );
  }
  assert(geometry.finding.bottom < geometry.consequence.top);
  assert(geometry.consequence.bottom < geometry.recommendation.top);
  console.log(
    "PASS rowSpan schema capacities and generated three-card/tall-timeline grid geometry",
  );
} finally {
  await browser.close();
}
