"use strict";

const $ = (id) => document.getElementById(id);
const api = (path, opts) =>
  fetch(path, { headers: { "Content-Type": "application/json" }, ...opts }).then((r) => r.json());
const apiUpload = (path, file) => {
  const fd = new FormData();
  fd.append("file", file);
  return fetch(path, { method: "POST", body: fd }).then((r) => r.json());
};
const POST = (p, body) => api(p, { method: "POST", body: body ? JSON.stringify(body) : undefined });

const state = { connected: false, recording: false, view: "dashboard" };
let pollTimer = null;
let usage = null;            // GET /api/usage — up here so openView can read it from the first call

// ---- icons ------------------------------------------------------------------
// The one icon map lives in shell.js (window.UI). These are the names the views
// below use, each an inline <svg class="ico">.
const ICONS = {
  power: UI.ico("power"), plug: UI.ico("plug"), record: UI.ico("record"), play: UI.ico("play"),
  pause: UI.ico("pause"), stop: UI.ico("stop"), step: UI.ico("step"), refresh: UI.ico("refresh"),
  chevronDown: UI.ico("chevron-down"), chevronUp: UI.ico("chevron-up"), close: UI.ico("x"),
  chevronLeft: UI.ico("chevron-left"), chevronRight: UI.ico("chevron-right"),
  check: UI.ico("tick"), arrowRight: UI.ico("arrow-right"), upload: UI.ico("upload"),
  download: UI.ico("download"), clipboard: UI.ico("clipboard"), grid: UI.ico("grid"),
  alert: UI.ico("alert"), skipBack: UI.ico("skip-back"), skipFwd: UI.ico("skip-fwd"),
  rewind: UI.ico("rewind"), fastFwd: UI.ico("fast-fwd"), edit: UI.ico("edit"), lock: UI.ico("lock"),
  swap: UI.ico("swap"),
};
const ICON_POWER = ICONS.power, ICON_RECORD = ICONS.record, ICON_STOP = ICONS.stop;
const _bigGrid = UI.ico("grid", "ico ico-hero");

// ---- navigation: ONE definition ---------------------------------------------
// It builds the rail, names the page in the banner (its `desc` is the page
// name's hold-tip), titles the browser tab, and test_ui reads it. Whether a
// view can be used right now is VIEW_READY's job, below.
const NAV = [
  { group: "Overview", items: [
    { id: "dashboard", label: "Dashboard", icon: "dashboard",
      desc: "Live values decoded from standard protocols (OBD-II, J1939), with no DBC needed." },
  ] },
  { group: "Capture", items: [
    { id: "logger", label: "CAN logger", icon: "list",
      desc: "Live capture with per-ID statistics, recorded to .asc, .blf or .csv." },
    { id: "replay", label: "TX replay", icon: "replay",
      desc: "Mimic a vehicle: replay recorded logs onto the bus, patch signals live, watch the exact bytes going out and check them against the device's cloud log." },
  ] },
  { group: "Analysis", items: [
    { id: "re", label: "Reverse engineering", icon: "activity",
      desc: "Find candidate signals in an unknown log: entropy, bit-flip rate, the state sniffer and OBD correlation." },
    { id: "autore", label: "Auto-RE", icon: "chip",
      desc: "Confidence-tiered (A/B/C) identification by CANMatch, OBD correlation and known-value matching." },
    { id: "framedec", label: "Frame decoder", icon: "grid",
      desc: "Decode raw CAN frames against a DBC or Signature JSON: byte, bit and signal views." },
    { id: "convert", label: "Converter", icon: "swap",
      desc: "Convert a signal database between DBC, Signature JSON and CSV, in any direction." },
    { id: "dbc", label: "DBC builder", icon: "layers",
      desc: "Edit messages and signals, then round-trip to a .dbc file." },
    { id: "oem", label: "OEM database", icon: "database",
      desc: "Store, fingerprint and auto-apply vehicle DBC profiles (CANMatch)." },
  ] },
  { group: "Visualization", items: [
    { id: "signals", label: "Signal viewer", icon: "trending",
      desc: "Live DBC decode into a table, tiles or strip charts, with computed signals and alarms; or play a log offline." },
  ] },
  { group: "Transmit", items: [
    { id: "scheduler", label: "TX scheduler", icon: "clock",
      desc: "Transmit cyclic or one-shot frames on the bus." },
    { id: "automation", label: "Automation", icon: "bolt",
      desc: "Rules, scheduled jobs, restbus simulation and scripting." },
  ] },
  { group: "Diagnostics", items: [
    { id: "dtc", label: "DTC codes", icon: "triangle",
      desc: "Read and clear trouble codes over OBD-II, UDS and J1939." },
    { id: "decoder", label: "Protocol decoder", icon: "code",
      desc: "Live OBD-II, UDS (ISO-TP) and J1939 frame interpretation." },
  ] },
];
const NAV_ITEMS = Object.fromEntries(NAV.flatMap((g) => g.items.map((it) => [it.id, { ...it, group: g.group }])));

// The rail lists what a person can use. A "soon" view (VIEW_READY, below) is
// left out altogether — the user, 2026-11-24: hide what is not developed, so the
// menu does not confuse — and a group with nothing left in it goes with it.
// Built once VIEW_READY exists (see the call after it).
function buildRail() {
  const shown = (it) => viewShown(it.id);
  $("railNav").innerHTML = NAV.filter((g) => g.items.some(shown)).map((g) =>
    `<div class="rail-section"><span class="rail-section-t">${g.group}</span><span class="rail-section-rule"></span></div>` +
    g.items.filter(shown).map((it) => {
      const on = it.id === state.view;
      return `<button type="button" class="rail-item${on ? " active" : ""}" data-view="${it.id}" title="${g.group} · ${it.label}"${on ? ' aria-current="page"' : ""}>` +
        `<span class="rail-ico">${UI.icons[it.icon] || ""}</span><span class="rail-label">${it.label}</span>` +
        `<span class="rail-pill" hidden></span></button>`;
    }).join("")).join("");
}

// ---- which views the rail shows: Settings → Views ---------------------------
// The person's own choice, kept in this browser ("ucando.views": only the views
// that differ from their default). Default: every view, except the ones held
// back (`soon`). A held-back view switched on is a preview — it opens, marked
// "Preview" in the rail. Dashboard always stays: it is where the app opens.
let viewPrefs = {};
try { viewPrefs = JSON.parse(UI.store.get("views", "{}")) || {}; } catch (e) { viewPrefs = {}; }
const isSoon = (id) => !!(VIEW_READY[id] && VIEW_READY[id].kind === "soon");
function viewShown(id) {
  if (id === "dashboard") return true;
  return Object.prototype.hasOwnProperty.call(viewPrefs, id) ? viewPrefs[id] !== false : !isSoon(id);
}
function saveViewPrefs() {
  UI.store.set("views", Object.keys(viewPrefs).length ? JSON.stringify(viewPrefs) : null);
  buildRail();
  applyAvailability();
  if (!viewShown(state.view)) openView("dashboard");   // never leave the person on a view they hid
}
function setViewShown(id, on) {
  if (id === "dashboard") return;
  if (on === !isSoon(id)) delete viewPrefs[id]; else viewPrefs[id] = on;
  saveViewPrefs();
}

function setViewMeta(view) {
  const it = NAV_ITEMS[view] || { label: view, desc: "", icon: "" };
  $("viewTitle").textContent = it.label;
  $("bannerPage").dataset.tip = it.desc;
  $("bannerPageIco").innerHTML = UI.icons[it.icon] || "";
  document.title = (state.build === "dev" ? "Dev · " : "") + `${it.label} · uCANdo`;
}

// ---------------------------------------------------------------- navigation
function openView(view) {
  // A "soon" view isn't usable yet — opening it anyway is what makes a
  // held-back feature look like a bug. Bus-gated views stay reachable.
  const ready = VIEW_READY[view];
  if (ready && ready.kind === "soon" && !viewShown(view)) return void setStatus(ready.why);
  if (!$("view-" + view)) return;
  document.querySelectorAll("#railNav .rail-item").forEach((b) => {
    const on = b.dataset.view === view;
    b.classList.toggle("active", on);
    if (on) b.setAttribute("aria-current", "page"); else b.removeAttribute("aria-current");
  });
  state.view = view;
  document.querySelectorAll(".view").forEach((v) => v.classList.add("hidden"));
  $("view-" + view).classList.remove("hidden");
  setViewMeta(view);
  countView(view);
  startPolling(view);
  if (view === "replay" || view === "re") refreshLogs();
  if (view === "replay") { refreshScenarios($("txScenario").value); refreshPatch(); }
  if (view === "dbc") renderDbc();
  if (view === "autore") initAutoRE();
  if (view === "oem") renderOem();
  if (view === "automation") renderAutomation();
  if (view === "scheduler") pollTx();
  // A DBC can arrive from elsewhere (OEM database → Apply, Identify and apply,
  // the DBC builder): the list must reflect it the moment the view opens.
  if (view === "signals") refreshSigList();
}
$("railNav").addEventListener("click", (e) => {
  const btn = e.target.closest(".rail-item");
  if (btn) openView(btn.dataset.view);
});
$("bnBrand").addEventListener("click", () => openView("dashboard"));

// ---- version, build, Settings ------------------------------------------------
api("/api/info").then((d) => {
  state.build = d.build;
  $("appVersion").textContent = `Version ${d.version}`;
  $("appDev").hidden = d.build !== "dev";
  $("aboutVersion").textContent = d.version;
  $("aboutBuild").textContent = d.build === "dev" ? "Dev (run from source)" : "Release";
  $("aboutData").textContent = d.data_dir || "—";
  $("aboutPlugins").textContent = String(d.plugins_loaded ?? "—");
  setViewMeta(state.view);
  $("staleChip").hidden = !d.code_stale;
  // A source copy keeps checking: code edited after it started means a restart is due.
  if (d.build === "dev") {
    setInterval(() => api("/api/info").then((i) => { $("staleChip").hidden = !i.code_stale; }).catch(() => {}), 15000);
  }
});
// uCANdo's own window (main.py → ucando/desktop.py) takes Edge's dark mode for its title bar —
// an app window ignores the page's colours — and main.py reads this saved choice at the next
// start. So the theme in use is saved now, and again whenever it changes.
const saveTheme = (t) => POST("/api/config", { key: "ui_theme", value: t }).catch(() => {});
saveTheme(UI.resolvedTheme());
UI.onTheme(saveTheme);

function segButtons(host, opts, cur, pick) {
  host.innerHTML = opts.map((o) =>
    `<button type="button" class="seg${o.id === cur ? " active" : ""}" role="radio" aria-checked="${o.id === cur}" data-v="${o.id}">${o.label}</button>`).join("");
  host.querySelectorAll(".seg").forEach((b) => b.addEventListener("click", () => pick(b.dataset.v)));
}
function renderSettings() {
  segButtons($("setTheme"), UI.THEMES, UI.theme(), (id) => { UI.setTheme(id); renderSettings(); });
  segButtons($("setRail"), UI.RAIL_MODES, UI.railMode(), (id) => { UI.setRailMode(id); renderSettings(); });
  renderViewPrefs();
}
// Settings → Views: a switch per view, grouped as the rail is.
function renderViewPrefs() {
  $("setViews").innerHTML = NAV.map((g) => `<div class="set-views-g">${g.group}</div>` + g.items.map((it) => {
    const locked = it.id === "dashboard";
    return `<label class="set-view${locked ? " is-locked" : ""}"${locked ? ' data-tip="Always shown: uCANdo opens on it."' : ""}>` +
      `<span class="rail-ico">${UI.icons[it.icon] || ""}</span><span class="set-view-l">${it.label}</span>` +
      (isSoon(it.id) ? `<span class="tag warn" data-tip="Held back from this release. Switch it on to preview it.">Soon</span>` : "") +
      `<input type="checkbox" class="ui-switch" data-view="${it.id}" aria-label="Show ${it.label}"` +
      `${viewShown(it.id) ? " checked" : ""}${locked ? " disabled" : ""} /></label>`;
  }).join("")).join("");
}
$("setViews").addEventListener("change", (e) => {
  const c = e.target.closest("input[data-view]");
  if (c) setViewShown(c.dataset.view, c.checked);
});
$("btnViewsReset").addEventListener("click", () => { viewPrefs = {}; saveViewPrefs(); renderViewPrefs(); });
$("btnSettings").addEventListener("click", () => {
  renderSettings(); loadLogDir(); refreshUsage(); refreshUpdate(); $("settingsDlg").showModal();
});

// ---- usage reporting (user skill app-control; ucando/usage.py) ---------------
// A release copy reports who uses it and how — counts, never CAN data. The first
// start asks the name as a welcome (never a notice of what is reported), the
// banner greets on every view, and Settings → Usage reporting shows the facts.
// Silent: nothing waits for the server, and a failed send is said only in Settings.
const WELCOME_TITLE = "Hi! May I have your name, please?";
const pad2 = (n) => String(n).padStart(2, "0");
function whenSent(iso) {                             // 24-hour; today's times without the date
  const d = iso ? new Date(iso) : null;
  if (!d || isNaN(d)) return "—";
  const t = `${pad2(d.getHours())}:${pad2(d.getMinutes())}`;
  return d.toDateString() === new Date().toDateString()
    ? `Today ${t}` : `${pad2(d.getDate())}-${pad2(d.getMonth() + 1)}-${d.getFullYear()} ${t}`;
}
function greet() {
  const name = usage && usage.enabled && usage.name;
  $("bannerHelloT").textContent = name ? "Hello, " + name : "";
  $("bannerHello").hidden = !name;
  $("bannerHelloSep").hidden = !name;
}
function renderUsage() {
  const s = usage;
  $("setUsage").hidden = !s;
  if (!s) return;
  const on = !!s.enabled;
  // switched off: the card is the reason alone — no row of dashes, no buttons
  $("usageOff").hidden = on;
  $("usageOffT").textContent = on ? "" : (s.disabled_reason || "Usage reporting is off on this copy.");
  $("usageFacts").hidden = !on;
  $("btnUsageName").hidden = !on;
  $("btnUsageSend").hidden = !on;
  $("usageErr").hidden = !(on && s.error);
  if (!on) return;
  $("usageName").textContent = s.name || "—";
  $("usageId").textContent = s.install_id || "—";
  $("usageTo").textContent = s.reporting_to || "—";
  $("usageLast").textContent = s.sending ? "Sending" : whenSent(s.last_sent);
  $("usageWaiting").textContent = String(s.waiting || 0);
  UI.setLabel($("btnUsageSend"), "send", s.sending ? "Sending" : "Send now");
  $("btnUsageSend").classList.add("btn-ico");
  $("btnUsageSend").disabled = !!s.sending;
  // amber, not red: a report that did not go is kept and retried — not a fault
  $("usageErrT").textContent = s.error ? "Not sent: " + s.error : "";
}
async function refreshUsage() {
  try { usage = await api("/api/usage"); } catch (e) { usage = null; }
  greet();
  renderUsage();
}
// A view switch never reaches the server in a single page, so it is said here.
// Only NAV ids are counted (the server checks), never anything typed.
function countView(view) {
  if (usage && usage.enabled) POST("/api/usage/view", { view }).catch(() => {});
}

// The name: once, at the first start, before anything else — and from Settings →
// Edit name as "Your name" with Cancel. The first start cannot be dismissed: Esc is
// refused, and a browser that closes it anyway (Chrome lets a second Esc through)
// gets it straight back. Saved at once; the server sends it in the background.
let nameDlg = null;                                  // { edit, saved, resolve } while open
function askName(edit) {
  return new Promise((resolve) => {
    nameDlg = { edit, saved: false, resolve };
    $("welcomeTitle").textContent = edit ? "Your name" : WELCOME_TITLE;
    $("welcomeName").value = edit && usage ? usage.name || "" : "";
    $("welcomeCancel").hidden = !edit;
    $("welcomeOk").textContent = edit ? "Save" : "Continue";
    $("welcomeErr").hidden = true;
    syncNameOk();
    $("welcomeDlg").showModal();
    $("welcomeName").focus();
  });
}
function syncNameOk() { $("welcomeOk").disabled = !$("welcomeName").value.trim(); }
$("welcomeName").addEventListener("input", syncNameOk);
$("welcomeCancel").addEventListener("click", () => $("welcomeDlg").close());
$("welcomeDlg").addEventListener("cancel", (e) => { if (nameDlg && !nameDlg.edit) e.preventDefault(); });
$("welcomeForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const name = $("welcomeName").value.trim();
  if (!name) return;
  $("welcomeOk").disabled = true;
  try {
    const r = await fetch("/api/usage/name", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name }),
    });
    const body = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(body.error || body.detail || "HTTP " + r.status);
    usage = body;
    if (nameDlg) nameDlg.saved = true;
    $("welcomeDlg").close();
  } catch (ex) {
    $("welcomeErrT").textContent = "Not saved: " + ex.message;
    $("welcomeErr").hidden = false;
    syncNameOk();
  }
});
$("welcomeDlg").addEventListener("close", () => {
  const d = nameDlg;
  if (d && !d.edit && !d.saved) { $("welcomeDlg").showModal(); $("welcomeName").focus(); return; }
  nameDlg = null;
  greet();
  renderUsage();
  if (d) d.resolve();
});
$("btnUsageName").addEventListener("click", () => askName(true));
$("btnUsageSend").addEventListener("click", async () => {
  $("btnUsageSend").disabled = true;
  try { usage = await POST("/api/usage/send"); } catch (e) { /* said on the next read */ }
  renderUsage();
  // follow the send while it runs (the client gives up after 30 s)
  for (let i = 0; i < 25 && usage && usage.sending; i++) {
    await new Promise((r) => setTimeout(r, 1500));
    await refreshUsage();
  }
});

refreshUsage().then(async () => {
  countView(state.view);                             // the view uCANdo opened on
  if (usage && usage.needs_name) await askName(false);
  startUpdates();                                    // the update offer waits for the name
});

// ---- self-update (user skill app-updates; ucando/update) ---------------------
// A launcher install checks the release channel on every start. A newer version
// is offered once per run, after the name; Later leaves the banner chip. Update
// downloads, verifies, installs beside this version and restarts into it, and
// this page follows the restart and reloads on the new version. Silent: a check
// that fails is said only in Settings → Updates.
let upd = null;                                      // GET /api/update
let following = false;                               // this page asked for the install
const UPD_BUSY = ["downloading", "installing", "restarting"];
const mbOf = (n) => (n == null ? "" : (n / 1048576).toFixed(1) + " MB");
const pause = (ms) => new Promise((r) => setTimeout(r, ms));

async function refreshUpdate() {
  try { upd = await api("/api/update"); } catch (e) { return; }
  paintUpdateChip();
  renderUpdates();
  if ($("updateDlg").open) paintOffer();
}
function paintUpdateChip() {
  const s = upd;
  const show = !!(s && s.available && s.stage !== "disabled");
  $("updateChip").hidden = !show;
  if (!show) return;
  let text = "Update " + s.latest;
  if (s.stage === "downloading") text = s.total ? `Updating ${Math.floor((s.received / s.total) * 100)}%` : "Updating";
  else if (s.stage === "installing") text = "Installing";
  else if (s.stage === "restarting") text = "Restarting";
  $("updateChipT").textContent = text;
  $("updateChip").classList.toggle("is-required", !!s.required);
  $("updateChip").dataset.tip = s.required ? `uCANdo ${s.latest} is required.`
    : `uCANdo ${s.latest} is available. Click to see what is new.`;
}
$("updateChip").addEventListener("click", () => openOffer());

// once per run (the server remembers across reloads)
async function maybeOffer() {
  if (!upd || !upd.available || upd.offered || upd.stage === "disabled") return;
  try { upd = await POST("/api/update/offered"); } catch (e) { return; }
  openOffer();
}
function openOffer() {
  if (!upd || !upd.available || $("updateDlg").open) return;
  paintOffer();
  $("updateDlg").showModal();
}
$("updateDlg").addEventListener("cancel", (e) => {
  if (upd && (upd.required || UPD_BUSY.includes(upd.stage))) e.preventDefault();
});
// Chrome lets a second Esc through a prevented cancel: an install in progress stays in view
$("updateDlg").addEventListener("close", () => {
  if (upd && UPD_BUSY.includes(upd.stage) && following) $("updateDlg").showModal();
});

function paintOffer() {
  const s = upd;
  if (!s) return;
  $("updDlgTitle").textContent = `uCANdo ${s.latest} is available`;
  $("updDlgRequired").hidden = !s.required;
  const facts = [`Installed ${s.current}`];
  if (s.size) facts.push(mbOf(s.size));
  if (s.published) facts.push("published " + whenSent(s.published).replace("Today ", "today "));
  $("updDlgFacts").textContent = facts.join(" · ");
  // the CHANGELOG section as text: markdown's #, **, * and ` markers dropped
  $("updDlgNotes").textContent = (s.notes || "").replace(/^#{1,6}\s+/gm, "")
    .replace(/\*\*(.+?)\*\*/g, "$1").replace(/\*([^*\n]+)\*/g, "$1").replace(/`([^`]+)`/g, "$1");
  const busy = UPD_BUSY.includes(s.stage);
  $("updProg").hidden = !busy;
  if (busy) {
    const pct = s.total ? Math.floor((s.received / s.total) * 100) : null;
    $("updProgT").textContent = s.stage === "downloading"
      ? (pct == null ? "Downloading" : `Downloading ${pct}% · ${mbOf(s.received)} of ${mbOf(s.total)}`)
      : s.stage === "installing" ? "Installing beside this version" : `Restarting into ${s.latest}`;
    $("updProgBar").style.width = (s.stage === "downloading" ? (pct || 0) : 100) + "%";
  }
  // why the last try failed, or what the restart stops — said before anyone clicks Update
  let warn = "";
  if (!busy && s.stage === "failed" && s.error && following) warn = "Not installed: " + s.error;
  else if (!busy && s.interrupts && s.interrupts.length) warn = "The restart: " + s.interrupts.join(". ") + ".";
  $("updDlgWarn").hidden = !warn;
  $("updDlgWarnT").textContent = warn;
  $("btnUpdLater").hidden = busy || !!s.required;
  $("btnUpdGo").hidden = busy;
  UI.setLabel($("btnUpdGo"), s.can_install_here ? "download" : "arrow-right",
    s.can_install_here ? (s.stage === "failed" && following ? "Try again" : "Update") : "Open the release");
}
$("btnUpdLater").addEventListener("click", () => {
  POST("/api/update/later").catch(() => {});
  $("updateDlg").close();
});
$("btnUpdGo").addEventListener("click", async () => {
  following = true;
  let s;
  try { s = await POST("/api/update/install"); } catch (e) { return; }
  if (s.open) {                                      // not a launcher install: the release page
    window.open(s.open, "_blank", "noopener");
    $("updateDlg").close();
    return;
  }
  upd = s;
  paintUpdateChip();
  paintOffer();
  followInstall();
});

// Follow the install, then the restart: once uCANdo answers with the new version, reload.
async function followInstall() {
  while (upd && ["downloading", "installing"].includes(upd.stage)) {
    await pause(600);
    await refreshUpdate();
  }
  if (!upd || upd.stage !== "restarting") return;
  const target = upd.latest;
  const t0 = Date.now();
  while (Date.now() - t0 < 120000) {
    await pause(1500);
    try {
      const info = await api("/api/info");
      if (info.version === target) { location.reload(); return; }
    } catch (e) { /* between versions */ }
  }
  $("updProg").hidden = true;
  $("updDlgWarnT").textContent = `uCANdo ${target} has not answered yet. Start it from uCANdo.exe.`;
  $("updDlgWarn").hidden = false;
}

// Settings → Updates
function renderUpdates() {
  const s = upd;
  $("setUpdates").hidden = !s;
  if (!s) return;
  const off = s.stage === "disabled";
  $("updOff").hidden = !off;
  $("updOffT").textContent = off ? (s.disabled_reason || "Updates are off on this copy.") : "";
  $("updFacts").hidden = off;
  $("btnUpdCheck").hidden = off;
  $("updCta").hidden = off || !s.available;
  $("updErr").hidden = off || !(s.stage === "failed" && s.error);
  if (off) return;
  $("updCurrent").textContent = s.current;
  $("updLatest").textContent = s.available ? `${s.latest} available`
    : s.stage === "up_to_date" ? "Up to date" : (s.latest || "—");
  $("updChecked").textContent = s.stage === "checking" ? "Checking" : whenSent(s.last_checked);
  let channel = "—";
  try { const u = new URL(s.channel); channel = u.host + u.pathname.split("/").slice(0, 3).join("/"); } catch (e) { /* — */ }
  $("updChannel").textContent = channel;
  UI.setLabel($("btnUpdCheck"), "refresh", s.stage === "checking" ? "Checking" : "Check now");
  $("btnUpdCheck").classList.add("btn-ico");
  $("btnUpdCheck").disabled = s.stage === "checking" || UPD_BUSY.includes(s.stage);
  if (s.available) UI.setLabel($("btnUpdOpen"), "download", `Update to ${s.latest}`);
  // amber: a check that did not reach the channel is retried next start — not a fault
  $("updErrT").textContent = s.stage === "failed" && s.error ? "Not checked: " + s.error : "";
}
$("btnUpdCheck").addEventListener("click", async () => {
  $("btnUpdCheck").disabled = true;
  try { upd = await POST("/api/update/check"); } catch (e) { /* said on the next read */ }
  renderUpdates();
  for (let i = 0; i < 70 && upd && upd.stage === "checking"; i++) { await pause(1000); await refreshUpdate(); }
  if (upd && upd.available) openOffer();
});
$("btnUpdOpen").addEventListener("click", () => { $("settingsDlg").close(); openOffer(); });

async function startUpdates() {
  await refreshUpdate();
  // the first check runs at start-up: follow it briefly so a fresh start can offer at once
  for (let i = 0; i < 40 && upd && upd.stage === "checking"; i++) { await pause(1500); await refreshUpdate(); }
  await maybeOffer();
  if (upd && UPD_BUSY.includes(upd.stage)) { following = true; openOffer(); followInstall(); }
  setInterval(refreshUpdate, 60000);
}

// ---- feature readiness ----------------------------------------------------
// One entry per view that is NOT "click it and it works right now". A view
// absent from this table is ready as-is — that absence is the promise the rail
// makes, so keep the table honest. Three kinds, three distinct treatments:
//
//   soon  — not available to the user yet: left out of the rail altogether
//           (2026-11-24, at the user's request — a greyed "Soon" row still read
//           as clutter), and openView() refuses it. Covers both "not built" and
//           "built but held back".
//   bus   — built, but can do nothing without a connected adapter. Dimmed and
//           labelled "Bus" only while offline, and still CLICKABLE: a disabled
//           nav item hides what the tool can do, a dimmed one with a stated
//           reason teaches. Clears the moment a bus connects.
//   input — built and works offline, but needs a file first (log / DBC /
//           signature). Full brightness — it isn't unavailable, it's waiting —
//           with a muted pill naming what to feed it.
const VIEW_READY = {
  // Held back from this release (tagged "Soon" on request, 2026-08-04). These
  // four are implemented and covered by tests — hidden, not missing. To bring
  // one back, restore the `kind` noted at the end of its line; nothing else
  // needs touching (the bus gate and pills follow from `kind`).
  re: { kind: "soon", why: "Reverse engineering is coming soon." },           // was: input · Log
  autore: { kind: "soon", why: "Auto-RE is coming soon." },                   // was: input · Log
  dbc: { kind: "soon", why: "The DBC builder is coming soon." },              // was: ready (no tag)
  decoder: { kind: "soon", why: "The protocol decoder is coming soon." },     // was: bus

  dashboard: { kind: "bus", why: "Decoding live OBD-II / J1939 values needs a connected bus." },
  logger: { kind: "bus", why: "Capturing frames needs a connected bus." },
  replay: { kind: "bus", why: "Transmitting a log onto the bus needs a connected bus." },
  scheduler: { kind: "bus", why: "Transmitting frames needs a connected bus." },
  automation: { kind: "bus", why: "Rules, jobs, restbus and scripting all act on a live bus." },
  dtc: { kind: "bus", why: "Reading or clearing trouble codes needs a connected bus." },

  framedec: { kind: "input", pill: "DBC", why: "Decodes against a DBC or Signature JSON — upload one, then paste frames." },
  convert: { kind: "input", pill: "File", why: "Converts an uploaded DBC, Signature JSON, CSV or CanPlus XML." },
  signals: { kind: "input", pill: "DBC", why: "Needs a DBC — upload one, or apply an OEM profile." },
};
const LIVE_ONLY_VIEWS = Object.fromEntries(          // bus-gated views only
  Object.entries(VIEW_READY).filter(([, r]) => r.kind === "bus").map(([v, r]) => [v, r.why]));
buildRail();

// What each rail pill means, said on the pill itself (a hold-tip) — there is no
// legend: a pill that needs one is a pill that explains itself badly.
const PILL_TIPS = {
  Preview: "Held back from this release — shown because it is switched on in Settings → Views.",
  Bus: "Needs a connected bus — dimmed until one is connected. Opens anyway.",
};
function applyAvailability() {
  const off = !state.connected;
  document.querySelectorAll("#railNav .rail-item").forEach((btn) => {
    const r = VIEW_READY[btn.dataset.view] || {};
    // a held-back view is only in the rail when the person switched it on: a preview
    const dim = r.kind === "bus" && off, preview = r.kind === "soon";
    btn.classList.toggle("is-unavail", dim);
    // A pill only earns rail space while it's telling the truth: "Bus"
    // disappears on connect, "DBC"/"File" state a standing requirement.
    const pill = btn.querySelector(".rail-pill");
    const text = preview ? "Preview" : dim ? "Bus" : r.kind === "input" ? r.pill : "";
    pill.textContent = text;
    pill.hidden = !text;
    pill.classList.toggle("warn", preview);
    pill.dataset.tip = preview ? PILL_TIPS.Preview : dim ? `${r.why} ${PILL_TIPS.Bus}` : r.why || "";
  });
  for (const [view, reason] of Object.entries(LIVE_ONLY_VIEWS)) {
    const section = $("view-" + view);
    if (!section) continue;
    let gate = section.querySelector(".view-gate");
    if (!gate) {
      gate = document.createElement("div");
      gate.className = "view-gate ui-notice warn";
      gate.innerHTML = `<span class="ui-ico">${UI.icons.plug}</span><span class="ui-notice-t gate-msg"></span>` +
        `<button type="button" class="btn btn-primary btn-sm" onclick="openConnect()">Connect a bus</button>`;
      section.insertBefore(gate, section.firstChild);
    }
    gate.querySelector(".gate-msg").textContent = reason;
    gate.hidden = !off;
  }
}

function startPolling(view) {
  if (pollTimer) clearInterval(pollTimer);
  if (view === "dashboard") pollTimer = setInterval(pollDashboard, 400);
  else if (view === "signals") pollTimer = setInterval(pollSignals, 400);
  else if (view === "scheduler") pollTimer = setInterval(pollTx, 700);
  else if (view === "dtc") pollTimer = setInterval(pollDtc, 700);
  else if (view === "decoder") pollTimer = setInterval(pollDecode, 500);
  // The TX view's playback state rides the WebSocket, but the "on the wire"
  // preview is its own REST read, so it needs a poll of its own.
  else if (view === "replay") pollTimer = setInterval(pollTxVerify, 500);
}
// A transient message, as a toast (the pre-1.6 footer status bar). Wording that
// reports a failure gets the red tone, so the 70-odd callers need no change.
const _BAD_WORDS = /\b(error|failed|could not|cannot|invalid|not connected|no confident)\b/i;
function setStatus(t, tone) { UI.toast(t, tone || (_BAD_WORDS.test(String(t)) ? "bad" : "")); }
// An advisory or a failure as one line with its icon — the fact, never a glyph.
// `t` may carry markup the caller built; the caller escapes anything it did not write.
const warnLine = (t) => `<div class="warn-line">${ICONS.alert}<span>${t}</span></div>`;
const badLine = (t) => `<div class="bad-line">${ICONS.alert}<span>${t}</span></div>`;
// A colour token's current value (canvas and inline fills can't say var(--x)
// where they need a hex). Series colours are re-read on a theme change.
const tok = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const seriesColors = () => [1, 2, 3, 4, 5, 6, 7, 8].map((i) => tok(`--series-${i}`));
let SERIES = seriesColors();
UI.onTheme(() => { SERIES = seriesColors(); });
// Sentence case for a state word the server sends lower-case ("playing" → "Playing").
const cap = (s) => (s ? String(s).charAt(0).toUpperCase() + String(s).slice(1) : "");

// ------------------------------------------------------------- connect/record
const HW_NAME = { virtual: "Virtual", neovi: "neoVI", pcan: "PCAN", microchip: "SLCAN" };
async function loadDevices() {
  const { devices } = await api("/api/devices");
  $("devSelect").innerHTML = devices
    .map((d) => `<option value='${JSON.stringify({ hw: d.hw, channel: d.channel })}'>${UI.esc(d.label)}</option>`)
    .join("");
}
window.openConnect = async () => {
  $("connectError").hidden = true;
  $("connectDlg").showModal();
  await loadDevices();
};
$("btnConnect").addEventListener("click", () => openConnect());
$("btnRefreshDevs").addEventListener("click", loadDevices);
$("btnCancelConnect").addEventListener("click", () => $("connectDlg").close());
$("connectForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!$("devSelect").value) return;
  const dev = JSON.parse($("devSelect").value);
  $("btnDoConnect").disabled = true;
  const res = await POST("/api/connect", {
    hw: dev.hw, channel: dev.channel,
    bitrate: parseInt($("bitrateSelect").value, 10), simulate: $("simCheck").checked,
  }).catch((err) => ({ ok: false, error: String(err) }));
  $("btnDoConnect").disabled = false;
  if (res.ok) $("connectDlg").close();
  else { $("connectErrorT").textContent = res.error || "Connection failed"; $("connectError").hidden = false; }
});
// Connected, the bus chip says which bus — and is the way to disconnect it.
function busLabel(c) {
  if (!c) return "Live";
  return `${HW_NAME[c.hw] || c.hw} · ${(c.bitrate / 1000).toFixed(0)} kbit/s`;
}
function refreshConn() {
  if (!state.connected) { state.conn = null; return; }
  api("/api/status").then((d) => {
    state.conn = d.connection || null;
    const c = state.conn;
    $("busChip").title = c ? `${HW_NAME[c.hw] || c.hw} ${c.channel}${c.simulated ? " · synthetic traffic" : ""}` : "";
    paintBusHealth(d.health);
  }).catch(() => {});
}
// The controller's own error state (PCAN), pushed with every live tick. A blinking red LED on
// the adapter is one of these — the user, 25-11-2026: "red light is blinking on the PCAN but
// TX is happening" — so the chip says which, and the hold-tip what to check.
const BUS_HEALTH = {
  "error-warning": { tone: "is-warn", word: "Bus errors",
    tip: "The adapter is counting bus errors (its LED blinks red). Frames still go out, but some are not acknowledged. Check: the bus is terminated (about 60 Ω across CAN-H and CAN-L with power off), the bitrate matches the device, the device is powered and wired H to H, L to L." },
  "error-passive": { tone: "is-warn", word: "Error passive",
    tip: "Many frames are not acknowledged and the controller has gone error passive (LED red). It still sends, more slowly. Check the device is powered, the wiring and the termination (about 60 Ω across CAN-H and CAN-L)." },
  "bus-off": { tone: "is-bad", word: "Bus-off",
    tip: "The controller stopped sending after too many errors. uCANdo resets it, and TX replay carries on by itself once the device acknowledges again." },
  "tx-full": { tone: "is-warn", word: "Queue full",
    tip: "Frames are waiting in the adapter: nothing on the bus is taking them. Check the device is powered and connected." },
};
function paintBusHealth(h) {
  const chip = $("busChip");
  const st = h && BUS_HEALTH[h.state];
  chip.classList.toggle("is-warn", !!st && st.tone === "is-warn");
  chip.classList.toggle("is-bad", !!st && st.tone === "is-bad");
  $("busChipT").textContent = busLabel(state.conn) + (st ? ` · ${st.word}` : "");
  if (st) chip.dataset.tip = st.tip; else delete chip.dataset.tip;
}
$("busChip").addEventListener("click", () => {
  const c = state.conn;
  UI.menu($("busChip"), c ? `${HW_NAME[c.hw] || c.hw} ${c.channel} · ${(c.bitrate / 1000).toFixed(0)} kbit/s` : "Bus",
    [{ label: "Disconnect", run: () => POST("/api/disconnect") }]);
});
async function stopRecording() {
  const r = await POST("/api/logger/record/stop");
  if (r.path) setStatus(`Saved ${Number(r.frames || 0).toLocaleString()} frames → ${r.path}`);
}
$("btnRecord").addEventListener("click", () => {
  if (state.recording) return void stopRecording();
  $("recordDlg").showModal();
  $("recName").select();
});
$("recChip").addEventListener("click", stopRecording);
$("btnCancelRecord").addEventListener("click", () => $("recordDlg").close());
$("recordForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const r = await POST("/api/logger/record/start", { name: $("recName").value || "capture", format: $("recFormat").value });
  $("recordDlg").close();
  setStatus(r.ok ? "Recording → " + r.path : "Record error: " + (r.error || "?"));
});
UI.setLabel($("btnConnect"), "plug", "Connect");
UI.setLabel($("btnRecord"), "record", "Record");
$("btnClear").addEventListener("click", () => POST("/api/logger/clear"));

// ----------------------------------------------------------------- CAN Logger
const fmtPeriod = (ms) => (!ms ? "—" : ms >= 1000 ? (ms / 1000).toFixed(2) + " s" : ms.toFixed(1) + " ms");

function renderLogger(snap) {
  const wasConnected = state.connected;
  state.connected = !!snap.connected;
  state.recording = !!snap.recording;
  if (wasConnected !== state.connected) { applyAvailability(); refreshConn(); }
  if (state.connected) paintBusHealth(snap.bus_health);
  // the banner: Connect while there is no bus; the bus chip (the way to
  // disconnect) once there is. Record while idle; the REC chip (the way to
  // stop) while recording — one control for each state, never two.
  $("btnConnect").hidden = state.connected;
  $("busChip").hidden = !state.connected;
  $("btnRecord").disabled = !state.connected;
  $("btnRecord").hidden = state.recording;
  $("recChip").hidden = !state.recording;
  $("recBadge").classList.toggle("hidden", !state.recording);
  if (state.recording) {
    $("recChipT").textContent = `Recording · ${(snap.record_frames || 0).toLocaleString()} frames`;
  }

  if (snap.replay) renderReplay(snap.replay);
  if (!snap.running) return;

  $("statTotal").textContent = (snap.total || 0).toLocaleString();
  $("statIds").textContent = snap.unique_ids || 0;
  $("statFps").textContent = snap.fps || 0;
  $("statLoad").textContent = (snap.bus_load_pct || 0) + "%";
  $("statElapsed").textContent = (snap.elapsed_s || 0).toFixed(1) + " s";
  $("idCount").textContent = (snap.ids || []).length ? String(snap.ids.length) : "";

  $("idTable").querySelector("tbody").innerHTML = (snap.ids || []).map((s) => `
    <tr><td class="mono">0x${s.id_hex}</td><td><span class="tag" title="${s.ext ? "29-bit extended" : "11-bit standard"}">${s.ext ? "EXT" : "STD"}</span></td>
    <td class="num">${s.dlc}</td><td class="num">${s.count.toLocaleString()}</td><td class="num">${fmtPeriod(s.period_ms)}</td>
    <td class="mono">${s.data || ""}</td></tr>`).join("");
  $("feedTable").querySelector("tbody").innerHTML = (snap.recent || []).map((f) => `
    <tr><td class="num">${f.ts.toFixed(3)}</td><td>0x${f.id_hex}</td><td class="num">${f.dlc}</td><td>${f.data}</td></tr>`).join("");
}

function connectWS() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws/live`);
  ws.onmessage = (e) => { try { renderLogger(JSON.parse(e.data)); } catch (_) {} };
  ws.onclose = () => setTimeout(connectWS, 1000);
}
connectWS();

