"""Bounded OOXML operations; no inference or dependency installation."""

from copy import deepcopy
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS = {"w": W}
ET.register_namespace("w", W)
ET.register_namespace("r", R)
MAX_BYTES = 64 * 1024 * 1024
TABLE_WIDTH = 14800
# Inert page-number fields are the only field codes the helper writes or edits.
PAGE_FIELDS = ("PAGE", "NUMPAGES")


def tag(name):
    return f"{{{W}}}{name}"


def xml(data):
    if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        raise ValueError("XML declarations with entities are unsupported")
    return ET.fromstring(data)


def package(path):
    if Path(path).stat().st_size > MAX_BYTES:
        raise ValueError("DOCX exceeds 64 MiB limit")
    with ZipFile(path) as z:
        entries = z.infolist()
        if len(entries) > 4096 or sum(x.file_size for x in entries) > MAX_BYTES:
            raise ValueError("Expanded DOCX exceeds package limit")
        if len({x.filename for x in entries}) != len(entries):
            raise ValueError("Duplicate package members")
        parts = {x.filename: z.read(x) for x in entries}
    if "word/document.xml" not in parts:
        raise ValueError("Not a Word document")
    return parts


def serialize(node):
    return ET.tostring(node, encoding="utf-8", xml_declaration=True)


def archive(parts):
    # OPC requires the content types stream to come first in the ZIP package;
    # the stable sort leaves every other part in its original order.
    buf = BytesIO()
    with ZipFile(buf, "w", ZIP_DEFLATED) as z:
        for name in sorted(parts, key=lambda n: n != "[Content_Types].xml"):
            z.writestr(name, parts[name])
    return buf.getvalue()


def text(node):
    values = []
    for p in node.iter(tag("p")):
        # Only run content is text; a tab stop under pPr is layout, not a tab.
        values.append(
            "".join(
                n.text or ""
                if n.tag == tag("t")
                else "\n"
                if n.tag == tag("br")
                else "\t"
                if n.tag == tag("tab")
                else ""
                for r in p.iter(tag("r"))
                for n in r.iter()
            )
        )
    return "\n".join(values)


def tables(root):
    body = root.find("w:body", NS)
    if body is None:
        raise ValueError("Missing document body")
    return body.findall("w:tbl", NS)


def cells(row):
    return row.findall("w:tc", NS)


def rows(table):
    return table.findall("w:tr", NS)


def span(cell):
    node = cell.find("w:tcPr/w:gridSpan", NS)
    return int(node.get(tag("val"), "1")) if node is not None else 1


def inspect(path):
    parts = package(path)
    root = xml(parts["word/document.xml"])
    result = []
    for ti, table in enumerate(tables(root)):
        result.append(
            {
                "table": ti,
                "grid_columns": len(table.findall("w:tblGrid/w:gridCol", NS)),
                "rows": [
                    {
                        "row": ri,
                        "cells": [text(c) for c in cells(row)],
                        "spans": [span(c) for c in cells(row)],
                        "vertical_merge": any(
                            c.find("w:tcPr/w:vMerge", NS) is not None
                            for c in cells(row)
                        ),
                    }
                    for ri, row in enumerate(rows(table))
                ],
            }
        )
    return result


def editable(root, parts):
    # Re-serialising extension namespaces can invalidate mc:Ignorable prefixes.
    # Preserve such documents by using a host editor rather than stripping them.
    mc = "http://schemas.openxmlformats.org/markup-compatibility/2006"
    if any(n.get(f"{{{mc}}}Ignorable") for n in root.iter()):
        raise ValueError("Extension namespace declarations require a host Word editor")
    forbidden = (
        "ins",
        "del",
        "moveFrom",
        "moveTo",
        "sdt",
        "altChunk",
        "fldChar",
        "instrText",
        "object",
        "drawing",
        "pict",
    )
    if any(root.find(f".//w:{name}", NS) is not None for name in forbidden):
        raise ValueError("Tracked, dynamic or embedded content requires a host editor")
    if any(not page_field(f) for f in root.iter(tag("fldSimple"))):
        raise ValueError("Field codes other than page numbers require a host editor")
    if any(
        "vbaProject" in name or name.startswith("_xmlsignatures/") for name in parts
    ):
        raise ValueError("Macro or digitally signed package requires a host editor")
    settings = parts.get("word/settings.xml")
    if settings and xml(settings).find("w:documentProtection", NS) is not None:
        raise ValueError("Protected document requires a host editor")


