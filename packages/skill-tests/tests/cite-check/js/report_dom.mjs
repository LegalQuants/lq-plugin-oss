#!/usr/bin/env node
/** Run the cite-check report script against a tiny DOM of known ids. */

import fs from "node:fs";

class Node {
  constructor(tag = "", text = "") {
    this.tagName = String(tag).toUpperCase();
    this.children = [];
    this.attrs = {};
    this.className = "";
    this._id = "";
    this._text = text;
    this.style = {};
    this.dataset = {};
    this.value = "";
    this.listeners = {};
    this.type = "";
  }

  get textContent() {
    if (!this.children.length) return this._text;
    return this.children.map((child) => child.textContent).join("");
  }

  set textContent(value) {
    this._text = value == null ? "" : String(value);
    this.children = [];
  }

  get id() {
    return this._id;
  }

  set id(value) {
    this._id = String(value || "");
    if (this._id && document?._byId) {
      document._byId.set(this._id, this);
    }
  }

  appendChild(child) {
    this.children.push(child);
    if (child.id) document._byId.set(child.id, child);
    return child;
  }

  replaceChildren() {
    this.children = [];
  }

  setAttribute(name, value) {
    this.attrs[name] = String(value);
    if (name === "id") {
      this.id = String(value);
      document._byId.set(this.id, this);
    }
    if (name === "style") {
      String(value)
        .split(";")
        .forEach((part) => {
          const [key, val] = part.split(":");
          if (key && val) this.style[key.trim()] = val.trim();
        });
    }
  }

  addEventListener(type, fn) {
    if (!this.listeners[type]) this.listeners[type] = [];
    this.listeners[type].push(fn);
  }

  dispatchEvent(type) {
    for (const fn of this.listeners[type] || []) fn();
  }

  querySelector(selector) {
    return this.querySelectorAll(selector)[0] || null;
  }

  querySelectorAll(selector) {
    const out = [];
    const walk = (node) => {
      if (matches(node, selector)) out.push(node);
      for (const child of node.children) walk(child);
    };
    for (const child of this.children) walk(child);
    return out;
  }
}

function matches(node, selector) {
  if (selector.startsWith(".")) {
    return node.className.split(/\s+/).includes(selector.slice(1));
  }
  if (selector.includes(".")) {
    const [tag, cls] = selector.split(".");
    return (
      node.tagName === tag.toUpperCase() &&
      node.className.split(/\s+/).includes(cls)
    );
  }
  return node.tagName === selector.toUpperCase();
}

function el(tag, id) {
  const node = new Node(tag);
  if (id) {
    node.id = id;
    node.setAttribute("id", id);
  }
  if (tag === "select") {
    const all = new Node("option");
    all.value = "all";
    all.textContent = "All";
    node.appendChild(all);
    node.value = "all";
  }
  if (tag === "table") {
    const tbody = new Node("tbody");
    node.appendChild(tbody);
  }
  return node;
}

const html = fs.readFileSync(process.argv[2], "utf8");
const payloadMatch = html.match(
  /<script type="application\/json" id="cc-report">([\s\S]*?)<\/script>/,
);
const scriptMatch = html.match(
  /<script>\s*\(\(\) => \{([\s\S]*?)\}\)\(\);\s*<\/script>/,
);
if (!payloadMatch || !scriptMatch) {
  process.stderr.write("could not extract report script\n");
  process.exit(2);
}

const document = { _byId: new Map() };
document.getElementById = (id) => document._byId.get(id) || null;
document.createElement = (tag) => new Node(tag);
document.createTextNode = (text) => new Node("#text", text);
globalThis.document = document;

for (const [tag, id] of [
  ["div", "cc-runstrip"],
  ["p", "cc-standfirst"],
  ["section", "cc-gate"],
  ["div", "cc-scoreboard"],
  ["p", "cc-reference-strip"],
  ["div", "cc-findings"],
  ["table", "cc-rollup"],
  ["select", "cc-tier"],
  ["select", "cc-kind"],
  ["input", "cc-search"],
  ["output", "cc-count"],
  ["div", "cc-ledger"],
  ["div", "cc-lineage"],
  ["table", "cc-authorities"],
  ["table", "cc-limitations"],
  ["ul", "cc-appendix"],
  ["ul", "cc-notes"],
  ["p", "cc-prov-1"],
]) {
  document._byId.set(id, el(tag, id));
}
const reportNode = new Node("script");
reportNode.id = "cc-report";
reportNode.textContent = payloadMatch[1];
document._byId.set("cc-report", reportNode);

const runner = new Function("document", `(() => {${scriptMatch[1]}})();`);
runner(document);

const ENUM_LEAK = /\b[a-z]+(?:_[a-z]+){2,}\b/;
const collect = (node, out = []) => {
  if (node.tagName === "SCRIPT" || node.id === "cc-report") return out;
  if (node.tagName === "#TEXT" || !node.children.length) {
    const text = node.textContent;
    if (text?.trim()) out.push(text);
  }
  for (const child of node.children) collect(child, out);
  return out;
};

const texts = [];
for (const node of document._byId.values()) {
  if (node.id === "cc-report") continue;
  collect(node, texts);
}
const leaks = [...new Set(texts.filter((text) => ENUM_LEAK.test(text)))];

const apply = (tier, kind, query) => {
  const tierSelect = document.getElementById("cc-tier");
  const kindSelect = document.getElementById("cc-kind");
  const search = document.getElementById("cc-search");
  tierSelect.value = tier;
  kindSelect.value = kind;
  search.value = query;
  tierSelect.dispatchEvent("change");
  kindSelect.dispatchEvent("change");
  search.dispatchEvent("input");
  return {
    count: document.getElementById("cc-count").textContent,
    empty: document.getElementById("cc-ledger").textContent,
  };
};

process.stdout.write(
  `${JSON.stringify(
    {
      leaks,
      gate: document.getElementById("cc-gate-verdict")?.textContent || "",
      runstrip: document.getElementById("cc-runstrip").textContent,
      reportRecord: document.getElementById("cc-prov-1").textContent,
      all: apply("all", "all", ""),
      red: apply("red", "all", ""),
      caseKind: apply("all", "case", ""),
      milam: apply("red", "case", "Milam"),
      none: apply("red", "case", "zzzz-no-such-citation"),
      lineageStages: [...document.getElementById("cc-lineage").children].map(
        (stage) => [...stage.children].map((child) => child.textContent),
      ),
    },
    null,
    2,
  )}\n`,
);