// ------------------------------------------------------------------------ TX
// One view, five steps: Source -> Playlist -> Patch -> Send -> Verify. The
// optional steps collapse to a one-line summary in their header, so the page
// stays short and each step still says its state without being opened.
document.querySelectorAll(".tx-step-toggle").forEach((el) => {
  const flip = () => {
    const step = $(el.dataset.step);
    step.dataset.open = step.dataset.open === "1" ? "" : "1";
  };
  // The summary is text people copy (a file name, frame counts): a click that
  // ends a selection inside the header must not fold the step under it.
  el.addEventListener("click", () => {
    const sel = window.getSelection();
    if (sel && !sel.isCollapsed && el.contains(sel.anchorNode)) return;
    flip();
  });
  el.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); flip(); }
  });
});
// Open a step programmatically — used when an action only makes sense with it
// visible (adding to the playlist, loading a DBC to patch against).
function txOpenStep(id) { if ($(id)) $(id).dataset.open = "1"; }
const txSum = (id, text) => { if ($(id)) $(id).textContent = text; };

// ------------------------------------------------------------------ TX Replay
async function refreshLogs() {
  const { logs, hidden } = await api("/api/logs");
  // logs taken off the list (Remove) are only hidden: say how many, and offer them back
  $("btnReplayShowAll").classList.toggle("hidden", !hidden);
  $("btnReplayShowAll").textContent = hidden ? `Show all (${hidden} removed)` : "Show all";
  const opts = logs.length
    ? logs.map((l) => `<option value="${l.path}">${l.name} (${(l.size / 1024).toFixed(0)} KB)</option>`).join("")
    : `<option value="">No logs yet</option>`;
  ["replaySelect", "reSelect", "cmpA", "cmpB", "autoreSelect"].forEach((id) => { if ($(id)) $(id).innerHTML = opts; });
  loadReEngines();
}
let reEnginesLoaded = false;
async function loadReEngines() {
  if (reEnginesLoaded || !$("reEngine")) return;
  const { engines } = await api("/api/re/engines");
  if (!engines) return;
  $("reEngine").innerHTML = engines
    .map((e) => `<option value="${e.name}" title="${e.description || ""}">${e.name}</option>`).join("");
  reEnginesLoaded = true;
}
$("btnReplayRescan").addEventListener("click", refreshLogs);
$("btnReRescan").addEventListener("click", refreshLogs);
$("btnReplayUpload").addEventListener("click", () => $("replayFile").click());
// One log or many at once. Several become a playlist in file-name order —
// natural order, so "Buffer2" comes before "Buffer10" — because capture tools
// number the chunks of one session; the file dialog's own order is arbitrary.
$("replayFile").addEventListener("change", async (e) => {
  const files = [...e.target.files].sort((a, b) =>
    a.name.localeCompare(b.name, undefined, { numeric: true, sensitivity: "base" }));
  e.target.value = "";                       // the same files can be chosen again
  if (!files.length) return;
  const paths = [];
  for (let i = 0; i < files.length; i++) {
    $("replayMeta").textContent = files.length > 1
      ? `Uploading ${i + 1} of ${files.length} — ${files[i].name}` : `Uploading ${files[i].name}…`;
    const r = await apiUpload("/api/upload", files[i]).catch((err) => ({ error: String(err) }));
    if (r && r.path) paths.push(r.path);
    else setStatus(`Upload failed: ${files[i].name} — ${(r && r.error) || "unknown error"}`);
  }
  await refreshLogs();
  [...$("replaySelect").options].forEach((o) => { o.selected = paths.includes(o.value); });
  $("replaySelCount").textContent = paths.length > 1 ? `${paths.length} files selected` : "";
  if (!paths.length) { $("replayMeta").textContent = ""; return; }
  if (paths.length === 1) return void loadReplay();
  const gap = $("txAutoGap").checked ? "auto" : 0;
  txItems = paths.map((p) => ({ path: p, gap_before_ms: gap, repeat: 1, baud: txBaud }));
  txOpenStep("stepPlaylist");                // the result must be visible
  await pushPlan();
  setStatus(`Uploaded ${paths.length} logs — they play in order as one playlist`);
});
let replayMeta = null;                      // last loaded meta, for the bitrate button
let txItems = [];                           // the playlist being edited (TxItem dicts)
// Bitrate the operator declared for these captures. A PCAN .trc records none at
// any format version, so the reader assumes 500 k; this overrides that and is
// what the bus-load estimate and the bitrate-mismatch check then use.
let txBaud = null;

const txSelectedPaths = () => [...$("replaySelect").selectedOptions].map((o) => o.value).filter(Boolean);

$("replaySelect").addEventListener("change", () => {
  const n = txSelectedPaths().length;
  $("replaySelCount").textContent = n > 1 ? `${n} files selected` : "";
  // One file selected and no playlist yet: behave like the old single-file picker.
  if (n === 1 && txItems.length <= 1) loadReplay();
});

async function loadReplay() {
  const path = txSelectedPaths()[0]; if (!path) return;
  $("replayMeta").textContent = "reading log…";
  $("replayWarn").textContent = "";
  txItems = [{ path, gap_before_ms: 0, repeat: 1, baud: txBaud }];
  renderTxItems();
  showReplayMeta(await POST("/api/replay/load", { path, baud: txBaud }));
}
// A bitrate is not a bitrate: where it came from decides what the operator
// should do next. "from log" needs no action; "assumed" invites a declaration;
// a mismatch against the connected bus means different things in each case. So
// the provenance is never dropped from the wording.
function baudLabel(m) {
  if (!m.baud) return "bitrate unknown";
  const k = `${(m.baud / 1000).toFixed(0)} kbit/s`;
  if (m.baud_source === "assumed") return `${k} assumed — this format records none`;
  if (m.baud_source === "declared") return `${k} (you declared)`;
  if (m.baud_source === "mixed") return `${k} (mixed sources)`;
  return `${k} (from log)`;
}

// Declaring the capture bitrate rebuilds the plan: bus load and the mismatch
// check are derived from it. The parse cache means this costs no re-read.
$("replayBaud").addEventListener("change", async () => {
  txBaud = $("replayBaud").value ? +$("replayBaud").value : null;
  txItems.forEach((it) => { it.baud = txBaud; });
  if (txItems.length) await pushPlan();
});

// Re-target an already-parsed log: network / tool-TX filter. Cheap — no re-parse.
async function reselectReplay() {
  if (!replayMeta) return;
  showReplayMeta(await POST("/api/replay/select", {
    network: $("replayNetwork").value || null,
    skip_tx: $("replaySkipTx").checked,
  }));
}

// ----- playlist ------------------------------------------------------------
async function pushPlan() {
  if (!txItems.length) return;
  $("replayMeta").textContent = `reading ${txItems.length} log${txItems.length > 1 ? "s" : ""}…`;
  showReplayMeta(await POST("/api/tx/plan", { items: txItems, name: $("txScenario").value || "" }));
}
// NB: distinct from the TX Scheduler's own "btnTxAdd" — sharing that id made
// getElementById return the scheduler's button and silently killed one of them.
$("btnTxPlaylistAdd").addEventListener("click", () => {
  const paths = txSelectedPaths();
  if (!paths.length) return setStatus("Select one or more logs first");
  const gap = $("txAutoGap").checked ? "auto" : 0;
  paths.forEach((p) => txItems.push({ path: p, gap_before_ms: gap, repeat: 1, baud: txBaud }));
  txOpenStep("stepPlaylist");            // the result of the click must be visible
  pushPlan();
});
// Source → Clear and Playlist → Clear: forget the log on the server too. Clearing
// only the page left the plan loaded, and Play then transmitted a log the screen
// no longer showed.
async function clearReplaySource() {
  const r = await POST("/api/replay/unload").catch((e) => ({ ok: false, error: String(e) }));
  if (r && r.ok === false) return void setStatus(r.error || "Could not clear the source");
  txItems = []; replayMeta = null; txBaud = null;
  [...$("replaySelect").options].forEach((o) => { o.selected = false; });
  $("replaySelCount").textContent = "";
  $("replayMeta").textContent = ""; $("replayWarn").innerHTML = "";
  $("replayNetwork").innerHTML = "";
  $("replayBaud").value = "";
  $("replayBaudWrap").classList.add("hidden");
  $("btnReplayBitrate").classList.add("hidden");
  renderTxItems();
  txSum("sumSource", "No log chosen"); $("sumSource").classList.remove("has-warn");
  txSum("sumPlaylist", "Single file");
}
$("btnTxClear").addEventListener("click", clearReplaySource);
$("btnReplayClear").addEventListener("click", clearReplaySource);

// Source → Remove: take logs off the list. Only hidden — an upload folder can hold the only
// copy of a capture session — and "Show all" brings them back.
$("btnReplayRemove").addEventListener("click", async () => {
  let paths = txSelectedPaths();
  const all = [...$("replaySelect").options].map((o) => o.value).filter(Boolean);
  if (!all.length) return;
  if (!paths.length) {
    if (!(await UI.confirm({ title: "Remove every log from the list?",
      text: `All ${all.length} logs leave this list. Nothing is deleted from disk — Show all brings them back.`,
      action: "Remove all" }))) return;
    paths = all;
  }
  const r = await POST("/api/logs/hide", { paths });
  if (!r.ok) {
    // FastAPI answers an unknown route with {"detail":"Not Found"}: the server is older than the page
    return void setStatus(r.detail === "Not Found"
      ? "This copy of uCANdo is older than its page — restart it to remove logs"
      : (r.error || "Could not remove the logs"));
  }
  if (txItems.some((it) => paths.includes(it.path))) await clearReplaySource();
  await refreshLogs();
  $("replaySelCount").textContent = "";
  setStatus(`Removed ${paths.length} log${paths.length === 1 ? "" : "s"} from the list`);
});
$("btnReplayShowAll").addEventListener("click", async () => {
  await POST("/api/logs/unhide");
  await refreshLogs();
});
$("txAutoGap").addEventListener("change", () => {
  const gap = $("txAutoGap").checked ? "auto" : 0;
  txItems.forEach((it) => { it.gap_before_ms = gap; });
  pushPlan();
});

function renderTxItems(resolved) {
  $("txEmpty").classList.toggle("hidden", txItems.length > 0);
  $("txItems").innerHTML = txItems.map((it, i) => {
    const info = resolved && resolved[i];
    const detail = info
      ? `${info.frames.toLocaleString()} frames · ${info.duration_s.toFixed(1)} s` +
        (info.gap_s ? ` · +${info.gap_s.toFixed(2)} s gap` : "")
      : "…";
    return `<tr data-i="${i}">
      <td class="tx-n">${i + 1}</td>
      <td class="tx-name" title="${it.path}">${(info && info.label) || it.path.split(/[\\/]/).pop()}
        <div class="tx-detail">${detail}</div></td>
      <td class="tx-rep-cell" data-tip="Passes of this file. 0 plays it endlessly.">×<input type="number" class="tx-rep" min="0" max="100000" value="${it.repeat || 1}"
             aria-label="Passes" /></td>
      <td class="tx-btns">
        <button type="button" class="btn-mini icon-only" data-act="up" title="Move up" aria-label="Move up" ${i === 0 ? "disabled" : ""}>${ICONS.chevronUp}</button>
        <button type="button" class="btn-mini icon-only" data-act="down" title="Move down" aria-label="Move down" ${i === txItems.length - 1 ? "disabled" : ""}>${ICONS.chevronDown}</button>
        <button type="button" class="btn-mini" data-act="del">Remove</button></td></tr>`;
  }).join("");
  const totalFrames = resolved ? resolved.reduce((a, r, i) => a + r.frames * Math.max(1, txItems[i].repeat || 1), 0) : 0;
  $("txTotals").textContent = txItems.length > 1 && resolved
    ? `${txItems.length} items · ${totalFrames.toLocaleString()} frames per pass` : "";
}

$("txItems").addEventListener("click", (e) => {
  const btn = e.target.closest("button[data-act]"); if (!btn) return;
  const i = +btn.closest("tr").dataset.i;
  const act = btn.dataset.act;
  if (act === "del") txItems.splice(i, 1);
  else if (act === "up") txItems.splice(i - 1, 0, txItems.splice(i, 1)[0]);
  else if (act === "down") txItems.splice(i + 1, 0, txItems.splice(i, 1)[0]);
  txItems.length ? pushPlan() : renderTxItems();
});
$("txItems").addEventListener("change", (e) => {
  if (!e.target.classList.contains("tx-rep")) return;
  txItems[+e.target.closest("tr").dataset.i].repeat = Math.max(0, parseInt(e.target.value, 10) || 1);
  pushPlan();
});

// ----- signal overrides & loop-seam continuity -----------------------------
let txPatch = null;                         // last /api/tx/patch state
let txSeamFound = null;                     // last "Detect from log" result

async function refreshPatch(state) {
  txPatch = state || await api("/api/tx/patch");
  const on = !!txPatch.loaded;
  $("txPatchNone").classList.toggle("hidden", on);
  $("txPatchBody").classList.toggle("hidden", !on);
  if (!on) return;
  if (txPatch.messages && txPatch.messages.length && !$("txPatchMsg").options.length) {
    $("txPatchMsg").innerHTML = txPatch.messages
      .map((m) => `<option value="${m.message}">${m.message} (0x${m.id_hex})</option>`).join("");
    fillPatchSignals();
  }
  renderPatchRules();
}
function patchMessages() { return (txPatch && txPatch.messages) || []; }
function fillPatchSignals() {
  const msg = patchMessages().find((m) => m.message === $("txPatchMsg").value);
  $("txPatchSig").innerHTML = msg
    ? msg.signals.map((s) => `<option value="${s.signal}">${s.signal}${s.unit ? " (" + s.unit + ")" : ""}</option>`).join("")
    : "";
  // Byte-aligned 8-bit fields are the only ones we can recompute a checksum into.
  $("txCsumSig").innerHTML = `<option value="">None</option>` + (msg
    ? msg.signals.filter((s) => s.length === 8)
        .map((s) => `<option value="${s.signal}">${msg.message}.${s.signal}</option>`).join("")
    : "");
  showPatchHint();
}
function showPatchHint() {
  const msg = patchMessages().find((m) => m.message === $("txPatchMsg").value);
  const sig = msg && msg.signals.find((s) => s.signal === $("txPatchSig").value);
  $("txPatchHint").textContent = sig
    ? `${sig.length} bit ${sig.signed ? "signed" : "unsigned"} · ×${sig.scale}` +
      (sig.offset ? ` ${sig.offset > 0 ? "+" : ""}${sig.offset}` : "") +
      (sig.minimum != null && sig.maximum != null ? ` · range ${sig.minimum}…${sig.maximum}` : "")
    : "";
}
$("txPatchMsg").addEventListener("change", fillPatchSignals);
$("txPatchSig").addEventListener("change", showPatchHint);

$("btnTxDbcUpload").addEventListener("click", () => $("txDbcFile").click());
$("txDbcFile").addEventListener("change", async (e) => {
  const f = e.target.files[0]; if (!f) return;
  const up = await apiUpload("/api/upload", f);
  const r = await POST("/api/tx/patch/dbc", { path: up.path });
  if (!r.ok) return setStatus(r.error);
  $("txPatchMsg").innerHTML = "";            // force a rebuild for the new DBC
  txOpenStep("stepPatch");                   // the result of the click must be visible
  refreshPatch(r);
});
$("btnTxDbcViewer").addEventListener("click", async () => {
  const r = await POST("/api/tx/patch/dbc", { use_viewer: true });
  if (!r.ok) return setStatus(r.error);
  $("txPatchMsg").innerHTML = "";
  txOpenStep("stepPatch");
  refreshPatch(r);
});

$("btnTxPatchAdd").addEventListener("click", async () => {
  const value = parseFloat($("txPatchVal").value);
  if (Number.isNaN(value)) return setStatus("enter a value to force");
  const r = await POST("/api/tx/patch/override", {
    message: $("txPatchMsg").value, signal: $("txPatchSig").value, value });
  r.ok ? refreshPatch(r) : setStatus(r.error);
});
$("btnTxPatchClear").addEventListener("click", async () => refreshPatch(await POST("/api/tx/patch/clear")));

function renderPatchRules() {
  const rules = (txPatch && txPatch.rules) || [];
  const checks = (txPatch && txPatch.checksums) || [];
  const KIND = { set: "forced", monotonic: "continuous", counter: "regenerated" };
  // Patching changes what goes on the wire, so a collapsed step must still say
  // so plainly — silently-active overrides would invalidate a byte comparison.
  txSum("sumPatch", !rules.length && !checks.length
    ? (txPatch && txPatch.loaded ? `${txPatch.dbc} loaded · no rules` : "Off — bytes go out exactly as captured")
    : [rules.filter((r) => r.kind === "set").map((r) => `${r.signal}=${r.value}`).join(", "),
       rules.some((r) => r.kind === "monotonic") ? "odometer continuous" : null,
       rules.some((r) => r.kind === "counter") ? "counters regenerated" : null,
       checks.length ? `${checks.length} checksum` : null].filter(Boolean).join(" · "));
  $("txPatchRules").innerHTML = rules.map((r) => `<tr>
      <td class="tx-name mono">${r.message}.${r.signal}
        <div class="tx-detail">${cap(KIND[r.kind] || r.kind)}${
          r.kind === "set" ? ` at ${r.value}${r.unit ? " " + r.unit : ""}` : ""}${
          r.last != null ? ` · last sent ${r.last}${r.unit ? " " + r.unit : ""}` : ""}</div></td>
      <td class="tx-btns"><button type="button" class="btn-mini" data-msg="${r.message}" data-sig="${r.signal}">Remove</button></td>
    </tr>`).join("") + checks.map((c) => `<tr>
      <td class="tx-name mono">${c.message}.${c.signal}
        <div class="tx-detail">Checksum recomputed (${c.algorithm})</div></td>
      <td class="tx-btns"></td></tr>`).join("");
}
$("txPatchRules").addEventListener("click", async (e) => {
  const btn = e.target.closest("button[data-sig]"); if (!btn) return;
  refreshPatch(await POST("/api/tx/patch/override",
    { message: btn.dataset.msg, signal: btn.dataset.sig, remove: true }));
});

$("btnTxPatchAnalyze").addEventListener("click", async () => {
  $("txPatchSeamInfo").textContent = "Scanning the log…";
  const r = await POST("/api/tx/patch/analyze");
  if (!r.ok) { $("txPatchSeamInfo").textContent = ""; return setStatus(r.error); }
  txSeamFound = r;
  $("txPatchSeamInfo").textContent =
    `${r.monotonic.length} rising · ${r.counters.length} counter-like in ${r.scanned}`;
  $("txSeamBox").classList.remove("hidden");
  // Nothing is pre-checked on purpose: "rose during this capture" is not the
  // same claim as "must climb forever". A battery temperature drifting up over
  // 41 s is monotonic in the data and would be wrong to accumulate on a loop.
  const star = UI.ico("star", "ico ico-star");
  const list = (items, group, label, tip) => `<div><div class="seam-h" data-tip="${tip}">${label}</div>` +
    (items.length ? items.slice(0, 12).map((e) => `<label class="check">
        <input type="checkbox" data-group="${group}" data-msg="${e.message}" data-sig="${e.signal}" />
        <span class="mono">${e.message}.${e.signal}</span>${e.accumulator_hint ? `<span title="Name looks like an accumulator">${star}</span>` : ""}
        <span class="ui-count">${
          group === "monotonic" ? `+${e.rise}${e.unit ? " " + e.unit : ""}` : `step ${e.step}, ${e.wraps} wraps`}</span>
      </label>`).join("") : `<div class="muted-line">None detected</div>`) + `</div>`;
  $("txSeamLists").innerHTML =
    list(r.monotonic, "monotonic", "Rose through this capture",
      "Signals that only went up in this log. A star marks a name that looks like an accumulator (odometer, energy total).") +
    list(r.counters, "counters", "Rolls over", "Rolling counters — safe to regenerate, so they never jump at a loop.");
});

$("btnTxSeamApply").addEventListener("click", async () => {
  const pick = (group) => [...document.querySelectorAll(`#txSeamLists input[data-group="${group}"]:checked`)]
    .map((el) => [el.dataset.msg, el.dataset.sig]);
  const body = { monotonic: pick("monotonic"), counters: pick("counters"), checksums: [] };
  if ($("txCsumSig").value) {
    body.checksums = [{ message: $("txPatchMsg").value, signal: $("txCsumSig").value,
                        algorithm: $("txCsumAlgo").value }];
  }
  const r = await POST("/api/tx/patch/seam", body);
  r.ok ? refreshPatch(r) : setStatus(r.error);
});

// ----- saved scenarios -----------------------------------------------------
async function refreshScenarios(selected) {
  const r = await api("/api/tx/scenarios");
  $("txScenario").innerHTML = `<option value="">Saved scenarios</option>` +
    (r.scenarios || []).map((s) => `<option value="${s}"${s === selected ? " selected" : ""}>${s}</option>`).join("");
}
$("btnTxScenarioSave").addEventListener("click", async () => {
  if (!txItems.length) return setStatus("Nothing to save — the playlist is empty");
  const name = await UI.prompt({ title: "Save playlist", label: "Scenario name",
    value: $("txScenario").value || "bench-scenario", action: "Save" });
  if (!name) return;
  const r = await POST("/api/tx/save", { name });
  if (!r.ok) return setStatus(r.error);
  await refreshScenarios(name);
  setStatus(`Saved scenario “${name}”`);
});
$("btnTxScenarioLoad").addEventListener("click", async () => {
  const name = $("txScenario").value; if (!name) return;
  const r = await POST("/api/tx/load", { name });
  if (!r.ok) return setStatus(r.error);
  txItems = r.meta.items.map((it) => ({
    path: it.path, repeat: it.repeat, network: it.network,
    gap_before_ms: $("txAutoGap").checked ? "auto" : 0,
  }));
  showReplayMeta(r);
  renderTxItems(r.meta.items);
});
$("btnTxScenarioDelete").addEventListener("click", async () => {
  const name = $("txScenario").value; if (!name) return;
  if (!(await UI.confirm({ title: "Delete scenario?", text: `The saved scenario “${name}” will be removed.`,
    action: "Delete", tone: "danger" }))) return;
  await POST("/api/tx/delete", { name });
  refreshScenarios();
});
$("replayNetwork").addEventListener("change", reselectReplay);
$("replaySkipTx").addEventListener("change", reselectReplay);

function showReplayMeta(r) {
  if (!r.ok) { replayMeta = null; $("replayMeta").textContent = r.error; return; }
  const m = replayMeta = r.meta;
  // Networks come from the log itself; a Vehicle Spy capture holds several.
  const carrying = (m.networks || []).filter((n) => n.frames);
  $("replayNetwork").innerHTML = carrying.length
    ? carrying.map((n) => `<option value="${n.name}"${n.name === m.network ? " selected" : ""}>${n.name} · ${n.frames.toLocaleString()} frames</option>`).join("")
    : `<option value="">—</option>`;
  renderTxItems(m.items);
  const bits = [
    m.item_count > 1 ? `${m.item_count} files` : null,
    `${m.frames.toLocaleString()} frames`,
    `${m.duration_s.toFixed(1)} s`,
    `${m.ids.length} IDs`,
    m.fps ? `${m.fps.toFixed(0)} fps` : null,
    baudLabel(m),
    m.load_pct != null ? `~${m.load_pct}% bus load` : null,
  ].filter(Boolean);
  $("replayMeta").textContent = bits.join(" · ");
  $("replayWarn").innerHTML = (r.warnings || []).map((w) => warnLine(UI.esc(w))).join("");
  $("btnReplayBitrate").classList.toggle("hidden", !m.baud);
  // Offer the declaration only for formats that record no bitrate — otherwise
  // the log already knows and overriding it would just be a way to be wrong.
  const declarable = m.baud_source === "assumed" || m.baud_source === "declared";
  $("replayBaudWrap").classList.toggle("hidden", !declarable);
  if (declarable) $("replayBaud").value = m.baud_source === "declared" ? String(m.baud) : "";

  // Header summaries, so a collapsed step still reports what it holds. A
  // warning always shows in the summary — it must not be hidden by collapsing.
  const name = (m.path || "").split(/[\\/]/).pop().replace(/\.[^.]+$/, "");
  const warn = (r.warnings || []).length;
  txSum("sumSource", [
    m.item_count > 1 ? `${m.item_count} files` : name,
    m.network, `${m.frames.toLocaleString()} frames`,
    m.baud ? `${(m.baud / 1000).toFixed(0)} kbit/s${m.baud_source === "assumed" ? " (assumed)" : ""}`
           : "bitrate unknown",
    warn ? `${warn} note${warn > 1 ? "s" : ""}` : null,
  ].filter(Boolean).join(" · "));
  $("sumSource").classList.toggle("has-warn", !!warn);
  txSum("sumPlaylist", m.item_count > 1
    ? `${m.item_count} files · ${m.frames.toLocaleString()} frames per pass · ${m.duration_s.toFixed(1)} s`
    : "Single file");
}

// Reconnect the current adapter at the log's own bitrate — the mismatch that
// otherwise looks like "the bus is dead" on the bench.
$("btnReplayBitrate").addEventListener("click", async () => {
  if (!replayMeta || !replayMeta.baud) return;
  const conn = (await api("/api/status")).connection;
  if (!conn) { setStatus("Not connected — connect an adapter, then apply the log bitrate"); return; }
  if (conn.bitrate === replayMeta.baud) { setStatus("Already at the log's bitrate"); return; }
  const r = await POST("/api/connect", { hw: conn.hw, channel: conn.channel,
    bitrate: replayMeta.baud, fd: !!conn.fd, simulate: !!conn.simulated });
  setStatus(r.ok ? `Reconnected at ${(replayMeta.baud / 1000).toFixed(0)} kbit/s` : r.error);
  reselectReplay();
});