def page_field(field):
    """True for a simple PAGE/NUMPAGES field, with or without format switches."""
    instr = (field.get(tag("instr")) or "").strip().upper()
    return instr.split()[:1] in ([name] for name in PAGE_FIELDS)


def plain_row(row, columns):
    cs = cells(row)
    if len(cs) != columns or any(span(c) != 1 for c in cs):
        raise ValueError("Item row must have one cell per grid column")
    if row.find("w:trPr/w:gridBefore", NS) is not None:
        raise ValueError("Offset rows require a host editor")
    if any(c.find("w:tcPr/w:vMerge", NS) is not None for c in cs):
        raise ValueError("Vertically merged item rows require a host editor")
    if row.find(".//w:tbl", NS) is not None:
        raise ValueError("Nested item tables require a host editor")
    return cs


def replace_cell(cell, value):
    """Keep cell/first paragraph/run formatting; replace approved cell contents."""
    if not isinstance(value, str):
        raise ValueError("Cell values must be strings")
    # Do not destroy anchors, footnotes, hyperlinks or other non-text content.
    allowed = {tag(x) for x in ("tc", "tcPr", "p", "pPr", "r", "rPr", "t", "br", "tab")}
    for child in cell:
        if child.tag == tag("tcPr"):
            continue
        for node in child.iter():
            if node.tag in {tag("pPr"), tag("rPr")}:
                continue
            if node.tag not in allowed and node not in list(child.iter(tag("pPr"))):
                # Formatting descendants are permitted, content constructs aren't.
                in_props = any(
                    node in list(p.iter())
                    for p in cell.iter()
                    if p.tag in {tag("pPr"), tag("rPr")}
                )
                if not in_props:
                    raise ValueError("Complex cell contents require a host editor")
    old_p = cell.find("w:p", NS)
    p = ET.Element(tag("p"))
    if old_p is not None:
        pp = old_p.find("w:pPr", NS)
        if pp is not None:
            p.append(deepcopy(pp))
    run = ET.SubElement(p, tag("r"))
    rp = cell.find(".//w:rPr", NS)
    if rp is not None:
        run.append(deepcopy(rp))
    for i, line in enumerate(value.split("\n")):
        if i:
            ET.SubElement(run, tag("br"))
        t = ET.SubElement(run, tag("t"))
        t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        t.text = line
    for child in list(cell):
        if child.tag != tag("tcPr"):
            cell.remove(child)
    cell.append(p)


def patch(parts, operations):
    root = xml(parts["word/document.xml"])
    editable(root, parts)
    ts = tables(root)
    # Original row indices stay stable while deletions/insertions are applied.
    snapshots = [rows(t) for t in ts]
    prototypes = deepcopy(snapshots)
    touched = set()
    for op in operations:
        ti, ri = op["table"], op["row"]
        if type(ti) is not int or type(ri) is not int or ti < 0 or ri < 0:
            raise ValueError("Nonnegative table/row indices required")
        table, row = ts[ti], snapshots[ti][ri]
        if (ti, ri) in touched:
            raise ValueError("Combine changes to a row in one operation")
        touched.add((ti, ri))
        if [text(c) for c in cells(row)] != op["before"]:
            raise ValueError("Row no longer matches the reviewed snapshot")
        ncols = len(table.findall("w:tblGrid/w:gridCol", NS))
        kind = op["kind"]
        if kind == "update":
            cs = plain_row(row, ncols)
            for key, value in op["values"].items():
                ci = int(key)
                if ci < 0 or ci >= len(cs):
                    raise ValueError("Invalid cell index")
                replace_cell(cs[ci], value)
        elif kind == "remove":
            plain_row(row, ncols)
            table.remove(row)
        elif kind == "add_after":
            proto_i = op["prototype_row"]
            if type(proto_i) is not int or proto_i < 0:
                raise ValueError("Invalid prototype row")
            new = deepcopy(prototypes[ti][proto_i])
            cs = plain_row(new, ncols)
            if len(op["values"]) != ncols:
                raise ValueError("New row must specify every column")
            for c, value in zip(cs, op["values"], strict=True):
                replace_cell(c, value)
            table.insert(list(table).index(row) + 1, new)
        else:
            raise ValueError("Unknown operation")
    result = dict(parts)
    result["word/document.xml"] = serialize(root)
    return result


