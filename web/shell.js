/* uCANdo shell kit — window.UI
 *
 * The house frame (user skill `utility-ui`), ported from Runway's web/shell.js
 * for a single page whose views swap client-side. Runway's version builds the
 * banner per HTML page and folds each page's <header> into it; here the banner
 * and rail are static markup in index.html and app.js builds the rail items
 * from its one NAV definition. What this file owns:
 *
 *   icons      the ONE icon map (Feather-style line icons, inline SVG). Nothing
 *              else in web/ may carry an <svg> of its own — test_ui enforces it.
 *   theme      Auto | Light | Dark, remembered ("ucando.theme"); Auto follows
 *              the OS and re-resolves when it changes. The <head> boot script in
 *              index.html applies the same rule before the first paint.
 *   rail       Sidebar control: Expanded | Collapsed | Expand on hover
 *              ("ucando.rail"); always Expand on hover under 1000px.
 *   hold-tips  [data-tip] shows after the pointer rests 5 s — help for whoever
 *              lingers, invisible to everyone else. Never the native title.
 *   resizable  drag an edge between a min and a max, remembered, double-click
 *              resets, arrow keys move it.
 *   dialogs    confirm / notice / prompt on <dialog> — never window.confirm.
 *   menu       a small menu under a button (Sidebar control's look).
 *   toast      a transient line, bottom right (what the old status bar said).
 *
 * Every localStorage access is wrapped: a private window or blocked site data
 * throws, and the page must still render.
 */