$("replayRepeat").addEventListener("change", () => {
  $("replayCount").classList.toggle("hidden", $("replayRepeat").value !== "n");
});
function replayPasses() {
  const mode = $("replayRepeat").value;
  if (mode === "0") return 0;                              // endless
  if (mode === "n") return Math.max(2, parseInt($("replayCount").value, 10) || 2);
  return 1;
}
// One button that says what a click will do (the user, 25-11-2026: "instead of having separate
// play and pause buttons, a single button, green to play and another colour for pause"):
// Play (green) → Pause (amber) while sending → Resume (green) while paused. Waiting for the bus it
// is a greyed Pause: Stop is what ends that wait.
function paintPlayButton(st) {
  const b = $("btnPlay");
  const mode = st === "playing" ? "pause" : st === "paused" ? "resume" : st === "recovering" ? "waiting" : "play";
  if (b.dataset.mode === mode) return;
  b.dataset.mode = mode;
  const hold = mode === "pause" || mode === "waiting";
  b.innerHTML = (hold ? ICONS.pause : ICONS.play) +
    `<span>${hold ? "Pause" : mode === "resume" ? "Resume" : "Play"}</span>`;
  b.classList.add("btn-ico");
  b.classList.toggle("btn-primary", !hold);
  b.classList.toggle("btn-pause", hold);
  b.disabled = mode === "waiting";
  if (mode === "waiting") b.dataset.tip = "Waiting for the bus — it carries on by itself. Stop ends the wait.";
  else delete b.dataset.tip;
}
$("btnPlay").addEventListener("click", () => {
  const mode = $("btnPlay").dataset.mode || "play";
  if (mode === "pause") return void POST("/api/replay/pause");
  if (mode === "resume") return void POST("/api/replay/resume");
  POST("/api/replay/play", { speed: parseFloat($("speedRange").value), repeat: replayPasses() })
    .then((r) => { if (!r.ok) setStatus(r.error); });
});
$("btnStop").addEventListener("click", () => POST("/api/replay/stop"));
$("btnStep").addEventListener("click", () => POST("/api/replay/step"));
$("speedRange").addEventListener("input", () => {
  $("speedLabel").textContent = parseFloat($("speedRange").value).toFixed(1) + "×";
  POST("/api/replay/speed", { speed: parseFloat($("speedRange").value) });
});
const REPLAY_TONE = { playing: "ok", paused: "warn", recovering: "warn", error: "bad" };
function renderReplay(s) {
  paintPlayButton(s.state);
  $("replayState").textContent = s.state === "playing" && s.passes !== 1
    ? `Playing ${s.pass_no}/${s.passes || "∞"}`
    : s.state === "recovering" ? "Waiting for the bus" : cap(s.state);
  $("replayState").className = "tag " + (REPLAY_TONE[s.state] || "");
  $("replayBar").style.width = (s.progress * 100).toFixed(1) + "%";
  $("replayCursor").textContent = `${s.cursor_s.toFixed(3)} s · ${s.sent.toLocaleString()} sent · ${s.cursor}/${s.total}`;
  // Which file is on the wire right now — said for a single file too (the user, 24-11-2026:
  // "unable to distinguish which file is transmitting"). The full path is the hover title.
  const active = s.state === "playing" || s.state === "paused" || s.state === "recovering";
  const items = (replayMeta && replayMeta.items) || [];
  const fullPath = (items[s.item] && items[s.item].path) || (replayMeta && replayMeta.path) || "";
  const fileName = s.item_label || fullPath.split(/[\\/]/).pop() || "";
  $("replayNow").classList.toggle("is-live", s.state === "playing");
  $("replayNow").title = fullPath;
  $("replayNow").textContent = s.state === "recovering" && s.recovering
    // the bus stopped taking frames: say so, and what usually causes it — playback carries on by itself
    ? `Waiting for the bus for ${tvFmtAge(s.recovering.since_s)}${s.recovering.tries ? ` · try ${s.recovering.tries}` : ""}` +
      ` — no acknowledgement. Is the device powered, the bus terminated (about 60 Ω), the bitrate right? ` +
      `Sending resumes from ${fileName || "the same frame"} by itself.`
    : active && fileName
    ? `${s.state === "paused" ? "Paused on" : "Now sending"} ${fileName}` +
      (s.item_count > 1 ? ` · file ${s.item + 1} of ${s.item_count}` +
        (s.item_repeat !== 1 ? ` (its pass ${s.item_pass} of ${s.item_repeat || "endless"})` : "") : "") +
      (s.passes !== 1 ? ` · pass ${s.pass_no} of ${s.passes || "endless"}` : "")
    : "";
  document.querySelectorAll("#txItems tr").forEach((tr, i) =>
    tr.classList.toggle("tx-now", s.item_count > 1 && i === s.item &&
                                  (s.state === "playing" || s.state === "paused")));
  const h = s.health;
  if (!h) return;
  // Health, not decoration: on a real capture the OS clock is the limit, so show
  // achieved vs target rate and how far off the deadlines we ran.
  const parts = [`${h.fps.toFixed(0)} fps sent`];
  if (h.target_fps) parts.push(`target ${h.target_fps.toFixed(0)}`);
  parts.push(`drift ${h.drift_ms.toFixed(0)} ms`,
             `late ${h.late_pct.toFixed(1)}% (max ${h.max_late_ms.toFixed(1)} ms)`,
             `burst ≤${h.burst_max}`);
  if (h.errors) parts.push(`TX errors ${h.errors}`);
  if (h.recoveries) parts.push(`bus back ${h.recoveries}× after ${tvFmtAge(h.outage_s)} without it`);
  // "Behind" is only meaningful while frames are going out: paused, the wall
  // clock runs on and the same figure would blame the speed for the pause.
  const behind = h.keeping_up === false && s.state === "playing";
  if (s.error && s.state === "recovering") {
    $("replayHealth").innerHTML = UI.esc(parts.join(" · ")) + warnLine(UI.esc(s.error));
  } else if (s.error) {
    $("replayHealth").innerHTML = badLine(UI.esc(s.error));
  } else if (behind) {
    // Say it plainly rather than leaving it to be inferred from late_pct.
    $("replayHealth").innerHTML = UI.esc(parts.join(" · ")) +
      warnLine(`Cannot sustain ${s.speed}× — sending ${h.fps.toFixed(0)} of ` +
        `${h.target_fps.toFixed(0)} fps, ${(h.drift_ms / 1000).toFixed(1)} s behind. Lower the speed.`);
  } else {
    $("replayHealth").textContent = parts.join(" · ");
  }
  // Send's own header summary: state, position and whether it is keeping up —
  // the three things you glance at while it runs.
  txSum("sumSend", s.state === "recovering" && s.recovering
    ? `Waiting for the bus · ${tvFmtAge(s.recovering.since_s)}`
    : s.state === "playing" || s.state === "paused"
    ? [fileName || null, `${(s.progress * 100).toFixed(0)}%`, `${s.sent.toLocaleString()} sent`,
       h.fps ? `${h.fps.toFixed(0)} fps` : null,
       behind ? "behind" : null].filter(Boolean).join(" · ")
    : s.state === "done" ? `Finished · ${s.sent.toLocaleString()} frames sent`
    : s.error ? s.error
    : s.state === "empty" ? "No log loaded"          // after Clear: "Ready" would promise a Play that sends nothing
    : "Ready");
  $("sumSend").classList.toggle("has-warn", !!s.error || behind);
}

// ----------------------------------------------------------------- TX Monitor
// What we transmitted (post-patch, as handed to the adapter) -> what it should
// mean -> whether the cloud got the same bytes.
let tvSelId = null, tvSelSig = 0, tvDecoded = null, tvRecording = false;
let tvDefIds = new Set();                   // IDs the loaded definition can decode

// ---- Transmit signal: Tiles / Bytes -------------------------------------------
// Two views of what left the machine. Tiles: every signal the loaded definition
// describes, the way the device's cloud panel shows it — the picture to hold up
// beside the cloud. Bytes: every transmitted ID's raw payload, plus one ID's bit
// layout. A tile opens its ID in Bytes, so choosing tiles loses nothing.
// Changes light up in both (a tile's value, a byte) and fade over TV_FLASH_MS.
const TV_FLASH_MS = 1500;
let tvMode = UI.store.get("tv.mode", null);       // "tiles" | "bytes"; null: tiles once a definition is loaded
let tvShow = UI.store.get("tv.show", null);       // "all" | "pinned"; null: pinned when there are pins
let tvIdFilter = UI.store.get("tv.idfilter", "all");  // "all" | "def"
let tvSearch = "";
let tvDefinition = null;                          // the loaded definition's name
let tvSelSigName = null;                          // a tile opened in Bytes selects its signal by name
let tvScrollToSel = false;
let tvLastLive = null, tvLastSigs = null;
let tvTilesShape = "", tvIdsShape = "";           // the structure last drawn: same shape → update in place
const tvBytesSeen = new Map();                    // id → { data, at: [when each byte last changed] }
const tvSigSeen = new Map();                      // tile key → { v, at }

const tvDefKind = () => (/JSON/.test(tvDefinition || "") ? "JSON" : "DBC");
const tvPinsKey = () => "tv.pins:" + (tvDefinition || "");
function tvPins() { try { return JSON.parse(UI.store.get(tvPinsKey(), "[]")) || []; } catch (e) { return []; } }
function tvSetPins(p) { UI.store.set(tvPinsKey(), p.length ? JSON.stringify(p) : null); }
const tvCurrentMode = () => tvMode || (tvDefinition ? "tiles" : "bytes");
const tvFmtPeriod = (ms) => (ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toFixed(ms < 10000 ? 1 : 0)} s`);
const tvFmtAge = (s) => (s < 60 ? `${Math.round(s)} s` : `${Math.floor(s / 60)} min ${Math.round(s % 60)} s`);
// Stopped by its *own* rhythm: 3 s of silence is nothing for a 10 s message and an
// outage for a 10 ms one. Paused playback and S8-style silence go grey honestly —
// it is what the device sees too.
function tvIsStale(m) {
  const p = m.period_ms ? m.period_ms / 1000 : null;
  return m.age_s > Math.max(p ? 3 * p : 3, 1);
}

// A segmented control redrawn only when its options or choice change — redrawing
// it on every poll would eat clicks and focus.
function tvSeg(host, opts, cur, pick) {
  const sig = JSON.stringify([opts, cur]);
  if (host.dataset.sig === sig) return;
  host.dataset.sig = sig;
  segButtons(host, opts, cur, pick);
}
function tvApplyMode() {
  const m = tvCurrentMode();
  $("tvTilesPane").classList.toggle("hidden", m !== "tiles");
  $("tvBytesPane").classList.toggle("hidden", m !== "bytes");
  tvSeg($("tvMode"), [{ id: "tiles", label: "Tiles" }, { id: "bytes", label: "Bytes" }], m, (id) => {
    tvMode = id; UI.store.set("tv.mode", id); tvTilesShape = ""; tvIdsShape = "";
    tvApplyMode(); pollTxVerify();
  });
}

async function pollTxVerify() {
  const tiles = tvCurrentMode() === "tiles";
  const [live, sigs] = await Promise.all([api("/api/tx/live"), tiles ? api("/api/tx/live/signals") : null]);
  if (!live || !live.ok) return;
  tvLastLive = live;
  tvRecording = !!live.recording;
  tvDefIds = new Set(live.def_ids || []);
  if ((live.definition || null) !== tvDefinition) {     // pins and the default view follow the definition
    tvDefinition = live.definition || null;
    tvTilesShape = ""; tvIdsShape = "";
    tvApplyMode();
  }
  $("tvStatus").textContent =
    `${live.frames.toLocaleString()} frames transmitted · ${live.unique_ids} IDs` +
    (live.recording ? ` · recording ${live.recorded.toLocaleString()}` : " · not recording");
  $("btnTvRecord").textContent = live.recording ? "Stop recording" : "Start recording";
  if (live.definition) $("tvDefName").textContent = live.definition;
  tvTrackBytes(live.ids);
  if (tvCurrentMode() === "tiles") {
    if (sigs) { tvLastSigs = sigs; tvRenderTiles(); }
    else pollTxVerify();                                // the definition just arrived: fetch its tiles
  } else tvRenderIds(live);
}

// When each byte of each ID last changed — what the Bytes view lights up.
function tvTrackBytes(rows) {
  const now = performance.now();
  rows.forEach((r) => {
    const prev = tvBytesSeen.get(r.id);
    if (!prev || prev.data.length !== r.data.length) {
      tvBytesSeen.set(r.id, { data: r.data, at: new Array(r.data.length / 2).fill(prev ? now : 0) });
      return;
    }
    if (prev.data === r.data) return;
    for (let i = 0; i < prev.at.length; i++) {
      if (prev.data.substr(i * 2, 2) !== r.data.substr(i * 2, 2)) prev.at[i] = now;
    }
    prev.data = r.data;
  });
}
const tvByteLit = (id, i, now) => {
  const s = tvBytesSeen.get(id);
  return !!(s && s.at[i] && now - s.at[i] < TV_FLASH_MS);
};

// ---- Bytes: the transmitted IDs ----
function tvRenderIds(live) {
  const all = live.ids;
  const tbody = $("tvIdTable").querySelector("tbody");
  const known = tvDefIds.size;
  const nIn = all.filter((r) => tvDefIds.has(r.id)).length;
  const filter = known ? tvIdFilter : "all";
  $("tvIdFilter").classList.toggle("hidden", !known);
  if (known) {
    tvSeg($("tvIdFilter"), [{ id: "all", label: `All ${all.length}` }, { id: "def", label: `In ${tvDefKind()} ${nIn}` }],
      filter, (id) => { tvIdFilter = id; UI.store.set("tv.idfilter", id); tvIdsShape = ""; tvRenderIds(tvLastLive); });
  }
  $("tvIdCount").textContent = known ? `${nIn} of ${all.length} in the ${tvDefKind()}` : String(all.length);
  // Nothing on the wire yet: say what to do instead of showing a blank panel.
  if (!all.length) {
    tbody.innerHTML = `<tr><td colspan="4" class="tv-empty">Nothing transmitted yet.</td></tr>`;
    $("tvDecode").innerHTML = ""; tvIdsShape = "";
    return;
  }
  const rows = filter === "def" ? all.filter((r) => tvDefIds.has(r.id)) : all;
  if (!rows.length) {
    tbody.innerHTML = `<tr><td colspan="4" class="tv-empty">None of the ${all.length} transmitted IDs is in ${UI.esc(tvDefinition || "the definition")}.</td></tr>`;
    tvIdsShape = "";
    return;
  }
  // Prefer a first selection the loaded definition can actually decode.
  if (tvSelId === null || !rows.some((r) => r.id === tvSelId)) {
    const decodable = rows.find((r) => tvDefIds.has(r.id));
    tvSelId = (decodable || rows[0]).id;
  }
  const shape = filter + ":" + known + ":" + rows.map((r) => r.id + "/" + r.dlc).join(",");
  if (shape !== tvIdsShape) {
    tvIdsShape = shape;
    tbody.innerHTML = rows.map((r) => {
      const inDef = tvDefIds.has(r.id);
      return `<tr data-id="${r.id}" class="row-pick${known && !inDef ? " tv-undef" : ""}">` +
        `<td>0x${r.id_hex}${known && inDef ? ` <span class="tv-dot" data-tip="In the ${tvDefKind()}: its signals show in Tiles and below."></span>` : ""}</td>` +
        `<td class="num">${r.dlc}</td><td class="num" data-c></td>` +
        `<td data-p>${(r.data.match(/../g) || []).map(() => `<span class="tv-b"></span>`).join(" ")}</td></tr>`;
    }).join("");
  }
  // Update in place, so a changed byte fades instead of blinking off on the next redraw.
  const now = performance.now();
  const byId = new Map(rows.map((r) => [r.id, r]));
  tbody.querySelectorAll("tr[data-id]").forEach((tr) => {
    const r = byId.get(+tr.dataset.id); if (!r) return;
    tr.classList.toggle("sel", r.id === tvSelId);
    tr.querySelector("[data-c]").textContent = r.count.toLocaleString();
    const bytes = r.data.match(/../g) || [];
    tr.querySelectorAll(".tv-b").forEach((sp, i) => {
      if (sp.textContent !== bytes[i]) sp.textContent = bytes[i] || "";
      sp.classList.toggle("chg", tvByteLit(r.id, i, now));
    });
  });
  if (tvScrollToSel) {
    tvScrollToSel = false;
    const tr = tbody.querySelector(`tr[data-id="${tvSelId}"]`);
    if (tr) tr.scrollIntoView({ block: "center" });
  }
  tvLoadDecode();
}

$("tvIdTable").addEventListener("click", (e) => {
  const tr = e.target.closest("tr[data-id]"); if (!tr) return;
  tvSelId = +tr.dataset.id; tvSelSig = 0;
  if (tvLastLive) tvRenderIds(tvLastLive);
});

// ---- Tiles: every signal, as the cloud shows it ----
function tvTileEmpty(text, tone, action) {
  tvTilesShape = "";
  $("tvTileCount").textContent = "";
  $("tvTiles").innerHTML = `<div class="ui-notice ${tone || "muted"} tv-tiles-empty">` +
    `<span class="ui-ico">${UI.icons[tone === "warn" ? "alert" : "info"]}</span>` +
    `<span class="ui-notice-t">${text}</span>` +
    (action ? `<button type="button" class="btn-mini" data-act="${action.act}">${action.label}</button>` : "") + `</div>`;
}

function tvRenderTiles() {
  const r = tvLastSigs;
  if (!r || !r.ok) return;
  $("tvSearch").parentElement.classList.toggle("hidden", !r.definition || !r.messages.length);
  if (!r.definition) {
    return tvTileEmpty("Upload the device's Signature JSON or a DBC to see each transmitted signal as a tile.",
      "muted", { act: "def", label: "Upload JSON / DBC" });
  }
  if (!r.transmitted) return tvTileEmpty("Nothing transmitted yet — tiles appear as frames go out.");
  if (!r.messages.length) {
    return tvTileEmpty(`None of the ${r.transmitted} transmitted IDs is in ${UI.esc(r.definition)}.`, "warn");
  }
  const now = performance.now();
  const tiles = [];
  r.messages.forEach((m) => (m.signals || []).forEach((s) => tiles.push({ key: `${m.id_hex}:${s.name}`, m, s })));
  const byKey = new Map(tiles.map((t) => [t.key, t]));
  tiles.forEach((t) => {                               // when each value last changed
    const v = t.s.choice != null ? t.s.choice : t.s.physical;
    const seen = tvSigSeen.get(t.key);
    if (!seen) tvSigSeen.set(t.key, { v, at: 0 });
    else if (seen.v !== v) { seen.v = v; seen.at = now; }
  });

  const pins = tvPins();
  const show = pins.length ? (tvShow || "pinned") : "all";
  tvSeg($("tvShow"), [{ id: "all", label: `All ${tiles.length}` }]
    .concat(pins.length ? [{ id: "pinned", label: `Pinned ${pins.length}` }] : []), show,
    (id) => { tvShow = id; UI.store.set("tv.show", id); tvTilesShape = ""; tvRenderTiles(); });
  const q = tvSearch.trim().toLowerCase();
  const match = (t) => !q || t.s.name.toLowerCase().includes(q) ||
    (t.m.name || "").toLowerCase().includes(q) || ("0x" + t.m.id_hex).toLowerCase().includes(q);
  const groups = show === "pinned"
    ? [{ m: null, items: pins.map((k) => byKey.get(k)).filter(Boolean).filter(match) }]
    : r.messages.map((m) => ({ m, items: tiles.filter((t) => t.m === m && match(t)) })).filter((g) => g.items.length);
  const shown = groups.reduce((n, g) => n + g.items.length, 0);
  $("tvTileCount").textContent = `${shown} of ${tiles.length} signals · ${r.messages.length} messages` +
    (pins.length ? ` · ${pins.length} pinned` : "");
  if (!shown) {
    return tvTileEmpty(q ? `No signal matches “${UI.esc(tvSearch.trim())}”.`
      : "None of the pinned signals has been transmitted yet.");
  }
  const pinSet = new Set(pins);
  const shape = [show, q, pins.join(","), groups.map((g) => (g.m ? g.m.id : "p") + ":" + g.items.map((t) => t.key).join(",")).join("|")].join("¦");
  if (shape !== tvTilesShape) {
    tvTilesShape = shape;
    // Compact tiles (the user, 25-11-2026: "small moderate tiles this fits in the UI"). Under a
    // message heading the ID is said once, by the heading; a pinned tile has no heading, so it
    // carries its own ID chip.
    const tile = (t) => `<div class="tv-tile${pinSet.has(t.key) ? " is-pinned" : ""}" data-key="${UI.esc(t.key)}" role="button" tabindex="0">` +
      `<div class="tv-tile-head"><span class="tv-tile-name" title="${UI.esc(t.s.name)}">${UI.esc(t.s.name)}</span>` +
      (show === "pinned" ? `<span class="tv-tile-id">0x${t.m.id_hex}</span>` : "") +
      `<button type="button" class="tv-pin" aria-label="${pinSet.has(t.key) ? "Unpin" : "Pin"} ${UI.esc(t.s.name)}"` +
      ` data-tip="${pinSet.has(t.key) ? "Unpin" : "Pin it: pinned signals show first, in the order you pin them — match the device's cloud panel."}">${UI.ico("star")}</button></div>` +
      `<div class="tv-tile-val"></div><div class="tv-tile-foot"></div></div>`;
    // Message groups flow side by side, so a two-signal message does not leave a row empty.
    $("tvTiles").innerHTML = groups.map((g) => g.m
      ? `<div class="tv-group"><div class="tv-group-title"><span>${UI.esc(g.m.name || "")}</span>` +
        `<span class="tv-gid">0x${g.m.id_hex}</span><span class="ui-count" data-grp="${g.m.id}"></span></div>` +
        `<div class="tv-row">${g.items.map(tile).join("")}</div></div>`
      : `<div class="tv-row">${g.items.map(tile).join("")}</div>`).join("");
  }
  // Paint values and states in place: a change lights up and then fades.
  const byMsg = new Map(r.messages.map((m) => [String(m.id), m]));
  $("tvTiles").querySelectorAll("[data-grp]").forEach((el) => {
    const m = byMsg.get(el.dataset.grp); if (!m) return;
    el.textContent = tvIsStale(m) ? `not sent for ${tvFmtAge(m.age_s)}`
      : m.period_ms ? `every ${tvFmtPeriod(m.period_ms)}` : "sent once";
  });
  $("tvTiles").querySelectorAll(".tv-tile").forEach((el) => {
    const t = byKey.get(el.dataset.key);
    if (t) tvPaintTile(el, t, now);
  });
}

function tvPaintTile(el, t, now) {
  const { m, s } = t;
  const stale = tvIsStale(m);
  const text = s.choice != null;
  const val = text ? s.choice : s.physical;
  const unit = text ? "" : (s.unit || "");
  if (el.dataset.v !== val + "|" + unit) {
    el.dataset.v = val + "|" + unit;
    const v = el.querySelector(".tv-tile-val");
    v.innerHTML = `${UI.esc(String(val))}<span class="tv-tile-unit">${UI.esc(unit)}</span>`;
    v.title = text ? String(val) : "";
  }
  const seen = tvSigSeen.get(t.key);
  el.classList.toggle("is-text", text);
  el.classList.toggle("stale", stale);
  el.classList.toggle("is-oor", !!s.out_of_range);
  el.classList.toggle("is-changed", !stale && !!(seen && seen.at && now - seen.at < TV_FLASH_MS));
  const tags = [];
  if (s.patch === "set") tags.push(`<span class="tag warn" data-tip="Patch is holding this value: the log said otherwise. The device gets this one.">Forced</span>`);
  else if (s.patch) tags.push(`<span class="tag info" data-tip="Patch rewrites this (${s.patch}) so it stays continuous across loops.">Rewritten</span>`);
  if (s.out_of_range) tags.push(`<span class="tag warn" data-tip="Outside the definition's own range${s.min != null ? ` (${s.min} to ${s.max})` : ""}.">Out of range</span>`);
  if (stale) tags.push(`<span>Not sent for ${tvFmtAge(m.age_s)}</span>`);
  const foot = tags.join("");
  const footEl = el.querySelector(".tv-tile-foot");
  if (footEl.innerHTML !== foot) footEl.innerHTML = foot;
  el.dataset.tip = `${m.name || ""} · 0x${m.id_hex} · raw ${s.raw}` +
    (s.min != null && s.max != null ? ` · range ${s.min} to ${s.max}${s.unit ? " " + s.unit : ""}` : "") +
    (m.period_ms ? ` · every ${tvFmtPeriod(m.period_ms)}` : "") + ". Click to see its bytes.";
}

// A tile opens its ID in Bytes with that signal's bits highlighted: nothing is lost.
function tvOpenInBytes(key) {
  const t = tvLastSigs && tvLastSigs.messages
    .flatMap((m) => (m.signals || []).map((s) => ({ m, s })))
    .find(({ m, s }) => `${m.id_hex}:${s.name}` === key);
  if (!t) return;
  tvMode = "bytes"; UI.store.set("tv.mode", "bytes");
  tvSelId = t.m.id; tvSelSigName = t.s.name; tvScrollToSel = true;
  tvIdsShape = "";
  tvApplyMode();
  pollTxVerify();
}
function tvTogglePin(key) {
  const pins = tvPins();
  const i = pins.indexOf(key);
  if (i >= 0) pins.splice(i, 1); else pins.push(key);
  // Pinning while looking at All stays in All — jumping to a one-tile Pinned view would lose the place.
  if (tvShow === null) tvShow = "all";
  tvSetPins(pins);
  tvTilesShape = "";
  tvRenderTiles();
}
$("tvTiles").addEventListener("click", (e) => {
  const act = e.target.closest("[data-act]");
  if (act && act.dataset.act === "def") return void $("tvDefFile").click();
  const pin = e.target.closest(".tv-pin");
  const tile = e.target.closest(".tv-tile");
  if (!tile) return;
  if (pin) return void tvTogglePin(tile.dataset.key);
  if (window.getSelection && String(window.getSelection()).length) return;   // a text selection, not a click
  tvOpenInBytes(tile.dataset.key);
});
$("tvTiles").addEventListener("keydown", (e) => {
  const tile = e.target.closest(".tv-tile");
  if (!tile || e.target.closest(".tv-pin") || (e.key !== "Enter" && e.key !== " ")) return;
  e.preventDefault();
  tvOpenInBytes(tile.dataset.key);
});
$("tvSearch").addEventListener("input", () => { tvSearch = $("tvSearch").value; tvTilesShape = ""; tvRenderTiles(); });
tvApplyMode();

async function tvLoadDecode() {
  if (tvSelId === null) return;
  const hex = `0x${tvSelId.toString(16).toUpperCase()}`;
  $("tvSelId").textContent = hex;
  const r = await api(`/api/tx/live/decode?frame_id=${tvSelId}`);
  // Every failure here has a different fix, so each says which one it is rather
  // than leaving an empty panel: no definition loaded, or this ID isn't in it.
  if (!r || !r.ok || r.error) {
    const raw = ((tvLastLive && tvLastLive.ids) || []).find((x) => x.id === tvSelId);
    // No definition: the raw bytes are the whole answer, and the line above says
    // why there is nothing more. Not in it: say so, and how many it does cover.
    $("tvDecode").innerHTML = tvRawOnly(raw) + (tvDefIds.size
      ? warnLine(`${hex} is not in ${UI.esc($("tvDefName").textContent)} — it describes ` +
                 `${tvDefIds.size} messages. Rows with an amber mark are in it.`)
      : "");
    return;
  }
  tvDecoded = r;
  if (tvSelSigName) {                                  // opened from a tile: select that signal
    const i = (r.signals || []).findIndex((s) => s.name === tvSelSigName);
    if (i >= 0) tvSelSig = i;
    tvSelSigName = null;
  }
  tvRenderDecode(r);
}

// The raw bytes are always worth showing — they are the thing under test, and
// they do not depend on having a definition at all.
function tvRawOnly(row) {
  if (!row) return "";
  const bytes = row.data.match(/../g) || [];
  const now = performance.now();
  return `<div class="sub-h">Raw payload <span class="ui-count">DLC ${row.dlc}</span></div>` +
    `<table class="byteview"><thead><tr><th>byte</th>` +
    bytes.map((_, i) => `<th>${i}</th>`).join("") + `</tr></thead><tbody><tr><th>hex</th>` +
    bytes.map((b, i) => `<td${tvByteLit(row.id, i, now) ? ' class="chg"' : ""}>${b}</td>`).join("") + `</tr></tbody></table>`;
}

// Purpose-built lightweight renderer — the Frame Decoder's grid is bound to its
// own selection state, and duplicating 30 lines beats refactoring it from under
// a working view.
function tvRenderDecode(f) {
  const COLS = [7, 6, 5, 4, 3, 2, 1, 0];
  const bytes = f.bytes || [];
  const sigs = f.signals || [];
  if (tvSelSig >= sigs.length) tvSelSig = 0;

  const now = performance.now();
  const byteRow = `<table class="byteview"><thead><tr><th>byte</th>` +
    bytes.map((_, i) => `<th>${i}</th>`).join("") + `</tr></thead><tbody><tr><th>hex</th>` +
    bytes.map((b, i) => `<td${tvByteLit(f.id, i, now) ? ' class="chg"' : ""}>${b.toString(16).toUpperCase().padStart(2, "0")}</td>`).join("") +
    `</tr></tbody></table>`;

  const owner = {}, msb = {}, lsb = {};
  sigs.forEach((s, i) => {
    (s.cells || []).forEach((c) => { owner[c[0] + ":" + c[1]] = i; });
    if (s.msb_cell) msb[s.msb_cell[0] + ":" + s.msb_cell[1]] = i;
    if (s.lsb_cell) lsb[s.lsb_cell[0] + ":" + s.lsb_cell[1]] = i;
  });
  let grid = `<table class="bitgrid"><thead><tr><th></th>` +
    COLS.map((c) => `<th>${c}</th>`).join("") + `</tr></thead><tbody>`;
  for (let b = 0; b < bytes.length; b++) {
    grid += `<tr><th>${b}</th>` + COLS.map((c) => {
      const key = b + ":" + c, bit = (bytes[b] >> c) & 1, mine = owner[key] === tvSelSig;
      const cls = !mine ? "" : msb[key] === tvSelSig ? "bit-msb"
                : lsb[key] === tvSelSig ? "bit-lsb" : "bit-hi";
      return `<td class="${cls}">${bit}</td>`;
    }).join("") + `</tr>`;
  }
  grid += `</tbody></table>`;

  const table = `<table class="data-table" id="tvSigTable"><thead><tr>
      <th>Signal</th><th>Raw</th><th>Value</th><th>Unit</th><th>Bits</th><th>Order</th></tr></thead><tbody>` +
    sigs.map((s, i) => `<tr data-sig="${i}" class="row-pick ${i === tvSelSig ? "sel" : ""}">
      <td>${s.name}</td><td class="mono">${s.raw}</td>
      <td class="mono${s.out_of_range ? " tc-oor" : ""}">${s.physical}</td>
      <td>${s.unit || ""}</td><td class="mono">${s.start_bit}+${s.length}</td>
      <td>${s.byte_order === "big_endian" ? "Motorola" : "Intel"}</td></tr>`).join("") +
    `</tbody></table>`;

  $("tvDecode").innerHTML =
    `<div class="sub-h" data-tip="What the cloud should display for these bytes. Click a signal to highlight its bits.">` +
    `${UI.esc(f.name || "")} <span class="ui-count">DLC ${bytes.length}</span></div>` +
    byteRow +
    `<div class="tv-split">${table}<div>${grid}</div></div>`;
  $("tvSigTable").addEventListener("click", (e) => {
    const tr = e.target.closest("tr[data-sig]"); if (!tr) return;
    tvSelSig = +tr.dataset.sig; tvRenderDecode(tvDecoded);
  });
}

$("btnTvRecord").addEventListener("click", async () => {
  const r = await POST(tvRecording ? "/api/tx/record/stop" : "/api/tx/record/start");
  setStatus(r.recording ? "Recording every transmitted frame" : "TX recording stopped");
});
$("btnTvReset").addEventListener("click", async () => {
  await POST("/api/tx/record/reset");
  tvSelId = null; tvDecoded = null;
  tvBytesSeen.clear(); tvSigSeen.clear(); tvTilesShape = ""; tvIdsShape = "";
  $("tvDecode").innerHTML = ""; $("tvReport").innerHTML = "";
  $("tvVerdict").innerHTML = `<div class="muted-line">No cloud log uploaded.</div>`;
  txSum("sumVerify", "No comparison yet");
});

$("btnTvDef").addEventListener("click", () => $("tvDefFile").click());
$("tvDefFile").addEventListener("change", async (e) => {
  const f = e.target.files[0]; if (!f) return;
  const r = await apiUpload("/api/tx/live/definition", f);
  if (!r.ok) return setStatus(r.error);
  $("tvDefName").textContent = r.definition;
  e.target.value = "";                               // the same file can be uploaded again
  pollTxVerify();                                    // the definition decides the default view and the pins
});

$("btnTvCloud").addEventListener("click", () => $("tvCloudFile").click());
$("tvCloudFile").addEventListener("change", async (e) => {
  const f = e.target.files[0]; if (!f) return;
  $("tvVerdict").innerHTML = `<div class="muted-line">Comparing…</div>`;
  tvRenderReport(await apiUpload("/api/tx/verify", f));
});