def element(parent, name, **attrs):
    return ET.SubElement(parent, tag(name), {tag(k): str(v) for k, v in attrs.items()})


def paragraph(parent, value, bold=False, size=20, italic=False, keep_next=False):
    p = element(parent, "p")
    pp = element(p, "pPr")
    if keep_next:
        element(pp, "keepNext")
    element(pp, "spacing", after=80)
    r = element(p, "r")
    rp = element(r, "rPr")
    element(rp, "rFonts", ascii="Calibri", hAnsi="Calibri")
    if bold:
        element(rp, "b")
    if italic:
        element(rp, "i")
    element(rp, "sz", val=size)
    element(r, "t").text = value
    return p


def sequenced(headings, records):
    """Re-sequence a plain generated number column after approval filtering.

    Rejecting a proposal would otherwise leave the approved rows numbered 1, 3.
    A manual scheme (1a, blanks, a first column that is not the number) is left
    exactly as supplied rather than guessed at.
    """
    if not headings or not headings[0].strip().lower().startswith("no"):
        return records
    if not all(record["cells"][0].strip().isdigit() for record in records):
        return records
    return [
        {**record, "cells": [str(i), *record["cells"][1:]]}
        for i, record in enumerate(records, 1)
    ]


# Width weights by column meaning; unknown headings share the remainder evenly.
# Longer keys are tested first so "Notes" is not read as a number column.
WEIGHTS = (
    (("note", "comment", "remark"), 2600),
    (("source", "reference", "clause"), 1900),
    (("item", "action", "document", "deliverable", "description"), 4800),
    (("responsib", "owner", "party", "who"), 1800),
    (("timing", "when", "deadline", "date"), 2300),
    (("status",), 1300),
    (("no.", "no", "ref", "#"), 650),
)
LEGEND_HEADINGS = ("Short label", "Full name", "Role")
KEY_HEADINGS = ("Status", "Meaning")
PARTIES_TITLE = "Parties"
KEY_TITLE = "Status key"
CHECKLIST_TITLE = "Checklist"
FRONT_KEYS = ("scope", "parties", "status_key", "footer")


def widths_for(headings):
    """Landscape column widths that follow the heading's meaning, not its index."""
    weights = []
    for heading in headings:
        lowered = heading.strip().lower()
        weight = next(
            (w for names, w in WEIGHTS if any(n in lowered for n in names)), 1800
        )
        weights.append(weight)
    scale = TABLE_WIDTH / sum(weights)
    return [int(w * scale) for w in weights]


def strings(values, label):
    if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
        raise ValueError(f"{label} must be a list of strings")
    return values


def front_matter(spec):
    """Validate the optional opening sections and footer of a generic checklist."""
    front = {key: spec.get(key) for key in FRONT_KEYS}
    if front["scope"] is not None:
        strings(front["scope"], "scope")
    for key, fields in (
        ("parties", ("label", "name", "role")),
        ("status_key", ("label", "meaning")),
    ):
        entries = front[key]
        if entries is None:
            continue
        if not isinstance(entries, list) or not entries:
            raise ValueError(f"{key} must be a nonempty list")
        for entry in entries:
            if not isinstance(entry, dict) or any(
                not isinstance(entry.get(f), str) or not entry[f].strip()
                for f in fields
            ):
                raise ValueError(f"Each {key} entry needs {', '.join(fields)}")
            if key == "parties" and not isinstance(entry.get("group", ""), str):
                raise ValueError("Party group must be a string")
    if front["footer"] is not None and not isinstance(front["footer"], str):
        raise ValueError("footer must be a string")
    return front


