"""The single embedded stylesheet for the Definition Check dashboard."""

from __future__ import annotations

DASHBOARD_STYLE = (
    r"""
/* Base dashboard layout and interaction rules. */
:root { color-scheme: light; --ink:#172033; --muted:#667085; --line:#d8dee8; --paper:#fff; --canvas:#f4f6f8; --navy:#19345f; --focus:#1769aa; --blue:#e8f1ff; --green:#e5f4ea; --red:#fde8e7; --amber:#fff0cf; --violet:#f0e9ff; font: 15px/1.5 Arial, Helvetica, sans-serif; }
* { box-sizing:border-box; }
body { margin:0; color:var(--ink); background:var(--canvas); }
button,input { font:inherit; }
button { color:inherit; }
.skip-link { position:fixed; left:.75rem; top:-4rem; z-index:20; background:#fff; padding:.65rem 1rem; border:2px solid var(--navy); }
.skip-link:focus { top:.75rem; }
.app-header { background:var(--paper); border-bottom:1px solid var(--line); padding:1rem clamp(1rem,3vw,2rem) 0; }
.identity { display:flex; align-items:flex-start; justify-content:space-between; gap:1rem; max-width:1600px; margin:auto; }
.eyebrow { margin:0 0 .15rem; color:var(--navy); font-size:.74rem; font-weight:700; letter-spacing:.08em; text-transform:uppercase; }
h1 { margin:0; font:600 clamp(1.25rem,2vw,1.65rem)/1.25 Georgia, serif; }
.run-summary { text-align:right; }
.run-summary strong { display:block; font-size:1.25rem; color:var(--navy); }
.run-summary span { color:var(--muted); font-size:.82rem; }
.tabs { display:flex; gap:1.4rem; max-width:1600px; margin:1rem auto 0; }
.tab { border:0; border-bottom:3px solid transparent; background:none; padding:.55rem .1rem .7rem; font-weight:700; cursor:pointer; }
.tab[aria-selected="true"] { color:var(--navy); border-color:var(--navy); }
.view { max-width:1600px; margin:auto; padding:1rem clamp(1rem,3vw,2rem) 2rem; }
.document-layout { display:grid; grid-template-columns:minmax(0,1fr) minmax(19rem,25rem); gap:1rem; align-items:start; }
.document-shell,.results-panel,.history-card { background:var(--paper); border:1px solid var(--line); border-radius:8px; }
.document-toolbar { display:flex; flex-wrap:wrap; align-items:center; justify-content:space-between; gap:.7rem; padding:.8rem 1.2rem; border-bottom:1px solid var(--line); }
.document-toolbar h2 { margin:0; font-size:1rem; }
.legend { display:flex; flex-wrap:wrap; gap:.75rem; color:var(--muted); font-size:.78rem; }
.legend span::before { content:""; display:inline-block; width:.65rem; height:.65rem; margin-right:.3rem; border-radius:2px; background:var(--legend); }
.document { padding:1.5rem clamp(1rem,3vw,2.4rem); max-height:calc(100vh - 12rem); overflow:auto; scroll-behavior:smooth; }
.document-block { scroll-margin-top:1rem; }
.document-block p { margin:0 0 .9rem; white-space:pre-wrap; overflow-wrap:anywhere; font:1rem/1.65 Georgia, serif; }
.annotation { --annotation-rest:transparent; --annotation-hover:transparent; --annotation-selected:transparent; --annotation-accent:var(--navy); color:inherit; background:var(--annotation-rest); border-radius:2px; border-bottom:2px solid var(--annotation-accent); padding:0 .03em; cursor:pointer; transition:background-color 120ms ease,box-shadow 120ms ease; }
.annotation.definition { --annotation-rest:var(--green); --annotation-hover:#ccebd6; --annotation-selected:#b8e2c5; --annotation-accent:#3f7f53; }
.annotation.use { --annotation-rest:var(--blue); --annotation-hover:#d3e5fb; --annotation-selected:#bad8f7; --annotation-accent:#4776ad; border-bottom-style:dotted; }
.annotation.issue { --annotation-rest:var(--red); --annotation-hover:#f9d2cf; --annotation-selected:#f3bdb9; --annotation-accent:#a33b36; }
.annotation.low-confidence { --annotation-rest:var(--violet); --annotation-hover:#dfd1f5; --annotation-selected:#cfbced; --annotation-accent:#684495; border-bottom-style:dashed; }
.annotation:hover { background:var(--annotation-hover); box-shadow:0 0 0 1px var(--annotation-accent); }
.annotation:active { background:var(--annotation-selected); }
.annotation:focus-visible { background:var(--annotation-hover); outline:3px solid var(--focus); outline-offset:2px; box-shadow:0 0 0 1px var(--paper); }
.annotation.selected { background:var(--annotation-selected); outline:2px solid var(--navy); outline-offset:2px; box-shadow:inset 0 -2px var(--annotation-accent); }
.annotation.selected:hover { background:var(--annotation-hover); outline-width:3px; box-shadow:inset 0 -2px var(--annotation-accent),0 0 0 1px var(--annotation-accent); }
.annotation.selected:focus-visible { background:var(--annotation-selected); outline:3px solid var(--focus); outline-offset:3px; box-shadow:inset 0 -2px var(--annotation-accent),0 0 0 1px var(--paper); }
.annotation-card { position:fixed; z-index:30; width:max-content; max-width:calc(100vw - 1rem); padding:.32rem .48rem; border:1px solid var(--line); border-radius:6px; background:var(--paper); box-shadow:0 6px 18px rgba(23,32,51,.16); pointer-events:none; }
.annotation-card.has-rationale { width:min(18rem,calc(100vw - 1rem)); padding:.5rem .6rem; }
.annotation-card-label { margin:0; color:var(--muted); font-size:.7rem; font-weight:700; line-height:1.2; letter-spacing:.04em; text-transform:uppercase; }
.annotation-card-rationale { display:-webkit-box; margin:.28rem 0 0; overflow:hidden; color:var(--ink); font-size:.78rem; line-height:1.35; overflow-wrap:anywhere; -webkit-box-orient:vertical; -webkit-line-clamp:2; }
.results-panel { position:sticky; top:1rem; max-height:calc(100vh - 2rem); overflow:auto; }
.panel-tabs { position:sticky; top:0; z-index:5; display:grid; grid-template-columns:1fr 1fr; background:#fff; border-bottom:1px solid var(--line); }
.panel-tab { border:0; border-bottom:3px solid transparent; background:#fff; padding:.85rem 1rem .7rem; font-weight:700; cursor:pointer; }
.panel-tab[aria-selected="true"] { color:var(--navy); border-bottom-color:var(--navy); }
.panel-tab span { color:var(--muted); font-weight:400; }
.panel-meta { display:flex; align-items:center; justify-content:space-between; gap:.75rem; min-height:3.5rem; padding:.65rem 1rem; border-bottom:1px solid var(--line); }
.panel-meta p { margin:0; color:var(--muted); font-size:.82rem; }
.filter-menu { position:relative; flex:0 0 auto; }
.filter-menu summary { display:flex; flex-direction:column; min-width:9.5rem; border:1px solid #9ba7b8; border-radius:5px; background:#fff; padding:.35rem .65rem; cursor:pointer; list-style:none; font-size:.78rem; }
.filter-menu summary::-webkit-details-marker { display:none; }
.filter-menu summary::after { content:"▾"; position:absolute; right:.65rem; top:.72rem; }
.filter-menu summary span { font-weight:700; }
.filter-menu summary small { max-width:8rem; padding-right:1rem; color:var(--muted); overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.filter-options { position:absolute; right:0; top:calc(100% + .35rem); z-index:8; width:min(20rem,80vw); padding:.35rem; background:#fff; border:1px solid #9ba7b8; border-radius:6px; box-shadow:0 10px 24px rgba(23,32,51,.16); }
.filter-option { display:flex; align-items:center; justify-content:space-between; gap:1rem; width:100%; border:0; border-radius:4px; background:#fff; padding:.55rem .65rem; text-align:left; cursor:pointer; }
.filter-option:hover,.filter-option.active { background:#edf3fb; color:var(--navy); }
.filter-option strong { min-width:1.5rem; color:var(--muted); text-align:right; }
.result-list { padding:.6rem; }
.result-group { border:1px solid var(--line); border-radius:6px; overflow:hidden; }
.result-group + .result-group { margin-top:.75rem; }
.result-group-heading { display:grid; grid-template-columns:auto 1fr auto; align-items:center; gap:.55rem; padding:.65rem .8rem; background:#f8fafc; cursor:pointer; list-style:none; }
.result-group-heading::-webkit-details-marker { display:none; }
.result-group-heading::before { content:"\203A"; color:var(--muted); font-size:1.1rem; line-height:1; transform-origin:center; transition:transform 120ms ease; }
.result-group-heading:hover { background:#edf3fb; }
.result-group[open] > .result-group-heading { border-bottom:1px solid var(--line); }
.result-group[open] > .result-group-heading::before { transform:rotate(90deg); }
.result-group-title { font-size:.82rem; font-weight:700; }
.result-group-count { color:var(--muted); font-size:.75rem; white-space:nowrap; }
.result-card { border:1px solid transparent; border-bottom-color:var(--line); padding:.85rem; cursor:pointer; scroll-margin-top:3.25rem; }
.result-card:last-child { border-bottom-color:transparent; }
.result-card:hover,.result-card.selected { background:#f8fafc; border-color:#aab7ca; border-radius:6px; }
.result-card h4 { margin:.2rem 0; font:600 1rem/1.3 Georgia,serif; }
.result-card p { margin:.3rem 0; }
.evidence { margin-top:.65rem; }
.evidence span { color:var(--muted); font-size:.72rem; font-weight:700; text-transform:uppercase; }
blockquote { margin:.2rem 0; padding:.55rem .75rem; border-left:3px solid #aab7ca; background:#f8fafc; white-space:pre-wrap; overflow-wrap:anywhere; }
.empty-state { padding:2rem 1rem; text-align:center; }
.empty-state h3 { margin:0; font:600 1.1rem Georgia,serif; }
.empty-state p { color:var(--muted); }
.terms-toolbar { display:flex; flex-wrap:wrap; gap:.55rem; padding:.8rem .8rem .45rem; }
.terms-toolbar label { width:100%; font-weight:700; }
.terms-toolbar input { flex:1 1 12rem; min-width:0; padding:.5rem .65rem; border:1px solid #9ba7b8; border-radius:5px; }
.segmented { display:flex; border:1px solid #9ba7b8; border-radius:5px; overflow:hidden; }
.segmented button { border:0; background:#fff; padding:.45rem .55rem; cursor:pointer; font-size:.78rem; }
.segmented button.active { color:#fff; background:var(--navy); }
.agent-note { margin:0; padding:.25rem .8rem .75rem; color:var(--muted); font-size:.78rem; border-bottom:1px solid var(--line); }
.term-list { overflow:auto; }
.term-row { display:flex; justify-content:space-between; gap:.7rem; width:100%; border:0; border-bottom:1px solid var(--line); background:#fff; padding:.7rem .9rem; text-align:left; cursor:pointer; }
.term-row small { color:var(--muted); }
.term-row.selected { color:var(--navy); background:#edf3fb; box-shadow:inset 3px 0 var(--navy); }
.term-detail-panel { padding:0; }
.term-detail { padding:1rem; }
.term-detail h2 { margin:.15rem 0 .8rem; font:600 1.35rem Georgia,serif; }
.back-to-terms { border:0; background:none; color:#174f91; margin:0 0 .9rem; padding:0; text-decoration:underline; cursor:pointer; }
.text-link { border:0; background:none; color:#174f91; padding:.2rem 0; text-decoration:underline; cursor:pointer; }
.usage-map { margin-top:1.25rem; }
.usage-map-heading { display:flex; align-items:baseline; gap:1rem; }
.usage-map-heading h3 { margin:0; font-size:1rem; }
.usage-map > p { margin:.25rem 0 .65rem; color:var(--muted); font-size:.78rem; }
.usage-grid { display:grid; grid-template-rows:repeat(7,.75rem); grid-auto-flow:column; grid-auto-columns:.75rem; width:max-content; max-width:100%; gap:3px; overflow-x:auto; padding:.15rem; }
.usage-cell { width:.75rem; height:.75rem; min-width:.75rem; min-height:.75rem; border:1px solid rgba(27,31,36,.06); border-radius:2px; background:#ebedf0; }
button.usage-cell { padding:0; cursor:pointer; }
.usage-cell.level-0 { background:#ebedf0; }
.usage-cell.level-1 { background:#c6dbef; }
.usage-cell.level-2 { background:#6baed6; }
.usage-cell.level-3 { background:#3182bd; }
.usage-cell.level-4 { background:#08519c; }
button.usage-cell:hover { outline:2px solid var(--navy); outline-offset:1px; }
.usage-legend { display:flex; align-items:center; justify-content:flex-end; gap:4px; margin-top:.6rem; color:var(--muted); font-size:.72rem; }
.usage-legend .usage-cell { flex:0 0 .75rem; }
.history-card { padding:1.2rem; max-width:52rem; }
.history-row { display:flex; justify-content:space-between; gap:1rem; padding:1rem 0; border-top:1px solid var(--line); }
.status { color:#28613a; font-weight:700; }
.muted { color:var(--muted); }
[hidden] { display:none !important; }
button:focus-visible,input:focus-visible,summary:focus-visible,[tabindex]:focus-visible { outline:3px solid var(--focus); outline-offset:2px; }
@media (max-width:900px) { .document-layout { grid-template-columns:1fr; } .document { max-height:none; } .results-panel { position:static; max-height:none; } .term-list { max-height:22rem; } }
@media (max-width:560px) { .identity { display:block; } .run-summary { margin-top:.65rem; text-align:left; } .tabs { gap:1rem; overflow:auto; } .document-toolbar { align-items:flex-start; } .legend { width:100%; } .view { padding-inline:.6rem; } }
@media (prefers-reduced-motion:reduce) { *,*::before,*::after { scroll-behavior:auto !important; transition:none !important; } }
@media print { .annotation-card { display:none !important; } }
@media (forced-colors:active) { .annotation { forced-color-adjust:auto; background:Canvas; color:CanvasText; border-bottom-color:LinkText; } .annotation:hover,.annotation:focus-visible { background:Highlight; color:HighlightText; } .annotation.selected { outline-color:Highlight; border-bottom-style:double; } }
""".strip()
    + "\n\n"
    + r"""
/* Codex light theme tokens and overrides. */
:root {
  color-scheme: light;
  --ink: #202020;
  --muted: #737373;
  --line: #e5e5e5;
  --line-strong: #d6d6d6;
  --paper: #ffffff;
  --canvas: #f7f7f7;
  --surface-subtle: #f3f3f3;
  --surface-hover: #ededed;
  --surface-selected: #e7e7e7;
  --badge-background: #f1f1f1;
  --badge-foreground: #5f5f5f;
  --navy: #202020;
  --focus: #4c8bf5;
  --blue: #e8f1ff;
  --green: #e5f4ea;
  --red: #fde8e7;
  --amber: #fff0cf;
  --violet: #f0e9ff;
  --font-ui: "Segoe UI Variable Text", "Segoe UI", Arial, sans-serif;
  --font-document: Georgia, "Times New Roman", serif;
  --radius-control: 7px;
  --shadow-popover: 0 8px 28px rgba(0, 0, 0, 0.12);
}

body {
  background: var(--canvas);
  color: var(--ink);
  font-size: 14px;
}

body,
button,
input {
  font-family: var(--font-ui);
}

h1,
.result-card h3,
.term-detail h2,
.history-card h2,
.empty-state h3 {
  font-family: var(--font-ui);
}

.app-header {
  position: sticky;
  top: 0;
  z-index: 12;
  padding: 0.72rem 1rem;
  background: rgba(255, 255, 255, 0.96);
  border-bottom-color: var(--line);
  box-shadow: none;
}

.identity,
.tabs,
.view {
  max-width: none;
}

.identity {
  align-items: center;
}

.eyebrow,
.result-label,
.evidence span {
  display: inline-flex;
  align-items: center;
  width: fit-content;
  min-height: 1.25rem;
  padding: 0.1rem 0.38rem;
  border: 1px solid var(--line);
  border-radius: 5px;
  color: var(--badge-foreground);
  background: var(--badge-background);
  font-size: 0.68rem;
  font-weight: 500;
  line-height: 1.2;
  letter-spacing: 0;
  text-transform: none;
}

.eyebrow {
  margin-bottom: 0.16rem;
}

h1 {
  font-size: 1rem;
  font-weight: 600;
  letter-spacing: -0.012em;
}

.tabs {
  gap: 0.2rem;
  margin-top: 0.6rem;
}

.tab {
  border: 0;
  border-radius: var(--radius-control);
  padding: 0.42rem 0.72rem;
  color: var(--muted);
  background: transparent;
  font-size: 0.82rem;
  font-weight: 500;
  transition: background-color 100ms ease, color 100ms ease;
}

.tab:hover {
  background: var(--surface-subtle);
}

.tab[aria-selected="true"] {
  color: var(--ink);
  border-color: transparent;
  background: var(--surface-selected);
  box-shadow: none;
}

.view {
  padding: 0;
}

.document-layout {
  grid-template-columns: minmax(0, 1fr) minmax(19rem, 25rem);
  gap: 0;
}

.document-shell,
.results-panel,
.history-card {
  border: 0;
  border-radius: 0;
  box-shadow: none;
}

.document-shell {
  min-width: 0;
  border-right: 1px solid var(--line);
}

.document-toolbar {
  min-height: 3.15rem;
  justify-content: flex-start;
  padding: 0.6rem 1rem;
  background: var(--paper);
  border-bottom-color: var(--line);
}

.legend {
  gap: 0.7rem;
  font-size: 0.71rem;
}

.legend span {
  display: inline-flex;
  align-items: center;
}

.legend span::before {
  width: 0.55rem;
  height: 0.55rem;
  border-radius: 2px;
}

.document {
  padding: 1.25rem clamp(1rem, 3vw, 2.4rem);
  background: var(--paper);
}

.document-block p {
  font-family: var(--font-document);
  font-size: 1rem;
  line-height: 1.68;
}

.results-panel {
  top: 0;
  max-height: calc(100vh - 5.65rem);
  background: var(--paper);
}

.panel-tabs {
  background: rgba(255, 255, 255, 0.97);
  border-bottom-color: var(--line);
}

.panel-tab {
  min-height: 3.15rem;
  padding: 0.7rem 1rem 0.58rem;
  border-bottom-width: 2px;
  background: transparent;
  color: var(--muted);
  font-size: 0.82rem;
  font-weight: 500;
  transition: background-color 100ms ease, color 100ms ease, border-color 100ms ease;
}

.panel-tab:hover {
  background: var(--surface-subtle);
}

.panel-tab[aria-selected="true"] {
  color: var(--ink);
  background: transparent;
  border-bottom-color: var(--ink);
}

.panel-meta {
  min-height: 3.5rem;
  align-items: center;
  gap: 0.6rem;
  padding: 0.55rem 0.8rem;
}

.panel-heading h2 {
  margin: 0;
  font-size: 0.86rem;
  font-weight: 600;
}

.panel-heading p {
  margin: 0.08rem 0 0;
  font-size: 0.72rem;
}

.filter-menu summary,
.document-search input,
.search-navigation button,
.terms-toolbar input,
.segmented {
  border-color: var(--line-strong);
  border-radius: var(--radius-control);
  background: var(--paper);
  box-shadow: none;
}

.filter-menu summary {
  min-width: 8.8rem;
  padding: 0.32rem 0.55rem;
}

.filter-options {
  border-color: var(--line-strong);
  border-radius: 9px;
  box-shadow: var(--shadow-popover);
}

.filter-option {
  border-radius: 5px;
  font-size: 0.78rem;
}

.filter-option:hover,
.filter-option.active {
  color: var(--ink);
  background: var(--surface-hover);
}

.result-list {
  padding: 0;
}

.result-card {
  position: relative;
  border: 0;
  border-bottom: 1px solid var(--line);
  border-radius: 0;
  padding: 0.82rem 0.9rem;
  transition: background-color 100ms ease;
}

.result-card:hover {
  border-color: var(--line);
  border-radius: 0;
  background: var(--surface-subtle);
}

.result-card.selected {
  border-color: var(--line);
  border-radius: 0;
  background: var(--surface-selected);
  box-shadow: inset 2px 0 var(--ink);
}

.result-card h3 {
  margin: 0.18rem 0;
  font-size: 0.9rem;
  font-weight: 600;
}

.result-card p {
  font-size: 0.82rem;
  line-height: 1.45;
}

.result-card-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.45rem;
  min-width: 0;
}

.occurrence-navigator {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex: 0 0 auto;
  gap: 0.35rem;
  margin: 0;
  padding: 0.12rem 0.2rem 0.12rem 0.4rem;
  border: 1px solid var(--line-strong);
  border-radius: var(--radius-control);
  background: var(--paper);
}

.occurrence-status {
  color: var(--muted);
  font-size: 0.7rem;
  font-variant-numeric: tabular-nums;
}

.occurrence-controls {
  display: inline-flex;
  overflow: hidden;
  border: 1px solid var(--line-strong);
  border-radius: 6px;
  background: var(--paper);
}

.occurrence-controls button {
  width: 1.75rem;
  min-width: 1.75rem;
  min-height: 1.7rem;
  border: 0;
  border-radius: 0;
  padding: 0.05rem;
  color: var(--ink);
  background: transparent;
  cursor: pointer;
  font-size: 1rem;
  line-height: 1;
}

.occurrence-controls button + button {
  border-left: 1px solid var(--line-strong);
}

.occurrence-controls button:hover:not(:disabled) {
  background: var(--surface-hover);
}

.occurrence-controls button:disabled {
  color: var(--muted);
  cursor: default;
  opacity: 0.45;
}

.result-label {
  margin-bottom: 0.08rem;
}

.result-label.low-confidence {
  color: var(--badge-foreground);
}

.evidence span {
  margin-bottom: 0.14rem;
}

blockquote {
  border-left-width: 2px;
  background: var(--surface-subtle);
  font-size: 0.8rem;
}

.document-search {
  display: flex;
  flex: 0 1 19rem;
  align-items: center;
  gap: 0.35rem;
  min-width: 14rem;
}

.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}

.document-search input {
  min-width: 7rem;
  flex: 1 1 auto;
  border: 1px solid var(--line-strong);
  padding: 0.4rem 0.62rem;
  font-size: 0.8rem;
}

.document-search input::placeholder {
  color: #8a8a8a;
}

.search-navigation {
  display: inline-flex;
  align-items: center;
  flex: 0 0 auto;
  gap: 0;
  overflow: hidden;
  border: 1px solid var(--line-strong);
  border-radius: var(--radius-control);
  background: var(--paper);
}

.search-navigation button {
  width: 1.5rem;
  min-width: 1.5rem;
  min-height: 1.75rem;
  border: 0;
  border-radius: 0;
  padding: 0.1rem;
  color: var(--ink);
  background: transparent;
  font-size: 1rem;
  line-height: 1;
}

.search-navigation button:hover:not(:disabled) {
  background: var(--surface-hover);
}

.search-navigation button:disabled {
  color: var(--muted);
  cursor: default;
  opacity: 0.45;
}

.search-status {
  min-width: 2.2rem;
  padding: 0 0.1rem;
  color: var(--muted);
  font-size: 0.72rem;
  text-align: center;
}

.search-hit {
  background: rgba(255, 224, 102, 0.48);
}

.search-current {
  outline: 2px solid var(--ink);
  outline-offset: 1px;
}

::highlight(definition-check-search) {
  background: rgba(255, 224, 102, 0.56);
  color: inherit;
}

::highlight(definition-check-search-current) {
  background: rgba(255, 186, 56, 0.78);
  color: inherit;
}

.terms-toolbar {
  padding: 0.7rem 0.8rem 0.45rem;
}

.terms-toolbar label {
  font-size: 0.78rem;
  font-weight: 600;
}

.terms-toolbar input {
  padding: 0.42rem 0.58rem;
  font-size: 0.8rem;
}

.segmented button {
  font-size: 0.74rem;
}

.segmented button.active {
  color: var(--ink);
  background: var(--surface-selected);
}

.agent-note {
  font-size: 0.72rem;
}

.term-row {
  border-bottom-color: var(--line);
  background: var(--paper);
  padding: 0.64rem 0.82rem;
  font-size: 0.8rem;
  transition: background-color 100ms ease;
}

.term-row:hover {
  background: var(--surface-subtle);
}

.term-row.selected {
  color: var(--ink);
  background: var(--surface-selected);
  box-shadow: inset 2px 0 var(--ink);
}

.term-detail {
  padding: 0.9rem;
}

.term-detail h2 {
  font-size: 1.05rem;
  font-weight: 600;
}

.back-to-terms,
.text-link {
  color: #3567a8;
}

.usage-cell {
  border-radius: 2px;
}

.history-card {
  margin: 1rem;
  max-width: 52rem;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--paper);
}

button:focus-visible,
input:focus-visible,
[tabindex]:focus-visible {
  outline-width: 2px;
  outline-color: var(--focus);
}

@media (max-width: 900px) {
  .document-shell {
    border-right: 0;
    border-bottom: 1px solid var(--line);
  }

  .document-search {
    flex-basis: 100%;
    min-width: 0;
  }

  .results-panel {
    max-height: none;
  }
}

@media (max-width: 560px) {
  .app-header {
    padding-inline: 0.7rem;
  }

  .document-search input {
    min-width: 0;
  }
}

@media (prefers-reduced-motion: reduce) {
  .tab,
  .panel-tab,
  .term-row,
  .result-card,
  .filter-option,
  .search-navigation button,
  .occurrence-controls button {
    transition: none !important;
  }
}

@media (forced-colors: active) {
  .app-header,
  .document-shell,
  .results-panel,
  .history-card {
    forced-color-adjust: auto;
  }

  .search-hit,
  ::highlight(definition-check-search),
  ::highlight(definition-check-search-current) {
    forced-color-adjust: none;
    background: Highlight;
    color: HighlightText;
  }
}

.identity h1 { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.app-header .document-search { width: min(25rem, 48vw); margin-left: auto; }
.document-toolbar { display: block; }
.document-search { flex-direction: row; align-items: stretch; min-width: 0; }
.document-search input { width: 100%; }
.search-navigation { align-self: stretch; }
.document-category-key { min-width: 0; }
.category-key > p { margin: 0 0 .35rem; color: var(--muted); font-size: .68rem; font-weight: 700; text-transform: uppercase; }
.toolbar-legend-items { display: flex; flex-wrap: wrap; align-items: center; gap: .3rem; }
.category-key .filter-options { position: static; display: contents; padding: 0; border: 0; box-shadow: none; }
.category-key .filter-option, .mark-key { display: inline-flex; align-items: center; width: auto; min-height: 1.6rem; gap: .3rem; padding: .2rem .42rem; border: 1px solid var(--line); border-radius: 5px; background: var(--paper); color: var(--muted); font-size: .68rem; white-space: nowrap; }
.category-key .filter-option { border-left-width: 1px; }
.category-key .filter-option::before, .mark-key::before { content: ""; width: .48rem; height: .48rem; flex: 0 0 .48rem; border: 1px solid var(--category-accent, var(--ink)); border-radius: 2px; background: color-mix(in srgb, var(--category-accent, var(--ink)) 18%, white); }
.category-key .filter-option strong { min-width: auto; margin-left: .12rem; }
.category-key .filter-option.active { color: var(--ink); border-color: var(--category-accent, var(--ink)); box-shadow: inset 0 -2px var(--category-accent, var(--ink)); }
.definition-key { --category-accent: #3f7f53; }
.use-key { --category-accent: #4776ad; }
.panel-meta { position: sticky; top: 3.15rem; z-index: 4; background: var(--paper); }
.result-group { overflow: visible; }
.result-group-cards { overflow: hidden; border-radius: 0 0 6px 6px; }
.result-group-heading { position: static; }
.results-panel { scroll-padding-top: 8rem; }
.result-card, .evidence { scroll-margin-top: 8rem; }
.category-label { display: inline-flex; padding: .12rem .42rem; border: 1px solid currentColor; border-radius: 999px; font-size: .68rem; font-weight: 700; }
.category-undefined { --category-accent: #9b2c2c; }
.category-unused { --category-accent: #8a4b08; }
.category-duplicate { --category-accent: #6b46a1; }
.category-inconsistent { --category-accent: #1f5f99; }
.category-used-before { --category-accent: #7a5410; }
.category-broken-reference { --category-accent: #7b2f72; }
.category-external-reference { --category-accent: #326b58; }
.category-needs-review { --category-accent: #5d3d8f; }
.result-card[class*="category-"], .filter-option[class*="category-"] { border-left: 3px solid var(--category-accent, var(--ink)); }
.category-label { color: var(--category-accent, var(--ink)); }
.annotation.issue[class*="category-"], .annotation.needs-review[class*="category-"] { --annotation-rest: color-mix(in srgb, var(--category-accent, #a33b36) 14%, white); --annotation-hover: color-mix(in srgb, var(--category-accent, #a33b36) 23%, white); --annotation-selected: color-mix(in srgb, var(--category-accent, #a33b36) 32%, white); --annotation-accent: var(--category-accent, #a33b36); }
.annotation.issue[class*="category-"] { border-bottom-style: double; }
.annotation.needs-review[class*="category-"] { border-bottom-style: dashed; }
.evidence { display: block; width: 100%; margin-top: .65rem; padding: .55rem; border: 1px solid var(--line); border-radius: 6px; background: var(--paper); color: inherit; text-align: left; cursor: pointer; }
.evidence:hover { border-color: var(--category-accent, var(--ink)); background: var(--surface-subtle); }
.evidence:focus-visible { outline: 3px solid var(--focus); outline-offset: 2px; }
.review-reason, .next-check, .scope-note { padding-left: .55rem; border-left: 3px solid var(--category-accent, var(--ink)); }
@media (max-width: 560px) { .identity h1 { white-space: normal; } .app-header .document-search { width: 100%; margin: .55rem 0 0; } }
""".strip()
)