function tvRenderReport(r) {
  txOpenStep("stepVerify");
  if (!r.ok && r.error) {
    $("tvVerdict").innerHTML = badLine(UI.esc(r.error));
    $("tvReport").innerHTML = "";
    txSum("sumVerify", "Could not read that cloud log");
    $("sumVerify").classList.add("has-warn");
    return;
  }
  const pass = r.unknown_payloads === 0;
  txSum("sumVerify", `${pass ? "Byte-identical" : "Mismatch"} · ` +
    `${r.matched_frames.toLocaleString()}/${r.cloud_frames.toLocaleString()} cloud frames matched` +
    (pass ? "" : ` · ${r.unknown_payloads} payload(s) we never sent`));
  $("sumVerify").classList.toggle("has-warn", !pass);
  $("tvVerdict").innerHTML =
    `<div class="tv-verdict ${pass ? "pass" : "fail"}">${pass ? UI.ico("check") : ICONS.alert}${pass ? "Byte-identical" : "Mismatch"}</div>` +
    `<div class="muted-line">${r.tx_frames.toLocaleString()} transmitted · ` +
    `${r.cloud_frames.toLocaleString()} at the cloud (${r.cloud_dialect}) · ` +
    `${r.matched_frames.toLocaleString()} matched · ${r.unknown_payloads} payload(s) we never sent</div>` +
    (r.warnings || []).map((w) => warnLine(UI.esc(w))).join("") +
    // What we deliberately did not transmit — stated, so "missing at the cloud"
    // is never confused with our own filtering.
    ((r.tx_filters && r.tx_filters.networks_not_sent || []).length
      ? `<div class="muted-line">Not transmitted by us: ` +
        r.tx_filters.networks_not_sent.map((n) => `${n.name} (${n.frames.toLocaleString()} frames)`).join(", ") +
        `</div>` : "");

  // One word and one colour per verdict. Only "corrupt" is a fault; a TCU that
  // forwards a subset ("sampled") is normal, and another node on the bench bus
  // ("not sent by us") is worth a look, not an alarm.
  const V = { complete: ["Complete", "ok"], sampled: ["Sampled", ""], "not forwarded": ["Not forwarded", ""],
              corrupt: ["Corrupt", "bad"], "unexpected id": ["Not sent by us", "warn"] };
  $("tvReport").innerHTML = `<div class="table-wrap report-wrap">
    <table class="data-table mono"><thead><tr>
      <th>ID</th><th class="num">TX</th><th class="num">Cloud</th><th class="num">Matched</th><th class="num">Delivery</th><th>Verdict</th><th>Detail</th>
    </tr></thead><tbody>` + r.per_id.map((p) => `<tr>
      <td>0x${p.id_hex}</td><td class="num">${p.tx.toLocaleString()}</td><td class="num">${p.cloud.toLocaleString()}</td>
      <td class="num">${p.matched.toLocaleString()}</td><td class="num">${p.delivery_pct == null ? "—" : p.delivery_pct + "%"}</td>
      <td><span class="tag ${(V[p.verdict] || [])[1] || ""}">${(V[p.verdict] || [p.verdict])[0]}</span></td>
      <td>${p.unknown_samples ? "cloud sent " + p.unknown_samples.join(", ") : ""}</td>
    </tr>`).join("") + `</tbody></table></div>`;
}

// -------------------------------------------------------- Reverse Engineering
let lastRe = null;
function entropyColor(h) {  // 0 (blue, constant) → 8 (red, noisy)
  const t = Math.min(1, h / 8);
  const r = Math.round(40 + 200 * t), g = Math.round(120 * (1 - Math.abs(t - 0.5) * 2)), b = Math.round(220 * (1 - t));
  return `rgb(${r},${g + 60},${b})`;
}
const KIND_COLOR = {
  counter: "var(--ok-ink)", crc: "var(--danger-ink)", physical: "var(--info-ink)",
  "multi-state": "var(--warn-ink)", constant: "var(--muted)", event: "var(--series-5)",
};
function candChip(c) {
  const col = KIND_COLOR[c.kind] || "var(--dim)";
  const conf = c.confidence != null ? ` ${Math.round(c.confidence * 100)}%` : "";
  const order = c.byte_order === "little_endian" ? " LE" : "";
  const step = c.step != null ? ` +${c.step}` : "";
  return `<span class="cand-chip" title="${c.kind}${order} · bit ${c.start_bit} len ${c.length}${step}"
    style="border-color:${col};color:${col}">${c.kind}${order} @${c.start_bit}/${c.length}${step}${conf}</span>`;
}

$("btnAnalyze").addEventListener("click", async () => {
  const path = $("reSelect").value; if (!path) return;
  const engine = $("reEngine") ? $("reEngine").value || "read" : "read";
  setStatus(`Analyzing ${path} (${engine}) …`);
  const r = await POST("/api/re/analyze", { path, engine });
  if (!r.ok) return void setStatus("RE error: " + r.error);
  lastRe = r.result; setStatus("Analysis complete");
  $("reSummary").textContent = `${r.result.id_count} IDs · ${r.result.total_frames} frames · ${r.result.engine || engine}`;
  $("reTable").querySelector("tbody").innerHTML = r.result.ids.map((id, i) => {
    const ent = id.bytes.map((b) =>
      `<div class="ebyte" title="byte ${b.index}: ${b.kind}, H=${b.entropy}" style="background:${entropyColor(b.entropy)}">${b.entropy.toFixed(1)}</div>`).join("");
    const cands = id.candidates.map(candChip).join(" ") || "—";
    const mux = id.multiplexor ? ` <span class="cand-chip" style="border-color:var(--series-5);color:var(--series-5)" title="Multiplexor">mux@byte${id.multiplexor.selector_byte}</span>` : "";
    return `<tr><td class="mono">0x${id.id_hex}</td><td>${id.frames}</td><td>${id.period_ms} ms</td>
      <td>${id.length}</td><td><div class="entropy-row">${ent}</div></td><td>${cands}${mux}</td>
      <td><button class="btn-mini" onclick="seedDbc(${i})">${ICONS.arrowRight} DBC</button></td></tr>`;
  }).join("");
});
window.seedDbc = async (i) => {
  if (!lastRe) return;
  await POST("/api/dbc/seed", lastRe.ids[i]);
  setStatus(`Sent 0x${lastRe.ids[i].id_hex} to DBC Builder`);
};

// ----- shared "changed IDs" renderer for sniffer + compare -----------------
const changedStore = {};   // ns -> {id_hex -> id_result} for promote
function renderChanged(wrapId, ns, result) {
  changedStore[ns] = {};
  const rows = (result.changed || []).map((c) => {
    changedStore[ns][c.id_hex] = c;
    const bits = c.candidates.map((cd) => `<span class="cand-chip" style="border-color:var(--series-5);color:var(--series-5)">@${cd.start_bit}/${cd.length}</span>`).join(" ");
    const bytes = c.changed_bytes.map((b) => `byte${b.index}: ${b.baseline.join("/")}→${b.after.join("/")}`).join("; ");
    return `<tr><td class="mono">0x${c.id_hex}</td><td>${bits}</td><td class="muted-line">${bytes}</td>
      <td><button class="btn-mini" onclick="promoteChanged('${ns}','${c.id_hex}')">${ICONS.arrowRight} DBC</button></td></tr>`;
  }).join("");
  const extra = [];
  if (result.new_ids && result.new_ids.length) extra.push(`new IDs: ${result.new_ids.map((x) => "0x" + x).join(", ")}`);
  if (result.removed_ids && result.removed_ids.length) extra.push(`gone: ${result.removed_ids.map((x) => "0x" + x).join(", ")}`);
  $(wrapId).innerHTML = `<table class="data-table"><thead><tr><th>ID</th><th>Changed bits</th><th>Bytes (before→after)</th><th></th></tr></thead>
    <tbody>${rows || `<tr><td colspan="4" class="muted-line" style="padding:14px">No bit changes detected.</td></tr>`}</tbody></table>
    ${extra.length ? `<div class="muted-line" style="padding:8px 14px">${extra.join(" · ")}</div>` : ""}`;
}
window.promoteChanged = async (ns, idHex) => {
  const id_result = changedStore[ns] && changedStore[ns][idHex];
  if (!id_result) return;
  await POST("/api/re/promote", { id_result });
  setStatus(`Promoted 0x${idHex} changes to DBC Builder`);
};

// ----- state-change sniffer -------------------------------------------------
function setSniffStatus(s) {
  $("sniffStatus").textContent = `${s.phase} · baseline ${s.baseline_frames}f/${s.baseline_ids}id · after ${s.after_frames}f/${s.after_ids}id`;
}
$("btnSniffArm").addEventListener("click", async () => {
  const r = await POST("/api/re/sniff/arm");
  if (!r.ok) return void setStatus("Sniffer: " + r.error);
  setSniffStatus(r); setStatus("Sniffer armed — perform the action now, then click step 2.");
});
$("btnSniffMark").addEventListener("click", async () => { setSniffStatus(await POST("/api/re/sniff/mark")); });
$("btnSniffStop").addEventListener("click", async () => { setSniffStatus(await POST("/api/re/sniff/stop")); });
$("btnSniffResult").addEventListener("click", async () => {
  const r = await api("/api/re/sniff/result");
  if (r && r.result) { renderChanged("sniffResultWrap", "sniff", r.result); setSniffStatus(r.result.status); }
});

// ----- compare two logs -----------------------------------------------------
$("btnCompare").addEventListener("click", async () => {
  const a = $("cmpA").value, b = $("cmpB").value;
  if (!a || !b) return void setStatus("Pick two logs to compare");
  setStatus("Comparing …");
  const r = await POST("/api/re/compare", { path_a: a, path_b: b });
  if (!r.ok) return void setStatus("Compare error: " + r.error);
  renderChanged("cmpResultWrap", "cmp", r.result);
  setStatus(`Compared · ${r.result.changed_id_count} IDs changed`);
});

// ----- LibreCAN correlation: auto-label vs OBD ground truth -----
const corrStore = {};
$("btnCorrelate").addEventListener("click", async () => {
  const path = $("reSelect").value; if (!path) return;
  setStatus("Correlating signals vs OBD ground truth …");
  const r = await POST("/api/re/correlate", { path });
  if (!r.ok) return void setStatus("Correlate error: " + r.error);
  const res = r.result;
  res.labeled_ids.forEach((d) => (corrStore[d.id_hex] = d));
  const rows = res.labeled_ids.map((d) => d.labeled.map((L) =>
    `<tr><td class="mono">0x${d.id_hex}</td><td>${L.label}</td><td>@${L.start_bit}/${L.length} ${L.byte_order === "little_endian" ? "LE" : "BE"}</td>
      <td>r=${L.r}</td><td>×${L.scale} ${L.offset >= 0 ? "+" : ""}${L.offset}</td>
      <td><button class="btn-mini" onclick="promoteCorr('${d.id_hex}')">${ICONS.arrowRight} DBC</button></td></tr>`).join("")).join("");
  $("corrResultWrap").innerHTML = `<table class="data-table"><thead><tr><th>ID</th><th>Label (OBD)</th><th>Bits</th><th>Fit</th><th>Scale/offset</th><th></th></tr></thead>
    <tbody>${rows || `<tr><td colspan="6" class="muted-line" style="padding:14px">No signals correlated above threshold. Capture must include OBD-II PID responses.</td></tr>`}</tbody></table>`;
  setStatus(`Correlated · ground truth: ${res.ground_truth.join(", ") || "none found"}`);
});
window.promoteCorr = async (idHex) => {
  const d = corrStore[idHex]; if (!d) return;
  await POST("/api/re/promote", { id_result: { ...d, candidates: d.labeled } });
  setStatus(`Promoted labelled signals for 0x${idHex} → DBC (with recovered scale/offset)`);
};

// ----------------------------------------------------------- OEM CAN Database
// Profiles is a two-level table: one row per vehicle, plus an expandable detail
// row listing the messages/signals that profile decodes. Detail is fetched on
// demand and cached — a pack DBC is far too big to ship inside the list call.
let oemProfiles = [];
const oemOpen = new Set();        // pids currently expanded
const oemDetail = {};             // pid -> /signals payload

async function renderOem() {
  const { profiles } = await api("/api/oem/profiles");
  oemProfiles = profiles || [];
  const live = new Set(oemProfiles.map((p) => p.id));
  for (const pid of [...oemOpen]) if (!live.has(pid)) oemOpen.delete(pid);
  oemDrawProfiles();
}

// Make/Model/Year now have their own columns, so the profile name only still
// carries the fuel and — for a vehicle tapped at two points — the bus segment.
function oemVariant(p) {
  let s = ` ${p.name} `;
  for (const part of [p.model, p.year]) if (part) s = s.split(part).join(" ");
  return s.replace(/\s+/g, " ").trim();
}

function oemDrawProfiles() {
  const tb = $("oemTable").querySelector("tbody");
  $("oemCount").textContent = oemProfiles.length ? String(oemProfiles.length) : "";
  if (!oemProfiles.length) {
    tb.innerHTML = `<tr class="empty-row"><td colspan="7">No profiles yet.</td></tr>`;
    return;
  }
  tb.innerHTML = oemProfiles.map((p) => {
    const open = oemOpen.has(p.id);
    // With no model recorded the cell falls back to the profile name, so the
    // variant sub-line would just repeat it.
    const variant = p.model ? oemVariant(p) : "";
    return `<tr>
      <td>${escAttr(p.oem)}</td>
      <td><button type="button" class="oem-model" onclick="oemToggle(${p.id})" aria-expanded="${open}">
          ${ICONS[open ? "chevronUp" : "chevronDown"]}<span>${escAttr(p.model || p.name)}</span></button>
        ${variant ? `<span class="oem-variant">${escAttr(variant)}</span>` : ""}</td>
      <td class="num">${p.id_count}</td>
      <td class="num">${p.msg_count ? `${p.msg_count} <span class="ui-count">· ${p.signal_count} signals</span>`
                        : `<span class="dim-note">None</span>`}</td>
      <td>${p.year || `<span class="dim-note">—</span>`}</td>
      <td><span class="tag ${p.status === "shipped" ? "ok" : ""}">${cap(p.status)}</span></td>
      <td class="row-actions">${p.msg_count
        ? `<button type="button" class="btn-mini" onclick="oemApply(${p.id})" data-tip="Load this profile's DBC into the Signal viewer and decode the live bus with it.">Apply</button>`
        : ""}
        <button type="button" class="btn-mini danger" onclick="oemDelete(${p.id})">Delete</button></td>
    </tr>${open ? oemDetailRow(p) : ""}`;
  }).join("");
}

function oemDetailRow(p) {
  const d = oemDetail[p.id];
  let body;
  if (!d) body = `<div class="muted-line oem-note">Loading signals…</div>`;
  else if (d.error) body = `<div class="oem-note">${badLine(`Could not read this profile's DBC — ${escAttr(d.error)}`)}</div>`;
  else if (!d.messages.length) body = `<div class="muted-line oem-note">Fingerprint only — identifies the vehicle, decodes nothing yet.</div>`;
  else body = d.messages.map((m) => `<div class="cv-msg">
      <div class="cv-msg-head">
        <span class="mono">0x${m.id_hex}</span><strong>${escAttr(m.name)}</strong>
        <span class="ui-count">${m.length} byte${m.length === 1 ? "" : "s"}${m.is_extended ? " · 29-bit" : ""}</span>
        <span class="ui-count">${m.signals.length} signal${m.signals.length === 1 ? "" : "s"}</span>
      </div>
      ${m.signals.length ? `<div class="table-wrap"><table class="data-table cv-sigtable"><thead><tr>
        <th>Signal</th><th class="num">Start</th><th class="num">Length</th><th>Layout</th><th class="num">Scale</th><th class="num">Offset</th><th>Range</th><th>Unit</th>
      </tr></thead><tbody>${m.signals.map((s) => `<tr>
        <td>${escAttr(s.name)}</td><td class="mono num">${s.start_bit}</td><td class="mono num">${s.length}</td>
        <td class="cell-dim">${String(s.byte_order || "").startsWith("big") ? "Motorola" : "Intel"}${s.is_signed ? " · signed" : ""}</td>
        <td class="mono num">${s.scale}</td><td class="mono num">${s.offset}</td>
        <td class="cell-dim">${s.minimum == null && s.maximum == null ? "—" : `${s.minimum ?? "—"} … ${s.maximum ?? "—"}`}</td>
        <td class="cell-dim">${escAttr(s.unit || "")}</td></tr>`).join("")}</tbody></table></div>` : ""}
    </div>`).join("");
  return `<tr class="oem-detail"><td colspan="7">${body}</td></tr>`;
}

window.oemToggle = async (id) => {
  if (oemOpen.has(id)) { oemOpen.delete(id); return void oemDrawProfiles(); }
  oemOpen.add(id);
  oemDrawProfiles();                     // open immediately, then fill in
  if (oemDetail[id]) return;
  const d = await api(`/api/oem/profile/${id}/signals`);
  oemDetail[id] = d.ok ? d : { error: d.error || "request failed", messages: [] };
  if (oemOpen.has(id)) oemDrawProfiles();
};
window.oemApply = async (id) => {
  const r = await POST("/api/oem/apply?pid=" + id);
  setStatus(r.ok ? `Applied profile → Signal viewer (${r.signals ? r.signals.length : 0} signals)` : "Apply: " + r.error);
};
window.oemDelete = async (id) => {
  const p = oemProfiles.find((x) => x.id === id) || {};
  if (!(await UI.confirm({ title: "Delete profile?",
    text: `“${`${p.oem || ""} ${p.name || id}`.trim()}” will be removed. Vehicle packs that ship with uCANdo come back from oem_packs/ at the next start.`,
    action: "Delete", tone: "danger" }))) return;
  await POST("/api/oem/profile/delete?pid=" + id);
  delete oemDetail[id]; oemOpen.delete(id);
  renderOem();
};
$("btnOemRefresh").addEventListener("click", renderOem);
$("btnOemPrune").addEventListener("click", async () => {
  const r = await POST("/api/oem/prune");
  setStatus(r.removed ? `Removed ${r.removed} empty profile${r.removed > 1 ? "s" : ""}` : "Nothing to clean — every profile has signals");
  for (const k of Object.keys(oemDetail)) delete oemDetail[k];
  renderOem();
});
$("btnOemIdentify").addEventListener("click", async () => {
  const r = await api("/api/oem/identify");
  if (!r.ok) return void ($("oemIdentStatus").textContent = r.error);
  $("oemIdentStatus").textContent = `${r.observed_ids} IDs observed`;
  $("oemIdentWrap").innerHTML = `<table class="data-table"><thead><tr><th>Match</th><th>OEM</th><th class="num">Score</th><th class="num">IDs matched</th><th></th></tr></thead>
    <tbody>${(r.matches || []).map((m) => `<tr><td>${escAttr(m.name)}</td><td>${escAttr(m.oem)}</td>
      <td class="num">${(m.score * 100).toFixed(0)}%</td><td class="num">${m.matched}/${m.profile_ids}</td>
      <td class="row-actions"><button type="button" class="btn-mini" onclick="oemApply(${m.profile_id})">Apply</button></td></tr>`).join("")
      || `<tr class="empty-row"><td colspan="5">No confident match.</td></tr>`}</tbody></table>`;
});
$("btnOemAutoApply").addEventListener("click", async () => {
  const r = await POST("/api/oem/auto-apply");
  if (r.ok && r.applied) setStatus(`Applied “${r.applied.name}” (${(r.match.score * 100).toFixed(0)}% match) → Signal viewer`);
  else setStatus(r.reason ? "No confident decodable match" : ("Auto-apply: " + (r.error || "?")));
  $("btnOemIdentify").click();
});

// --------------------------------------------------------------- Automation
function renderAutomation() { renderRules(); renderJobs(); pollRestbus(); }
async function renderRules() {
  const t = await api("/api/rules");
  const rules = t.rules || [];
  $("ruleCount").textContent = rules.length ? String(rules.length) : "";
  $("rulesWrap").innerHTML = `<table class="data-table"><thead><tr><th>Name</th><th>When</th><th>Action</th><th class="num">Fired</th><th></th></tr></thead>
    <tbody>${rules.map((r) => `<tr><td>${UI.esc(r.name)}</td><td class="mono">${UI.esc(r.when)}</td>
      <td>${cap(r.action.type)}</td><td class="num">${r.fired}</td>
      <td class="row-actions"><button type="button" class="btn-mini danger" data-name="${UI.esc(r.name || r.when)}" onclick="delRule(${r.uid}, this.dataset.name)">Remove</button></td></tr>`).join("")
      || `<tr class="empty-row"><td colspan="5">No rules yet.</td></tr>`}</tbody></table>`;
  $("ruleEventsWrap").innerHTML = `<table class="data-table mono"><tbody>${(t.events || []).slice(0, 30).map((e) =>
    `<tr><td>${e.ts}</td><td>${UI.esc(e.rule)}</td><td>${e.action}</td><td>${UI.esc(e.detail)}</td></tr>`).join("")
    || `<tr class="empty-row"><td>No events yet.</td></tr>`}</tbody></table>`;
}
$("btnRuleAdd").addEventListener("click", async () => {
  const when = $("ruleWhen").value.trim(); if (!when) return;
  const type = $("ruleActType").value, arg = $("ruleActArg").value.trim();
  let action = { type: "log", message: arg };
  if (type === "transmit") {
    const m = arg.match(/id\s*=\s*(\w+)\s+data\s*=\s*(.+)/i);
    action = m ? { type: "transmit", id: parseInt(m[1], 16), data: m[2] } : { type: "transmit", id: 0, data: "" };
  }
  const r = await POST("/api/rules/add", { name: $("ruleName").value.trim(), when, action });
  if (r.ok) { $("ruleName").value = $("ruleWhen").value = $("ruleActArg").value = ""; renderRules(); }
  else setStatus("Rule: " + r.error);
});
// Rules and jobs are saved: removing one asks first (the name is passed as
// data, never spliced into the handler's script).
window.delRule = async (uid, name) => {
  if (!(await UI.confirm({ title: "Remove rule?", text: `The rule “${name || uid}” will be deleted.`,
    action: "Remove", tone: "danger" }))) return;
  await POST("/api/rules/remove?uid=" + uid); renderRules();
};

async function renderJobs() {
  const { jobs } = await api("/api/jobs");
  $("jobCount").textContent = (jobs || []).length ? String(jobs.length) : "";
  $("jobsWrap").innerHTML = `<table class="data-table"><thead><tr><th>Name</th><th>Kind</th><th>Schedule</th><th>Last run</th><th></th></tr></thead>
    <tbody>${(jobs || []).map((j) => `<tr><td>${UI.esc(j.name)}</td><td>${cap(j.kind)}</td><td>${/^every:/.test(j.schedule || "") ? `Every ${j.schedule.slice(6)} s` : (j.schedule || "Manual")}</td>
      <td>${j.last_run ? new Date(j.last_run * 1000).toLocaleTimeString() : "—"}</td>
      <td class="row-actions"><button type="button" class="btn-mini" onclick="runJob(${j.id})">${ICONS.play}<span>Run</span></button>
        <button type="button" class="btn-mini danger" data-name="${UI.esc(j.name)}" onclick="delJob(${j.id}, this.dataset.name)">Remove</button></td></tr>`).join("")
      || `<tr class="empty-row"><td colspan="5">No jobs yet.</td></tr>`}</tbody></table>`;
}
$("btnJobAdd").addEventListener("click", async () => {
  const name = $("jobName").value.trim() || "job"; const every = $("jobEvery").value.trim();
  await POST("/api/jobs/add", { name, kind: $("jobKind").value, schedule: every ? "every:" + every : "", spec: { duration_s: 5 } });
  $("jobName").value = $("jobEvery").value = ""; renderJobs();
});
window.runJob = async (id) => { const r = await POST("/api/jobs/run?jid=" + id); setStatus("Job: " + JSON.stringify(r.result || r)); renderJobs(); };
window.delJob = async (id, name) => {
  if (!(await UI.confirm({ title: "Remove job?", text: `The job “${name || id}” will be deleted.`,
    action: "Remove", tone: "danger" }))) return;
  await POST("/api/jobs/remove?jid=" + id); renderJobs();
};

async function pollRestbus() {
  const s = await api("/api/restbus/status");
  $("restbusStatus").textContent = `${s.running ? "Running" : "Stopped"} · ${s.messages} messages · ${s.sent.toLocaleString()} sent`;
}
$("btnRestbusBuilder").addEventListener("click", async () => { const r = await POST("/api/restbus/load-builder"); setStatus(r.ok ? `Restbus: ${r.messages} messages loaded` : "Restbus: " + r.error); pollRestbus(); });
$("btnRestbusStart").addEventListener("click", async () => { const r = await POST("/api/restbus/start"); if (!r.ok) setStatus("Restbus: " + r.error); pollRestbus(); });
$("btnRestbusStop").addEventListener("click", async () => { await POST("/api/restbus/stop"); pollRestbus(); });

$("btnScriptRun").addEventListener("click", async () => {
  const r = await POST("/api/script/run", { code: $("scriptCode").value });
  $("scriptOut").textContent = (r.error ? "ERROR: " + r.error + "\n" : "") + (r.logs || []).join("\n");
});

// ------------------------------------------------------ Auto-RE (A/B/C tiers)
async function initAutoRE() {
  refreshLogs();
  const p = await api("/api/autore/protocols");
  if ($("autoreProtocols")) $("autoreProtocols").textContent = (p.protocols || []).join(" · ");
  renderAutoRE(await api("/api/autore/report"));
}
$("btnAutoReRescan").addEventListener("click", refreshLogs);
$("btnAutoReAnalyze").addEventListener("click", async () => {
  const path = $("autoreSelect").value; if (!path) return;
  const known = {};
  if ($("autoreOdo").value.trim()) known["Odometer"] = $("autoreOdo").value.trim();
  if ($("autoreFuel").value.trim()) known["Fuel Level"] = $("autoreFuel").value.trim();
  $("autoreStatus").textContent = "Analyzing…";
  const r = await POST("/api/autore/analyze-log", { path, known_values: known });
  $("autoreStatus").textContent = r.ok ? "Done" : ("Error: " + r.error);
  if (r.ok) renderAutoRE(r.report);
});
function autoreLoc(s) {
  const sc = s.scale && s.scale !== 1 ? " ×" + s.scale : "";
  return `0x${s.id_hex} · bit ${s.start_bit}/${s.length} ${s.byte_order === "little_endian" ? "LE" : "BE"}${sc}`;
}
const _ref = (s) => encodeURIComponent(JSON.stringify(
  { frame_id: s.frame_id, start_bit: s.start_bit, length: s.length, byte_order: s.byte_order, ext: s.ext, label: s.label }));
function renderAutoRE(rep) {
  if (!rep) return;
  const c = rep.counts || { A: 0, B: 0, C: 0 };
  $("autoreACount").textContent = c.A + " confirmed";
  $("autoreBCount").textContent = c.B + " to review";
  $("autoreCCount").textContent = c.C + " fields";
  $("autoreA").innerHTML = `<table class="data-table"><thead><tr><th>Signal</th><th>Location</th><th>Conf</th><th>Source</th></tr></thead><tbody>` +
    (rep.A || []).map((s) => `<tr><td><b>${s.label || "—"}</b></td><td class="mono">${autoreLoc(s)}</td><td>${(s.confidence * 100).toFixed(0)}%</td><td class="muted-line">${s.sources.join(",")}</td></tr>`).join("") +
    `</tbody></table>`;
  $("autoreB").innerHTML = `<table class="data-table"><thead><tr><th>Guess (editable)</th><th>Location</th><th>Conf</th><th></th></tr></thead><tbody>` +
    (rep.B || []).map((s, i) => `<tr><td><input id="blbl${i}" value="${s.label || ""}" style="width:140px"/></td>
      <td class="mono">${autoreLoc(s)}</td><td>${(s.confidence * 100).toFixed(0)}%</td>
      <td><button class="btn-mini btn-ico" onclick="autoreConfirm('${_ref(s)}',${i})">${ICONS.check}<span>Confirm</span></button>
          <button class="btn-mini btn-ico" onclick="autoreReject('${_ref(s)}')">${ICONS.close}<span>Reject</span></button></td></tr>`).join("") +
    `</tbody></table>`;
  $("autoreC").innerHTML = `<table class="data-table"><thead><tr><th>Location</th><th>Behaviour</th></tr></thead><tbody>` +
    (rep.C || []).slice(0, 40).map((s) => `<tr><td class="mono">${autoreLoc(s)}</td><td class="muted-line">${s.kind || s.sources.join(",")}</td></tr>`).join("") +
    `</tbody></table>` + ((rep.C || []).length > 40 ? `<div class="muted-line" style="padding:6px">+${rep.C.length - 40} more</div>` : "");
}
window.autoreConfirm = async (ref, i) => {
  const s = JSON.parse(decodeURIComponent(ref));
  const edited = $("blbl" + i); if (edited && edited.value.trim()) s.label = edited.value.trim();
  const r = await POST("/api/autore/confirm", s);
  if (r.ok) { renderAutoRE(r.report); setStatus(`Confirmed ${s.label || "signal"} → tier A`); }
};
window.autoreReject = async (ref) => {
  const r = await POST("/api/autore/reject", JSON.parse(decodeURIComponent(ref)));
  if (r.ok) renderAutoRE(r.report);
};
$("btnAutoReSave").addEventListener("click", async () => {
  const oem = $("autoreOem").value.trim(), name = $("autoreName").value.trim();
  if (!oem || !name) return void setStatus("Enter OEM + profile name");
  const r = await POST("/api/autore/save-profile", { oem, name, tiers: ["A"] });
  setStatus(r.ok ? `Saved profile "${name}" (id ${r.id})` : "Save: " + r.error);
});

// --------------------------- Frame Decoder (per-ID editable payloads + grid)
let fdMessages = [], fdPayloads = {}, fdDetail = null, fdSelSig = -1, fdTimer = null, fdCurrentDetailId = null;
let fdSource = "dbc";   // "dbc" → show IDs in hex; "json" → show IDs in decimal (native)
// Multi-frame "Trace" mode: decode many payloads of one ID as a change-highlighted matrix.
let fdMode = "single";          // "single" | "trace"
let fdTraceText = {};           // idHex → pasted multi-line payloads (one per line)
let fdTraceFrames = [];         // last decoded trace frames (reused on option toggle)
let fdTraceRaw = false;         // false → physical value, true → raw (hex)
let fdTraceCollapse = true;     // collapse runs of identical consecutive frames
let fdRenderedKey = null;       // "<id>:<mode>" the header was last built for
// Trace can also source from an uploaded log (Vehicle Spy CSV, .asc/.blf/.trc/...)
// instead of pasted payloads — same decode/render pipeline either way.
let fdLogPath = null;           // server-side path of the last uploaded log
let fdLogName = "";             // its filename, for the hint line
let fdLogCatalogue = [];        // [{id, id_hex, ext, count, first_ts, last_ts}]
// Display the CAN ID in its source's native base. `o` is a catalogue row or a decoded frame.
const fdIdLabel = (o) => fdSource === "json" ? `${o.id}` : `0x${o.id_hex}`;
// Group a clean hex string into space-separated bytes: "0128C3" → "01 28 C3".
const spaceHex = (h) => (h.match(/.{1,2}/g) || []).join(" ");
// Raw bit-pattern as hex, zero-padded to the signal's bit width (e.g. 24-bit → "0x0128C3").
function fdRawHex(s) {
  if (s.raw === null || s.raw === undefined) return "—";
  const nib = Math.max(1, Math.ceil((s.length || 8) / 4));
  const hex = Math.abs(s.raw).toString(16).toUpperCase().padStart(nib, "0");
  return (s.raw < 0 ? "-0x" : "0x") + hex;
}
$("btnFdUpload").addEventListener("click", () => $("fdFile").click());
$("btnFdToggleFill").addEventListener("click", () => {
  const box = $("fdFillBox");
  box.classList.toggle("hidden");
  $("btnFdToggleFill").classList.toggle("active", !box.classList.contains("hidden"));
});

function _fdLoaded(filename, messages) {
  fdMessages = messages; fdPayloads = {};
  fdMessages.forEach((m) => (fdPayloads[m.id_hex] = "00".repeat(m.length)));
  // Paste-dump example IDs match the active source's base (decimal for JSON).
  // Both accepted shapes are shown: one record per line, or `id:payload` pairs
  // separated by semicolons (a whole-bus snapshot pastes as a single line).
  const fill = $("fdFill");
  if (fill) fill.placeholder = fdSource === "json"
    ? "912  0128C30000000000\n900  0205000000000200\nor   0000038F:0128C3…;00000384:0205…"
    : "163  0205000000000200\n94   0006320040001C00\nor   163:0205…;94:000632…";
  $("fdDbcStatus").textContent = `${filename} — ${fdMessages.length} messages`;
  $("fdMsgCount").textContent = `${fdMessages.length} IDs`;
  fdDetail = null; fdCurrentDetailId = null;
  $("fdDetailHeader").innerHTML = "";
  $("fdDetailBody").innerHTML = `<div class="fd-placeholder">${_bigGrid}<span>Click a message row to decode</span></div>`;
  renderFdCatalogue();
}