def table_element(parent, widths):
    table = element(parent, "tbl")
    pr = element(table, "tblPr")
    element(pr, "tblW", w=sum(widths), type="dxa")
    element(pr, "tblLayout", type="fixed")
    borders = element(pr, "tblBorders")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        element(borders, edge, val="single", sz=4, color="D9D9D9")
    margins = element(pr, "tblCellMar")
    for side in ("top", "left", "bottom", "right"):
        element(margins, side, w=90, type="dxa")
    grid = element(table, "tblGrid")
    for width in widths:
        element(grid, "gridCol", w=width)
    return table


def add_row(table, widths, values, kind="item"):
    """kind: header (repeats per page), phase or group (merged), or item."""
    row = element(table, "tr")
    rp = element(row, "trPr")
    element(rp, "cantSplit")
    if kind == "header":
        element(rp, "tblHeader")
    merged = kind in ("phase", "group")
    for i, value in enumerate(values):
        cell = element(row, "tc")
        cp = element(cell, "tcPr")
        element(cp, "tcW", w=sum(widths) if merged else widths[i], type="dxa")
        element(cp, "vAlign", val="center")
        if merged:
            element(cp, "gridSpan", val=len(widths))
        if kind == "header":
            element(cp, "shd", fill="E7E6E6")
        elif kind == "phase":
            element(cp, "shd", fill="F2F2F2")
        elif kind == "group":
            element(cp, "shd", fill="FAFAFA")
        paragraph(
            cell,
            value,
            bold=kind in ("header", "phase"),
            italic=kind == "group",
            keep_next=merged,
        )
    return row


def legend_table(body, title, headings, rows_, grouped=False):
    widths = [2600, 5200, 7000] if len(headings) == 3 else [2600, 12200]
    paragraph(body, title, bold=True, size=22, keep_next=True)
    table = table_element(body, widths)
    add_row(table, widths, headings, "header")
    group = None
    for entry in rows_:
        if grouped and entry[0] != group:
            group = entry[0]
            add_row(table, widths, [group], "phase")
        add_row(table, widths, entry[1:] if grouped else entry)
    return table


def footer_part(basis):
    """One footer for every page: source-draft basis left, page numbers right."""
    ftr = ET.Element(tag("ftr"))
    p = element(ftr, "p")
    pp = element(p, "pPr")
    tabs = element(pp, "tabs")
    element(tabs, "tab", val="right", pos=TABLE_WIDTH)
    element(pp, "spacing", after=0)

    def run(value=None, field=None):
        r = element(p, "r")
        rp = element(r, "rPr")
        element(rp, "rFonts", ascii="Calibri", hAnsi="Calibri")
        element(rp, "sz", val=16)
        if value is not None:
            t = element(r, "t")
            t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
            t.text = value
        elif field:
            element(r, "tab")

    run(basis or "")
    run(field=True)
    run("Page ")
    for i, name in enumerate(PAGE_FIELDS):
        if i:
            run(" of ")
        f = element(p, "fldSimple", instr=f" {name} ")
        r = element(f, "r")
        rp = element(r, "rPr")
        element(rp, "rFonts", ascii="Calibri", hAnsi="Calibri")
        element(rp, "sz", val=16)
        element(r, "t").text = "1"
    return serialize(ftr)


