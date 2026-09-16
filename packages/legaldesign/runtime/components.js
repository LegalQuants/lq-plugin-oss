(() => {
  window.LegalDesign = window.LegalDesign || {};
  var LD = window.LegalDesign;
  var REGISTRY = [
    "flow",
    "timeline",
    "hierarchy",
    "zones",
    "beforeAfter",
    "hub",
    "compareTwo",
    "funnel",
    "loop",
    "matrix",
    "figurePath",
    "stairSteps",
    "pyramid",
    "gears",
    "rungBars",
    "hairlineLine",
    "hairlineArea",
    "tickDonut",
    "tickRows",
    "pairedRungs",
    "stackedRungs",
    "plumbScatter",
    "rungWaterfall",
    "dotHeat",
    "tickGauge",
    "dumbbell",
    "treemap",
    "rungHistogram",
    "tickBox",
    "streamRibbon",
    "rangeBars",
  ];
  var C = Object.create(null);
  var NS = "http://www.w3.org/2000/svg";
  var ACCENT_ROLES = Object.freeze([
    "open",
    "incomplete",
    "uncovered",
    "recommendation",
    "action",
    "decision",
    "active",
  ]);

  function esc(t) {
    return String(t)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function known(value, name, allowed) {
    object(value, name);
    Object.keys(value).forEach((key) => {
      if (!allowed.includes(key))
        throw new TypeError(`${name}.${key} is an unknown field`);
    });
    return value;
  }

  function object(value, name = "data") {
    if (!value || typeof value !== "object" || Array.isArray(value))
      throw new TypeError(`${name} must be an object`);
    return value;
  }
  function text(value, name, optional = false) {
    if (optional && value == null) return "";
    if (typeof value !== "string" || (!optional && !value.trim()))
      throw new TypeError(
        `${name} must be ${optional ? "a string when supplied" : "a non-empty string"}`,
      );
    return value;
  }
  function list(value, name, min, max) {
    if (!Array.isArray(value) || value.length < min || value.length > max)
      throw new TypeError(
        `${name} must contain ${min === max ? min : `${min}–${max}`} items`,
      );
    return value;
  }
  function choice(value, name, choices, optional = false) {
    if (optional && value == null) return;
    if (!choices.includes(value))
      throw new TypeError(`${name} must be one of ${choices.join(", ")}`);
  }
  function strings(value, name, min, max = min) {
    list(value, name, min, max);
    value.forEach((v, i) => {
      text(v, `${name}[${i}]`);
    });
    return value;
  }
  function records(value, name, min, max, required, optional = []) {
    list(value, name, min, max);
    value.forEach((v, i) => {
      known(v, `${name}[${i}]`, required.concat(optional));
      required.forEach((k) => {
        text(v[k], `${name}[${i}].${k}`);
      });
      optional.forEach((k) => {
        if (k === "accentRole") {
          choice(v[k], `${name}[${i}].${k}`, ACCENT_ROLES, true);
        } else if (k !== "leaves") text(v[k], `${name}[${i}].${k}`, true);
      });
    });
    return value;
  }
  function checkOpts(opts) {
    known(opts, "opts", [
      "narrow",
      "compact",
      "density",
      "width",
      "theme",
      "ariaLabel",
    ]);
    if (opts.density != null && !["standard", "compact"].includes(opts.density))
      throw new TypeError("opts.density must be standard or compact");
    if (opts.narrow != null && typeof opts.narrow !== "boolean")
      throw new TypeError("opts.narrow must be boolean");
    if (opts.compact != null && typeof opts.compact !== "boolean")
      throw new TypeError("opts.compact must be boolean");
  }
  function detailWrap(markup, detail, hitbox) {
    // Text-only SVG groups have no painted shape. Labels intentionally ignore
    // pointer events in view mode, so give them an explicit transparent target.
    const hit =
      detail && hitbox
        ? `<rect class="detail-hit" x="${hitbox[0]}" y="${hitbox[1]}" width="${hitbox[2]}" height="${hitbox[3]}" fill="transparent" stroke="none" pointer-events="all"/>`
        : "";
    return typeof detail === "string" && detail
      ? `<g data-diagram-object class="ld-detail" role="button" tabindex="0" aria-haspopup="dialog" aria-controls="${esc(detail)}" data-detail="${esc(detail)}">${hit}${markup}</g>`
      : `<g data-diagram-object>${markup}</g>`;
  }
  function sentence(data) {
    const words = [];
    const visit = (value) => {
      if (typeof value === "string" && value.trim()) words.push(value.trim());
      else if (Array.isArray(value)) value.forEach(visit);
      else if (value && typeof value === "object")
        Object.keys(value)
          .filter((key) => key !== "detail")
          .forEach((key) => {
            visit(value[key]);
          });
    };
    visit(data);
    return `Diagram showing ${words.slice(0, 10).join(", ")}.`;
  }

  function lines(value, maxChars = 20, maxLines = 3) {
    const words = String(value).trim().split(/\s+/),
      out = [];
    words.forEach((word) => {
      if (!out.length || `${out.at(-1)} ${word}`.length > maxChars)
        out.push(word);
      else out[out.length - 1] += ` ${word}`;
    });
    if (out.length > maxLines)
      return [...out.slice(0, maxLines - 1), out.slice(maxLines - 1).join(" ")];
    return out;
  }
  function txt(value, x, y, width, cls = "", maxLines = 2, anchor = "middle") {
    if (value == null || value === "") return "";
    // Uppercase relationship labels include tracking, so budget their real
    // letter width instead of letting them intrude into adjacent cards.
    const chars = Math.max(
        5,
        Math.floor(width / (cls === "edge" ? 8.25 : 6.2)),
      ),
      rows = lines(value, chars, maxLines),
      first = y - (rows.length - 1) * 7;
    return `<text class="${cls}" x="${x}" y="${first}" text-anchor="${anchor}">${rows.map((row, i) => `<tspan x="${x}" dy="${i ? 14 : 0}">${esc(row)}</tspan>`).join("")}</text>`;
  }
  function svgMarkup(body, opts, viewBox, extraClass = "", data = {}) {
    checkOpts(opts);
    const aria = esc(
      typeof opts.ariaLabel === "string" && opts.ariaLabel
        ? opts.ariaLabel
        : sentence(data),
    );
    const width = opts.width == null ? "100%" : esc(opts.width);
    const theme = opts.theme == null ? "" : ` data-theme="${esc(opts.theme)}"`;
    const role = body.includes('data-detail="') ? "group" : "img";
    return `<svg xmlns="${NS}" class="library-viz diagram-viz${extraClass ? ` ${extraClass}` : ""}" viewBox="${viewBox}" width="${width}" role="${role}" aria-label="${aria}"${theme}>
    <style>
      .diagram-viz{display:block;color:var(--ink);overflow:visible}.diagram-viz text{font-family:var(--sans);font-size:14px;font-weight:600;fill:var(--ink);stroke:none}.diagram-viz .sub{font-size:12.25px;font-weight:400;fill:var(--muted)}.diagram-viz .zone,.diagram-viz .edge{font-family:var(--sans);font-size:12.25px;font-weight:650;letter-spacing:0;text-transform:none}.diagram-viz .edge{fill:var(--muted)}.diagram-viz .line,.diagram-viz .hair{fill:none;stroke:var(--line-strong);stroke-width:1;vector-effect:non-scaling-stroke}.diagram-viz .box{fill:var(--card);stroke:transparent;stroke-width:1.5;filter:drop-shadow(0 1px 2px rgba(0,0,0,.06)) drop-shadow(0 7px 16px rgba(0,0,0,.07));vector-effect:non-scaling-stroke}.diagram-viz .box.tint{fill:var(--tint);stroke:var(--line-strong)}.diagram-viz .box.accent{fill:var(--red-wash);stroke:var(--red)}.diagram-viz .tint{fill:var(--tint)}.diagram-viz .inkfill{fill:var(--ink);fill-opacity:.1;stroke:var(--ink);stroke-width:1;vector-effect:non-scaling-stroke}.diagram-viz .band{fill:var(--tint);stroke:var(--line-strong);stroke-width:1;vector-effect:non-scaling-stroke}.diagram-viz .edge-band{fill:var(--tint);stroke:none}.diagram-viz .open{stroke:var(--red);fill:var(--red-wash)}.diagram-viz .leaf{fill:var(--tint);stroke:transparent;stroke-width:1;vector-effect:non-scaling-stroke}.diagram-viz .ld-detail{cursor:pointer;outline:none}.diagram-viz .ld-detail text{user-select:none}
      .chart-viz text{font-size:11.75px}.chart-viz .chart-title{font-size:12.5px;font-weight:650;fill:var(--ink)}.chart-viz .axis-title{font-size:11.75px;font-weight:600;fill:var(--ink)}.chart-viz .value{font-size:12px;font-weight:500;fill:var(--ink)}.chart-viz .muted,.chart-viz .source{fill:var(--muted)}.chart-viz .source{font-size:11.75px}.chart-viz .quiet{fill:none;stroke:var(--muted);stroke-width:1;vector-effect:non-scaling-stroke}.chart-viz .faint{fill:none;stroke:currentColor;stroke-opacity:.18;stroke-width:1;vector-effect:non-scaling-stroke}.chart-viz .fill,.chart-viz .tone-1,.chart-viz .tone-2,.chart-viz .tone-3,.chart-viz .tone-4{stroke:currentColor;stroke-width:1;vector-effect:non-scaling-stroke}.chart-viz .label-pad{stroke:none}.chart-viz .fill,.chart-viz .tone-1{fill:color-mix(in srgb,currentColor 14%,var(--card))}.chart-viz .tone-2{fill:color-mix(in srgb,currentColor 28%,var(--card))}.chart-viz .tone-3{fill:color-mix(in srgb,currentColor 48%,var(--card))}.chart-viz .tone-4{fill:color-mix(in srgb,currentColor 72%,var(--card))}.chart-viz .open{stroke:var(--red);fill:var(--red-wash)}.chart-viz .open-line{stroke:var(--red)}
      .diagram-viz .ld-detail:hover>.box:first-child,.diagram-viz .ld-detail:hover>.leaf:first-child,html:not([data-input-modality="pointer"]) .diagram-viz .ld-detail:focus-visible>.box:first-child,html:not([data-input-modality="pointer"]) .diagram-viz .ld-detail:focus-visible>.leaf:first-child{stroke:var(--interaction)}
      :is(html[data-theme="dark"] .diagram-viz:not([data-theme="light"]),.diagram-viz[data-theme="dark"]){--ld-node-fill:var(--card,#111);--ld-node-ink:#fff;--ld-node-muted:#fff;--ld-node-accent-ink:#fff;--ld-node-outline:#999}
      :is(html[data-theme="dark"] .diagram-viz:not([data-theme="light"]),.diagram-viz[data-theme="dark"]):not(.chart-viz) :is(.box,.leaf,.band,.tint,.inkfill){fill:var(--ld-node-fill);fill-opacity:1;stroke:var(--ld-node-outline);stroke-width:2;filter:none}
      :is(html[data-theme="dark"] .diagram-viz:not([data-theme="light"]),.diagram-viz[data-theme="dark"]):not(.chart-viz) :is(.box,.inkfill)+circle.line{stroke:var(--ld-node-muted)}
      :is(html[data-theme="dark"] .diagram-viz:not([data-theme="light"]),.diagram-viz[data-theme="dark"]):not(.chart-viz) :is(.box,.band,.leaf).accent,:is(html[data-theme="dark"] .diagram-viz:not([data-theme="light"]),.diagram-viz[data-theme="dark"]):not(.chart-viz) .open{fill:var(--ld-node-fill);fill-opacity:1;stroke:var(--red)}
      :is(html[data-theme="dark"] .diagram-viz:not([data-theme="light"]),.diagram-viz[data-theme="dark"]):not(.chart-viz) text{fill:var(--ld-node-ink)}
      :is(html[data-theme="dark"] .diagram-viz:not([data-theme="light"]),.diagram-viz[data-theme="dark"]):not(.chart-viz) :is(.line,.hair){stroke:#fff;stroke-width:1.5}
      :is(html[data-theme="dark"] .diagram-viz:not([data-theme="light"]),.diagram-viz[data-theme="dark"]):not(.chart-viz) [data-diagram-object]:has(> :is(.box,.leaf,.band,.tint,.inkfill))>text,:is(html[data-theme="dark"] .diagram-viz:not([data-theme="light"]),.diagram-viz[data-theme="dark"]):not(.chart-viz) .surface-text{fill:var(--ld-node-ink)}
      :is(html[data-theme="dark"] .diagram-viz:not([data-theme="light"]),.diagram-viz[data-theme="dark"]):not(.chart-viz) [data-diagram-object]:has(> :is(.box,.leaf,.band,.tint))>text.sub{fill:var(--ld-node-muted)}
      :is(html[data-theme="dark"] .diagram-viz:not([data-theme="light"]),.diagram-viz[data-theme="dark"]):not(.chart-viz) [data-diagram-object]:has(> :is(.accent,.open))>text:is(.sub,:not(.sub)){fill:var(--ld-node-accent-ink)}
      html[data-theme="dark"] .chart-viz .fill.open,html[data-theme="dark"] .chart-viz .tone-1.open,.chart-viz[data-theme="dark"] .fill.open,.chart-viz[data-theme="dark"] .tone-1.open{fill:color-mix(in srgb,currentColor 14%,var(--card))}
      html[data-theme="dark"] .chart-viz .tone-2.open,.chart-viz[data-theme="dark"] .tone-2.open{fill:color-mix(in srgb,currentColor 28%,var(--card))}
      html[data-theme="dark"] .chart-viz .tone-3.open,.chart-viz[data-theme="dark"] .tone-3.open{fill:color-mix(in srgb,currentColor 48%,var(--card))}
      html[data-theme="dark"] .chart-viz .tone-4.open,.chart-viz[data-theme="dark"] .tone-4.open{fill:color-mix(in srgb,currentColor 72%,var(--card))}
    </style>${body}</svg>`;
  }
  function svg(body, opts, frame = "pane", data = {}) {
    const viewBox =
      frame === "wideTall"
        ? "0 0 880 420"
        : frame === "wide"
          ? "0 0 880 360"
          : "0 0 400 400";
    return svgMarkup(body, opts, viewBox, "", data);
  }
  function accentAttr(role) {
    return role ? ` data-accent-role="${esc(role)}"` : "";
  }
  function box(x, y, w, h, title, sub = "", opts = {}) {
    const cls = `box${opts.tint ? " tint" : ""}${opts.accentRole ? " accent" : ""}${opts.open ? " open" : ""}`;
    const cy = y + h / 2;
    return detailWrap(
      `<rect class="${cls}"${accentAttr(opts.accentRole)} x="${x}" y="${y}" width="${w}" height="${h}" rx="7"/>${txt(title, x + w / 2, cy - (sub ? 8 : 0), w - 18, opts.titleClass || "", 2)}${sub ? txt(sub, x + w / 2, cy + 19, w - 18, "sub", 2) : ""}`,
      opts.detail,
    );
  }

  function flowCard(x, y, w, h, stage) {
    return box(x, y, w, h, stage.title, stage.sub, stage);
  }
  function hierarchyLeaf(x, y, w, h, leaf) {
    return detailWrap(
      `<rect class="leaf" x="${x}" y="${y}" width="${w}" height="${h}" rx="5"/>${txt(leaf.title, x + w / 2, y + h / 2 + 4, w - 12, "sub", 2)}`,
      leaf.detail,
    );
  }
  function arrowH(x1, x2, y, edge, reverse = false) {
    const from = reverse ? x2 : x1,
      to = reverse ? x1 : x2,
      sign = to > from ? 1 : -1,
      end = to - sign * 7;
    return `<path class="line" d="M${from} ${y}H${end}"/><path class="line" d="M${to - sign * 7} ${y - 4}L${to} ${y}L${to - sign * 7} ${y + 4}"/>${txt(edge, (x1 + x2) / 2, y - 25, Math.abs(x2 - x1) - 32, "edge", 3)}`;
  }
  function arrowV(y1, y2, x, edge) {
    const sign = y2 > y1 ? 1 : -1,
      end = y2 - sign * 7;
    return `<path class="line" d="M${x} ${y1}V${end}"/><path class="line" d="M${x - 4} ${y2 - sign * 7}L${x} ${y2}L${x + 4} ${y2 - sign * 7}"/>${txt(edge, x + 18, (y1 + y2) / 2 + 3, 120, "edge", 2, "start")}`;
  }

  // A thumbnail may scale a diagram, but must not remove facts or change its
  // relationships. Keep compact as a compatibility option for saved files.
  function compactDiagram(id, data, opts) {
    return C[id](data, { ...opts, compact: false });
  }

  function narrowSvg(body, opts, height = 400, data = {}) {
    return svgMarkup(body, opts, `0 0 400 ${height}`, "narrow-viz", data);
  }

  function narrowDiagram(id, data, opts) {
    let body = "";
    let height = 400;

    if (id === "flow") {
      const boxH = 68,
        gap = opts.density === "compact" ? 48 : 62;
      height =
        28 + data.stages.length * boxH + (data.stages.length - 1) * gap + 28;
      data.stages.forEach((stage, i) => {
        const y = 28 + i * (boxH + gap);
        body += box(40, y, 320, boxH, stage.title, stage.sub, stage);
        if (i < data.stages.length - 1)
          body += arrowV(y + boxH + 6, y + boxH + gap - 6, 200, data.edges[i]);
      });
    } else if (id === "timeline") {
      const boxH = 66,
        step = 94;
      height = 24 + (data.marks.length - 1) * step + boxH + 24;
      body = `<path class="line" d="M104 38V${height - 38}M100 ${height - 45}L104 ${height - 38}L108 ${height - 45}"/>`;
      data.marks.forEach((mark, i) => {
        const y = 24 + i * step,
          cy = y + boxH / 2,
          active = i === data.nowAt;
        body += `${txt(mark.when, 84, cy + 4, 70, active ? "zone" : "edge", 1, "end")}<circle class="${active ? "box accent" : "box"}"${accentAttr(active ? "active" : undefined)} cx="104" cy="${cy}" r="4.5"/>${box(122, y, 256, boxH, mark.title, mark.sub, { accentRole: active ? "active" : undefined, detail: mark.detail })}`;
      });
    } else if (id === "hierarchy") {
      const gap = opts.density === "compact" ? 28 : 62,
        branchHeights = data.branches.map((branch) => {
          const leaves = branch.leaves || [];
          if (!leaves.length) return branch.sub ? 82 : 70;
          return branch.sub ? 122 : 104;
        });
      height =
        26 +
        68 +
        data.branches.reduce(
          (total, _branch, index) => total + gap + branchHeights[index],
          0,
        ) +
        24;
      body = box(142, 26, 236, 68, data.root, data.rootSub, {
        detail: data.rootDetail,
      });
      const lastBranchY =
        26 +
        68 +
        branchHeights.slice(0, -1).reduce((sum, h) => sum + h + gap, 0) +
        gap;
      // Each sibling is connected to the root's shared bus. A vertical row
      // must never turn a parent/child tree into a chain of dependencies.
      body += `<path class="line hierarchy-root-bus" d="M142 60H24V${lastBranchY + branchHeights.at(-1) / 2}"/>`;
      let branchY = 26 + 68 + gap;
      data.branches.forEach((branch, i) => {
        const branchH = branchHeights[i],
          leaves = branch.leaves || [],
          titleY =
            branchY + (branch.sub ? 28 : leaves.length ? 31 : branchH / 2 + 4),
          subY = branchY + 51;
        let branchMarkup = `<rect class="box${branch.accentRole ? " accent" : ""}"${accentAttr(branch.accentRole)} x="142" y="${branchY}" width="236" height="${branchH}" rx="7"/>${txt(branch.title, 260, titleY, 202, "", 2)}${branch.sub ? txt(branch.sub, 260, subY, 202, "sub", 2) : ""}`;
        let leafTargets = "";
        if (leaves.length) {
          const leafW = (216 - 10 * (leaves.length - 1)) / leaves.length,
            leafY = branchY + (branch.sub ? 70 : 52),
            leafH = branchH - (leafY - branchY) - 10;
          leaves.forEach((leaf, j) => {
            const leafMarkup = hierarchyLeaf(
              152 + j * (leafW + 10),
              leafY,
              leafW,
              leafH,
              leaf,
            );
            if (leaf.detail) leafTargets += leafMarkup;
            else branchMarkup += leafMarkup;
          });
        }
        body +=
          `<g class="hierarchy-branch-link" data-parent="root" data-branch="${i}">${arrowH(24, 134, branchY + branchH / 2, branch.edge)}</g>` +
          detailWrap(branchMarkup, branch.detail) +
          leafTargets;
        branchY += branchH + gap;
      });
    } else if (id === "zones") {
      const zones = [
        { title: data.zoneA, items: data.itemsA },
        { title: data.zoneB, items: data.itemsB },
      ];
      const itemHeight = (item) => {
        const titleRows = lines(item.title, 51, 2).length;
        const subRows = item.sub ? lines(item.sub, 51, 3).length : 0;
        return Math.max(
          54,
          26 + titleRows * 14 + (subRows ? 7 + subRows * 14 : 0),
        );
      };
      const itemGap = 12;
      const zoneHeights = zones.map(
        (zone) =>
          42 +
          zone.items.reduce((sum, item) => sum + itemHeight(item), 0) +
          Math.max(0, zone.items.length - 1) * itemGap +
          14,
      );
      const gap = 70;
      height = 18 + zoneHeights[0] + gap + zoneHeights[1] + 18;
      let y = 18;
      zones.forEach((zone, zi) => {
        const zh = zoneHeights[zi];
        body += `<rect class="band" x="16" y="${y}" width="368" height="${zh}" rx="4"/>${txt(zone.title, 30, y + 25, 330, "zone surface-text", 1, "start")}`;
        let itemY = y + 42;
        zone.items.forEach((item) => {
          const h = itemHeight(item);
          body += box(30, itemY, 340, h, item.title, item.sub, item);
          itemY += h + itemGap;
        });
        if (!zi)
          body += arrowV(y + zh + 8, y + zh + gap - 8, 200, data.crossing);
        y += zh + gap;
      });
    } else if (id === "beforeAfter") {
      height = 350;
      body =
        box(40, 16, 320, 110, data.beforeLabel, data.beforeSub, {}) +
        arrowV(136, 214, 200, data.edge) +
        box(40, 224, 320, 110, data.afterLabel, data.afterSub);
    } else if (id === "hub") {
      const rowH = 58,
        gap = 12;
      height =
        24 +
        70 +
        30 +
        data.spokes.length * rowH +
        (data.spokes.length - 1) * gap +
        24;
      body = box(100, 24, 200, 70, data.centre);
      // All satellites join the same continuous bus. Splitting the bus at
      // each row leaves later spokes disconnected from the central node.
      body += `<path class="hair hub-bus" d="M200 94V${124 + (data.spokes.length - 1) * (rowH + gap) + rowH / 2}"/>`;
      data.spokes.forEach((spoke, i) => {
        const y = 124 + i * (rowH + gap),
          cy = y + rowH / 2,
          towardCentre = data.toward === "centre",
          arrowTip = towardCentre ? 200 : 218,
          arrowBase = towardCentre ? 207 : 211;
        body += `<path class="line" d="M200 ${cy}H218"/><path class="line hub-arrowhead" data-direction="${towardCentre ? "centre" : "satellites"}" d="M${arrowBase} ${cy - 4}L${arrowTip} ${cy}L${arrowBase} ${cy + 4}"/>${txt(spoke.edge, 190, cy + 4, 154, "edge", 1, "end")}${box(224, y, 154, rowH, spoke.title, "", { detail: spoke.detail })}`;
      });
    } else if (id === "compareTwo") {
      const rowH = 102;
      height = 70 + data.rows.length * rowH + 20;
      body = `${detailWrap(txt(data.a, 112, 36, 168, "zone", 1), data.aDetail, [20, 8, 168, 44])}${detailWrap(txt(data.b, 288, 36, 168, "zone", 1), data.bDetail, [212, 8, 168, 44])}`;
      data.rows.forEach((row, i) => {
        const y = 62 + i * rowH;
        body += `${txt(row.label, 20, y + 14, 360, "zone", 1, "start")}${box(20, y + 26, 168, 62, row.a, "", { tint: data.highlight === "a", titleClass: row.winner === "a" ? "zone" : "" })}${box(212, y + 26, 168, 62, row.b, "", { tint: data.highlight === "b", titleClass: row.winner === "b" ? "zone" : "" })}`;
      });
    } else if (id === "funnel") {
      const widths = data.tiers.length === 3 ? [352, 260, 168] : [332, 206],
        boxH = 70,
        gap = 58;
      height =
        24 + data.tiers.length * boxH + (data.tiers.length - 1) * gap + 82;
      data.tiers.forEach((tier, i) => {
        const w = widths[i],
          x = 200 - w / 2,
          y = 24 + i * (boxH + gap);
        if (i) body += arrowV(y - gap + 6, y - 6, 200, data.edges[i - 1]);
        body += box(x, y, w, boxH, tier.title, tier.sub, {
          detail: tier.detail,
        });
      });
      body +=
        arrowV(height - 72, height - 44, 200, "") +
        txt(data.outcome, 200, height - 18, 340, "zone", 2);
    } else if (id === "loop") {
      const boxH = 58,
        gap = 50;
      height =
        70 + data.steps.length * boxH + (data.steps.length - 1) * gap + 54;
      body = txt(data.centre, 200, 30, 340, "zone", 2);
      data.steps.forEach((step, i) => {
        const y = 58 + i * (boxH + gap);
        body += box(78, y, 284, boxH, step.title, "", {
          detail: step.detail,
        });
        if (i < data.steps.length - 1)
          body += arrowV(y + boxH + 6, y + boxH + gap - 6, 220, step.edge);
      });
      const lastY = 58 + (data.steps.length - 1) * (boxH + gap);
      body += `<path class="line loop-return" d="M78 ${lastY + boxH / 2}H38V${58 + boxH / 2}H71M64 ${58 + boxH / 2 - 4}L71 ${58 + boxH / 2}L64 ${58 + boxH / 2 + 4}"/><g transform="translate(18 ${(lastY + 58 + boxH) / 2}) rotate(-90)">${txt(data.steps.at(-1).edge, 0, 0, 220, "edge", 1)}</g>`;
    } else if (id === "matrix") {
      height = 430;
      const x = 20,
        y = 36,
        size = 360,
        half = 180;
      data.quads.forEach((quad, i) => {
        const qx = x + (i % 2) * half,
          qy = y + Math.floor(i / 2) * half;
        body += detailWrap(
          `<rect class="${i === data.markAt ? "band" : "box"}" x="${qx}" y="${qy}" width="${half}" height="${half}"/>${txt(quad.title, qx + half / 2, qy + half / 2 - (quad.sub ? 12 : 0), half - 26, "zone", 2)}${quad.sub ? txt(quad.sub, qx + half / 2, qy + half / 2 + 22, half - 28, "sub", 3) : ""}`,
          quad.detail,
        );
      });
      body += `${txt(data.yAxis, 20, 22, 170, "zone", 1, "start")}${txt(data.xAxis, 380, 418, 170, "zone", 1, "end")}`;
    } else if (id === "figurePath") {
      height = 430;
      const spots = [
        [82, 330],
        [174, 236],
        [266, 142],
      ];
      body = `<path class="line" d="M46 374C88 356 105 304 150 268S220 204 250 164S300 104 350 64M343 60L350 64L346 72"/>${txt(data.goal, 346, 42, 112, "zone", 1, "end")}`;
      data.marks.forEach((mark, i) => {
        body += `<circle class="inkfill" cx="${spots[i][0]}" cy="${spots[i][1]}" r="5"/>${txt(mark, spots[i][0] + 13, spots[i][1] + 4, 108, "", 1, "start")}`;
      });
      body += txt(data.caption, 200, 408, 350, "sub", 2);
    } else if (id === "stairSteps") {
      height = 430;
      const tread = 344 / data.steps.length,
        rise = 48,
        x0 = 28,
        y0 = 354;
      data.steps.forEach((step, i) => {
        const x = x0 + i * tread,
          y = y0 - i * rise;
        body += `<path class="line" d="M${x} ${i ? y + rise : y}V${y}H${x + tread}"/>${txt(step.title, x + tread / 2, y - (step.sub ? 30 : 11), tread - 10, "", 2)}${step.sub ? txt(step.sub, x + tread / 2, y - 9, tread - 10, "sub", 1) : ""}`;
      });
      if (data.caption) body += txt(data.caption, 200, 410, 350, "sub", 2);
    } else if (id === "pyramid") {
      height = 430;
      const baseY = 342,
        blockH = 48;
      data.blocks.forEach((block, i) => {
        const w = 352 - i * 48,
          x = 200 - w / 2,
          y = baseY - i * (blockH + 4);
        body += detailWrap(
          `<rect class="band" x="${x}" y="${y}" width="${w}" height="${blockH}" rx="3"/>${txt(block.title, 200, y + (block.sub ? 19 : 29), w - 12, "", 1)}${block.sub ? txt(block.sub, 200, y + 36, w - 12, "sub", 1) : ""}`,
        );
      });
      if (data.caption) body += txt(data.caption, 200, 408, 350, "sub", 2);
    } else if (id === "gears") {
      height = 430;
      const gs = [
        { cx: 106, cy: 210, r: 42, t: 10 },
        { cx: 200, cy: 158, r: 61, t: 14 },
        { cx: 302, cy: 222, r: 46, t: 11 },
      ];
      [1, 0, 2].forEach((i) => {
        const gear = gs[i];
        body += `<path class="${i === 2 ? "inkfill" : "box"}" d="${gearPath(gear.cx, gear.cy, gear.r, gear.t, i * 0.22)}"/><circle class="line" cx="${gear.cx}" cy="${gear.cy}" r="${(gear.r * 0.22).toFixed(2)}"/>`;
      });
      const labels = [
        [106, 292],
        [200, 70],
        [302, 310],
      ];
      data.labels.forEach((value, i) => {
        body += txt(value, labels[i][0], labels[i][1], 116, "", 2);
      });
      if (data.caption) body += txt(data.caption, 200, 404, 350, "sub", 2);
    }

    return narrowSvg(body, opts, height, data);
  }

  C.flow = (params, opts) => {
    var data = params;
    opts = opts || {};
    known(data, "params", ["stages", "edges"]);
    const stages = records(
      data.stages,
      "stages",
      2,
      6,
      ["title"],
      ["sub", "detail", "accentRole"],
    );
    const edges = strings(data.edges, "edges", stages.length - 1);
    if (opts.compact) return compactDiagram("flow", data, opts);
    if (opts.narrow === true) return narrowDiagram("flow", data, opts);
    let body = "";
    if (stages.length <= 4) {
      const gap = stages.length === 2 ? 160 : stages.length === 3 ? 148 : 116,
        w = (832 - gap * (stages.length - 1)) / stages.length,
        y = 88,
        h = 178;
      stages.forEach((s, i) => {
        const x = 24 + i * (w + gap);
        body += box(x, y, w, h, s.title, s.sub, {
          accentRole: s.accentRole,
          detail: s.detail,
        });
        if (i < stages.length - 1)
          body += arrowH(x + w + 8, x + w + gap - 8, y + h / 2, edges[i]);
      });
    } else {
      const w = 200,
        h = 112,
        xs = [22, 340, 658],
        top = 44,
        bottom = 218,
        positions = [
          [xs[0], top],
          [xs[1], top],
          [xs[2], top],
          [xs[2], bottom],
          [xs[1], bottom],
          [xs[0], bottom],
        ];
      body += arrowH(xs[0] + w + 8, xs[1] - 8, top + h / 2, edges[0]);
      body += arrowH(xs[1] + w + 8, xs[2] - 8, top + h / 2, edges[1]);
      body += arrowV(top + h + 8, bottom - 8, xs[2] + w / 2, edges[2]);
      body += arrowH(xs[1] + w + 8, xs[2] - 8, bottom + h / 2, edges[3], true);
      if (stages.length === 6)
        body += arrowH(
          xs[0] + w + 8,
          xs[1] - 8,
          bottom + h / 2,
          edges[4],
          true,
        );
      stages.forEach((stage, i) => {
        const [x, y] = positions[i];
        body += flowCard(x, y, w, h, stage);
      });
    }
    return svg(body, opts, "wide", data);
  };

  C.timeline = (params, opts) => {
    var data = params;
    opts = opts || {};
    known(data, "params", ["marks", "nowAt", "orientation"]);
    choice(data.orientation, "orientation", ["horizontal", "vertical"], true);
    const marks = records(
      data.marks,
      "marks",
      3,
      5,
      ["when", "title"],
      ["sub", "detail"],
    );
    if (
      data.nowAt != null &&
      (!Number.isInteger(data.nowAt) ||
        data.nowAt < 0 ||
        data.nowAt >= marks.length)
    )
      throw new TypeError("nowAt must index marks");
    if (data.orientation === "vertical") {
      // This rail encodes order, not elapsed duration. Event depth comes from
      // its prose, so no text is dropped or forced into equally sized boxes.
      const wrap = (value, columns) => lines(value || "", columns, Infinity);
      const blocks = marks.map((mark) => ({
        when: wrap(mark.when, 43),
        title: wrap(mark.title, 37),
        sub: mark.sub ? wrap(mark.sub, 43) : [],
      }));
      let cursor = 26;
      const positions = blocks.map((block) => {
        const y = cursor;
        const height =
          block.when.length * 16 +
          8 +
          block.title.length * 18 +
          (block.sub.length ? 8 + block.sub.length * 17 : 0);
        cursor += height + 28;
        return { y, height };
      });
      const writeLines = (rows, y, cls, leading) =>
        `<text class="${cls}" x="58" y="${y}" text-anchor="start">${rows.map((row, index) => `<tspan x="58" dy="${index ? leading : 0}">${esc(row)}</tspan>`).join("")}</text>`;
      let body = `<style>.timeline-vertical .timeline-hit{fill:transparent;stroke:none}.timeline-vertical .timeline-dot{fill:var(--card);stroke:var(--muted);stroke-width:1.5;vector-effect:non-scaling-stroke}.timeline-vertical .timeline-dot[data-accent-role="active"]{fill:var(--red);stroke:var(--red)}</style><path class="line timeline-rail" d="M28 ${positions[0].y + 5}V${positions.at(-1).y + 5}"/>`;
      blocks.forEach((block, index) => {
        const { y, height } = positions[index];
        const titleY = y + block.when.length * 16 + 8;
        const subY = titleY + block.title.length * 18 + 8;
        const content = `<rect class="timeline-hit" x="12" y="${y - 10}" width="376" height="${height + 14}" rx="4"/><circle class="timeline-dot"${accentAttr(index === data.nowAt ? "active" : undefined)} cx="28" cy="${y + 5}" r="4.5"/>${writeLines(block.when, y + 9, "edge", 16)}${writeLines(block.title, titleY + 11, "", 18)}${block.sub.length ? writeLines(block.sub, subY + 9, "sub", 17) : ""}`;
        body += detailWrap(content, marks[index].detail).replace(
          "<g data-diagram-object",
          `<g data-timeline-event="${index}" data-diagram-object`,
        );
      });
      return svgMarkup(
        body,
        opts,
        `0 0 400 ${cursor - 12}`,
        "timeline-vertical",
        data,
      );
    }
    if (opts.compact) return compactDiagram("timeline", data, opts);
    if (opts.narrow === true) return narrowDiagram("timeline", data, opts);
    const n = marks.length,
      gap = 24,
      w = (828 - gap * (n - 1)) / n,
      axisY = 262;
    let body = `<path class="line" d="M22 ${axisY}H858"/><path class="line" d="M851 ${axisY - 4}L858 ${axisY}L851 ${axisY + 4}"/>`;
    marks.forEach((m, i) => {
      const x = 26 + i * (w + gap),
        cx = x + w / 2,
        now = i === data.nowAt;
      body +=
        box(x, 54, w, 140, m.title, m.sub, {
          accentRole: now ? "active" : undefined,
          detail: m.detail,
        }) +
        `<path class="hair" d="M${cx} 194V257"/><circle class="${now ? "box accent" : "box"}"${accentAttr(now ? "active" : undefined)} cx="${cx}" cy="${axisY}" r="4.5"/>${txt(m.when, cx, 292, w, now ? "zone" : "edge", 1)}`;
    });
    return svg(body, opts, "wide", data);
  };

  C.hierarchy = (params, opts) => {
    var data = params;
    opts = opts || {};
    known(data, "params", ["root", "rootSub", "rootDetail", "branches"]);
    text(data.root, "root");
    text(data.rootSub, "rootSub", true);
    text(data.rootDetail, "rootDetail", true);
    const branches = records(
      data.branches,
      "branches",
      2,
      4,
      ["title", "edge"],
      ["sub", "detail", "leaves", "accentRole"],
    );
    branches.forEach((b, i) => {
      if (b.leaves != null) {
        list(b.leaves, `branches[${i}].leaves`, 1, 2);
        b.leaves.forEach((leaf, j) => {
          known(leaf, `branches[${i}].leaves[${j}]`, ["title", "detail"]);
          text(leaf.title, `branches[${i}].leaves[${j}].title`);
          text(leaf.detail, `branches[${i}].leaves[${j}].detail`, true);
        });
      }
    });
    if (opts.compact) return compactDiagram("hierarchy", data, opts);
    if (opts.narrow === true) return narrowDiagram("hierarchy", data, opts);
    const rootW = 300,
      rootX = 290,
      rootY = 18,
      rootH = 82,
      gap = 24,
      branchY = 204,
      branchH = 156,
      bw = (820 - gap * (branches.length - 1)) / branches.length;
    let body = "";
    branches.forEach((b, i) => {
      const x = 30 + i * (bw + gap),
        cx = x + bw / 2;
      // Break only around the label's ink: a few points of clear space on
      // either side keeps the relationship continuous without drawing through it.
      body += `<path class="line hierarchy-connector" data-label-y="160" d="M440 ${rootY + rootH}V124H${cx}V147M${cx} 166V${branchY - 8}"/><path class="line" d="M${cx - 4} ${branchY - 15}L${cx} ${branchY - 8}L${cx + 4} ${branchY - 15}"/>${txt(b.edge, cx, 160, bw - 8, "edge", 1)}`;
    });
    body += box(rootX, rootY, rootW, rootH, data.root, data.rootSub, {
      detail: data.rootDetail,
    });
    branches.forEach((branch, i) => {
      const x = 30 + i * (bw + gap),
        leaves = branch.leaves || [],
        rowY = branchY + 84,
        rowGap = 8,
        rowW =
          (bw - 32 - rowGap * Math.max(0, leaves.length - 1)) /
          Math.max(1, leaves.length),
        titleY = leaves.length
          ? branchY + (branch.sub ? 35 : 50)
          : branchY + branchH / 2 - (branch.sub ? 8 : 0),
        subY = leaves.length ? branchY + 61 : branchY + branchH / 2 + 19;
      let markup = `<rect class="box${branch.accentRole ? " accent" : ""}"${accentAttr(branch.accentRole)} x="${x}" y="${branchY}" width="${bw}" height="${branchH}" rx="7"/>${txt(branch.title, x + bw / 2, titleY, bw - 34, "", 2)}${branch.sub ? txt(branch.sub, x + bw / 2, subY, bw - 34, "sub", 2) : ""}`;
      let leafTargets = "";
      leaves.forEach((leaf, j) => {
        const lx = x + 16 + j * (rowW + rowGap),
          leafMarkup = hierarchyLeaf(lx, rowY, rowW, 45, leaf);
        // A leaf with its own popup is a sibling target. A leaf without one
        // belongs to the branch's single clickable surface and never gets a
        // separate hover/focus outline.
        if (leaf.detail) leafTargets += leafMarkup;
        else markup += leafMarkup;
      });
      body += detailWrap(markup, branch.detail) + leafTargets;
    });
    return svg(body, opts, "wideTall", data);
  };

  C.zones = (params, opts) => {
    var data = params;
    opts = opts || {};
    known(data, "params", ["zoneA", "itemsA", "zoneB", "itemsB", "crossing"]);
    text(data.zoneA, "zoneA");
    text(data.zoneB, "zoneB");
    text(data.crossing, "crossing");
    const a = records(
        data.itemsA,
        "itemsA",
        1,
        3,
        ["title"],
        ["sub", "detail"],
      ),
      b = records(data.itemsB, "itemsB", 1, 3, ["title"], ["sub", "detail"]);
    if (opts.compact) return compactDiagram("zones", data, opts);
    if (opts.narrow === true) return narrowDiagram("zones", data, opts);
    let body = `<rect class="band" x="14" y="10" width="852" height="150" rx="4"/>${txt(data.zoneA, 34, 32, 300, "zone surface-text", 1, "start")}<rect class="band" x="14" y="242" width="852" height="168" rx="4"/>${txt(data.zoneB, 34, 266, 300, "zone surface-text", 1, "start")}`;
    const row = (items, y) => {
      const gap = 34,
        w = (804 - gap * (items.length - 1)) / items.length;
      return items
        .map((v, i) =>
          box(38 + i * (w + gap), y, w, 90, v.title, v.sub, {
            detail: v.detail,
          }),
        )
        .join("");
    };
    body += row(a, 52) + row(b, 286) + arrowV(160, 242, 440, data.crossing);
    return svg(body, opts, "wideTall", data);
  };

  C.beforeAfter = (params, opts) => {
    var data = params;
    opts = opts || {};
    known(data, "params", [
      "orientation",
      "beforeLabel",
      "beforeSub",
      "edge",
      "afterLabel",
      "afterSub",
    ]);
    ["beforeLabel", "beforeSub", "edge", "afterLabel", "afterSub"].forEach(
      (k) => {
        text(data[k], k);
      },
    );
    choice(data.orientation, "orientation", ["vertical", "horizontal"], true);
    if (opts.compact) return compactDiagram("beforeAfter", data, opts);
    if (opts.narrow === true) return narrowDiagram("beforeAfter", data, opts);
    const horizontal = data.orientation === "horizontal";
    let body = "";
    if (horizontal) {
      body +=
        box(12, 70, 126, 220, data.beforeLabel, data.beforeSub, {}) +
        arrowH(150, 250, 180, data.edge) +
        box(262, 70, 126, 220, data.afterLabel, data.afterSub);
    } else {
      body +=
        box(100, 18, 200, 104, data.beforeLabel, data.beforeSub, {}) +
        arrowV(150, 220, 200, data.edge) +
        box(100, 248, 200, 104, data.afterLabel, data.afterSub);
    }
    return svg(body, opts, "pane", data);
  };

  C.hub = (params, opts) => {
    var data = params;
    opts = opts || {};
    known(data, "params", ["centre", "spokes", "toward"]);
    text(data.centre, "centre");
    choice(data.toward, "toward", ["centre", "satellites"]);
    const spokes = records(
      data.spokes,
      "spokes",
      3,
      6,
      ["title", "edge"],
      ["detail"],
    );
    if (opts.compact) return compactDiagram("hub", data, opts);
    if (opts.narrow === true) return narrowDiagram("hub", data, opts);
    // Aligned spokes preserve direction and leave every relationship label
    // beside its own connector; radial labels otherwise drift onto neighbours.
    const rowH = 64,
      gap = 24,
      height = 48 + spokes.length * rowH + (spokes.length - 1) * gap;
    const centerY = height / 2;
    let body = box(24, centerY - 48, 180, 96, data.centre);
    body += `<path class="line" d="M204 ${centerY}H236M236 56V${24 + (spokes.length - 1) * (rowH + gap) + rowH / 2}"/>`;
    spokes.forEach((spoke, i) => {
      const y = 24 + i * (rowH + gap),
        cy = y + rowH / 2;
      body += `<g data-relationship="spoke" data-direction="${data.toward}">${arrowH(236, 622, cy, spoke.edge, data.toward === "centre")}</g>`;
      body += box(630, y, 226, rowH, spoke.title, "", { detail: spoke.detail });
    });
    return svgMarkup(body, opts, `0 0 880 ${height}`, "", data);
  };

  C.compareTwo = (params, opts) => {
    var data = params;
    opts = opts || {};
    known(data, "params", [
      "a",
      "b",
      "aDetail",
      "bDetail",
      "highlight",
      "rows",
    ]);
    text(data.a, "a");
    text(data.b, "b");
    text(data.aDetail, "aDetail", true);
    text(data.bDetail, "bDetail", true);
    choice(data.highlight, "highlight", ["a", "b", "none"]);
    const rows = records(data.rows, "rows", 2, 4, [
      "label",
      "a",
      "b",
      "winner",
    ]);
    rows.forEach((r, i) => {
      choice(r.winner, `rows[${i}].winner`, ["a", "b", "none"]);
    });
    if (opts.compact) return compactDiagram("compareTwo", data, opts);
    if (opts.narrow === true) return narrowDiagram("compareTwo", data, opts);
    const x = [24, 216, 536, 856],
      head = 58,
      rowH = 68,
      tableH = head + rowH * rows.length,
      top = (360 - tableH) / 2,
      bottom = top + tableH;
    let body = "";
    if (data.highlight === "a")
      body += `<rect class="band" x="${x[1]}" y="${top}" width="${x[2] - x[1]}" height="${tableH}"/>`;
    if (data.highlight === "b")
      body += `<rect class="band" x="${x[2]}" y="${top}" width="${x[3] - x[2]}" height="${tableH}"/>`;
    body += `<path class="hair" d="M${x[0]} ${top}H${x[3]}M${x[0]} ${top + head}H${x[3]}M${x[0]} ${top}V${bottom}M${x[1]} ${top}V${bottom}M${x[2]} ${top}V${bottom}M${x[3]} ${top}V${bottom}"/>${detailWrap(txt(data.a, (x[1] + x[2]) / 2, top + 34, x[2] - x[1] - 24, data.highlight === "a" ? "zone surface-text" : "zone", 2), data.aDetail, [x[1], top, x[2] - x[1], head])}${detailWrap(txt(data.b, (x[2] + x[3]) / 2, top + 34, x[3] - x[2] - 24, data.highlight === "b" ? "zone surface-text" : "zone", 2), data.bDetail, [x[2], top, x[3] - x[2], head])}`;
    rows.forEach((r, i) => {
      const y = top + head + i * rowH,
        cy = y + rowH / 2;
      body += `<path class="hair" d="M${x[0]} ${y + rowH}H${x[3]}"/>${txt(r.label, (x[0] + x[1]) / 2, cy, x[1] - x[0] - 24, "sub", 2)}${txt(r.a, (x[1] + x[2]) / 2, cy, x[2] - x[1] - 24, `${r.winner === "a" ? "zone" : "sub"}${data.highlight === "a" ? " surface-text" : ""}`, 2)}${txt(r.b, (x[2] + x[3]) / 2, cy, x[3] - x[2] - 24, `${r.winner === "b" ? "zone" : "sub"}${data.highlight === "b" ? " surface-text" : ""}`, 2)}`;
    });
    return svg(body, opts, "wide", data);
  };

  C.funnel = (params, opts) => {
    var data = params;
    opts = opts || {};
    known(data, "params", ["tiers", "edges", "outcome"]);
    const tiers = records(
        data.tiers,
        "tiers",
        2,
        3,
        ["title"],
        ["sub", "detail"],
      ),
      edges = strings(data.edges, "edges", tiers.length - 1);
    text(data.outcome, "outcome");
    if (opts.compact) return compactDiagram("funnel", data, opts);
    if (opts.narrow === true) return narrowDiagram("funnel", data, opts);
    const widths = tiers.length === 3 ? [320, 224, 132] : [300, 168],
      ys = tiers.length === 3 ? [26, 138, 250] : [50, 190],
      h = 76;
    let body = "";
    tiers.forEach((t, i) => {
      const w = widths[i],
        x = 200 - w / 2,
        y = ys[i];
      if (i) {
        const pw = widths[i - 1],
          px = 200 - pw / 2,
          py = ys[i - 1];
        body += `<path class="hair" d="M${px + 6} ${py + h}L${x + 6} ${y}M${px + pw - 6} ${py + h}L${x + w - 6} ${y}"/>${txt(edges[i - 1], 200, (py + h + y) / 2 + 3, w + 60, "edge", 1)}`;
      }
      body += box(x, y, w, h, t.title, t.sub, { detail: t.detail });
    });
    const lastY = ys.at(-1) + h;
    body +=
      arrowV(lastY, lastY + 34, 200, "") +
      txt(data.outcome, 200, lastY + 57, 300, "zone", 2);
    return svg(body, opts, "pane", data);
  };

  C.loop = (params, opts) => {
    var data = params;
    opts = opts || {};
    known(data, "params", ["centre", "steps"]);
    text(data.centre, "centre");
    const steps = records(
      data.steps,
      "steps",
      3,
      4,
      ["title", "edge"],
      ["detail"],
    );
    if (opts.compact) return compactDiagram("loop", data, opts);
    if (opts.narrow === true) return narrowDiagram("loop", data, opts);
    const cx = 200,
      cy = 200,
      r = 130,
      ar = 84,
      bw = 120,
      bh = 50;
    let body = txt(data.centre, cx, cy + 4, 108, "zone", 3);
    steps.forEach((s, i) => {
      const a = ((-90 + (i * 360) / steps.length) * Math.PI) / 180,
        next = ((-90 + ((i + 1) * 360) / steps.length) * Math.PI) / 180,
        a0 = a + 0.34,
        a1 = next - 0.34,
        x0 = cx + ar * Math.cos(a0),
        y0 = cy + ar * Math.sin(a0),
        x1 = cx + ar * Math.cos(a1),
        y1 = cy + ar * Math.sin(a1),
        endA = a1 - 0.09,
        xe = cx + ar * Math.cos(endA),
        ye = cy + ar * Math.sin(endA);
      body += `<path class="line" d="M${x0} ${y0}A${ar} ${ar} 0 0 1 ${xe} ${ye}"/><path class="line" d="M${x1} ${y1}l${-8 * Math.cos(a1 - 0.55)} ${-8 * Math.sin(a1 - 0.55)}M${x1} ${y1}l${-8 * Math.cos(a1 + 0.55)} ${-8 * Math.sin(a1 + 0.55)}"/>${txt(s.edge, cx + (ar + 24) * Math.cos((a0 + a1) / 2), cy + (ar + 24) * Math.sin((a0 + a1) / 2), 80, "edge", 1)}${box(cx + r * Math.cos(a) - bw / 2, cy + r * Math.sin(a) - bh / 2, bw, bh, s.title, "", { detail: s.detail })}`;
    });
    return svg(body, opts, "pane", data);
  };

  C.matrix = (params, opts) => {
    var data = params;
    opts = opts || {};
    known(data, "params", ["xAxis", "yAxis", "quads", "markAt"]);
    text(data.xAxis, "xAxis");
    text(data.yAxis, "yAxis");
    const quads = records(
      data.quads,
      "quads",
      4,
      4,
      ["title"],
      ["sub", "detail"],
    );
    if (!Number.isInteger(data.markAt) || data.markAt < 0 || data.markAt > 3)
      throw new TypeError("markAt must be an index from 0 to 3");
    if (opts.compact) return compactDiagram("matrix", data, opts);
    if (opts.narrow === true) return narrowDiagram("matrix", data, opts);
    const x = 66,
      y = 24,
      size = 304,
      half = 152;
    let body = "";
    quads.forEach((q, i) => {
      const qx = x + (i % 2) * half,
        qy = y + Math.floor(i / 2) * half;
      body += detailWrap(
        `<rect class="${i === data.markAt ? "band" : "box"}" x="${qx}" y="${qy}" width="${half}" height="${half}"/>${txt(q.title, qx + half / 2, qy + half / 2 - (q.sub ? 12 : 0), half - 24, "zone", 2)}${q.sub ? txt(q.sub, qx + half / 2, qy + half / 2 + 24, half - 32, "sub", 3) : ""}`,
        q.detail,
      );
    });
    body += `<path class="line" d="M${x} ${y}V${y + size}H${x + size}"/><path class="hair" d="M${x + half} ${y}V${y + size}M${x} ${y + half}H${x + size}"/>${txt(data.xAxis, x + half, y + size + 48, 260, "zone", 1)}<g transform="translate(12 ${y + half}) rotate(-90)">${txt(data.yAxis, 0, 0, 260, "zone", 1)}</g>`;
    return svg(body, opts, "pane", data);
  };

  C.figurePath = (params, opts) => {
    var data = params;
    opts = opts || {};
    known(data, "params", ["marks", "goal", "caption"]);
    strings(data.marks, "marks", 3);
    text(data.goal, "goal");
    text(data.caption, "caption");
    if (opts.compact) return compactDiagram("figurePath", data, opts);
    if (opts.narrow === true) return narrowDiagram("figurePath", data, opts);
    const spots = [
      [118, 309],
      [202, 241],
      [277, 135],
    ];
    let body = `<path class="line" d="M46 336C118 336 96 268 168 252S246 224 258 168S292 92 352 74"/><path class="line" d="M352 74V34"/><path class="inkfill" d="M352 34V56L386 45Z"/>${txt(data.goal, 348, 18, 96, "zone", 1)}`;
    data.marks.forEach((m, i) => {
      body += `<circle class="inkfill" cx="${spots[i][0]}" cy="${spots[i][1]}" r="5"/>${txt(m, spots[i][0] + 14, spots[i][1] + 18, 100, "edge", 1, "start")}`;
    });
    body += `<g transform="translate(326 82)"><circle class="line" cx="0" cy="-30" r="7.5"/><path class="line" d="M0 -22V-6M0 -16L-10 -9M0 -16L10 -9M0 -6L-8 6M0 -6L8 6"/></g>${txt(data.caption, 200, 374, 350, "sub", 2)}`;
    return svg(body, opts, "pane", data);
  };

  C.stairSteps = (params, opts) => {
    var data = params;
    opts = opts || {};
    known(data, "params", ["steps", "caption"]);
    const steps = records(data.steps, "steps", 3, 6, ["title"], ["sub"]);
    text(data.caption, "caption", true);
    const x0 = 34,
      y0 = 326,
      tread = 332 / steps.length,
      rise = 46;
    let body = "";
    if (opts.compact) return compactDiagram("stairSteps", data, opts);
    if (opts.narrow === true) return narrowDiagram("stairSteps", data, opts);
    steps.forEach((s, i) => {
      const x = x0 + i * tread,
        y = y0 - i * rise;
      body += `<path class="line" d="M${x} ${i ? y + rise : y}V${y}H${x + tread}"/>${txt(s.title, x + tread / 2, y - (s.sub ? 30 : 12), tread - 8, "edge", 2)}${s.sub ? txt(s.sub, x + tread / 2, y - 9, tread - 8, "sub", 1) : ""}`;
    });
    if (data.caption) body += txt(data.caption, 200, 374, 352, "sub", 2);
    return svg(body, opts, "pane", data);
  };

  C.pyramid = (params, opts) => {
    var data = params;
    opts = opts || {};
    known(data, "params", ["blocks", "caption"]);
    const blocks = records(data.blocks, "blocks", 6, 6, ["title"], ["sub"]);
    text(data.caption, "caption", true);
    const cells = [
      { x: 54, y: 286, w: 292, h: 56 },
      { x: 82, y: 226, w: 116, h: 56 },
      { x: 202, y: 226, w: 116, h: 56 },
      { x: 112, y: 166, w: 86, h: 56 },
      { x: 202, y: 166, w: 86, h: 56 },
      { x: 150, y: 58, w: 100, h: 104, tri: true },
    ];
    let body = "";
    if (opts.compact) return compactDiagram("pyramid", data, opts);
    // Preserve the saved level structure at every width. The former narrow
    // variant turned four levels into six, which changed the represented claim.
    cells.forEach((c, i) => {
      const cx = c.x + c.w / 2;
      body += c.tri
        ? `<path class="band" d="M${cx} ${c.y}L${c.x + c.w} ${c.y + c.h}H${c.x}Z"/>`
        : `<rect class="band" x="${c.x}" y="${c.y}" width="${c.w}" height="${c.h}" rx="3"/>`;
      body += txt(
        blocks[i].title,
        cx,
        c.tri ? c.y + 55 : c.y + (blocks[i].sub ? 22 : 32),
        c.w - 10,
        "edge surface-text",
        c.tri ? 2 : 1,
      );
      if (blocks[i].sub)
        body += txt(
          blocks[i].sub,
          cx,
          c.tri ? c.y + 78 : c.y + 42,
          c.w - 10,
          "sub surface-text",
          1,
        );
    });
    if (data.caption) body += txt(data.caption, 200, 374, 352, "sub", 2);
    return svg(body, opts, "pane", data);
  };

  function gearPath(cx, cy, r, teeth, phase = 0) {
    const inner = r - 3.4,
      outer = r + 3.4,
      per = (Math.PI * 2) / teeth,
      points = [];
    for (let i = 0; i < teeth; i++) {
      const a = phase + i * per;
      [
        [inner, -0.5],
        [inner, -0.28],
        [outer, -0.18],
        [outer, 0.18],
        [inner, 0.28],
        [inner, 0.5],
      ].forEach(([rad, f]) => {
        points.push([
          cx + rad * Math.cos(a + per * f),
          cy + rad * Math.sin(a + per * f),
        ]);
      });
    }
    return (
      points
        .map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)} ${p[1].toFixed(1)}`)
        .join("") + "Z"
    );
  }
  C.gears = (params, opts) => {
    var data = params;
    opts = opts || {};
    known(data, "params", ["labels", "caption"]);
    strings(data.labels, "labels", 3);
    text(data.caption, "caption", true);
    const gs = [
      { cx: 150, cy: 186, r: 33, t: 8 },
      { cx: 236, cy: 150, r: 58, t: 14 },
      { cx: 321, cy: 203, r: 41, t: 10 },
    ];
    let body = "";
    if (opts.compact) return compactDiagram("gears", data, opts);
    if (opts.narrow === true) return narrowDiagram("gears", data, opts);
    [1, 0, 2].forEach((i) => {
      const g = gs[i],
        d = gearPath(g.cx, g.cy, g.r, g.t, i * 0.22);
      body += `<path class="${i === 2 ? "inkfill" : "box"}" d="${d}"/><circle class="line" cx="${g.cx}" cy="${g.cy}" r="${g.r * 0.22}"/>`;
    });
    const lp = [
      [150, 268],
      [236, 54],
      [321, 280],
    ];
    data.labels.forEach((v, i) => {
      body += txt(v, lp[i][0], lp[i][1], 112, "edge", 1);
    });
    body += `<circle class="line" cx="92" cy="212" r="11"/><path class="line" d="M93 223Q98 252 101 280M101 280L91 316M101 280L124 316M80 319H103M118 319H136M94 238L138 192"/><circle class="inkfill" cx="138" cy="192" r="4"/>`;
    if (data.caption) body += txt(data.caption, 200, 366, 352, "sub", 2);
    return svg(body, opts, "pane", data);
  };

  /* Charts share a 360 × 200 viewBox and 12px outer padding. Quantitative
     plots use x=54…346 and y=24…144; labels, axis titles, and the required
     source-note line occupy the reserved margins rather than the plot. */
  const CHART = Object.freeze({ left: 54, right: 346, top: 24, base: 144 });

  function number(value, name, min = -Infinity, integer = false) {
    if (
      !Number.isFinite(value) ||
      value < min ||
      (integer && !Number.isInteger(value))
    )
      throw new TypeError(
        `${name} must be ${integer ? "an integer" : "a finite number"}${min !== -Infinity ? ` at least ${min}` : ""}`,
      );
    return value;
  }
  function boolean(value, name) {
    if (value != null && typeof value !== "boolean")
      throw new TypeError(`${name} must be boolean when supplied`);
  }
  function detail(value, name) {
    text(value, name, true);
  }
  function chartParams(data, allowed) {
    known(data, "params", ["title", ...allowed]);
    text(data.title, "title", true);
    text(data.sourceNote, "sourceNote");
    return data;
  }
  function chartItem(value, name, fields, required) {
    known(value, name, fields);
    required.forEach((key) => {
      if (key === "label") text(value[key], `${name}.${key}`);
      else number(value[key], `${name}.${key}`);
    });
    if (fields.includes("open")) boolean(value.open, `${name}.open`);
    if (fields.includes("detail")) detail(value.detail, `${name}.detail`);
    return value;
  }
  function fmt(value) {
    if (Number.isInteger(value)) return String(value);
    return String(Math.round(value * 100) / 100);
  }
  function scale(value, fromMin, fromMax, toMin, toMax) {
    return (
      toMin + ((value - fromMin) / (fromMax - fromMin || 1)) * (toMax - toMin)
    );
  }
  function path(points) {
    return points
      .map(
        (point, i) =>
          `${i ? "L" : "M"}${point[0].toFixed(2)} ${point[1].toFixed(2)}`,
      )
      .join("");
  }
  function openClass(value, line = false) {
    return value && value.open === true ? (line ? " open-line" : " open") : "";
  }
  function chartLabel(
    value,
    x,
    y,
    cls = "",
    anchor = "middle",
    baseline = "auto",
  ) {
    const classes = /(^|\s)value(\s|$)/.test(cls) ? `${cls} data-label` : cls;
    return `<text class="${classes}" x="${Number(x).toFixed(2)}" y="${Number(y).toFixed(2)}" text-anchor="${anchor}" dominant-baseline="${baseline}">${esc(value)}</text>`;
  }
  function categoryLabel(value, x, y, width, anchor = "middle") {
    return txt(value, x, y, width, "muted", 2, anchor);
  }
  function unitTitle(title, unit) {
    return unit == null ? title : `${title} (${unit})`;
  }
  function chartFrame(body, data, opts, baseline = "zero") {
    const heading = data.title
      ? chartLabel(data.title, 12, 13, "chart-title", "start")
      : "";
    const source = chartLabel(data.sourceNote, 12, 195, "source", "start");
    return svgMarkup(
      `${heading}${body}${source}`,
      opts,
      "0 0 360 200",
      "chart-viz",
      data,
    ).replace(
      " class=",
      ` data-kind="chart" data-baseline="${esc(baseline)}" class=`,
    );
  }
  function axisX(title, unit, y = 177) {
    return chartLabel(unitTitle(title, unit), 200, y, "axis-title");
  }
  function axisY(title, unit, x = 11, cy = 84) {
    return `<g transform="translate(${x} ${cy}) rotate(-90)">${chartLabel(unitTitle(title, unit), 0, 0, "axis-title")}</g>`;
  }
  function niceTicks(min, max, count = 5) {
    if (min === max) max = min + 1;
    const rough = Math.abs(max - min) / Math.max(1, count - 1);
    const magnitude = 10 ** Math.floor(Math.log10(rough || 1));
    const normalized = rough / magnitude;
    const step =
      (normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 5 ? 5 : 10) *
      magnitude;
    const first = Math.ceil(min / step) * step;
    const values = [];
    for (let value = first; value <= max + step * 1e-8; value += step) {
      values.push(Math.round(value * 1e10) / 1e10);
      if (values.length === 7) break;
    }
    if (!values.length || Math.abs(values[0] - min) > step * 0.1)
      values.unshift(min);
    if (values.length < 7 && Math.abs(values.at(-1) - max) > step * 0.1)
      values.push(max);
    return values.slice(0, 7);
  }
  function numericAxes(min, max, yTitle, unit, options = {}) {
    const left = options.left == null ? CHART.left : options.left,
      right = options.right == null ? CHART.right : options.right,
      top = options.top == null ? CHART.top : options.top,
      base = options.base == null ? CHART.base : options.base,
      horizontal = options.horizontal === true;
    let body = "";
    niceTicks(min, max, options.tickCount || 5).forEach((tick) => {
      if (horizontal) {
        const x = scale(tick, min, max, left, right);
        body += `<path class="faint" d="M${x.toFixed(2)} ${top}V${base}"/>${chartLabel(fmt(tick), x, base + 13, "muted")}`;
      } else {
        const y = scale(tick, min, max, base, top);
        body += `<path class="faint" d="M${left} ${y.toFixed(2)}H${right}"/>${chartLabel(fmt(tick), left - 6, y + 3.5, "muted", "end")}`;
      }
    });
    body += horizontal
      ? `<path class="hair" d="M${left} ${base}H${right}"/>`
      : `<path class="hair" d="M${left} ${top}V${base}H${right}"/>`;
    if (yTitle) body += axisY(yTitle, unit);
    return body;
  }
  function unitRungs(x, y, width, height, value, horizontal = false) {
    if (!Number.isInteger(value) || value <= 1) return "";
    let body = "";
    for (let i = 1; i < value; i++) {
      if (horizontal) {
        const xx = x + (width * i) / value;
        body += `<path class="hair" d="M${xx.toFixed(2)} ${y}V${(y + height).toFixed(2)}"/>`;
      } else {
        const yy = y + height - (height * i) / value;
        body += `<path class="hair" d="M${x} ${yy.toFixed(2)}H${(x + width).toFixed(2)}"/>`;
      }
    }
    return body;
  }
  function pointData(
    data,
    min,
    max,
    fields = ["x", "y", "label", "open", "detail"],
  ) {
    return list(data.points, "points", min, max).map((value, i) => {
      chartItem(value, `points[${i}]`, fields, ["x", "y"]);
      if (value.label != null) text(value.label, `points[${i}].label`, true);
      return value;
    });
  }
  function labeledData(data, key, min, max, numberKeys, fields) {
    return list(data[key], key, min, max).map((value, i) => {
      chartItem(value, `${key}[${i}]`, fields, ["label", ...numberKeys]);
      numberKeys.forEach((name) => {
        number(value[name], `${key}[${i}].${name}`, 0);
      });
      return value;
    });
  }
  function wrapDetail(markup, item) {
    return detailWrap(markup, item && item.detail);
  }
  function labelBoxes(points) {
    const occupied = [];
    return points.map((point, index) => {
      const value = point.label || fmt(point.y),
        width = Math.max(24, value.length * 6.2),
        height = 13,
        candidates = [
          [8, -8, "start"],
          [-8, -8, "end"],
          [8, 14, "start"],
          [-8, 14, "end"],
          [0, -13, "middle"],
          [0, 18, "middle"],
        ];
      let chosen = candidates[index % candidates.length];
      for (const candidate of candidates) {
        const left =
            point.px +
            candidate[0] -
            (candidate[2] === "end"
              ? width
              : candidate[2] === "middle"
                ? width / 2
                : 0),
          top = point.py + candidate[1] - height;
        const box = { left, top, right: left + width, bottom: top + height };
        if (
          left >= CHART.left &&
          box.right <= CHART.right &&
          top >= CHART.top - 10 &&
          box.bottom <= CHART.base &&
          !occupied.some(
            (other) =>
              box.left < other.right + 2 &&
              box.right + 2 > other.left &&
              box.top < other.bottom + 2 &&
              box.bottom + 2 > other.top,
          )
        ) {
          occupied.push(box);
          chosen = candidate;
          break;
        }
      }
      return chartLabel(
        value,
        point.px + chosen[0],
        point.py + chosen[1],
        "value",
        chosen[2],
      );
    });
  }

  C.rungBars = (params, opts) => {
    const data = chartParams(params, [
        "items",
        "unit",
        "yAxisTitle",
        "sourceNote",
      ]),
      items = labeledData(
        data,
        "items",
        2,
        8,
        ["value"],
        ["label", "value", "open", "detail"],
      );
    opts = opts || {};
    text(data.unit, "unit");
    text(data.yAxisTitle, "yAxisTitle");
    const max = Math.max(1, ...items.map((item) => item.value)),
      slot = (CHART.right - CHART.left) / items.length,
      width = Math.min(34, slot - 6);
    let body = numericAxes(0, max, data.yAxisTitle, data.unit);
    items.forEach((item, i) => {
      const height = scale(item.value, 0, max, 0, CHART.base - CHART.top),
        x = CHART.left + i * slot + (slot - width) / 2,
        y = CHART.base - height;
      body += wrapDetail(
        `<rect class="fill${openClass(item)}" x="${x.toFixed(2)}" y="${y.toFixed(2)}" width="${width.toFixed(2)}" height="${height.toFixed(2)}"/>${unitRungs(x, y, width, height, item.value)}${chartLabel(fmt(item.value), x + width / 2, Math.max(20, y - 5), "value")}${categoryLabel(item.label, x + width / 2, 158, slot - 2)}`,
        item,
      );
    });
    return chartFrame(body, data, opts, "zero");
  };

  C.hairlineLine = (params, opts) => {
    const data = chartParams(params, [
        "points",
        "xLabels",
        "xAxisTitle",
        "yAxisTitle",
        "unit",
        "baselineZero",
        "sourceNote",
      ]),
      points = pointData(data, 3, 30);
    opts = opts || {};
    strings(data.xLabels, "xLabels", points.length);
    ["xAxisTitle", "yAxisTitle", "unit"].forEach((key) => {
      text(data[key], key);
    });
    choice(data.baselineZero, "baselineZero", ["yes", "no"], true);
    const xmin = Math.min(...points.map((point) => point.x)),
      xmax = Math.max(...points.map((point) => point.x)),
      observedMin = Math.min(...points.map((point) => point.y)),
      ymin =
        data.baselineZero === "no" ? observedMin : Math.min(0, observedMin),
      ymax = Math.max(...points.map((point) => point.y), ymin + 1),
      xy = points.map((point) => ({
        ...point,
        px: scale(point.x, xmin, xmax, CHART.left, CHART.right),
        py: scale(point.y, ymin, ymax, CHART.base, CHART.top),
      }));
    let body = numericAxes(ymin, ymax, data.yAxisTitle, data.unit);
    body += `<path class="line" d="${path(xy.map((point) => [point.px, point.py]))}"/>`;
    xy.forEach((point) => {
      body += wrapDetail(
        `<circle class="tone-2${openClass(point)}" cx="${point.px.toFixed(2)}" cy="${point.py.toFixed(2)}" r="3"/>`,
        point,
      );
    });
    if (points.length <= 12) body += labelBoxes(xy).join("");
    const stride = Math.max(1, Math.ceil(points.length / 7));
    data.xLabels.forEach((value, i) => {
      if (i % stride === 0 || i === points.length - 1)
        body += chartLabel(value, xy[i].px, 157, "muted");
    });
    body += axisX(data.xAxisTitle);
    return chartFrame(
      body,
      data,
      opts,
      data.baselineZero === "no" ? "observed-min" : "zero",
    );
  };

  C.hairlineArea = (params, opts) => {
    const data = chartParams(params, [
        "points",
        "xLabels",
        "xAxisTitle",
        "yAxisTitle",
        "unit",
        "sourceNote",
      ]),
      points = pointData(data, 5, 60, ["x", "y", "label", "open"]);
    opts = opts || {};
    strings(data.xLabels, "xLabels", 2, 12);
    ["xAxisTitle", "yAxisTitle", "unit"].forEach((key) => {
      text(data[key], key);
    });
    const xmin = Math.min(...points.map((point) => point.x)),
      xmax = Math.max(...points.map((point) => point.x)),
      ymax = Math.max(1, ...points.map((point) => point.y)),
      xy = points.map((point) => ({
        ...point,
        px: scale(point.x, xmin, xmax, CHART.left, CHART.right),
        py: scale(point.y, 0, ymax, CHART.base, CHART.top),
      }));
    let body = numericAxes(0, ymax, data.yAxisTitle, data.unit),
      area = `${path(xy.map((point) => [point.px, point.py]))}L${CHART.right} ${CHART.base}L${CHART.left} ${CHART.base}Z`;
    body += `<path class="tone-1" d="${area}"/><path class="line" d="${path(xy.map((point) => [point.px, point.py]))}"/>`;
    xy.forEach((point) => {
      body += `<circle class="${point.open ? "open" : "tone-2"}" cx="${point.px.toFixed(2)}" cy="${point.py.toFixed(2)}" r="2.5"/>`;
    });
    body += labelBoxes(xy).join("");
    data.xLabels.forEach((value, i) => {
      body += chartLabel(
        value,
        scale(i, 0, data.xLabels.length - 1, CHART.left, CHART.right),
        157,
        "muted",
      );
    });
    body += axisX(data.xAxisTitle);
    return chartFrame(body, data, opts, "zero");
  };

  C.tickDonut = (params, opts) => {
    const data = chartParams(params, ["parts", "unit", "total", "sourceNote"]);
    opts = opts || {};
    text(data.unit, "unit");
    text(data.total, "total", true);
    const parts = list(data.parts, "parts", 2, 6).map((value, i) => {
        chartItem(
          value,
          `parts[${i}]`,
          ["label", "value", "open", "detail"],
          ["label", "value"],
        );
        number(value.value, `parts[${i}].value`, 0, true);
        return value;
      }),
      total = parts.reduce((sum, part) => sum + part.value, 0);
    if (!total || total > 120)
      throw new TypeError("parts must total from 1 to 120 ticks");
    const cx = 180,
      cy = 83,
      inner = 42,
      outer = 53;
    let body = "",
      cursor = 0;
    parts.forEach((part) => {
      let marks = "";
      const start = cursor;
      for (let i = 0; i < part.value; i++, cursor++) {
        const angle = ((cursor + 0.5) / total) * Math.PI * 2 - Math.PI / 2,
          x1 = cx + Math.cos(angle) * inner,
          y1 = cy + Math.sin(angle) * inner,
          x2 = cx + Math.cos(angle) * outer,
          y2 = cy + Math.sin(angle) * outer;
        marks += `<path class="line${openClass(part, true)}" d="M${x1.toFixed(2)} ${y1.toFixed(2)}L${x2.toFixed(2)} ${y2.toFixed(2)}"/>`;
      }
      const mid =
          ((start + part.value / 2) / total) * Math.PI * 2 - Math.PI / 2,
        lx = cx + Math.cos(mid) * 72,
        ly = cy + Math.sin(mid) * 62,
        anchor =
          Math.cos(mid) > 0.2
            ? "start"
            : Math.cos(mid) < -0.2
              ? "end"
              : "middle";
      marks += `${chartLabel(part.label, lx, ly, "muted", anchor)}${chartLabel(part.value, lx, ly + 12, "value", anchor)}`;
      body += wrapDetail(marks, part);
    });
    body += `${chartLabel(data.total || total, cx, cy - 1, "value")}${chartLabel(data.unit, cx, cy + 14, "muted")}`;
    return chartFrame(body, data, opts, "not-applicable");
  };

  C.tickRows = (params, opts) => {
    const data = chartParams(params, [
        "items",
        "unit",
        "xAxisTitle",
        "sourceNote",
      ]),
      items = labeledData(
        data,
        "items",
        2,
        8,
        ["value"],
        ["label", "value", "open", "detail"],
      );
    opts = opts || {};
    text(data.unit, "unit");
    text(data.xAxisTitle, "xAxisTitle");
    items.forEach((item, i) => {
      number(item.value, `items[${i}].value`, 0, true);
    });
    if (items.some((item) => item.value > 40))
      throw new TypeError("items[].value must be at most 40 ticks");
    const max = Math.max(1, ...items.map((item) => item.value)),
      row = 116 / items.length,
      tickGap = Math.min(7, 210 / max);
    let body = `<path class="hair" d="M112 ${CHART.top}V${CHART.base}"/>`;
    items.forEach((item, ri) => {
      const y = CHART.top + row * (ri + 0.5);
      let marks = categoryLabel(item.label, 104, y + 4, 88, "end");
      for (let i = 0; i < item.value; i++) {
        const x = 118 + i * tickGap;
        marks += `<path class="line${openClass(item, true)}" d="M${x.toFixed(2)} ${(y - 5).toFixed(2)}V${(y + 6).toFixed(2)}"/>`;
      }
      marks += chartLabel(fmt(item.value), 346, y + 4, "value", "end");
      body += wrapDetail(marks, item);
    });
    body += axisX(data.xAxisTitle, data.unit, 174);
    return chartFrame(body, data, opts, "zero");
  };

  C.pairedRungs = (params, opts) => {
    const data = chartParams(params, [
      "aLabel",
      "bLabel",
      "items",
      "unit",
      "xAxisTitle",
      "sourceNote",
    ]);
    opts = opts || {};
    ["aLabel", "bLabel", "unit", "xAxisTitle"].forEach((key) => {
      text(data[key], key);
    });
    const items = labeledData(
        data,
        "items",
        2,
        6,
        ["a", "b"],
        ["label", "a", "b", "open", "detail"],
      ),
      max = Math.max(1, ...items.flatMap((item) => [item.a, item.b])),
      row = 106 / items.length,
      x0 = 96,
      width = 238;
    let body = `${chartLabel(data.aLabel, 220, 14, "axis-title", "end")}${chartLabel(data.bLabel, 334, 14, "axis-title", "end")}`;
    body += numericAxes(0, max, "", data.unit, {
      left: x0,
      right: x0 + width,
      top: CHART.top,
      base: CHART.base,
      horizontal: true,
    });
    items.forEach((item, i) => {
      const y = CHART.top + 3 + i * row,
        aw = scale(item.a, 0, max, 0, width),
        bw = scale(item.b, 0, max, 0, width),
        h = Math.max(5, Math.min(8, row / 2 - 2));
      body += wrapDetail(
        `${categoryLabel(item.label, x0 - 7, y + h + 2, 82, "end")}<rect class="tone-3${openClass(item)}" x="${x0}" y="${y.toFixed(2)}" width="${aw.toFixed(2)}" height="${h.toFixed(2)}"/>${unitRungs(x0, y, aw, h, item.a, true)}${chartLabel(fmt(item.a), x0 + aw + 4, y + h, "value", "start")}<rect class="tone-1${openClass(item)}" x="${x0}" y="${(y + h + 3).toFixed(2)}" width="${bw.toFixed(2)}" height="${h.toFixed(2)}"/>${unitRungs(x0, y + h + 3, bw, h, item.b, true)}${chartLabel(fmt(item.b), x0 + bw + 4, y + h * 2 + 3, "value", "start")}`,
        item,
      );
    });
    body += axisX(data.xAxisTitle, data.unit);
    return chartFrame(body, data, opts, "zero");
  };

  C.stackedRungs = (params, opts) => {
    const data = chartParams(params, [
      "partLabels",
      "items",
      "unit",
      "xAxisTitle",
      "sourceNote",
    ]);
    opts = opts || {};
    strings(data.partLabels, "partLabels", 2, 4);
    text(data.unit, "unit");
    text(data.xAxisTitle, "xAxisTitle");
    const items = list(data.items, "items", 2, 6).map((value, i) => {
        chartItem(
          value,
          `items[${i}]`,
          ["label", "parts", "open", "detail"],
          ["label"],
        );
        list(
          value.parts,
          `items[${i}].parts`,
          data.partLabels.length,
          data.partLabels.length,
        );
        value.parts.forEach((part, j) => {
          number(part, `items[${i}].parts[${j}]`, 0);
        });
        return value;
      }),
      totals = items.map((item) =>
        item.parts.reduce((sum, value) => sum + value, 0),
      ),
      max = Math.max(1, ...totals),
      row = 108 / items.length,
      x0 = 91,
      plotW = 239,
      showSegments = items.length * data.partLabels.length <= 12;
    let body = data.partLabels
      .map((label, i) =>
        chartLabel(
          label,
          x0 + (i + 0.5) * (plotW / data.partLabels.length),
          14,
          `axis-title tone-name-${i + 1}`,
        ),
      )
      .join("");
    body += numericAxes(0, max, "", data.unit, {
      left: x0,
      right: x0 + plotW,
      top: CHART.top,
      base: CHART.base,
      horizontal: true,
    });
    items.forEach((item, ri) => {
      const y = CHART.top + ri * row + 4,
        height = Math.min(16, row - 5);
      let x = x0,
        marks = categoryLabel(
          item.label,
          x0 - 7,
          y + height / 2 + 4,
          77,
          "end",
        );
      item.parts.forEach((value, pi) => {
        const width = scale(value, 0, max, 0, plotW);
        marks += `<rect class="tone-${pi + 1}${openClass(item)}" x="${x.toFixed(2)}" y="${y.toFixed(2)}" width="${width.toFixed(2)}" height="${height.toFixed(2)}"/>${unitRungs(x, y, width, height, value, true)}`;
        if (showSegments && width >= 18) {
          const label = fmt(value),
            padW = label.length * 7 + 4;
          marks += `<rect class="tone-${pi + 1} label-pad${openClass(item)}" x="${(x + width / 2 - padW / 2).toFixed(2)}" y="${(y + height / 2 - 6).toFixed(2)}" width="${padW}" height="12"/>`;
          marks += chartLabel(
            label,
            x + width / 2,
            y + height / 2 + 4,
            "value",
          );
        }
        x += width;
      });
      marks += chartLabel(
        fmt(totals[ri]),
        x + 4,
        y + height / 2 + 4,
        "value",
        "start",
      );
      body += wrapDetail(marks, item);
    });
    body += axisX(data.xAxisTitle, data.unit);
    return chartFrame(body, data, opts, "zero");
  };

  C.plumbScatter = (params, opts) => {
    const data = chartParams(params, [
        "points",
        "xAxisTitle",
        "yAxisTitle",
        "xUnit",
        "yUnit",
        "sourceNote",
      ]),
      points = pointData(data, 3, 20);
    opts = opts || {};
    ["xAxisTitle", "yAxisTitle", "xUnit", "yUnit"].forEach((key) => {
      text(data[key], key);
    });
    points.forEach((point, i) => {
      text(point.label, `points[${i}].label`);
    });
    const xmin = Math.min(0, ...points.map((point) => point.x)),
      xmax = Math.max(1, ...points.map((point) => point.x)),
      ymin = Math.min(0, ...points.map((point) => point.y)),
      ymax = Math.max(1, ...points.map((point) => point.y)),
      xy = points.map((point) => ({
        ...point,
        px: scale(point.x, xmin, xmax, CHART.left, CHART.right),
        py: scale(point.y, ymin, ymax, CHART.base, CHART.top),
      }));
    let body = numericAxes(ymin, ymax, data.yAxisTitle, data.yUnit);
    niceTicks(xmin, xmax, 5).forEach((tick) => {
      const x = scale(tick, xmin, xmax, CHART.left, CHART.right);
      body += `${chartLabel(fmt(tick), x, 157, "muted")}<path class="faint" d="M${x.toFixed(2)} ${CHART.top}V${CHART.base}"/>`;
    });
    xy.forEach((point) => {
      body += wrapDetail(
        `<path class="quiet${openClass(point, true)}" d="M${point.px.toFixed(2)} ${CHART.base}V${point.py.toFixed(2)}"/><circle class="tone-3${openClass(point)}" cx="${point.px.toFixed(2)}" cy="${point.py.toFixed(2)}" r="3.5"/>`,
        point,
      );
    });
    body += labelBoxes(xy).join("") + axisX(data.xAxisTitle, data.xUnit);
    return chartFrame(body, data, opts, "zero");
  };

  C.rungWaterfall = (params, opts) => {
    const data = chartParams(params, [
      "start",
      "startLabel",
      "steps",
      "endLabel",
      "unit",
      "yAxisTitle",
      "sourceNote",
    ]);
    opts = opts || {};
    number(data.start, "start");
    ["startLabel", "endLabel", "unit", "yAxisTitle"].forEach((key) => {
      text(data[key], key);
    });
    const steps = list(data.steps, "steps", 2, 6).map((value, i) =>
        chartItem(
          value,
          `steps[${i}]`,
          ["label", "delta", "open", "detail"],
          ["label", "delta"],
        ),
      ),
      cumulative = [data.start];
    steps.forEach((step) => {
      cumulative.push(cumulative.at(-1) + step.delta);
    });
    const ymin = Math.min(0, ...cumulative),
      ymax = Math.max(1, ...cumulative),
      count = steps.length + 2,
      slot = (CHART.right - CHART.left) / count,
      width = Math.min(28, slot - 5),
      ypos = (value) => scale(value, ymin, ymax, CHART.base, CHART.top);
    let body = numericAxes(ymin, ymax, data.yAxisTitle, data.unit);
    const fullBar = (value, label, index, tone) => {
      const x = CHART.left + index * slot + (slot - width) / 2,
        y0 = ypos(0),
        y1 = ypos(value),
        y = Math.min(y0, y1),
        height = Math.max(1, Math.abs(y1 - y0));
      return `<rect class="${tone}" x="${x.toFixed(2)}" y="${y.toFixed(2)}" width="${width.toFixed(2)}" height="${height.toFixed(2)}"/>${chartLabel(fmt(value), x + width / 2, Math.max(20, y - 5), "value")}${categoryLabel(label, x + width / 2, 158, slot - 2)}`;
    };
    body += fullBar(data.start, data.startLabel, 0, "tone-3");
    steps.forEach((step, i) => {
      const before = cumulative[i],
        after = cumulative[i + 1],
        x = CHART.left + (i + 1) * slot + (slot - width) / 2,
        yBefore = ypos(before),
        yAfter = ypos(after),
        y = Math.min(yBefore, yAfter),
        height = Math.max(1, Math.abs(yAfter - yBefore));
      body += wrapDetail(
        `<rect class="tone-1${openClass(step)}" x="${x.toFixed(2)}" y="${y.toFixed(2)}" width="${width.toFixed(2)}" height="${height.toFixed(2)}"/>${unitRungs(x, y, width, height, Math.abs(step.delta))}${chartLabel(`${step.delta >= 0 ? "+" : ""}${fmt(step.delta)}`, x + width / 2, step.delta >= 0 ? Math.max(20, y - 5) : Math.min(141, y + height + 12), "value")}${categoryLabel(step.label, x + width / 2, 158, slot - 2)}`,
        step,
      );
      if (i < steps.length - 1)
        body += `<path class="faint" d="M${(x + width).toFixed(2)} ${yAfter.toFixed(2)}H${(x + slot).toFixed(2)}"/>`;
    });
    body += fullBar(cumulative.at(-1), data.endLabel, count - 1, "tone-3");
    return chartFrame(body, data, opts, "zero");
  };

  C.dotHeat = (params, opts) => {
    const data = chartParams(params, [
      "rows",
      "cols",
      "values",
      "rowAxisTitle",
      "colAxisTitle",
      "unit",
      "sourceNote",
    ]);
    opts = opts || {};
    strings(data.rows, "rows", 2, 8);
    strings(data.cols, "cols", 2, 12);
    ["rowAxisTitle", "colAxisTitle", "unit"].forEach((key) => {
      text(data[key], key);
    });
    list(data.values, "values", data.rows.length, data.rows.length);
    data.values.forEach((row, ri) => {
      list(row, `values[${ri}]`, data.cols.length, data.cols.length);
      row.forEach((value, ci) => {
        number(value, `values[${ri}][${ci}]`, 0);
      });
    });
    const max = Math.max(1, ...data.values.flat()),
      left = 92,
      top = 29,
      width = 252,
      height = 111,
      cellW = width / data.cols.length,
      cellH = height / data.rows.length;
    let body = chartLabel(
      `Dot area · ${data.unit}`,
      344,
      14,
      "axis-title",
      "end",
    );
    data.cols.forEach((value, i) => {
      body += categoryLabel(value, left + (i + 0.5) * cellW, 24, cellW - 2);
    });
    data.rows.forEach((rowLabel, ri) => {
      body += categoryLabel(
        rowLabel,
        left - 7,
        top + (ri + 0.5) * cellH + 4,
        76,
        "end",
      );
      data.values[ri].forEach((value, ci) => {
        const radius =
            Math.sqrt(value / max) * Math.max(1, Math.min(8, cellH / 2 - 2)),
          x = left + (ci + 0.5) * cellW,
          y = top + (ri + 0.5) * cellH;
        body += `<circle class="tone-2" cx="${x.toFixed(2)}" cy="${y.toFixed(2)}" r="${radius.toFixed(2)}"/>${chartLabel(value, x, y + 3.5, "value")}`;
      });
    });
    body += `<g transform="translate(11 84) rotate(-90)">${chartLabel(data.rowAxisTitle, 0, 0, "axis-title")}</g>${chartLabel(data.colAxisTitle, 218, 158, "axis-title")}`;
    return chartFrame(body, data, opts, "not-applicable");
  };

  C.tickGauge = (params, opts) => {
    const data = chartParams(params, [
      "value",
      "max",
      "label",
      "unit",
      "open",
      "sourceNote",
    ]);
    opts = opts || {};
    number(data.value, "value", 0, true);
    number(data.max, "max", 1, true);
    if (data.max > 100) throw new TypeError("max must be at most 100 ticks");
    if (data.value > data.max) throw new TypeError("value must not exceed max");
    ["label", "unit"].forEach((key) => {
      text(data[key], key);
    });
    choice(data.open, "open", ["yes", "no"], true);
    const cx = 180,
      cy = 116,
      inner = 56,
      outer = 72;
    let body = "";
    for (let i = 0; i < data.max; i++) {
      const angle = Math.PI + ((i + 0.5) / data.max) * Math.PI,
        x1 = cx + Math.cos(angle) * inner,
        y1 = cy + Math.sin(angle) * inner,
        x2 = cx + Math.cos(angle) * outer,
        y2 = cy + Math.sin(angle) * outer,
        active = i < data.value,
        open = active && data.open === "yes";
      body += `<path class="${active ? "line" : "faint"}${open ? " open-line" : ""}" d="M${x1.toFixed(2)} ${y1.toFixed(2)}L${x2.toFixed(2)} ${y2.toFixed(2)}"/>`;
    }
    body += `${chartLabel(fmt(data.value), cx, 103, "value")}${chartLabel(`0`, cx - outer, 136, "muted")}${chartLabel(fmt(data.max), cx + outer, 136, "value")}${chartLabel(unitTitle(data.label, data.unit), cx, 160, "axis-title")}`;
    return chartFrame(body, data, opts, "zero");
  };

  C.dumbbell = (params, opts) => {
    const data = chartParams(params, [
      "beforeLabel",
      "afterLabel",
      "items",
      "unit",
      "xAxisTitle",
      "sourceNote",
    ]);
    opts = opts || {};
    ["beforeLabel", "afterLabel", "unit", "xAxisTitle"].forEach((key) => {
      text(data[key], key);
    });
    const items = labeledData(
        data,
        "items",
        2,
        6,
        ["before", "after"],
        ["label", "before", "after", "open", "detail"],
      ),
      max = Math.max(1, ...items.flatMap((item) => [item.before, item.after])),
      left = 103,
      right = 336,
      row = 105 / items.length;
    let body = `${chartLabel(data.beforeLabel, 220, 14, "axis-title", "end")}${chartLabel(data.afterLabel, 336, 14, "axis-title", "end")}`;
    body += numericAxes(0, max, "", data.unit, {
      left,
      right,
      top: CHART.top,
      base: CHART.base,
      horizontal: true,
    });
    items.forEach((item, i) => {
      const y = CHART.top + row * (i + 0.5),
        before = scale(item.before, 0, max, left, right),
        after = scale(item.after, 0, max, left, right);
      body += wrapDetail(
        `${categoryLabel(item.label, left - 8, y + 4, 88, "end")}<path class="quiet${openClass(item, true)}" d="M${before.toFixed(2)} ${y.toFixed(2)}H${after.toFixed(2)}"/><circle class="fill${openClass(item)}" cx="${before.toFixed(2)}" cy="${y.toFixed(2)}" r="4"/><circle class="tone-4${openClass(item)}" cx="${after.toFixed(2)}" cy="${y.toFixed(2)}" r="4"/>${chartLabel(fmt(item.before), before, y - 7, "value")}${chartLabel(fmt(item.after), after, y + 14, "value")}`,
        item,
      );
    });
    body += axisX(data.xAxisTitle, data.unit);
    return chartFrame(body, data, opts, "zero");
  };

  function treemapNodes(values, name, depth = 0) {
    return list(values, name, 2, depth ? 6 : 8).map((value, i) => {
      chartItem(
        value,
        `${name}[${i}]`,
        ["label", "value", "children", "open", "detail"],
        ["label", "value"],
      );
      number(value.value, `${name}[${i}].value`, 0);
      if (value.children != null) {
        if (depth)
          throw new TypeError(
            `${name}[${i}].children may only be one level deep`,
          );
        treemapNodes(value.children, `${name}[${i}].children`, depth + 1);
      }
      return value;
    });
  }
  function treemapRects(items, x, y, width, height, depth = 0) {
    const total = items.reduce((sum, item) => sum + item.value, 0);
    if (!total) throw new TypeError("treemap levels must total more than zero");
    let cursor = depth % 2 ? y : x,
      body = "";
    items.forEach((item, i) => {
      const ratio = item.value / total,
        w = depth % 2 ? width : width * ratio,
        h = depth % 2 ? height * ratio : height,
        rx = depth % 2 ? x : cursor,
        ry = depth % 2 ? cursor : y,
        header = item.children ? Math.min(20, h * 0.3) : 0;
      cursor += depth % 2 ? h : w;
      body += wrapDetail(
        `<rect class="tone-${(i % 4) + 1}${openClass(item)}" x="${rx.toFixed(2)}" y="${ry.toFixed(2)}" width="${w.toFixed(2)}" height="${h.toFixed(2)}"/>${categoryLabel(`${item.label} ${fmt(item.value)}`, rx + 5, ry + 14, Math.max(18, w - 10), "start")}`,
        item,
      );
      if (item.children)
        body += treemapRects(
          item.children,
          rx + 3,
          ry + header,
          Math.max(1, w - 6),
          Math.max(1, h - header - 3),
          depth + 1,
        );
    });
    return body;
  }
  C.treemap = (params, opts) => {
    const data = chartParams(params, ["items", "unit", "total", "sourceNote"]);
    opts = opts || {};
    text(data.unit, "unit");
    text(data.total, "total", true);
    const items = treemapNodes(data.items, "items"),
      sum = items.reduce((total, item) => total + item.value, 0);
    const body = `${chartLabel(data.total || `${fmt(sum)} ${data.unit}`, 348, 14, "value", "end")}${treemapRects(items, 14, 24, 332, 145)}`;
    return chartFrame(body, data, opts, "not-applicable");
  };

  C.rungHistogram = (params, opts) => {
    const data = chartParams(params, [
        "bins",
        "xAxisTitle",
        "unit",
        "sourceNote",
      ]),
      bins = labeledData(
        data,
        "bins",
        3,
        12,
        ["count"],
        ["label", "count", "open", "detail"],
      );
    opts = opts || {};
    text(data.xAxisTitle, "xAxisTitle");
    text(data.unit, "unit");
    bins.forEach((bin, i) => {
      number(bin.count, `bins[${i}].count`, 0, true);
    });
    const max = Math.max(1, ...bins.map((bin) => bin.count)),
      slot = (CHART.right - CHART.left) / bins.length,
      width = slot - 1;
    let body = numericAxes(0, max, "Count", data.unit);
    bins.forEach((bin, i) => {
      const height = scale(bin.count, 0, max, 0, CHART.base - CHART.top),
        x = CHART.left + i * slot,
        y = CHART.base - height;
      body += wrapDetail(
        `<rect class="tone-2${openClass(bin)}" x="${x.toFixed(2)}" y="${y.toFixed(2)}" width="${width.toFixed(2)}" height="${height.toFixed(2)}"/>${unitRungs(x, y, width, height, bin.count)}${chartLabel(bin.count, x + width / 2, Math.max(20, y - 5), "value")}${categoryLabel(bin.label, x + width / 2, 158, slot - 1)}`,
        bin,
      );
    });
    body += axisX(data.xAxisTitle, data.unit);
    return chartFrame(body, data, opts, "zero");
  };

  C.tickBox = (params, opts) => {
    const data = chartParams(params, [
      "groups",
      "xAxisTitle",
      "unit",
      "sourceNote",
    ]);
    opts = opts || {};
    text(data.xAxisTitle, "xAxisTitle");
    text(data.unit, "unit");
    const groups = list(data.groups, "groups", 1, 6).map((value, i) => {
        chartItem(
          value,
          `groups[${i}]`,
          [
            "label",
            "min",
            "q1",
            "median",
            "q3",
            "max",
            "outliers",
            "open",
            "detail",
          ],
          ["label", "min", "q1", "median", "q3", "max"],
        );
        if (
          !(
            value.min <= value.q1 &&
            value.q1 <= value.median &&
            value.median <= value.q3 &&
            value.q3 <= value.max
          )
        )
          throw new TypeError(
            `groups[${i}] five-number values must be ordered`,
          );
        if (value.outliers != null) {
          list(value.outliers, `groups[${i}].outliers`, 0, 20);
          value.outliers.forEach((outlier, j) => {
            number(outlier, `groups[${i}].outliers[${j}]`);
          });
        }
        return value;
      }),
      observed = groups.flatMap((group) => [
        group.min,
        group.max,
        ...(group.outliers || []),
      ]),
      min = Math.min(0, ...observed),
      max = Math.max(1, ...observed),
      left = 91,
      right = 340,
      row = 108 / groups.length;
    let body = numericAxes(min, max, "", data.unit, {
      left,
      right,
      top: CHART.top,
      base: CHART.base,
      horizontal: true,
    });
    groups.forEach((group, i) => {
      const y = CHART.top + row * (i + 0.5),
        pos = (value) => scale(value, min, max, left, right),
        boxH = Math.min(16, row - 5),
        q1 = pos(group.q1),
        q3 = pos(group.q3),
        lineCls = `line${openClass(group, true)}`;
      let marks = `${categoryLabel(group.label, left - 7, y + 4, 76, "end")}<path class="${lineCls}" d="M${pos(group.min).toFixed(2)} ${y.toFixed(2)}H${pos(group.max).toFixed(2)}M${pos(group.min).toFixed(2)} ${(y - 5).toFixed(2)}V${(y + 5).toFixed(2)}M${pos(group.max).toFixed(2)} ${(y - 5).toFixed(2)}V${(y + 5).toFixed(2)}"/><rect class="fill${openClass(group)}" x="${q1.toFixed(2)}" y="${(y - boxH / 2).toFixed(2)}" width="${Math.max(1, q3 - q1).toFixed(2)}" height="${boxH.toFixed(2)}"/><path class="${lineCls}" d="M${pos(group.median).toFixed(2)} ${(y - boxH / 2).toFixed(2)}V${(y + boxH / 2).toFixed(2)}"/>${chartLabel(fmt(group.min), pos(group.min), y - 10, "value")}${chartLabel(fmt(group.q1), pos(group.q1), y + 17, "value")}${chartLabel(fmt(group.median), pos(group.median), y - 10, "value")}${chartLabel(fmt(group.q3), pos(group.q3), y + 17, "value")}${chartLabel(fmt(group.max), pos(group.max), y - 10, "value")}`;
      (group.outliers || []).forEach((outlier) => {
        marks += `<circle class="tone-4${openClass(group)}" cx="${pos(outlier).toFixed(2)}" cy="${y.toFixed(2)}" r="2.5"/>${chartLabel(fmt(outlier), pos(outlier), y + 17, "value")}`;
      });
      body += wrapDetail(marks, group);
    });
    body += axisX(data.xAxisTitle, data.unit);
    return chartFrame(body, data, opts, "zero");
  };

  C.streamRibbon = (params, opts) => {
    const data = chartParams(params, [
      "seriesLabels",
      "xLabels",
      "values",
      "xAxisTitle",
      "yAxisTitle",
      "unit",
      "sourceNote",
    ]);
    opts = opts || {};
    strings(data.seriesLabels, "seriesLabels", 2, 5);
    strings(data.xLabels, "xLabels", 3, 12);
    ["xAxisTitle", "yAxisTitle", "unit"].forEach((key) => {
      text(data[key], key);
    });
    list(
      data.values,
      "values",
      data.seriesLabels.length,
      data.seriesLabels.length,
    );
    data.values.forEach((series, si) => {
      list(series, `values[${si}]`, data.xLabels.length, data.xLabels.length);
      series.forEach((value, xi) => {
        number(value, `values[${si}][${xi}]`, 0);
      });
    });
    const totals = data.xLabels.map((_, xi) =>
        data.values.reduce((sum, series) => sum + series[xi], 0),
      ),
      max = Math.max(1, ...totals),
      left = CHART.left,
      right = 292,
      x = (index) => scale(index, 0, data.xLabels.length - 1, left, right),
      y = (value) => scale(value, 0, max, CHART.base, CHART.top),
      cumulative = new Array(data.xLabels.length).fill(0);
    let body = numericAxes(0, max, data.yAxisTitle, data.unit, { right });
    data.values.forEach((series, si) => {
      const bottom = cumulative.slice(),
        top = series.map((value, xi) => bottom[xi] + value),
        upper = top.map((value, xi) => [x(xi), y(value)]),
        lower = bottom.map((value, xi) => [x(xi), y(value)]).reverse();
      body += `<path class="tone-${si + 1}" d="${path([...upper, ...lower])}Z"/>`;
      top.forEach((value, xi) => {
        cumulative[xi] = value;
      });
    });
    const railYs = data.seriesLabels.map(
      (_, i) =>
        CHART.top +
        ((i + 0.5) * (CHART.base - CHART.top)) / data.seriesLabels.length,
    );
    let atLast = 0;
    data.seriesLabels.forEach((label, si) => {
      const mid = atLast + data.values[si].at(-1) / 2,
        fromY = y(mid);
      atLast += data.values[si].at(-1);
      body += `<path class="quiet" d="M${right} ${fromY.toFixed(2)}L302 ${railYs[si].toFixed(2)}"/>${chartLabel(label, 306, railYs[si] + 3.5, "axis-title", "start")}`;
    });
    const stride = Math.max(1, Math.ceil(data.xLabels.length / 7));
    data.xLabels.forEach((label, i) => {
      if (i % stride === 0 || i === data.xLabels.length - 1)
        body += chartLabel(label, x(i), 157, "muted");
    });
    body += `${chartLabel(fmt(totals[0]), left + 4, Math.max(20, y(totals[0]) - 5), "value", "start")}${chartLabel(fmt(totals.at(-1)), right - 4, Math.max(20, y(totals.at(-1)) - 5), "value", "end")}${axisX(data.xAxisTitle)}`;
    return chartFrame(body, data, opts, "zero");
  };

  C.rangeBars = (params, opts) => {
    const data = chartParams(params, [
        "items",
        "unit",
        "xAxisTitle",
        "scaleMin",
        "scaleMax",
        "sourceNote",
      ]),
      items = list(data.items, "items", 1, 8).map((value, i) => {
        chartItem(
          value,
          `items[${i}]`,
          ["label", "low", "high", "mark", "markLabel", "open", "detail"],
          ["label", "low", "high"],
        );
        if (value.low > value.high)
          throw new TypeError(`items[${i}].low must not exceed high`);
        if (value.mark != null) number(value.mark, `items[${i}].mark`);
        if (value.markLabel != null)
          text(value.markLabel, `items[${i}].markLabel`, true);
        return value;
      });
    opts = opts || {};
    text(data.unit, "unit");
    text(data.xAxisTitle, "xAxisTitle");
    if (data.scaleMin != null) number(data.scaleMin, "scaleMin");
    if (data.scaleMax != null) number(data.scaleMax, "scaleMax");
    const observed = items.flatMap((item) => [
        item.low,
        item.high,
        ...(item.mark == null ? [] : [item.mark]),
      ]),
      min = data.scaleMin == null ? Math.min(0, ...observed) : data.scaleMin,
      max = data.scaleMax == null ? Math.max(1, ...observed) : data.scaleMax;
    if (min >= max) throw new TypeError("scaleMin must be less than scaleMax");
    if (observed.some((value) => value < min || value > max))
      throw new TypeError(
        "scaleMin and scaleMax must contain every item value",
      );
    const left = 94,
      right = 338,
      row = 107 / items.length,
      pos = (value) => scale(value, min, max, left, right);
    let body = numericAxes(min, max, "", data.unit, {
      left,
      right,
      top: CHART.top,
      base: CHART.base,
      horizontal: true,
    });
    items.forEach((item, i) => {
      const y = CHART.top + row * (i + 0.5),
        low = pos(item.low),
        high = pos(item.high);
      let marks = `${categoryLabel(item.label, left - 7, y + 4, 80, "end")}<path class="quiet${openClass(item, true)}" d="M${low.toFixed(2)} ${y.toFixed(2)}H${high.toFixed(2)}"/><path class="line${openClass(item, true)}" d="M${low.toFixed(2)} ${(y - 5).toFixed(2)}V${(y + 5).toFixed(2)}M${high.toFixed(2)} ${(y - 5).toFixed(2)}V${(y + 5).toFixed(2)}"/>${chartLabel(fmt(item.low), low, y - 7, "value")}${chartLabel(fmt(item.high), high, y - 7, "value")}`;
      if (item.mark != null) {
        const mark = pos(item.mark);
        marks += `<circle class="tone-4${openClass(item)}" cx="${mark.toFixed(2)}" cy="${y.toFixed(2)}" r="3.5"/>${chartLabel(item.markLabel || fmt(item.mark), mark, y + 13, "value")}`;
      }
      body += wrapDetail(marks, item);
    });
    body += axisX(data.xAxisTitle, data.unit);
    return chartFrame(body, data, opts, `scale-min:${fmt(min)}`);
  };

  LD.registry = REGISTRY.slice();
  // New work uses the reviewed core; saved files may still render all IDs.
  LD.recommendedRegistry = [
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
  ];
  LD.components = C;
  LD.render = (id, params, opts) => {
    var fn = C[id];
    if (!fn) throw new Error("unknown component: " + id);
    return fn(params, opts || {});
  };
})();