$("fdFile").addEventListener("change", async (e) => {
  const f = e.target.files[0]; if (!f) return;
  // Auto-detect format from the file extension (.json → signature, else DBC).
  const isJson = (f.name.split(".").pop() || "").toLowerCase() === "json";
  $("fdDbcStatus").textContent = "Loading…";
  const r = await apiUpload(isJson ? "/api/decode/json-import" : "/api/decode/dbc-import", f);
  if (!r.ok) return void ($("fdDbcStatus").textContent = "error: " + r.error);
  fdSource = isJson ? "json" : "dbc";
  _fdLoaded(f.name, r.messages);
  e.target.value = "";          // allow re-uploading the same file
});
function renderFdCatalogue() {
  $("fdCatalogue").innerHTML =
    `<table class="data-table"><colgroup>
      <col class="c-num"><col class="c-id"><col class="c-dlc"><col class="c-sigs">
    </colgroup><thead><tr>
      <th style="text-align:center">#</th>
      <th>CAN ID${fdSource === "json" ? " (dec)" : ""} · Message</th>
      <th style="text-align:center">DLC</th>
      <th>Signals</th>
    </tr></thead><tbody>` +
    fdMessages.map((m, i) => {
      const sigList = m.signals.join(", ") || "—";
      // Echo the payload under the name once it carries something other than the
      // all-zero default, so a paste-fill is visible at a glance instead of only
      // after clicking each row.
      const p = fdPayloads[m.id_hex] || "";
      const loaded = p && !/^0+$/.test(p);
      const payloadLine = loaded
        ? `<div class="fd-cat-payload">${spaceHex(p.toUpperCase())}</div>` : "";
      return `<tr data-id="${m.id_hex}">
        <td>${i + 1}</td>
        <td class="mono" style="font-weight:500">${fdIdLabel(m)}&thinsp;<span style="color:var(--muted);font-weight:400;font-family:inherit">· ${m.name}</span>${payloadLine}</td>
        <td style="text-align:center">${m.length}</td>
        <td class="muted-line" style="font-size:12px" title="${sigList}">${m.signals.length}: ${sigList}</td>
      </tr>`;
    }).join("") + `</tbody></table>`;
}
$("fdCatalogue").addEventListener("click", (e) => {
  const tr = e.target.closest("tr[data-id]"); if (tr) fdDecodeOne(tr.dataset.id);
});
async function fdDecodeOne(idHex) {
  const r = await POST("/api/decode/frames", { frames: [{ id: idHex, data: fdPayloads[idHex] || "" }] });
  if (!r.ok || !r.frames.length) return;
  fdDetail = r.frames[0]; fdSelSig = -1; renderFdDetail();
  document.querySelectorAll("#fdCatalogue tr[data-id]").forEach((tr) => tr.classList.toggle("sel", tr.dataset.id === idHex));
}
window.fdSelectSig = (si) => { fdSelSig = si; if (fdDetail) fdRenderBody(fdDetail); };
function renderFdDetail() {
  const f = fdDetail;
  if (!f) {
    fdCurrentDetailId = null; fdRenderedKey = null;
    $("fdDetailHeader").innerHTML = "";
    $("fdDetailBody").innerHTML = `<div class="fd-placeholder">${_bigGrid}<span>Click a message row to decode</span><span class="muted-line" style="font-size:12px">Byte view · Signal table · Bit grid will appear here</span></div>`;
    return;
  }
  if (f.error) {
    fdCurrentDetailId = null; fdRenderedKey = null;
    $("fdDetailHeader").innerHTML = "";
    $("fdDetailBody").innerHTML = `<div style="padding:16px;color:var(--muted)">${fdIdLabel(f)} — ${f.error}</div>`;
    return;
  }
  // Rebuild the header only when the message OR the mode changes (preserves input focus while typing).
  const key = f.id_hex + ":" + fdMode;
  if (fdRenderedKey !== key) {
    fdRenderedKey = key;
    fdCurrentDetailId = f.id_hex;
    const seg = `<span class="fd-seg">
        <button class="${fdMode === "single" ? "active" : ""}" onclick="fdSetMode('single')">Single</button>
        <button class="${fdMode === "trace" ? "active" : ""}" onclick="fdSetMode('trace')">Trace</button>
      </span>`;
    const head = `<div class="panel-head">
        <span class="mono" style="font-weight:500">${fdIdLabel(f)}&thinsp;<span style="color:var(--muted);font-weight:400;font-family:inherit">· ${f.name}</span></span>
        <span style="display:flex;align-items:center;gap:10px">
          <span class="tag" style="font-size:11px">DLC ${f.length}</span>${seg}
        </span>
      </div>`;
    if (fdMode === "single") {
      $("fdDetailHeader").innerHTML = head + `
        <div class="fd-pay-bar">
          <span class="muted-line" style="font-size:12px;white-space:nowrap">Payload (hex)</span>
          <input id="fdPayInput" class="fdpay" value="${spaceHex(fdPayloads[f.id_hex] || "")}"
            placeholder="${spaceHex("00".repeat(f.length))}"
            maxlength="${f.length * 3}"
            autocomplete="off" spellcheck="false" />
          <span id="fdPayHint" class="muted-line" style="font-size:11px;white-space:nowrap">0 / ${f.length} bytes</span>
        </div>`;
      $("fdPayInput").addEventListener("input", (e) => {
        const inp = e.target;
        // Strip to hex-only, cap at DLC bytes, then auto-space between bytes for readability.
        const clean = inp.value.replace(/[^0-9a-fA-F]/g, "").slice(0, f.length * 2);
        fdPayloads[f.id_hex] = clean;
        const spaced = spaceHex(clean);
        if (inp.value !== spaced) { inp.value = spaced; inp.setSelectionRange(spaced.length, spaced.length); }
        const bytes = Math.floor(clean.length / 2);
        $("fdPayHint").textContent = `${bytes} / ${f.length} bytes`;
        inp.classList.toggle("invalid", clean.length % 2 !== 0);
        clearTimeout(fdTimer);
        fdTimer = setTimeout(() => fdDecodeBody(f.id_hex), 250);
      });
    } else {
      const ph = `Paste one payload per line — e.g.&#10;525100FFC000BE56&#10;525100498000BE56&#10;(optional leading index/timestamp: '12.34, 5251…')`;
      const inLog = fdLogCatalogue.find((m) => m.id === f.id);
      $("fdDetailHeader").innerHTML = head + `
        <div class="fd-trace-bar">
          <textarea id="fdTraceInput" class="fd-trace-ta" spellcheck="false" autocomplete="off" placeholder="${ph}">${fdTraceText[f.id_hex] || ""}</textarea>
          <div class="fd-trace-tools">
            <input type="file" id="fdLogFile" hidden accept=".csv,.asc,.blf,.trc,.log" />
            <button id="fdLogUploadBtn" class="mini" onclick="$('fdLogFile').click()">Upload log…</button>
            <button id="fdLogLoadBtn" class="mini" ${inLog ? "" : "disabled"} onclick="fdLoadFromLog('${f.id_hex}')"
              title="${inLog ? `${inLog.count} frame(s) of this ID in ${fdLogName}` : "Upload a log with this ID first"}">Load from log${inLog ? ` (${inLog.count})` : ""}</button>
            <button id="fdTraceRawBtn" class="mini ${fdTraceRaw ? "active" : ""}" onclick="fdTraceToggleRaw()">Raw (hex)</button>
            <button id="fdTraceColBtn" class="mini ${fdTraceCollapse ? "active" : ""}" onclick="fdTraceToggleCollapse()">Collapse duplicates</button>
            <button id="fdTraceCsvBtn" class="mini" onclick="fdTraceExport()">Download CSV</button>
            <span id="fdTraceHint" class="muted-line" style="font-size:11px"></span>
          </div>
        </div>`;
      const ta = $("fdTraceInput");
      ta.addEventListener("input", () => {
        fdTraceText[f.id_hex] = ta.value;
        clearTimeout(fdTimer);
        fdTimer = setTimeout(() => fdDecodeTrace(f.id_hex), 300);
      });
      $("fdLogFile").addEventListener("change", (e) => {
        const file = e.target.files[0]; if (file) fdUploadLog(file);
      });
    }
  }
  if (fdMode === "single") fdRenderBody(f);
  else fdDecodeTrace(f.id_hex);
}
window.fdSetMode = (m) => { if (fdMode === m) return; fdMode = m; renderFdDetail(); };
window.fdTraceToggleRaw = () => {
  fdTraceRaw = !fdTraceRaw;
  const b = $("fdTraceRawBtn"); if (b) b.classList.toggle("active", fdTraceRaw);
  fdRenderTrace();
};
window.fdTraceToggleCollapse = () => {
  fdTraceCollapse = !fdTraceCollapse;
  const b = $("fdTraceColBtn"); if (b) b.classList.toggle("active", fdTraceCollapse);
  fdRenderTrace();
};
// Export the decoded trace to CSV: Frame No, Message ID, RAW payload, then one
// column per signal (parsed physical value). Always per-frame (not collapsed).
window.fdTraceExport = () => {
  const frames = fdTraceFrames;
  if (!frames.length) { setStatus("Nothing to export — paste payloads first"); return; }
  const ok = frames.filter((fr) => fr && fr.signals);
  const cols = ok.length ? ok[0].signals.map((s) => s.name) : [];
  const unit = {};
  ok.forEach((fr) => fr.signals.forEach((s) => { if (s.unit && !unit[s.name]) unit[s.name] = s.unit; }));
  const esc = (v) => {
    const t = v == null ? "" : String(v);
    return /[",\n]/.test(t) ? `"${t.replace(/"/g, '""')}"` : t;
  };
  const idLabel = (fr) => (fdSource === "json" ? String(fr.id) : "0x" + fr.id_hex);
  const header = ["Frame No", "Message ID", "RAW payload",
                  ...cols.map((c) => (unit[c] ? `${c} (${unit[c]})` : c))];
  const rows = frames.map((fr, i) => {
    const base = [i + 1, idLabel(fr), fr._data || ""];
    if (fr.error) return [...base, fr.error, ...cols.slice(1).map(() => "")].map(esc).join(",");
    const byName = {}; (fr.signals || []).forEach((s) => (byName[s.name] = s));
    return [...base, ...cols.map((c) => (byName[c] ? byName[c].physical : ""))].map(esc).join(",");
  });
  const csv = [header.map(esc).join(","), ...rows].join("\r\n");

  const now = new Date();
  const pad = (n) => String(n).padStart(2, "0");
  const ts = `${pad(now.getDate())}${pad(now.getMonth() + 1)}${String(now.getFullYear()).slice(-2)}_${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`;
  const id = fdDetail ? (fdSource === "json" ? String(fdDetail.id) : fdDetail.id_hex) : "trace";
  const blob = new Blob([csv], { type: "text/csv" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob); a.download = `Trace_${id}_${ts}.csv`; a.click();
  setStatus(`Trace exported — ${frames.length} frame${frames.length === 1 ? "" : "s"} → ${a.download}`);
};

// Parse the trace textarea into [{label, data}]. One payload per line; a leading
// short decimal/timestamp token (e.g. "12.34, " or "1 ") is taken as the row label.
function fdParseTrace(text) {
  const out = [];
  (text || "").split(/\r?\n/).forEach((ln) => {
    const t = ln.trim(); if (!t) return;
    let toks = t.split(/[\s,]+/).filter(Boolean);
    let label = null;
    if (toks.length > 1 && /^[0-9]+(\.[0-9]+)?$/.test(toks[0]) && toks[0].length <= 8) {
      label = toks[0]; toks = toks.slice(1);
    }
    const hex = toks.join("").replace(/[^0-9a-fA-F]/g, "");
    if (!hex) return;
    out.push({ label: label ?? String(out.length + 1), data: hex });
  });
  return out;
}

async function fdDecodeTrace(idHex) {
  const lines = fdParseTrace(fdTraceText[idHex] || "").slice(0, 2000);
  if (!lines.length) {
    fdTraceFrames = [];
    if ($("fdTraceHint")) $("fdTraceHint").textContent = "";
    $("fdDetailBody").innerHTML = `<div class="muted-line" style="padding:16px;font-size:13px">Paste payloads above — one per line — or <b>Upload log…</b> to build the trace.</div>`;
    return;
  }
  await fdDecodeTraceLines(idHex, lines);
}

// Shared by paste-mode and log-mode: decode {label, data} pairs against the
// loaded DBC/JSON and render. `lines` is capped upstream by each caller.
async function fdDecodeTraceLines(idHex, lines) {
  const r = await POST("/api/decode/frames", { frames: lines.map((l) => ({ id: idHex, data: l.data })) });
  if (!r.ok || !r.frames) return;
  fdTraceFrames = r.frames.map((fr, i) => ({
    ...fr,
    _label: lines[i] ? lines[i].label : String(i + 1),
    _data: lines[i] ? lines[i].data.toUpperCase() : "",
  }));
  fdRenderTrace();
}

// Upload a CAN log (Vehicle Spy 3 CSV, .asc/.blf/.trc/...) and catalogue its
// arbitration IDs, so Trace can load real captured frames for the open message.
// Only reachable from within Trace mode (the file input lives in its markup).
async function fdUploadLog(file) {
  setStatus(`Uploading ${file.name}…`);
  const up = await apiUpload("/api/upload", file);
  if (!up || !up.ok) { setStatus(`Log upload failed: ${(up && up.error) || "unknown error"}`); return; }
  const cat = await POST("/api/log/catalogue", { path: up.path });
  if (!cat.ok) { setStatus(`Could not read log: ${cat.error}`); return; }
  fdLogPath = up.path; fdLogName = file.name; fdLogCatalogue = cat.messages;
  const totalFrames = cat.messages.reduce((n, m) => n + m.count, 0);
  setStatus(`${file.name} — ${cat.messages.length} IDs, ${totalFrames} frames`);
  fdRenderedKey = null; renderFdDetail();     // rebuild the header so "Load from log" reflects the new catalogue
}

// Pull every captured occurrence of the open message's ID from the uploaded
// log (real timestamps as row labels) and decode it through the usual path.
window.fdLoadFromLog = async function fdLoadFromLog(idHex) {
  if (!fdLogPath || !fdDetail) return;
  const r = await POST("/api/log/trace", { path: fdLogPath, id: fdDetail.id, ext: false });
  if (!r.ok) { setStatus(`Load from log failed: ${r.error}`); return; }
  const lines = r.frames.slice(0, 2000);
  setStatus(`Loaded ${r.frames.length} frame(s) of 0x${idHex} from ${fdLogName}`);
  await fdDecodeTraceLines(idHex, lines);
};

function fdRenderTrace() {
  const frames = fdTraceFrames, body = $("fdDetailBody");
  if (!frames.length) { body.innerHTML = `<div style="padding:16px" class="muted-line">Paste payloads above to build the trace.</div>`; return; }
  const ok = frames.filter((fr) => fr && fr.signals);
  const cols = ok.length ? ok[0].signals.map((s) => s.name) : [];

  // Per-signal stats over every frame → const vs varies + min/max.
  const stat = {};
  cols.forEach((c) => (stat[c] = { vals: new Set(), min: null, max: null, unit: "" }));
  ok.forEach((fr) => fr.signals.forEach((s) => {
    const st = stat[s.name]; if (!st) return;
    st.vals.add(s.raw); if (s.unit) st.unit = s.unit;
    if (typeof s.raw === "number") {
      st.min = st.min === null ? s.raw : Math.min(st.min, s.raw);
      st.max = st.max === null ? s.raw : Math.max(st.max, s.raw);
    }
  }));
  const isConst = {}; cols.forEach((c) => (isConst[c] = stat[c].vals.size <= 1));

  // Display rows: optionally collapse runs of identical consecutive frames.
  const rowMap = (fr) => { const m = {}; (fr.signals || []).forEach((s) => (m[s.name] = s)); return m; };
  const sig = (fr) => fr.error ? "ERR:" + fr.error : (fr.signals || []).map((s) => s.raw).join("|");
  let disp = [];
  frames.forEach((fr) => {
    const k = sig(fr), prev = disp[disp.length - 1];
    if (fdTraceCollapse && prev && prev.key === k) { prev.count++; prev.last = fr._label; return; }
    disp.push({ key: k, count: 1, first: fr._label, last: fr._label, fr, map: rowMap(fr) });
  });
  const total = frames.length, capped = disp.length > 1000;
  if (capped) disp = disp.slice(0, 1000);

  // Summary strip.
  const sChip = (c) => {
    const s = stat[c], u = s.unit ? " " + s.unit : "";
    return `<span class="${isConst[c] ? "tc-const" : ""}" style="display:inline-flex;gap:5px;align-items:center">
      <b style="font-weight:600;color:var(--text)">${c}</b>` +
      (isConst[c] ? `<span class="muted-line">const</span>`
                  : `<span class="ok-ink">varies</span><span class="muted-line">${s.min}–${s.max}${u}</span>`) + `</span>`;
  };
  const summary = `<div style="display:flex;flex-wrap:wrap;gap:8px 18px;font-size:11px;color:var(--muted);margin-bottom:12px">${cols.map(sChip).join("")}</div>`;

  // Matrix with change-highlighting.
  const fmt = (s) => (s == null ? "—" : (fdTraceRaw ? fdRawHex(s) : s.physical));
  let prev = null;
  const trows = disp.map((d, ri) => {
    let cells;
    if (d.fr.error) {
      cells = `<td colspan="${cols.length}" class="tc-oor mono" style="text-align:left">${d.fr.error}</td>`;
    } else {
      cells = cols.map((c) => {
        const s = d.map[c];
        const changed = prev && prev[c] && s && prev[c].raw !== s.raw;
        const cls = [isConst[c] ? "tc-const" : "", changed ? "tc-chg" : "", s && s.out_of_range ? "tc-oor" : ""].filter(Boolean).join(" ");
        return `<td class="mono ${cls}" style="text-align:right" title="${s ? s.raw + " (raw)" : ""}">${fmt(s)}</td>`;
      }).join("");
    }
    prev = d.fr.error ? null : d.map;
    const lbl = d.count > 1 ? `${d.first}–${d.last}` : d.first;
    const cnt = d.count > 1 ? ` <span class="tc-cnt">×${d.count}</span>` : "";
    return `<tr><td class="tc-cnt" style="text-align:center">${ri + 1}</td><td class="mono" style="white-space:nowrap">${lbl}${cnt}</td>${cells}</tr>`;
  }).join("");

  const head = `<tr><th style="text-align:center;width:40px">#</th><th style="text-align:left">Frame</th>` +
    cols.map((c) => `<th class="${isConst[c] ? "tc-const" : ""}" style="text-align:right">${c}</th>`).join("") + `</tr>`;
  const note = `${total} frame${total === 1 ? "" : "s"} → ${disp.length} ${fdTraceCollapse ? "state" : "row"}${disp.length === 1 ? "" : "s"}${capped ? " (showing first 1000)" : ""}`;
  if ($("fdTraceHint")) $("fdTraceHint").textContent = note;

  body.innerHTML = `<div style="padding:12px 16px">
    ${summary}
    <div style="overflow:auto"><table class="data-table trace-tbl"><thead>${head}</thead><tbody>${trows}</tbody></table></div>
    <div class="muted-line" style="font-size:11px;margin-top:8px">Changed cells highlighted · constant signals dimmed · ${note}</div>
  </div>`;
}
async function fdDecodeBody(idHex) {
  const r = await POST("/api/decode/frames", { frames: [{ id: idHex, data: fdPayloads[idHex] || "" }] });
  if (!r.ok || !r.frames.length) return;
  fdDetail = r.frames[0]; fdSelSig = -1; fdRenderBody(fdDetail);
}
function fdRenderBody(f) {
  const COLS = [7, 6, 5, 4, 3, 2, 1, 0];
  const sel = (fdSelSig >= 0 && f.signals[fdSelSig]) ? f.signals[fdSelSig] : null;
  const single = !!(sel && sel.msb_cell && sel.lsb_cell
    && sel.msb_cell[0] === sel.lsb_cell[0] && sel.msb_cell[1] === sel.lsb_cell[1]);
  const idx = f.bytes.map((_, i) => `<td>${String(i).padStart(2, "0")}</td>`).join("");
  const val = f.bytes.map((b) => `<td>${b.toString(16).toUpperCase().padStart(2, "0")}</td>`).join("");

  // Check if any signal in this frame has a DBC value description
  const hasChoices = f.signals.some((s) => s.choice !== null && s.choice !== undefined);

  const rows = f.signals.map((s, si) => {
    const oor = s.out_of_range;
    const physColor = oor ? "var(--danger-ink)" : "var(--accent-ink)";
    const oorBadge = oor
      ? ` <span class="tag bad" title="Outside the DBC range [${s.min ?? "?"}…${s.max ?? "?"}]">Out of range</span>`
      : "";
    // Value description (DBC VAL_ label) — wraps inside its column, never overflows
    const descCell = hasChoices
      ? `<td>${s.choice != null ? `<div class="fd-desc">${s.choice}</div>` : '<span style="color:var(--muted)">—</span>'}</td>`
      : "";
    return `<tr class="${si === fdSelSig ? "sel" : ""}" style="cursor:pointer" onclick="fdSelectSig(${si})" title="Click to highlight bits">
      <td style="text-align:center;color:var(--muted);vertical-align:top">${si + 1}</td>
      <td style="font-weight:500;vertical-align:top;word-break:break-word">${s.name}</td>
      <td class="mono" style="text-align:right;vertical-align:top" title="${s.raw} (dec)">${fdRawHex(s)}</td>
      <td class="mono" style="text-align:right;vertical-align:top;color:${physColor}">${s.physical}${oorBadge}</td>
      <td style="color:var(--muted);font-size:12px;vertical-align:top">${s.unit || "—"}</td>
      ${descCell}
    </tr>`;
  }).join("") || `<tr class="empty-row"><td colspan="${hasChoices ? 6 : 5}">No decoded signals.</td></tr>`;

  // Header: add Description column only when needed
  const descHead = hasChoices ? `<th>Description</th>` : "";

  // Colours from the theme tokens: the selected signal's bits in --info (a
  // second kind beside the green LSB), the MSB in the fixed amber swatch.
  const C_HI = tok("--info"), C_MSB = tok("--bit-msb"), C_LSB = tok("--ok");
  // One series colour per signal for the message-layout view.
  const sigColorAt = (i) => SERIES[i % SERIES.length];
  const _lum = (h) => 0.299 * parseInt(h.slice(1, 3), 16)
                    + 0.587 * parseInt(h.slice(3, 5), 16)
                    + 0.114 * parseInt(h.slice(5, 7), 16);
  const txtOn = (h) => (_lum(h) > 150 ? "var(--ink-on-bright)" : "var(--ink-light)");

  // Map every grid cell to its owning signal + remember each signal's MSB/LSB cell.
  const owner = {}, msbOf = {}, lsbOf = {};
  f.signals.forEach((s, i) => {
    (s.cells || []).forEach((c) => { owner[c[0] + ":" + c[1]] = i; });
    if (s.msb_cell) msbOf[s.msb_cell[0] + ":" + s.msb_cell[1]] = i;
    if (s.lsb_cell) lsbOf[s.lsb_cell[0] + ":" + s.lsb_cell[1]] = i;
  });
  // Arrow glyph pointing from the LSB cell toward the MSB cell (bit direction).
  const arrowFor = (s) => {
    if (!s || !s.msb_cell || !s.lsb_cell) return "";
    const dr = s.msb_cell[0] - s.lsb_cell[0];
    const dc = COLS.indexOf(s.msb_cell[1]) - COLS.indexOf(s.lsb_cell[1]);
    if (dr === 0 && dc === 0) return "";
    if (Math.abs(dr) >= Math.abs(dc)) return dr < 0 ? "↑" : "↓";
    return dc < 0 ? "←" : "→";
  };

  // Highlighted header cells (gray top row + left column, like CANdb++ Layout).
  const hSty = "background:var(--panel-2);color:var(--dim);font-weight:600;border:1px solid var(--border-strong);font-size:11px;text-align:center;font-family:var(--mono)";
  const bitHead = COLS.map((c) => `<th style="${hSty};width:30px;height:24px">${c}</th>`).join("");

  let grid = `<table class="bitgrid" style="border-collapse:collapse"><thead><tr>`
    + `<th style="${hSty};width:26px;height:24px"></th>${bitHead}</tr></thead><tbody>`;
  for (let b = 0; b < f.bytes.length; b++) {
    grid += `<tr><th style="${hSty};width:26px;height:30px">${b}</th>` + COLS.map((c) => {
      const key = b + ":" + c, bit = (f.bytes[b] >> c) & 1, idx = b * 8 + c;
      const si = owner[key];
      const isMsb = si !== undefined && msbOf[key] === si;
      const isLsb = si !== undefined && lsbOf[key] === si;
      let bg = "transparent", tc = "var(--muted)", fw = "400", tag = "";
      if (sel) {                                   // single-signal highlight mode
        if (si === fdSelSig) {
          fw = "700";
          if (single) { bg = C_HI; tc = txtOn(C_HI); tag = "bit"; }
          else if (isMsb) { bg = C_MSB; tc = "var(--ink-on-bright)"; tag = "msb"; }
          else if (isLsb) { bg = C_LSB; tc = txtOn(C_LSB); tag = "lsb " + arrowFor(sel); }
          else { bg = C_HI; tc = txtOn(C_HI); }
        }
      } else if (si !== undefined) {               // message-layout mode (all signals)
        const col = sigColorAt(si);
        bg = col; tc = txtOn(col); fw = "600";
        if (isMsb && isLsb) tag = "bit";
        else if (isMsb) tag = "msb";
        else if (isLsb) tag = "lsb " + arrowFor(f.signals[si]);
      }
      const idxSpan = `<span style="position:absolute;top:0;right:2px;font-size:8px;line-height:1.1;opacity:.5;font-weight:400">${idx}</span>`;
      const tagSpan = tag ? `<span style="position:absolute;bottom:-1px;left:0;right:0;font-size:7px;line-height:1.2;font-weight:600">${tag}</span>` : "";
      return `<td style="position:relative;width:30px;height:30px;padding:0;border:1px solid var(--border-strong);text-align:center;background:${bg};color:${tc};font-weight:${fw}">`
        + `${idxSpan}<span style="font-size:12px;line-height:30px">${bit}</span>${tagSpan}</td>`;
    }).join("") + `</tr>`;
  }
  grid += `</tbody></table>`;

  // Legend — selected signal: MSB/bits/LSB + arrow; otherwise one chip per signal.
  const sw = (c) => `<i style="width:12px;height:12px;border-radius:3px;display:inline-block;background:${c}"></i>`;
  const chip = (c, label) => `<span style="display:inline-flex;align-items:center;gap:5px">${sw(c)}${label}</span>`;
  const legendStyle = "display:flex;gap:14px;flex-wrap:wrap;margin-top:8px;font-size:11px;color:var(--muted)";
  let legend;
  if (sel) {
    legend = single
      ? `<div style="${legendStyle}">${chip(C_HI, "signal bit")}</div>`
      : `<div style="${legendStyle}">${chip(C_MSB, "MSB")}${chip(C_HI, "signal bits")}${chip(C_LSB, "LSB")}<span>arrow ${arrowFor(sel)} = LSB→MSB</span></div>`;
  } else {
    legend = `<div style="${legendStyle}">`
      + f.signals.map((s, i) => chip(sigColorAt(i), s.name)).join("")
      + (f.signals.length ? `<span style="opacity:.8">· msb/lsb + arrow show bit direction</span>` : "")
      + `</div>`;
  }

  $("fdDetailBody").innerHTML = `<div style="padding:12px 16px">
    <div class="sec-h">Data bytes <span class="ui-count">hex</span></div>
    <table class="byteview mono"><tbody><tr><th>Byte</th>${idx}</tr><tr><th>Value</th>${val}</tr></tbody></table>
    <div style="margin-top:16px">
      <div class="sec-h">Signals</div>
      <div style="overflow-x:auto">
        <table class="data-table">
          <colgroup><col style="width:34px"><col><col style="width:84px"><col style="width:92px"><col style="width:48px">${hasChoices ? "<col>" : ""}</colgroup>
          <thead><tr>
            <th style="text-align:center">#</th><th>Signal</th>
            <th style="text-align:right">Raw</th>
            <th style="text-align:right">Physical</th>
            <th>Unit</th>
            ${descHead}
          </tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    </div>
    <div class="fd-sec">
      <div class="sec-h" data-tip="Click a signal above to isolate its bits. The arrows point from the LSB towards the MSB.">Bit layout</div>
      <div style="overflow-x:auto">${grid}</div>
      ${legend}
    </div>
  </div>`;
}
// One `<id><sep><payload>` record per entry. Records are separated by newlines
// **or** semicolons, and the id from its payload by whitespace, comma or colon —
// so a one-line cloud snapshot ("000000E1:000040A0...;00000120:0002FEA2...")
// pastes as readily as a hand-typed two-column dump.
function fdParseFill(text) {
  return text.split(/[;\n]+/)
    .map((rec) => rec.trim().split(/[\s,:]+/).filter(Boolean))
    .filter((t) => t.length >= 2);
}
// Which base the *pasted* ids are in. It need not match the base the catalogue
// displays: a JSON signature lists decimal ids, yet a snapshot of the same bus
// is dumped as 8-digit zero-padded hex. Same rule as jsondecode.detect_id_base —
// only unambiguous evidence (a 0x prefix, a hex letter, or zero-padding) wins,
// since "163" alone is legal in both bases; otherwise trust the source.
function fdDetectIdBase(ids, fallback) {
  for (const s of ids) {
    if (/^0x/i.test(s) || /[a-f]/i.test(s)) return 16;
    if (s.length > 1 && s[0] === "0") return 16;
  }
  return fallback;
}
$("btnFdFill").addEventListener("click", () => {
  const recs = fdParseFill($("fdFill").value);
  // ID base follows the active source (decimal for JSON, hex for DBC) unless the
  // paste itself proves otherwise.
  const fallback = fdSource === "json" ? 10 : 16;
  const idBase = fdDetectIdBase(recs.map((t) => t[0]), fallback);
  let matched = 0, firstFilled = null;
  const unknown = [];
  for (const t of recs) {
    const id = parseInt(t[0], idBase); if (isNaN(id)) continue;
    const idHex = id.toString(16).toUpperCase();
    if (idHex in fdPayloads) {
      // join remaining tokens so spaced payloads ("01 28 C3") work, hex-only
      fdPayloads[idHex] = t.slice(1).join("").replace(/[^0-9a-fA-F]/g, "");
      matched++;
      if (!firstFilled) firstFilled = idHex;
    } else {
      unknown.push(t[0]);
    }
  }
  renderFdCatalogue();
  // Show a decode straight away. Filling only mutates fdPayloads, so without this
  // the whole action is invisible — the catalogue looks identical and the detail
  // pane still reads "Click a message row", which reads as a dead button.
  const openId = fdCurrentDetailId && fdCurrentDetailId in fdPayloads
    ? fdCurrentDetailId : firstFilled;
  if (openId) { fdCurrentDetailId = null; fdDecodeOne(openId); }
  // Say what was read *and* what was skipped — a silent 0-match paste otherwise
  // looks like a broken button when it is really a base or definition mismatch.
  const idsIn = idBase === 16 ? "hex" : "decimal";
  let msg = `${matched}/${recs.length} matched · ids read as ${idsIn}`;
  if (unknown.length) {
    const shown = unknown.slice(0, 6).join(", ");
    msg += ` · not in this definition: ${shown}${unknown.length > 6 ? `, +${unknown.length - 6} more` : ""}`;
  }
  if (!recs.length) msg = "nothing to read — expected `id payload` per line, or `id:payload;id:payload`";
  const out = $("fdFillMsg");
  if (out) { out.textContent = msg; out.style.color = matched ? "var(--ok-ink)" : "var(--danger-ink)"; }
  setStatus("Fill payloads — " + msg);
});

// ----------------------- Converter workbench (upload · edit · select · export)
let cvModel = null, cvSourceFmt = null, cvSourceName = null, cvEdited = false, cvEditMode = false;
const CV_FMT = { dbc: "DBC", json: "JSON", csv: "CSV", canplus: "CanPlus XML" };
// CAN IDs read in hex for DBC/CSV (engineer convention, matches the source);
// JSON keeps decimal because its keys are native decimal. Display only — the
// model frame_id stays an int, so conversions/exports are unchanged.
const cvIdHex = () => cvSourceFmt !== "json";
const cvFmtId = (id) => (cvIdHex() ? "0x" + (id || 0).toString(16).toUpperCase() : String(id));
const cvParseId = (val) => {
  const t = String(val).trim();
  if (/^0x/i.test(t)) return parseInt(t, 16) || 0;
  return (cvIdHex() ? parseInt(t, 16) : parseInt(t, 10)) || 0;
};
const CV_ICON = { edit: ICONS.edit, lock: ICONS.lock };
const escAttr = (s) => String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;");
const cvParseVT = (raw) => {
  const out = {}; let any = false;
  for (const p of String(raw || "").split(";")) {
    const i = p.indexOf(":"); if (i < 0) continue;
    const k = p.slice(0, i).trim(), v = p.slice(i + 1).trim();
    if (k === "" || isNaN(+k)) continue;
    out[+k] = v; any = true;
  }
  return any ? out : null;
};
const cvFmtVT = (vt) => vt ? Object.entries(vt).map(([k, v]) => `${k}:${v}`).join(";") : "";
// Big-endian startingBit maps exactly to the DBC Motorola position (validated),
// so there is no longer any sub-byte ambiguity to flag.
function cvBeDoubt() { return null; }

$("btnCvUpload").addEventListener("click", () => $("cvFile").click());
$("cvFile").addEventListener("change", async (e) => {
  const f = e.target.files[0]; if (!f) return;
  $("cvFileName").textContent = f.name; $("cvStatus").textContent = "Parsing…";
  const fd = new FormData(); fd.append("file", f);
  let r;
  try { r = await fetch("/api/convert/parse", { method: "POST", body: fd }).then((x) => x.json()); }
  catch (err) { $("cvStatus").textContent = "Network error: " + err; return; }
  if (!r.ok) { $("cvStatus").textContent = "Error: " + r.error; cvModel = null; renderCv(); return; }
  cvModel = r.model; cvSourceFmt = r.source_fmt; cvSourceName = r.source_name;
  cvEdited = false; cvEditMode = false;          // #1: open in read-only view mode
  cvModel.messages.forEach((m) => m.signals.forEach((s) => (s._sel = true)));   // select all by default
  $("cvStatus").textContent = "";
  $("cvWarnings").innerHTML = (r.warnings && r.warnings.length)
    ? cvWarnBox(r.warnings, "from parsing") : "";
  cvBuildFormatOptions();
  renderCv();
});

function cvWarnBox(warns, ctx) {
  return `<div class="notes-box">
    <div class="notes-h">${ICONS.alert}<span>${warns.length} note${warns.length === 1 ? "" : "s"} ${ctx || ""}</span></div>
    <ul>${warns.map((w) => `<li>${w}</li>`).join("")}</ul></div>`;
}

function cvBuildFormatOptions() {
  const sel = $("cvTo"), prev = sel.value;
  const opts = [];
  ["json", "dbc", "csv"].forEach((f) => {
    if (f === cvSourceFmt && !cvEdited) return;        // #1: hide same-format until edited
    opts.push(`<option value="${f}">${f === cvSourceFmt ? CV_FMT[f] + " (save edits)" : CV_FMT[f]}</option>`);
  });
  sel.innerHTML = opts.join("");
  if ([...sel.options].some((o) => o.value === prev)) sel.value = prev;
}

function renderCv() {
  const wb = $("cvWorkbench"), empty = $("cvEmpty");
  if (!cvModel) { wb.classList.add("hidden"); empty.classList.remove("hidden"); return; }
  empty.classList.add("hidden"); wb.classList.remove("hidden");
  const chip = $("cvSrcChip"); chip.textContent = "source: " + CV_FMT[cvSourceFmt]; chip.classList.remove("hidden");
  const et = $("cvEditToggle");
  et.innerHTML = cvEditMode ? `${CV_ICON.lock}<span>Editing — click to lock</span>` : `${CV_ICON.edit}<span>Edit</span>`;
  et.classList.toggle("cv-editing", cvEditMode);
  const ro = cvEditMode ? "" : "readonly", dis = cvEditMode ? "" : "disabled";
  const filter = ($("cvSearch").value || "").toLowerCase();
  const html = cvModel.messages.map((m, mi) => {
    const rows = m.signals.map((s, si) => ({ s, si }))
      .filter(({ s }) => !filter || s.name.toLowerCase().includes(filter)
        || String(m.frame_id).includes(filter) || cvFmtId(m.frame_id).toLowerCase().includes(filter));
    if (!rows.length) return "";
    const allSel = m.signals.every((s) => s._sel);
    return `<div class="cv-msg">
      <div class="cv-msg-head">
        <input type="checkbox" ${allSel ? "checked" : ""} onchange="cvToggleMsg(${mi},this.checked)" title="select all in message" />
        <input class="cv-in" style="width:78px" value="${cvFmtId(m.frame_id)}" ${ro} onchange="cvEditMsg(${mi},'frame_id',this.value)" title="CAN ID (${cvIdHex() ? "hex" : "decimal"})" />
        <input class="cv-in" style="width:170px" value="${escAttr(m.name)}" ${ro} onchange="cvEditMsg(${mi},'name',this.value)" />
        <span class="muted-line">DLC</span>
        <input class="cv-in n" value="${m.dlc}" ${ro} onchange="cvEditMsg(${mi},'dlc',this.value)" />
        <span class="muted-line">${m.signals.length} signal${m.signals.length === 1 ? "" : "s"}</span>
      </div>
      <div class="table-wrap"><table class="data-table cv-sigtable"><thead><tr>
        <th></th><th>Signal</th><th>Start</th><th>Len</th><th>Order</th><th>Sgn</th>
        <th>Scale</th><th>Offset</th><th>Min</th><th>Max</th><th>Unit</th><th>Value table</th><th>Comment</th>
      </tr></thead><tbody>${rows.map(({ s, si }) => cvSigRow(mi, si, s)).join("")}</tbody></table></div>
    </div>`;
  }).join("");
  $("cvTable").innerHTML = html || `<div class="muted-line" style="padding:14px">No signals match "${filter}".</div>`;
  cvUpdateSelCount(); cvUpdateLoss();
}

function cvSigRow(mi, si, s) {
  const doubt = cvBeDoubt(s.start_bit, s.length, s.byte_order);
  const warn = doubt ? `<span class="doubt-mark" title="${escAttr(doubt)}">${ICONS.alert}</span>` : "";
  const isM = s.byte_order === "big_endian";
  const ro = cvEditMode ? "" : "readonly", dis = cvEditMode ? "" : "disabled";
  return `<tr>
    <td style="text-align:center"><input type="checkbox" ${s._sel ? "checked" : ""} onchange="cvToggleSig(${mi},${si},this.checked)" /></td>
    <td><input class="cv-in" value="${escAttr(s.name)}" ${ro} onchange="cvEdit(${mi},${si},'name',this.value)" />${warn}</td>
    <td><input class="cv-in n" value="${s.start_bit}" ${ro} onchange="cvEdit(${mi},${si},'start_bit',this.value)" /></td>
    <td><input class="cv-in n" value="${s.length}" ${ro} onchange="cvEdit(${mi},${si},'length',this.value)" /></td>
    <td><select class="cv-in" ${dis} onchange="cvEdit(${mi},${si},'byte_order',this.value)">
      <option ${isM ? "selected" : ""}>Motorola</option><option ${!isM ? "selected" : ""}>Intel</option></select></td>
    <td style="text-align:center"><input type="checkbox" ${s.is_signed ? "checked" : ""} ${dis} onchange="cvEdit(${mi},${si},'is_signed',this.checked)" /></td>
    <td><input class="cv-in n" value="${s.scale}" ${ro} onchange="cvEdit(${mi},${si},'scale',this.value)" /></td>
    <td><input class="cv-in n" value="${s.offset}" ${ro} onchange="cvEdit(${mi},${si},'offset',this.value)" /></td>
    <td><input class="cv-in n" value="${s.min ?? ""}" ${ro} onchange="cvEdit(${mi},${si},'min',this.value)" /></td>
    <td><input class="cv-in n" value="${s.max ?? ""}" ${ro} onchange="cvEdit(${mi},${si},'max',this.value)" /></td>
    <td><input class="cv-in" style="width:50px" value="${escAttr(s.unit || "")}" ${ro} onchange="cvEdit(${mi},${si},'unit',this.value)" /></td>
    <td><input class="cv-in" style="width:118px" value="${escAttr(cvFmtVT(s.value_table))}" placeholder="0:Off;1:On" ${ro} onchange="cvEdit(${mi},${si},'value_table',this.value)" /></td>
    <td><input class="cv-in" style="width:130px" value="${escAttr(s.comment || "")}" ${ro} onchange="cvEdit(${mi},${si},'comment',this.value)" /></td>
  </tr>`;
}

window.cvEdit = (mi, si, key, val) => {
  const s = cvModel.messages[mi].signals[si];
  if (key === "byte_order") s.byte_order = val === "Motorola" ? "big_endian" : "little_endian";
  else if (key === "start_bit" || key === "length") s[key] = parseInt(val, 10) || 0;
  else if (key === "scale" || key === "offset") s[key] = parseFloat(val) || 0;
  else if (key === "min" || key === "max") s[key] = val === "" ? null : parseFloat(val);
  else if (key === "is_signed") s.is_signed = val;
  else if (key === "value_table") s.value_table = cvParseVT(val);
  else s[key] = val;
  cvMarkEdited();
  renderCv();      // refresh the doubt markers + loss preview
};
window.cvEditMsg = (mi, key, val) => {
  const m = cvModel.messages[mi];
  if (key === "frame_id") m.frame_id = cvParseId(val);
  else if (key === "dlc") m.dlc = parseInt(val, 10) || 0;
  else m[key] = val;
  cvMarkEdited();
};
function cvMarkEdited() {
  if (!cvEdited) { cvEdited = true; cvBuildFormatOptions(); }
}
window.cvToggleSig = (mi, si, on) => { cvModel.messages[mi].signals[si]._sel = on; cvUpdateSelCount(); cvUpdateLoss(); };
window.cvToggleMsg = (mi, on) => { cvModel.messages[mi].signals.forEach((s) => (s._sel = on)); renderCv(); };
$("cvSelAll").addEventListener("click", () => { cvModel.messages.forEach((m) => m.signals.forEach((s) => (s._sel = true))); renderCv(); });
$("cvSelNone").addEventListener("click", () => { cvModel.messages.forEach((m) => m.signals.forEach((s) => (s._sel = false))); renderCv(); });
$("cvEditToggle").addEventListener("click", () => { if (cvModel) { cvEditMode = !cvEditMode; renderCv(); } });
$("cvSearch").addEventListener("input", renderCv);
$("cvTo").addEventListener("change", cvUpdateLoss);
$("btnCvClear").addEventListener("click", () => {
  cvModel = null; cvSourceFmt = null; cvSourceName = null; cvEdited = false; cvEditMode = false;
  $("cvFile").value = "";
  $("cvFileName").textContent = "no file selected";
  $("cvSrcChip").classList.add("hidden");
  $("cvStatus").textContent = ""; $("cvWarnings").innerHTML = ""; $("cvSelCount").textContent = "";
  renderCv();
});

function cvUpdateSelCount() {
  let sel = 0, tot = 0;
  cvModel.messages.forEach((m) => m.signals.forEach((s) => { tot++; if (s._sel) sel++; }));
  $("cvSelCount").textContent = `${sel} of ${tot} signals selected`;
  $("btnCvDownload").disabled = sel === 0;
}
function cvUpdateLoss() {
  const to = $("cvTo").value; if (!to) return;
  let msg;
  if (to === "json") {
    let u = 0, r = 0, v = 0, c = 0;
    cvModel.messages.forEach((m) => m.signals.forEach((s) => {
      if (!s._sel) return;
      if (s.unit) u++; if (s.min != null || s.max != null) r++; if (s.value_table) v++; if (s.comment) c++;
    }));
    const d = [];
    if (u) d.push(`units (${u})`); if (r) d.push(`min/max (${r})`); if (v) d.push(`value tables (${v})`); if (c) d.push(`comments (${c})`);
    d.push("message names");
    msg = `→ JSON will drop: ${d.join(", ")}.`;
  } else {
    msg = `→ ${CV_FMT[to]} preserves all fields.`;
  }
  let dbt = 0;
  cvModel.messages.forEach((m) => m.signals.forEach((s) => { if (s._sel && cvBeDoubt(s.start_bit, s.length, s.byte_order)) dbt++; }));
  if (dbt) msg += ` · ${dbt} sub-byte big-endian signal${dbt === 1 ? "" : "s"}${to === "dbc" ? " will get a verify comment" : ""}.`;
  $("cvLoss").textContent = msg;
}

$("btnCvDownload").addEventListener("click", async () => {
  if (!cvModel) return;
  const to = $("cvTo").value;
  // Carry id_base: the export writes JSON keys in the source's base (hex for a
  // DBC/CSV), and this model is rebuilt from scratch, so dropping it here would
  // silently renumber 0x120 back into "288".
  const fm = { messages: [], id_base: cvModel.id_base };
  cvModel.messages.forEach((m) => {
    const sigs = m.signals.filter((s) => s._sel).map((s) => {
      const { _sel, doubt, ...clean } = s; return clean;
    });
    if (sigs.length) fm.messages.push({
      name: m.name, frame_id: parseInt(m.frame_id, 10) || 0,
      is_extended: !!m.is_extended, dlc: parseInt(m.dlc, 10) || 8, signals: sigs,
    });
  });
  if (!fm.messages.length) { $("cvStatus").textContent = "Select at least one signal."; return; }
  $("cvStatus").textContent = "Preparing…";
  const r = await POST("/api/convert/export", { model: fm, to, source_name: cvSourceName });
  if (!r.ok) { $("cvStatus").textContent = "Download error: " + r.error; return; }
  const blob = new Blob([r.content], { type: "text/plain" });
  const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = r.filename; a.click();
  $("cvStatus").textContent = `Downloaded ${r.filename}`;
  $("cvWarnings").innerHTML = (r.warnings && r.warnings.length)
    ? cvWarnBox(r.warnings, "— annotated in the file")
    : `<div class="muted-line ok-ink">Clean conversion — downloaded ${r.filename}</div>`;
});

// -------------------------------------------------------------- DBC Builder
let dbcModel = { messages: [] };
async function renderDbc() {
  dbcModel = await api("/api/dbc");
  const host = $("dbcMessages");
  host.innerHTML = dbcModel.messages.map((m, mi) => `
    <div class="dbc-msg">
      <div class="dbc-msg-head">
        <input value="${m.name}" onchange="dbcEdit(${mi},null,'name',this.value)" style="width:200px" />
        <span class="muted-line">ID 0x${m.frame_id.toString(16).toUpperCase()} · len</span>
        <input type="number" value="${m.length}" onchange="dbcEdit(${mi},null,'length',+this.value)" style="width:60px" />
        <span style="flex:1"></span>
        <button class="btn-mini" onclick="dbcAddSig(${mi})">+ Signal</button>
        <button type="button" class="btn-mini" onclick="dbcDelMsg(${mi})">Remove</button>
      </div>
      <table class="data-table dbc-sig-table"><thead><tr>
        <th>Name</th><th>Start</th><th>Len</th><th>Order</th><th>Signed</th><th>Scale</th><th>Offset</th><th>Unit</th><th></th>
      </tr></thead><tbody>
      ${m.signals.map((s, si) => `<tr>
        <td><input value="${s.name}" onchange="dbcEdit(${mi},${si},'name',this.value)"/></td>
        <td><input type="number" value="${s.start_bit}" onchange="dbcEdit(${mi},${si},'start_bit',+this.value)"/></td>
        <td><input type="number" value="${s.length}" onchange="dbcEdit(${mi},${si},'length',+this.value)"/></td>
        <td><select onchange="dbcEdit(${mi},${si},'byte_order',this.value)">
          <option value="little_endian" ${s.byte_order === "little_endian" ? "selected" : ""}>Intel</option>
          <option value="big_endian" ${s.byte_order === "big_endian" ? "selected" : ""}>Motorola</option></select></td>
        <td style="text-align:center"><input type="checkbox" ${s.is_signed ? "checked" : ""} onchange="dbcEdit(${mi},${si},'is_signed',this.checked)"/></td>
        <td><input type="number" step="any" value="${s.scale}" onchange="dbcEdit(${mi},${si},'scale',+this.value)"/></td>
        <td><input type="number" step="any" value="${s.offset}" onchange="dbcEdit(${mi},${si},'offset',+this.value)"/></td>
        <td><input value="${s.unit || ""}" onchange="dbcEdit(${mi},${si},'unit',this.value)"/></td>
        <td><button type="button" class="btn-mini" onclick="dbcDelSig(${mi},${si})">Remove</button></td>
      </tr>`).join("")}
      </tbody></table>
    </div>`).join("") || `<div class="placeholder" style="padding:40px">No messages. Add one, or seed from Reverse Engineering.</div>`;
}
const dbcSave = () => POST("/api/dbc/set", { messages: dbcModel.messages });
window.dbcEdit = (mi, si, key, val) => { (si === null ? dbcModel.messages[mi] : dbcModel.messages[mi].signals[si])[key] = val; dbcSave(); };
window.dbcAddSig = (mi) => { dbcModel.messages[mi].signals.push({ name: "sig_" + dbcModel.messages[mi].signals.length, start_bit: 0, length: 8, byte_order: "little_endian", is_signed: false, scale: 1, offset: 0, unit: "" }); dbcSave().then(renderDbc); };
window.dbcDelSig = (mi, si) => { dbcModel.messages[mi].signals.splice(si, 1); dbcSave().then(renderDbc); };
window.dbcDelMsg = (mi) => { dbcModel.messages.splice(mi, 1); dbcSave().then(renderDbc); };
$("btnDbcAddMsg").addEventListener("click", async () => {
  const hex = await UI.prompt({ title: "New message", label: "Frame ID (hex)", value: "200", action: "Add" });
  if (!hex) return;
  dbcModel.messages.push({ frame_id: parseInt(hex, 16), name: "MSG_" + hex.toUpperCase(), length: 8, is_extended: false, comment: "", signals: [] });
  dbcSave().then(renderDbc);
});
$("btnDbcImport").addEventListener("click", () => $("dbcFile").click());
$("dbcFile").addEventListener("change", async (e) => { const f = e.target.files[0]; if (f) { await apiUpload("/api/dbc/import", f); renderDbc(); } });
$("btnDbcExport").addEventListener("click", async () => {
  const txt = await fetch("/api/dbc/export").then((r) => r.text());
  const blob = new Blob([txt], { type: "text/plain" });
  const now = new Date();
  const pad = (n) => String(n).padStart(2, "0");
  const ts = `${pad(now.getDate())}${pad(now.getMonth()+1)}${String(now.getFullYear()).slice(-2)}_${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`;
  const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = `${ts}.dbc`; a.click();
});
$("btnDbcToViewer").addEventListener("click", async () => {
  const r = await POST("/api/signals/use-builder");
  setStatus(r.ok ? `Loaded ${r.signals.length} signals into Signal Viewer` : r.error);
});

// ------------------------------------------------------------- Signal Viewer
const sigSelected = new Set();
// Log-playback mode: chart a decoded-once log instead of polling live traffic.
// null = live (the original behaviour); set by "Upload log for playback" below.
let sigLogSeries = null;
let sigLogName = "";
let sigLogCoverage = null;           // {unknown_ids, decode_errors} from the last upload
let sigLiveSeries = null;            // last /api/signals/series payload (live mode)
let sigLiveMaxT = 0;
// Per-signal statistics + staleness model, rebuilt whenever the data source
// changes. Keyed by "MSG.SIGNAL" — see sigBuildMeta().
let sigMeta = {};
let sigViewMode = "table";           // "table" | "chart" — table is the default
// Playback transport — purely client-side windowing over the already-decoded
// sigLogSeries; no network calls while scrubbing/playing.
let sigPlaybackT = 0;                 // current playhead, seconds relative to log start
let sigPlaybackMaxT = 0;
// One "time resolution" zoom drives BOTH views: the chart window width and the
// table's row interval scale together, so zooming means the same thing in each.
let sigBaseWindow = 5;                // unzoomed chart window (s)
let sigBaseGrid = 0.05;               // unzoomed table row interval (s)
let sigZoomExp = 0;                   // window/grid multiplier = 2**sigZoomExp
let sigWindowSec = 5;                 // derived: sigBaseWindow * 2**sigZoomExp
let sigGridSec = 0.05;                // derived: sigBaseGrid   * 2**sigZoomExp
let sigScrubLo = 0, sigScrubHi = 0;   // scrubber sub-range (pages as the playhead moves)
let sigAutoScroll = true;             // keep the playhead row in view on the next render
let sigPlaying = false;
let sigPlaySpeed = 1;
let sigPlayRAF = null, sigPlayLastTs = null;
const SIG_SPEEDS = [0.25, 0.5, 1, 2, 4, 8];
const SIG_ZOOM_MIN = -6, SIG_ZOOM_MAX = 8;
const SIG_STALE_FACTOR = 3;           // grey a held value older than 3x its own period
const SIG_MAX_ROWS = 400;             // rows actually written to the DOM
const SIG_RAW_ROWS = 4000;            // rows built before the changes-only filter
const SIG_FULL_SCALE = [255, 4095, 65535, 16777215, 4294967295];   // unscaled-signal tells

function sigResetLogMode() {
  sigLogSeries = null; sigLogName = ""; sigLogCoverage = null;
  sigPlaying = false;
  sigZoomExp = 0;
  sigMeta = {};
  sigTilePrev = {};
  if (sigPlayRAF) { cancelAnimationFrame(sigPlayRAF); sigPlayRAF = null; }
  $("btnPbPlay").innerHTML = ICONS.play;
  $("btnSigLogBack").classList.add("hidden");
  $("sigPlaybackBar").hidden = true;
  $("sigCoveragePanel").hidden = true;
  $("sigSummaryPanel").hidden = true;
  $("sigExportWrap").classList.add("hidden");
  sigApplyPlaybackGating();
}

// ----- per-signal period, staleness and statistics ------------------------
// A signal is "stale" when its held value is older than a few times ITS OWN
// nominal period — not when a row happens to carry no fresh frame. On a 10 ms
// grid a healthy 100 ms signal would otherwise strobe grey 9 rows out of 10,
// which is both unreadable and untrue.
function sigBuildMeta(series) {
  const dbc = {};
  sigAllSignals.forEach((s) => (dbc[s.key] = s));
  const meta = {};
  let minPeriod = Infinity;
  for (const key of Object.keys(series || {})) {
    const pts = series[key];
    if (!pts || !pts.length) continue;
    // Median inter-sample gap (sampled — logs can hold 100k points per signal).
    const step = Math.max(1, Math.floor(pts.length / 400));
    const gaps = [];
    for (let i = step; i < pts.length; i += step) gaps.push((pts[i][0] - pts[i - step][0]) / step);
    gaps.sort((a, b) => a - b);
    const period = gaps.length ? gaps[gaps.length >> 1] : 0;
    let mn = Infinity, mx = -Infinity, decimals = 0;
    const distinct = new Set();
    const dstep = Math.max(1, Math.floor(pts.length / 2000));
    for (let i = 0; i < pts.length; i++) {
      const v = pts[i][1];
      if (v < mn) mn = v;
      if (v > mx) mx = v;
      if (distinct.size <= 64) distinct.add(v);
      if (i % dstep === 0 && decimals < 4) {
        const s = String(v), dot = s.indexOf(".");
        if (dot >= 0) decimals = Math.max(decimals, Math.min(4, s.length - dot - 1));
      }
    }
    const d = dbc[key] || {};
    meta[key] = {
      period, staleAfter: period > 0 ? period * SIG_STALE_FACTOR : 1,
      min: mn, max: mx, distinct: distinct.size, count: pts.length, decimals,
      first: pts[0][0], last: pts[pts.length - 1][0],
      unit: d.unit || "",
      dbcMin: d.minimum == null ? null : d.minimum,
      dbcMax: d.maximum == null ? null : d.maximum,
    };
    if (period > 0) minPeriod = Math.min(minPeriod, period);
  }
  // The finest row interval worth offering is the fastest signal in the data,
  // floored at 10 ms so a 1 ms message can't demand a million-row grid.
  // Rounded to 0.1 ms: an unrounded median (0.0999999...) makes the row budget
  // overshoot by one and reports a "99 ms" grid for a 100 ms signal.
  sigBaseGrid = Math.round(Math.max(0.01, isFinite(minPeriod) ? minPeriod : 0.1) * 10000) / 10000;
  return meta;
}

// Index of the last sample at or before t, or -1 if the signal hasn't started.
function sigIndexAt(pts, t) {
  let lo = 0, hi = pts.length - 1, ans = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (pts[mid][0] <= t) { ans = mid; lo = mid + 1; } else hi = mid - 1;
  }
  return ans;
}

const sigActiveSeries = () => sigLogSeries || sigLiveSeries || {};
// Log playback centres the window on the playhead so you see the approach AND
// the aftermath of every transition; live has no future, so it stays trailing.
function sigWindowBounds() {
  if (!sigLogSeries) return [Math.max(0, sigLiveMaxT - sigWindowSec), sigLiveMaxT];
  const half = sigWindowSec / 2;
  return [sigPlaybackT - half, sigPlaybackT + half];
}
// The row the table locks onto: the playhead in playback, "now" when live.
const sigAnchorT = (t1) => (sigLogSeries ? sigPlaybackT : t1);
// A signal key selected under one DBC almost never exists in the next one —
// left alone, its chart card lingers forever with no checkbox left to clear it.
function sigClearSelection() {
  sigSelected.clear();
  renderChartShells();
}
$("btnSigUseBuilder").addEventListener("click", async () => { sigResetLogMode(); sigClearSelection(); await POST("/api/signals/use-builder"); refreshSigList(); });
$("btnSigImport").addEventListener("click", () => $("sigDbcFile").click());
$("sigDbcFile").addEventListener("change", async (e) => { const f = e.target.files[0]; if (f) { sigResetLogMode(); sigClearSelection(); await apiUpload("/api/signals/import", f); refreshSigList(); } });
$("btnSigClear").addEventListener("click", () => { sigClearSelection(); POST("/api/signals/clear"); });
let sigAllSignals = [];   // cached from the last /api/signals fetch — lets Select all/None re-render without a round-trip
async function refreshSigList() {
  const info = await api("/api/signals");
  $("sigStatus").textContent = info.loaded ? `${info.signals.length} signals · ${info.messages} messages` : "No DBC loaded";
  sigAllSignals = info.signals || [];
  sigRebuildColorIndex();
  sigApplyPlaybackGating();      // owns the Computed & alarms panel's visibility
  renderSigCheckboxes();
}
// A signal's colour follows the signal, not its position in whatever subset is
// on screen — filtering or deselecting must never repaint the survivors.
let sigColorIdx = {};
function sigRebuildColorIndex() {
  sigColorIdx = {};
  sigAllSignals.forEach((s, i) => (sigColorIdx[s.key] = i));
}
function sigColorOf(key) {
  let i = sigColorIdx[key];
  if (i === undefined) {           // computed channels etc. aren't in the DBC list
    i = 0;
    for (let c = 0; c < key.length; c++) i = (i * 31 + key.charCodeAt(c)) >>> 0;
  }
  return SERIES[i % SERIES.length];
}
function renderSigCheckboxes() {
  const q = ($("sigFilter").value || "").trim().toLowerCase();
  let shown = q ? sigAllSignals.filter((s) => s.key.toLowerCase().includes(q)) : sigAllSignals.slice();
  // Pinned to the top of the list too, so the list mirrors the column order.
  shown = shown.filter((s) => sigPinned.has(s.key)).concat(shown.filter((s) => !sigPinned.has(s.key)));
  $("sigList").innerHTML = shown.map((s) => {
    const k = escAttr(s.key), pinned = sigPinned.has(s.key);
    return `<div class="sig-item">
      <input type="checkbox" data-key="${k}" ${sigSelected.has(s.key) ? "checked" : ""} onchange="toggleSig('${k}')"/>
      <span class="sig-swatch" style="background:${sigColorOf(s.key)}"></span>
      <span class="sig-item-name" onclick="toggleSig('${k}')">${k}${s.unit ? " (" + escAttr(s.unit) + ")" : ""}</span>
      <button class="pin${pinned ? " on" : ""}" title="${pinned ? "Unpin" : "Pin to the front of every view"}"
        onclick="togglePin('${k}')">${UI.ico("star")}</button></div>`;
  }).join("") || `<div class="muted-line">${q ? `No signal matches “${escAttr(q)}”.` : "No DBC loaded."}</div>`;
}
// Pinned signals lead every view — with 30 columns selected, the one you care
// about is otherwise scrolled off the right edge.
const sigPinned = new Set();
function sigOrderedKeys() {
  const sel = [...sigSelected];
  return sel.filter((k) => sigPinned.has(k)).concat(sel.filter((k) => !sigPinned.has(k)));
}
window.togglePin = (key) => {
  sigPinned.has(key) ? sigPinned.delete(key) : sigPinned.add(key);
  sigSelected.add(key);            // pinning something implies wanting to see it
  renderSigCheckboxes();
  sigSelectionChanged();
};
function sigSelectionChanged() {
  if (sigViewMode === "chart") renderChartShells();
  sigAutoScroll = true;
  sigRenderData(true);
}
window.toggleSig = (key) => { sigSelected.has(key) ? sigSelected.delete(key) : sigSelected.add(key); sigSelectionChanged(); };
$("btnSigSelAll").addEventListener("click", () => {
  sigAllSignals.forEach((s) => sigSelected.add(s.key));
  renderSigCheckboxes(); sigSelectionChanged();
});
$("btnSigSelNone").addEventListener("click", () => {
  sigSelected.clear();
  renderSigCheckboxes(); sigSelectionChanged();
});
function renderChartShells() {
  $("charts").innerHTML = sigOrderedKeys().map((k) => `
    <div class="chart-card"><div class="chart-title"><span>${escAttr(k)}</span><span id="cv-${cssId(k)}-v"></span></div>
    <canvas class="chart" id="cv-${cssId(k)}" data-key="${escAttr(k)}" data-color="${sigColorOf(k)}"></canvas></div>`).join("");
}
const cssId = (k) => k.replace(/[^a-zA-Z0-9]/g, "_");

async function pollSignals() {
  if (!sigLogSeries) {
    pollDerived();     // alarms/computed are live-only — not evaluated during log playback
    if (!sigSelected.size) { sigRenderData(true); return; }
    const res = await api("/api/signals/series?keys=" + encodeURIComponent([...sigSelected].join(",")));
    sigLiveSeries = res.series || {};
    sigLiveMaxT = 0;
    for (const k of Object.keys(sigLiveSeries)) {
      const pts = sigLiveSeries[k];
      if (pts && pts.length) sigLiveMaxT = Math.max(sigLiveMaxT, pts[pts.length - 1][0]);
    }
    sigMeta = sigBuildMeta(sigLiveSeries);
    if (!sigWindowSec) sigApplyZoom();
  }
  sigRenderData(true);
}

// Scrubbing and playback drive renders far faster than a table can be rebuilt,
// so the heavy work is throttled while the cheap transport chrome stays at full
// rate. `force` is the 400 ms poll tick, which must never be dropped.
let sigLastRender = 0;
function sigRenderData(force) {
  const now = performance.now();
  if (!force && now - sigLastRender < 80) return;
  sigLastRender = now;
  if (sigViewMode === "table") renderSigTable();
  else if (sigViewMode === "tiles") renderSigTiles();
  else renderSigCharts();
}

// ----- tiles ---------------------------------------------------------------
// A stat tile per signal: name on top, the value at the playhead as the hero,
// min/max over the whole log underneath. Carries the same four states as the
// table (fresh / held / not-seen / out-of-range) so both views read alike.
let sigTilePrev = {};
function renderSigTiles() {
  const host = $("sigTiles"), keys = sigOrderedKeys();
  if (!keys.length) {
    host.innerHTML = `<div class="muted-line">No signals selected.</div>`;
    $("sigTileHint").textContent = "";
    return;
  }
  const series = sigActiveSeries();
  const [, t1] = sigWindowBounds();
  const at = sigAnchorT(t1);
  let held = 0, oor = 0;
  host.innerHTML = `<div class="tile-grid">${keys.map((k) => {
    const m = sigMeta[k] || {}, pts = series[k] || [];
    const idx = sigIndexAt(pts, at);
    const swatch = `<span class="sig-swatch" style="background:${sigColorOf(k)}"></span>`;
    const name = `<div class="sig-tile-name">${swatch}<span title="${escAttr(k)}">${escAttr(k)}</span>` +
      `${sigPinned.has(k) ? `<span class="pin on pin-end">${UI.ico("star")}</span>` : ""}</div>`;
    if (idx < 0) {
      return `<div class="sig-tile unseen">${name}<div class="sig-tile-val">not seen yet</div>
        <div class="sig-tile-foot"><span>—</span><span>—</span></div></div>`;
    }
    const v = pts[idx][1], dec = m.decimals ?? 2;
    const stale = (at - pts[idx][0]) > (m.staleAfter || 1);
    const bad = (m.dbcMin != null && v < m.dbcMin) || (m.dbcMax != null && v > m.dbcMax);
    const changed = sigTilePrev[k] !== undefined && sigTilePrev[k] !== v;
    sigTilePrev[k] = v;
    if (stale) held++;
    if (bad) oor++;
    const cls = ["sig-tile", stale ? "held" : "", bad ? "oor" : "", changed && !stale ? "changed" : ""].filter(Boolean).join(" ");
    const tip = stale ? ' title="held — this message stopped arriving"' : (bad ? ' title="outside the range this DBC declares"' : "");
    return `<div class="${cls}"${tip}>${name}
      <div class="sig-tile-val">${v.toFixed(dec)}${m.unit ? `<span class="u">${escAttr(m.unit)}</span>` : ""}</div>
      <div class="sig-tile-foot"><span>min ${m.min.toFixed(dec)}</span><span>max ${m.max.toFixed(dec)}</span></div></div>`;
  }).join("")}</div>`;
  $("sigTileHint").innerHTML = `<span class="sig-legend"><span>${keys.length} signals</span>` +
    (held ? `<span style="opacity:.6">${held} held</span>` : "") +
    (oor ? `<span class="sum-bad">${oor} outside DBC range</span>` : "") +
    `<span>at t=${at.toFixed(2)}s</span></span>`;
}

function renderSigCharts() {
  if (!sigSelected.size) return;
  const series = sigActiveSeries();
  const [t0, t1] = sigWindowBounds();
  for (const key of sigSelected) {
    const pts = series[key] || [];
    // Carry one sample either side of the window so the trace spans the full
    // width instead of stopping short at the first/last in-window sample.
    let i0 = sigIndexAt(pts, t0); i0 = i0 < 0 ? 0 : i0;
    const iEnd = sigIndexAt(pts, t1);
    const slice = iEnd < 0 ? [] : pts.slice(i0, Math.min(pts.length - 1, iEnd + 1) + 1);
    drawChart(key, slice, t0, t1);
  }
}

// ----- the time x signal matrix -------------------------------------------
// Rows are built lazily for the visible window only: each column keeps a
// forward cursor into its own already-sorted series, so cost is (rows x
// columns) regardless of how long the log is. Nothing is materialised.
function sigBuildRows(keys, t0, t1, grid, changesOnly) {
  const series = sigActiveSeries();
  const cols = keys.map((k) => ({ pts: series[k] || [], meta: sigMeta[k] || {} }));
  const anchor = sigAnchorT(t1);                     // guarantees an exact playhead row
  const cursor = new Array(cols.length).fill(-2);    // -2 = not yet located
  const prev = new Array(cols.length).fill(undefined);
  const rows = [];
  const kStart = Math.ceil((t0 - anchor) / grid), kEnd = Math.floor((t1 - anchor) / grid);
  for (let k = kStart; k <= kEnd; k++) {
    const t = anchor + k * grid;
    if (t < 0) continue;                              // before the log starts
    const cells = [];
    let anyChange = false;
    for (let c = 0; c < cols.length; c++) {
      const { pts, meta } = cols[c];
      let i = cursor[c];
      if (i === -2 || i < 0) i = sigIndexAt(pts, t);
      else while (i + 1 < pts.length && pts[i + 1][0] <= t) i++;
      cursor[c] = i;
      if (i < 0) { cells.push({ s: "none" }); continue; }   // signal not seen yet
      const v = pts[i][1];
      const stale = (t - pts[i][0]) > (meta.staleAfter || 1);
      const changed = prev[c] !== undefined && v !== prev[c];
      if (changed) anyChange = true;
      prev[c] = v;
      cells.push({ v, s: stale ? "stale" : "fresh", ch: changed });
    }
    rows.push({ t, cells, anyChange });
  }
  return changesOnly ? rows.filter((r, i) => i === 0 || r.anyChange) : rows;
}

function renderSigTable() {
  const wrap = $("sigTableWrap"), keys = sigOrderedKeys();
  if (!keys.length) {
    wrap.innerHTML = `<div class="panel-body muted-line m0">No signals selected.</div>`;
    $("sigTableHint").textContent = "";
    return;
  }
  const [t0, t1] = sigWindowBounds();
  const span = Math.max(t1 - t0, 1e-6);
  // Never build more than SIG_RAW_ROWS: coarsen the interval instead, and say so.
  const grid = span / sigRowBudget(span);
  const anchor = sigAnchorT(t1);
  const changesOnly = $("sigChangesOnly").checked;
  const rows = sigBuildRows(keys, t0, t1, grid, changesOnly);

  let list = rows, clipped = 0;
  if (rows.length > SIG_MAX_ROWS) {
    let pi = 0, best = Infinity;
    for (let i = 0; i < rows.length; i++) {
      const d = Math.abs(rows[i].t - anchor);
      if (d < best) { best = d; pi = i; }
    }
    const s = Math.max(0, Math.min(rows.length - SIG_MAX_ROWS, pi - (SIG_MAX_ROWS >> 1)));
    list = rows.slice(s, s + SIG_MAX_ROWS);
    clipped = rows.length - list.length;
  }

  const head = `<tr><th class="t-col">t (s)</th>${keys.map((k) => {
    const m = sigMeta[k] || {}, short = k.split(".").slice(-1)[0];
    return `<th title="${escAttr(k)}">${sigPinned.has(k) ? `<span class="pin on">${UI.ico("star")}</span> ` : ""}` +
      `${escAttr(short)}${m.unit ? ` <span style="opacity:.6">${escAttr(m.unit)}</span>` : ""}</th>`;
  }).join("")}</tr>`;

  const body = list.map((r) => {
    const isHead = Math.abs(r.t - anchor) < grid / 2;
    const tds = r.cells.map((c, ci) => {
      if (c.s === "none") return `<td class="c-none" title="not seen yet in this log">—</td>`;
      const dec = (sigMeta[keys[ci]] || {}).decimals ?? 2;
      if (c.ch) return `<td class="c-changed">${c.v.toFixed(dec)}</td>`;
      if (c.s === "stale") return `<td class="c-stale" title="held — this message stopped arriving">${c.v.toFixed(dec)}</td>`;
      return `<td>${c.v.toFixed(dec)}</td>`;
    }).join("");
    return `<tr class="${isHead ? "row-head" : ""}" data-t="${r.t}"><td class="t-col">${r.t.toFixed(3)}</td>${tds}</tr>`;
  }).join("");

  wrap.innerHTML = `<table class="sig-table${sigLogSeries ? " seekable" : ""}">` +
    `<thead>${head}</thead><tbody>${body}</tbody></table>`;
  $("sigTableHint").innerHTML = `<span class="sig-legend"><span><i style="background:var(--accent-soft)"></i>changed</span>` +
    `<span style="opacity:.55;font-style:italic">held</span><span class="dim-note">— not seen</span>` +
    `<span>${list.length} row${list.length === 1 ? "" : "s"} @ ${fmtInterval(grid)}${clipped ? ` (+${clipped} off-screen)` : ""}</span></span>`;

  // Follow the anchor row while playing or right after a seek; when paused and
  // idle, leave the scroll alone so inspecting a row isn't yanked away.
  if (sigAutoScroll || sigPlaying || !sigLogSeries) {
    sigCentreOnAnchor(wrap);
    // The first render of a freshly shown panel has no layout yet, so scrollTop
    // silently no-ops — retry once the frame has been laid out.
    requestAnimationFrame(() => sigCentreOnAnchor(wrap));
    sigAutoScroll = false;
  }
}
function sigCentreOnAnchor(wrap) {
  const hd = wrap.querySelector("tr.row-head");
  if (hd && wrap.clientHeight) wrap.scrollTop = Math.max(0, hd.offsetTop - wrap.clientHeight / 2);
}
// Row budget for a window: the requested grid, capped so a huge window can't
// build an unbounded matrix.
function sigRowBudget(span) {
  return Math.max(1, Math.min(SIG_RAW_ROWS, Math.ceil(span / Math.max(sigGridSec, 1e-6))));
}
const fmtInterval = (s) => (s >= 1 ? s.toFixed(2) + " s" : (s * 1000).toFixed(s * 1000 >= 10 ? 0 : 1) + " ms");

// ----- log playback: upload a log, decode it against the loaded DBC, scrub it
$("btnSigLogUpload").addEventListener("click", () => $("sigLogFile").click());
$("sigLogFile").addEventListener("change", async (e) => {
  const file = e.target.files[0]; if (!file) return;
  setStatus(`Uploading ${file.name}…`);
  const up = await apiUpload("/api/upload", file);
  if (!up || !up.ok) { setStatus(`Log upload failed: ${(up && up.error) || "unknown error"}`); return; }
  const r = await POST("/api/log/signals", { path: up.path });
  if (!r.ok) { setStatus(`Could not decode log: ${r.error}`); return; }

  sigLogSeries = r.series; sigLogName = file.name;
  sigLogCoverage = { unknown_ids: r.unknown_ids || [], decode_errors: r.decode_errors || [] };
  const unknownFrames = sigLogCoverage.unknown_ids.reduce((n, u) => n + u.count, 0);
  const errorFrames = sigLogCoverage.decode_errors.reduce((n, u) => n + u.count, 0);
  $("sigStatus").textContent = `${file.name} — ${r.frames_decoded}/${r.frames_seen} frames decoded (playback, not live)`;
  $("btnSigLogBack").classList.remove("hidden");
  sigRenderCoverage(unknownFrames, errorFrames);

  // Spread (Math.max(...pts)) overflows the call stack on a large log — walk it.
  sigPlaybackMaxT = 0;
  for (const pts of Object.values(sigLogSeries))
    if (pts.length) sigPlaybackMaxT = Math.max(sigPlaybackMaxT, pts[pts.length - 1][0]);

  sigMeta = sigBuildMeta(sigLogSeries);        // also sets sigBaseGrid
  sigBaseWindow = Math.min(20, Math.max(2, sigPlaybackMaxT * 0.05)) || 5;
  sigZoomExp = 0;
  sigApplyZoom();
  sigPlaybackT = Math.min(sigWindowSec / 2, sigPlaybackMaxT);
  sigEnsureScrubRange(true);
  $("sigPlaybackBar").hidden = false;
  $("sigExportWrap").classList.remove("hidden");
  sigApplyPlaybackGating();
  renderSigSummary();
  sigAutoScroll = true;
  sigUpdatePlaybackLabel();
  sigRenderOverview();
  sigRenderData(true);
});
$("btnSigLogBack").addEventListener("click", () => { sigResetLogMode(); refreshSigList(); });

// ----- signal summary: the fast DBC verdict --------------------------------
// Constant-when-it-should-vary, a max sitting exactly on a full-scale boundary,
// or a value outside the DBC's own declared min/max are the three cheapest
// tells for a wrong start bit, length, scale or signedness.
function sigSummaryRows() {
  return Object.keys(sigMeta).sort().map((key) => {
    const m = sigMeta[key];
    const constant = !(m.max > m.min);
    const belowMin = m.dbcMin != null && m.min < m.dbcMin;
    const aboveMax = m.dbcMax != null && m.max > m.dbcMax;
    const fullScale = SIG_FULL_SCALE.includes(m.max);
    const flags = [];
    if (belowMin || aboveMax) flags.push({ cls: "sum-bad", text: `outside DBC [${m.dbcMin ?? "−∞"}, ${m.dbcMax ?? "∞"}]` });
    if (constant) flags.push({ cls: "sum-warn", text: "constant" });
    if (fullScale && !constant) flags.push({ cls: "sum-warn", text: "max at full scale" });
    return { key, m, constant, bad: belowMin || aboveMax, flags };
  });
}
function renderSigSummary() {
  const rows = sigSummaryRows();
  if (!rows.length) { $("sigSummaryPanel").hidden = true; return; }
  $("sigSummaryPanel").hidden = false;
  const bad = rows.filter((r) => r.bad).length, con = rows.filter((r) => r.constant).length;
  $("sigSummaryFlags").innerHTML =
    (bad ? `<span class="sum-bad">${bad} outside DBC range</span> · ` : "") +
    (con ? `<span class="sum-warn">${con} constant</span> · ` : "") + `${rows.length} signals`;
  $("sigSummaryBody").innerHTML = `<table class="data-table mono">
    <thead><tr><th>Signal</th><th>State</th><th>Min</th><th>Max</th>
      <th title="Max − min. 0 means the signal never moved.">Range</th>
      <th title="How many different values the signal took. 1 means it never changed.">Unique</th>
      <th>Unit</th><th>Period</th><th>Samples</th><th>Notes</th></tr></thead><tbody>${
    rows.map((r) => {
      const m = r.m, d = m.decimals ?? 2;
      return `<tr><td title="${escAttr(r.key)}">${escAttr(r.key)}</td>
        <td class="${r.constant ? "sum-warn" : ""}">${r.constant ? "CONST" : "varies"}</td>
        <td class="${m.dbcMin != null && m.min < m.dbcMin ? "sum-bad" : ""}">${m.min.toFixed(d)}</td>
        <td class="${m.dbcMax != null && m.max > m.dbcMax ? "sum-bad" : ""}">${m.max.toFixed(d)}</td>
        <td class="${r.constant ? "sum-warn" : ""}">${(m.max - m.min).toFixed(d)}</td>
        <td>${m.distinct > 64 ? "64+" : m.distinct}</td><td>${escAttr(m.unit)}</td>
        <td>${m.period ? fmtInterval(m.period) : "—"}</td><td>${m.count}</td>
        <td>${r.flags.map((f) => `<span class="${f.cls}">${f.text}</span>`).join(", ")}</td></tr>`;
    }).join("")}</tbody></table>`;
}
$("btnSigSummaryToggle").addEventListener("click", () => {
  const b = $("sigSummaryBody"), hide = b.classList.toggle("hidden");
  $("btnSigSummaryToggle").textContent = hide ? "Show" : "Hide";
});

// ----- Table / Tiles / Chart toggle ----------------------------------------
function sigSetViewMode(mode) {
  sigViewMode = mode;
  document.querySelectorAll("#sigViewToggle .seg").forEach((b) => b.classList.toggle("active", b.dataset.mode === mode));
  $("sigChartPanel").hidden = mode !== "chart";
  $("sigTablePanel").hidden = mode !== "table";
  $("sigTilePanel").hidden = mode !== "tiles";
  if (mode === "chart") renderChartShells();
  if (mode === "tiles") sigTilePrev = {};      // no phantom "changed" borders on entry
  sigAutoScroll = true;
  sigUpdatePlaybackLabel();
  sigRenderData(true);
}
document.querySelectorAll("#sigViewToggle .seg").forEach((b) =>
  b.addEventListener("click", () => sigSetViewMode(b.dataset.mode)));
$("sigChangesOnly").addEventListener("change", () => { sigAutoScroll = true; sigRenderData(true); });

// ----- fold the signal list -------------------------------------------------
function sigSetFolded(folded) {
  $("sigGrid").classList.toggle("sig-folded", folded);
  const b = $("btnSigFold");
  // Spelled out, and highlighted while folded — this button IS the way back
  // once the list (and the fold button in its header) is gone.
  b.innerHTML = folded ? `${ICONS.chevronRight}<span>Show signals</span>` : `${ICONS.chevronLeft}<span>Hide signals</span>`;
  b.title = folded ? "Bring the signal list back" : "Hide the signal list to give the data more width";
  b.classList.toggle("active", folded);
  sigRenderData(true);
}
$("btnSigFold").addEventListener("click", () => sigSetFolded(!$("sigGrid").classList.contains("sig-folded")));
$("btnSigFoldHead").addEventListener("click", () => sigSetFolded(true));

// A real vehicle DBC runs to hundreds of signals — scrolling to find one is the
// slowest part of picking what to look at.
$("sigFilter").addEventListener("input", renderSigCheckboxes);

// Computed channels and alarms are evaluated on the live tap only, and they
// reference signal keys that don't exist without a DBC — in either case the
// panel is dead weight, so it's removed rather than shown inert. Two callers
// (DBC load, playback enter/exit) share this one rule.
function sigApplyPlaybackGating() {
  $("sigCompAlarmPanel").hidden = !!sigLogSeries || !sigAllSignals.length;
}

function sigRenderCoverage(unknownFrames, errorFrames) {
  const c = sigLogCoverage;
  $("sigCoverageBody").classList.add("hidden");            // collapsed by default on every fresh upload
  $("btnSigCoverageToggle").textContent = "Show breakdown";
  if (!c.unknown_ids.length && !c.decode_errors.length) { $("sigCoveragePanel").hidden = true; return; }
  $("sigCoveragePanel").hidden = false;
  const rows = [];
  if (errorFrames) rows.push(badLine(`${errorFrames} frame(s) from ${c.decode_errors.length} ID(s) are in this DBC but failed to decode — likely a DBC / vehicle mismatch:`));
  rows.push(...c.decode_errors.map((e) => `<div class="err-sub">0x${e.id_hex} × ${e.count} — ${e.error}</div>`));
  if (unknownFrames) rows.push(`<div style="margin:6px 0">${unknownFrames} frame(s) from ${c.unknown_ids.length} ID(s) have no message in this DBC (expected for a partial DBC):</div>`);
  rows.push(`<div style="padding-left:10px;display:flex;flex-wrap:wrap;gap:6px">${
    c.unknown_ids.map((u) => `<span class="tag" style="font-size:11px">0x${u.id_hex} ×${u.count}</span>`).join("")}</div>`);
  $("sigCoverageBody").innerHTML = rows.join("");
}
$("btnSigCoverageToggle").addEventListener("click", () => {
  const body = $("sigCoverageBody"); const show = body.classList.toggle("hidden");
  $("btnSigCoverageToggle").textContent = show ? "Show breakdown" : "Hide breakdown";
});

// ----- transport controls -----
$("btnPbStart").innerHTML = ICONS.skipBack;
$("btnPbEnd").innerHTML = ICONS.skipFwd;
$("btnPbSlower").innerHTML = ICONS.rewind;
$("btnPbFaster").innerHTML = ICONS.fastFwd;
$("btnPbPlay").innerHTML = ICONS.play;
function sigUpdatePlaybackLabel() {
  $("sigPlaybackTime").textContent = `${sigPlaybackT.toFixed(2)}s / ${sigPlaybackMaxT.toFixed(2)}s`;
  $("sigPbWindow").textContent = sigViewMode === "table"
    ? `window ${sigWindowSec.toFixed(1)}s · rows ${fmtInterval(sigGridSec)}`
    : `window ${sigWindowSec.toFixed(1)}s`;
}

// One zoom, two meanings: narrower chart window AND finer table rows.
function sigApplyZoom() {
  const f = Math.pow(2, sigZoomExp);
  sigWindowSec = Math.max(0.05, sigBaseWindow * f);
  sigGridSec = Math.max(0.001, sigBaseGrid * f);
  $("sigPbZoom").textContent = f >= 1 ? `${f}x` : `1/${Math.round(1 / f)}x`;
  sigEnsureScrubRange(true);
  sigUpdatePlaybackLabel();
}
function sigZoomStep(delta) {
  const next = Math.min(SIG_ZOOM_MAX, Math.max(SIG_ZOOM_MIN, sigZoomExp + delta));
  if (next === sigZoomExp) return;
  sigZoomExp = next;
  sigApplyZoom();
  sigAutoScroll = true;
  sigRenderOverview(); sigRenderBand(); sigRenderData(true);
}
$("btnPbZoomIn").addEventListener("click", () => sigZoomStep(-1));
$("btnPbZoomOut").addEventListener("click", () => sigZoomStep(1));

// The scrubber spans a slice of the log, not all of it — otherwise a 30-minute
// capture gives ~2 s per pixel and precise seeking is impossible. The slice
// pages forward instead of recentring on every input, so dragging works.
function sigEnsureScrubRange(force) {
  const span = Math.min(sigPlaybackMaxT || 1, Math.max(sigWindowSec * 8, 0.5));
  if (!force && sigPlaybackT >= sigScrubLo && sigPlaybackT <= sigScrubHi && sigScrubHi > sigScrubLo) return;
  let lo = sigPlaybackT - span / 2, hi = lo + span;
  if (lo < 0) { lo = 0; hi = span; }
  if (hi > sigPlaybackMaxT) { hi = sigPlaybackMaxT; lo = Math.max(0, hi - span); }
  sigScrubLo = lo; sigScrubHi = hi;
  const el = $("sigPbScrub");
  el.min = String(Math.round(lo * 1000));
  el.max = String(Math.round(hi * 1000) || 1);
}
function sigRenderOverview() {
  if (!sigPlaybackMaxT) return;
  const pct = (t) => `${Math.max(0, Math.min(100, (t / sigPlaybackMaxT) * 100))}%`;
  $("sigPbOvRange").style.left = pct(sigScrubLo);
  $("sigPbOvRange").style.width = `${Math.max(0.5, ((sigScrubHi - sigScrubLo) / sigPlaybackMaxT) * 100)}%`;
  $("sigPbOvHead").style.left = pct(sigPlaybackT);
}
// Band behind the scrubber marking the slice the chart/table is actually showing.
function sigRenderBand() {
  const wrapW = $("sigPbScrub").clientWidth || 1;
  const range = sigScrubHi - sigScrubLo;
  const band = $("sigPbBand");
  if (range <= 0) { band.style.width = "0"; return; }
  const [w0, w1] = sigWindowBounds();
  const l = Math.max(0, (w0 - sigScrubLo) / range), r = Math.min(1, (w1 - sigScrubLo) / range);
  band.style.left = `${l * wrapW}px`;
  band.style.width = `${Math.max(2, (r - l) * wrapW)}px`;
}
// `immediate` for one-off actions (click a row, a key, jump to end) — those must
// repaint at once or the table lags the scrubber by up to a poll tick. Dragging
// the scrubber and the play loop stay throttled; that's what the throttle is for.
function sigSeekTo(t, immediate) {
  sigPlaybackT = Math.max(0, Math.min(sigPlaybackMaxT, t));
  sigEnsureScrubRange(false);
  $("sigPbScrub").value = String(Math.round(sigPlaybackT * 1000));
  sigUpdatePlaybackLabel();
  sigRenderOverview();
  sigRenderBand();
  sigAutoScroll = true;
  sigRenderData(!!immediate);
}
$("sigPbScrub").addEventListener("input", () => sigSeekTo((+$("sigPbScrub").value) / 1000));
$("btnPbStart").addEventListener("click", () => sigSeekTo(0, true));
$("btnPbEnd").addEventListener("click", () => sigSeekTo(sigPlaybackMaxT, true));
$("sigPbOverview").addEventListener("click", (e) => {
  if (!sigPlaybackMaxT) return;
  const r = e.currentTarget.getBoundingClientRect();
  // Jumping anywhere in the log recentres the zoomed scrubber on the target.
  sigPlaybackT = Math.max(0, Math.min(sigPlaybackMaxT, ((e.clientX - r.left) / r.width) * sigPlaybackMaxT));
  sigEnsureScrubRange(true);
  sigSeekTo(sigPlaybackT, true);
});
// Ctrl/Shift + wheel zooms time; a plain wheel still scrolls the pane, so the
// table stays navigable (the usual convention rather than a surprise).
["charts", "sigTableWrap"].forEach((id) => {
  $(id).addEventListener("wheel", (e) => {
    if (!e.ctrlKey && !e.shiftKey) return;
    e.preventDefault();
    sigZoomStep(e.deltaY > 0 ? 1 : -1);
  }, { passive: false });
});
function sigSpeedStep(delta) {
  const i = Math.min(SIG_SPEEDS.length - 1, Math.max(0, SIG_SPEEDS.indexOf(sigPlaySpeed) + delta));
  sigPlaySpeed = SIG_SPEEDS[i];
  $("sigPbSpeed").textContent = sigPlaySpeed + "x";
}
$("btnPbSlower").addEventListener("click", () => sigSpeedStep(-1));
$("btnPbFaster").addEventListener("click", () => sigSpeedStep(1));
function sigPlayTick(now) {
  if (!sigPlaying) return;
  if (sigPlayLastTs == null) sigPlayLastTs = now;
  const dt = (now - sigPlayLastTs) / 1000;
  sigPlayLastTs = now;
  sigSeekTo(sigPlaybackT + dt * sigPlaySpeed);
  if (sigPlaybackT >= sigPlaybackMaxT) { sigPlaying = false; $("btnPbPlay").innerHTML = ICONS.play; sigPlayRAF = null; return; }
  sigPlayRAF = requestAnimationFrame(sigPlayTick);
}
function sigTogglePlay(force) {
  if (!sigLogSeries) return;
  sigPlaying = force === undefined ? !sigPlaying : force;
  $("btnPbPlay").innerHTML = sigPlaying ? ICONS.pause : ICONS.play;
  if (sigPlaying) {
    if (sigPlaybackT >= sigPlaybackMaxT) sigPlaybackT = 0;   // replay from the top if already at the end
    sigPlayLastTs = null;
    sigPlayRAF = requestAnimationFrame(sigPlayTick);
  } else if (sigPlayRAF) { cancelAnimationFrame(sigPlayRAF); sigPlayRAF = null; }
}
$("btnPbPlay").addEventListener("click", () => sigTogglePlay());

// Keyboard transport — drive playback while reading the table, without
// round-tripping to the mouse. Inert unless the Signal Viewer is open on a log,
// and never steals keys from a text field (the signal filter, alarm inputs…).
document.addEventListener("keydown", (e) => {
  if (state.view !== "signals" || !sigLogSeries) return;
  const t = e.target;
  if (t && (/^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName) || t.isContentEditable)) return;
  if (e.ctrlKey || e.altKey || e.metaKey) return;
  const step = e.shiftKey ? sigGridSec * 10 : sigGridSec;   // Shift = coarse step
  switch (e.key) {
    case " ": case "Spacebar": sigTogglePlay(); break;
    case "ArrowLeft": sigTogglePlay(false); sigSeekTo(sigPlaybackT - step, true); break;
    case "ArrowRight": sigTogglePlay(false); sigSeekTo(sigPlaybackT + step, true); break;
    case "Home": sigSeekTo(0, true); break;
    case "End": sigSeekTo(sigPlaybackMaxT, true); break;
    case "+": case "=": sigZoomStep(-1); break;
    case "-": case "_": sigZoomStep(1); break;
    default: return;
  }
  e.preventDefault();      // only after a key we actually handled
});

// Click any row to put the playhead on it — you already scan the table to find
// the interesting moment; this saves hunting for it on the scrubber.
$("sigTableWrap").addEventListener("click", (e) => {
  if (!sigLogSeries) return;
  const tr = e.target.closest("tr[data-t]");
  if (!tr) return;
  sigTogglePlay(false);    // clicking a row means "stop here and look"
  sigSeekTo(+tr.dataset.t, true);
});

// ----- export --------------------------------------------------------------
// Both exports share one builder so the file always matches what's on screen
// (same selection, same interval, same changes-only filter).
const SIG_EXPORT_MAX = 50000;
function sigExportPayload() {
  const keys = sigOrderedKeys();
  if (!keys.length) { setStatus("Select at least one signal to export."); return null; }
  const whole = $("sigExportScope").value === "all";
  let t0, t1, grid;
  if (whole) {
    t0 = 0; t1 = sigLogSeries ? sigPlaybackMaxT : sigLiveMaxT;
    grid = Math.max(sigBaseGrid, (t1 - t0) / SIG_EXPORT_MAX);
  } else {
    [t0, t1] = sigWindowBounds();
    grid = (t1 - t0) / sigRowBudget(t1 - t0);
  }
  let rows = sigBuildRows(keys, Math.max(0, t0), t1, grid, $("sigChangesOnly").checked);
  const clipped = Math.max(0, rows.length - SIG_EXPORT_MAX);
  if (clipped) rows = rows.slice(0, SIG_EXPORT_MAX);
  return {
    keys, rows, grid, clipped, whole,
    columns: keys.map((k) => ({ key: k, unit: (sigMeta[k] || {}).unit || "", decimals: (sigMeta[k] || {}).decimals ?? 2 })),
    summary: sigSummaryRows().map((r) => ({
      key: r.key, state: r.constant ? "CONST" : "varies", min: r.m.min, max: r.m.max,
      range: +(r.m.max - r.m.min).toFixed(6), distinct: r.m.distinct, unit: r.m.unit,
      period_ms: r.m.period ? +(r.m.period * 1000).toFixed(2) : null,
      samples: r.m.count, dbc_min: r.m.dbcMin, dbc_max: r.m.dbcMax,
      notes: r.flags.map((f) => f.text).join("; "),
    })),
    source: sigLogName || "live capture",
  };
}
function sigDownload(blob, ext) {
  const now = new Date(), pad = (n) => String(n).padStart(2, "0");
  const ts = `${pad(now.getDate())}${pad(now.getMonth() + 1)}${String(now.getFullYear()).slice(-2)}_${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`;
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob); a.download = `signals_${ts}.${ext}`; a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 4000);
}
const csvCell = (s) => (/[",\n]/.test(String(s)) ? `"${String(s).replace(/"/g, '""')}"` : String(s));
$("btnSigExportCsv").addEventListener("click", () => {
  const p = sigExportPayload(); if (!p) return;
  const L = [];
  L.push(`# uCANdo signal export — ${p.source}`);
  L.push(`# interval ${fmtInterval(p.grid)} · ${p.rows.length} rows · ${p.whole ? "whole log" : "visible window"}`);
  L.push(`# CSV carries plain values; use Export Excel to keep the held / changed colouring.`);
  if (p.clipped) L.push(`# NOTE: truncated — ${p.clipped} further row(s) not exported.`);
  L.push("", "SUMMARY");
  L.push(["Signal", "State", "Min", "Max", "Range", "Unique", "Unit", "Period (ms)", "Samples", "DBC Min", "DBC Max", "Notes"].join(","));
  p.summary.forEach((s) => L.push([s.key, s.state, s.min, s.max, s.range, s.distinct, s.unit, s.period_ms ?? "", s.samples, s.dbc_min ?? "", s.dbc_max ?? "", s.notes].map(csvCell).join(",")));
  L.push("", "DATA");
  L.push(["t (s)", ...p.columns.map((c) => c.unit ? `${c.key} (${c.unit})` : c.key)].map(csvCell).join(","));
  p.rows.forEach((r) => L.push([r.t.toFixed(3), ...r.cells.map((c, i) => c.s === "none" ? "" : c.v.toFixed(p.columns[i].decimals))].join(",")));
  sigDownload(new Blob([L.join("\n")], { type: "text/csv;charset=utf-8" }), "csv");
  setStatus(`Exported ${p.rows.length} rows x ${p.keys.length} signals to CSV${p.clipped ? ` (truncated, ${p.clipped} rows dropped)` : ""}`);
});
$("btnSigExportXlsx").addEventListener("click", async () => {
  const p = sigExportPayload(); if (!p) return;
  setStatus("Building Excel workbook…");
  const res = await fetch("/api/signals/export-xlsx", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      source: p.source, interval_ms: +(p.grid * 1000).toFixed(3), truncated: p.clipped,
      columns: p.columns, summary: p.summary,
      rows: p.rows.map((r) => ({ t: +r.t.toFixed(3), cells: r.cells.map((c) => c.s === "none" ? null : { v: c.v, s: c.s, ch: !!c.ch }) })),
    }),
  });
  if (!res.ok) {
    let msg = `HTTP ${res.status}`;
    try { msg = (await res.json()).error || msg; } catch (_) { /* non-JSON body */ }
    setStatus(`Excel export failed: ${msg}`);
    return;
  }
  sigDownload(await res.blob(), "xlsx");
  setStatus(`Exported ${p.rows.length} rows x ${p.keys.length} signals to Excel${p.clipped ? ` (truncated, ${p.clipped} rows dropped)` : ""}`);
});