def generic(title, headings, records, front=None):
    """Helper-created landscape checklist: title, scope, legends, table, footer."""
    if not 5 <= len(headings) <= 8:
        raise ValueError("Generic layout requires five to eight columns")
    if any(len(record["cells"]) != len(headings) for record in records):
        raise ValueError("Every item must match the column count")
    front = front_matter(front or {})
    root = ET.Element(tag("document"))
    body = element(root, "body")
    paragraph(body, title, True, 28)
    for line in front["scope"] or []:
        paragraph(body, line)
    if front["parties"]:
        grouped = any(e.get("group") for e in front["parties"])
        legend_table(
            body,
            PARTIES_TITLE,
            LEGEND_HEADINGS,
            [
                [e.get("group") or "Other", e["label"], e["name"], e["role"]]
                if grouped
                else [e["label"], e["name"], e["role"]]
                for e in front["parties"]
            ],
            grouped,
        )
    if front["status_key"]:
        legend_table(
            body,
            KEY_TITLE,
            KEY_HEADINGS,
            [[e["label"], e["meaning"]] for e in front["status_key"]],
        )
    # A paragraph between tables stops Word joining the key and the checklist
    # into one table, which would repeat the wrong header row on later pages.
    paragraph(body, CHECKLIST_TITLE, bold=True, size=22, keep_next=True)
    widths = widths_for(headings)
    table = table_element(body, widths)
    add_row(table, widths, headings, "header")
    phase = group = None
    for record in records:
        if record["phase"] != phase:
            phase, group = record["phase"], None
            add_row(table, widths, [phase], "phase")
        if record.get("group") and record["group"] != group:
            group = record["group"]
            add_row(table, widths, [group], "group")
        add_row(table, widths, record["cells"])
    section = element(body, "sectPr")
    ref = element(section, "footerReference", type="default")
    ref.set(f"{{{R}}}id", "rId1")
    element(section, "pgSz", w=16838, h=11906, orient="landscape")
    element(section, "pgMar", top=720, bottom=900, left=1000, right=1000, footer=400)
    return {
        "word/document.xml": serialize(root),
        "word/footer1.xml": footer_part(front["footer"]),
        "word/_rels/document.xml.rels": (
            b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            b'<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/'
            b'officeDocument/2006/relationships/footer" Target="footer1.xml"/>'
            b"</Relationships>"
        ),
        "[Content_Types].xml": (
            b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            b'<Default Extension="rels" ContentType="application/'
            b'vnd.openxmlformats-package.relationships+xml"/>'
            b'<Default Extension="xml" ContentType="application/xml"/>'
            b'<Override PartName="/word/document.xml" ContentType="application/'
            b'vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            b'<Override PartName="/word/footer1.xml" ContentType="application/'
            b'vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/>'
            b"</Types>"
        ),
        "_rels/.rels": (
            b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            b'<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/'
            b'officeDocument/2006/relationships/officeDocument" '
            b'Target="word/document.xml"/>'
            b"</Relationships>"
        ),
    }


GENERIC_PARTS = frozenset(
    (
        "word/document.xml",
        "word/footer1.xml",
        "word/_rels/document.xml.rels",
        "[Content_Types].xml",
        "_rels/.rels",
    )
)


