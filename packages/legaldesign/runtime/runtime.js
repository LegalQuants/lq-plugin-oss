(() => {
  function boot() {
    window.LegalDesign = window.LegalDesign || {};
    const LD = window.LegalDesign;
    const root = document.documentElement;
    const stateNode = document.getElementById("legaldesign-state");
    if (!stateNode) return;

    const TEXT_TOKENS = ["ink", "muted", "faint", "red", "red-strong"];
    const FILL_TOKENS = ["card", "card-strong", "tint", "bg", "none"];
    // Template export replaces matter-specific copy, but these values describe
    // how a component is encoded rather than what the matter says. Preserve
    // them so the sanitized template remains both intentional and renderable.
    const TEMPLATE_STRUCTURAL_PARAM_KEYS = new Set([
      "accentRole",
      "baselineZero",
      "highlight",
      "markAt",
      "nowAt",
      "open",
      "orientation",
      "toward",
      "winner",
    ]);
    const TEMPLATE_HEAD_STYLE_BASELINES = Array.from(
      document.head ? document.head.querySelectorAll("style") : [],
    ).map((style, index) => ({
      id: style.id || null,
      index: index,
      attributes: Array.from(style.attributes).map((attribute) => [
        attribute.name,
        attribute.value,
      ]),
      text: style.textContent,
    }));
    const TEMPLATE_CSS_TOKENS = new Set([
      "bg",
      "card",
      "card-strong",
      "faint",
      "ink",
      "insert",
      "label",
      "line",
      "line-strong",
      "muted",
      "red",
      "red-strong",
      "red-wash",
      "scrim",
      "shadow",
      "shadow-soft",
      "tint",
    ]);
    const PLACEHOLDERS = {
      title: "[The claim in one sentence, ending with a period.]",
      cardTitle: "[The open item in five words.]",
      cardLine: "[One fact about it, under twenty words.]",
      figureLabel: "[Stage name.]",
    };
    const RELATIONSHIPS = [
      "sequence",
      "time",
      "hierarchy",
      "containment",
      "comparison",
      "convergence",
      "feedback",
      "priority",
      "progression",
      "interaction",
      "part-of-whole",
      "distribution",
      "correlation",
      "change",
      "quantity",
    ];
    const VARIANT_AXES = [
      "form",
      "framing",
      "granularity",
      "emphasis",
      "layout",
      "register",
      "single",
    ];
    const LEGACY_LAYOUTS = ["cards", "zones", "agenda", "track"];
    const VARIANT_FIELDS = new Set([
      "agreed_line",
      "axis",
      "cards",
      "component",
      "encoding",
      "html",
      "items",
      "layout",
      "params",
      "rows",
      "segments",
      "sub",
      "text",
      "title",
      "why",
    ]);
    const LEGACY_COLLECTION_FIELDS = {
      cards: new Set(["action", "detail", "line", "tag", "title"]),
      items: new Set(["line", "n", "title"]),
      segments: new Set(["detail", "label", "line", "name", "state"]),
    };
    const UNIT_KINDS = [
      "text",
      "card",
      "figure",
      "table",
      "evidence",
      "decision",
    ];
    const UNIT_ROLES = [
      "title",
      "answer",
      "summary",
      "action",
      "scope",
      "finding",
      "expected",
      "matter",
    ];
    let selection = [];
    const undo = [];
    let redo = [];
    let editing = false;
    let gesture = null;
    let textUndoArmed = false;
    let returnFocus = null;
    let returnFocusKey = null;
    const popupTrail = [];
    let suppressEditorClick = false;
    const EDITOR_OBJECTS =
      '[data-editable],[data-diagram-object],[data-editor-object],.ld-card,.sb-card,section.ld-unit[data-kind="card"],.ld-diagram svg g[role="button"]';
    const popupFallbackNodes = new WeakSet();
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
    const MIN_FIGURE_TEXT_PX = 11;
    const FIGURE_TEXT_ROUNDING_PX = 0.01;
    const WIDE_FRAME_WIDTH = 880;
    const WIDE_MIN_TEXT_PX = 12.25;

    function announceReady() {
      root.setAttribute("data-legaldesign-ready", "true");
      window.dispatchEvent(new CustomEvent("legaldesign:ready"));
    }

    function scheduleReady(afterPageListeners) {
      root.removeAttribute("data-legaldesign-ready");
      if (!afterPageListeners) {
        queueMicrotask(announceReady);
        return;
      }
      requestAnimationFrame(() => {
        requestAnimationFrame(announceReady);
      });
    }

    function safeJSON(value) {
      return JSON.stringify(value).replace(/</g, "\\u003c");
    }

    function clone(value) {
      return JSON.parse(JSON.stringify(value));
    }
    function same(a, b) {
      return safeJSON(a) === safeJSON(b);
    }
    function all(selector, scope) {
      return Array.prototype.slice.call(
        (scope || document).querySelectorAll(selector),
      );
    }
    function removeLegacyReviewChrome(scope) {
      all(
        ".ld-review,.ld-sheet-open,.ld-bottom-save,#ld-phone-sheet,#ld-selection-popover",
        scope || document,
      ).forEach((node) => {
        node.remove();
      });
    }
    function visible(node) {
      const box = node.getBoundingClientRect();
      return (
        !node.hidden &&
        box.width > 0 &&
        box.height > 0 &&
        getComputedStyle(node).visibility !== "hidden"
      );
    }
    function sanitizeEditorTokens(scope) {
      all("[data-fill-token]", scope || document).forEach((node) => {
        if (!FILL_TOKENS.includes(node.getAttribute("data-fill-token")))
          node.removeAttribute("data-fill-token");
      });
      all("[data-text-token]", scope || document).forEach((node) => {
        if (!TEXT_TOKENS.includes(node.getAttribute("data-text-token")))
          node.removeAttribute("data-text-token");
      });
    }
    function restoreTrustedTemplateStyles(cloneRoot) {
      all("style", cloneRoot).forEach((style) => {
        if (!style.closest("head")) style.remove();
      });
      const head = cloneRoot.querySelector("head");
      if (!head) return;
      const candidates = all("style", head);
      const claimed = new Set();
      TEMPLATE_HEAD_STYLE_BASELINES.forEach((baseline) => {
        let style = baseline.id
          ? candidates.find(
              (candidate) =>
                !claimed.has(candidate) && candidate.id === baseline.id,
            )
          : candidates[baseline.index];
        if (style && claimed.has(style)) style = null;
        if (!style)
          style = candidates.find((candidate) => !claimed.has(candidate));
        if (!style) {
          style = document.createElement("style");
          head.appendChild(style);
        }
        Array.from(style.attributes).forEach((attribute) => {
          style.removeAttribute(attribute.name);
        });
        baseline.attributes.forEach(([name, value]) => {
          style.setAttribute(name, value);
        });
        style.textContent = baseline.text;
        claimed.add(style);
      });
      candidates.forEach((style) => {
        if (!claimed.has(style)) style.remove();
      });
    }
    function safeTemplateMeasurement(value, allowKeywords) {
      const keywords = allowKeywords || [];
      return String(value)
        .trim()
        .split(/\s+/)
        .every(
          (part) =>
            keywords.includes(part) ||
            /^-?(?:\d+(?:\.\d+)?|\.\d+)(?:px|%|em|rem|vh|vw)?$/.test(part),
        );
    }
    function safeTemplateTransform(value) {
      value = String(value).trim();
      if (value === "none") return true;
      const number = "-?(?:\\d+(?:\\.\\d+)?|\\.\\d+)(?:px|%|deg)?";
      const args = `${number}(?:\\s*(?:,|\\s)\\s*${number}){0,15}`;
      const transform = new RegExp(
        `(?:matrix3d|matrix|translate3d|translate|translateX|translateY|scale3d|scale|scaleX|scaleY|rotate)\\(\\s*${args}\\s*\\)`,
        "gi",
      );
      return value.replace(transform, "").trim() === "";
    }
    function safeTemplateColor(value) {
      value = String(value).trim();
      if (["currentcolor", "inherit", "none", "transparent"].includes(value))
        return true;
      const match = /^var\(--([a-z0-9-]+)\)$/.exec(value);
      return Boolean(match && TEMPLATE_CSS_TOKENS.has(match[1]));
    }
    function safeTemplateStyleValue(property, value) {
      // Composed pages encode placement with numeric custom properties. These
      // are structural coordinates, not matter content; stripping them collapses
      // every unit into a single grid column in an exported template.
      if (
        ["--ld-row", "--ld-column", "--ld-span", "--ld-row-span"].includes(
          property,
        )
      )
        return /^[1-9]\d{0,3}$/.test(String(value).trim());
      const measurements = new Set([
        "bottom",
        "border-radius",
        "column-gap",
        "font-size",
        "gap",
        "height",
        "left",
        "max-height",
        "max-width",
        "min-height",
        "min-width",
        "right",
        "row-gap",
        "top",
        "width",
      ]);
      const boxMeasurements =
        /^(?:margin|padding)(?:-(?:top|right|bottom|left))?$/;
      if (measurements.has(property))
        return safeTemplateMeasurement(value, ["auto", "none"]);
      if (boxMeasurements.test(property))
        return safeTemplateMeasurement(value, ["auto"]);
      if (
        ["background", "background-color", "border-color", "color"].includes(
          property,
        )
      )
        return safeTemplateColor(value);
      if (property === "transform") return safeTemplateTransform(value);
      if (property === "transform-origin")
        return safeTemplateMeasurement(value, [
          "bottom",
          "center",
          "left",
          "right",
          "top",
        ]);
      if (property === "position")
        return ["absolute", "fixed", "relative", "static", "sticky"].includes(
          value,
        );
      if (property === "display")
        return [
          "block",
          "flex",
          "grid",
          "inline",
          "inline-block",
          "inline-flex",
          "none",
        ].includes(value);
      if (property === "justify-content")
        return [
          "center",
          "end",
          "flex-end",
          "flex-start",
          "space-around",
          "space-between",
          "space-evenly",
          "start",
        ].includes(value);
      if (property === "text-align")
        return ["center", "end", "left", "right", "start"].includes(value);
      if (property === "box-sizing")
        return ["border-box", "content-box"].includes(value);
      if (property === "transform-box")
        return ["border-box", "content-box", "fill-box", "view-box"].includes(
          value,
        );
      if (property === "font-style")
        return ["italic", "normal", "oblique"].includes(value);
      if (property === "font-weight")
        return /^(?:normal|bold|[1-9]00)$/.test(value);
      if (property === "text-decoration-line")
        return /^(?:none|underline|overline|line-through)(?:\s+(?:underline|overline|line-through))*$/.test(
          value,
        );
      if (property === "line-height")
        return value === "normal" || safeTemplateMeasurement(value);
      if (property === "z-index") return /^-?\d+$/.test(value);
      return false;
    }
    function scrubTemplateMatterAttributes(cloneRoot) {
      const idReferences = new Set([
        "aria-controls",
        "aria-describedby",
        "aria-labelledby",
      ]);
      const stateValues = {
        "aria-current": new Set([
          "date",
          "false",
          "location",
          "page",
          "step",
          "time",
          "true",
        ]),
        "aria-disabled": new Set(["false", "true"]),
        "aria-expanded": new Set(["false", "true"]),
        "aria-haspopup": new Set([
          "dialog",
          "false",
          "grid",
          "listbox",
          "menu",
          "tree",
          "true",
        ]),
        "aria-hidden": new Set(["false", "true"]),
        "aria-live": new Set(["assertive", "off", "polite"]),
        "aria-modal": new Set(["false", "true"]),
        "aria-pressed": new Set(["false", "mixed", "true"]),
      };
      const ids = new Set(
        all("[id]", cloneRoot)
          .map((node) => node.id)
          .filter(Boolean),
      );
      all("*", cloneRoot).forEach((node) => {
        if (node.localName === "style" || node.localName === "script") return;
        if (node.hasAttribute("style")) {
          const kept = Array.from(node.style)
            .map((property) => ({
              property: property,
              value: node.style.getPropertyValue(property).trim(),
              priority: node.style.getPropertyPriority(property),
            }))
            .filter((item) =>
              safeTemplateStyleValue(item.property, item.value),
            );
          node.removeAttribute("style");
          kept.forEach((item) => {
            node.style.setProperty(item.property, item.value, item.priority);
          });
        }
        if (node.hasAttribute("value")) {
          const value = node.getAttribute("value");
          const safeDecision =
            node.hasAttribute("data-decision-option") &&
            /^option-\d+$/.test(value);
          const safeFill =
            node.matches("#editor-fill-token option") &&
            [""].concat(FILL_TOKENS).includes(value);
          const safeText =
            node.matches("#editor-text-token option") &&
            [""].concat(TEXT_TOKENS).includes(value);
          if (!safeDecision && !safeFill && !safeText)
            node.removeAttribute("value");
        }
        if (node.hasAttribute("placeholder")) {
          if (node.hasAttribute("data-decision-custom"))
            node.setAttribute("placeholder", "Custom position");
          else if (node.hasAttribute("data-decision-note"))
            node.setAttribute("placeholder", "Note");
          else if (node.matches("input,textarea"))
            node.setAttribute("placeholder", "[Editable value.]");
          else node.removeAttribute("placeholder");
        }
        Array.from(node.attributes).forEach((attribute) => {
          const name = attribute.name.toLowerCase();
          if (!name.startsWith("aria-")) return;
          if (name === "aria-label" || name === "aria-description") {
            if (name === "aria-description")
              node.setAttribute(name, "[Accessible description.]");
            return;
          }
          if (idReferences.has(name)) {
            const references = attribute.value
              .split(/\s+/)
              .filter((id) => id && ids.has(id));
            if (references.length)
              node.setAttribute(name, references.join(" "));
            else node.removeAttribute(name);
            return;
          }
          if (stateValues[name] && stateValues[name].has(attribute.value))
            return;
          node.removeAttribute(name);
        });
      });
    }
    function normalizeChrome() {
      ["mode-toggle", "export-html", "export-template"].forEach((id) => {
        const control = document.getElementById(id);
        if (control) control.setAttribute("data-editor-only", "");
      });
      const controls = document.querySelector(".ld-controls");
      const editorTools = document.querySelector(".ld-editor-tools");
      if (controls) controls.classList.add("ld-pills");
      if (controls && editorTools && editorTools.parentElement !== controls) {
        const theme = document.getElementById("theme-toggle");
        controls.insertBefore(editorTools, theme || controls.firstChild);
      }
      [
        ["editor-font-down", "A−", "Decrease type"],
        ["editor-font-up", "A+", "Increase type"],
        ["editor-bold", "B", "Bold"],
        ["editor-italic", "I", "Italic"],
        ["editor-underline", "U", "Underline"],
      ].forEach((entry) => {
        const button = document.getElementById(entry[0]);
        if (!button) return;
        button.textContent = entry[1];
        button.setAttribute("aria-label", entry[2]);
        button.title = entry[2];
      });
      const theme = document.getElementById("theme-toggle");
      if (theme) {
        theme.setAttribute("aria-label", "Theme");
        theme.title = "Theme";
        theme.innerHTML =
          '<svg class="ld-theme-icon ld-theme-moon" aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.8A9 9 0 1 1 11.2 3 7 7 0 0 0 21 12.8z"></path></svg><svg class="ld-theme-icon ld-theme-sun" aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="4"></circle><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"></path></svg>';
      }
      const overflow = document.getElementById("editor-overflow-toggle");
      if (overflow) {
        overflow.textContent = "More";
        overflow.setAttribute("aria-label", "More");
      }
      [
        ["editor-fill-token", "Fill", FILL_TOKENS],
        ["editor-text-token", "Text", TEXT_TOKENS],
      ].forEach((entry) => {
        const select = document.getElementById(entry[0]);
        if (!select) return;
        const value = select.value;
        select.replaceChildren();
        [""].concat(entry[2]).forEach((token) => {
          const option = document.createElement("option");
          option.value = token;
          option.textContent = token || entry[1];
          select.appendChild(option);
        });
        if ([""].concat(entry[2]).includes(value)) select.value = value;
      });
      sanitizeEditorTokens(document);
      installAuthoringControls();
    }
    function rememberReturnFocus(source) {
      const node = source || document.activeElement;
      const unit = node && node.closest("[data-unit]");
      returnFocus = node;
      returnFocusKey = node
        ? {
            id: node.id || null,
            detail: node.getAttribute("data-detail"),
            evidence: node.getAttribute("data-evidence"),
            card: node.matches(".ld-card[data-evidence]"),
            unit: unit && unit.getAttribute("data-unit"),
          }
        : null;
    }
    function restoreReturnFocus() {
      let target = returnFocus;
      const key = returnFocusKey;
      if (target && !target.isConnected && key) {
        if (key.id) target = document.getElementById(key.id);
        if ((!target || !target.isConnected) && key.detail)
          target = all("[data-detail]").find(
            (node) =>
              node.getAttribute("data-detail") === key.detail &&
              !node.closest("[hidden]"),
          );
        if ((!target || !target.isConnected) && key.evidence)
          target = all(
            key.card ? ".ld-card[data-evidence]" : "[data-evidence]",
          ).find(
            (node) =>
              node.getAttribute("data-evidence") === key.evidence &&
              !node.closest("[hidden]"),
          );
      }
      if (target && target.isConnected) target.focus();
      returnFocus = null;
      returnFocusKey = null;
    }
    function parseDate(value) {
      const time = Date.parse(value || "");
      return Number.isFinite(time) ? time : 0;
    }

    let blockState;
    try {
      blockState = JSON.parse(stateNode.textContent);
      if (blockState.schema !== "legaldesign.state.v1")
        throw new TypeError("unsupported legaldesign state schema");
      const roundTrip = JSON.parse(safeJSON(blockState));
      if (!same(blockState, roundTrip))
        throw new Error("legaldesign state round-trip mismatch");
    } catch (error) {
      console.error(
        "LegalDesign refused to render stale or invalid state.",
        error,
      );
      root.setAttribute("data-legaldesign-error", "state");
      return;
    }

    function stableLocationHash(value) {
      let hash = 2166136261;
      value = String(value || "");
      for (let index = 0; index < value.length; index += 1) {
        hash ^= value.charCodeAt(index);
        hash = Math.imul(hash, 16777619);
      }
      return (hash >>> 0).toString(36);
    }
    function stableTemplateLocation() {
      try {
        const url = new URL(window.location.href);
        url.search = "";
        url.hash = "";
        return url.href;
      } catch (_) {
        return String(window.location.href || "").split(/[?#]/)[0];
      }
    }

    let state = blockState;
    const exportMode = root.getAttribute("data-exported");
    if (exportMode === "client") {
      const blueprintId =
        root.getAttribute("data-client-blueprint-id") || state.artifactId;
      const instanceId =
        blueprintId +
        "-client-copy-" +
        stableLocationHash(stableTemplateLocation());
      state.artifactId = instanceId;
      root.setAttribute("data-client-blueprint-id", blueprintId);
      root.setAttribute("data-client-id", instanceId);
      stateNode.textContent = safeJSON(state);
    }
    if (
      exportMode === "template" &&
      ["exported", "packaged"].includes(root.getAttribute("data-template-kind"))
    ) {
      const blueprintId =
        root.getAttribute("data-template-blueprint-id") || state.artifactId;
      const instanceId =
        blueprintId + "-copy-" + stableLocationHash(stableTemplateLocation());
      state.artifactId = instanceId;
      root.setAttribute("data-template-blueprint-id", blueprintId);
      root.setAttribute("data-template-id", instanceId);
      stateNode.textContent = safeJSON(state);
    }
    let storageKey = "legaldesign:" + state.artifactId + ":v1";
    if (exportMode)
      storageKey = "legaldesign:" + state.artifactId + ":" + exportMode + ":v1";
    const domStorageKey = storageKey + ":dom";

    function writeBlock() {
      stateNode.textContent = safeJSON(state);
    }
    function mirror() {
      writeBlock();
      try {
        localStorage.setItem(storageKey, safeJSON(state));
      } catch (_) {
        /* local files may deny storage */
      }
    }
    function editorRoots() {
      return [
        document.querySelector("main"),
        document.getElementById("popup-scrim"),
      ].filter(Boolean);
    }
    function cleanSnapshotHTML(node) {
      const copy = node.cloneNode(true);
      all("[contenteditable]", copy).forEach((editable) => {
        editable.removeAttribute("contenteditable");
        editable.removeAttribute("spellcheck");
      });
      all(".ld-selected,.ld-selection-mark", copy).forEach((selected) => {
        selected.classList.remove("ld-selected", "ld-selection-mark");
      });
      return copy.innerHTML;
    }
    function editorDOMSnapshot() {
      return {
        schema: "legaldesign.editor-dom.v1",
        artifactId: state.artifactId,
        savedAt: state.savedAt,
        roots: editorRoots().map((node, index) => ({
          id: node.id || null,
          index: index,
          html: cleanSnapshotHTML(node),
        })),
      };
    }
    function storeEditorDOM() {
      if (root.getAttribute("data-exported") === "client") return;
      try {
        localStorage.setItem(domStorageKey, safeJSON(editorDOMSnapshot()));
      } catch (_) {
        /* local files may deny storage */
      }
    }
    function readEditorDOM() {
      try {
        const saved = JSON.parse(localStorage.getItem(domStorageKey) || "null");
        if (
          saved &&
          saved.schema === "legaldesign.editor-dom.v1" &&
          saved.artifactId === state.artifactId &&
          Array.isArray(saved.roots)
        )
          return saved;
      } catch (_) {
        /* malformed recovery data is ignored */
      }
      return null;
    }
    function applyEditorDOM(saved) {
      if (!saved || parseDate(saved.savedAt) > parseDate(state.savedAt)) return;
      (saved.roots || []).forEach((item) => {
        const current = item.id
          ? document.getElementById(item.id)
          : editorRoots()[item.index];
        if (current && typeof item.html === "string")
          current.innerHTML = item.html;
      });
      sanitizeEditorTokens(document);
    }
    function captureSnapshot() {
      syncEditorDOMToState();
      return {
        state: clone(state),
        roots: editorRoots().map((node) => ({
          id: node.id || null,
          tag: node.tagName,
          html: cleanSnapshotHTML(node),
        })),
      };
    }
    function checkpoint() {
      undo.push(captureSnapshot());
      if (undo.length > 100) undo.shift();
      redo = [];
      updateEditorButtons();
    }
    function change(fn, options) {
      if (!options || options.history !== false) checkpoint();
      fn(state);
      state.savedAt = new Date().toISOString();
      mirror();
      renderAll();
      storeEditorDOM();
    }
    function restoreSnapshot(next) {
      state = clone(next.state);
      (next.roots || []).forEach((saved, index) => {
        const current = saved.id
          ? document.getElementById(saved.id)
          : editorRoots()[index];
        if (current) current.innerHTML = saved.html;
      });
      sanitizeEditorTokens(document);
      selection = [];
      gesture = null;
      textUndoArmed = false;
      mirror();
      applyTheme((state.review && state.review.theme) || initialTheme(), false);
      bindApproaches();
      bindUnits();
      bindDecisions();
      bindPopupDOM();
      installComposedForm();
      stampEditorOrigins();
      renderSelection();
      storeEditorDOM();
    }
    function doUndo() {
      if (!undo.length) return;
      redo.push(captureSnapshot());
      restoreSnapshot(undo.pop());
      updateEditorButtons();
    }
    function doRedo() {
      if (!redo.length) return;
      undo.push(captureSnapshot());
      restoreSnapshot(redo.pop());
      updateEditorButtons();
    }

    function initialTheme() {
      if (
        state.review &&
        (state.review.theme === "light" || state.review.theme === "dark")
      )
        return state.review.theme;
      return window.matchMedia &&
        window.matchMedia("(prefers-color-scheme: dark)").matches
        ? "dark"
        : "light";
    }
    function applyTheme(theme, persist) {
      const next = theme === "dark" ? "dark" : "light";
      root.setAttribute("data-theme", next);
      if (!state.review) state.review = {};
      state.review.theme = next;
      if (persist) {
        state.savedAt = new Date().toISOString();
        mirror();
      }
    }

    function installRestoreBanner() {
      let stored = null;
      try {
        stored = JSON.parse(localStorage.getItem(storageKey) || "null");
      } catch (_) {
        stored = null;
      }
      if (root.getAttribute("data-exported") === "client") {
        if (
          stored &&
          stored.schema === state.schema &&
          parseDate(stored.savedAt) > parseDate(state.savedAt) &&
          !same(stored, state)
        ) {
          state = stored;
          mirror();
          renderAll({ sync: false });
        }
        return;
      }
      if (
        !stored ||
        stored.schema !== state.schema ||
        parseDate(stored.savedAt) <= parseDate(state.savedAt) ||
        same(stored, state)
      )
        return;
      const banner = document.createElement("div");
      banner.className = "ld-restore";
      banner.id = "ld-restore-banner";
      banner.innerHTML =
        '<span>Restore unsaved changes?</span><button type="button" data-restore>Restore</button><button type="button" data-discard>Discard</button>';
      const bar = document.querySelector(".ld-bar");
      (bar ? bar.parentNode : document.body).insertBefore(
        banner,
        bar ? bar.nextSibling : document.body.firstChild,
      );
      banner.querySelector("[data-restore]").addEventListener("click", () => {
        state = stored;
        applyEditorDOM(readEditorDOM());
        mirror();
        banner.remove();
        renderAll({ sync: false });
        bindApproaches();
        bindUnits();
        bindDecisions();
        bindPopupDOM();
        installComposedForm();
        stampEditorOrigins();
        storeEditorDOM();
      });
      banner.querySelector("[data-discard]").addEventListener("click", () => {
        try {
          localStorage.removeItem(storageKey);
          localStorage.removeItem(domStorageKey);
        } catch (_) {}
        banner.remove();
        mirror();
      });
    }

    function unitState(id) {
      return state.units && state.units[id];
    }
    function selectedVariant(unit) {
      return unit && unit.variants ? unit.variants[unit.selected] : null;
    }
    function setVariant(id, variant) {
      const unit = unitState(id);
      if (!unit || !unit.variants || !unit.variants[variant]) return;
      change(() => {
        unit.selected = variant;
      });
    }
    function hasPageApproaches() {
      return Boolean(
        state.approaches &&
          state.approaches.a &&
          state.approaches.b &&
          document.querySelector("[data-approach='a']") &&
          document.querySelector("[data-approach='b']"),
      );
    }
    function currentApproach() {
      return state.review && state.review.approach === "b" ? "b" : "a";
    }
    function renderApproach() {
      if (!hasPageApproaches()) return;
      const selected = currentApproach();
      root.setAttribute("data-page-approach", selected);
      all("[data-approach]").forEach((page) => {
        page.hidden = page.getAttribute("data-approach") !== selected;
      });
      all("[data-select-approach]").forEach((button) => {
        button.setAttribute(
          "aria-pressed",
          button.getAttribute("data-select-approach") === selected
            ? "true"
            : "false",
        );
      });
    }
    function setApproach(approach) {
      if (!hasPageApproaches() || !["a", "b"].includes(approach)) return;
      if (!state.review) state.review = {};
      if (state.review.approach === approach) return;
      syncEditorDOMToState();
      state.review.approach = approach;
      state.review.location = 0;
      state.savedAt = new Date().toISOString();
      const nav = document.getElementById("ld-form-navigation");
      if (nav) nav.remove();
      renderAll({ sync: false });
      installComposedForm();
      mirror();
      storeEditorDOM();
    }
    function bindApproaches() {
      const control = document.getElementById("ld-page-approach");
      if (!control || control.__legalDesignApproachBound) return;
      control.__legalDesignApproachBound = true;
      control.addEventListener("click", (event) => {
        const button = event.target.closest("[data-select-approach]");
        if (!button) return;
        setApproach(button.getAttribute("data-select-approach"));
      });
      control.addEventListener("keydown", (event) => {
        if (!["ArrowLeft", "ArrowRight"].includes(event.key)) return;
        event.preventDefault();
        setApproach(event.key === "ArrowLeft" ? "a" : "b");
        const selected = control.querySelector(
          '[data-select-approach="' + currentApproach() + '"]',
        );
        if (selected) selected.focus();
      });
    }
    function pointerPart(value) {
      return String(value).replace(/~/g, "~0").replace(/\//g, "~1");
    }
    function pointerValue(rootValue, pointer, nextValue) {
      if (!rootValue || !pointer || pointer[0] !== "/") return false;
      const parts = pointer
        .slice(1)
        .split("/")
        .map((part) => part.replace(/~1/g, "/").replace(/~0/g, "~"));
      let current = rootValue;
      for (let index = 0; index < parts.length - 1; index += 1) {
        if (current == null || typeof current !== "object") return false;
        current = current[parts[index]];
      }
      if (current == null || typeof current !== "object") return false;
      current[parts[parts.length - 1]] = nextValue;
      return true;
    }
    function diagramLeaves(value, path, output) {
      const leaves = output || [];
      const pointer = path || "";
      if (typeof value === "string" || typeof value === "number") {
        leaves.push({
          path: pointer,
          value: String(value).replace(/\s+/g, " ").trim(),
          used: false,
        });
        return leaves;
      }
      if (Array.isArray(value)) {
        value.forEach((item, index) => {
          diagramLeaves(item, pointer + "/" + index, leaves);
        });
        return leaves;
      }
      if (value && typeof value === "object") {
        Object.keys(value).forEach((key) => {
          diagramLeaves(value[key], pointer + "/" + pointerPart(key), leaves);
        });
      }
      return leaves;
    }
    function diagramLabelValue(label) {
      const lines = all("tspan", label);
      return (
        lines.length
          ? lines.map((line) => line.textContent.trim()).join(" ")
          : label.textContent
      )
        .replace(/\s+/g, " ")
        .trim();
    }
    function annotateDiagramLabels(scope, params) {
      const leaves = diagramLeaves(params || {});
      all(".ld-diagram svg text", scope || document).forEach((label) => {
        label.setAttribute("data-diagram-label", "");
        label.setAttribute("data-editable", "");
        if (editing) {
          label.setAttribute("tabindex", "0");
          label.setAttribute("role", "textbox");
          label.setAttribute("aria-label", "Editable diagram label");
        } else {
          label.removeAttribute("tabindex");
          label.removeAttribute("role");
          label.removeAttribute("aria-label");
        }
        if (!label.hasAttribute("data-placeholder")) {
          label.setAttribute(
            "data-placeholder",
            diagramLabelValue(label) || PLACEHOLDERS.figureLabel,
          );
        }
        if (!label.hasAttribute("data-param-path")) {
          const value = diagramLabelValue(label);
          const match = leaves.find(
            (leaf) => !leaf.used && leaf.value === value,
          );
          if (match) {
            match.used = true;
            label.setAttribute("data-param-path", match.path);
          }
        }
      });
    }

    function renderFigure(section, unit) {
      all(".ld-variant", section).forEach((variant) => {
        const id = variant.getAttribute("data-variant");
        const spec = unit.variants && unit.variants[id];
        const host = variant.querySelector(".ld-diagram");
        if (!host || !spec || !spec.component) return;
        if (
          (host.hasAttribute("data-editor-preserve-dom") ||
            root.getAttribute("data-exported") === "client") &&
          host.querySelector("svg")
        ) {
          annotateDiagramLabels(host, spec.params);
          return;
        }
        // Page scaling is presentation only. Keep the authored diagram in its
        // desktop geometry when the complete 4:3 page is fitted on a phone.
        const hostWidth = host.closest(".ld-fixed-page")
          ? host.clientWidth
          : host.getBoundingClientRect().width;
        const narrow =
          hostWidth <
          (WIDE_FRAME_WIDTH * MIN_FIGURE_TEXT_PX) / WIDE_MIN_TEXT_PX;
        host.innerHTML = LD.render(spec.component, spec.params, {
          narrow: narrow,
          density: singleComposition() ? "compact" : "standard",
          ariaLabel: unit.claim,
        });
        const figure = host.querySelector("svg");
        if (!figure) return;
        annotateDiagramLabels(host, spec.params);
        figure.setAttribute("data-frame", narrow ? "narrow" : "wide");
        if (narrow && hostWidth > 480 && !host.closest(".ld-fixed-page")) {
          const sectionBox = section.getBoundingClientRect();
          const hostBox = host.getBoundingClientRect();
          const source = section.querySelector(".ld-source-note");
          let trailing = 0;
          if (source) {
            const style = getComputedStyle(source);
            trailing =
              source.getBoundingClientRect().height +
              (parseFloat(style.marginTop) || 0) +
              (parseFloat(style.marginBottom) || 0);
          }
          const sectionStyle = getComputedStyle(section);
          const available =
            sectionBox.bottom -
            hostBox.top -
            trailing -
            (parseFloat(sectionStyle.paddingBottom) || 0) -
            (parseFloat(sectionStyle.borderBottomWidth) || 0);
          const viewHeight = figure.viewBox.baseVal.height;
          const minimum =
            (viewHeight * (MIN_FIGURE_TEXT_PX + FIGURE_TEXT_ROUNDING_PX)) /
            WIDE_MIN_TEXT_PX;
          figure.style.height = Math.max(available, minimum) + "px";
          figure.style.maxHeight = "none";
        }
      });
    }

    function installInlineDetail(section, unit) {
      // A prose block is not one giant hyperlink. Move its authored target to
      // a short phrase, or a named detail link for older specifications. Added
      // editor text keeps its existing whole-object popup behavior.
      if (
        unit.kind !== "text" ||
        !section.matches(".ld-composed-unit[data-detail]")
      )
        return;
      const detail = section.getAttribute("data-detail");
      all(".ld-variant > [data-variant-body]", section).forEach((body) => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "ld-inline-detail";
        button.setAttribute("data-detail", detail);
        button.setAttribute("aria-haspopup", "dialog");
        button.setAttribute("aria-controls", detail);
        const anchor = unit.detailAnchor;
        const walker = document.createTreeWalker(body, NodeFilter.SHOW_TEXT);
        for (
          let node = walker.nextNode();
          anchor && node;
          node = walker.nextNode()
        ) {
          const at = node.textContent.indexOf(anchor);
          if (at < 0 || node.parentElement.closest("a,button")) continue;
          const match = node.splitText(at);
          match.splitText(anchor.length);
          button.textContent = anchor;
          match.replaceWith(button);
          break;
        }
        if (!button.parentNode) {
          const title = state.evidence?.[detail]?.popup?.title;
          button.textContent =
            title && title.length <= 72 ? title : "Read supporting detail";
          const line = document.createElement("p");
          line.className = "ld-detail-linkline";
          line.appendChild(button);
          body.appendChild(line);
        }
      });
      [
        "data-detail",
        "role",
        "tabindex",
        "aria-haspopup",
        "aria-controls",
      ].forEach((name) => {
        section.removeAttribute(name);
      });
      section.classList.remove("ld-popup-trigger");
    }

    function renderUnit(section) {
      const id = section.getAttribute("data-unit");
      const unit = unitState(id);
      if (!unit) return;
      all(".ld-variant", section).forEach((variant) => {
        const key = variant.getAttribute("data-variant");
        variant.hidden = key !== unit.selected;
        if (
          unit.edits &&
          unit.edits[key] != null &&
          unit.kind !== "figure" &&
          root.getAttribute("data-exported") !== "client"
        ) {
          const body = variant.querySelector("[data-variant-body]");
          if (body && body.innerHTML !== unit.edits[key])
            body.innerHTML = unit.edits[key];
        }
      });
      all(".ld-ab button", section).forEach((button) => {
        button.setAttribute(
          "aria-pressed",
          button.getAttribute("data-select-variant") === unit.selected
            ? "true"
            : "false",
        );
      });
      const why = section.querySelector(".ld-why");
      if (why) {
        const current = selectedVariant(unit);
        why.textContent = current && current.why ? current.why : "";
      }
      if (unit.kind === "figure") renderFigure(section, unit);
      installInlineDetail(section, unit);
    }

    function renderAll(options) {
      if (editing && (!options || options.sync !== false))
        syncEditorDOMToState();
      renderApproach();
      all("section.ld-unit[data-unit]").forEach(renderUnit);
      renderDecisions();
      applyTheme((state.review && state.review.theme) || initialTheme(), false);
      updateComposedForm();
    }

    function composedSections() {
      if (!root.hasAttribute("data-composed-shell")) return [];
      const selected = document.querySelector(
        '#legaldesign-composed-root > [data-approach="' +
          currentApproach() +
          '"]',
      );
      if (selected)
        return all(
          ":scope > .ld-composed-section[data-composition-section]",
          selected,
        );
      return all(
        "#legaldesign-composed-root > .ld-composed-section[data-composition-section]",
      );
    }
    function composedForm() {
      return state.brief && state.brief.form;
    }
    function singleComposition() {
      return state.sourceSchemaVersion === "legaldesign.build.v4";
    }
    function pageScaleFor(node) {
      return node && node.closest && node.closest(".ld-fixed-page")
        ? Number(root.style.getPropertyValue("--ld-page-scale")) || 1
        : 1;
    }
    function layoutViewport() {
      // WebKit may report the pinch-zoomed visual viewport through innerWidth
      // and innerHeight. Refitting to those values counteracts native zoom.
      // Root client dimensions describe the layout viewport, matching CSS.
      return {
        width: root.clientWidth || window.innerWidth,
        height: root.clientHeight || window.innerHeight,
      };
    }
    function onLayoutResize(callback) {
      let previous = layoutViewport();
      window.addEventListener("resize", () => {
        const next = layoutViewport();
        if (next.width === previous.width && next.height === previous.height)
          return;
        previous = next;
        callback();
      });
    }
    function fixedPageTargets() {
      if (root.hasAttribute("data-composed-shell")) {
        const approaches = all(
          "#legaldesign-composed-root > .ld-page-approach",
        );
        if (composedForm() === "one-page") return approaches;
        return all(".ld-page-approach > .ld-composed-section");
      }
      const slides = all("main > .sb-slide[data-frame]");
      if (slides.length) return slides;
      // Reference templates retain their own composition. The library is an
      // authoring catalogue, not a deliverable, and is intentionally excluded.
      return all("main.ld-page");
    }
    function paginateReferenceOverview() {
      if (root.hasAttribute("data-composed-shell")) return;
      const main = document.querySelector("main.ld-page");
      const core = main && main.querySelector(":scope > .ld-core");
      const figure = core && core.querySelector(":scope > .ld-figure");
      if (!main || !core || !figure || main.querySelector(":scope > .sb-slide"))
        return;
      // Old single-sheet references held overview, diagram and four detailed
      // cards in one tall area. Preserve every node, splitting at that existing
      // semantic boundary rather than squeezing the diagram or dropping copy.
      const overview = document.createElement("section");
      overview.className = "sb-slide is-current ld-reference-page";
      overview.setAttribute("data-frame", "1");
      const details = document.createElement("section");
      details.className = "sb-slide ld-reference-page";
      details.setAttribute("data-frame", "2");
      details.hidden = true;
      let afterCore = false;
      Array.from(main.children).forEach((node) => {
        if (node === core) {
          afterCore = true;
          overview.appendChild(figure);
          core.classList.add("ld-reference-cards");
          details.appendChild(core);
        } else (afterCore ? details : overview).appendChild(node);
      });
      main.append(overview, details);
      if (!main.id) main.id = "slide-stage";
    }
    function referenceEvidenceDetails() {
      const scrim = document.getElementById("popup-scrim");
      if (!scrim || root.hasAttribute("data-composed-shell")) return;
      all("main .finding-grid .evidence-panel").forEach((panel, index) => {
        const page = panel.closest(".sb-slide[data-frame]");
        const id =
          "reference-evidence-" +
          (page?.getAttribute("data-frame") || index + 1);
        const title =
          panel.querySelector("h2")?.textContent || "Evidence reviewed";
        if (document.getElementById(id)) return;
        state.evidence[id] = {
          cite: "",
          locator: "",
          excerpt: "",
          link: null,
          status: "authored",
          popup: { type: "detail", title, lede: "", sections: [] },
        };
        const pop = document.createElement("article");
        pop.id = id;
        pop.className = "pop";
        pop.hidden = true;
        pop.setAttribute("data-evidence-id", id);
        pop.setAttribute("role", "dialog");
        pop.setAttribute("aria-modal", "true");
        pop.setAttribute("aria-label", title);
        const close = document.createElement("button");
        close.className = "ld-popup-close";
        close.type = "button";
        close.textContent = "×";
        close.setAttribute("aria-label", "Close evidence review");
        pop.appendChild(close);
        const button = document.createElement("button");
        button.type = "button";
        button.className = "ld-control ld-reference-evidence";
        button.textContent = title;
        button.setAttribute("data-detail", id);
        button.setAttribute("aria-haspopup", "dialog");
        button.setAttribute("aria-controls", id);
        panel.replaceWith(button);
        pop.appendChild(panel);
        scrim.appendChild(pop);
      });
    }
    let pageFitFrame = 0;
    let pageFitInstalled = false;
    function openPageReader(trigger) {
      const page = visibleFixedPages()[0];
      const scrim = document.getElementById("popup-scrim");
      if (!page || !scrim) return;
      document.getElementById("ld-page-reader")?.remove();
      const reader = document.createElement("div");
      reader.id = "ld-page-reader";
      reader.className = "pop ld-page-reader";
      reader.setAttribute("role", "dialog");
      reader.setAttribute("aria-modal", "true");
      reader.setAttribute("aria-label", "Read current page");
      reader.innerHTML =
        '<button type="button" class="ld-popup-close" aria-label="Close page reader">×</button>';
      const nodes = Array.from(page.children);
      let readerId = 0;
      nodes.forEach((source) => {
        const copy = source.cloneNode(true);
        all("[hidden],.ld-unit-tools,.ld-why,[data-editor-only]", copy).forEach(
          (node) => {
            node.remove();
          },
        );
        [copy, ...all(".ld-unit[data-unit]", copy)].forEach((figure) => {
          const unit = unitState(figure.getAttribute("data-unit"));
          const variant = unit && selectedVariant(unit);
          if (
            variant &&
            variant.component &&
            !figure.querySelector("[data-editor-preserve-dom]")
          ) {
            const host = figure.querySelector(".ld-diagram");
            if (host)
              host.innerHTML = LD.render(variant.component, variant.params, {
                narrow: true,
                density: singleComposition() ? "compact" : "standard",
                ariaLabel: unit.claim,
              });
          }
        });
        const svgIds = new Map();
        all("[id]", copy)
          .filter((node) => node instanceof SVGElement)
          .forEach((node) => {
            const next = "ld-reader-svg-" + ++readerId;
            svgIds.set(node.id, next);
            node.id = next;
          });
        const rewriteSVGReference = (value) =>
          value.replace(
            /url\(\s*(['"]?)#([^)'"\s]+)\1\s*\)/g,
            (whole, quote, id) =>
              svgIds.has(id) ? "url(#" + svgIds.get(id) + ")" : whole,
          );
        [copy, ...all("*", copy)].forEach((node) => {
          if (
            node.matches(
              '.ld-composed-unit[data-kind="text"]:is([data-detail],[data-evidence])',
            )
          )
            all(":scope > .ld-variant > [data-variant-body]", node).forEach(
              (body) => {
                body.classList.add("ld-reader-popup-text");
              },
            );
          if (!(node instanceof SVGElement)) node.removeAttribute("id");
          if (node instanceof SVGElement) {
            Array.from(node.attributes).forEach((attribute) => {
              let value = rewriteSVGReference(attribute.value);
              if (
                ["href", "xlink:href"].includes(attribute.name) &&
                value.startsWith("#") &&
                svgIds.has(value.slice(1))
              )
                value = "#" + svgIds.get(value.slice(1));
              if (value !== attribute.value)
                node.setAttribute(attribute.name, value);
            });
            if (node.tagName.toLowerCase() === "style")
              node.textContent = rewriteSVGReference(node.textContent);
          }
          node.removeAttribute("contenteditable");
          node.removeAttribute("spellcheck");
          node.removeAttribute("tabindex");
          [
            "aria-controls",
            "aria-labelledby",
            "aria-describedby",
            "for",
          ].forEach((name) => {
            node.removeAttribute(name);
          });
          Array.from(node.attributes).forEach((attribute) => {
            if (
              attribute.name.startsWith("data-") &&
              !["data-detail", "data-evidence", "data-section-target"].includes(
                attribute.name,
              )
            )
              node.removeAttribute(attribute.name);
          });
          if (node.classList.contains("ld-unit"))
            node.classList.add("ld-reader-unit");
          node.classList.remove(
            "ld-unit",
            "ld-composed-unit",
            "ld-fixed-page",
            "ld-popup-trigger",
            "ld-selected",
            "ld-selection-mark",
          );
          if (!(node instanceof SVGElement)) node.removeAttribute("style");
        });
        all(
          "input,textarea,select,button:not([data-detail]):not([data-evidence]):not([data-section-target])",
          copy,
        ).forEach((control) => {
          const text = document.createElement("p");
          text.textContent = control.matches("input,textarea,select")
            ? (control.getAttribute("aria-label") ||
                control.getAttribute("placeholder") ||
                "Response") +
              ": " +
              (control.value || "—")
            : control.textContent +
              (control.getAttribute("aria-pressed") === "true"
                ? " — selected"
                : "");
          control.replaceWith(text);
        });
        copy.className = "ld-reader-section";
        reader.appendChild(copy);
      });
      scrim.appendChild(reader);
      installSectionLinks();
      bindPopupDOM();
      openPopup(reader.id, trigger);
      all(".ld-diagram svg", reader).forEach((svg) => {
        const frameWidth = svg.viewBox.baseVal.width || 400;
        const fontSizes = all("text", svg)
          .map((text) => parseFloat(getComputedStyle(text).fontSize))
          .filter((size) => size > 0);
        const smallest = fontSizes.length ? Math.min(...fontSizes) : 13;
        const available = svg.parentElement.clientWidth;
        // Fit ordinary narrow diagrams completely. Pan only when the actual
        // component would otherwise put a label below 11 screen pixels.
        svg.style.width =
          Math.max(available, (frameWidth * 11) / smallest) + "px";
        svg.style.height = "auto";
        svg.style.maxHeight = "none";
      });
      updatePopupScrollHint(reader);
    }
    function installPageReader() {
      let button = document.getElementById("ld-read-page");
      if (!button) {
        button = document.createElement("button");
        button.id = "ld-read-page";
        button.className = "ld-control ld-read-page";
        button.type = "button";
        button.innerHTML =
          '<svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true" focusable="false"><path d="M12 5.5C9 3.5 5.5 3.5 2 4.5v14c3.5-1 7-1 10 1 3-2 6.5-2 10-1v-14c-3.5-1-7-1-10 1Zm0 0v14" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>';
        button.setAttribute("aria-label", "Read page");
        button.title = "Read page — larger text and diagram details";
        button.setAttribute("aria-haspopup", "dialog");
        button.hidden = true;
        document.body.appendChild(button);
      }
      if (!button.__legalDesignReaderBound) {
        button.__legalDesignReaderBound = true;
        button.addEventListener("click", () => openPageReader(button));
      }
    }
    function visibleFixedPages() {
      return all(".ld-fixed-page").filter(
        (page) =>
          !page.closest("[hidden]") &&
          getComputedStyle(page).display !== "none",
      );
    }
    function pageOverflow(page, diagnostics) {
      const bounds = page.getBoundingClientRect();
      const tolerance = Math.max(1, pageScaleFor(page) * 2);
      const outside = (box) =>
        box.width > 0 &&
        box.height > 0 &&
        (box.left < bounds.left - tolerance ||
          box.right > bounds.right + tolerance ||
          box.top < bounds.top - tolerance ||
          box.bottom > bounds.bottom + tolerance);
      const concealedByDisclosure = (node) => {
        let closed = node.parentElement?.closest("details:not([open])");
        while (closed && page.contains(closed)) {
          if (!closed.querySelector(":scope > summary")?.contains(node))
            return true;
          closed = closed.parentElement?.closest("details:not([open])");
        }
        return false;
      };
      const candidates = all("*", page).filter(
        (node) =>
          !node.closest("[hidden],[data-editor-only],.ld-unit-tools") &&
          !concealedByDisclosure(node) &&
          !node.matches("script,style") &&
          node.getClientRects().length,
      );
      if (
        candidates.some((node) => {
          const box = node.getBoundingClientRect();
          const style = getComputedStyle(node);
          const clipsContent =
            !(node instanceof SVGElement) &&
            ((/auto|scroll|hidden|clip/.test(style.overflowY) &&
              node.scrollHeight > node.clientHeight + 2) ||
              (/auto|scroll|hidden|clip/.test(style.overflowX) &&
                node.scrollWidth > node.clientWidth + 2));
          const invalid = outside(box) || clipsContent;
          if (invalid && diagnostics)
            diagnostics.push({
              page: page.id || page.getAttribute("data-composition-section"),
              tag: node.tagName,
              className: node.getAttribute("class"),
              kind: clipsContent ? "internal clipping" : "box outside frame",
              height: node.clientHeight,
              scrollHeight: node.scrollHeight,
              width: node.clientWidth,
              scrollWidth: node.scrollWidth,
              top: box.top - bounds.top,
              bottom: box.bottom - bounds.top,
            });
          return invalid;
        })
      )
        return true;
      // A fixed-height text box can have in-bounds edges while its ink spills
      // beyond the page. Check actual text geometry as well as container boxes.
      return candidates.some((node) =>
        Array.from(node.childNodes).some((child) => {
          if (child.nodeType !== Node.TEXT_NODE || !child.textContent.trim())
            return false;
          const range = document.createRange();
          range.selectNodeContents(child);
          const box = range.getBoundingClientRect();
          const invalid = outside(box);
          if (invalid && diagnostics)
            diagnostics.push({
              page: page.id || page.dataset.compositionSection,
              tag: node.tagName,
              className: node.getAttribute("class"),
              kind: "text ink outside frame",
              top: box.top - bounds.top,
              bottom: box.bottom - bounds.top,
            });
          return invalid;
        }),
      );
    }
    function validatePageFit(showNotice = true) {
      const invalid = visibleFixedPages().some((page) => pageOverflow(page));
      root.toggleAttribute("data-page-overflow", invalid);
      let notice = document.getElementById("ld-page-fit-error");
      if (invalid && showNotice && !notice) {
        notice = document.createElement("div");
        notice.id = "ld-page-fit-error";
        notice.className = "ld-page-fit-error";
        notice.setAttribute("data-editor-chrome", "");
        notice.setAttribute("role", "alert");
        notice.textContent =
          "This page has more content than the available window can hold. Move detail into a popup or split it into another page before exporting. Your content has not been removed.";
        document.body.appendChild(notice);
      }
      if (notice && !invalid && !notice.hasAttribute("data-export-fit-error"))
        notice.remove();
      return !invalid;
    }
    function validateExportPageFit(includeOtherApproaches) {
      const issues = [];
      const pages = fixedPageTargets().filter((page) => {
        const approach = page.closest("[data-approach]");
        return (
          includeOtherApproaches ||
          !approach ||
          approach.dataset.approach === currentApproach()
        );
      });
      const changed = new Map();
      const reveal = (node) => {
        if (!node || changed.has(node)) return;
        changed.set(node, { hidden: node.hidden, display: node.style.display });
        node.hidden = false;
        if (getComputedStyle(node).display === "none")
          node.style.display = "block";
      };
      let valid = true;
      try {
        for (const page of pages) {
          reveal(page.closest("[data-approach]"));
          reveal(page);
          // Hidden approach figures have no measurable width until revealed.
          // Keep authored SVG edits; only state-driven figures are rendered.
          all('.ld-unit[data-kind="figure"]', page).forEach((section) => {
            const unit = unitState(section.getAttribute("data-unit"));
            if (unit) renderFigure(section, unit);
          });
          if (pageOverflow(page, issues)) valid = false;
          // A collapsed dashboard must not conceal a group that cannot fit.
          const groups = all("details.ld-overview-group", page);
          const openStates = groups.map((group) => group.open);
          try {
            for (const active of groups) {
              groups.forEach((group) => {
                group.open = group === active;
              });
              if (pageOverflow(page, issues)) valid = false;
            }
          } finally {
            groups.forEach((group, index) => {
              group.open = openStates[index];
            });
          }
        }
      } finally {
        changed.forEach((prior, node) => {
          node.hidden = prior.hidden;
          node.style.display = prior.display;
          if (!node.getAttribute("style")) node.removeAttribute("style");
        });
      }
      LD.lastPageFitIssues = issues;
      if (!valid) {
        let notice = document.getElementById("ld-page-fit-error");
        if (!notice) {
          notice = document.createElement("div");
          notice.id = "ld-page-fit-error";
          notice.className = "ld-page-fit-error";
          notice.setAttribute("data-editor-chrome", "");
          notice.setAttribute("role", "alert");
          document.body.appendChild(notice);
        }
        notice.textContent =
          "An output page exceeds its available window. Review every page and move detail into a popup or another page before exporting. Nothing has been deleted.";
        notice.setAttribute("data-export-fit-error", "");
      } else {
        const notice = document.getElementById("ld-page-fit-error");
        if (notice) notice.remove();
      }
      return valid;
    }
    function fitFixedPages() {
      pageFitFrame = 0;
      if (!root.hasAttribute("data-fixed-pages")) return;
      const viewport = layoutViewport();
      const bar = document.querySelector(".ld-bar");
      const approach = document.getElementById("ld-page-approach");
      const toolbarBottom = bar
        ? Math.max(0, bar.getBoundingClientRect().bottom)
        : 0;
      const approachHeight =
        approach && !approach.hidden ? approach.offsetHeight + 10 : 0;
      const rail = document.querySelector("nav.rail");
      const railRight =
        rail && rail.getClientRects().length
          ? rail.getBoundingClientRect().right + 12
          : 0;
      const leftGutter = root.hasAttribute("data-has-slide-index")
        ? viewport.width <= 760
          ? 68
          : 214
        : 12;
      const stable =
        root.hasAttribute("data-composed-shell") && singleComposition();
      root.toggleAttribute("data-stable-type", stable);
      const availableWidth = Math.max(
        1,
        viewport.width - Math.max(leftGutter, railRight) - 12,
      );
      // Desktop type is a reading size, not a percentage of the window. Limit
      // the combined rail/page measure; extra width becomes outer margin.
      const width =
        stable && viewport.width > 760
          ? Math.min(availableWidth, 1440)
          : availableWidth;
      const shellOffset = (availableWidth - width) / 2;
      const pageLeftGutter = Math.max(leftGutter, railRight) + shellOffset;
      root.style.setProperty("--ld-index-left", shellOffset + "px");
      const resultTop = toolbarBottom + 10 + approachHeight;
      root.style.setProperty("--ld-result-top", resultTop + "px");
      const result = document.querySelector(".ld-save-banner");
      const resultHeight =
        result && result.getClientRects().length
          ? result.getBoundingClientRect().height + 10
          : 0;
      const top = resultTop + resultHeight;
      const reader = document.getElementById("ld-read-page");
      // The book reader is always available, not a substitute for missing
      // content. Its reserved corner belongs to chrome, not the page itself.
      if (reader) reader.hidden = false;
      const readerReserve = stable && viewport.width > 760 ? 0 : 52;
      const height = Math.max(1, viewport.height - top - 12 - readerReserve);
      let scale = Math.min(width / 1200, height / 900, 1);
      if (stable && viewport.width > 760) scale = 1;
      const baselineScale = scale;
      // On short desktop windows, a sparse page need not become a thumbnail
      // simply because the planning reference is 900px tall. Try a readable
      // coordinate scale against actual content, leaving the approved roomier
      // layouts and phone overview unchanged. Never crop to claim a fit.
      // Authored reference pages have pinned footers and their own spacing;
      // preserve that approved coordinate scale. This content-fit pass is for
      // the flow-layout composer, whose children participate in natural flow.
      if (
        root.hasAttribute("data-composed-shell") &&
        !stable &&
        viewport.width > 760 &&
        scale < 0.8
      ) {
        const candidate = Math.min(width / 1200, 1);
        for (let trial = candidate; trial > baselineScale; trial -= 0.02) {
          root.style.setProperty("--ld-page-scale", String(trial));
          root.style.setProperty("--ld-page-width", width / trial + "px");
          root.style.setProperty("--ld-page-height", height / trial + "px");
          const changed = new Map();
          const reveal = (node) => {
            if (!node || changed.has(node)) return;
            changed.set(node, {
              hidden: node.hidden,
              display: node.style.display,
            });
            node.hidden = false;
            if (getComputedStyle(node).display === "none")
              node.style.display = "block";
          };
          let fits = true;
          try {
            for (const page of fixedPageTargets()) {
              reveal(page.closest("[data-approach]"));
              reveal(page);
              if (pageOverflow(page)) {
                fits = false;
                break;
              }
            }
          } finally {
            changed.forEach((prior, node) => {
              node.hidden = prior.hidden;
              node.style.display = prior.display;
            });
          }
          if (fits) {
            scale = trial;
            break;
          }
        }
      }
      root.style.setProperty("--ld-page-scale", String(scale));
      // Keep one uniform coordinate scale for persisted edits, but let each
      // dimension fill the window independently. 1200×900 remains a design
      // reference, never a letterboxed aspect-ratio constraint.
      root.style.setProperty("--ld-page-width", width / scale + "px");
      root.style.setProperty("--ld-page-height", height / scale + "px");
      root.style.setProperty("--ld-page-left", pageLeftGutter + "px");
      root.style.setProperty("--ld-page-top", top + "px");
      root.setAttribute("data-page-layout", "adaptive");
      root.style.setProperty("--ld-approach-top", toolbarBottom + 6 + "px");
      validatePageFit();
      alignSlideIndex();
      // Saved/client SVG is kept verbatim rather than rerendered. In Chromium,
      // a changed ancestor scale can leave its glyph paint transform stale even
      // when getBBox is correct. Invalidate that paint after layout settles,
      // using an identity transform and restoring every authored attribute.
      all(".ld-fixed-page .ld-diagram svg text").forEach((label) => {
        const original = label.getAttribute("transform");
        label.setAttribute("transform", (original || "") + " translate(0 0)");
        label.getBoundingClientRect();
        if (original === null) label.removeAttribute("transform");
        else label.setAttribute("transform", original);
      });
      if (editing) renderSelection();
    }
    function schedulePageFit() {
      if (!pageFitFrame) pageFitFrame = requestAnimationFrame(fitFixedPages);
    }
    function alignSlideIndex() {
      const nav = document.getElementById("ld-form-navigation");
      if (!nav || !root.hasAttribute("data-composed-shell")) return;
      const viewport = layoutViewport();
      if (viewport.width <= 760) {
        nav.style.removeProperty("height");
        nav.style.removeProperty("--ld-index-top");
        return;
      }
      const pages = visibleFixedPages();
      const bodies = pages.flatMap((page) => all(".ld-composed-grid", page));
      if (!bodies.length) return;
      const top = Math.min(
        ...bodies.map((node) => node.getBoundingClientRect().top),
      );
      const bottom = Math.max(
        ...bodies.map((node) => node.getBoundingClientRect().bottom),
      );
      // Align the rail to the actual explanation, including its scope footer,
      // not to an empty viewport-sized page box. Long indices scroll inside it.
      nav.style.setProperty("--ld-index-top", top + "px");
      nav.style.height =
        Math.max(44, Math.min(bottom, viewport.height - 12) - top) + "px";
    }
    function installFixedPages() {
      paginateReferenceOverview();
      referenceEvidenceDetails();
      const targets = fixedPageTargets();
      if (!targets.length) return;
      root.setAttribute("data-fixed-pages", "4:3");
      installPageReader();
      all(".ld-fixed-page").forEach((page) => {
        if (!targets.includes(page)) page.classList.remove("ld-fixed-page");
      });
      targets.forEach((page) => {
        page.classList.add("ld-fixed-page");
        if (!page.querySelector("h1,h2")) {
          const heading = document.createElement("h1");
          heading.className = "ld-page-heading";
          heading.setAttribute("data-editable", "");
          heading.setAttribute(
            "data-placeholder",
            "[Title for the subjects covered on this page.]",
          );
          heading.textContent =
            page.getAttribute("aria-label") ||
            state.brief?.title ||
            "Supporting details";
          page.prepend(heading);
        }
      });
      if (!pageFitInstalled) {
        pageFitInstalled = true;
        onLayoutResize(schedulePageFit);
        const bar = document.querySelector(".ld-bar");
        if (bar && typeof ResizeObserver !== "undefined")
          new ResizeObserver(schedulePageFit).observe(bar);
        new MutationObserver((records) => {
          if (
            records.some(
              (record) =>
                !record.target.closest ||
                !record.target.closest(
                  "#ld-selection-box,#ld-editor-layer,#ld-page-fit-error,#ld-page-reader",
                ),
            )
          )
            schedulePageFit();
        }).observe(document.body, {
          subtree: true,
          childList: true,
          characterData: true,
        });
        document.addEventListener("toggle", schedulePageFit, true);
        document.fonts && document.fonts.ready.then(schedulePageFit);
      }
      // Resolve the viewport transform before renderAll creates SVG text.
      // Painting text first at the reference scale then changing its ancestor
      // scale can leave Chromium's glyph paint cache at the old coordinates.
      // Geometry APIs still report correct boxes, masking the error until hover.
      if (pageFitFrame) cancelAnimationFrame(pageFitFrame);
      fitFixedPages();
    }
    LD.checkPageFit = (options = {}) => ({
      valid: options.allPages ? validateExportPageFit(true) : validatePageFit(),
      ratio: "adaptive",
      authoringReference: "4:3",
      width: parseFloat(root.style.getPropertyValue("--ld-page-width")) || 1200,
      height:
        parseFloat(root.style.getPropertyValue("--ld-page-height")) || 900,
      visiblePages: visibleFixedPages().length,
    });
    function composedLocation(sectionCount) {
      const location = state.review && state.review.location;
      return Number.isInteger(location)
        ? Math.max(0, Math.min(sectionCount - 1, location))
        : 0;
    }
    function composedIndexItems(sections) {
      return sections.map((section, index) => {
        const heading = section.querySelector("h1,h2,h3");
        return {
          id: section.getAttribute("data-composition-section"),
          label:
            section.getAttribute("data-index-label") ||
            (heading && heading.textContent.trim()) ||
            section.getAttribute("aria-label") ||
            "Section " + (index + 1),
        };
      });
    }
    function composedIndexGroups() {
      const overview = state.overview;
      if (!overview?.groups?.length) return [];
      const targets = new Map(
        (overview.topics || []).map((topic) => [
          topic.unitId,
          topic.targetSectionId,
        ]),
      );
      return overview.groups.map((group) => ({
        label: group.label,
        sectionIds: group.topicUnitIds
          .map((id) => targets.get(id))
          .filter(Boolean),
      }));
    }
    function updateComposedForm() {
      installSectionLinks();
      installFixedPages();
      const sections = composedSections();
      if (sections.length < 2) return;
      const form = composedForm();
      const location = composedLocation(sections.length);
      sections.forEach((section, index) => {
        section.hidden = form !== "one-page" && index !== location;
      });
      // Hidden slide hosts have zero width. Resolve a newly visible figure
      // against its real page width so first navigation and resize agree.
      // renderFigure retains authored/edit-preserved and client SVG verbatim.
      sections
        .filter((section) => !section.hidden)
        .forEach((section) => {
          all("section.ld-unit[data-unit]", section).forEach((node) => {
            const unit = unitState(node.getAttribute("data-unit"));
            if (unit?.kind === "figure") renderFigure(node, unit);
          });
        });
      const nav = document.getElementById("ld-form-navigation");
      if (!nav) return;
      if (
        nav.__legalDesignIndexSignature !==
        JSON.stringify({
          form,
          items: composedIndexItems(sections),
          groups: composedIndexGroups(),
        })
      ) {
        installComposedForm();
        return;
      }
      if (form !== "one-page") {
        const status = nav.querySelector("[data-walkthrough-status]");
        const previous = nav.querySelector("[data-walkthrough-previous]");
        const next = nav.querySelector("[data-walkthrough-next]");
        if (status) status.textContent = location + 1 + " / " + sections.length;
        if (previous) previous.disabled = location === 0;
        if (next) next.disabled = location === sections.length - 1;
      }
      all("[data-report-section]", nav).forEach((button) => {
        button.setAttribute(
          "aria-current",
          Number(button.dataset.reportSection) === location ? "true" : "false",
        );
      });
      // Navigation, not repaint, reveals the current subject. A reader may
      // still close that group or inspect another without it snapping back.
      if (nav.__legalDesignGroupLocation !== location) {
        all(".ld-index-group", nav).forEach((group) => {
          group.open = Boolean(group.querySelector('[aria-current="true"]'));
        });
        nav.__legalDesignGroupLocation = location;
      }
    }
    let sectionLinksBound = false;
    function installSectionLinks() {
      installOverviewGroups();
      all("[data-section-target]").forEach((node) => {
        node.setAttribute("role", "link");
        node.setAttribute("tabindex", "0");
      });
      if (sectionLinksBound) return;
      sectionLinksBound = true;
      const activate = (event) => {
        const target = event.target.closest("[data-section-target]");
        if (!target || editing) return;
        if (event.type === "keydown" && !["Enter", " "].includes(event.key))
          return;
        const sections = composedSections();
        const index = sections.findIndex(
          (section) =>
            section.dataset.compositionSection === target.dataset.sectionTarget,
        );
        if (index < 0) return;
        event.preventDefault();
        const fromReader = Boolean(target.closest("#ld-page-reader"));
        if (activePopup()) closePopup();
        setComposedLocation(index);
        if (fromReader) {
          openPageReader(document.getElementById("ld-read-page"));
          return;
        }
        const heading = sections[index].querySelector("h1,h2,h3");
        if (heading) {
          heading.setAttribute("tabindex", "-1");
          heading.focus({ preventScroll: true });
        }
      };
      document.addEventListener("click", activate);
      document.addEventListener("keydown", activate);
    }
    let overviewGroupsBound = false;
    function installOverviewGroups() {
      if (overviewGroupsBound) return;
      overviewGroupsBound = true;
      // Native keyboard activation also emits click. Apply the complete
      // one-open transition synchronously: a delayed toggle from a freshly
      // cloned reader must not overrule a newer user choice.
      document.addEventListener("click", (event) => {
        const summary = event.target.closest(".ld-overview-group > summary");
        if (!summary) return;
        const group = summary.parentElement;
        const container = group.closest(".ld-overview-groups");
        if (!container) return;
        event.preventDefault();
        const opening = !group.open;
        if (opening)
          all(":scope > details.ld-overview-group", container).forEach(
            (peer) => {
              if (peer !== group) peer.open = false;
            },
          );
        group.open = opening;
      });
      document.addEventListener(
        "toggle",
        (event) => {
          const group = event.target;
          if (!group.matches?.("details.ld-overview-group")) return;
          const container = group.closest(".ld-overview-groups");
          if (!container) return;
          if (!container.closest("#ld-page-reader")) storeEditorDOM();
          schedulePageFit();
        },
        true,
      );
    }
    function setComposedLocation(index, options) {
      const sections = composedSections();
      if (!sections.length) return;
      const next = Math.max(0, Math.min(sections.length - 1, index));
      if (!state.review) state.review = {};
      state.review.location = next;
      state.savedAt = new Date().toISOString();
      mirror();
      updateComposedForm();
      storeEditorDOM();
      schedulePageFit();
    }
    function installComposedForm() {
      installLegacySlideIndex();
      const sections = composedSections();
      const form = composedForm();
      if (
        sections.length < 2 ||
        !["slide-brief", "walkthrough", "report"].includes(form)
      ) {
        if (root.hasAttribute("data-composed-shell")) {
          const stale = document.getElementById("ld-form-navigation");
          if (stale) stale.remove();
          root.removeAttribute("data-has-slide-index");
        }
        return;
      }
      const main = document.getElementById("legaldesign-composed-root");
      let nav = document.getElementById("ld-form-navigation");
      const items = composedIndexItems(sections);
      const groups = composedIndexGroups();
      const signature = JSON.stringify({ form, items, groups });
      // Exported/restored navigation is presentation only. Rebuild it from the
      // active approach so a reset template cannot retain another page's index.
      if (nav && nav.__legalDesignIndexSignature !== signature) {
        nav.remove();
        nav = null;
      }
      if (!nav) {
        nav = document.createElement("nav");
        nav.id = "ld-form-navigation";
        nav.className = "ld-form-nav ld-slide-index";
        nav.setAttribute(
          "aria-label",
          form === "report" ? "Report sections" : "Slide navigation",
        );
        nav.innerHTML =
          '<button class="ld-control ld-index-toggle" type="button" data-index-toggle aria-controls="ld-index-list" aria-expanded="true">Contents</button>' +
          '<div id="ld-index-list" data-index-list></div>';
        const list = nav.querySelector("[data-index-list]");
        const makeEntry = (item, index) => {
          const button = document.createElement("button");
          button.className = "ld-control";
          button.type = "button";
          button.setAttribute("data-report-section", String(index));
          const number = document.createElement("span");
          number.className = "ld-index-number";
          number.setAttribute("aria-hidden", "true");
          number.textContent = String(index + 1);
          const label = document.createElement("span");
          label.className = "ld-index-label";
          label.textContent = item.label;
          button.append(number, label);
          return button;
        };
        const groupedIds = new Set(groups.flatMap((group) => group.sectionIds));
        items.forEach((item, index) => {
          if (!groupedIds.has(item.id))
            list.appendChild(makeEntry(item, index));
        });
        groups.forEach((group) => {
          const details = document.createElement("details");
          details.className = "ld-index-group";
          const summary = document.createElement("summary");
          summary.textContent = group.label;
          details.appendChild(summary);
          const entries = document.createElement("div");
          entries.className = "ld-index-group-items";
          group.sectionIds.forEach((id) => {
            const index = items.findIndex((item) => item.id === id);
            if (index >= 0) entries.appendChild(makeEntry(items[index], index));
          });
          details.appendChild(entries);
          summary.addEventListener("click", (event) => {
            event.preventDefault();
            const opening = !details.open;
            all(".ld-index-group", list).forEach((peer) => {
              peer.open = false;
            });
            details.open = opening;
          });
          list.appendChild(details);
        });
        if (form !== "one-page") {
          const pager = document.createElement("div");
          pager.className = "ld-index-pager";
          pager.innerHTML =
            '<button class="ld-control" type="button" data-walkthrough-previous>Previous</button>' +
            '<span data-walkthrough-status aria-live="polite"></span>' +
            '<button class="ld-control" type="button" data-walkthrough-next>Next</button>';
          (singleComposition() ? nav : list).appendChild(pager);
        }
        main.insertBefore(nav, main.firstChild);
      }
      nav.__legalDesignIndexSignature = signature;
      installSlideIndexToggle(nav);
      if (!nav.__legalDesignFormBound) {
        nav.__legalDesignFormBound = true;
        const previous = nav.querySelector("[data-walkthrough-previous]");
        const next = nav.querySelector("[data-walkthrough-next]");
        if (previous)
          previous.addEventListener("click", () => {
            setComposedLocation(composedLocation(sections.length) - 1);
          });
        if (next)
          next.addEventListener("click", () => {
            setComposedLocation(composedLocation(sections.length) + 1);
          });
        all("[data-report-section]", nav).forEach((button) => {
          button.addEventListener("click", () => {
            setComposedLocation(
              Number(button.getAttribute("data-report-section")),
              {
                scroll: form === "report",
              },
            );
          });
        });
      }
      updateComposedForm();
    }

    function installSlideIndexToggle(nav) {
      root.setAttribute("data-has-slide-index", "true");
      const toggle = nav.querySelector("[data-index-toggle]");
      const list = nav.querySelector("[data-index-list]");
      if (!toggle || !list || nav.__legalDesignIndexBound) return;
      nav.__legalDesignIndexBound = true;
      const phone = window.matchMedia("(max-width: 760px)");
      const setExpanded = (expanded) => {
        nav.setAttribute("data-index-expanded", expanded ? "true" : "false");
        toggle.setAttribute("aria-expanded", expanded ? "true" : "false");
        toggle.textContent = expanded ? "Contents" : "☰";
        toggle.setAttribute(
          "aria-label",
          expanded ? "Collapse contents" : "Open contents",
        );
        list.hidden = !expanded;
      };
      setExpanded(!phone.matches);
      toggle.addEventListener("click", () => {
        setExpanded(toggle.getAttribute("aria-expanded") !== "true");
      });
      nav.addEventListener("click", (event) => {
        if (phone.matches && event.target.closest("[data-report-section]"))
          setExpanded(false);
      });
      phone.addEventListener("change", () => setExpanded(!phone.matches));
      const bar = document.querySelector(".ld-bar");
      if (bar && typeof ResizeObserver !== "undefined") {
        const position = () =>
          nav.style.setProperty(
            "--ld-index-top",
            Math.ceil(bar.getBoundingClientRect().height + 16) + "px",
          );
        position();
        const observer = new ResizeObserver(position);
        observer.observe(bar);
      }
    }

    function installLegacySlideIndex() {
      if (root.hasAttribute("data-composed-shell")) return;
      const slides = all("section.sb-slide[data-frame]");
      const stage = document.getElementById("slide-stage");
      if (slides.length < 2 || !stage) return;
      let nav = document.getElementById("ld-legacy-slide-index");
      if (!nav) {
        nav = document.createElement("nav");
        nav.id = "ld-legacy-slide-index";
        nav.className = "ld-slide-index";
        nav.setAttribute("aria-label", "Slide navigation");
        nav.innerHTML =
          '<button class="ld-control ld-index-toggle" type="button" data-index-toggle aria-controls="ld-legacy-index-list" aria-expanded="true">Contents</button><div id="ld-legacy-index-list" data-index-list></div>';
        const list = nav.querySelector("[data-index-list]");
        slides.forEach((slide, index) => {
          const button = document.createElement("button");
          button.type = "button";
          button.className = "ld-control";
          button.setAttribute("data-report-section", String(index));
          list.appendChild(button);
        });
        const pager = document.querySelector(".sb-navigation");
        if (pager) list.appendChild(pager);
        stage.before(nav);
      }
      installSlideIndexToggle(nav);
      if (nav.__legalDesignLegacyBound) return;
      nav.__legalDesignLegacyBound = true;
      const refresh = () => {
        all("[data-report-section]", nav).forEach((button, index) => {
          const heading = slides[index].querySelector(
            ".ld-variant:not([hidden]) h1,h2,h3",
          );
          button.textContent =
            (heading && heading.textContent.trim()) || "Slide " + (index + 1);
          button.setAttribute(
            "aria-current",
            slides[index].classList.contains("is-current") ? "true" : "false",
          );
        });
      };
      nav.addEventListener("click", (event) => {
        const button = event.target.closest("[data-report-section]");
        if (!button) return;
        const frame = Number(button.getAttribute("data-report-section")) + 1;
        if (window.LegalDesignWalkthrough)
          window.LegalDesignWalkthrough.showFrame(frame, true);
        else {
          const original = document.querySelector(
            '[data-frame-button="' + frame + '"]',
          );
          if (original) original.click();
          else {
            slides.forEach((slide, index) => {
              slide.hidden = index !== frame - 1;
              slide.classList.toggle("is-current", index === frame - 1);
            });
            if (!state.review) state.review = {};
            state.review.location = frame - 1;
            mirror();
            schedulePageFit();
          }
        }
        refresh();
      });
      const observer = new MutationObserver(refresh);
      observer.observe(stage, {
        attributes: true,
        attributeFilter: ["class", "hidden"],
        childList: true,
        characterData: true,
        subtree: true,
      });
      refresh();
    }

    function syncUnitEdit(section) {
      if (!section || !section.isConnected) return;
      const id = section.getAttribute("data-unit");
      const unit = unitState(id);
      if (!unit || unit.kind === "figure") return;
      if (!unit.edits) unit.edits = {};
      all(".ld-variant[data-variant]", section).forEach((variant) => {
        const body = variant.querySelector("[data-variant-body]");
        if (body)
          unit.edits[variant.getAttribute("data-variant")] = body.innerHTML;
      });
    }
    function syncEvidenceEdit(pop) {
      if (!pop || !pop.isConnected) return;
      const id = pop.getAttribute("data-evidence-id") || pop.id;
      const item = state.evidence && state.evidence[id];
      if (!item) return;
      all("[data-evidence-field]", pop).forEach((node) => {
        const field = node.getAttribute("data-evidence-field");
        const value = node.textContent.trim();
        if (!value) return;
        if (["cite", "locator", "detail"].includes(field)) item[field] = value;
        else if (field === "popup.title" && item.popup)
          item.popup.title = value;
        else if (field === "popup.lede" && item.popup) item.popup.lede = value;
        else {
          const match = /^popup\.sections\.(\d+)\.(heading|body)$/.exec(field);
          const section =
            match && item.popup && Array.isArray(item.popup.sections)
              ? item.popup.sections[Number(match[1])]
              : null;
          if (!section) return;
          section[match[2]] = value;
        }
        if (field === "detail") item.excerpt = value;
        if (field === "locator")
          item.provenance = (item.sourceId || "source") + " · " + value;
      });
    }
    function syncEditorDOMToState(nodes) {
      let sections = [];
      let popups = [];
      if (nodes && nodes.length) {
        nodes.forEach((node) => {
          const section =
            node && node.closest && node.closest("section.ld-unit[data-unit]");
          if (section && !sections.includes(section)) sections.push(section);
          const popup =
            node && node.closest && node.closest(".pop[data-evidence-id]");
          if (popup && !popups.includes(popup)) popups.push(popup);
        });
      } else {
        sections = all("section.ld-unit[data-unit]");
        popups = all(".pop[data-evidence-id]");
      }
      sections.forEach(syncUnitEdit);
      popups.forEach(syncEvidenceEdit);
    }
    function commitEditorDOM(nodes) {
      (nodes || []).forEach((node) => {
        if (!node || !node.closest) return;
        const diagram = node.closest(".ld-diagram");
        const section = node.closest("section.ld-unit[data-unit]");
        if (diagram) diagram.setAttribute("data-editor-preserve-dom", "true");
        else if (
          section &&
          unitState(section.getAttribute("data-unit")) &&
          unitState(section.getAttribute("data-unit")).kind === "figure"
        )
          all(".ld-diagram", section).forEach((host) => {
            host.setAttribute("data-editor-preserve-dom", "true");
          });
      });
      syncEditorDOMToState(nodes);
      state.savedAt = new Date().toISOString();
      mirror();
      storeEditorDOM();
      renderSelection();
      updateEditorButtons();
    }

    function bindUnits() {
      all("section.ld-unit[data-unit]").forEach((section) => {
        const id = section.getAttribute("data-unit");
        const ab = section.querySelector(".ld-ab");
        if (ab && !ab.__legalDesignUnitBound) {
          ab.__legalDesignUnitBound = true;
          ab.addEventListener("keydown", (event) => {
            if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
            event.preventDefault();
            event.stopPropagation();
            setVariant(id, event.key === "ArrowLeft" ? "a" : "b");
          });
          all("[data-select-variant]", ab).forEach((button) => {
            if (button.__legalDesignUnitBound) return;
            button.__legalDesignUnitBound = true;
            button.addEventListener("click", () => {
              setVariant(id, button.getAttribute("data-select-variant"));
            });
          });
        }
        const whyButton = section.querySelector(".ld-why-toggle");
        const why = section.querySelector(".ld-why");
        if (whyButton && why && !whyButton.__legalDesignUnitBound) {
          whyButton.__legalDesignUnitBound = true;
          whyButton.addEventListener("click", () => {
            const open = why.hidden;
            why.hidden = !open;
            whyButton.setAttribute("aria-expanded", open ? "true" : "false");
          });
        }
        all("[data-editable]", section).forEach((node) => {
          if (node.__legalDesignUnitBound) return;
          node.__legalDesignUnitBound = true;
          node.addEventListener("blur", () => {
            if (!node.isConnected || !node.hasAttribute("contenteditable"))
              return;
            node.removeAttribute("contenteditable");
            node.removeAttribute("spellcheck");
            textUndoArmed = false;
            commitEditorDOM([node]);
          });
        });
      });
    }

    function renderDecisions() {
      all('[data-kind="decision"][data-unit]').forEach((unit) => {
        const id = unit.getAttribute("data-unit");
        const value =
          state.review && state.review.decisions
            ? state.review.decisions[id]
            : null;
        const choice =
          value && typeof value === "object" && !Array.isArray(value)
            ? value.choice
            : value;
        const choices =
          value && typeof value === "object" && !Array.isArray(value)
            ? value.choices
            : value;
        all("[data-decision-option]", unit).forEach((button) => {
          const selected = unit.hasAttribute("data-multi")
            ? Array.isArray(choices) && choices.includes(button.value)
            : choice === button.value;
          button.setAttribute("aria-pressed", selected ? "true" : "false");
        });
        all("[data-decision-custom],[data-decision-note]", unit).forEach(
          (input) => {
            const key = input.hasAttribute("data-decision-custom")
              ? "custom"
              : "note";
            const next =
              value && typeof value === "object" && !Array.isArray(value)
                ? value[key] || ""
                : "";
            if (document.activeElement !== input) input.value = next;
          },
        );
        unit.toggleAttribute(
          "data-answered",
          Boolean(
            unit.hasAttribute("data-multi")
              ? (Array.isArray(choices) && choices.length) ||
                  (value && (value.custom || value.note))
              : choice || (value && (value.custom || value.note)),
          ),
        );
      });
    }
    function bindDecisions() {
      all('[data-kind="decision"][data-unit]').forEach((unit) => {
        const id = unit.getAttribute("data-unit");
        all("[data-decision-option]", unit).forEach((button) => {
          if (button.__legalDesignDecisionBound) return;
          button.__legalDesignDecisionBound = true;
          button.addEventListener("click", () => {
            change(() => {
              if (!state.review.decisions) state.review.decisions = {};
              if (unit.hasAttribute("data-multi")) {
                const current = state.review.decisions[id];
                const values = Array.isArray(current)
                  ? current
                  : current && Array.isArray(current.choices)
                    ? current.choices
                    : [];
                const at = values.indexOf(button.value);
                if (at >= 0) values.splice(at, 1);
                else values.push(button.value);
                if (
                  current &&
                  typeof current === "object" &&
                  !Array.isArray(current)
                )
                  current.choices = values;
                else state.review.decisions[id] = values;
              } else {
                const current = state.review.decisions[id];
                if (
                  current &&
                  typeof current === "object" &&
                  !Array.isArray(current)
                )
                  current.choice = button.value;
                else state.review.decisions[id] = button.value;
              }
            });
          });
        });
        all("[data-decision-custom],[data-decision-note]", unit).forEach(
          (input) => {
            if (input.__legalDesignDecisionBound) return;
            input.__legalDesignDecisionBound = true;
            input.addEventListener("change", () => {
              change(() => {
                if (!state.review.decisions) state.review.decisions = {};
                let current = state.review.decisions[id];
                if (
                  !current ||
                  typeof current !== "object" ||
                  Array.isArray(current)
                ) {
                  current = unit.hasAttribute("data-multi")
                    ? {
                        choices: Array.isArray(current)
                          ? current.slice()
                          : current
                            ? [current]
                            : [],
                      }
                    : { choice: current || null };
                }
                current[
                  input.hasAttribute("data-decision-custom") ? "custom" : "note"
                ] = input.value;
                state.review.decisions[id] = current;
              });
            });
          },
        );
      });
    }

    function popupFor(id) {
      const pop = document.getElementById(id);
      return pop && pop.matches("#popup-scrim .pop") ? pop : null;
    }
    function activePopup() {
      const scrim = document.getElementById("popup-scrim");
      if (!scrim || scrim.hidden) return null;
      return (
        all(".pop", scrim).find((pop) => !pop.hidden && visible(pop)) || null
      );
    }
    function popupFocusables(pop) {
      return all(
        'a[href],button,input:not([type="hidden"]),select,textarea,summary,[contenteditable="true"],[tabindex]',
        pop,
      ).filter(
        (node) =>
          node.tabIndex >= 0 &&
          !node.matches(':disabled,[aria-disabled="true"]') &&
          !node.closest('[hidden],[inert],[aria-hidden="true"]') &&
          visible(node),
      );
    }
    function focusPopupFallback(pop) {
      if (!pop.hasAttribute("tabindex")) {
        pop.setAttribute("tabindex", "-1");
        popupFallbackNodes.add(pop);
      }
      pop.focus();
    }
    function clearPopupFallback(pop) {
      if (!popupFallbackNodes.has(pop)) return;
      pop.removeAttribute("tabindex");
      popupFallbackNodes.delete(pop);
    }
    function trapPopupTab(event, pop) {
      const focusables = popupFocusables(pop);
      if (!focusables.length) {
        event.preventDefault();
        focusPopupFallback(pop);
        return;
      }
      const active = document.activeElement;
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      if (
        !focusables.includes(active) ||
        (event.shiftKey && active === first) ||
        (!event.shiftKey && active === last)
      ) {
        event.preventDefault();
        (event.shiftKey ? last : first).focus();
      }
    }
    function openPopup(id, source) {
      const scrim = document.getElementById("popup-scrim");
      const pop = popupFor(id);
      if (!scrim || !pop) return;
      const prior = activePopup();
      if (prior && prior !== pop && source && prior.contains(source)) {
        popupTrail.push({
          pop: prior,
          source,
          scrollTop: prior.scrollTop,
          returnFocus,
          returnFocusKey,
        });
      } else if (!prior) {
        popupTrail.length = 0;
      }
      rememberReturnFocus(source);
      all(".pop", scrim).forEach((item) => {
        clearPopupFallback(item);
        item.hidden = item !== pop;
      });
      scrim.hidden = false;
      pop.hidden = false;
      document.body.style.overflow = "hidden";
      const close = pop.querySelector(".ld-popup-close,.pop-close");
      const focusables = popupFocusables(pop);
      const initial =
        close && focusables.includes(close) ? close : focusables[0];
      if (initial) initial.focus();
      else focusPopupFallback(pop);
      updatePopupScrollHint(pop);
    }
    function closePopup() {
      const scrim = document.getElementById("popup-scrim");
      if (!scrim || scrim.hidden) return;
      const prior = popupTrail.pop();
      if (prior?.pop.isConnected) {
        all(".pop", scrim).forEach((item) => {
          item.hidden = item !== prior.pop;
          clearPopupFallback(item);
        });
        prior.pop.scrollTop = prior.scrollTop;
        returnFocus = prior.returnFocus;
        returnFocusKey = prior.returnFocusKey;
        if (prior.source.isConnected)
          prior.source.focus({ preventScroll: true });
        else focusPopupFallback(prior.pop);
        updatePopupScrollHint(prior.pop);
        return;
      }
      scrim.hidden = true;
      all(".pop", scrim).forEach((item) => {
        item.hidden = true;
        clearPopupFallback(item);
      });
      document.body.style.overflow = "";
      restoreReturnFocus();
    }
    function bindPopupDOM() {
      all("[data-evidence],[data-detail]").forEach((node) => {
        if (!node.matches("a,button,input,select,textarea,[tabindex]")) {
          node.tabIndex = 0;
          node.setAttribute("role", "button");
        }
      });
      all("#popup-scrim .pop").forEach((pop) => {
        if (pop.querySelector(".ld-popup-authoring"))
          popupAuthoringControls(pop);
        if (pop.__legalDesignPopupBound) return;
        pop.__legalDesignPopupBound = true;
        pop.addEventListener("scroll", () => {
          updatePopupScrollHint(pop);
        });
        all("[data-evidence-field][data-editable]", pop).forEach((node) => {
          if (node.__legalDesignEvidenceBound) return;
          node.__legalDesignEvidenceBound = true;
          node.addEventListener("blur", () => {
            if (!node.isConnected || !node.hasAttribute("contenteditable"))
              return;
            node.removeAttribute("contenteditable");
            node.removeAttribute("spellcheck");
            textUndoArmed = false;
            commitEditorDOM([node]);
          });
        });
      });
      all("#popup-scrim a[href]").forEach((link) => {
        try {
          const url = new URL(link.getAttribute("href"));
          if (url.protocol !== "http:" && url.protocol !== "https:")
            throw new Error("scheme");
        } catch (_) {
          link.setAttribute("href", "#");
        }
      });
    }
    function bindPopups() {
      bindPopupDOM();
      document.addEventListener("click", (event) => {
        if (suppressEditorClick) {
          suppressEditorClick = false;
          event.preventDefault();
          return;
        }
        const trigger = event.target.closest("[data-evidence],[data-detail]");
        if (editing && trigger && !trigger.closest(".pop")) return;
        const interactive = event.target.closest(
          "button,input,select,textarea,.ld-unit-tools",
        );
        if (trigger && interactive && interactive !== trigger) return;
        const editableTarget =
          editing && event.target.closest("[data-editable]");
        if (trigger && editableTarget && trigger.contains(editableTarget))
          return;
        if (trigger) {
          event.preventDefault();
          openPopup(
            trigger.getAttribute("data-evidence") ||
              trigger.getAttribute("data-detail"),
            trigger,
          );
          return;
        }
        if (
          event.target.closest(".ld-popup-close,.pop-close") ||
          event.target.id === "popup-scrim"
        ) {
          event.preventDefault();
          closePopup();
        }
      });
      document.addEventListener("keydown", (event) => {
        const pop = activePopup();
        if (pop && event.key === "Tab") {
          trapPopupTab(event, pop);
          return;
        }
        const detail =
          event.target.closest &&
          event.target.closest("[data-evidence],[data-detail]");
        const editableTarget =
          editing &&
          event.target.closest &&
          event.target.closest("[data-editable]");
        if (detail && editableTarget && detail.contains(editableTarget)) return;
        if (detail && (event.key === "Enter" || event.key === " ")) {
          event.preventDefault();
          openPopup(
            detail.getAttribute("data-evidence") ||
              detail.getAttribute("data-detail"),
            detail,
          );
        }
        if (pop && event.key === "Escape") {
          event.preventDefault();
          closePopup();
        }
      });
    }

    function updatePopupScrollHint(pop) {
      if (!pop) return;
      pop.toggleAttribute(
        "data-scroll-more",
        pop.scrollTop + pop.clientHeight < pop.scrollHeight - 1,
      );
    }

    function installAuthoringControls() {
      const tools = document.querySelector(".ld-editor-tools");
      if (!tools) return;
      for (const [id, label] of [
        ["editor-add-text", "Text box"],
        ["editor-popup", "Add popup"],
        ["editor-remove-popup", "Remove popup"],
      ]) {
        if (document.getElementById(id)) continue;
        const button = document.createElement("button");
        button.id = id;
        button.type = "button";
        button.className = "ld-tool";
        button.textContent = label;
        button.title = label;
        tools.appendChild(button);
      }
      for (const [kind, tokens] of [
        ["fill", FILL_TOKENS],
        ["text", TEXT_TOKENS],
      ]) {
        const select = document.getElementById(`editor-${kind}-token`);
        if (!select) continue;
        document.getElementById(`editor-${kind}-palette`)?.remove();
        select.hidden = true;
        const button = document.createElement("button");
        button.id = `editor-${kind}-palette`;
        button.type = "button";
        button.className = "ld-tool";
        button.textContent = kind === "fill" ? "Fill ▾" : "Text ▾";
        button.setAttribute(
          "aria-label",
          kind === "fill" ? "Fill color" : "Text color",
        );
        button.setAttribute("aria-haspopup", "dialog");
        button.setAttribute("aria-expanded", "false");
        select.after(button);
        button.addEventListener("click", () => {
          const existing = document.getElementById("ld-color-palette");
          const same = existing && existing.dataset.kind === kind;
          if (existing) existing.remove();
          all('[id$="-palette"].ld-tool').forEach((node) => {
            node.setAttribute("aria-expanded", "false");
          });
          if (same) return;
          const panel = document.createElement("div");
          panel.id = "ld-color-palette";
          panel.dataset.kind = kind;
          panel.setAttribute("data-editor-only", "");
          panel.setAttribute("role", "dialog");
          panel.setAttribute(
            "aria-label",
            kind === "fill" ? "Choose fill color" : "Choose text color",
          );
          const names = {
            card: "Card",
            "card-strong": "Raised card",
            tint: "Soft tint",
            bg: "Page",
            none: "No fill",
            ink: "Primary text",
            muted: "Secondary text",
            faint: "Quiet text",
            red: "Accent",
            "red-strong": "Strong accent",
          };
          const heading = document.createElement("strong");
          heading.textContent = kind === "fill" ? "Fill color" : "Text color";
          panel.appendChild(heading);
          const grid = document.createElement("div");
          grid.className = "ld-swatch-grid";
          const painted = selection.map((node) =>
            node.getAttribute(`data-${kind}-token`),
          );
          const currentToken =
            painted.length && painted.every((value) => value === painted[0])
              ? painted[0]
              : null;
          tokens.forEach((token) => {
            const swatch = document.createElement("button");
            swatch.type = "button";
            swatch.className = "ld-color-swatch";
            swatch.dataset.colorToken = token;
            swatch.setAttribute("aria-label", names[token]);
            swatch.setAttribute("aria-pressed", String(currentToken === token));
            swatch.title = names[token];
            swatch.style.background =
              token === "none" ? "transparent" : `var(--${token})`;
            if (token === "none") swatch.textContent = "∅";
            swatch.addEventListener("click", () => {
              applyToken(`data-${kind}-token`, token);
              panel.remove();
              button.setAttribute("aria-expanded", "false");
              button.focus();
            });
            grid.appendChild(swatch);
          });
          panel.appendChild(grid);
          const hint = document.createElement("small");
          hint.textContent = "House palette · adapts to light and dark";
          panel.appendChild(hint);
          document.body.appendChild(panel);
          const box = button.getBoundingClientRect();
          panel.style.top =
            Math.min(innerHeight - panel.offsetHeight - 8, box.bottom + 8) +
            "px";
          panel.style.left =
            Math.max(
              8,
              Math.min(innerWidth - panel.offsetWidth - 8, box.left),
            ) + "px";
          button.setAttribute("aria-expanded", "true");
          grid.querySelector("button").focus();
          panel.addEventListener("keydown", (event) => {
            if (event.key === "Escape") {
              event.stopPropagation();
              panel.remove();
              button.setAttribute("aria-expanded", "false");
              button.focus();
            }
          });
        });
      }
    }
    function newPopupId() {
      let n = 1;
      while (
        state.evidence["detail-added-" + n] ||
        document.getElementById("detail-added-" + n)
      )
        n++;
      return "detail-added-" + n;
    }
    function cloneAttachedPopups(copy) {
      const targets = all("[data-detail],[data-evidence]", copy);
      if (copy.matches("[data-detail],[data-evidence]")) targets.unshift(copy);
      const mapping = new Map();
      targets.forEach((target) => {
        const attr = target.hasAttribute("data-detail")
          ? "data-detail"
          : "data-evidence";
        const original = target.getAttribute(attr);
        const pop = popupFor(original);
        if (!pop) return;
        if (!mapping.has(original)) {
          const id = newPopupId();
          const duplicate = pop.cloneNode(true);
          duplicate.id = id;
          duplicate.setAttribute("data-evidence-id", id);
          duplicate.hidden = true;
          all("[id]", duplicate).forEach((node) => {
            node.removeAttribute("id");
          });
          duplicate.removeAttribute("aria-labelledby");
          duplicate.setAttribute(
            "aria-label",
            state.evidence[original]?.popup?.title || "Detail",
          );
          if (state.evidence[original])
            state.evidence[id] = clone(state.evidence[original]);
          document.getElementById("popup-scrim").appendChild(duplicate);
          mapping.set(original, id);
        }
        target.setAttribute(attr, mapping.get(original));
        target.setAttribute("aria-controls", mapping.get(original));
      });
    }
    function addTextBox() {
      editorCheckpoint();
      const selected = topSelection()[0];
      const scope =
        activePopup() ||
        (selected && selected.closest("section.ld-unit")) ||
        all("section.ld-unit").find(visible) ||
        document.querySelector("main");
      if (!scope) return;
      if (getComputedStyle(scope).position === "static")
        scope.style.position = "relative";
      const node = document.createElement("p");
      node.className = "ld-added-text";
      node.setAttribute("data-editable", "");
      node.setAttribute("data-editor-object", "text");
      node.setAttribute("data-placeholder", "[Text explaining this point.]");
      node.textContent = "Your text";
      Object.assign(node.style, {
        position: "absolute",
        left: "24px",
        top: "64px",
        width: "240px",
        margin: "0",
        zIndex: "4",
      });
      scope.appendChild(node);
      stampEditorOrigins(node);
      commitEditorDOM([node]);
      select([node]);
      editText(node);
    }
    function addPopupSection(pop) {
      const id = pop.getAttribute("data-evidence-id");
      const item = state.evidence[id];
      if (!item?.popup) return;
      const index = item.popup.sections.length;
      item.popup.sections.push({
        heading: "Section heading",
        body: "Explain this point.",
      });
      const section = document.createElement("section");
      section.className = "ld-popup-section";
      for (const [tag, field, text] of [
        ["h3", "heading", "Section heading"],
        ["p", "body", "Explain this point."],
      ]) {
        const node = document.createElement(tag);
        node.textContent = text;
        node.setAttribute("data-editable", "");
        node.setAttribute(
          "data-evidence-field",
          `popup.sections.${index}.${field}`,
        );
        node.setAttribute(
          "data-placeholder",
          field === "heading"
            ? "[Section heading.]"
            : "[Explanation of this point.]",
        );
        section.appendChild(node);
      }
      const controls = pop.querySelector(".ld-popup-authoring");
      pop.insertBefore(section, controls || null);
      bindPopupDOM();
      stampEditorOrigins(section);
      commitEditorDOM([section]);
    }
    function popupAuthoringControls(pop) {
      const existing = pop.querySelector(".ld-popup-authoring");
      if (existing?.__bound) return;
      existing?.remove();
      const controls = document.createElement("div");
      controls.className = "ld-popup-authoring";
      controls.setAttribute("data-editor-only", "");
      controls.__bound = true;
      const add = document.createElement("button");
      add.type = "button";
      add.className = "ld-tool";
      add.textContent = "Add section";
      add.addEventListener("click", () => {
        editorCheckpoint();
        addPopupSection(pop);
      });
      controls.appendChild(add);
      pop.appendChild(controls);
    }
    function editSelectedPopup() {
      const target = topSelection().length === 1 && topSelection()[0];
      if (!target) return;
      let id =
        target.getAttribute("data-detail") ||
        target.getAttribute("data-evidence");
      if (!id || !popupFor(id)) {
        editorCheckpoint();
        id = newPopupId();
        const title =
          (target.textContent || "Detail").trim().slice(0, 120) || "Detail";
        state.evidence[id] = {
          cite: "",
          locator: "",
          excerpt: "",
          link: null,
          status: "authored",
          popup: {
            type: "detail",
            title,
            lede: "Add the detail this element should explain.",
            sections: [],
          },
        };
        target.setAttribute("data-detail", id);
        target.setAttribute("aria-controls", id);
        target.setAttribute("aria-haspopup", "dialog");
        target.setAttribute("role", "button");
        target.setAttribute("tabindex", "0");
        if (target instanceof SVGElement) target.classList.add("ld-detail");
        const pop = document.createElement("article");
        pop.id = id;
        pop.className = "pop";
        pop.hidden = true;
        pop.setAttribute("role", "dialog");
        pop.setAttribute("aria-modal", "true");
        pop.setAttribute("aria-label", title);
        pop.setAttribute("data-evidence-id", id);
        const close = document.createElement("button");
        close.type = "button";
        close.className = "ld-popup-close";
        close.textContent = "×";
        close.setAttribute("aria-label", "Close");
        pop.appendChild(close);
        for (const [tag, field, value] of [
          ["h2", "title", title],
          ["p", "lede", state.evidence[id].popup.lede],
        ]) {
          const node = document.createElement(tag);
          node.textContent = value;
          node.setAttribute("data-editable", "");
          node.setAttribute("data-evidence-field", "popup." + field);
          if (field === "lede") node.className = "ld-popup-lede";
          pop.appendChild(node);
        }
        document.getElementById("popup-scrim").appendChild(pop);
        addPopupSection(pop);
        bindPopupDOM();
        commitEditorDOM([target, pop]);
      }
      const pop = popupFor(id);
      popupAuthoringControls(pop);
      stampEditorOrigins(pop);
      select([]);
      openPopup(id, target);
    }
    function removeSelectedPopup() {
      const target = topSelection().length === 1 && topSelection()[0];
      if (!target) return;
      editorCheckpoint();
      [
        "data-detail",
        "data-evidence",
        "aria-controls",
        "aria-haspopup",
      ].forEach((attr) => {
        target.removeAttribute(attr);
      });
      target.classList.remove("ld-detail");
      if (
        target.getAttribute("role") === "button" &&
        !target.matches("button")
      ) {
        target.removeAttribute("role");
        target.removeAttribute("tabindex");
      }
      // Keep the detached content recoverable through Undo and other references.
      commitEditorDOM([target]);
    }
    function editorTargets() {
      return all(EDITOR_OBJECTS).filter(visible);
    }
    function editorObjectTargets(scope) {
      return all(EDITOR_OBJECTS, scope || document).filter(
        (node) =>
          visible(node) &&
          !node.closest("[data-editor-only],.ld-slide-index") &&
          (!activePopup() || activePopup().contains(node)),
      );
    }
    function stampEditorOrigins(scope) {
      all(".ld-diagram", scope || document).forEach((host) => {
        all('svg [data-diagram-object],svg g[role="button"]', host).forEach(
          (node, index) => {
            if (!node.hasAttribute("data-editor-node-key"))
              node.setAttribute("data-editor-node-key", "node-" + (index + 1));
          },
        );
      });
      annotateDiagramLabels(scope || document);
      const selector = EDITOR_OBJECTS;
      const nodes = all(selector, scope || document);
      if (scope && scope.matches && scope.matches(selector))
        nodes.unshift(scope);
      nodes.forEach((node) => {
        if (node.closest("[data-editor-only]")) return;
        node.setAttribute("data-editor-unit", "1");
        if (!node.hasAttribute("data-editor-origin-style-stamped")) {
          node.setAttribute("data-editor-origin-style-stamped", "true");
          node.setAttribute(
            "data-editor-origin-style-present",
            node.hasAttribute("style") ? "true" : "false",
          );
          node.setAttribute(
            "data-editor-origin-style",
            node.getAttribute("style") || "",
          );
          ["fill-token", "text-token"].forEach((key) => {
            const source = "data-" + key;
            node.setAttribute(
              "data-editor-origin-" + key + "-present",
              node.hasAttribute(source) ? "true" : "false",
            );
            node.setAttribute(
              "data-editor-origin-" + key,
              node.getAttribute(source) || "",
            );
          });
        }
      });
    }
    function topSelection() {
      return selection.filter(
        (node) =>
          !selection.some((other) => other !== node && other.contains(node)),
      );
    }
    function boxFor(nodes) {
      const boxes = nodes
        .filter(visible)
        .map((node) => node.getBoundingClientRect());
      if (!boxes.length) return null;
      const left = Math.min.apply(
        null,
        boxes.map((box) => box.left),
      );
      const top = Math.min.apply(
        null,
        boxes.map((box) => box.top),
      );
      const right = Math.max.apply(
        null,
        boxes.map((box) => box.right),
      );
      const bottom = Math.max.apply(
        null,
        boxes.map((box) => box.bottom),
      );
      return {
        left: left,
        top: top,
        right: right,
        bottom: bottom,
        width: right - left,
        height: bottom - top,
      };
    }
    function makeEditorLayer() {
      if (document.getElementById("ld-editor-layer")) return;
      const layer = document.createElement("div");
      layer.id = "ld-editor-layer";
      layer.setAttribute("data-editor-only", "");
      const box = document.createElement("div");
      box.id = "ld-selection-box";
      ["nw", "n", "ne", "e", "se", "s", "sw", "w"].forEach((name) => {
        const handle = document.createElement("span");
        handle.className = "ld-handle";
        handle.setAttribute("data-handle", name);
        box.appendChild(handle);
      });
      const marquee = document.createElement("div");
      marquee.id = "ld-marquee";
      layer.appendChild(box);
      layer.appendChild(marquee);
      document.body.appendChild(layer);
    }
    function renderSelection() {
      all(".ld-selected").forEach((node) => {
        node.classList.remove("ld-selected");
      });
      selection.forEach((node) => {
        node.classList.add("ld-selected");
      });
      // Context controls normally sit above their object. A wrapped phone
      // toolbar can occupy that space, so move only the controls below it.
      // The authored object and page geometry remain untouched.
      const barBottom = Math.max(
        0,
        ...all(".ld-bar,#ld-page-approach,.ld-save-banner")
          .filter((node) => !node.hidden && node.getClientRects().length)
          .map((node) => node.getBoundingClientRect().bottom),
      );
      all(".ld-fixed-page .ld-unit-tools").forEach((tools) => {
        tools.style.removeProperty("--ld-context-offset");
        if (!editing || !tools.getClientRects().length) return;
        const offset = barBottom + 4 - tools.getBoundingClientRect().top;
        if (offset > 0)
          tools.style.setProperty("--ld-context-offset", offset + "px");
      });
      const control = document.getElementById("ld-selection-box");
      if (!control) return;
      const bounds = boxFor(selection);
      updateEditorButtons();
      control.toggleAttribute(
        "data-diagram-label-selection",
        selection.length === 1 &&
          selection[0].hasAttribute("data-diagram-label"),
      );
      if (!bounds || !editing) {
        control.style.display = "none";
        return;
      }
      control.style.display = "block";
      control.style.left = bounds.left + "px";
      control.style.top = bounds.top + "px";
      control.style.width = bounds.width + "px";
      control.style.height = bounds.height + "px";
      const close = activePopup()?.querySelector(".ld-popup-close,.pop-close");
      const closeBox = close && close.getBoundingClientRect();
      all(".ld-handle", control).forEach((handle) => {
        const box = handle.getBoundingClientRect();
        const overlapsClose =
          closeBox &&
          box.left < closeBox.right + 4 &&
          box.right > closeBox.left - 4 &&
          box.top < closeBox.bottom + 4 &&
          box.bottom > closeBox.top - 4;
        handle.style.visibility = overlapsClose ? "hidden" : "";
      });
      updateEditorButtons();
    }
    function select(nodes, additive) {
      if (!additive) selection = [];
      nodes.forEach((node) => {
        if (node && node.isConnected && !selection.includes(node))
          selection.push(node);
      });
      renderSelection();
    }
    function editorCheckpoint() {
      checkpoint();
    }
    function translate(node, x, y) {
      x = Math.round(x * 10) / 10;
      y = Math.round(y * 10) / 10;
      node.setAttribute("data-editor-x", String(x));
      node.setAttribute("data-editor-y", String(y));
      let base = node.getAttribute("data-editor-base-transform");
      if (base == null) {
        base = node.style.transform || "";
        node.setAttribute("data-editor-base-transform", base);
      }
      const sx = Number(node.getAttribute("data-editor-scale-x") || 1);
      const sy = Number(node.getAttribute("data-editor-scale-y") || 1);
      node.style.transform =
        `translate(${x}px,${y}px) ${base} scale(${sx},${sy})`.trim();
    }
    function localDelta(node, dx, dy) {
      // Pointer coordinates are CSS pixels; SVG transforms use parent units.
      const parent = node instanceof SVGElement && node.parentElement;
      const matrix = parent && parent.getScreenCTM && parent.getScreenCTM();
      if (!matrix) {
        const scale = pageScaleFor(node);
        return { x: dx / scale, y: dy / scale };
      }
      const inverse = matrix.inverse();
      return {
        x: inverse.a * dx + inverse.c * dy,
        y: inverse.b * dx + inverse.d * dy,
      };
    }
    function deleteSelection() {
      if (!selection.length) return;
      editorCheckpoint();
      const changed = topSelection()
        .map((node) => node.closest("section.ld-unit[data-unit]"))
        .filter(Boolean);
      topSelection().forEach((node) => {
        node.remove();
      });
      selection = [];
      commitEditorDOM(changed);
    }
    function nextCopyUnitId(source) {
      const base = (source || "unit") + "-copy";
      let serial = 1;
      while (state.units && state.units[base + "-" + serial]) serial += 1;
      return base + "-" + serial;
    }
    function clearCloneMetadata(copy) {
      all("[id]", copy)
        .concat(copy.id ? [copy] : [])
        .forEach((item) => {
          item.removeAttribute("id");
        });
      const editorNames = [
        "data-editor-unit",
        "data-editor-origin-style",
        "data-editor-origin-style-present",
        "data-editor-origin-style-stamped",
        "data-editor-origin-fill-token",
        "data-editor-origin-fill-token-present",
        "data-editor-origin-text-token",
        "data-editor-origin-text-token-present",
        "data-editor-x",
        "data-editor-y",
        "data-editor-base-transform",
        "contenteditable",
        "spellcheck",
      ];
      all("*", copy)
        .concat([copy])
        .forEach((item) => {
          editorNames.forEach((name) => {
            item.removeAttribute(name);
          });
          item.classList.remove("ld-selected", "ld-selection-mark");
        });
    }
    function duplicateSelection() {
      if (!selection.length) return;
      editorCheckpoint();
      const copies = [];
      topSelection().forEach((node) => {
        const copy = node.cloneNode(true);
        clearCloneMetadata(copy);
        cloneAttachedPopups(copy);
        let sourceSections = [];
        if (node.matches && node.matches("section.ld-unit[data-unit]"))
          sourceSections.push(node);
        sourceSections = sourceSections.concat(
          all("section.ld-unit[data-unit]", node),
        );
        let copySections = [];
        if (copy.matches && copy.matches("section.ld-unit[data-unit]"))
          copySections.push(copy);
        copySections = copySections.concat(
          all("section.ld-unit[data-unit]", copy),
        );
        sourceSections.forEach((sourceSection, index) => {
          const duplicateSection = copySections[index];
          if (!duplicateSection) return;
          const sourceId = sourceSection.getAttribute("data-unit");
          const copyId = nextCopyUnitId(sourceId);
          duplicateSection.setAttribute("data-unit", copyId);
          if (state.units && state.units[sourceId])
            state.units[copyId] = clone(state.units[sourceId]);
        });
        const parent = node.parentElement;
        const box = node.getBoundingClientRect();
        const parentBox = parent.getBoundingClientRect();
        const position = getComputedStyle(node).position;
        if (node instanceof SVGElement) {
          const delta = localDelta(node, 20, 20);
          copy.setAttribute(
            "data-editor-base-transform",
            node.getAttribute("data-editor-base-transform") || "",
          );
          translate(
            copy,
            Number(node.getAttribute("data-editor-x") || 0) + delta.x,
            Number(node.getAttribute("data-editor-y") || 0) + delta.y,
          );
        } else if (position !== "absolute" && position !== "fixed") {
          if (getComputedStyle(parent).position === "static")
            parent.style.position = "relative";
          copy.style.position = "absolute";
          copy.style.left =
            box.left - parentBox.left + parent.scrollLeft + 16 + "px";
          copy.style.top =
            box.top - parentBox.top + parent.scrollTop + 16 + "px";
          copy.style.width = box.width + "px";
          copy.style.margin = "0";
          copy.style.zIndex = "4";
        } else {
          translate(
            copy,
            Number(node.getAttribute("data-editor-x") || 0) + 16,
            Number(node.getAttribute("data-editor-y") || 0) + 16,
          );
        }
        node.insertAdjacentElement("afterend", copy);
        stampEditorOrigins(copy);
        copies.push(copy);
      });
      bindUnits();
      bindDecisions();
      bindPopupDOM();
      commitEditorDOM(copies);
      select(copies);
    }
    function eachSelection(fn) {
      if (!selection.length) return;
      editorCheckpoint();
      selection.forEach(fn);
      commitEditorDOM(selection);
    }
    function tokenValue(attribute, value) {
      const allowed =
        attribute === "data-fill-token"
          ? FILL_TOKENS
          : attribute === "data-text-token"
            ? TEXT_TOKENS
            : [];
      return allowed.includes(value) ? value : "";
    }
    function applyToken(attribute, value) {
      value = tokenValue(attribute, value);
      if (!value) return;
      eachSelection((node) => {
        node.setAttribute(attribute, value);
      });
    }
    function toggleStyle(property, on, off) {
      eachSelection((node) => {
        node.style[property] = getComputedStyle(node)[property].includes(on)
          ? off
          : on;
      });
    }
    function changeFont(delta) {
      eachSelection((node) => {
        node.style.fontSize =
          Math.max(
            11,
            Math.min(
              180,
              (parseFloat(getComputedStyle(node).fontSize) || 14) + delta,
            ),
          ) + "px";
      });
    }
    function resetSelection() {
      eachSelection((node) => {
        if (node.getAttribute("data-editor-origin-style-present") === "true")
          node.setAttribute(
            "style",
            node.getAttribute("data-editor-origin-style") || "",
          );
        else node.removeAttribute("style");
        ["fill-token", "text-token"].forEach((key) => {
          if (
            node.getAttribute("data-editor-origin-" + key + "-present") ===
            "true"
          )
            node.setAttribute(
              "data-" + key,
              node.getAttribute("data-editor-origin-" + key) || "",
            );
          else node.removeAttribute("data-" + key);
        });
        [
          "data-editor-x",
          "data-editor-y",
          "data-editor-base-transform",
          "data-editor-scale-x",
          "data-editor-scale-y",
        ].forEach((name) => {
          node.removeAttribute(name);
        });
      });
    }
    function canEditText(node) {
      return (
        node &&
        node.hasAttribute("data-editable") &&
        (!(node instanceof SVGElement) ||
          node.hasAttribute("data-diagram-label")) &&
        !node.matches("img,input,select,button")
      );
    }
    function setDiagramLabelText(node, value) {
      const lines = all("tspan", node);
      if (!lines.length) {
        node.textContent = value;
        return;
      }
      const words = value.trim().split(/\s+/).filter(Boolean);
      const wanted = Math.max(1, Math.min(lines.length, words.length || 1));
      const chunks = [];
      for (let index = 0; index < wanted; index += 1) {
        const start = Math.floor((index * words.length) / wanted);
        const end = Math.floor(((index + 1) * words.length) / wanted);
        chunks.push(words.slice(start, end).join(" "));
      }
      lines.forEach((line, index) => {
        if (index < chunks.length) line.textContent = chunks[index];
        else line.remove();
      });
    }
    function syncDiagramLabelParam(node, value) {
      const pointer = node.getAttribute("data-param-path");
      const section = node.closest("section.ld-unit[data-unit]");
      const variant = node.closest(".ld-variant[data-variant]");
      if (!pointer || !section || !variant) return false;
      const unit = unitState(section.getAttribute("data-unit"));
      const spec =
        unit &&
        unit.variants &&
        unit.variants[variant.getAttribute("data-variant")];
      return Boolean(spec && pointerValue(spec.params, pointer, value));
    }
    function editDiagramLabel(node) {
      select([node]);
      editorCheckpoint();
      const old = document.getElementById("ld-svg-text-editor");
      if (old) old.remove();
      const box = node.getBoundingClientRect();
      const style = getComputedStyle(node);
      const input = document.createElement("input");
      input.id = "ld-svg-text-editor";
      input.type = "text";
      input.value = node.textContent.trim();
      input.setAttribute("aria-label", "Edit diagram label");
      Object.assign(input.style, {
        position: "fixed",
        zIndex: "1000",
        left: Math.max(8, box.left - 6) + "px",
        top: Math.max(8, box.top - 5) + "px",
        width: Math.max(160, box.width + 28) + "px",
        minHeight: Math.max(34, box.height + 10) + "px",
        border: "2px solid var(--interaction)",
        borderRadius: "4px",
        background: "var(--card)",
        color: "var(--ink)",
        padding: "5px 8px",
        fontFamily: style.fontFamily,
        fontSize: Math.max(13, parseFloat(style.fontSize) || 13) + "px",
      });
      document.body.appendChild(input);
      let finished = false;
      const finish = (commit) => {
        if (finished) return;
        finished = true;
        if (commit && input.value.trim()) {
          const value = input.value.trim();
          syncDiagramLabelParam(node, value);
          setDiagramLabelText(node, value);
          commitEditorDOM([node]);
        }
        input.remove();
        renderSelection();
      };
      input.addEventListener("blur", () => finish(true));
      input.addEventListener("keydown", (event) => {
        if (event.key === "Enter") {
          event.preventDefault();
          finish(true);
        } else if (event.key === "Escape") {
          event.preventDefault();
          finish(false);
        }
      });
      input.focus();
      input.select();
    }
    function editText(node) {
      if (!canEditText(node)) return;
      if (node.hasAttribute("data-diagram-label")) {
        editDiagramLabel(node);
        return;
      }
      all('[contenteditable="true"]').forEach((active) => {
        if (active !== node) active.blur();
      });
      select([node]);
      editorCheckpoint();
      textUndoArmed = true;
      node.setAttribute("contenteditable", "true");
      node.setAttribute("spellcheck", "false");
      node.focus();
      const range = document.createRange();
      range.selectNodeContents(node);
      const current = getSelection();
      current.removeAllRanges();
      current.addRange(range);
    }
    function updateEditorButtons() {
      [
        "editor-duplicate",
        "editor-delete",
        "editor-bold",
        "editor-italic",
        "editor-underline",
        "editor-font-up",
        "editor-font-down",
        "editor-reset",
        "editor-fill-token",
        "editor-text-token",
        "editor-fill-palette",
        "editor-text-palette",
        "editor-popup",
        "editor-remove-popup",
      ].forEach((id) => {
        const node = document.getElementById(id);
        if (node) node.disabled = !selection.length;
      });
      const popup = document.getElementById("editor-popup");
      const remove = document.getElementById("editor-remove-popup");
      const target = topSelection().length === 1 ? topSelection()[0] : null;
      const id =
        target &&
        (target.getAttribute("data-detail") ||
          target.getAttribute("data-evidence"));
      if (popup) {
        popup.disabled = !target;
        popup.textContent = id ? "Edit popup" : "Add popup";
      }
      if (remove) remove.disabled = !id;
      const u = document.getElementById("editor-undo");
      const r = document.getElementById("editor-redo");
      if (u) u.disabled = !undo.length;
      if (r) r.disabled = !redo.length;
    }
    function setMode(on) {
      if (!on)
        all('[contenteditable="true"]').forEach((node) => {
          node.blur();
        });
      editing = Boolean(on);
      root.toggleAttribute("data-mode", editing);
      if (editing) root.setAttribute("data-mode", "edit");
      const mode = document.getElementById("mode-toggle");
      if (mode) {
        mode.textContent = editing ? "Done" : "Edit";
        mode.setAttribute("aria-pressed", editing ? "true" : "false");
      }
      if (editing) {
        all("section.ld-unit[data-unit]").forEach((unit) => {
          if (!unit.hasAttribute("tabindex")) {
            unit.tabIndex = 0;
            unit.setAttribute("data-editor-added-tabindex", "");
          }
        });
        stampEditorOrigins();
        makeEditorLayer();
      } else {
        selection = [];
        root.removeAttribute("data-editor-menu");
        all("[contenteditable]").forEach((node) => {
          node.removeAttribute("contenteditable");
          node.removeAttribute("spellcheck");
        });
        all("[data-editor-added-tabindex]").forEach((unit) => {
          unit.removeAttribute("data-editor-added-tabindex");
          unit.removeAttribute("tabindex");
        });
        textUndoArmed = false;
      }
      annotateDiagramLabels(document);
      renderSelection();
      updateEditorButtons();
    }

    function bindEditor() {
      document.addEventListener(
        "pointerdown",
        () => root.setAttribute("data-input-modality", "pointer"),
        true,
      );
      document.addEventListener(
        "keydown",
        (event) => {
          if (event.key === "Tab" || event.key.startsWith("Arrow"))
            root.setAttribute("data-input-modality", "keyboard");
        },
        true,
      );
      const mode = document.getElementById("mode-toggle");
      if (mode)
        mode.addEventListener("click", () => {
          setMode(!editing);
        });
      function bind(id, fn) {
        const node = document.getElementById(id);
        if (node) node.addEventListener("click", fn);
      }
      bind("editor-undo", doUndo);
      bind("editor-redo", doRedo);
      bind("editor-duplicate", duplicateSelection);
      bind("editor-delete", deleteSelection);
      bind("editor-bold", () => {
        toggleStyle("fontWeight", "700", "400");
      });
      bind("editor-italic", () => {
        toggleStyle("fontStyle", "italic", "normal");
      });
      bind("editor-underline", () => {
        toggleStyle("textDecorationLine", "underline", "none");
      });
      bind("editor-font-up", () => {
        changeFont(1);
      });
      bind("editor-font-down", () => {
        changeFont(-1);
      });
      bind("editor-reset", resetSelection);
      bind("editor-add-text", addTextBox);
      bind("editor-popup", editSelectedPopup);
      bind("editor-remove-popup", removeSelectedPopup);
      bind("editor-overflow-toggle", () => {
        const open = root.getAttribute("data-editor-menu") === "open";
        root.toggleAttribute("data-editor-menu", !open);
        if (!open) root.setAttribute("data-editor-menu", "open");
        const button = document.getElementById("editor-overflow-toggle");
        if (button)
          button.setAttribute("aria-expanded", !open ? "true" : "false");
      });
      const fill = document.getElementById("editor-fill-token");
      if (fill)
        fill.addEventListener("change", () => {
          applyToken("data-fill-token", fill.value);
          fill.value = "";
        });
      const text = document.getElementById("editor-text-token");
      if (text)
        text.addEventListener("change", () => {
          applyToken("data-text-token", text.value);
          text.value = "";
        });
      document.addEventListener(
        "pointerdown",
        (event) => {
          if (
            !editing ||
            event.button !== 0 ||
            event.target.closest(
              '.ld-bar,.ld-unit-tools,.ld-slide-index,[data-editor-only]:not(#ld-editor-layer):not(#ld-selection-box),input,textarea,select,button:not([data-detail]):not([data-evidence]),[contenteditable="true"]',
            )
          )
            return;
          const handle = event.target.closest(".ld-handle");
          if (handle) {
            event.preventDefault();
            const bounds = boxFor(selection);
            if (!bounds) return;
            editorCheckpoint();
            gesture = {
              type: "resize",
              handle: handle.getAttribute("data-handle"),
              x: event.clientX,
              y: event.clientY,
              bounds: bounds,
              starts: topSelection().map((node) => {
                const box = node.getBoundingClientRect();
                if (!node.hasAttribute("data-editor-base-transform"))
                  node.setAttribute(
                    "data-editor-base-transform",
                    node.style.transform || "",
                  );
                return {
                  node: node,
                  box: box,
                  x: Number(node.getAttribute("data-editor-x") || 0),
                  y: Number(node.getAttribute("data-editor-y") || 0),
                  sx: Number(node.getAttribute("data-editor-scale-x") || 1),
                  sy: Number(node.getAttribute("data-editor-scale-y") || 1),
                };
              }),
            };
            return;
          }
          const diagramLabel = event.target.closest(
            ".ld-diagram [data-diagram-label][data-editable]",
          );
          let target = event.target.closest(EDITOR_OBJECTS);
          if (diagramLabel && event.detail < 2) {
            target =
              diagramLabel.closest('[data-diagram-object],g[role="button"]') ||
              diagramLabel;
          }
          const card = event.target.closest(
            '.ld-card,.sb-card,section.ld-unit[data-kind="card"]',
          );
          if (card && event.detail < 2) target = card;
          // Empty space in a figure starts an enclosure selection, not a drag
          // of its whole editable body. Existing group selection survives a grab.
          if (
            event.target.closest(".ld-diagram") &&
            !event.target.closest(
              '[data-diagram-object],g[role="button"],[data-diagram-label]',
            )
          )
            target = null;
          if (target) {
            event.preventDefault();
            if (event.detail >= 2 && diagramLabel) {
              event.stopImmediatePropagation();
              gesture = null;
              editText(diagramLabel);
              return;
            }
            const selectedOwner = selection.find(
              (node) => node === target || node.contains(target),
            );
            if (!selectedOwner || event.shiftKey)
              select([target], event.shiftKey);
            gesture = {
              type: "pending",
              x: event.clientX,
              y: event.clientY,
              starts: topSelection().map((node) => ({
                node: node,
                x: Number(node.getAttribute("data-editor-x") || 0),
                y: Number(node.getAttribute("data-editor-y") || 0),
              })),
            };
            return;
          }
          const marquee = document.getElementById("ld-marquee");
          if (marquee) {
            if (!event.shiftKey) select([]);
            gesture = {
              type: "marquee",
              x: event.clientX,
              y: event.clientY,
              base: selection.slice(),
            };
            marquee.style.display = "block";
            marquee.style.left = event.clientX + "px";
            marquee.style.top = event.clientY + "px";
          }
        },
        true,
      );
      document.addEventListener(
        "pointermove",
        (event) => {
          if (!gesture) return;
          const dx = event.clientX - gesture.x;
          const dy = event.clientY - gesture.y;
          if (gesture.type === "pending" && Math.hypot(dx, dy) > 3) {
            editorCheckpoint();
            gesture.type = "move";
          }
          if (gesture.type === "move") {
            event.preventDefault();
            gesture.starts.forEach((start) => {
              const delta = localDelta(start.node, dx, dy);
              translate(start.node, start.x + delta.x, start.y + delta.y);
            });
            renderSelection();
          }
          if (gesture.type === "resize") {
            event.preventDefault();
            const horizontal = gesture.handle.includes("e")
              ? 1
              : gesture.handle.includes("w")
                ? -1
                : 0;
            const vertical = gesture.handle.includes("s")
              ? 1
              : gesture.handle.includes("n")
                ? -1
                : 0;
            const nextWidth = Math.max(
              12,
              gesture.bounds.width + dx * horizontal,
            );
            const nextHeight = Math.max(
              12,
              gesture.bounds.height + dy * vertical,
            );
            const scaleX = nextWidth / gesture.bounds.width;
            const scaleY = nextHeight / gesture.bounds.height;
            gesture.starts.forEach((start) => {
              const node = start.node;
              const left = start.box.left - gesture.bounds.left;
              const top = start.box.top - gesture.bounds.top;
              const width = Math.max(8, start.box.width * scaleX);
              const height = Math.max(8, start.box.height * scaleY);
              if (!(node instanceof SVGElement)) {
                const pageScale = pageScaleFor(node);
                if (getComputedStyle(node).display === "inline")
                  node.style.display = "inline-block";
                if (horizontal) {
                  node.style.width = width / pageScale + "px";
                  node.style.maxWidth = "none";
                }
                if (vertical) {
                  if (
                    /^(P|H1|H2|H3|H4|SPAN|B|I|A|DEL|INS|MARK|FIGCAPTION|TD|TH)$/.test(
                      node.tagName,
                    )
                  ) {
                    node.style.minHeight = height / pageScale + "px";
                    node.style.height = "auto";
                  } else node.style.height = height / pageScale + "px";
                }
                node.style.boxSizing = "border-box";
              }
              const nextX =
                start.x + left * (scaleX - 1) + (horizontal < 0 ? dx : 0);
              const nextY =
                start.y + top * (scaleY - 1) + (vertical < 0 ? dy : 0);
              if (node instanceof SVGElement) {
                const delta = localDelta(
                  node,
                  nextX - start.x,
                  nextY - start.y,
                );
                node.style.transformBox = "fill-box";
                node.style.transformOrigin = "top left";
                node.setAttribute(
                  "data-editor-scale-x",
                  String(start.sx * scaleX),
                );
                node.setAttribute(
                  "data-editor-scale-y",
                  String(start.sy * scaleY),
                );
                translate(node, start.x + delta.x, start.y + delta.y);
              } else {
                const delta = localDelta(
                  node,
                  nextX - start.x,
                  nextY - start.y,
                );
                translate(node, start.x + delta.x, start.y + delta.y);
              }
            });
            renderSelection();
          }
          if (gesture.type === "marquee") {
            const left = Math.min(gesture.x, event.clientX);
            const top = Math.min(gesture.y, event.clientY);
            const right = Math.max(gesture.x, event.clientX);
            const bottom = Math.max(gesture.y, event.clientY);
            const marquee = document.getElementById("ld-marquee");
            marquee.style.left = left + "px";
            marquee.style.top = top + "px";
            marquee.style.width = right - left + "px";
            marquee.style.height = bottom - top + "px";
            const hits = editorObjectTargets().filter((node) => {
              const box = node.getBoundingClientRect();
              return (
                box.left >= left &&
                box.right <= right &&
                box.top >= top &&
                box.bottom <= bottom
              );
            });
            const outerHits = hits.filter(
              (node) =>
                !hits.some(
                  (parent) => parent !== node && parent.contains(node),
                ),
            );
            selection = gesture.base.concat(
              outerHits.filter((node) => !gesture.base.includes(node)),
            );
            renderSelection();
          }
        },
        true,
      );
      document.addEventListener(
        "pointerup",
        () => {
          const marquee = document.getElementById("ld-marquee");
          if (marquee) marquee.style.display = "none";
          if (
            gesture &&
            (gesture.type === "move" || gesture.type === "resize")
          ) {
            suppressEditorClick = true;
            commitEditorDOM(gesture.starts.map((start) => start.node));
            setTimeout(() => {
              suppressEditorClick = false;
            }, 0);
          }
          gesture = null;
        },
        true,
      );
      document.addEventListener(
        "dblclick",
        (event) => {
          if (!editing) return;
          const target = event.target.closest("[data-editable]");
          if (target) {
            event.preventDefault();
            event.stopImmediatePropagation();
            editText(target);
          }
        },
        true,
      );
      window.addEventListener("keydown", (event) => {
        if (!editing) return;
        const focusedUnit =
          event.target.matches &&
          event.target.matches("section.ld-unit[data-unit]")
            ? event.target
            : null;
        if (focusedUnit && (event.key === "Enter" || event.key === " ")) {
          const first = editorTargets().find((node) =>
            focusedUnit.contains(node),
          );
          if (first) {
            event.preventDefault();
            event.stopImmediatePropagation();
            if (
              event.key === "Enter" &&
              selection.length === 1 &&
              selection[0] === first &&
              canEditText(first)
            )
              editText(first);
            else select([first]);
          }
          return;
        }
        const typing =
          event.target.closest &&
          event.target.closest(
            '[contenteditable="true"],input,textarea,select',
          );
        const key = event.key.toLowerCase();
        const mod = event.metaKey || event.ctrlKey;
        if (mod && key === "z") {
          event.preventDefault();
          event.stopImmediatePropagation();
          event.shiftKey ? doRedo() : doUndo();
        } else if (mod && key === "d" && !typing) {
          event.preventDefault();
          event.stopImmediatePropagation();
          duplicateSelection();
        } else if (
          (event.key === "Delete" || event.key === "Backspace") &&
          !typing
        ) {
          event.preventDefault();
          event.stopImmediatePropagation();
          deleteSelection();
        } else if (event.key === "Escape") {
          event.preventDefault();
          event.stopImmediatePropagation();
          if (typing && typing.hasAttribute("contenteditable")) typing.blur();
          select([]);
        } else if (
          event.key.startsWith("Arrow") &&
          !typing &&
          selection.length
        ) {
          event.preventDefault();
          event.stopImmediatePropagation();
          let dx =
            event.key === "ArrowLeft" ? -1 : event.key === "ArrowRight" ? 1 : 0;
          let dy =
            event.key === "ArrowUp" ? -1 : event.key === "ArrowDown" ? 1 : 0;
          if (event.shiftKey) {
            dx *= 10;
            dy *= 10;
          }
          editorCheckpoint();
          topSelection().forEach((node) => {
            translate(
              node,
              Number(node.getAttribute("data-editor-x") || 0) + dx,
              Number(node.getAttribute("data-editor-y") || 0) + dy,
            );
          });
          commitEditorDOM(selection);
        }
      });
      document.addEventListener(
        "beforeinput",
        (event) => {
          if (
            editing &&
            event.target.closest &&
            event.target.closest('[contenteditable="true"]') &&
            !textUndoArmed
          ) {
            editorCheckpoint();
            textUndoArmed = true;
          }
        },
        true,
      );
      document.addEventListener(
        "input",
        (event) => {
          if (
            editing &&
            event.target.closest &&
            event.target.closest('[contenteditable="true"]')
          )
            commitEditorDOM([event.target]);
        },
        true,
      );
      document.addEventListener(
        "focusout",
        (event) => {
          const node = event.target;
          if (
            !editing ||
            !node.matches?.('[data-editable][contenteditable="true"]')
          )
            return;
          node.removeAttribute("contenteditable");
          node.removeAttribute("spellcheck");
          textUndoArmed = false;
          commitEditorDOM([node]);
        },
        true,
      );
      document.addEventListener("scroll", renderSelection, true);
      onLayoutResize(() => {
        // Choose responsive diagram geometry against the newly fitted page,
        // not its previous width. The fit listener schedules a later frame;
        // rendering first would leave wide/narrow mode one resize behind.
        if (pageFitFrame) cancelAnimationFrame(pageFitFrame);
        fitFixedPages();
        renderAll();
        renderSelection();
      });
    }

    function clearProtected(cloneRoot) {
      all("[data-export-protect]", cloneRoot).forEach((node) => {
        (node.getAttribute("data-export-protect") || "")
          .split(/[\s,]+/)
          .filter(Boolean)
          .forEach((name) => {
            node.style.removeProperty(name);
            node.removeAttribute(name);
          });
      });
    }
    function serializeClone(cloneRoot) {
      return (
        "<!doctype html>\n" +
        cloneRoot.outerHTML.replaceAll(
          ' xmlns="http://www.w3.org/2000/svg"',
          "",
        )
      );
    }
    function setCloneState(cloneRoot, nextState) {
      const block = cloneRoot.querySelector("#legaldesign-state");
      if (block) block.textContent = safeJSON(nextState);
    }
    function scrubTransientEditing(cloneRoot) {
      all("[contenteditable]", cloneRoot).forEach((node) => {
        node.removeAttribute("contenteditable");
        node.removeAttribute("spellcheck");
      });
      all(".ld-selected,.ld-selection-mark", cloneRoot).forEach((node) => {
        node.classList.remove("ld-selected", "ld-selection-mark");
      });
      all(
        "#ld-editor-layer,#ld-svg-text-editor,#ld-selection-popover,#ld-phone-sheet,#ld-restore-banner,.ld-save-banner,.ld-download-link,.ld-bottom-save,#ld-page-reader,#ld-read-page,#ld-page-fit-error",
        cloneRoot,
      ).forEach((node) => {
        node.remove();
      });
      all("[data-editor-added-tabindex]", cloneRoot).forEach((unit) => {
        unit.removeAttribute("data-editor-added-tabindex");
        unit.removeAttribute("tabindex");
      });
      cloneRoot.removeAttribute("data-mode");
      cloneRoot.removeAttribute("data-editor-menu");
      const mode = cloneRoot.querySelector("#mode-toggle");
      if (mode) {
        mode.textContent = "Edit";
        mode.setAttribute("aria-pressed", "false");
      }
      const overflow = cloneRoot.querySelector("#editor-overflow-toggle");
      if (overflow) overflow.setAttribute("aria-expanded", "false");
      const scrim = cloneRoot.querySelector("#popup-scrim");
      if (scrim) {
        scrim.hidden = true;
        all(".pop", scrim).forEach((pop) => {
          pop.hidden = true;
        });
      }
      const body = cloneRoot.querySelector("body");
      if (body && body.style.overflow === "hidden")
        body.style.removeProperty("overflow");
    }
    function scrubEditing(cloneRoot) {
      scrubTransientEditing(cloneRoot);
      clearProtected(cloneRoot);
    }
    function reducedClientState(cloneRoot, clientBlueprintId) {
      const brief = state.brief || {};
      const next = {
        schema: state.schema,
        artifactId: clientBlueprintId,
        savedAt: new Date().toISOString(),
        brief: {
          title: "[Descriptive title for the visible artifact.]",
          reader: "[Reader described by the visible artifact.]",
          action: "[Action described by the visible artifact.]",
          purpose: brief.purpose || "understand",
          message: "[Message stated in the visible artifact.]",
          spine: brief.spine || "sequence",
          situation: brief.situation || "laptop",
          form: brief.form || "one-page",
          sources: [],
          assumptions: [],
          gaps: [],
        },
        units: {},
        evidence: {},
        review: {
          ...(singleComposition() ? {} : { approach: currentApproach() }),
          decisions: {},
          theme: (state.review && state.review.theme) || "light",
          location:
            state.review && state.review.location != null
              ? state.review.location
              : null,
        },
      };
      if (state.sourceSchemaVersion != null)
        next.sourceSchemaVersion = state.sourceSchemaVersion;
      if (state.approaches) {
        const approach = currentApproach();
        if (state.approaches[approach])
          next.approaches = {
            [approach]: clone(state.approaches[approach]),
          };
      }
      if (state.composition) {
        next.composition = {
          strategy: state.composition.strategy,
          sections: (state.composition.sections || []).map((section) => ({
            id: section.id,
            unitIds: [...section.unitIds],
            layout: clone(section.layout),
            ...(section.issueLayout
              ? { issueLayout: clone(section.issueLayout) }
              : {}),
          })),
        };
      }
      if (state.overview) next.overview = clone(state.overview);
      if (state.style)
        next.style = { source: state.style.source || "loxoto", ref: null };
      const presentIds = [];
      all("section.ld-unit[data-unit]", cloneRoot).forEach((section) => {
        const id = section.getAttribute("data-unit");
        const sourceUnit = state.units && state.units[id];
        if (!sourceUnit) return;
        presentIds.push(id);
        const selected = sourceUnit.selected === "b" ? "b" : "a";
        const variant = section.querySelector(
          '.ld-variant[data-variant="' + selected + '"]',
        );
        const body = variant && variant.querySelector("[data-variant-body]");
        const finalHTML = body ? body.innerHTML : "";
        const axis =
          (sourceUnit.variants &&
            sourceUnit.variants[selected] &&
            sourceUnit.variants[selected].axis) ||
          "single";
        const canonicalVariant = { axis: axis, why: "" };
        if (sourceUnit.kind !== "figure") canonicalVariant.html = finalHTML;
        const unit = {
          kind: sourceUnit.kind,
          selected: selected,
          variants: { a: clone(canonicalVariant) },
          edits: { a: selected === "a" ? finalHTML : null },
          placeholder:
            sourceUnit.kind === "card"
              ? PLACEHOLDERS.cardLine
              : sourceUnit.kind === "figure"
                ? PLACEHOLDERS.figureLabel
                : sourceUnit.kind === "decision"
                  ? "[The decision the reader must make.]"
                  : PLACEHOLDERS.title,
        };
        if (selected === "b") {
          unit.variants.b = clone(canonicalVariant);
          unit.edits.b = sourceUnit.kind === "figure" ? null : finalHTML;
        }
        next.units[id] = unit;
      });
      Object.keys((state.review && state.review.decisions) || {}).forEach(
        (id) => {
          if (presentIds.includes(id))
            next.review.decisions[id] = clone(state.review.decisions[id]);
        },
      );
      return next;
    }
    function placeholderFor(component, key, path, value) {
      if (value === "") return value;
      if (TEMPLATE_STRUCTURAL_PARAM_KEYS.has(key)) return value;
      if (key === "sub" || /Sub$/.test(key))
        return "[One fact about it, under twenty words.]";

      const phrases = {
        flow: {
          title: "[Stage name.]",
          edges: "[What passes to the next stage.]",
        },
        timeline: { when: "[Date.]", title: "[What happened.]" },
        hierarchy: {
          root: "[The authority at the top.]",
          title: path.includes("leaves") ? "[Leaf.]" : "[Branch.]",
          edge: "[What connects it.]",
        },
        zones: {
          zoneA: "[Zone label.]",
          zoneB: "[Zone label.]",
          title: "[Item in this zone.]",
          crossing: "[What crosses between the zones.]",
        },
        beforeAfter: {
          beforeLabel: "[State before.]",
          afterLabel: "[State after.]",
          edge: "[What changes it.]",
        },
        hub: {
          centre: "[Central idea.]",
          title: "[Spoke.]",
          edge: "[What connects it.]",
        },
        compareTwo: {
          a: path.includes("rows") ? "[Value.]" : "[Option name.]",
          b: path.includes("rows") ? "[Value.]" : "[Option name.]",
          label: "[Criterion.]",
        },
        funnel: {
          title: "[Tier.]",
          edges: "[What passes to the next tier.]",
          outcome: "[Outcome.]",
        },
        loop: {
          centre: "[Central idea.]",
          title: "[Step.]",
          edge: "[What leads to the next step.]",
        },
        matrix: {
          xAxis: "[Axis label.]",
          yAxis: "[Axis label.]",
          title: "[Quadrant.]",
        },
        figurePath: {
          marks: "[Milestone.]",
          goal: "[Goal.]",
          caption: "[What the path shows.]",
        },
        stairSteps: {
          title: "[Step.]",
          caption: "[What the steps show.]",
        },
        pyramid: {
          title: "[Level.]",
          caption: "[What the levels show.]",
        },
        gears: {
          labels: "[Moving part.]",
          caption: "[How the parts work together.]",
        },
      };
      return (phrases[component] && phrases[component][key]) || "[Label.]";
    }
    function validTemplatePlaceholder(value) {
      if (
        typeof value !== "string" ||
        !/^\[[^[\]\r\n]{3,200}\]$/.test(value.trim())
      )
        return false;
      return new Set([
        "[0 checked · 0 need attention]",
        "[01]",
        "[AREA · STATUS]",
        "[Agreed in this draft: the settled sections, listed.]",
        "[Amount, security, valuation · investor.]",
        "[Area name, e.g. Formation]",
        "[Area name.]",
        "[Area · document and page.]",
        "[Assumption the reader should know.]",
        "[Axis label.]",
        "[Branch.]",
        "[Candidate visual treatment.]",
        "[Central idea.]",
        "[Citation or record label.]",
        "[Clip of the source page with the cited passage highlighted.]",
        "[Column heading.]",
        "[Company name, or the number of findings that matter.]",
        "[Company · transaction · report date.]",
        "[Criterion.]",
        "[Date.]",
        "[Date. What it means.]",
        "[Decision or action.]",
        "[Document name.]",
        "[Document, section, and page.]",
        "[Each date with what happened or came due on it.]",
        "[Expected record: the document, approval, or filing that would resolve the point.]",
        "[Fact label, e.g. Incorporated]",
        "[Finding not included in this sample.]",
        "[First amount.]",
        "[First position.]",
        "[Goal.]",
        "[How choices are saved.]",
        "[How position, direction, grouping, scale, or contrast expresses the relationship.]",
        "[How the parts work together.]",
        "[How to read this report.]",
        "[How to use the page, in one line.]",
        "[How to use the slide.]",
        "[Item in this zone.]",
        "[Known gap or unresolved point.]",
        "[Label.]",
        "[Leaf.]",
        "[Level.]",
        "[List item.]",
        "[Matter or deliverable title.]",
        "[Section heading.]",
        "[Finding title.]",
        "[Scope and limits.]",
        "[Required conditions.]",
        "[Options and next action.]",
        "[Review summary.]",
        "[Findings and consequences.]",
        "[Follow-up plan.]",
        "[Actions before proceeding.]",
        "[Review coverage.]",
        "[Method workflow.]",
        "[Method structure.]",
        "[Matter · document · draft · date received.]",
        "[Matter · the question this page answers.]",
        "[Milestone.]",
        "[Moving part.]",
        "[NN]",
        "[Not included in this template.]",
        "[One card or row per finding that needs attention.]",
        "[One fact about it, under twenty words.]",
        "[One line that qualifies the title.]",
        "[Open issue · section and name.]",
        "[Open item name.]",
        "[Open the document in the data room.]",
        "[Open the source.]",
        "[Option A.]",
        "[Option B.]",
        "[Option C.]",
        "[Outcome.]",
        "[PROPOSED INVESTMENT]",
        "[Page label.]",
        "[Provenance line.]",
        "[QUESTION · JURISDICTION OR MATTER]",
        "[QUESTION · MATTER]",
        "[REPORT AREA]",
        "[SECTION N OF TOTAL · COUNT DOCUMENTS CHECKED]",
        "[STATUS]",
        "[Scale end.]",
        "[Scale label and gap.]",
        "[Scale start.]",
        "[Second amount.]",
        "[Second position.]",
        "[Section and page.]",
        "[Short answer.]",
        "[Source and locator.]",
        "[Source of the figure's facts.]",
        "[Sources and the date they were read.]",
        "[Spoke.]",
        "[Stage name.]",
        "[State after.]",
        "[State before.]",
        "[Step.]",
        "[Table value.]",
        "[Term or category.]",
        "[The area, or its exceptions, in one sentence.]",
        "[The authority at the top.]",
        "[The choice the reader makes, as a question.]",
        "[The claim in one sentence, ending with a period.]",
        "[The clause, in the document’s words.]",
        "[The closing condition, cure, covenant, representation, or follow-up.]",
        "[The consequence of option A.]",
        "[The consequence of option B.]",
        "[The consequence of option C.]",
        "[The counts.]",
        "[The decision the reader must make.]",
        "[The finding in five words.]",
        "[The finding in one sentence.]",
        "[The open item in five words.]",
        "[The practical consequence for this transaction.]",
        "[The question this card answers?]",
        "[The reader and what they already know.]",
        "[The source reviewed, the controlling fact, and the exact gap, with dates and numbers.]",
        "[The value or fact this block communicates.]",
        "[Timing or provenance.]",
        "[Two sentences that tell the reader what they are looking at.]",
        "[Value from the data room.]",
        "[Value.]",
        "[Verbatim excerpt of the controlling passage, in the document's words.]",
        "[What changes it.]",
        "[What connects it.]",
        "[What crosses between the zones.]",
        "[What happened.]",
        "[What happens on this date.]",
        "[What is open, in one line.]",
        "[What it means.]",
        "[What leads to the next step.]",
        "[What passes to the next stage.]",
        "[What passes to the next tier.]",
        "[What the figure shows, as a claim.]",
        "[What the levels show.]",
        "[What the path shows.]",
        "[What the steps show.]",
        "[What the table shows.]",
        "[What the value means.]",
        "[What this report is and who it is for.]",
        "[What this section enables the reader to understand or do.]",
        "[What this source establishes, in one sentence.]",
        "[What was found, with the date.]",
        "[Why this composition best communicates the core relationship.]",
        "[Why this treatment fits the reader and purpose.]",
        "[Zone label.]",
        "[§ Section]",
        "[§N]",
      ]).has(value.trim());
    }
    function preferredTemplatePlaceholder(value, fallback) {
      return validTemplatePlaceholder(value) ? value.trim() : fallback;
    }
    function placeholderNumber(key, path) {
      const indexes = (path || []).filter((part) => typeof part === "number");
      const ordinal = (indexes.length ? indexes[indexes.length - 1] : 0) + 1;
      const fixed = {
        nowAt: 0,
        offset: 0,
        location: 0,
        min: 0,
        minValue: 0,
        scaleMin: 0,
        low: 20,
        q1: 25,
        before: 30,
        a: 30,
        start: 40,
        median: 50,
        mark: 50,
        markAt: 50,
        after: 60,
        b: 60,
        q3: 75,
        high: 80,
        max: 100,
        maxValue: 100,
        scaleMax: 100,
        delta: 10,
      };
      if (key === "value") return ordinal;
      if (Object.hasOwn(fixed, key)) return fixed[key];
      if (key === "x") return ordinal;
      if (key === "y") return ordinal * 10;
      return ordinal * 10;
    }
    function placeholderParams(value, key, evidenceMap, component, path) {
      path = path || [];
      if (Array.isArray(value))
        return value.map((item, index) =>
          placeholderParams(
            item,
            key,
            evidenceMap,
            component,
            path.concat(index),
          ),
        );
      if (value && typeof value === "object") {
        const out = {};
        Object.keys(value).forEach((name) => {
          const placeholder = placeholderParams(
            value[name],
            name,
            evidenceMap,
            component,
            path.concat(name),
          );
          if (placeholder !== undefined) out[name] = placeholder;
        });
        return out;
      }
      if (key === "detail" || /Detail$/.test(key))
        return evidenceMap[value] || undefined;
      if (TEMPLATE_STRUCTURAL_PARAM_KEYS.has(key)) return value;
      if (typeof value === "number") return placeholderNumber(key, path);
      return typeof value === "string"
        ? placeholderFor(component, key, path, value)
        : value;
    }
    function addTemplateId(order, seen, value) {
      if (typeof value !== "string" || !value || Object.hasOwn(seen, value))
        return;
      seen[value] = true;
      order.push(value);
    }
    function idMap(order, prefix) {
      const map = Object.create(null);
      order.forEach((id, index) => {
        map[id] = prefix + "-" + (index + 1);
      });
      return map;
    }
    function templateMappings() {
      const orders = {
        section: [],
        unit: [],
        claim: [],
        evidence: [],
        source: [],
      };
      const seen = {
        section: Object.create(null),
        unit: Object.create(null),
        claim: Object.create(null),
        evidence: Object.create(null),
        source: Object.create(null),
      };
      const compositions = state.approaches
        ? ["a", "b"].map(
            (key) => (state.approaches[key] || {}).composition || {},
          )
        : [state.composition || {}];
      compositions.forEach((composition) => {
        (composition.sections || []).forEach((section) => {
          addTemplateId(orders.section, seen.section, section.id);
          (section.unitIds || []).forEach((id) => {
            addTemplateId(orders.unit, seen.unit, id);
          });
          ((section.layout || {}).placements || []).forEach((placement) => {
            addTemplateId(orders.unit, seen.unit, placement.unitId);
          });
        });
      });
      Object.keys(state.units || {}).forEach((id) => {
        addTemplateId(orders.unit, seen.unit, id);
      });
      (state.claims || []).forEach((claim) => {
        addTemplateId(orders.claim, seen.claim, claim.id);
        (claim.sourceIds || []).forEach((id) => {
          addTemplateId(orders.source, seen.source, id);
        });
        (claim.evidenceIds || []).forEach((id) => {
          addTemplateId(orders.evidence, seen.evidence, id);
        });
      });
      Object.keys(state.units || {}).forEach((id) => {
        const unit = state.units[id] || {};
        (unit.claimRefs || []).forEach((claimId) => {
          addTemplateId(orders.claim, seen.claim, claimId);
        });
        (unit.evidence || []).forEach((evidenceId) => {
          addTemplateId(orders.evidence, seen.evidence, evidenceId);
        });
      });
      Object.keys(state.evidence || {}).forEach((id) => {
        addTemplateId(orders.evidence, seen.evidence, id);
        const item = state.evidence[id] || {};
        addTemplateId(orders.source, seen.source, item.sourceId);
        (item.claimRefs || []).forEach((claimId) => {
          addTemplateId(orders.claim, seen.claim, claimId);
        });
      });
      ((state.brief || {}).sources || []).forEach((source) => {
        addTemplateId(orders.source, seen.source, source.id);
      });
      const maps = {
        section: idMap(orders.section, "section"),
        unit: idMap(orders.unit, "unit"),
        claim: idMap(orders.claim, "claim"),
        evidence: idMap(orders.evidence, "evidence"),
        source: idMap(orders.source, "source"),
        options: Object.create(null),
        orders: orders,
      };
      Object.keys(state.units || {}).forEach((unitId) => {
        const optionMap = Object.create(null);
        ((state.units[unitId] || {}).options || []).forEach((option, index) => {
          if (option && option.key != null)
            optionMap[String(option.key)] = "option-" + (index + 1);
        });
        maps.options[unitId] = optionMap;
      });
      return maps;
    }
    function mappedIds(values, map) {
      return (values || []).map((id) => map[id]);
    }
    function templateUnitPlaceholder(unit) {
      let fallback = PLACEHOLDERS.title;
      if (unit.kind === "card") fallback = PLACEHOLDERS.cardLine;
      if (unit.kind === "figure") fallback = PLACEHOLDERS.figureLabel;
      if (unit.kind === "decision")
        fallback = "[The decision the reader must make.]";
      return preferredTemplatePlaceholder(unit.placeholder, fallback);
    }
    function templateHeadingPlaceholder(unit = {}, node = null) {
      // Only this finite vocabulary can survive as heading intent. A user's
      // arbitrary bracketed matter text is not a trustworthy template label.
      const headings = new Set([
        "[Matter or deliverable title.]",
        "[Section heading.]",
        "[Finding title.]",
        "[Scope and limits.]",
        "[Short answer.]",
        "[Decision or action.]",
        "[Required conditions.]",
        "[Options and next action.]",
        "[Review summary.]",
        "[Findings and consequences.]",
        "[Follow-up plan.]",
        "[Actions before proceeding.]",
        "[Review coverage.]",
        "[Method workflow.]",
        "[Method structure.]",
      ]);
      for (const candidate of [
        unit.placeholder_title,
        node?.getAttribute("data-placeholder-title"),
        node?.getAttribute("data-placeholder"),
        unit.placeholder,
      ]) {
        if (typeof candidate === "string" && headings.has(candidate.trim()))
          return candidate.trim();
      }
      const roleHeadings = {
        title: "[Matter or deliverable title.]",
        matter: "[Matter or deliverable title.]",
        answer: "[Short answer.]",
        finding: "[Finding title.]",
        scope: "[Scope and limits.]",
        action: "[Decision or action.]",
        expected: "[Required conditions.]",
      };
      return Object.hasOwn(roleHeadings, unit.role)
        ? roleHeadings[unit.role]
        : "[Section heading.]";
    }
    function templateLegacyCollection(value, name, maps) {
      const allowed = LEGACY_COLLECTION_FIELDS[name];
      if (!allowed || !Array.isArray(value)) return [];
      return value.map((item, index) => {
        if (!item || typeof item !== "object" || Array.isArray(item)) return {};
        const next = {};
        Object.keys(item).forEach((key) => {
          if (!allowed.has(key)) return;
          next[key] = placeholderParams(item[key], key, maps.evidence, null, [
            index,
            key,
          ]);
        });
        return next;
      });
    }
    function templateVariant(variant, unit, maps) {
      const next = {};
      let component =
        typeof variant.component === "string" &&
        (LD.registry || []).includes(variant.component)
          ? variant.component
          : null;
      if (component) {
        try {
          LD.render(component, variant.params, {});
        } catch (_) {
          component = null;
        }
      }
      Object.keys(variant).forEach((name) => {
        if (!VARIANT_FIELDS.has(name)) return;
        if (name === "axis") {
          next.axis = VARIANT_AXES.includes(variant.axis)
            ? variant.axis
            : unit.single
              ? "single"
              : "form";
          return;
        }
        if (name === "component") {
          if (component) next.component = component;
          return;
        }
        if (name === "params") {
          if (component) {
            next.params = placeholderParams(
              variant.params,
              "params",
              maps.evidence,
              component,
              [],
            );
            try {
              LD.render(component, next.params, {});
            } catch (error) {
              throw new TypeError(
                `template ${component} parameters became invalid during sanitization: ${error.message}`,
              );
            }
          }
          return;
        }
        if (Object.hasOwn(LEGACY_COLLECTION_FIELDS, name)) {
          next[name] = templateLegacyCollection(variant[name], name, maps);
          return;
        }
        if (name === "layout") {
          if (LEGACY_LAYOUTS.includes(variant.layout))
            next.layout = variant.layout;
          return;
        }
        if (name === "why") {
          next[name] = "[Why this treatment fits the reader and purpose.]";
          return;
        }
        if (name === "encoding") {
          next[name] =
            "[How position, direction, grouping, scale, or contrast expresses the relationship.]";
          return;
        }
        if (name === "html") {
          next[name] = templateUnitPlaceholder(unit);
          return;
        }
        if (name === "title") {
          next[name] = PLACEHOLDERS.cardTitle;
          return;
        }
        next[name] = placeholderParams(
          variant[name],
          name,
          maps.evidence,
          component,
          [],
        );
      });
      return next;
    }
    function templateUnit(unitId, maps) {
      const unit = state.units[unitId] || {};
      const next = {
        kind: UNIT_KINDS.includes(unit.kind) ? unit.kind : "text",
        selected: unit.selected === "b" ? "b" : "a",
      };
      if (UNIT_ROLES.includes(unit.role)) next.role = unit.role;
      if (["single", "multiple"].includes(unit.selection_mode))
        next.selection_mode = unit.selection_mode;
      ["allow_custom", "allow_note", "single", "sourcePreview"].forEach(
        (name) => {
          if (typeof unit[name] === "boolean") next[name] = unit[name];
        },
      );
      if (unit.claim != null)
        next.claim =
          unit.kind === "decision"
            ? "[The decision this unit presents.]"
            : templateUnitPlaceholder(unit);
      if (unit.relationship != null)
        next.relationship = RELATIONSHIPS.includes(unit.relationship)
          ? unit.relationship
          : "containment";
      if (Array.isArray(unit.candidates))
        next.candidates = unit.candidates.map(
          () => "[Candidate visual treatment.]",
        );
      if (Array.isArray(unit.claimRefs))
        next.claimRefs = mappedIds(unit.claimRefs, maps.claim);
      if (Array.isArray(unit.evidence))
        next.evidence = mappedIds(unit.evidence, maps.evidence);
      if (typeof unit.detail === "string" && maps.evidence[unit.detail])
        next.detail = maps.evidence[unit.detail];
      next.variants = {};
      Object.keys(unit.variants || {}).forEach((key) => {
        next.variants[key] = templateVariant(unit.variants[key], unit, maps);
      });
      next.edits = {};
      Object.keys(
        Object.assign({}, unit.variants || {}, unit.edits || {}),
      ).forEach((key) => {
        next.edits[key] = null;
      });
      next.placeholder = templateUnitPlaceholder(unit);
      if (unit.placeholder_title != null)
        next.placeholder_title = templateHeadingPlaceholder(unit);
      if (unit.placeholder_sub != null)
        next.placeholder_sub = "[One fact about it, under twenty words.]";
      if (unit.source_note != null) next.source_note = "[Source and locator.]";
      if (unit.tag != null) next.tag = "[Open issue · section and name.]";
      if (unit.question != null)
        next.question = "[The choice the reader makes, as a question.]";
      if (Array.isArray(unit.options)) {
        const optionMap = maps.options[unitId] || {};
        next.options = unit.options.map((option, index) => {
          const key = optionMap[String(option.key)] || "option-" + (index + 1);
          return {
            key: key,
            label: "[Option " + (index + 1) + ".]",
            consequence: "[The consequence of option " + (index + 1) + ".]",
          };
        });
      }
      return next;
    }
    function templateEvidence(item, maps) {
      const next = {
        cite: "[Citation or record label.]",
        locator: "[Section and page.]",
        excerpt:
          "[Verbatim excerpt of the controlling clause, in the document's words.]",
        link: item.link == null ? null : "#",
        status: "supplied-unverified",
      };
      if (item.sourceId != null) next.sourceId = maps.source[item.sourceId];
      if (Array.isArray(item.claimRefs))
        next.claimRefs = mappedIds(item.claimRefs, maps.claim);
      if (item.detail != null)
        next.detail = "[What this source establishes, in one sentence.]";
      if (item.popup) {
        next.popup = {
          type: ["source", "explainer", "detail"].includes(item.popup.type)
            ? item.popup.type
            : "detail",
          title: "[The question or insight this popup explains.]",
          sections: (item.popup.sections || []).map(() => ({
            heading: "[Specific subpoint.]",
            body: "[The deeper detail the reader needs here.]",
          })),
        };
        if (item.popup.lede != null)
          next.popup.lede = "[One-sentence orientation to the deeper detail.]";
      }
      if (item.original) {
        next.original = {
          availability:
            item.original.availability === "linked" ? "linked" : "unavailable",
          label: "[Original source label.]",
        };
        if (next.original.availability === "linked") next.original.href = "#";
      }
      if (item.image) {
        next.image = {
          status:
            "[Clip of the source page with the cited passage highlighted.]",
        };
        if (Object.hasOwn(item.image, "data")) next.image.data = null;
      }
      if (item.provenance != null)
        next.provenance = "[Source, version, and retrieval note.]";
      return next;
    }
    function isPackagedTemplateId(requestedId) {
      return /^legaldesign-template-[a-z0-9][a-z0-9-]{0,79}$/.test(
        requestedId || "",
      );
    }
    function templateExportId(requestedId) {
      if (isPackagedTemplateId(requestedId)) return requestedId;
      let suffix = "";
      if (window.crypto && typeof window.crypto.randomUUID === "function")
        suffix = window.crypto.randomUUID();
      else
        suffix =
          Date.now().toString(36) +
          "-" +
          Math.random().toString(36).slice(2, 14);
      return "legaldesign-template-" + suffix.toLowerCase();
    }
    function templateState(maps, templateId) {
      const brief = state.brief || {};
      const nextBrief = {
        title: "[Descriptive title for the artifact.]",
        reader: "[The reader and what they already know.]",
        action: "[What the reader should decide or do.]",
        purpose: brief.purpose,
        message: "[The answer the page should make clear.]",
        spine: brief.spine,
        situation: brief.situation,
        form: brief.form,
        sources: (brief.sources || []).map((source) => {
          const next = {
            id: maps.source[source.id],
            label: "[Source label.]",
            status: "supplied-unverified",
          };
          if (source.note != null) next.note = "[Source status note.]";
          return next;
        }),
        assumptions: (brief.assumptions || []).map(
          () => "[Assumption the reader should know.]",
        ),
        gaps: (brief.gaps || []).map(() => "[Known gap or unresolved point.]"),
      };
      if (brief.run != null) nextBrief.run = {};
      const next = {
        schema: state.schema,
        artifactId: templateId,
        savedAt: new Date().toISOString(),
        brief: nextBrief,
        units: {},
        evidence: {},
        review: {
          ...(singleComposition() ? {} : { approach: "a" }),
          decisions: {},
          theme: (state.review && state.review.theme) || "light",
          location: null,
        },
        history: [],
      };
      if (state.sourceSchemaVersion != null)
        next.sourceSchemaVersion = state.sourceSchemaVersion;
      if (state.style != null) next.style = { source: "template", ref: null };
      if (state.approaches) {
        next.approaches = {};
        ["a", "b"].forEach((key) => {
          const approach = state.approaches[key] || {};
          const composition = approach.composition || {};
          next.approaches[key] = {
            label: key === "a" ? "Page A" : "Page B",
            rationale:
              "[Why this complete page approach fits the reader and purpose.]",
            composition: {
              strategy: composition.strategy,
              shape: "[The section sequence and reading path.]",
              rationale:
                "[Why this composition best communicates the core relationship.]",
              sections: (composition.sections || []).map((section) => ({
                id: maps.section[section.id],
                purpose:
                  "[What this section enables the reader to understand or do.]",
                unitIds: mappedIds(section.unitIds, maps.unit),
                layout: {
                  columns: (section.layout || {}).columns || 12,
                  placements: ((section.layout || {}).placements || []).map(
                    (placement) => ({
                      unitId: maps.unit[placement.unitId],
                      row: placement.row,
                      column: placement.column,
                      span: placement.span,
                      ...(placement.rowSpan
                        ? { rowSpan: placement.rowSpan }
                        : {}),
                    }),
                  ),
                },
              })),
              templateRef:
                composition.strategy === "template-import"
                  ? "[Template or playbook reference.]"
                  : null,
            },
          };
        });
      }
      if (state.composition) {
        next.composition = {
          strategy: state.composition.strategy,
          shape: "[The section sequence and reading path.]",
          rationale:
            "[Why this composition best communicates the core relationship.]",
          sections: (state.composition.sections || []).map((section) => ({
            id: maps.section[section.id],
            purpose:
              "[What this section enables the reader to understand or do.]",
            unitIds: mappedIds(section.unitIds, maps.unit),
            ...(section.issueLayout
              ? {
                  issueLayout: {
                    findingUnitId: maps.unit[section.issueLayout.findingUnitId],
                    implicationUnitId:
                      maps.unit[section.issueLayout.implicationUnitId],
                    actionUnitId: maps.unit[section.issueLayout.actionUnitId],
                    supportUnitIds: mappedIds(
                      section.issueLayout.supportUnitIds,
                      maps.unit,
                    ),
                  },
                }
              : {}),
            layout: {
              columns: (section.layout || {}).columns || 12,
              placements: ((section.layout || {}).placements || []).map(
                (placement) => ({
                  unitId: maps.unit[placement.unitId],
                  row: placement.row,
                  column: placement.column,
                  span: placement.span,
                  ...(placement.rowSpan ? { rowSpan: placement.rowSpan } : {}),
                }),
              ),
            },
          })),
          templateRef:
            state.composition.strategy === "template-import"
              ? "[Template or playbook reference.]"
              : null,
        };
      }
      if (state.overview) {
        next.overview = {
          sectionId: maps.section[state.overview.sectionId],
          contextUnitIds: mappedIds(state.overview.contextUnitIds, maps.unit),
          questionUnitId: maps.unit[state.overview.questionUnitId],
          answerUnitId: maps.unit[state.overview.answerUnitId],
          topics: (state.overview.topics || []).map((topic) => ({
            unitId: maps.unit[topic.unitId],
            targetSectionId: maps.section[topic.targetSectionId],
          })),
          ...(state.overview.groups
            ? {
                groups: state.overview.groups.map((group, index) => ({
                  label: `Topic group ${index + 1}`,
                  topicUnitIds: mappedIds(group.topicUnitIds, maps.unit),
                })),
              }
            : {}),
        };
      }
      if (Array.isArray(state.claims)) {
        next.claims = state.claims.map((claim) => {
          const nextClaim = {
            id: maps.claim[claim.id],
            text:
              claim.kind === "context"
                ? "[Context the reader needs.]"
                : "[Material claim the artifact communicates.]",
            kind: claim.kind,
            sourceIds: mappedIds(claim.sourceIds, maps.source),
            placement: claim.placement,
            evidenceIds: mappedIds(claim.evidenceIds, maps.evidence),
          };
          if (claim.omissionReason != null)
            nextClaim.omissionReason =
              "[Why this claim belongs in detail or is omitted.]";
          return nextClaim;
        });
      }
      maps.orders.unit.forEach((id) => {
        if (state.units && state.units[id])
          next.units[maps.unit[id]] = templateUnit(id, maps);
      });
      maps.orders.evidence.forEach((id) => {
        if (state.evidence && state.evidence[id])
          next.evidence[maps.evidence[id]] = templateEvidence(
            state.evidence[id],
            maps,
          );
      });
      return next;
    }
    function sanitizeTemplateDOM(cloneRoot, nextState, maps) {
      const unitMap = Object.assign(Object.create(null), maps.unit);
      const sectionMap = Object.assign(Object.create(null), maps.section);
      const referenceMap = Object.assign(Object.create(null), maps.evidence);
      const classMap = Object.create(null);
      const mappedReferenceValues = Object.keys(referenceMap).reduce(
        (values, key) => {
          values[referenceMap[key]] = true;
          return values;
        },
        Object.create(null),
      );
      let nextUnitIndex = Object.keys(unitMap).length;
      let nextSectionIndex = Object.keys(sectionMap).length;
      let nextDetailIndex = 0;
      function mappedDOMId(map, oldId, prefix, nextIndex) {
        if (Object.hasOwn(map, oldId)) return map[oldId];
        const value = prefix + "-" + nextIndex();
        map[oldId] = value;
        return value;
      }
      function mappedReference(oldId) {
        if (Object.hasOwn(referenceMap, oldId)) return referenceMap[oldId];
        if (mappedReferenceValues[oldId]) return oldId;
        return mappedDOMId(referenceMap, oldId, "detail", () => {
          nextDetailIndex += 1;
          const id = nextDetailIndex;
          mappedReferenceValues["detail-" + id] = true;
          return id;
        });
      }
      function rewriteAttributeSelectorMap(css, attribute, map) {
        const staged = [];
        let prefix = "__ld_attribute_stage__";
        while (css.includes(prefix)) prefix = "_" + prefix;
        Object.keys(map).forEach((oldValue, index) => {
          const temporary = prefix + attribute + "-" + index;
          css = rewriteAttributeSelector(css, attribute, oldValue, temporary);
          staged.push([temporary, map[oldValue]]);
        });
        staged.forEach((entry) => {
          css = rewriteAttributeSelector(css, attribute, entry[0], entry[1]);
        });
        return css;
      }
      function rewriteClassSelectorMap(css, map) {
        const staged = [];
        let prefix = "__ld_class_stage__";
        while (css.includes(prefix)) prefix = "_" + prefix;
        Object.keys(map).forEach((oldValue, index) => {
          const temporary = prefix + index;
          const escaped = oldValue.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
          css = css.replace(
            new RegExp("\\." + escaped + "(?![A-Za-z0-9_-])", "g"),
            "." + temporary,
          );
          staged.push([temporary, map[oldValue]]);
        });
        staged.forEach((entry) => {
          // Stage 1 must not also replace stage 10, 11, ... . A substring
          // replacement silently detaches CSS from larger template class maps.
          const escaped = entry[0].replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
          css = css.replace(
            new RegExp("\\." + escaped + "(?![A-Za-z0-9_-])", "g"),
            "." + entry[1],
          );
        });
        return css;
      }
      function remapIdReferences(oldId, newId) {
        if (!oldId || oldId === newId) return;
        all(
          "[for],[aria-controls],[aria-labelledby],[aria-describedby]",
          cloneRoot,
        ).forEach((node) => {
          [
            "for",
            "aria-controls",
            "aria-labelledby",
            "aria-describedby",
          ].forEach((name) => {
            if (!node.hasAttribute(name)) return;
            const value = node
              .getAttribute(name)
              .split(/\s+/)
              .map((id) => (id === oldId ? newId : id));
            node.setAttribute(name, value.join(" "));
          });
        });
        all("[href]", cloneRoot).forEach((node) => {
          if (node.getAttribute("href") === "#" + oldId)
            node.setAttribute("href", "#" + newId);
        });
      }
      function rewriteAttributeSelector(css, attribute, oldValue, newValue) {
        [
          `[${attribute}="${oldValue}"]`,
          `[${attribute}='${oldValue}']`,
          `[${attribute}=${oldValue}]`,
        ].forEach((selector, index) => {
          const quote = index === 0 ? '"' : index === 1 ? "'" : "";
          const replacement = `[${attribute}=${quote}${newValue}${quote}]`;
          css = css.split(selector).join(replacement);
        });
        return css;
      }
      function nodePlaceholder(node, fallback) {
        return preferredTemplatePlaceholder(
          node.getAttribute("data-placeholder"),
          fallback,
        );
      }
      function semanticPlaceholder(node, fallback) {
        const name = node.localName;
        let semanticFallback = fallback;
        if (/^h[1-4]$/.test(name)) {
          const id = node.closest("[data-unit]")?.getAttribute("data-unit");
          return templateHeadingPlaceholder(
            nextState.units[id] || state.units[id],
            node,
          );
        }
        if (name === "li") semanticFallback = "[List item.]";
        if (name === "th") semanticFallback = "[Column heading.]";
        if (name === "td") semanticFallback = "[Table value.]";
        if (name === "caption") semanticFallback = "[What the table shows.]";
        if (name === "dt") semanticFallback = "[Term or category.]";
        if (name === "dd") semanticFallback = "[What it means.]";
        return nodePlaceholder(node, semanticFallback);
      }
      function scrubEditableStructure(body, heading, fallback) {
        const editables = all("[data-editable]", body);
        if (body.matches("[data-editable]")) editables.unshift(body);
        const scrubbed = new Set();
        editables.forEach((editable) => {
          if (editable === heading || scrubbed.has(editable)) return;
          if (!editable.children.length) {
            const placeholder = semanticPlaceholder(editable, fallback);
            editable.setAttribute("data-placeholder", placeholder);
            editable.textContent = placeholder;
            scrubbed.add(editable);
            return;
          }
          let semantic = all("h1,h2,h3,h4,p,li,td,th,caption,dt,dd", editable);
          if (editable.matches("h1,h2,h3,h4,p,li,td,th,caption,dt,dd"))
            semantic.unshift(editable);
          semantic = semantic.filter((node) => {
            if (node === editable) return true;
            const ancestor = node.parentElement.closest(
              "h1,h2,h3,h4,p,li,td,th,caption,dt,dd",
            );
            return !ancestor || !editable.contains(ancestor);
          });
          if (!semantic.length)
            semantic = all("span,small,strong,em", editable).filter(
              (node) => !node.querySelector("span,small,strong,em"),
            );
          if (!semantic.length) {
            const placeholder = nodePlaceholder(editable, fallback);
            editable.setAttribute("data-placeholder", placeholder);
            editable.textContent = placeholder;
            scrubbed.add(editable);
            return;
          }
          semantic.forEach((node) => {
            if (node === heading || scrubbed.has(node)) return;
            const placeholder = semanticPlaceholder(node, fallback);
            node.setAttribute("data-placeholder", placeholder);
            node.textContent = placeholder;
            scrubbed.add(node);
          });
        });
        const remaining = all("h1,h2,h3,h4,p,li,td,th,caption,dt,dd", body);
        if (body.matches("h1,h2,h3,h4,p,li,td,th,caption,dt,dd"))
          remaining.unshift(body);
        remaining
          .filter((node) => {
            if (node === heading || scrubbed.has(node)) return false;
            if (node === body) return true;
            const ancestor = node.parentElement.closest(
              "h1,h2,h3,h4,p,li,td,th,caption,dt,dd",
            );
            return !ancestor || !body.contains(ancestor);
          })
          .forEach((node) => {
            const placeholder = semanticPlaceholder(node, fallback);
            node.setAttribute("data-placeholder", placeholder);
            node.textContent = placeholder;
            scrubbed.add(node);
          });
        const walker = document.createTreeWalker(body, NodeFilter.SHOW_TEXT);
        const textNodes = [];
        while (walker.nextNode()) textNodes.push(walker.currentNode);
        textNodes.forEach((textNode) => {
          if (!textNode.textContent.trim()) return;
          const parent = textNode.parentElement;
          if (
            !parent ||
            parent.closest("script,style,.ld-diagram") ||
            parent.closest("h1,h2,h3,h4,p,li,td,th,caption,dt,dd") ||
            validTemplatePlaceholder(textNode.textContent.trim())
          )
            return;
          textNode.textContent = nodePlaceholder(parent, fallback);
        });
      }
      function editedFigureRecords(host) {
        if (!host || !host.hasAttribute("data-editor-preserve-dom"))
          return null;
        const records = all(
          'svg [data-diagram-object],svg g[role="button"]',
          host,
        ).map((node, index) => ({
          key:
            node.getAttribute("data-editor-node-key") || "node-" + (index + 1),
          transform: node.style.transform || "",
          transformBox: node.style.transformBox || "",
          transformOrigin: node.style.transformOrigin || "",
          detail: node.getAttribute("data-detail") || null,
          x: node.getAttribute("data-editor-x") || "0",
          y: node.getAttribute("data-editor-y") || "0",
          sx: node.getAttribute("data-editor-scale-x") || "1",
          sy: node.getAttribute("data-editor-scale-y") || "1",
          fill: FILL_TOKENS.includes(node.getAttribute("data-fill-token"))
            ? node.getAttribute("data-fill-token")
            : null,
          text: TEXT_TOKENS.includes(node.getAttribute("data-text-token"))
            ? node.getAttribute("data-text-token")
            : null,
          labels: ownedFigureLabels(node).map(figureLabelPresentation),
        }));
        records.looseLabels = all("svg text", host)
          .filter(
            (label) => !label.closest('[data-diagram-object],g[role="button"]'),
          )
          .map(figureLabelPresentation);
        return records;
      }
      function ownedFigureLabels(node) {
        return all("text", node).filter(
          (label) =>
            label.closest('[data-diagram-object],g[role="button"]') === node,
        );
      }
      function figureLabelPresentation(label) {
        const styles = {};
        for (const property of [
          "transform",
          "transform-box",
          "transform-origin",
          "font-size",
          "font-weight",
          "font-style",
          "text-decoration-line",
        ]) {
          const value = label.style.getPropertyValue(property);
          if (value && safeTemplateStyleValue(property, value))
            styles[property] = value;
        }
        const geometry = {};
        for (const name of ["x", "y", "scale-x", "scale-y"]) {
          const value = label.getAttribute("data-editor-" + name);
          if (value !== null && Number.isFinite(Number(value)))
            geometry[name] = String(Number(value));
        }
        return {
          styles,
          geometry,
          fill: FILL_TOKENS.includes(label.getAttribute("data-fill-token"))
            ? label.getAttribute("data-fill-token")
            : null,
          text: TEXT_TOKENS.includes(label.getAttribute("data-text-token"))
            ? label.getAttribute("data-text-token")
            : null,
        };
      }
      function restoreFigureLabelPresentation(labels, records) {
        (records || []).forEach((record, index) => {
          const label = labels[index];
          if (!label) return;
          Object.entries(record.styles).forEach(([property, value]) => {
            label.style.setProperty(property, value);
          });
          Object.entries(record.geometry).forEach(([name, value]) => {
            label.setAttribute("data-editor-" + name, value);
          });
          if (record.styles.transform)
            label.setAttribute("data-editor-base-transform", "");
          if (record.fill) label.setAttribute("data-fill-token", record.fill);
          if (record.text) label.setAttribute("data-text-token", record.text);
        });
      }
      function applyEditedFigureRecords(host, records) {
        if (!records) return;
        const clean = all(
          'svg [data-diagram-object],svg g[role="button"]',
          host,
        );
        const grouped = Object.create(null);
        records.forEach((record) => {
          if (!grouped[record.key]) grouped[record.key] = [];
          grouped[record.key].push(record);
        });
        clean.forEach((node, index) => {
          const key = "node-" + (index + 1);
          const matches = grouped[key] || [];
          if (!matches.length) {
            node.remove();
            return;
          }
          let cursor = node;
          matches.forEach((record, copyIndex) => {
            const target = copyIndex ? node.cloneNode(true) : node;
            if (copyIndex) cursor.insertAdjacentElement("afterend", target);
            target.setAttribute("data-editor-node-key", key);
            target.style.transform = record.transform;
            target.style.transformBox = record.transformBox;
            target.style.transformOrigin = record.transformOrigin;
            target.setAttribute("data-editor-x", record.x);
            target.setAttribute("data-editor-y", record.y);
            target.setAttribute("data-editor-scale-x", record.sx);
            target.setAttribute("data-editor-scale-y", record.sy);
            target.setAttribute("data-editor-base-transform", "");
            if (record.detail) {
              target.setAttribute("data-detail", record.detail);
              target.setAttribute("aria-controls", record.detail);
              target.setAttribute("role", "button");
              target.setAttribute("tabindex", "0");
              target.classList.add("ld-detail");
            } else {
              [
                "data-detail",
                "aria-controls",
                "aria-haspopup",
                "role",
                "tabindex",
              ].forEach((attr) => {
                target.removeAttribute(attr);
              });
              target.classList.remove("ld-detail");
            }
            if (record.fill)
              target.setAttribute("data-fill-token", record.fill);
            else target.removeAttribute("data-fill-token");
            if (record.text)
              target.setAttribute("data-text-token", record.text);
            else target.removeAttribute("data-text-token");
            restoreFigureLabelPresentation(
              ownedFigureLabels(target),
              record.labels,
            );
            cursor = target;
          });
        });
        restoreFigureLabelPresentation(
          all("svg text", host).filter(
            (label) => !label.closest('[data-diagram-object],g[role="button"]'),
          ),
          records.looseLabels,
        );
        host.setAttribute("data-editor-preserve-dom", "true");
      }
      const documentTitle = cloneRoot.matches(
        "[data-document-title-placeholder]",
      )
        ? cloneRoot
        : cloneRoot.querySelector("[data-document-title-placeholder]");
      if (documentTitle)
        documentTitle.setAttribute(
          "data-document-title-placeholder",
          "[Matter] · LegalDesign template",
        );
      const title = cloneRoot.querySelector("title");
      if (title)
        title.textContent = documentTitle
          ? documentTitle.getAttribute("data-document-title-placeholder")
          : "[Matter] · LegalDesign template";
      const matter = cloneRoot.querySelector(".ld-matter");
      if (matter) {
        matter.setAttribute(
          "data-placeholder",
          "[Matter or deliverable title.]",
        );
        matter.textContent = "[Matter or deliverable title.]";
      }
      all("[data-placeholder]", cloneRoot).forEach((node) => {
        const fallback = node.hasAttribute("data-card-title")
          ? PLACEHOLDERS.cardTitle
          : node.closest(".ld-diagram")
            ? PLACEHOLDERS.figureLabel
            : PLACEHOLDERS.title;
        const unitId = node.closest("[data-unit]")?.getAttribute("data-unit");
        const placeholder = /^h[1-4]$/.test(node.localName)
          ? templateHeadingPlaceholder(state.units[unitId], node)
          : nodePlaceholder(node, fallback);
        node.setAttribute("data-placeholder", placeholder);
        node.textContent = placeholder;
      });
      all("[data-placeholder-title]", cloneRoot).forEach((node) => {
        const unitId = node.closest("[data-unit]")?.getAttribute("data-unit");
        node.setAttribute(
          "data-placeholder-title",
          templateHeadingPlaceholder(state.units[unitId], node),
        );
      });
      all("[data-placeholder-sub]", cloneRoot).forEach((node) => {
        node.setAttribute(
          "data-placeholder-sub",
          preferredTemplatePlaceholder(
            node.getAttribute("data-placeholder-sub"),
            "[One fact about it, under twenty words.]",
          ),
        );
      });
      all(
        "[data-evidence],[data-detail],[data-evidence-ids]",
        cloneRoot,
      ).forEach((node) => {
        if (node.hasAttribute("data-evidence"))
          node.setAttribute(
            "data-evidence",
            mappedReference(node.getAttribute("data-evidence")),
          );
        if (node.hasAttribute("data-detail"))
          node.setAttribute(
            "data-detail",
            mappedReference(node.getAttribute("data-detail")),
          );
        if (node.hasAttribute("data-evidence-ids"))
          node.setAttribute(
            "data-evidence-ids",
            node
              .getAttribute("data-evidence-ids")
              .split(/\s+/)
              .filter(Boolean)
              .map(mappedReference)
              .join(" "),
          );
      });
      all("[data-section-target]", cloneRoot).forEach((node) => {
        const mapped = sectionMap[node.getAttribute("data-section-target")];
        if (mapped) node.setAttribute("data-section-target", mapped);
        else node.removeAttribute("data-section-target");
      });
      all("[data-composition-section]", cloneRoot).forEach((section) => {
        const oldId = section.getAttribute("data-composition-section");
        if (!Object.hasOwn(sectionMap, oldId)) {
          section.remove();
          return;
        }
        const newId = mappedDOMId(sectionMap, oldId, "section", () => {
          nextSectionIndex += 1;
          return nextSectionIndex;
        });
        section.setAttribute("data-composition-section", newId);
        if (section.hasAttribute("data-index-label"))
          section.setAttribute("data-index-label", "[Section topic]");
        section.setAttribute(
          "aria-label",
          "[What this section enables the reader to understand or do.]",
        );
      });
      all("section.ld-unit[data-unit]", cloneRoot).forEach((section) => {
        const oldId = section.getAttribute("data-unit");
        if (!Object.hasOwn(unitMap, oldId)) {
          section.remove();
          return;
        }
        const id = mappedDOMId(unitMap, oldId, "unit", () => {
          nextUnitIndex += 1;
          return nextUnitIndex;
        });
        section.setAttribute("data-unit", id);
        const unit = nextState.units[id];
        if (!unit) return;
        section.setAttribute("aria-label", unit.claim || unit.placeholder);
        all(".ld-variant", section).forEach((variant) => {
          const key = variant.getAttribute("data-variant");
          const spec = unit.variants && unit.variants[key];
          const existingHosts = all(".ld-diagram", variant);
          const bodies = all("[data-variant-body]", variant).filter(
            (node) => node.parentElement === variant,
          );
          let body = bodies.shift();
          if (!body) {
            body = document.createElement("div");
            body.setAttribute("data-variant-body", "");
            body.setAttribute("data-editable", "");
            variant.appendChild(body);
          }
          let host =
            unit.kind === "figure" ? body.querySelector(".ld-diagram") : null;
          if (!host && unit.kind === "figure") host = existingHosts[0] || null;
          const figureRecords = editedFigureRecords(host);
          if (host && !body.contains(host)) body.appendChild(host);
          bodies.forEach((extra) => {
            extra.remove();
          });
          all(".ld-diagram", variant).forEach((candidate) => {
            if (candidate !== host) candidate.remove();
          });
          if (unit.kind === "figure") {
            Array.from(body.childNodes).forEach((child) => {
              if (child !== host) child.remove();
            });
          }
          if (body && spec && unit.kind !== "figure") {
            const inlineDetails = all(
              ".ld-inline-detail[data-detail]",
              body,
            ).map((link) => ({
              detail: link.getAttribute("data-detail"),
              parent: link.closest("p,li,td,th,dt,dd"),
            }));
            const heading = body.querySelector("[data-card-title]");
            if (heading)
              heading.textContent = templateHeadingPlaceholder(unit, heading);
            scrubEditableStructure(
              body,
              heading,
              unit.placeholder ||
                (unit.kind === "card"
                  ? PLACEHOLDERS.cardLine
                  : PLACEHOLDERS.title),
            );
            // Scrubbing a paragraph replaces its text nodes, including nested
            // phrase links. Restore only the existing targets, with neutral
            // presentation; never resurrect a user-removed popup or its copy.
            inlineDetails.forEach(({ detail, parent }) => {
              const existing = parent && body.contains(parent);
              const line = existing ? parent : document.createElement("p");
              const link = document.createElement("button");
              link.type = "button";
              link.className = "ld-inline-detail";
              link.setAttribute("data-detail", detail);
              link.setAttribute("aria-haspopup", "dialog");
              link.textContent = existing
                ? line.textContent
                : "[Open the supporting explanation.]";
              // Keep the original paragraph slot. Appending a second copy
              // adds unplanned rows and can overflow a previously fitted page.
              line.replaceChildren(link);
              if (!existing) {
                line.className = "ld-detail-linkline";
                body.appendChild(line);
              }
            });
          }
          if (!host && spec && unit.kind === "figure") {
            host = document.createElement("div");
            host.className = "ld-diagram";
            body.appendChild(host);
          }
          if (host && unit.kind === "figure") {
            const oldHostId = host.id;
            const nextHostId = "diagram-" + id + "-" + (key || "a");
            host.id = nextHostId;
            remapIdReferences(oldHostId, nextHostId);
          }
          if (host && spec && spec.component) {
            host.innerHTML = LD.render(spec.component, spec.params, {
              ariaLabel: unit.placeholder || PLACEHOLDERS.figureLabel,
            });
            applyEditedFigureRecords(host, figureRecords);
            annotateDiagramLabels(host, spec.params);
          } else if (host && spec && unit.kind === "figure") {
            host.removeAttribute("data-editor-preserve-dom");
            host.innerHTML =
              '<svg viewBox="0 0 800 420" role="img" aria-label="[Illustration or diagram supplied for this field.]"><rect width="799" height="419" x=".5" y=".5" fill="var(--card)" stroke="var(--line-strong)"/><text x="400" y="210" text-anchor="middle" fill="currentColor" font-family="Helvetica,Arial,sans-serif" font-size="20">[Illustration or diagram supplied for this field.]</text></svg>';
          }
        });
        const why = section.querySelector(".ld-why");
        const selected = unit.variants && unit.variants[unit.selected];
        if (why && selected && selected.why) why.textContent = selected.why;
        all("[data-editable]", section).forEach((node) => {
          if (!node.closest(".ld-variant"))
            node.textContent =
              node.getAttribute("data-placeholder") ||
              (node.hasAttribute("data-card-title")
                ? unit.placeholder_title || PLACEHOLDERS.cardTitle
                : unit.placeholder || PLACEHOLDERS.title);
        });
        if (unit.kind === "decision") {
          section.removeAttribute("data-answered");
          const tag = section.querySelector(".tag");
          if (tag && unit.tag) tag.textContent = unit.tag;
          const question = section.querySelector(".ld-decision h3,h2");
          if (question && unit.question) question.textContent = unit.question;
          all("[data-decision-option]", section).forEach((button, index) => {
            const option = (unit.options || [])[index];
            if (!option) return;
            button.setAttribute("value", option.key);
            button.setAttribute("aria-pressed", "false");
            const key = button.querySelector("strong");
            const legacyLabel = button.querySelector("b");
            const label = button.querySelector("span");
            const consequence = button.querySelector("small");
            if (key) key.textContent = "Option " + (index + 1);
            if (legacyLabel) legacyLabel.textContent = option.label;
            if (label)
              label.textContent = consequence
                ? option.label
                : option.consequence;
            if (consequence) consequence.textContent = option.consequence;
            if (!key && !legacyLabel && !label && !consequence)
              button.textContent = option.label;
          });
        }
        all(".ld-evidence-trigger", section).forEach((trigger) => {
          trigger.textContent = "Source: [Citation or record label.]";
        });
        const walker = document.createTreeWalker(section, NodeFilter.SHOW_TEXT);
        const textNodes = [];
        while (walker.nextNode()) textNodes.push(walker.currentNode);
        textNodes.forEach((textNode) => {
          const value = textNode.textContent.trim();
          if (!value || validTemplatePlaceholder(value)) return;
          const parent = textNode.parentElement;
          if (
            !parent ||
            parent.closest(
              "script,style,.ld-unit-tools,.ld-diagram,.ld-why,[data-decision-option],.ld-evidence-trigger",
            ) ||
            parent.closest("[data-placeholder]")
          )
            return;
          textNode.textContent = unit.placeholder || PLACEHOLDERS.title;
        });
      });
      all("[data-variant-body] [class]", cloneRoot).forEach((node) => {
        if (node.closest(".ld-diagram")) return;
        const next = node
          .getAttribute("class")
          .split(/\s+/)
          .filter(Boolean)
          .map((name) => {
            if (
              name.startsWith("ld-") ||
              ["cite", "tag", "action"].includes(name)
            )
              return name;
            if (!Object.hasOwn(classMap, name))
              classMap[name] =
                "template-class-" + (Object.keys(classMap).length + 1);
            return classMap[name];
          });
        if (next.length) node.setAttribute("class", next.join(" "));
        else node.removeAttribute("class");
      });
      all("section.ld-unit [data-variant-body] img", cloneRoot).forEach(
        (image) => {
          const replacement = document.createElementNS(
            "http://www.w3.org/2000/svg",
            "svg",
          );
          const sourcePreview = image.closest(".ld-source-preview");
          const originalImage = sourcePreview
            ? all(".ld-source-preview img").find(
                (node) =>
                  node.getAttribute("src") === image.getAttribute("src"),
              )
            : null;
          const width = originalImage?.naturalWidth || 800;
          const height = originalImage?.naturalHeight || 420;
          replacement.setAttribute("viewBox", `0 0 ${width} ${height}`);
          replacement.setAttribute("role", "img");
          replacement.setAttribute(
            "aria-label",
            "[Illustration or source image supplied for this field.]",
          );
          replacement.innerHTML = `<rect width="${width - 1}" height="${height - 1}" x=".5" y=".5" fill="var(--card)" stroke="var(--line-strong)"/><text x="${width / 2}" y="${height / 2}" dominant-baseline="middle" text-anchor="middle" fill="currentColor" font-family="Helvetica,Arial,sans-serif" font-size="${Math.min(20, height / 2)}">${sourcePreview ? "[Source clip.]" : "[Illustration or source image supplied for this field.]"}</text>`;
          image.replaceWith(replacement);
        },
      );
      const safeInternalPages = new Set(
        all("[id][data-frame]", cloneRoot)
          .map((node) => node.id)
          .filter((id) => /^p\d+$/.test(id)),
      );
      all("[data-page]", cloneRoot).forEach((node) => {
        if (!safeInternalPages.has(node.getAttribute("data-page")))
          node.removeAttribute("data-page");
      });
      const allowedMatterData = new Set([
        "data-card-title",
        "data-decision-custom",
        "data-decision-note",
        "data-decision-option",
        "data-detail",
        "data-editable",
        "data-diagram-label",
        "data-evidence-field",
        "data-evidence-id",
        "data-editor-node-key",
        "data-editor-object",
        "data-diagram-object",
        "data-editor-preserve-dom",
        "data-evidence",
        "data-fill-token",
        "data-placeholder",
        "data-placeholder-sub",
        "data-placeholder-title",
        "data-page",
        "data-text-token",
        "data-variant-body",
      ]);
      all(
        "section.ld-unit [data-variant-body],section.ld-unit [data-variant-body] *",
        cloneRoot,
      ).forEach((node) => {
        if (node.closest(".ld-diagram")) return;
        Array.from(node.attributes).forEach((attribute) => {
          const name = attribute.name.toLowerCase();
          if (name === "id") {
            node.removeAttribute(name);
            return;
          }
          if (name === "title" || name === "aria-description") {
            node.setAttribute(name, "[Accessible description.]");
            return;
          }
          if (name === "alt") {
            node.setAttribute(name, "[Accessible description.]");
            return;
          }
          if (name === "src" || name === "srcset") {
            node.removeAttribute(name);
            return;
          }
          if (name.startsWith("data-") && !allowedMatterData.has(name))
            node.removeAttribute(name);
        });
      });
      const allowedUnitData = new Set([
        "data-answered",
        "data-detail",
        "data-editor-preserve-dom",
        "data-editor-x",
        "data-editor-y",
        "data-evidence",
        "data-fill-token",
        "data-kind",
        "data-role",
        "data-section-target",
        "data-single",
        "data-text-token",
        "data-unit",
      ]);
      all("section.ld-unit[data-unit]", cloneRoot).forEach((section) => {
        Array.from(section.attributes).forEach((attribute) => {
          const name = attribute.name.toLowerCase();
          if (name === "data-role" && !UNIT_ROLES.includes(attribute.value)) {
            section.removeAttribute(name);
            return;
          }
          if (name === "id") {
            section.removeAttribute(name);
            return;
          }
          if (name === "title" || name === "aria-description") {
            section.setAttribute(name, "[Accessible description.]");
            return;
          }
          if (name.startsWith("data-") && !allowedUnitData.has(name))
            section.removeAttribute(name);
        });
      });
      all("section.ld-unit .ld-variant", cloneRoot).forEach((variant) => {
        Array.from(variant.attributes).forEach((attribute) => {
          const name = attribute.name.toLowerCase();
          if (name === "id") {
            variant.removeAttribute(name);
            return;
          }
          if (name === "title" || name === "aria-description") {
            variant.setAttribute(name, "[Accessible description.]");
            return;
          }
          if (name.startsWith("data-") && name !== "data-variant")
            variant.removeAttribute(name);
        });
      });
      all("main [title],#popup-scrim [title]", cloneRoot).forEach((node) => {
        node.setAttribute("title", "[Accessible description.]");
      });
      const main = cloneRoot.querySelector("main");
      if (main) {
        const walker = document.createTreeWalker(main, NodeFilter.SHOW_TEXT);
        const textNodes = [];
        while (walker.nextNode()) textNodes.push(walker.currentNode);
        textNodes.forEach((textNode) => {
          const value = textNode.textContent.trim();
          if (!value || validTemplatePlaceholder(value)) return;
          const parent = textNode.parentElement;
          if (
            !parent ||
            parent.closest(
              "script,style,section.ld-unit,#ld-form-navigation,#ld-page-approach,.ld-diagram",
            ) ||
            parent.closest("[data-placeholder]")
          )
            return;
          textNode.textContent = "[The value or fact this block communicates.]";
        });
      }
      // Reconstruct navigation chrome after generic matter-text scrubbing.
      // Do not preserve an edited label or count as a purported safe value.
      all(".ld-index-group", cloneRoot).forEach((group, index) => {
        group.open = false;
        const summary = group.querySelector(":scope > summary");
        if (summary) summary.textContent = `Topic group ${index + 1}`;
      });
      all(".ld-overview-groups", cloneRoot).forEach((container) => {
        all(":scope > .ld-overview-group", container).forEach(
          (group, index) => {
            group.open = index === 0;
            group.setAttribute("data-overview-group", String(index));
            const label = group.querySelector(".ld-overview-group-label");
            if (label) {
              label.textContent = `Topic group ${index + 1}`;
              label.setAttribute("data-overview-group-label", String(index));
            }
            const count = group.querySelector(".ld-overview-group-count");
            const total =
              nextState.overview?.groups?.[index]?.topicUnitIds.length || 0;
            if (count)
              count.textContent = `${total} ${total === 1 ? "topic" : "topics"}`;
          },
        );
      });
      // The issue anatomy teaches the same three jobs after matter removal.
      // Fixed semantic labels, not arbitrary author headings, survive export.
      all(".ld-issue-analysis", cloneRoot).forEach((column) => {
        const labels = [
          "[Statement or finding.]",
          "[Why it matters.]",
          "[Recommendation or next check.]",
        ];
        all(":scope > section.ld-unit", column).forEach((unit, index) => {
          const heading = unit.querySelector("h2,h3");
          if (!heading || !labels[index]) return;
          heading.textContent = labels[index];
          heading.setAttribute("data-placeholder", labels[index]);
        });
      });
      all(".ld-source-preview", cloneRoot).forEach((preview) => {
        const heading = preview.querySelector("h2,h3");
        const quote = preview.querySelector("blockquote");
        const caption = preview.querySelector("figcaption");
        for (const [node, label] of [
          [heading, "[Source passage.]"],
          [quote, "[Exact supporting excerpt, with its qualification.]"],
          [caption, "[Source, locator and review status.]"],
        ]) {
          if (!node) continue;
          node.textContent = label;
          node.setAttribute("data-placeholder", label);
        }
      });
      restoreTrustedTemplateStyles(cloneRoot);
      all("style", cloneRoot).forEach((style) => {
        let css = style.textContent;
        css = rewriteAttributeSelectorMap(css, "data-unit", unitMap);
        css = rewriteAttributeSelectorMap(
          css,
          "data-composition-section",
          sectionMap,
        );
        css = rewriteClassSelectorMap(css, classMap);
        style.textContent = css;
      });
      all("#popup-scrim .pop", cloneRoot).forEach((pop) => {
        const oldId = pop.id;
        const newId = mappedReference(oldId);
        const tag = pop.querySelector(".tag");
        const heading = pop.querySelector("h2");
        const desc = pop.querySelector(".desc");
        remapIdReferences(oldId, newId);
        remapIdReferences(oldId + "-title", newId + "-title");
        pop.id = newId;
        pop.setAttribute("data-evidence-id", newId);
        pop.setAttribute("aria-labelledby", newId + "-title");
        if (tag) tag.textContent = "[Citation or record label.]";
        if (heading) {
          heading.id = newId + "-title";
          heading.textContent =
            "[What this source establishes, in one sentence.]";
        }
        if (desc)
          desc.textContent =
            "[Two sentences that tell the reader what they are looking at.]";
        all(".doc-text", pop).forEach((node) => {
          node.textContent =
            "[Verbatim excerpt of the controlling clause, in the document's words.]";
        });
        all("blockquote", pop).forEach((node) => {
          node.textContent =
            "[Verbatim excerpt of the controlling clause, in the document's words.]";
        });
        all(".doc-cl", pop).forEach((node) => {
          node.textContent = "[Section and page.]";
        });
        all(".doc-foot,.ld-popup-source", pop).forEach((node) => {
          node.textContent = "[Source, version, date retrieved.]";
        });
        const evidencePlaceholders = {
          cite: "[Citation or record label.]",
          locator: "[Section and page.]",
          detail:
            "[Verbatim excerpt of the controlling clause, in the document's words.]",
          "popup.title": "[The question or insight this popup explains.]",
          "popup.lede": "[One-sentence orientation to the deeper detail.]",
        };
        all("[data-evidence-field]", pop).forEach((node) => {
          const field = node.getAttribute("data-evidence-field");
          const sectionField = /^popup\.sections\.\d+\.(heading|body)$/.exec(
            field,
          );
          const placeholder =
            evidencePlaceholders[field] ||
            (sectionField && sectionField[1] === "heading"
              ? "[Specific subpoint.]"
              : sectionField
                ? "[The deeper detail the reader needs here.]"
                : null);
          if (!placeholder) return;
          node.setAttribute("data-placeholder", placeholder);
          node.textContent = placeholder;
        });
        all("img", pop).forEach((image) => {
          const svg = document.createElementNS(
            "http://www.w3.org/2000/svg",
            "svg",
          );
          svg.setAttribute("viewBox", "0 0 800 420");
          svg.setAttribute("role", "img");
          svg.setAttribute(
            "aria-label",
            "[Clip of the source page with the cited passage highlighted.]",
          );
          svg.innerHTML =
            '<rect width="799" height="419" x=".5" y=".5" fill="var(--card)" stroke="var(--line-strong)"/><text x="400" y="210" text-anchor="middle" fill="currentColor" font-family="Helvetica,Arial,sans-serif" font-size="20">[Clip of the source page with the cited passage highlighted.]</text>';
          image.replaceWith(svg);
        });
        all("a", pop).forEach((link) => {
          link.setAttribute("href", "#");
          link.removeAttribute("target");
          link.removeAttribute("rel");
          link.textContent = "[Open the clause in the source document.]";
        });
        all(".out,.ld-source-unavailable", pop).forEach((source) => {
          if (!source.querySelector("a"))
            source.textContent =
              "[Original source unavailable in this template.]";
        });
      });
      const safeLabels = [
        "Close source popup",
        "Theme",
        "Edit",
        "Export HTML",
        "Export template",
        "Save",
        "Undo",
        "Redo",
        "Duplicate",
        "Delete",
        "Bold",
        "Italic",
        "Underline",
        "Increase type",
        "Decrease type",
        "Reset",
        "More",
        "Treatment",
        "Treatment A",
        "Treatment B",
        "Fill token",
        "Text token",
        "Custom position",
        "Note",
        "Previous slide",
        "Next slide",
        "Slide navigation",
        "Select slide",
        "Report sections",
        "Contents",
        "Collapse contents",
        "Expand contents",
        "Open contents",
        "Previous page",
        "Next page",
        "Previous section",
        "Next section",
      ];
      all("[aria-label]", cloneRoot).forEach((node) => {
        const value = node.getAttribute("aria-label");
        if (value && !safeLabels.includes(value))
          node.setAttribute("aria-label", "[Accessible description.]");
      });
      all("a[href]", cloneRoot).forEach((link) => {
        link.setAttribute("href", "#");
        link.removeAttribute("target");
        link.removeAttribute("rel");
        if (link.closest("#popup-scrim")) return;
        const internal =
          link.hasAttribute("data-page") ||
          link.hasAttribute("data-frame-button") ||
          link.hasAttribute("data-evidence") ||
          link.hasAttribute("data-detail");
        if (internal && link.children.length) return;
        if (
          link.hasAttribute("data-evidence") ||
          link.hasAttribute("data-detail")
        )
          link.textContent = "[Open the source.]";
        else if (internal) link.textContent = "[Open the relevant section.]";
        else link.textContent = "[Link.]";
      });
      all("[data-decision-custom],[data-decision-note]", cloneRoot).forEach(
        (input) => {
          input.value = "";
          input.setAttribute(
            "aria-label",
            input.hasAttribute("data-decision-custom")
              ? "Custom position"
              : "Note",
          );
        },
      );
      all("[data-report-section]", cloneRoot).forEach((button, index) => {
        button.textContent = "[Section " + (index + 1) + ".]";
      });
      all("#ld-page-approach [data-select-approach]", cloneRoot).forEach(
        (button) => {
          const key =
            button.getAttribute("data-select-approach") === "b" ? "B" : "A";
          button.innerHTML = "<span>" + key + "</span>Page " + key;
        },
      );
      all("[data-zone-doc]", cloneRoot).forEach((node) => {
        node.removeAttribute("data-zone-doc");
      });
      scrubTemplateMatterAttributes(cloneRoot);
    }
    // Compiled away, not merely disabled, in the reader-only export runtime.
    if (
      typeof LEGALDESIGN_CLIENT_BUILD === "undefined" ||
      !LEGALDESIGN_CLIENT_BUILD
    ) {
      let fileHandle = null;
      let exportHandle = null;
      function clientFilename() {
        let stem = state.artifactId;
        let openedName = "";
        if (location.protocol === "file:") {
          try {
            openedName = decodeURIComponent(location.pathname.split("/").pop());
            stem = openedName || stem;
          } catch {
            /* Fall back to the artifact identifier. */
          }
        }
        stem = stem
          .replace(/\.html?$/i, "")
          .replace(/\.(working|editor|client)$/i, "");
        const name = stem + ".client.html";
        return name === openedName ? stem + ".exported.client.html" : name;
      }
      function download(text, name) {
        const blob = new Blob([text], { type: "text/html;charset=utf-8" });
        const link = document.createElement("a");
        link.className = "ld-download-link";
        const url = URL.createObjectURL(blob);
        link.href = url;
        link.download = name;
        link.hidden = true;
        link.setAttribute("data-editor-chrome", "");
        document.body.appendChild(link);
        try {
          link.click();
        } catch (error) {
          link.remove();
          URL.revokeObjectURL(url);
          throw error;
        }
        // The browser consumes a Blob asynchronously. Do not revoke it in the
        // same task that requests the download, or assume the request reached disk.
        setTimeout(() => {
          link.remove();
          URL.revokeObjectURL(url);
        }, 60000);
      }
      let fileWriteInProgress = false;
      let clientPreviewURL = null;
      function clearSaveBanner() {
        const old = document.querySelector(".ld-save-banner");
        if (old) old.remove();
        if (clientPreviewURL) {
          URL.revokeObjectURL(clientPreviewURL);
          clientPreviewURL = null;
        }
      }
      async function persistHTML(
        html,
        name,
        reuseWorkingHandle = false,
        clientPreview = false,
      ) {
        if (fileWriteInProgress) {
          showSaveBanner(
            "A save is already in progress. Finish that save first.",
            8000,
          );
          return "busy";
        }
        fileWriteInProgress = true;
        clearSaveBanner();
        let writable;
        try {
          if (typeof window.showSaveFilePicker === "function") {
            try {
              // Invoke the picker before the first await, while the button's
              // user activation is still available. Exports never reuse the
              // working-copy handle or overwrite it without a fresh choice.
              const handle =
                reuseWorkingHandle && fileHandle
                  ? fileHandle
                  : await window.showSaveFilePicker({
                      id: "legaldesign-html",
                      ...(fileHandle || exportHandle
                        ? { startIn: fileHandle || exportHandle }
                        : {}),
                      suggestedName: name,
                      types: [
                        {
                          description: "HTML file",
                          accept: { "text/html": [".html"] },
                        },
                      ],
                    });
              writable = await handle.createWritable();
              await writable.write(html);
              await writable.close();
              writable = null;
              if (reuseWorkingHandle) fileHandle = handle;
              else exportHandle = handle;
              showSaveBanner(
                `Saved ${handle.name || name} to the location you chose.${clientPreview ? " Open a preview of this exact exported copy below." : ""}`,
                clientPreview ? 0 : 8000,
                clientPreview ? html : null,
              );
              return "saved";
            } catch (error) {
              if (writable && typeof writable.abort === "function") {
                try {
                  await writable.abort();
                } catch {
                  /* Preserve the original failure. */
                }
                writable = null;
              }
              if (error && error.name === "AbortError") {
                showSaveBanner(
                  "Save canceled. Your open work is unchanged.",
                  8000,
                );
                return "canceled";
              }
              if (reuseWorkingHandle) fileHandle = null;
            }
          }
          download(html, name);
          showSaveBanner(
            `Download requested: ${name}. Check your browser's download location; this page cannot confirm it reached disk. Your open work is unchanged.${clientPreview ? " The link opens a preview of this exact exported copy, not the saved disk file." : ""}`,
            clientPreview ? 0 : 16000,
            clientPreview ? html : null,
          );
          return "download-requested";
        } catch {
          showSaveBanner(
            "The file could not be saved. Your open work is unchanged. Try Save or Export again and choose a writable location.",
            16000,
          );
          return "failed";
        } finally {
          fileWriteInProgress = false;
        }
      }
      function stripAuthoringData(cloneRoot) {
        // data-variant-body is a presentation wrapper: shared copy spacing and
        // popup-text affordances depend on it even in a read-only client export.
        const names = [
          "data-card-title",
          "data-document-title-placeholder",
          "data-editable",
          "data-diagram-label",
          "data-evidence-field",
          "data-evidence-id",
          "data-editor-base-transform",
          "data-editor-scale-x",
          "data-editor-scale-y",
          "data-editor-node-key",
          "data-editor-origin-fill-token",
          "data-editor-origin-fill-token-present",
          "data-editor-origin-style",
          "data-editor-origin-style-present",
          "data-editor-origin-style-stamped",
          "data-editor-origin-text-token",
          "data-editor-origin-text-token-present",
          "data-editor-only",
          "data-editor-preserve-dom",
          "data-editor-unit",
          "data-editor-x",
          "data-editor-y",
          "data-export-chrome",
          "data-export-protect",
          "data-placeholder",
          "data-param-path",
          "data-single",
          "data-zone-doc",
        ];
        all("*", cloneRoot)
          .concat([cloneRoot])
          .forEach((node) => {
            names.forEach((name) => {
              node.removeAttribute(name);
            });
          });
      }
      LD.exportHTML = (shouldDownload) => {
        all('[contenteditable="true"]').forEach((node) => {
          node.blur();
        });
        // The previous transfer's notice is editor chrome, not part of the next
        // deliverable. Release its reserved space before checking page geometry.
        clearSaveBanner();
        fitFixedPages();
        if (!validateExportPageFit(false))
          throw new Error(
            "Page exceeds the available window. Move detail to a popup or another page before exporting.",
          );
        const cloneRoot = document.documentElement.cloneNode(true);
        scrubEditing(cloneRoot);
        cloneRoot.setAttribute("data-exported", "client");
        const clientBlueprintId =
          "legaldesign-client-" + stableLocationHash(state.artifactId);
        cloneRoot.setAttribute("data-client-blueprint-id", clientBlueprintId);
        all("#export-html,#export-template", cloneRoot).forEach((node) => {
          node.remove();
        });
        all("[data-placeholder],[data-placeholder-title]", cloneRoot).forEach(
          (node) => {
            node.removeAttribute("data-placeholder");
            node.removeAttribute("data-placeholder-title");
          },
        );
        if (state.approaches) {
          const selectedApproach = currentApproach();
          all("[data-approach]", cloneRoot).forEach((page) => {
            if (page.getAttribute("data-approach") !== selectedApproach)
              page.remove();
            else page.hidden = false;
          });
          const approachControl = cloneRoot.querySelector("#ld-page-approach");
          if (approachControl) approachControl.remove();
        }
        all("section.ld-unit[data-unit]", cloneRoot).forEach((section) => {
          const sourceUnit = unitState(section.getAttribute("data-unit"));
          if (!sourceUnit) {
            section.remove();
            return;
          }
          const selected = sourceUnit.selected;
          all(".ld-variant", section).forEach((variant) => {
            if (variant.getAttribute("data-variant") !== selected)
              variant.remove();
            else variant.hidden = false;
          });
          all(
            ".ld-ab,.ld-why,.ld-unit-tools,.ld-review,.ld-sheet-open",
            section,
          ).forEach((node) => {
            node.remove();
          });
        });
        all("[data-editor-only]", cloneRoot).forEach((node) => {
          node.remove();
        });
        const referenced = new Set(
          all("[data-evidence],[data-detail],[data-evidence-ids]", cloneRoot)
            .filter((node) => !node.closest("#popup-scrim"))
            .flatMap((node) => {
              const grouped = node.getAttribute("data-evidence-ids");
              if (grouped) return grouped.split(/\s+/).filter(Boolean);
              return [
                node.getAttribute("data-evidence") ||
                  node.getAttribute("data-detail"),
              ].filter(Boolean);
            }),
        );
        // A purposeful detail popup can link onward to an original source popup.
        // Keep that whole reachable chain, not only the first surface hop.
        for (const id of referenced) {
          const pop = all("#popup-scrim .pop[id]", cloneRoot).find(
            (node) => node.id === id,
          );
          if (!pop) continue;
          all("[data-detail],[data-evidence],[data-evidence-ids]", pop).forEach(
            (node) => {
              const ids = node.getAttribute("data-evidence-ids");
              (ids
                ? ids.split(/\s+/)
                : [
                    node.getAttribute("data-detail") ||
                      node.getAttribute("data-evidence"),
                  ]
              )
                .filter(Boolean)
                .forEach((target) => {
                  referenced.add(target);
                });
            },
          );
        }
        all("#popup-scrim .pop[id]", cloneRoot).forEach((pop) => {
          if (!referenced.has(pop.id)) pop.remove();
        });
        const clientState = reducedClientState(cloneRoot, clientBlueprintId);
        stripAuthoringData(cloneRoot);
        const readerPayload = cloneRoot.querySelector("#ld-client-runtime");
        const runtimeScript = cloneRoot.querySelector("#ld-runtime");
        if (!readerPayload || !runtimeScript)
          throw new Error(
            "Reader runtime is missing. Rebuild with the current LegalDesign assets before exporting.",
          );
        runtimeScript.textContent = JSON.parse(readerPayload.textContent);
        runtimeScript.removeAttribute("data-source-sha256");
        runtimeScript.removeAttribute("data-output-sha256");
        readerPayload.remove();
        all("#ld-response-save", cloneRoot).forEach((node) => {
          node.remove();
        });
        setCloneState(cloneRoot, clientState);
        const html = serializeClone(cloneRoot);
        if (shouldDownload !== false)
          void persistHTML(html, clientFilename(), false, true);
        return html;
      };
      LD.exportTemplate = (shouldDownload, requestedId) => {
        all('[contenteditable="true"]').forEach((node) => {
          node.blur();
        });
        clearSaveBanner();
        fitFixedPages();
        if (!validateExportPageFit(true))
          throw new Error(
            "Page exceeds the available window. Move detail to a popup or another page before exporting.",
          );
        const templateId = templateExportId(requestedId);
        const cloneRoot = document.documentElement.cloneNode(true);
        cloneRoot.dataset.templateId = templateId;
        if (isPackagedTemplateId(requestedId)) {
          cloneRoot.dataset.templateKind = "packaged";
        } else {
          cloneRoot.dataset.templateKind = "exported";
        }
        cloneRoot.dataset.templateBlueprintId = templateId;
        scrubEditing(cloneRoot);
        cloneRoot.setAttribute("data-exported", "template");
        const maps = templateMappings();
        const nextState = templateState(maps, templateId);
        sanitizeTemplateDOM(cloneRoot, nextState, maps);
        setCloneState(cloneRoot, nextState);
        const html = serializeClone(cloneRoot);
        if (shouldDownload !== false)
          void persistHTML(html, templateId + ".html");
        return html;
      };

      async function saveFile() {
        all('[contenteditable="true"]').forEach((node) => {
          node.blur();
        });
        state.savedAt = new Date().toISOString();
        mirror();
        storeEditorDOM();
        const cloneRoot = document.documentElement.cloneNode(true);
        scrubTransientEditing(cloneRoot);
        setCloneState(cloneRoot, state);
        const html = serializeClone(cloneRoot);
        const saveName = state.artifactId + ".html";
        const result = await persistHTML(html, saveName, true);
        if (result === "saved") clearRestore();
        return result === "canceled" || result === "failed" || result === "busy"
          ? null
          : html;
      }
      function clearRestore() {
        const banner = document.getElementById("ld-restore-banner");
        if (banner) banner.remove();
      }
      function showSaveBanner(
        message,
        duration = 2400,
        clientPreviewHTML = null,
      ) {
        clearSaveBanner();
        const banner = document.createElement("div");
        banner.className = "ld-save-banner";
        banner.setAttribute("role", "status");
        banner.setAttribute("aria-live", "polite");
        banner.setAttribute("data-editor-chrome", "");
        banner.textContent = message;
        if (clientPreviewHTML !== null) {
          clientPreviewURL = URL.createObjectURL(
            new Blob([clientPreviewHTML], { type: "text/html;charset=utf-8" }),
          );
          const link = document.createElement("a");
          link.className = "ld-export-preview";
          link.href = clientPreviewURL;
          link.target = "_blank";
          link.rel = "noopener noreferrer";
          link.textContent = "Open exported HTML";
          banner.appendChild(link);
        }
        const bar = document.querySelector(".ld-bar");
        (bar ? bar.parentNode : document.body).insertBefore(
          banner,
          bar ? bar.nextSibling : document.body.firstChild,
        );
        if (duration > 0)
          setTimeout(() => {
            if (banner.isConnected) clearSaveBanner();
          }, duration);
      }

      LD.save = saveFile;
      const save = document.getElementById("ld-save");
      if (save) save.addEventListener("click", saveFile);
      const html = document.getElementById("export-html");
      if (html) html.addEventListener("click", () => LD.exportHTML(true));
      const template = document.getElementById("export-template");
      if (template)
        template.addEventListener("click", () => LD.exportTemplate(true));
    }

    function bindChrome() {
      const theme = document.getElementById("theme-toggle");
      if (theme)
        theme.addEventListener("click", () => {
          scheduleReady(true);
          applyTheme(
            root.getAttribute("data-theme") === "dark" ? "light" : "dark",
            true,
          );
        });
    }

    LD.state = () => clone(state);
    LD.setState = (next) => {
      if (!next || next.schema !== "legaldesign.state.v1")
        throw new TypeError("state must use legaldesign.state.v1");
      checkpoint();
      state = clone(next);
      mirror();
      renderAll({ sync: false });
      storeEditorDOM();
    };
    LD.setMode = setMode;
    LD.setApproach = setApproach;
    LD.openPopup = openPopup;
    LD.closePopup = closePopup;
    LD.bindDecisions = bindDecisions;
    LD.placeholderDerivation = clone(PLACEHOLDERS);

    scrubTransientEditing(root);
    normalizeChrome();
    applyTheme(initialTheme(), false);
    removeLegacyReviewChrome();
    installFixedPages();
    renderAll();
    bindApproaches();
    bindUnits();
    bindDecisions();
    bindPopups();
    installComposedForm();
    bindEditor();
    bindChrome();
    installRestoreBanner();
    updateEditorButtons();
    scheduleReady(false);
    // Phones land in the existing readable view, not an illegible miniature.
    // Run once at load; deliberately closing it keeps the canvas available.
    if (
      singleComposition() &&
      window.matchMedia("(max-width: 760px)").matches
    ) {
      requestAnimationFrame(() => {
        if (!editing && !activePopup())
          openPageReader(document.getElementById("ld-read-page"));
      });
    }
  }

  if (document.readyState === "loading")
    document.addEventListener("DOMContentLoaded", boot, { once: true });
  else boot();
})();