// ----- computed signals & alarms -----
let computedDefs = [], alarmDefs = [];
async function pollDerived() {
  const d = await api("/api/signals/derived");
  const active = (d.alarms || []).filter((a) => a.active);
  $("sigAlarmBanner").innerHTML = active.length
    ? `<span class="tag bad">${active.map((a) => a.name).join(", ")} in alarm</span>` : "";
  $("almList").innerHTML = (d.alarms || []).map((a, i) =>
    `<span class="tag ${a.active ? "bad" : ""}">
      ${a.name} [${a.min ?? "−∞"},${a.max ?? "∞"}] <a href="#" class="tag-x" aria-label="Remove alarm" onclick="delAlarm(${i});return false">${ICONS.close}</a></span>`).join("") || "None";
}
$("btnCompAdd").addEventListener("click", async () => {
  const name = $("compName").value.trim(), expr = $("compExpr").value.trim();
  if (!name || !expr) return;
  computedDefs.push({ name, expr });
  await POST("/api/signals/computed", { defs: computedDefs });
  $("compName").value = ""; $("compExpr").value = ""; renderCompList();
});
function renderCompList() {
  $("compList").innerHTML = computedDefs.map((c, i) =>
    `<span class="tag info">${c.name} = ${c.expr} <a href="#" class="tag-x" aria-label="Remove" onclick="delComp(${i});return false">${ICONS.close}</a></span>`).join("") || "None";
}
window.delComp = async (i) => { computedDefs.splice(i, 1); await POST("/api/signals/computed", { defs: computedDefs }); renderCompList(); refreshSigList(); };
$("btnAlmAdd").addEventListener("click", async () => {
  const key = $("almKey").value.trim();
  if (!key) return;
  const min = $("almMin").value.trim(), max = $("almMax").value.trim();
  alarmDefs.push({ name: key, key, min: min === "" ? null : +min, max: max === "" ? null : +max });
  await POST("/api/signals/alarms", { defs: alarmDefs });
  $("almKey").value = ""; $("almMin").value = ""; $("almMax").value = ""; pollDerived();
});
window.delAlarm = async (i) => { alarmDefs.splice(i, 1); await POST("/api/signals/alarms", { defs: alarmDefs }); pollDerived(); };
function drawChart(key, pts, winT0, winT1) {
  const cv = $("cv-" + cssId(key)); if (!cv) return;
  const dpr = window.devicePixelRatio || 1, w = cv.clientWidth, h = cv.clientHeight;
  cv.width = w * dpr; cv.height = h * dpr;
  const ctx = cv.getContext("2d"); ctx.scale(dpr, dpr); ctx.clearRect(0, 0, w, h);
  const meta = sigMeta[key] || {}, dec = meta.decimals ?? 2;
  const vEl = $("cv-" + cssId(key) + "-v");

  // X spans the requested window, not the data extent, so the playhead line
  // stays put and sparse data doesn't silently rescale the time axis.
  let x0 = winT0, x1 = winT1;
  if (x0 == null || x1 == null || !(x1 > x0)) {
    if (!pts.length) { if (vEl) vEl.textContent = "—"; return; }
    x0 = pts[0][0]; x1 = pts[pts.length - 1][0];
  }
  const sx = (t) => ((t - x0) / ((x1 - x0) || 1)) * (w - 8) + 4;

  // Y autoscales, but a signal that is CONSTANT across the window must not
  // collapse onto the floor — padding it draws the trace mid-height so
  // "flat at 89" reads differently from "at zero" or "broken".
  let y0 = Infinity, y1 = -Infinity;
  for (const p of pts) { if (p[1] < y0) y0 = p[1]; if (p[1] > y1) y1 = p[1]; }
  const constant = pts.length > 0 && !(y1 > y0);
  if (!pts.length) { y0 = 0; y1 = 1; }
  else if (constant) { const pad = Math.max(Math.abs(y0) * 0.05, 0.5); y0 -= pad; y1 += pad; }
  const sy = (v) => h - 6 - ((v - y0) / ((y1 - y0) || 1)) * (h - 12);

  // Playhead: centred in log playback, at the right edge when live.
  const headT = sigLogSeries ? (x0 + x1) / 2 : x1;
  ctx.save();
  ctx.strokeStyle = tok("--accent"); ctx.globalAlpha = 0.5; ctx.lineWidth = 1; ctx.setLineDash([3, 3]);
  ctx.beginPath(); ctx.moveTo(sx(headT), 2); ctx.lineTo(sx(headT), h - 2); ctx.stroke();
  ctx.restore();

  if (!pts.length) { if (vEl) vEl.textContent = "—"; return; }

  ctx.strokeStyle = cv.dataset.color;
  ctx.lineWidth = 1.5;
  if (constant) { ctx.save(); ctx.setLineDash([5, 3]); ctx.globalAlpha = 0.85; }
  ctx.beginPath();
  if (pts.length === 1) {
    const y = sy(pts[0][1]); ctx.moveTo(sx(x0), y); ctx.lineTo(sx(x1), y);
  } else {
    // Min/max per pixel column — a 50k-point window still shows its spikes
    // instead of being decimated away by naive index striding.
    let px = null, lo = 0, hi = 0, started = false;
    const flush = () => {
      if (!started) { ctx.moveTo(px, sy(lo)); started = true; } else ctx.lineTo(px, sy(lo));
      if (hi !== lo) ctx.lineTo(px, sy(hi));
    };
    for (const p of pts) {
      const X = Math.round(sx(p[0])), v = p[1];
      if (px === null) { px = X; lo = hi = v; continue; }
      if (X === px) { if (v < lo) lo = v; if (v > hi) hi = v; continue; }
      flush(); px = X; lo = hi = v;
    }
    if (px !== null) flush();
  }
  ctx.stroke();
  if (constant) ctx.restore();

  if (vEl) {
    const src = sigActiveSeries()[key] || [];
    const i = sigIndexAt(src, headT);
    const cur = i < 0 ? null : src[i][1];
    const stale = i >= 0 && (headT - src[i][0]) > (meta.staleAfter || 1);
    vEl.innerHTML = cur == null
      ? `<span class="dim-note">Not seen yet</span>`
      : `<span${stale ? ' style="opacity:.55;font-style:italic" title="held — this message stopped arriving"' : ""}>${cur.toFixed(dec)}${meta.unit ? " " + escAttr(meta.unit) : ""}</span>` +
        (constant ? ` <span class="sum-warn" style="font-size:11px">flat</span>` : "");
  }
}