def parse_generic(parts, table_index=None):
    """Invert generic(): plain strings only, so a rebuild carries no hidden data.

    Returns title, front matter, checklist headings and records, and the index
    of the checklist table. Anything outside the helper's own layout is an error.
    """
    root = xml(parts["word/document.xml"])
    body = root.find("w:body", NS)
    if body is None:
        raise ValueError("Missing document body")
    children = list(body)
    if not children or children[-1].tag != tag("sectPr"):
        raise ValueError("Unexpected content outside generic checklist")
    ts = tables(root)
    if not ts:
        raise ValueError("Generic checklist table not found")
    checklist = ts[-1] if table_index is None else ts[table_index]
    if checklist is not ts[-1]:
        raise ValueError("The checklist is the last table in a generic document")
    paragraphs = [c for c in children[:-1] if c.tag == tag("p")]
    if not paragraphs or children[0].tag != tag("p"):
        raise ValueError("Generic checklist starts with a title paragraph")
    title = text(paragraphs[0])
    front = {"scope": [], "parties": None, "status_key": None, "footer": None}
    pending = []
    for node in children[1:-1]:
        if node.tag == tag("p"):
            pending.append(text(node))
        elif node.tag == tag("tbl") and node is not checklist:
            heading = pending.pop() if pending else ""
            front["scope"].extend(pending)
            pending = []
            grid = [[text(c) for c in cells(r)] for r in rows(node)]
            if heading == PARTIES_TITLE and grid[0] == list(LEGEND_HEADINGS):
                group, entries = None, []
                for row in grid[1:]:
                    if len(row) == 1:
                        group = row[0]
                    else:
                        entries.append(
                            {
                                "label": row[0],
                                "name": row[1],
                                "role": row[2],
                                "group": group or "",
                            }
                        )
                front["parties"] = entries
            elif heading == KEY_TITLE and grid[0] == list(KEY_HEADINGS):
                front["status_key"] = [
                    {"label": r[0], "meaning": r[1]} for r in grid[1:]
                ]
            else:
                raise ValueError("Unknown opening table; use a host editor")
        elif node is checklist:
            if pending and pending[-1] == CHECKLIST_TITLE:
                pending.pop()
            front["scope"].extend(pending)
            pending = []
        else:
            raise ValueError("Unexpected content outside generic checklist")
    if pending:
        raise ValueError("Unexpected content after the checklist table")
    rs = rows(checklist)
    headings = [text(c) for c in cells(rs[0])]
    records, phase, group = [], None, None
    for row in rs[1:]:
        cs = cells(row)
        if len(cs) == 1:
            shade = cs[0].find("w:tcPr/w:shd", NS)
            if shade is not None and shade.get(tag("fill")) == "FAFAFA":
                group = text(cs[0])
            else:
                phase, group = text(cs[0]), None
        else:
            if phase is None:
                raise ValueError("Missing phase heading")
            record = {"phase": phase, "cells": [text(c) for c in cs]}
            if group:
                record["group"] = group
            records.append(record)
    footer = parts.get("word/footer1.xml")
    if footer:
        froot = xml(footer)
        if any(not page_field(f) for f in froot.iter(tag("fldSimple"))):
            raise ValueError("Footer contains fields other than page numbers")
        front["footer"] = text(froot).split("\t")[0]
    if not front["scope"]:
        front["scope"] = None
    return title, front, headings, records, ts.index(checklist)


def from_template(parts, spec, records):
    for key in ("table", "item_row", "phase_row", "body_start"):
        if type(spec[key]) is not int or spec[key] < 0:
            raise ValueError("Template indices must be nonnegative integers")
    root = xml(parts["word/document.xml"])
    editable(root, parts)
    table = tables(root)[spec["table"]]
    rs = rows(table)
    ncols = len(table.findall("w:tblGrid/w:gridCol", NS))
    data = deepcopy(rs[spec["item_row"]])
    plain_row(data, ncols)
    phase_row = deepcopy(rs[spec["phase_row"]])
    if len(cells(phase_row)) != 1 or span(cells(phase_row)[0]) != ncols:
        raise ValueError("Phase prototype must span the full table")
    start = spec["body_start"]
    if not 0 < start < len(rs):
        raise ValueError("Template must retain at least one header row")
    # Explicit template mode replaces the selected table body, not other parts.
    for row in rs[start:]:
        table.remove(row)
    previous = None
    for record in records:
        if record["phase"] != previous:
            previous = record["phase"]
            row = deepcopy(phase_row)
            replace_cell(cells(row)[0], previous)
            table.append(row)
        row = deepcopy(data)
        cs = cells(row)
        if len(record["cells"]) != len(cs):
            raise ValueError("Template columns do not match supplied cells")
        for c, value in zip(cs, record["cells"], strict=True):
            replace_cell(c, value)
        table.append(row)
    result = dict(parts)
    result["word/document.xml"] = serialize(root)
    return result