"use strict";
(function () {
  // ---- storage --------------------------------------------------------------------------------
  const store = {
    get(k, d) {
      try { const v = localStorage.getItem("ucando." + k); return v == null ? d : v; } catch (e) { return d; }
    },
    set(k, v) {
      try {
        if (v == null) localStorage.removeItem("ucando." + k); else localStorage.setItem("ucando." + k, String(v));
      } catch (e) { /* private mode */ }
    },
  };

  // ---- icons: one consistent line family, sized by the control around it ---------------------
  const B = {
    // views
    "dashboard": '<rect x="3" y="3" width="7" height="9" rx="1"/><rect x="14" y="3" width="7" height="5" rx="1"/><rect x="14" y="12" width="7" height="9" rx="1"/><rect x="3" y="16" width="7" height="5" rx="1"/>',
    "list": '<path d="M8 6h13"/><path d="M8 12h13"/><path d="M8 18h13"/><circle cx="3.5" cy="6" r="1"/><circle cx="3.5" cy="12" r="1"/><circle cx="3.5" cy="18" r="1"/>',
    "replay": '<path d="M3 12a9 9 0 1 0 3-6.7"/><path d="M3 4v5h5"/><path d="m10.5 9 4.5 3-4.5 3Z"/>',
    "activity": '<path d="M22 12h-4l-3 9L9 3l-3 9H2"/>',
    "chip": '<rect x="6" y="6" width="12" height="12" rx="2"/><path d="M9 2v4M15 2v4M9 18v4M15 18v4M2 9h4M2 15h4M18 9h4M18 15h4"/>',
    "grid": '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18"/><path d="M3 15h18"/><path d="M9 3v18"/><path d="M15 3v18"/>',
    "swap": '<path d="M7 4 3 8l4 4"/><path d="M3 8h13"/><path d="M17 12l4 4-4 4"/><path d="M21 16H8"/>',
    "layers": '<path d="m12 2 10 5-10 5L2 7Z"/><path d="m2 17 10 5 10-5"/><path d="m2 12 10 5 10-5"/>',
    "database": '<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v7c0 1.7 3.6 3 8 3s8-1.3 8-3V5"/><path d="M4 12v7c0 1.7 3.6 3 8 3s8-1.3 8-3v-7"/>',
    "trending": '<path d="m22 6-8.5 9.5-5-5L1 18"/><path d="M16 6h6v6"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "bolt": '<path d="M13 2 4 14h7l-1 8 9-12h-7Z"/>',
    "triangle": '<path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
    "code": '<path d="m16 18 6-6-6-6"/><path d="m8 6-6 6 6 6"/>',
    // frame
    "brand": '<path d="M3 13h3.5l2.5-6 4 10 2.5-6H21"/>',
    "sidebar": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16"/>',
    "settings": '<path d="M4 7h8"/><path d="M16 7h4"/><circle cx="14" cy="7" r="2"/><path d="M4 17h4"/><path d="M12 17h8"/><circle cx="8" cy="17" r="2"/>',
    "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
    "moon": '<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z"/>',
    "monitor": '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8"/><path d="M12 16v4"/>',
    "user": '<circle cx="12" cy="8" r="4"/><path d="M4.5 20.5c1.4-3.6 4.2-5.5 7.5-5.5s6.1 1.9 7.5 5.5"/>',
    "plug": '<path d="M9 2v6"/><path d="M15 2v6"/><path d="M6 8h12v3a6 6 0 0 1-12 0Z"/><path d="M12 17v5"/>',
    "power": '<path d="M18.4 6.6a9 9 0 1 1-12.7 0"/><path d="M12 2v10"/>',
    // actions
    "play": '<path d="M7 4.5v15l12-7.5Z" fill="currentColor"/>',
    "pause": '<rect x="6" y="5" width="4" height="14" rx="1"/><rect x="14" y="5" width="4" height="14" rx="1"/>',
    "stop": '<rect x="6" y="6" width="12" height="12" rx="1.5"/>',
    "step": '<path d="M5 4.5v15l10-7.5Z" fill="currentColor"/><path d="M19 5v14"/>',
    "skip-back": '<path d="M19 19.5V4.5L9 12Z" fill="currentColor"/><path d="M5 5v14"/>',
    "skip-fwd": '<path d="M5 4.5v15L15 12Z" fill="currentColor"/><path d="M19 5v14"/>',
    "rewind": '<path d="M12 4.5v15L4 12Z" fill="currentColor"/><path d="M20 4.5v15L12 12Z" fill="currentColor"/>',
    "fast-fwd": '<path d="M12 4.5v15l8-7.5Z" fill="currentColor"/><path d="M4 4.5v15l8-7.5Z" fill="currentColor"/>',
    "record": '<circle cx="12" cy="12" r="6.5" fill="currentColor" stroke="none"/>',
    "refresh": '<path d="M21 12a9 9 0 1 1-2.6-6.4"/><path d="M21 3v6h-6"/>',
    "chevron-down": '<path d="m6 9 6 6 6-6"/>',
    "chevron-up": '<path d="m18 15-6-6-6 6"/>',
    "chevron-right": '<path d="m9 6 6 6-6 6"/>',
    "chevron-left": '<path d="m15 6-6 6 6 6"/>',
    "x": '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
    "tick": '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
    "arrow-right": '<path d="M5 12h14"/><path d="m12 5 7 7-7 7"/>',
    "upload": '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="m17 8-5-5-5 5"/><path d="M12 3v12"/>',
    "download": '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="m7 10 5 5 5-5"/><path d="M12 15V3"/>',
    "clipboard": '<rect x="5" y="4" width="14" height="17" rx="2"/><path d="M9 4V3h6v1"/><path d="M9 10h6"/><path d="M9 14h6"/><path d="M9 18h3"/>',
    "alert": '<path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v5"/><path d="M12 7.5h.01"/>',
    "check": '<circle cx="12" cy="12" r="9"/><path d="m8.5 12.5 2.5 2.5 4.5-5"/>',
    "edit": '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/>',
    "lock": '<rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
    "trash": '<path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="m19 6-1 14H6L5 6"/>',
    "plus": '<path d="M12 5v14"/><path d="M5 12h14"/>',
    "copy": '<rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h10"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
    "file": '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8Z"/><path d="M14 3v5h5"/>',
    "star": '<path d="m12 3 2.8 5.7 6.2.9-4.5 4.4 1 6.2L12 17.3 6.5 20.2l1-6.2L3 9.6l6.2-.9Z"/>',
    "pin": '<path d="M12 17v5"/><path d="M9 3h6l-1 6 3 3v2H7v-2l3-3Z"/>',
    "send": '<path d="M21 3 10.5 13.5"/><path d="m21 3-6.5 18-4-7.5L3 9.5Z"/>',
  };
  const svg = (body, cls) =>
    '<svg' + (cls ? ' class="' + cls + '"' : "") + ' viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
    'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + body + "</svg>";
  const ICONS = {};
  Object.keys(B).forEach((k) => { ICONS[k] = svg(B[k]); });

  /** An icon as an inline <svg class="ico"> (buttons, cells). Unknown name → "". */
  const ico = (name, cls) => (B[name] ? svg(B[name], cls || "ico") : "");
  /** An icon wrapped for the kit: <span class="ui-ico">. */
  const icon = (name) => '<span class="ui-ico">' + (ICONS[name] || "") + "</span>";
  /** Fill every [data-icon] once. */
  function paint(root) {
    (root || document).querySelectorAll("[data-icon]").forEach((n) => {
      if (n.dataset.painted) return;
      n.innerHTML = ICONS[n.dataset.icon] || "";
      n.classList.add("ui-ico");
      n.dataset.painted = "1";
    });
  }
  /** An icon and a word on a button: the word is text, never parsed as HTML. */
  function setLabel(btn, name, text) {
    btn.innerHTML = ico(name);
    if (text) {
      const s = document.createElement("span");
      s.textContent = text;
      btn.appendChild(s);
    }
    btn.classList.add("btn-ico");
  }
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

  // ---- theme: Auto | Light | Dark --------------------------------------------------------------
  const THEMES = [
    { id: "auto", label: "Auto", icon: "monitor" },
    { id: "light", label: "Light", icon: "sun" },
    { id: "dark", label: "Dark", icon: "moon" },
  ];
  const osLight = window.matchMedia("(prefers-color-scheme: light)");
  let themeChoice = store.get("theme", "dark");
  if (!THEMES.some((t) => t.id === themeChoice)) themeChoice = "dark";
  const themeListeners = [];
  const resolvedTheme = () => (themeChoice === "auto" ? (osLight.matches ? "light" : "dark") : themeChoice);
  function applyTheme() {
    const de = document.documentElement;
    const t = resolvedTheme();
    const changed = de.dataset.theme !== t;
    de.dataset.theme = t;
    de.dataset.themeChoice = themeChoice;
    if (changed) themeListeners.forEach((fn) => { try { fn(t); } catch (e) { /* a broken listener never breaks the switch */ } });
    const btn = document.getElementById("themeBtn");
    if (btn) {
      const cur = THEMES.find((x) => x.id === themeChoice);
      btn.innerHTML = ICONS[cur.icon];
      btn.setAttribute("aria-label", "Theme: " + cur.label);
      btn.title = "Theme: " + cur.label;
    }
  }
  function setTheme(id) {
    if (!THEMES.some((t) => t.id === id)) return;
    themeChoice = id;
    store.set("theme", id);
    applyTheme();
  }
  osLight.addEventListener("change", () => { if (themeChoice === "auto") applyTheme(); });

  // ---- rail: Sidebar control --------------------------------------------------------------------
  const RAIL_MODES = [
    { id: "expanded", label: "Expanded" },
    { id: "collapsed", label: "Collapsed" },
    { id: "hover", label: "Expand on hover" },
  ];
  let railMode = store.get("rail", null);
  if (!railMode) {                       // the pre-1.6 two-state switch
    let legacy = null;
    try { legacy = localStorage.getItem("ucando_nav_mode"); } catch (e) { /* ignore */ }
    railMode = legacy === "rail" ? "collapsed" : "expanded";
  }
  if (!RAIL_MODES.some((m) => m.id === railMode)) railMode = "expanded";
  const narrow = window.matchMedia("(max-width: 1000px)");
  let peek = false;
  const hoverMode = () => railMode === "hover" || narrow.matches;
  function applyRail() {
    // data-rail on <html>: expanded | collapsed | hover | peek (hover, opened)
    document.documentElement.dataset.rail = hoverMode() ? (peek ? "peek" : "hover") : railMode;
  }
  function setRailMode(id) {
    if (!RAIL_MODES.some((m) => m.id === id)) return;
    railMode = id;
    peek = false;
    store.set("rail", id);
    applyRail();
    setTimeout(() => window.dispatchEvent(new Event("resize")), 230);   // canvases re-measure
  }
  narrow.addEventListener("change", () => { peek = false; applyRail(); });

  // ---- hold-tips ---------------------------------------------------------------------------------
  const HOLD_MS = 5000;
  let tipFor = null, tipTimer = 0, tipEl = null;
  function hideTip() {
    clearTimeout(tipTimer);
    tipFor = null;
    if (tipEl) tipEl.hidden = true;
  }
  function showTip(target) {
    if (!tipEl) {
      tipEl = document.createElement("div");
      tipEl.className = "ui-holdtip";
      tipEl.setAttribute("role", "tooltip");
      document.body.appendChild(tipEl);
    }
    tipEl.textContent = target.dataset.tip;
    tipEl.hidden = false;
    const r = target.getBoundingClientRect();
    const w = tipEl.offsetWidth, h = tipEl.offsetHeight;
    const left = Math.min(Math.max(8, r.left), window.innerWidth - w - 8);
    let top = r.bottom + 8;
    if (top + h > window.innerHeight - 8) top = Math.max(8, r.top - h - 8);
    tipEl.style.left = left + "px";
    tipEl.style.top = top + "px";
  }
  document.addEventListener("pointerover", (e) => {
    const t = e.target && e.target.closest ? e.target.closest("[data-tip]") : null;
    if (t === tipFor) return;
    hideTip();
    if (!t || !t.dataset.tip) return;
    tipFor = t;
    tipTimer = setTimeout(() => { if (tipFor === t) showTip(t); }, HOLD_MS);
  });
  document.addEventListener("pointerdown", hideTip, true);
  document.addEventListener("scroll", hideTip, true);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") hideTip(); });

  // ---- resizing (Runway's resizable, keys under "ucando.size.") ---------------------------------
  function readSize(k) {
    const v = parseFloat(store.get("size." + k, ""));
    return isFinite(v) ? v : null;
  }
  const saveSize = (k, v) => { if (k) store.set("size." + k, v == null ? null : Math.round(v)); };
  let kickFrame = 0;
  function kickResize() {
    if (kickFrame) return;
    kickFrame = requestAnimationFrame(() => { kickFrame = 0; window.dispatchEvent(new Event("resize")); });
  }
  function dragging(axis, on) {
    document.body.classList.toggle("ui-resizing", on);
    document.body.classList.toggle("ui-resizing-" + axis, on);
  }
  function resizable(target, opts) {
    if (!target || target.dataset.resizeReady) return null;
    const o = opts || {};
    const d = target.dataset;
    const edge = o.edge || d.resizeEdge || "right";
    const vertical = edge === "top" || edge === "bottom";
    const key = o.key || d.resize;
    const cssVar = o.cssVar || d.resizeVar;
    const min = +(o.min || d.resizeMin || 160);
    const maxOpt = +(o.max || d.resizeMax || 0);
    const keep = +(o.keep || d.resizeKeep || 320);
    const title = o.title || d.resizeTitle || "the panel";
    const host = o.host || target.parentElement;
    if (!host) return null;
    d.resizeReady = "1";
    if (getComputedStyle(host).position === "static") host.style.position = "relative";
    const grow = edge === "right" || edge === "bottom" ? 1 : -1;
    const apply = o.apply || ((px) => {
      if (px == null) host.style.removeProperty(cssVar); else host.style.setProperty(cssVar, px + "px");
    });
    const size = () => { const r = target.getBoundingClientRect(); return vertical ? r.height : r.width; };
    const enabled = o.enabled || (() => !(narrow.matches && !vertical) &&
      target.offsetParent !== null && size() >= min * 0.75);
    const maxNow = () => {
      const room = (vertical ? host.clientHeight : host.clientWidth) - keep;
      return Math.max(min, maxOpt ? Math.min(maxOpt, room) : room);
    };
    const clamp = (v) => Math.round(Math.min(Math.max(v, min), maxNow()));

    const h = document.createElement("div");
    h.className = "ui-resize " + (vertical ? "is-y" : "is-x");
    h.setAttribute("role", "separator");
    h.setAttribute("aria-orientation", vertical ? "horizontal" : "vertical");
    h.setAttribute("aria-label", "Resize " + title);
    h.tabIndex = 0;
    h.dataset.tip = "Drag to resize " + title + ". A double-click puts it back.";
    host.appendChild(h);

    function place() {
      if (!enabled()) { h.hidden = true; return; }
      h.hidden = false;
      const t = target.getBoundingClientRect(), p = host.getBoundingClientRect();
      if (vertical) {
        const y = (edge === "top" ? t.top : t.bottom) - p.top + host.scrollTop;
        h.style.cssText = "left:" + (t.left - p.left) + "px;width:" + t.width + "px;top:" + (y - 3) + "px";
      } else {
        const x = (edge === "left" ? t.left : t.right) - p.left + host.scrollLeft;
        h.style.cssText = "top:" + (t.top - p.top) + "px;height:" + t.height + "px;left:" + (x - 3) + "px";
      }
    }
    function set(px, save) {
      apply(px);
      if (save) saveSize(key, px);
      place();
      kickResize();
    }
    const saved = key ? readSize(key) : null;
    if (saved != null) apply(Math.max(min, maxOpt ? Math.min(maxOpt, saved) : saved));

    h.addEventListener("pointerdown", (e) => {
      if (e.button !== 0) return;
      e.preventDefault();
      h.setPointerCapture(e.pointerId);
      const start = vertical ? e.clientY : e.clientX;
      const from = size();
      let last = from;
      dragging(vertical ? "y" : "x", true);
      h.classList.add("is-active");
      const move = (ev) => { last = clamp(from + ((vertical ? ev.clientY : ev.clientX) - start) * grow); set(last, false); };
      const up = () => {
        h.removeEventListener("pointermove", move);
        h.removeEventListener("pointerup", up);
        h.removeEventListener("pointercancel", up);
        dragging(vertical ? "y" : "x", false);
        h.classList.remove("is-active");
        saveSize(key, last);
        window.dispatchEvent(new Event("resize"));
      };
      h.addEventListener("pointermove", move);
      h.addEventListener("pointerup", up);
      h.addEventListener("pointercancel", up);
    });
    h.addEventListener("dblclick", () => set(null, true));
    h.addEventListener("keydown", (e) => {
      const step = (vertical ? { ArrowDown: 1, ArrowUp: -1 } : { ArrowRight: 1, ArrowLeft: -1 })[e.key];
      if (!step) return;
      e.preventDefault();
      set(clamp(size() + step * 16 * grow), true);
    });
    if (window.ResizeObserver) {
      const ro = new ResizeObserver(() => place());
      ro.observe(target);
      ro.observe(host);
    }
    window.addEventListener("resize", place);
    narrow.addEventListener("change", place);
    requestAnimationFrame(place);
    return { place, reset: () => set(null, true) };
  }

  // ---- house dialogs: confirm / notice / prompt --------------------------------------------------
  // A title, one sentence, Cancel focused, the action on the right — red only when it destroys.
  // A notice (something did not work) has OK alone, focused. User strings are set as text.
  function ask(o) {
    return new Promise((resolve) => {
      const d = document.createElement("dialog");
      d.className = "ui-dlg";
      d.innerHTML =
        '<form method="dialog"><div class="ui-dlg-head"><h2></h2></div>' +
        '<div class="ui-dlg-body"><p class="ui-dlg-text"></p></div>' +
        '<div class="ui-dlg-foot"><span class="spacer"></span>' +
        '<button type="button" class="btn" data-cancel>Cancel</button>' +
        '<button type="submit" class="btn btn-primary" data-ok></button></div></form>';
      d.querySelector("h2").textContent = o.title || "Are you sure?";
      const p = d.querySelector(".ui-dlg-text");
      if (o.text) p.textContent = o.text; else p.remove();
      let field = null;
      if (o.input) {
        const lab = document.createElement("label");
        lab.className = "ui-dlg-field";
        lab.textContent = o.input.label || "";
        field = document.createElement("input");
        field.value = o.input.value || "";
        if (o.input.placeholder) field.placeholder = o.input.placeholder;
        field.spellcheck = false;
        lab.appendChild(field);
        d.querySelector(".ui-dlg-body").appendChild(lab);
      }
      const ok = d.querySelector("[data-ok]");
      ok.textContent = o.action || "OK";
      if (o.notice) d.querySelector("[data-cancel]").remove();
      if (o.tone === "danger") ok.className = "btn btn-danger-fill";
      let result = null;
      const cancel = d.querySelector("[data-cancel]");
      if (cancel) cancel.addEventListener("click", () => d.close());
      d.querySelector("form").addEventListener("submit", (e) => {
        e.preventDefault();
        if (field && !field.value.trim()) { field.focus(); return; }
        result = field ? field.value.trim() : true;
        d.close();
      });
      d.addEventListener("close", () => {
        d.remove();
        resolve(result === null ? (field ? null : false) : result);
      });
      document.body.appendChild(d);
      d.showModal();
      if (field) { field.focus(); field.select(); } else (cancel || ok).focus();
    });
  }
  const confirmDlg = (o) => ask(o);                                          // → true / false
  const noticeDlg = (o) => ask(Object.assign({}, o, { notice: true }));      // OK only
  const promptDlg = (o) => ask(Object.assign({}, o,
    { input: { label: o.label, value: o.value, placeholder: o.placeholder } }));  // → text / null

  // ---- a small menu under (or over) a button ----------------------------------------------------
  // items: [{label, sub?, on?, run}] — Esc, a click elsewhere or a choice closes it; arrows move.
  function menuAt(anchor, title, items, opts) {
    const old = document.getElementById("ui-menu-open");
    if (old) { const same = old._anchor === anchor; old._close(); if (same) return; }
    const m = document.createElement("div");
    m.id = "ui-menu-open";
    m.className = "ui-menu";
    m.setAttribute("role", "menu");
    m._anchor = anchor;
    if (title) {
      const h = document.createElement("div");
      h.className = "ui-menu-h";
      h.textContent = title;
      m.appendChild(h);
    }
    const close = () => {
      m.remove();
      document.removeEventListener("pointerdown", outside, true);
      document.removeEventListener("keydown", key, true);
      anchor.setAttribute("aria-expanded", "false");
      if (opts && opts.onClose) opts.onClose();
    };
    m._close = close;
    const outside = (e) => { if (!m.contains(e.target) && !anchor.contains(e.target)) close(); };
    const key = (e) => {
      if (e.key === "Escape") { e.preventDefault(); close(); anchor.focus(); return; }
      if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
      e.preventDefault();
      const all = Array.from(m.querySelectorAll(".ui-menu-item"));
      const i = all.indexOf(document.activeElement);
      all[(i + (e.key === "ArrowDown" ? 1 : all.length - 1)) % all.length].focus();
    };
    for (const it of items) {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "ui-menu-item" + (it.on ? " is-on" : "") + (it.tone === "danger" ? " is-danger" : "");
      b.setAttribute("role", it.on === undefined ? "menuitem" : "menuitemradio");
      if (it.on !== undefined) b.setAttribute("aria-checked", String(!!it.on));
      b.innerHTML = '<span class="ui-menu-dot" aria-hidden="true"></span>';
      b.appendChild(document.createTextNode(it.label));
      if (it.sub != null) {
        const s = document.createElement("span");
        s.className = "ui-menu-sub";
        s.textContent = it.sub;
        b.appendChild(s);
      }
      b.addEventListener("click", () => { close(); it.run(); });
      m.appendChild(b);
    }
    document.body.appendChild(m);
    const r = anchor.getBoundingClientRect();
    const up = opts && opts.up;
    const below = !up && r.bottom + 6 + m.offsetHeight <= window.innerHeight - 8;
    const left = opts && opts.alignLeft ? r.left : r.right - m.offsetWidth;
    m.style.left = Math.max(8, Math.min(left, window.innerWidth - m.offsetWidth - 8)) + "px";
    m.style.top = (below ? r.bottom + 6 : Math.max(8, r.top - m.offsetHeight - 6)) + "px";
    anchor.setAttribute("aria-expanded", "true");
    document.addEventListener("pointerdown", outside, true);
    document.addEventListener("keydown", key, true);
    const first = m.querySelector(".ui-menu-item.is-on") || m.querySelector(".ui-menu-item");
    if (first) first.focus();
  }

  // ---- toast: one transient line, bottom right ---------------------------------------------------
  // What the pre-1.6 status bar said. The same text again within a moment is not news, so it only
  // keeps the line up; anything new replaces it.
  let toastEl = null, toastTimer = 0, toastText = "", toastTone = "";
  function hideToastLater() {
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => {
      // never take a line away while the person is reading or selecting it
      if (toastEl.matches(":hover")) return hideToastLater();
      toastEl.classList.remove("show");
      setTimeout(() => { if (!toastEl.classList.contains("show")) toastEl.hidden = true; }, 220);
    }, toastTone === "bad" ? 7000 : 4500);
  }
  function toast(text, tone) {
    if (!text) return;
    text = String(text);
    if (!toastEl) {
      toastEl = document.createElement("div");
      toastEl.className = "ui-toast";
      toastEl.setAttribute("role", "status");
      toastEl.setAttribute("aria-live", "polite");
      document.body.appendChild(toastEl);
      // hovering holds the line (selectable — a saved path is worth copying);
      // leaving starts the countdown again
      toastEl.addEventListener("mouseenter", () => clearTimeout(toastTimer));
      toastEl.addEventListener("mouseleave", hideToastLater);
    }
    toastTone = tone || "";
    if (text !== toastText || toastEl.hidden) {
      toastEl.className = "ui-toast" + (tone ? " " + tone : "");
      toastEl.textContent = text;
      toastText = text;
    }
    toastEl.hidden = false;
    requestAnimationFrame(() => toastEl.classList.add("show"));
    hideToastLater();
  }

  // ---- the frame: rail hover, Sidebar control, theme button, rail width -------------------------
  function wireFrame() {
    const rail = document.getElementById("rail");
    const app = document.getElementById("app");
    if (rail) {
      let peekTimer = 0;
      rail.addEventListener("pointerenter", (e) => {
        if (!hoverMode() || e.pointerType === "touch") return;
        clearTimeout(peekTimer);
        peekTimer = setTimeout(() => { peek = true; applyRail(); }, 120);
      });
      rail.addEventListener("pointerleave", () => {
        clearTimeout(peekTimer);
        if (!peek || document.getElementById("ui-menu-open")) return;
        peekTimer = setTimeout(() => { peek = false; applyRail(); }, 180);
      });
      const ctl = document.getElementById("railCtl");
      if (ctl) {
        ctl.innerHTML = ICONS.sidebar;
        ctl.addEventListener("click", () => menuAt(ctl, "Sidebar control",
          RAIL_MODES.map((m) => ({ label: m.label, on: m.id === railMode, run: () => setRailMode(m.id) })),
          { up: true, alignLeft: true,
            onClose: () => { if (peek && !rail.matches(":hover")) { peek = false; applyRail(); } } }));
      }
      resizable(rail, {
        key: "rail", edge: "right", host: app, min: 180, max: 380, keep: 480, title: "the sidebar",
        apply: (px) => {
          if (px == null) document.documentElement.style.removeProperty("--rail-w");
          else document.documentElement.style.setProperty("--rail-w", px + "px");
        },
        enabled: () => railMode === "expanded" && !narrow.matches,
      });
    }
    const themeBtn = document.getElementById("themeBtn");
    if (themeBtn) {
      themeBtn.addEventListener("click", () => menuAt(themeBtn, "Theme",
        THEMES.map((t) => ({ label: t.label, on: t.id === themeChoice, run: () => setTheme(t.id) }))));
    }
    // favicon: the brand mark on its tile (a fixed swatch — a tab icon does not follow the theme)
    const fav = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><rect width="32" height="32" rx="8" fill="#4ea1ff"/>' +
      '<g transform="translate(4 4)" fill="none" stroke="#04121d" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round">' +
      B.brand + "</g></svg>";
    let link = document.querySelector("link[rel=icon]");
    if (!link) { link = document.createElement("link"); link.rel = "icon"; document.head.appendChild(link); }
    link.href = "data:image/svg+xml," + encodeURIComponent(fav);
  }

  applyTheme();
  applyRail();
  paint(document);
  wireFrame();

  window.UI = {
    icons: ICONS, ico, icon, paint, setLabel, esc, store,
    theme: () => themeChoice, resolvedTheme, setTheme, onTheme: (fn) => themeListeners.push(fn), THEMES,
    railMode: () => railMode, setRailMode, RAIL_MODES,
    resizable, menu: menuAt, confirm: confirmDlg, notice: noticeDlg, prompt: promptDlg, toast,
  };
})();