// -------------------------------------------------------------- TX Scheduler
$("btnTxAdd").addEventListener("click", async () => {
  const id = parseInt($("txId").value, 16);
  if (isNaN(id)) return void setStatus("Invalid TX ID");
  await POST("/api/tx/add", { id, data: $("txData").value, cycle_ms: +$("txCycle").value, mode: $("txMode").value });
  pollTx();
});
// One-click standard OBD-II Mode-01 request rows (added idle; press Start to transmit).
const OBD_PRESET = [
  ["02 01 0C 00 00 00 00 00", "OBD RPM"], ["02 01 0D 00 00 00 00 00", "OBD Speed"],
  ["02 01 05 00 00 00 00 00", "OBD Coolant"], ["02 01 11 00 00 00 00 00", "OBD Throttle"],
  ["02 01 04 00 00 00 00 00", "OBD Load"],
];
$("btnTxObdPreset").addEventListener("click", async () => {
  for (const [data, name] of OBD_PRESET)
    await POST("/api/tx/add", { id: 0x7DF, data, cycle_ms: 300, mode: "cyclic", name });
  pollTx();
  setStatus("Added 5 OBD-II PID request rows — press Start all to begin polling.");
});

// ----- log folder -----
async function loadLogDir() {
  const r = await api("/api/logger/log-dir");
  if ($("logDir")) $("logDir").value = r.custom ? r.dir : "";
}
$("btnLogDirSave").addEventListener("click", async () => {
  const r = await POST("/api/logger/log-dir", { dir: $("logDir").value.trim() });
  setStatus(r.ok ? "Log folder set → " + r.dir : "Log folder: " + (r.error || "?"));
});
$("btnLogDirReset").addEventListener("click", async () => {
  $("logDir").value = "";
  const r = await POST("/api/logger/log-dir", { dir: "" });
  setStatus("Log folder reset → " + r.dir);
});
$("btnTxStart").addEventListener("click", () => POST("/api/tx/start").then((r) => !r.ok && setStatus(r.error)));
$("btnTxStop").addEventListener("click", () => POST("/api/tx/stop"));
window.txToggle = (uid, on) => POST("/api/tx/update", { uid, patch: { enabled: on } });
window.txRemove = (uid) => fetch("/api/tx/remove?uid=" + uid, { method: "POST" }).then(pollTx);
window.txOnce = (uid) => fetch("/api/tx/send-once?uid=" + uid, { method: "POST" });
async function pollTx() {
  const t = await api("/api/tx");
  $("txState").textContent = t.running ? "Running" : "Stopped";
  $("txState").className = "tag" + (t.running ? " ok" : "");
  $("txCount").textContent = t.entries.length ? String(t.entries.length) : "";
  $("txTable").querySelector("tbody").innerHTML = t.entries.map((e) => `
    <tr><td class="cell-center"><input type="checkbox" ${e.enabled ? "checked" : ""} aria-label="Enabled" onchange="txToggle(${e.uid},this.checked)"/></td>
    <td>${UI.esc(e.name)}</td><td class="mono">0x${e.id_hex}</td><td class="mono">${e.data}</td>
    <td class="num">${e.cycle_ms} ms</td><td>${cap(e.mode)}</td><td class="num">${e.count.toLocaleString()}</td>
    <td class="row-actions"><button type="button" class="btn-mini" onclick="txOnce(${e.uid})">Send once</button>
        <button type="button" class="btn-mini" onclick="txRemove(${e.uid})">Remove</button></td></tr>`).join("")
    || `<tr class="empty-row"><td colspan="8">No frames yet.</td></tr>`;
}

