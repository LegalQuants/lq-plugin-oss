"""The single embedded stylesheet for the conform redline.

Light-default, local system fonts only, no remote fonts/scripts/stylesheets/
images/analytics — matching the "no remote resources, works offline"
constraint that already governs definition-check's dashboard
(`../../definition-check/scripts/definition_check/dashboard_theme.py`).
"""

from __future__ import annotations

REDLINE_STYLE = """
:root { color-scheme: light; --ink:#172033; --muted:#667085; --line:#d8dee8; --paper:#fff; --canvas:#f4f6f8; --navy:#19345f; --del-bg:#fde8e7; --del-ink:#8a2f2a; --ins-bg:#e5f4ea; --ins-ink:#1f5c33; --amber:#fff0cf; font: 16px/1.6 system-ui, -apple-system, "Segoe UI", Arial, sans-serif; }
* { box-sizing: border-box; }
body { margin: 0; color: var(--ink); background: var(--canvas); }
header, main, footer { max-width: 900px; margin: auto; padding: 1rem clamp(1rem, 3vw, 2rem); }
header { background: var(--paper); border-bottom: 1px solid var(--line); }
h1 { margin: 0 0 .2rem; font: 600 1.35rem/1.3 Georgia, "Times New Roman", serif; }
.scope-note { margin: .4rem 0 0; color: var(--muted); font-size: .9rem; }
.mode-badge { display: inline-block; margin-bottom: .5rem; padding: .15rem .55rem; border-radius: 999px; background: var(--amber); color: #6b4c00; font-size: .75rem; font-weight: 700; letter-spacing: .02em; text-transform: uppercase; }
.clause { background: var(--paper); border: 1px solid var(--line); border-radius: 8px; padding: 1.25rem clamp(1rem, 3vw, 1.75rem); margin: 1rem 0; font: 1.05rem/1.75 Georgia, "Times New Roman", serif; white-space: pre-wrap; overflow-wrap: anywhere; }
del { background: var(--del-bg); color: var(--del-ink); text-decoration: line-through; padding: 0 .1em; border-radius: 2px; }
ins { background: var(--ins-bg); color: var(--ins-ink); text-decoration: none; padding: 0 .1em; border-radius: 2px; }
h2 { font: 600 1.05rem/1.3 Georgia, "Times New Roman", serif; margin: 1.5rem 0 .5rem; }
table { width: 100%; border-collapse: collapse; background: var(--paper); border: 1px solid var(--line); border-radius: 8px; overflow: hidden; }
th, td { text-align: left; padding: .55rem .7rem; border-bottom: 1px solid var(--line); font-size: .92rem; vertical-align: top; }
th { background: #f8fafc; color: var(--muted); font-size: .78rem; text-transform: uppercase; letter-spacing: .04em; }
tr:last-child td { border-bottom: none; }
.badge { display: inline-block; padding: .1rem .5rem; border-radius: 999px; font-size: .75rem; font-weight: 700; }
.badge.escalate { background: var(--del-bg); color: var(--del-ink); }
.badge.clear { background: var(--ins-bg); color: var(--ins-ink); }
.evidence-list { margin: .3rem 0 0; padding-left: 1.1rem; color: var(--muted); font-size: .85rem; }
footer { color: var(--muted); font-size: .8rem; }
""".strip()