// ----------------------------------------------------------- Protocol Decoder
function interp(f) {
  if (f.protocol === "OBD-II") return `${f.mode_name}${f.pid_name ? " · " + f.pid_name : ""}${f.value ? " = " + f.value : ""}`;
  if (f.protocol === "UDS") return `${f.type} · ${f.service}${f.nrc_name ? " · NRC " + f.nrc_name : ""}${f.did ? " · DID " + f.did : ""}`;
  if (f.protocol === "J1939") return `PGN ${f.pgn_hex}${f.pgn_name ? " " + f.pgn_name : ""} · prio ${f.priority} · src ${f.source}`;
  if (f.protocol === "ISO-TP") return `${f.type}${f.total_len ? " · " + f.total_len + "B" : ""}`;
  return f.data || "";
}
$("btnDecode").addEventListener("click", async () => {
  const id = parseInt($("decId").value, 16); if (isNaN(id)) return void ($("decResult").textContent = "bad ID");
  const r = await POST("/api/decode/frame", { id, data: $("decData").value, is_extended: $("decExt").checked });
  $("decResult").textContent = r.ok ? `${r.result.protocol}: ${interp(r.result)}` : r.error;
});
async function pollDecode() {
  const r = await api("/api/decode/live");
  const filt = $("protoFilter").value;
  const rows = r.frames.filter((f) => !filt || f.protocol === filt);
  $("decTable").querySelector("tbody").innerHTML = rows.map((f) => `
    <tr><td>${f.ts.toFixed(3)}</td><td>0x${f.id_hex}</td><td><span class="tag">${f.protocol}</span></td><td>${interp(f)}</td></tr>`).join("");
}
$("btnDecClear").addEventListener("click", () => POST("/api/decode/clear").then(pollDecode));

// ----------------------------------------------------------------- Dashboard
$("btnDashClear").addEventListener("click", () => POST("/api/dashboard/clear").then(pollDashboard));
const fmtVal = (v) => (Math.abs(v) >= 100 ? v.toFixed(0) : v.toFixed(1));
async function pollDashboard() {
  const d = await api("/api/dashboard");
  const has = d.groups && d.groups.some((g) => g.items.length);
  $("dashEmpty").classList.toggle("hidden", has);
  $("dashBar").classList.toggle("hidden", !has);
  $("dashGroups").innerHTML = (d.groups || []).map((g) => `
    <div class="dash-group">
      <div class="dash-group-title">${g.group} <span class="ui-count">${g.items.length}</span></div>
      <div class="gauge-grid">
        ${g.items.map((it) => `
          <div class="gauge ${it.stale ? "stale" : ""}">
            ${it.pid ? `<span class="gauge-meta">PID ${it.pid}</span>` : ""}
            ${it.spn ? `<span class="gauge-meta">SPN ${it.spn}</span>` : ""}
            <div class="gauge-name">${it.name}</div>
            <div class="gauge-val">${fmtVal(it.value)}<span class="gauge-unit">${it.unit}</span></div>
          </div>`).join("")}
      </div>
    </div>`).join("");
}

// ----------------------------------------------------------------- DTC Codes
$("btnDtcScan").addEventListener("click", () => POST("/api/dtc/scan").then((r) => !r.ok && setStatus(r.error)));
$("btnDtcClearList").addEventListener("click", () => POST("/api/dtc/clear").then(pollDtc));
$("btnDtcClearEcu").addEventListener("click", async () => {
  if (!(await UI.confirm({ title: "Clear trouble codes on the vehicle?",
    text: "This sends OBD-II Mode 04. The ECU erases its stored DTCs and freeze-frame data.",
    action: "Clear codes", tone: "danger" }))) return;
  POST("/api/dtc/clear-ecu").then((r) => setStatus(r.ok ? "Sent Mode 04 clear request" : r.error));
});
async function pollDtc() {
  const d = await api("/api/dtc");
  const n = d.count || 0;
  $("dtcCount").textContent = `${n} code${n === 1 ? "" : "s"}`;
  $("dtcEmpty").classList.toggle("hidden", n > 0);
  $("dtcGroups").innerHTML = (d.groups || []).map((g) => `
    <div class="dash-group">
      <div class="dash-group-title">${g.group} <span class="ui-count">${g.items.length}</span></div>
      ${g.items.map((it) => `
        <div class="dtc-card ${it.stale ? "stale" : ""}">
          <div class="dtc-code">${it.code}</div>
          <div class="dtc-body">
            <div class="dtc-desc">${it.desc || '<span class="dtc-nodesc">No description</span>'}</div>
            ${it.status ? `<div class="dtc-status">${it.status}${it.oc !== undefined ? " · OC " + it.oc : ""}</div>` : ""}
          </div>
          <div class="dtc-seen" title="Times seen">×${it.seen}</div>
        </div>`).join("")}
    </div>`).join("");
}

// ----------------------------------------------------- Hardware setup panel
async function checkDrivers() {
  const { backends } = await api("/api/drivers/status");
  const need = (backends || []).filter((b) => !b.ready && b.remedy);
  const panel = $("driverPanel");
  if (!need.length) { panel.classList.add("hidden"); return; }
  panel.classList.remove("hidden");
  $("driverList").innerHTML = need.map((b) => {
    const r = b.remedy;
    let action = "";
    if (r.type === "pip") action = `<code>${r.command}</code>`;
    else if (r.type === "installer") {
      const dl = b.download || {};
      const pct = dl.total ? Math.round((dl.downloaded / dl.total) * 100) : 0;
      if (dl.state === "downloading") action = `Downloading… ${pct}% <button type="button" class="btn-mini" onclick="driverPoll('${b.hw}')">Refresh</button>`;
      else if (dl.state === "done" || dl.cached) action = `<button type="button" class="btn-mini" onclick="driverLaunch('${b.hw}')">Install now</button>`;
      else action = `<button type="button" class="btn-mini" onclick="driverDownload('${b.hw}')">Download and install (${r.approx_mb || "?"} MB)</button>`;
    }
    return `<div class="driver-row"><b>${b.label}</b> — ${b.detail}
      ${r.note ? `<div class="muted-line">${r.note}</div>` : ""} ${action}</div>`;
  }).join("");
}
window.driverDownload = async (hw) => {
  const r = await POST("/api/drivers/download?hw=" + hw);
  if (r.state === "page" && r.url) { window.open(r.url, "_blank"); return; }
  setStatus(r.reused ? "Installer already downloaded — click Install now" : "Downloading driver kit…");
  checkDrivers();
};
window.driverPoll = checkDrivers;
window.driverLaunch = async (hw) => {
  const r = await POST("/api/drivers/launch?hw=" + hw);
  if (r.open_url) window.open(r.open_url, "_blank");
  setStatus(r.ok ? (r.note || "Installer launched — approve the UAC prompt") : ("Install: " + (r.error || "?")));
};
$("btnDriverRecheck").addEventListener("click", checkDrivers);
checkDrivers();

// ----------------------------------- icons on static action buttons (by id)
const BTN_ICONS = {
  btnPlay: [ICONS.play, "Play"],
  btnStop: [ICONS.stop, "Stop"], btnStep: [ICONS.step, "Step"],
  btnTxStart: [ICONS.play, "Start all"], btnTxStop: [ICONS.stop, "Stop"],
  btnRestbusStart: [ICONS.play, "Start"], btnRestbusStop: [ICONS.stop, "Stop"],
  btnScriptRun: [ICONS.play, "Run script"],
  btnReplayRescan: [ICONS.refresh, "Rescan"], btnReRescan: [ICONS.refresh, "Rescan"],
  btnAutoReRescan: [ICONS.refresh, "Rescan"], btnOemRefresh: [ICONS.refresh, "Refresh"],
  btnRefreshDevs: [ICONS.refresh, "Rescan"], btnDbcToViewer: [ICONS.arrowRight, "Signal viewer"],
  btnReplayUpload: [ICONS.upload, "Upload logs"], btnTvCloud: [ICONS.upload, "Upload cloud log"],
  btnTvDef: [ICONS.upload, "Upload JSON / DBC"], btnTxDbcUpload: [ICONS.upload, "Upload .dbc"],
  btnTxPlaylistAdd: [UI.ico("plus"), "Add to playlist"], btnTxAdd: [UI.ico("plus"), "Add"],
  btnTxObdPreset: [UI.ico("plus"), "OBD PIDs"], btnRuleAdd: [UI.ico("plus"), "Add rule"],
  btnJobAdd: [UI.ico("plus"), "Add job"], btnDtcScan: [ICONS.refresh, "Scan"],
  btnTxScenarioDelete: [UI.ico("trash"), "Delete"],
  btnFdToggleFill: [ICONS.clipboard, "Paste frames"],
  btnDbcImport: [ICONS.upload, "Upload .dbc"], btnDbcExport: [ICONS.download, "Download .dbc"],
  btnSigImport: [ICONS.upload, "Upload .dbc"],
  btnUsageName: [ICONS.edit, "Edit name"],
};
Object.entries(BTN_ICONS).forEach(([id, [ic, label]]) => {
  const el = $(id);
  if (!el) return;
  el.innerHTML = ic + (label ? `<span>${label}</span>` : "");
  el.classList.add("btn-ico");
});

// ===================== Animated idle / empty states ========================
// One self-contained CAN-bus SVG (no GIF, no library) reused across idle pages:
// ECU chip-nodes tapping a differential bus while data frames flow + nodes pulse.
const CAN_BUS_SVG = `<svg class="bus-anim" viewBox="0 0 440 200" role="img" aria-label="CAN bus animation">
  <line class="bus-line" x1="40" y1="112" x2="400" y2="112" stroke="var(--brand)" stroke-width="2.5"/>
  <line class="bus-line" x1="40" y1="120" x2="400" y2="120" stroke="var(--accent)" stroke-width="2.5"/>
  <line class="bus-flow" x1="40" y1="112" x2="400" y2="112" stroke="var(--brand)" stroke-width="2.5"/>
  <line class="bus-flow" x1="40" y1="120" x2="400" y2="120" stroke="var(--accent)" stroke-width="2.5"/>
  <line x1="40" y1="110" x2="40" y2="122" stroke="var(--muted)" stroke-width="2" stroke-linecap="round"/>
  <line x1="400" y1="110" x2="400" y2="122" stroke="var(--muted)" stroke-width="2" stroke-linecap="round"/>
  <line class="tap" x1="90" y1="66" x2="90" y2="112"/><line class="tap" x1="180" y1="120" x2="180" y2="134"/>
  <line class="tap" x1="270" y1="66" x2="270" y2="112"/><line class="tap" x1="360" y1="120" x2="360" y2="134"/>
  <rect class="node-ring" style="animation-delay:0s" x="62" y="30" width="56" height="40" rx="9"/>
  <rect class="ecu" x="66" y="34" width="48" height="32" rx="6"/>
  <rect x="80" y="42" width="20" height="16" rx="3" fill="none" stroke="var(--muted)" stroke-width="1.4"/>
  <line class="ecu-pin" x1="78" y1="66" x2="78" y2="71"/><line class="ecu-pin" x1="90" y1="66" x2="90" y2="71"/><line class="ecu-pin" x1="102" y1="66" x2="102" y2="71"/>
  <rect class="node-ring" style="animation-delay:.8s" x="152" y="130" width="56" height="40" rx="9"/>
  <rect class="ecu" x="156" y="134" width="48" height="32" rx="6"/>
  <rect x="170" y="142" width="20" height="16" rx="3" fill="none" stroke="var(--muted)" stroke-width="1.4"/>
  <line class="ecu-pin" x1="168" y1="129" x2="168" y2="134"/><line class="ecu-pin" x1="180" y1="129" x2="180" y2="134"/><line class="ecu-pin" x1="192" y1="129" x2="192" y2="134"/>
  <rect class="node-ring" style="animation-delay:1.6s" x="242" y="30" width="56" height="40" rx="9"/>
  <rect class="ecu" x="246" y="34" width="48" height="32" rx="6"/>
  <rect x="260" y="42" width="20" height="16" rx="3" fill="none" stroke="var(--muted)" stroke-width="1.4"/>
  <line class="ecu-pin" x1="258" y1="66" x2="258" y2="71"/><line class="ecu-pin" x1="270" y1="66" x2="270" y2="71"/><line class="ecu-pin" x1="282" y1="66" x2="282" y2="71"/>
  <rect class="node-ring" style="animation-delay:2.4s" x="332" y="130" width="56" height="40" rx="9"/>
  <rect class="ecu" x="336" y="134" width="48" height="32" rx="6"/>
  <rect x="350" y="142" width="20" height="16" rx="3" fill="none" stroke="var(--muted)" stroke-width="1.4"/>
  <line class="ecu-pin" x1="348" y1="129" x2="348" y2="134"/><line class="ecu-pin" x1="360" y1="129" x2="360" y2="134"/><line class="ecu-pin" x1="372" y1="129" x2="372" y2="134"/>
  <rect class="pkt" style="animation-delay:0s" x="40" y="111" width="16" height="10" rx="3"/>
  <rect class="pkt" style="animation-delay:.95s" x="40" y="111" width="16" height="10" rx="3"/>
  <rect class="pkt" style="animation-delay:1.9s" x="40" y="111" width="16" height="10" rx="3"/>
</svg>`;

// Live CAN-network hero on <canvas>: glowing differential bus + ECU nodes, with
// data packets streaking node→node (comet trails), arrival ripples that flash the
// destination ECU, over a faint drift of hex CAN-IDs. Pauses when off-screen;
// draws a single static frame under prefers-reduced-motion.
function startHeroCanvas(canvas) {
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("no 2d context");
  // The two bus wires are the brand blue and the accent green (CAN-H / CAN-L);
  // colours are re-read whenever the theme changes, so a light page never
  // keeps a dark page's canvas.
  const tokens = () => {
    const css = getComputedStyle(document.documentElement);
    const pick = (v) => (css.getPropertyValue(v) || "").trim();
    return { acc: pick("--brand"), grn: pick("--accent"), mut: pick("--muted"), txt: pick("--text") };
  };
  let C = tokens();
  UI.onTheme(() => { C = tokens(); });
  const NAMES = ["ENGINE", "BMS", "ABS", "DASH", "GATEWAY", "TPMS", "HVAC", "EPS"];
  const HEX = ["0x0C9", "0x1A4", "0x244", "0x316", "0x5B0", "FF 2C", "3A 90", "0x7DF", "1B C0", "0x18F", "0x202", "0x45A"];
  const BANDS = [-86, 54, -50, 88, -56, 50, -86, 60];   // y-offsets from the bus → 2D scatter
  let W = 0, H = 0, dpr = 1, busY = 0;
  let nodes = [], edges = [], adj = [], packets = [], wires = [], ripples = [], rain = [];
  let raf = null, running = false, last = 0, spawnAcc = 0, hover = -1, reduce = false;
  try { reduce = matchMedia("(prefers-reduced-motion: reduce)").matches; } catch (e) {}

  const hexA = (hex, a) => {
    let h = hex.replace("#", ""); if (h.length === 3) h = h.replace(/(.)/g, "$1$1");
    const n = parseInt(h, 16); return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
  };
  const seg = (x1, y1, x2, y2) => { ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke(); };
  const dot = (x, y, r) => { ctx.beginPath(); ctx.arc(x, y, r, 0, 6.2832); ctx.fill(); };
  const rrect = (x, y, w, h, r) => { ctx.beginPath(); ctx.moveTo(x + r, y); ctx.arcTo(x + w, y, x + w, y + h, r); ctx.arcTo(x + w, y + h, x, y + h, r); ctx.arcTo(x, y + h, x, y, r); ctx.arcTo(x, y, x + w, y, r); ctx.closePath(); };
  const ease = (t) => { t = t < 0 ? 0 : t > 1 ? 1 : t; return t * t * (3 - 2 * t); };

  function resize() {
    const r = canvas.getBoundingClientRect();
    if (!r.width) return;
    dpr = Math.min(window.devicePixelRatio || 1, 2); W = r.width; H = r.height;
    canvas.width = Math.round(W * dpr); canvas.height = Math.round(H * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    busY = Math.round(H * 0.5);
    const n = W < 560 ? 5 : 8, pad = Math.max(50, W * 0.09), span = W - pad * 2;
    nodes = [];
    for (let i = 0; i < n; i++) nodes.push({ x: pad + span * (i / (n - 1)), y: busY + BANDS[i % BANDS.length], name: NAMES[i % NAMES.length], pulse: 0 });
    // mesh: connect each node to its 2 nearest neighbours (dedup) → edges + adjacency
    edges = []; adj = nodes.map(() => []);
    const have = new Set();
    for (let i = 0; i < n; i++) {
      const d = nodes.map((m, j) => ({ j, d: (m.x - nodes[i].x) ** 2 + (m.y - nodes[i].y) ** 2 })).filter((o) => o.j !== i).sort((a, b) => a.d - b.d);
      for (let k = 0; k < Math.min(2, d.length); k++) {
        const a = Math.min(i, d[k].j), b = Math.max(i, d[k].j), key = a + "_" + b;
        if (have.has(key)) continue; have.add(key);
        const ei = edges.length; edges.push({ a, b, glow: 0 });
        adj[a].push({ to: b, ei }); adj[b].push({ to: a, ei });
      }
    }
    packets = []; wires = []; ripples = [];
    rain = [];
    const cols = Math.max(6, Math.floor(W / 90));
    for (let i = 0; i < cols; i++) rain.push({ x: Math.random() * W, y: Math.random() * H, vy: 14 + Math.random() * 26, t: HEX[(Math.random() * HEX.length) | 0], a: 0.04 + Math.random() * 0.08 });
  }
  const nbox = (nd) => ({ x: nd.x - 17, y: nd.y - 12, w: 34, h: 24 });
  function spawnBus() {
    if (nodes.length < 2) return;
    let a = (Math.random() * nodes.length) | 0, b; do { b = (Math.random() * nodes.length) | 0; } while (b === a);
    packets.push({ x0: nodes[a].x, x1: nodes[b].x, to: b, t: 0, spd: 0.4 + Math.random() * 0.5, col: Math.random() < 0.5 ? C.acc : C.grn, trail: [] });
  }
  // Hover a node → ripple signals outward along the mesh wires (BFS ≤2 hops) and back.
  function emitRipple(src) {
    if (wires.length > 70 || !adj[src]) return;
    const seen = new Set([src]); let frontier = [src];
    for (let d = 0; d < 2; d++) {
      const next = [];
      for (const u of frontier) for (const { to, ei } of adj[u]) {
        if (seen.has(to)) continue; seen.add(to); next.push(to);
        const delay = d * 0.28;
        wires.push({ a: u, b: to, ei, t: 0, delay, spd: 0.8, col: d % 2 ? C.grn : C.acc });
        wires.push({ a: to, b: u, ei, t: 0, delay: delay + 0.9, spd: 0.8, col: C.acc });   // return wave
      }
      frontier = next;
    }
  }

  function draw(dt) {
    ctx.clearRect(0, 0, W, H);
    if (!W || !nodes.length) return;
    // background hex drift
    ctx.font = "11px ui-monospace, Menlo, Consolas, monospace"; ctx.textBaseline = "top"; ctx.textAlign = "left";
    for (const d of rain) {
      d.y += d.vy * dt;
      if (d.y > H + 12) { d.y = -12; d.x = Math.random() * W; d.t = HEX[(Math.random() * HEX.length) | 0]; }
      ctx.fillStyle = hexA(C.acc, d.a); ctx.fillText(d.t, d.x, d.y);
    }
    // mesh wires (faint; brighten when a signal rides them)
    for (const e of edges) {
      e.glow = Math.max(0, e.glow - dt * 1.2);
      const A = nodes[e.a], B = nodes[e.b], mid = 0.05 + e.glow * 0.55;
      // fade the wire to transparent at both ends (no hard endpoints)
      const g = ctx.createLinearGradient(A.x, A.y, B.x, B.y);
      g.addColorStop(0, hexA(C.acc, 0)); g.addColorStop(.2, hexA(C.acc, mid * .6));
      g.addColorStop(.5, hexA(C.acc, mid)); g.addColorStop(.8, hexA(C.acc, mid * .6));
      g.addColorStop(1, hexA(C.acc, 0));
      ctx.strokeStyle = g; ctx.lineWidth = 1 + e.glow * 1.4; seg(A.x, A.y, B.x, B.y);
    }
    // differential bus spine
    const x0 = nodes[0].x - 28, x1 = nodes[nodes.length - 1].x + 28;
    ctx.save(); ctx.lineCap = "round"; ctx.lineWidth = 2.5; ctx.shadowBlur = 12;
    ctx.shadowColor = C.acc; ctx.strokeStyle = C.acc; seg(x0, busY - 4, x1, busY - 4);
    ctx.shadowColor = C.grn; ctx.strokeStyle = C.grn; seg(x0, busY + 4, x1, busY + 4);
    ctx.restore();
    // nodes (with tap to bus)
    for (let i = 0; i < nodes.length; i++) {
      const nd = nodes[i], b = nbox(nd); nd.pulse = Math.max(0, nd.pulse - dt * 2.2);
      ctx.strokeStyle = hexA(C.mut, .35); ctx.lineWidth = 1.5; seg(nd.x, nd.y < busY ? b.y + b.h : b.y, nd.x, busY);
      const hot = i === hover ? 1 : nd.pulse;
      if (hot > 0) { ctx.save(); ctx.globalAlpha = hot; ctx.shadowColor = C.acc; ctx.shadowBlur = 18; ctx.strokeStyle = C.acc; ctx.lineWidth = 2; rrect(b.x - 4, b.y - 4, b.w + 8, b.h + 8, 8); ctx.stroke(); ctx.restore(); }
      ctx.fillStyle = hexA(C.txt, .03); ctx.strokeStyle = C.acc; ctx.lineWidth = 1.5; rrect(b.x, b.y, b.w, b.h, 6); ctx.fill(); ctx.stroke();
      ctx.strokeStyle = hexA(C.mut, .8); ctx.lineWidth = 1.3; rrect(nd.x - 9, nd.y - 7, 18, 14, 3); ctx.stroke();
      ctx.fillStyle = hexA(C.mut, .85); ctx.font = "9px ui-sans-serif,system-ui,sans-serif"; ctx.textAlign = "center"; ctx.textBaseline = nd.y < busY ? "bottom" : "top";
      ctx.fillText(nd.name, nd.x, nd.y < busY ? b.y - 6 : b.y + b.h + 6); ctx.textAlign = "left";
    }
    // bus packets
    for (let i = packets.length - 1; i >= 0; i--) {
      const p = packets[i]; p.t += dt * p.spd;
      const x = p.x0 + (p.x1 - p.x0) * ease(p.t);
      p.trail.unshift(x); if (p.trail.length > 10) p.trail.pop();
      for (let k = 0; k < p.trail.length; k++) { const a = (1 - k / p.trail.length) * 0.5; ctx.fillStyle = hexA(p.col, a); dot(p.trail[k], busY, (1 - k / p.trail.length) * 3 + 1); }
      ctx.save(); ctx.shadowColor = p.col; ctx.shadowBlur = 12; ctx.fillStyle = p.col; dot(x, busY, 4); ctx.restore();
      if (p.t >= 1) { nodes[p.to].pulse = 1; ripples.push({ x: nodes[p.to].x, y: busY, r: 6, a: .6, col: p.col }); packets.splice(i, 1); }
    }
    // wire pulses (hover ripple)
    for (let i = wires.length - 1; i >= 0; i--) {
      const p = wires[i];
      if (p.delay > 0) { p.delay -= dt; continue; }
      p.t += dt * p.spd; edges[p.ei].glow = 1;
      const A = nodes[p.a], B = nodes[p.b], e = ease(p.t);
      const x = A.x + (B.x - A.x) * e, y = A.y + (B.y - A.y) * e;
      ctx.save(); ctx.shadowColor = p.col; ctx.shadowBlur = 10; ctx.fillStyle = p.col; dot(x, y, 3); ctx.restore();
      if (p.t >= 1) { nodes[p.b].pulse = Math.max(nodes[p.b].pulse, .9); wires.splice(i, 1); }
    }
    // arrival ripples
    for (let i = ripples.length - 1; i >= 0; i--) { const r = ripples[i]; r.r += dt * 42; r.a -= dt * 0.9; if (r.a <= 0) { ripples.splice(i, 1); continue; } ctx.save(); ctx.globalAlpha = r.a; ctx.strokeStyle = r.col; ctx.lineWidth = 2; ctx.beginPath(); ctx.arc(r.x, r.y, r.r, 0, 6.2832); ctx.stroke(); ctx.restore(); }
  }
  function frame(ts) {
    const dt = Math.min(0.05, (ts - last) / 1000 || 0.016); last = ts;
    if (!nodes.length) resize();
    draw(dt);
    spawnAcc += dt; if (spawnAcc > 0.6 && packets.length < 9) { spawnAcc = 0; spawnBus(); }
    raf = requestAnimationFrame(frame);
  }
  function start() { if (running || reduce) return; running = true; last = performance.now(); raf = requestAnimationFrame(frame); }
  function stop() { running = false; if (raf) cancelAnimationFrame(raf); raf = null; }

  canvas.addEventListener("mousemove", (e) => {
    const r = canvas.getBoundingClientRect(), mx = e.clientX - r.left, my = e.clientY - r.top;
    let hit = -1, best = 30 * 30;
    for (let i = 0; i < nodes.length; i++) { const d = (nodes[i].x - mx) ** 2 + (nodes[i].y - my) ** 2; if (d < best) { best = d; hit = i; } }
    if (hit !== hover) { hover = hit; if (hit >= 0) { nodes[hit].pulse = 1; emitRipple(hit); } }
    canvas.style.cursor = hit >= 0 ? "pointer" : "default";
  });
  canvas.addEventListener("mouseleave", () => { hover = -1; });

  resize();
  if (reduce) { draw(0); return; }
  try {
    const io = new IntersectionObserver((es) => { if (es[0].isIntersecting) { resize(); start(); } else { stop(); } });
    io.observe(canvas);
  } catch (e) { start(); }
  window.addEventListener("resize", resize);
  document.addEventListener("visibilitychange", () => { if (document.hidden) stop(); else if (canvas.offsetParent) start(); });
}

// An action card: an icon and a name. What it does is its hold-tip — a caption
// under every card is help text, and the page carries none.
function idleCard(c) {
  return `<button type="button" class="idle-card ${c.primary ? "primary" : ""}" onclick="${c.onclick}" data-tip="${c.tip}">
    <span class="ic-wrap">${c.icon}</span><h4>${c.title}</h4></button>`;
}
function emptyHero(id, o) {
  const el = $(id); if (!el) return;
  const cards = (o.cards || []).map(idleCard).join("");
  el.innerHTML = `<div class="idle-hero">
    <div class="hero-stage"><canvas class="hero-canvas"></canvas></div>
    <div class="empty-anim-title">${o.title}</div>
    ${o.sub ? `<div class="empty-anim-sub">${o.sub}</div>` : ""}
    ${cards ? `<div class="idle-cards">${cards}</div>` : ""}
  </div>`;
  try { startHeroCanvas(el.querySelector(".hero-canvas")); }
  catch (e) { el.querySelector(".hero-stage").innerHTML = CAN_BUS_SVG; }   // graceful fallback
}
window.goView = (v) => openView(v);
window.quickConnectVirtual = async () => {
  setStatus("Connecting to virtual bus…");
  const r = await POST("/api/connect", { hw: "virtual", channel: "ucando", bitrate: 500000, simulate: true });
  setStatus(r && r.ok !== false ? "Virtual bus connected — streaming demo frames" : "Could not start virtual bus");
};
window.cvUploadClick = () => $("btnCvUpload").click();

emptyHero("dashEmpty", {
  title: "Waiting for live frames",
  sub: "OBD-II and J1939 values appear here as soon as a bus carries them.",
  cards: [
    { icon: ICONS.plug, title: "Virtual bus", onclick: "quickConnectVirtual()", primary: true,
      tip: "Connect the built-in virtual bus with demo OBD-II and J1939 traffic." },
    { icon: ICONS.grid, title: "Frame decoder", onclick: "goView('framedec')",
      tip: "Decode payloads against a DBC or Signature JSON, one frame or a whole trace." },
    { icon: ICONS.swap, title: "Converter", onclick: "goView('convert')",
      tip: "Convert a signal database between DBC, Signature JSON and CSV." },
  ],
});
emptyHero("cvEmpty", {
  title: "No database open",
  sub: "DBC, Signature JSON, CSV or a CanPlus vehicle library.",
  cards: [{ icon: ICONS.upload, title: "Upload file", onclick: "cvUploadClick()", primary: true,
    tip: "The format is detected from the file. Edit fields, pick signals, then download in any format." }],
});
emptyHero("dtcEmpty", {
  title: "No trouble codes",
  sub: "",
  cards: [{ icon: ICONS.plug, title: "Virtual bus", onclick: "quickConnectVirtual()", primary: true,
    tip: "Connect the built-in virtual bus; its demo traffic includes trouble codes." }],
});

// Initial header title/description + kick off polling for the Dashboard view.
setViewMeta(state.view);
applyAvailability();
sigSetViewMode(sigViewMode);
startPolling(state.view);
