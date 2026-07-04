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

// ---- shared inline SVG icon set (Feather-style) ----
const _ico = (b, extra = "") => `<svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"${extra}>${b}</svg>`;
const ICONS = {
  power: _ico('<path d="M18.36 6.64a9 9 0 1 1-12.73 0"/><line x1="12" y1="2" x2="12" y2="12"/>'),
  record: '<svg class="ico" viewBox="0 0 24 24"><circle cx="12" cy="12" r="6" fill="#e25555"/></svg>',
  play: '<svg class="ico" viewBox="0 0 24 24"><polygon points="6 4 20 12 6 20 6 4" fill="currentColor"/></svg>',
  pause: _ico('<rect x="6" y="5" width="4" height="14" rx="1"/><rect x="14" y="5" width="4" height="14" rx="1"/>'),
  stop: _ico('<rect x="6" y="6" width="12" height="12" rx="1.5"/>'),
  step: '<svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="5 4 15 12 5 20 5 4" fill="currentColor"/><line x1="19" y1="5" x2="19" y2="19"/></svg>',
  refresh: _ico('<polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/>'),
  chevronDown: _ico('<polyline points="6 9 12 15 18 9"/>'),
  chevronUp: _ico('<polyline points="18 15 12 9 6 15"/>'),
  close: _ico('<line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>'),
  check: _ico('<polyline points="20 6 9 17 4 12"/>'),
  arrowRight: _ico('<line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/>'),
  upload: _ico('<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/>'),
  download: _ico('<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>'),
  clipboard: _ico('<path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/><rect x="8" y="2" width="8" height="4" rx="1"/>'),
  grid: _ico('<rect x="3" y="3" width="18" height="18" rx="2"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="3" y1="15" x2="21" y2="15"/><line x1="9" y1="3" x2="9" y2="21"/><line x1="15" y1="3" x2="15" y2="21"/>'),
  alert: _ico('<path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>'),
  // playback transport (log-signal scrubbing)
  skipBack: '<svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="19 20 9 12 19 4 19 20" fill="currentColor"/><line x1="5" y1="19" x2="5" y2="5"/></svg>',
  skipFwd: '<svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="5 4 15 12 5 20 5 4" fill="currentColor"/><line x1="19" y1="5" x2="19" y2="19"/></svg>',
  rewind: '<svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="12 4 5 12 12 20 12 4" fill="currentColor"/><polygon points="19 4 12 12 19 20 19 4" fill="currentColor"/></svg>',
  fastFwd: '<svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="12 4 19 12 12 20 12 4" fill="currentColor"/><polygon points="5 4 12 12 5 20 5 4" fill="currentColor"/></svg>',
};
// Back-compat aliases used by the topbar renderer
const ICON_POWER = ICONS.power, ICON_RECORD = ICONS.record, ICON_STOP = ICONS.stop;
const _bigGrid = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" style="width:30px;height:30px;color:var(--accent)"><rect x="3" y="3" width="18" height="18" rx="3"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="3" y1="15" x2="21" y2="15"/><line x1="9" y1="3" x2="9" y2="21"/><line x1="15" y1="3" x2="15" y2="21"/></svg>';

// Populate version chip from API
api("/api/info").then((d) => {
  const chip = $("verChip");
  if (chip) chip.textContent = `v${d.version} · ${d.app}`;
});

// Each view: a short fixed title + a one-line description.
const VIEW_META = {
  dashboard: { t: "Dashboard", d: "Live values decoded from standard protocols (OBD-II, J1939) — no DBC required." },
  logger: { t: "CAN Logger", d: "Live capture with per-ID stats and recording to .asc / .blf / .csv." },
  replay: { t: "TX Replay", d: "Play a recorded log back onto the bus with speed, loop, and step control." },
  re: { t: "Reverse Engineering", d: "Find candidate signals in an unknown log — entropy, bit-flip rate, sniffer, OBD correlation." },
  autore: { t: "Auto-RE", d: "Confidence-tiered (A/B/C) identification: CANMatch, OBD correlation, and known-value matching." },
  framedec: { t: "Frame Decoder", d: "Decode raw CAN frames against a DBC or JSON signature — byte, bit, and signal view." },
  convert: { t: "Converter", d: "Convert a signal database among DBC, Signature JSON, and CSV in any direction." },
  dbc: { t: "DBC Builder", d: "Edit messages and signals, then round-trip to a .dbc file." },
  oem: { t: "OEM Database", d: "Store, fingerprint, and auto-apply vehicle DBC profiles (CANMatch)." },
  signals: { t: "Signal Viewer", d: "Live DBC decode into strip charts, with computed signals and alarms — or upload a log to chart it offline." },
  scheduler: { t: "TX Scheduler", d: "Transmit cyclic or one-shot frames on the bus." },
  automation: { t: "Automation", d: "Rules, scheduled jobs, restbus simulation, and scripting." },
  dtc: { t: "DTC Codes", d: "Read and clear trouble codes — OBD-II, UDS, and J1939." },
  decoder: { t: "Protocol Decoder", d: "Live OBD-II / UDS (ISO-TP) / J1939 frame interpretation." },
};
function setViewMeta(view) {
  const m = VIEW_META[view] || { t: view, d: "" };
  $("viewTitle").textContent = m.t;
  const desc = $("viewDesc");
  desc.textContent = m.d;
  desc.title = m.d;
}

// ---------------------------------------------------------------- navigation
document.querySelectorAll(".nav").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".nav").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    const view = btn.dataset.view;
    state.view = view;
    document.querySelectorAll(".view").forEach((v) => v.classList.add("hidden"));
    $("view-" + view).classList.remove("hidden");
    setViewMeta(view);
    startPolling(view);
    if (view === "replay" || view === "re") refreshLogs();
    if (view === "dbc") renderDbc();
    if (view === "logger") loadLogDir();
    if (view === "autore") initAutoRE();
    if (view === "oem") renderOem();
    if (view === "automation") renderAutomation();
    if (view === "scheduler") pollTx();
  });
});

function startPolling(view) {
  if (pollTimer) clearInterval(pollTimer);
  if (view === "dashboard") pollTimer = setInterval(pollDashboard, 400);
  else if (view === "signals") pollTimer = setInterval(pollSignals, 400);
  else if (view === "scheduler") pollTimer = setInterval(pollTx, 700);
  else if (view === "dtc") pollTimer = setInterval(pollDtc, 700);
  else if (view === "decoder") pollTimer = setInterval(pollDecode, 500);
}
function setStatus(t) { $("statusText").textContent = t; }

// ------------------------------------------------------------- connect/record
async function loadDevices() {
  const { devices } = await api("/api/devices");
  $("devSelect").innerHTML = devices
    .map((d) => `<option value='${JSON.stringify({ hw: d.hw, channel: d.channel })}'>${d.label}</option>`)
    .join("");
}
$("btnConnect").addEventListener("click", async () => {
  if (state.connected) return void POST("/api/disconnect");
  $("connectError").classList.add("hidden");
  await loadDevices();
  $("connectModal").classList.remove("hidden");
});
$("btnRefreshDevs").addEventListener("click", loadDevices);
$("btnCancelConnect").addEventListener("click", () => $("connectModal").classList.add("hidden"));
$("btnDoConnect").addEventListener("click", async () => {
  const dev = JSON.parse($("devSelect").value);
  const res = await POST("/api/connect", {
    hw: dev.hw, channel: dev.channel,
    bitrate: parseInt($("bitrateSelect").value, 10), simulate: $("simCheck").checked,
  });
  if (res.ok) $("connectModal").classList.add("hidden");
  else { const e = $("connectError"); e.textContent = res.error || "Connection failed"; e.classList.remove("hidden"); }
});
$("btnRecord").addEventListener("click", async () => {
  if (state.recording) {
    const r = await POST("/api/logger/record/stop");
    if (r.path) setStatus(`Saved ${r.frames} frames → ${r.path}`);
    return;
  }
  $("recordModal").classList.remove("hidden");
});
$("btnCancelRecord").addEventListener("click", () => $("recordModal").classList.add("hidden"));
$("btnDoRecord").addEventListener("click", async () => {
  const r = await POST("/api/logger/record/start", { name: $("recName").value || "capture", format: $("recFormat").value });
  $("recordModal").classList.add("hidden");
  setStatus(r.ok ? "Recording → " + r.path : "Record error: " + (r.error || "?"));
});
$("btnClear").addEventListener("click", () => POST("/api/logger/clear"));

// ----------------------------------------------------------------- CAN Logger
const fmtPeriod = (ms) => (!ms ? "—" : ms >= 1000 ? (ms / 1000).toFixed(2) + " s" : ms.toFixed(1) + " ms");

function renderLogger(snap) {
  state.connected = !!snap.connected;
  state.recording = !!snap.recording;
  const chip = $("hwChip");
  chip.dataset.state = state.connected ? "on" : "off";
  $("hwChipText").textContent = state.connected ? "Connected" : "Not connected";
  $("btnConnect").innerHTML = ICON_POWER + `<span>${state.connected ? "Disconnect" : "Connect"}</span>`;
  $("btnRecord").disabled = !state.connected;
  $("btnRecord").dataset.on = state.recording ? "1" : "0";
  $("btnRecord").innerHTML = (state.recording ? ICON_STOP : ICON_RECORD) + `<span>${state.recording ? "Stop" : "Record"}</span>`;
  $("recBadge").classList.toggle("hidden", !state.recording);

  if (snap.replay) renderReplay(snap.replay);
  if (!snap.running) { if (state.view === "logger") setStatus(state.connected ? "Connected · idle" : "Ready"); return; }

  $("statTotal").textContent = (snap.total || 0).toLocaleString();
  $("statIds").textContent = snap.unique_ids || 0;
  $("statFps").textContent = snap.fps || 0;
  $("statLoad").textContent = (snap.bus_load_pct || 0) + "%";
  $("statElapsed").textContent = (snap.elapsed_s || 0).toFixed(1) + "s";
  $("recInfo").textContent = state.recording ? `REC ${snap.record_frames} frames` : "";
  if (state.view === "logger") setStatus("Capturing");

  $("idTable").querySelector("tbody").innerHTML = (snap.ids || []).map((s) => `
    <tr><td class="mono">0x${s.id_hex}</td><td><span class="tag">${s.ext ? "EXT" : "STD"}</span></td>
    <td>${s.dlc}</td><td>${s.count.toLocaleString()}</td><td>${fmtPeriod(s.period_ms)}</td>
    <td class="mono">${s.data || ""}</td></tr>`).join("");
  $("feedTable").querySelector("tbody").innerHTML = (snap.recent || []).map((f) => `
    <tr><td>${f.ts.toFixed(3)}</td><td>0x${f.id_hex}</td><td>${f.dlc}</td><td>${f.data}</td></tr>`).join("");
}

function connectWS() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws/live`);
  ws.onmessage = (e) => { try { renderLogger(JSON.parse(e.data)); } catch (_) {} };
  ws.onclose = () => setTimeout(connectWS, 1000);
}
connectWS();

// ------------------------------------------------------------------ TX Replay
async function refreshLogs() {
  const { logs } = await api("/api/logs");
  const opts = logs.length
    ? logs.map((l) => `<option value="${l.path}">${l.name} (${(l.size / 1024).toFixed(0)} KB)</option>`).join("")
    : `<option value="">— no logs yet (record one first) —</option>`;
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
$("replayFile").addEventListener("change", async (e) => {
  const f = e.target.files[0]; if (!f) return;
  const r = await apiUpload("/api/upload", f);
  await refreshLogs();
  if (r.path) { $("replaySelect").value = r.path; loadReplay(); }
});
$("replaySelect").addEventListener("change", loadReplay);
async function loadReplay() {
  const path = $("replaySelect").value; if (!path) return;
  const r = await POST("/api/replay/load", { path });
  if (r.ok) $("replayMeta").textContent =
    `${r.meta.frames} frames · ${r.meta.duration_s}s · ${r.meta.ids.length} IDs · ch ${r.meta.channels.join("+") || "?"}`;
  else $("replayMeta").textContent = r.error;
}
$("btnPlay").addEventListener("click", () =>
  POST("/api/replay/play", { speed: parseFloat($("speedRange").value), loop: $("replayLoop").checked })
    .then((r) => { if (!r.ok) setStatus(r.error); }));
$("btnPause").addEventListener("click", () => POST("/api/replay/pause"));
$("btnStop").addEventListener("click", () => POST("/api/replay/stop"));
$("btnStep").addEventListener("click", () => POST("/api/replay/step"));
$("speedRange").addEventListener("input", () => {
  $("speedLabel").textContent = parseFloat($("speedRange").value).toFixed(1) + "×";
});
function renderReplay(s) {
  $("replayState").textContent = s.state;
  $("replayBar").style.width = (s.progress * 100).toFixed(1) + "%";
  $("replayCursor").textContent = `${s.cursor_s.toFixed(3)} s · ${s.sent} sent · ${s.cursor}/${s.total}`;
}

// -------------------------------------------------------- Reverse Engineering
let lastRe = null;
function entropyColor(h) {  // 0 (blue, constant) → 8 (red, noisy)
  const t = Math.min(1, h / 8);
  const r = Math.round(40 + 200 * t), g = Math.round(120 * (1 - Math.abs(t - 0.5) * 2)), b = Math.round(220 * (1 - t));
  return `rgb(${r},${g + 60},${b})`;
}
const KIND_COLOR = {
  counter: "#7bd88f", crc: "#e06c75", physical: "#61afef",
  "multi-state": "#e5c07b", constant: "#6b7280", event: "#c678dd",
};
function candChip(c) {
  const col = KIND_COLOR[c.kind] || "#9aa0a6";
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
    const mux = id.multiplexor ? ` <span class="cand-chip" style="border-color:#c678dd;color:#c678dd" title="multiplexor">mux@byte${id.multiplexor.selector_byte}</span>` : "";
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
    const bits = c.candidates.map((cd) => `<span class="cand-chip" style="border-color:#c678dd;color:#c678dd">@${cd.start_bit}/${cd.length}</span>`).join(" ");
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
async function renderOem() {
  const { profiles } = await api("/api/oem/profiles");
  $("oemTable").querySelector("tbody").innerHTML = (profiles || []).map((p) => {
    const apply = p.id_count ? `<button class="btn-mini" onclick="oemApply(${p.id})">Apply</button>` : "";
    return `<tr><td>${p.oem}</td><td>${p.name}</td><td class="muted-line">${p.model || "—"}</td>
      <td>${p.id_count}</td><td><span class="tag">${p.status}</span></td>
      <td>${apply} <button class="btn-mini" onclick="oemDelete(${p.id})">${ICONS.close}</button></td></tr>`;
  }).join("") || `<tr><td colspan="6" class="muted-line" style="padding:14px">No profiles.</td></tr>`;
}
window.oemApply = async (id) => {
  const r = await POST("/api/oem/apply?pid=" + id);
  setStatus(r.ok ? `Applied profile → Signal Viewer (${r.signals ? r.signals.length : 0} signals)` : "Apply: " + r.error);
};
window.oemDelete = async (id) => { await POST("/api/oem/profile/delete?pid=" + id); renderOem(); };
$("btnOemRefresh").addEventListener("click", renderOem);
$("btnOemIdentify").addEventListener("click", async () => {
  const r = await api("/api/oem/identify");
  if (!r.ok) return void ($("oemIdentStatus").textContent = r.error);
  $("oemIdentStatus").textContent = `${r.observed_ids} IDs observed`;
  $("oemIdentWrap").innerHTML = `<table class="data-table"><thead><tr><th>Match</th><th>OEM</th><th>Score</th><th>IDs matched</th><th></th></tr></thead>
    <tbody>${(r.matches || []).map((m) => `<tr><td>${m.name}</td><td>${m.oem}</td>
      <td>${(m.score * 100).toFixed(0)}%</td><td>${m.matched}/${m.profile_ids}</td>
      <td><button class="btn-mini" onclick="oemApply(${m.profile_id})">Apply</button></td></tr>`).join("")
      || `<tr><td colspan="5" class="muted-line" style="padding:14px">No confident match — reverse-engineer it and save a new profile.</td></tr>`}</tbody></table>`;
});
$("btnOemAutoApply").addEventListener("click", async () => {
  const r = await POST("/api/oem/auto-apply");
  if (r.ok && r.applied) setStatus(`Auto-applied "${r.applied.name}" (${(r.match.score * 100).toFixed(0)}%) → Signal Viewer`);
  else setStatus(r.reason ? "No confident decodable match" : ("Auto-apply: " + (r.error || "?")));
  $("btnOemIdentify").click();
});
$("btnOemFromBuilder").addEventListener("click", async () => {
  const oem = $("oemSaveOem").value.trim(), name = $("oemSaveName").value.trim();
  if (!oem || !name) return void setStatus("Enter OEM and profile name");
  const r = await POST("/api/oem/from-builder", { oem, name });
  if (r.ok) { setStatus(`Saved profile "${name}"`); renderOem(); }
  else setStatus("Save: " + r.error);
});

// --------------------------------------------------------------- Automation
function renderAutomation() { renderRules(); renderJobs(); pollRestbus(); }
async function renderRules() {
  const t = await api("/api/rules");
  $("rulesWrap").innerHTML = `<table class="data-table"><thead><tr><th>Name</th><th>When</th><th>Action</th><th>Fired</th><th></th></tr></thead>
    <tbody>${(t.rules || []).map((r) => `<tr><td>${r.name}</td><td class="mono">${r.when}</td>
      <td>${r.action.type}</td><td>${r.fired}</td>
      <td><button class="btn-mini" onclick="delRule(${r.uid})">${ICONS.close}</button></td></tr>`).join("")
      || `<tr><td colspan="5" class="muted-line" style="padding:12px">No rules.</td></tr>`}</tbody></table>`;
  $("ruleEventsWrap").innerHTML = `<table class="data-table mono"><tbody>${(t.events || []).slice(0, 30).map((e) =>
    `<tr><td>${e.ts}</td><td>${e.rule}</td><td>${e.action}</td><td>${e.detail}</td></tr>`).join("")
    || `<tr><td class="muted-line" style="padding:12px">No events yet.</td></tr>`}</tbody></table>`;
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
window.delRule = async (uid) => { await POST("/api/rules/remove?uid=" + uid); renderRules(); };

async function renderJobs() {
  const { jobs } = await api("/api/jobs");
  $("jobsWrap").innerHTML = `<table class="data-table"><thead><tr><th>Name</th><th>Kind</th><th>Schedule</th><th>Last run</th><th></th></tr></thead>
    <tbody>${(jobs || []).map((j) => `<tr><td>${j.name}</td><td>${j.kind}</td><td class="mono">${j.schedule || "manual"}</td>
      <td>${j.last_run ? new Date(j.last_run * 1000).toLocaleTimeString() : "—"}</td>
      <td><button class="btn-mini" onclick="runJob(${j.id})">Run</button> <button class="btn-mini" onclick="delJob(${j.id})">${ICONS.close}</button></td></tr>`).join("")
      || `<tr><td colspan="5" class="muted-line" style="padding:12px">No jobs.</td></tr>`}</tbody></table>`;
}
$("btnJobAdd").addEventListener("click", async () => {
  const name = $("jobName").value.trim() || "job"; const every = $("jobEvery").value.trim();
  await POST("/api/jobs/add", { name, kind: $("jobKind").value, schedule: every ? "every:" + every : "", spec: { duration_s: 5 } });
  $("jobName").value = $("jobEvery").value = ""; renderJobs();
});
window.runJob = async (id) => { const r = await POST("/api/jobs/run?jid=" + id); setStatus("Job: " + JSON.stringify(r.result || r)); renderJobs(); };
window.delJob = async (id) => { await POST("/api/jobs/remove?jid=" + id); renderJobs(); };

async function pollRestbus() {
  const s = await api("/api/restbus/status");
  $("restbusStatus").textContent = `${s.running ? "running" : "stopped"} · ${s.messages} msgs · ${s.sent} sent`;
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
  const fill = $("fdFill");
  if (fill) fill.placeholder = fdSource === "json"
    ? "912  0128C30000000000\n900  0205000000000200"
    : "163  0205000000000200\n94   0006320040001C00";
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
      return `<tr data-id="${m.id_hex}">
        <td>${i + 1}</td>
        <td class="mono" style="font-weight:500">${fdIdLabel(m)}&thinsp;<span style="color:var(--muted);font-weight:400;font-family:inherit">· ${m.name}</span></td>
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
                  : `<span style="color:var(--green)">varies</span><span class="muted-line">${s.min}–${s.max}${u}</span>`) + `</span>`;
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
    const physColor = oor ? "var(--red)" : "var(--accent)";
    const oorBadge = oor
      ? `<span title="Outside DBC range [${s.min ?? "?"}…${s.max ?? "?"}]"
           style="margin-left:5px;font-size:10px;background:#3a1c1c;color:var(--red);border-radius:3px;padding:1px 5px;vertical-align:middle">OOR</span>`
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
  }).join("") || `<tr><td colspan="${hasChoices ? 6 : 5}" class="muted-line" style="padding:12px;text-align:center">no decoded signals</td></tr>`;

  // Header: add Description column only when needed
  const descHead = hasChoices ? `<th style="color:var(--green)">Description</th>` : "";

  // Inline colours (cache-proof — don't depend on style.css being fresh).
  const C_HI = "#4ea1ff", C_MSB = "#e0a82e", C_LSB = "#46b86a";
  // Distinct palette for the message-layout view (one colour per signal).
  const PALETTE = ["#4ea1ff", "#46b86a", "#e0a82e", "#c264d6", "#e06c4e",
                   "#3fb6c0", "#d65a8a", "#8a9a3f", "#6a78e0", "#cf7e3f"];
  const sigColorAt = (i) => PALETTE[i % PALETTE.length];
  const _lum = (h) => 0.299 * parseInt(h.slice(1, 3), 16)
                    + 0.587 * parseInt(h.slice(3, 5), 16)
                    + 0.114 * parseInt(h.slice(5, 7), 16);
  const txtOn = (h) => (_lum(h) > 150 ? "#1b1d1f" : "#fff");

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
  const hSty = "background:#2a2d31;color:#cdd3da;font-weight:600;border:1px solid var(--line);font-size:11px;text-align:center;font-family:var(--mono)";
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
          if (single) { bg = C_HI; tc = "#fff"; tag = "bit"; }
          else if (isMsb) { bg = C_MSB; tc = "#1b1d1f"; tag = "msb"; }
          else if (isLsb) { bg = C_LSB; tc = "#fff"; tag = "lsb " + arrowFor(sel); }
          else { bg = C_HI; tc = "#fff"; }
        }
      } else if (si !== undefined) {               // message-layout mode (all signals)
        const col = sigColorAt(si);
        bg = col; tc = txtOn(col); fw = "600";
        if (isMsb && isLsb) tag = "bit";
        else if (isMsb) tag = "msb";
        else if (isLsb) tag = "lsb " + arrowFor(f.signals[si]);
      }
      const idxSpan = `<span style="position:absolute;top:0;right:2px;font-size:8px;line-height:1.1;opacity:.5;font-weight:400">${idx}</span>`;
      const tagSpan = tag ? `<span style="position:absolute;bottom:-1px;left:0;right:0;font-size:7px;line-height:1.2;font-weight:600;letter-spacing:.02em">${tag}</span>` : "";
      return `<td style="position:relative;width:30px;height:30px;padding:0;border:1px solid var(--line);text-align:center;background:${bg};color:${tc};font-weight:${fw}">`
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
    <div class="muted-line" style="font-size:11px;text-transform:uppercase;letter-spacing:.06em;margin-bottom:6px">Data Byte View (HEX)</div>
    <table class="byteview mono"><tbody><tr><th>Byte</th>${idx}</tr><tr><th>Value</th>${val}</tr></tbody></table>
    <div style="margin-top:16px">
      <div class="muted-line" style="font-size:11px;text-transform:uppercase;letter-spacing:.06em;margin-bottom:6px">Signal Details</div>
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
    <div style="margin-top:24px;border-top:1px solid var(--line);padding-top:16px">
      <h3 style="font-size:15px;font-weight:600;color:var(--text);margin:0 0 2px">Bit Layout</h3>
      <div class="muted-line" style="font-size:11px;margin-bottom:10px">Click a signal to isolate · arrows point LSB→MSB</div>
      <div style="overflow-x:auto">${grid}</div>
      ${legend}
    </div>
  </div>`;
}
$("btnFdFill").addEventListener("click", () => {
  // ID base follows the active source: decimal for JSON, hex for DBC.
  const idBase = fdSource === "json" ? 10 : 16;
  let matched = 0;
  for (const ln of $("fdFill").value.split("\n")) {
    const t = ln.trim().split(/[\s,]+/); if (t.length < 2) continue;
    const id = parseInt(t[0], idBase); if (isNaN(id)) continue;
    const idHex = id.toString(16).toUpperCase();
    if (idHex in fdPayloads) {
      // join remaining tokens so spaced payloads ("01 28 C3") work, hex-only
      fdPayloads[idHex] = t.slice(1).join("").replace(/[^0-9a-fA-F]/g, "");
      matched++;
    }
  }
  renderFdCatalogue();
  // Refresh the open message so its input + decode reflect the filled payload.
  const openId = fdCurrentDetailId;
  if (openId && openId in fdPayloads) { fdCurrentDetailId = null; fdDecodeOne(openId); }
  setStatus(`Payloads filled from dump — ${matched} message${matched === 1 ? "" : "s"} matched`);
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
const _svg = (body) => `<svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${body}</svg>`;
const CV_ICON = {
  edit: _svg('<path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4z"/>'),
  lock: _svg('<rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>'),
};
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
  return `<div style="border:1px solid #7a5;background:#2a2410;border-radius:8px;padding:10px 14px">
    <div style="color:#e0a82e;margin-bottom:6px">⚠ ${warns.length} note${warns.length === 1 ? "" : "s"} ${ctx || ""}</div>
    <ul style="margin:0;padding-left:18px;color:var(--muted);font-size:13px">${warns.map((w) => `<li>${w}</li>`).join("")}</ul></div>`;
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
  const warn = doubt ? `<span title="${escAttr(doubt)}" style="color:#e0a82e;margin-left:4px">⚠</span>` : "";
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
  renderCv();      // refresh ⚠ markers + loss preview
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
  if (dbt) msg += ` ⚠ ${dbt} sub-byte big-endian signal${dbt === 1 ? "" : "s"}${to === "dbc" ? " will get a verify comment" : ""}.`;
  $("cvLoss").textContent = msg;
}

$("btnCvDownload").addEventListener("click", async () => {
  if (!cvModel) return;
  const to = $("cvTo").value;
  const fm = { messages: [] };
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
    : `<div class="muted-line" style="color:var(--green)">Clean conversion — downloaded ${r.filename}</div>`;
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
        <button class="btn-mini" onclick="dbcDelMsg(${mi})">${ICONS.close}</button>
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
        <td><button class="btn-mini" onclick="dbcDelSig(${mi},${si})">${ICONS.close}</button></td>
      </tr>`).join("")}
      </tbody></table>
    </div>`).join("") || `<div class="placeholder" style="padding:40px">No messages. Add one, or seed from Reverse Engineering.</div>`;
}
const dbcSave = () => POST("/api/dbc/set", { messages: dbcModel.messages });
window.dbcEdit = (mi, si, key, val) => { (si === null ? dbcModel.messages[mi] : dbcModel.messages[mi].signals[si])[key] = val; dbcSave(); };
window.dbcAddSig = (mi) => { dbcModel.messages[mi].signals.push({ name: "sig_" + dbcModel.messages[mi].signals.length, start_bit: 0, length: 8, byte_order: "little_endian", is_signed: false, scale: 1, offset: 0, unit: "" }); dbcSave().then(renderDbc); };
window.dbcDelSig = (mi, si) => { dbcModel.messages[mi].signals.splice(si, 1); dbcSave().then(renderDbc); };
window.dbcDelMsg = (mi) => { dbcModel.messages.splice(mi, 1); dbcSave().then(renderDbc); };
$("btnDbcAddMsg").addEventListener("click", () => {
  const hex = prompt("New message frame ID (hex):", "200"); if (!hex) return;
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
const SIG_COLORS = ["#4ea1ff", "#46b86a", "#e2a055", "#c46bde", "#e25555", "#3fc7c7", "#d4d04e"];
// Log-playback mode: chart a decoded-once log instead of polling live traffic.
// null = live (the original behaviour); set by "Upload log for playback" below.
let sigLogSeries = null;
let sigLogName = "";
let sigLogCoverage = null;           // {unknown_ids, decode_errors} from the last upload
// Playback transport — purely client-side windowing over the already-decoded
// sigLogSeries; no network calls while scrubbing/playing.
let sigPlaybackT = 0;                 // current playhead, seconds relative to log start
let sigPlaybackMaxT = 0;
let sigWindowSec = 5;                 // trailing window width each chart displays
let sigPlaying = false;
let sigPlaySpeed = 1;
let sigPlayRAF = null, sigPlayLastTs = null;
const SIG_SPEEDS = [0.25, 0.5, 1, 2, 4, 8];

function sigResetLogMode() {
  sigLogSeries = null; sigLogName = ""; sigLogCoverage = null;
  sigPlaying = false;
  if (sigPlayRAF) { cancelAnimationFrame(sigPlayRAF); sigPlayRAF = null; }
  $("btnPbPlay").innerHTML = ICONS.play;
  $("btnSigLogBack").classList.add("hidden");
  $("sigPlaybackBar").hidden = true;
  $("sigCoveragePanel").hidden = true;
}
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
  // Computed channels & alarms reference signal keys that don't exist yet without a DBC loaded — hide, don't show an unusable panel.
  $("sigCompAlarmPanel").hidden = !(info.loaded && info.signals.length > 0);
  sigAllSignals = info.signals || [];
  renderSigCheckboxes();
}
function renderSigCheckboxes() {
  $("sigList").innerHTML = sigAllSignals.map((s, i) => `
    <label class="sig-item"><input type="checkbox" data-key="${s.key}" ${sigSelected.has(s.key) ? "checked" : ""} onchange="toggleSig('${s.key}')"/>
    <span class="sig-swatch" style="background:${SIG_COLORS[i % SIG_COLORS.length]}"></span>${s.key} ${s.unit ? "(" + s.unit + ")" : ""}</label>`).join("");
}
window.toggleSig = (key) => { sigSelected.has(key) ? sigSelected.delete(key) : sigSelected.add(key); renderChartShells(); };
$("btnSigSelAll").addEventListener("click", () => {
  sigAllSignals.forEach((s) => sigSelected.add(s.key));
  renderSigCheckboxes(); renderChartShells();
});
$("btnSigSelNone").addEventListener("click", () => {
  sigSelected.clear();
  renderSigCheckboxes(); renderChartShells();
});
function renderChartShells() {
  $("charts").innerHTML = [...sigSelected].map((k, i) => `
    <div class="chart-card"><div class="chart-title"><span>${k}</span><span id="cv-${cssId(k)}-v"></span></div>
    <canvas class="chart" id="cv-${cssId(k)}" data-key="${k}" data-color="${SIG_COLORS[i % SIG_COLORS.length]}"></canvas></div>`).join("");
}
const cssId = (k) => k.replace(/[^a-zA-Z0-9]/g, "_");
async function pollSignals() {
  if (!sigLogSeries) pollDerived();     // alarms/computed are live-only — not evaluated during log playback
  if (!sigSelected.size) return;
  if (sigLogSeries) {
    // Trailing window ending at the playhead — a 50k-frame log squished onto
    // one chart is unreadable, so only the last `sigWindowSec` are drawn.
    const winStart = Math.max(0, sigPlaybackT - sigWindowSec);
    for (const key of sigSelected) {
      const pts = (sigLogSeries[key] || []).filter((p) => p[0] >= winStart && p[0] <= sigPlaybackT);
      drawChart(key, pts);
    }
    return;
  }
  const res = await api("/api/signals/series?keys=" + encodeURIComponent([...sigSelected].join(",")));
  for (const key of sigSelected) drawChart(key, res.series[key] || []);
}

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

  sigPlaybackMaxT = Math.max(0, ...Object.values(sigLogSeries).flatMap((pts) => pts.map((p) => p[0])), 0);
  sigWindowSec = Math.min(20, Math.max(2, sigPlaybackMaxT * 0.05)) || 5;
  sigPlaybackT = Math.min(sigWindowSec, sigPlaybackMaxT);   // start with one populated window, not blank
  $("sigPbScrub").max = String(Math.round(sigPlaybackMaxT * 1000) || 1);
  $("sigPbScrub").value = String(Math.round(sigPlaybackT * 1000));
  $("sigPlaybackBar").hidden = false;
  sigUpdatePlaybackLabel();
  pollSignals();
});
$("btnSigLogBack").addEventListener("click", () => { sigResetLogMode(); refreshSigList(); });

function sigRenderCoverage(unknownFrames, errorFrames) {
  const c = sigLogCoverage;
  $("sigCoverageBody").classList.add("hidden");            // collapsed by default on every fresh upload
  $("btnSigCoverageToggle").textContent = "Show breakdown";
  if (!c.unknown_ids.length && !c.decode_errors.length) { $("sigCoveragePanel").hidden = true; return; }
  $("sigCoveragePanel").hidden = false;
  const rows = [];
  if (errorFrames) rows.push(`<div style="color:var(--red);margin-bottom:6px">⚠ ${errorFrames} frame(s) from ${c.decode_errors.length} ID(s) ARE in this DBC but failed to decode — likely a DBC/vehicle mismatch:</div>`);
  rows.push(...c.decode_errors.map((e) => `<div style="padding-left:10px;color:var(--red)">0x${e.id_hex} × ${e.count} — ${e.error}</div>`));
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
  $("sigPlaybackTime").textContent = `${sigPlaybackT.toFixed(1)}s / ${sigPlaybackMaxT.toFixed(1)}s`;
  $("sigPbWindow").textContent = `window ${sigWindowSec.toFixed(1)}s`;
}
function sigSeekTo(t) {
  sigPlaybackT = Math.max(0, Math.min(sigPlaybackMaxT, t));
  $("sigPbScrub").value = String(Math.round(sigPlaybackT * 1000));
  sigUpdatePlaybackLabel();
  pollSignals();
}
$("sigPbScrub").addEventListener("input", () => sigSeekTo((+$("sigPbScrub").value) / 1000));
$("btnPbStart").addEventListener("click", () => sigSeekTo(0));
$("btnPbEnd").addEventListener("click", () => sigSeekTo(sigPlaybackMaxT));
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
$("btnPbPlay").addEventListener("click", () => {
  if (!sigLogSeries) return;
  sigPlaying = !sigPlaying;
  $("btnPbPlay").innerHTML = sigPlaying ? ICONS.pause : ICONS.play;
  if (sigPlaying) {
    if (sigPlaybackT >= sigPlaybackMaxT) sigPlaybackT = 0;   // replay from the top if already at the end
    sigPlayLastTs = null;
    sigPlayRAF = requestAnimationFrame(sigPlayTick);
  } else if (sigPlayRAF) { cancelAnimationFrame(sigPlayRAF); sigPlayRAF = null; }
});

// ----- computed signals & alarms -----
let computedDefs = [], alarmDefs = [];
async function pollDerived() {
  const d = await api("/api/signals/derived");
  const active = (d.alarms || []).filter((a) => a.active);
  $("sigAlarmBanner").innerHTML = active.length
    ? `<span class="cand-chip" style="border-color:#e25555;color:#e25555">⚠ ${active.map((a) => a.name).join(", ")}</span>` : "";
  $("almList").innerHTML = (d.alarms || []).map((a, i) =>
    `<span class="cand-chip" style="border-color:${a.active ? "#e25555" : "#6b7280"};color:${a.active ? "#e25555" : "#9aa0a6"}">
      ${a.name} [${a.min ?? "−∞"},${a.max ?? "∞"}]${a.active ? " ⚠" : ""} <a href="#" onclick="delAlarm(${i});return false">${ICONS.close}</a></span>`).join("") || "none";
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
    `<span class="cand-chip" style="border-color:#61afef;color:#61afef">${c.name} = ${c.expr} <a href="#" onclick="delComp(${i});return false">${ICONS.close}</a></span>`).join("") || "none";
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
function drawChart(key, pts) {
  const cv = $("cv-" + cssId(key)); if (!cv) return;
  const dpr = window.devicePixelRatio || 1, w = cv.clientWidth, h = cv.clientHeight;
  cv.width = w * dpr; cv.height = h * dpr;
  const ctx = cv.getContext("2d"); ctx.scale(dpr, dpr); ctx.clearRect(0, 0, w, h);
  if (pts.length < 2) return;
  const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
  const x0 = xs[0], x1 = xs[xs.length - 1], y0 = Math.min(...ys), y1 = Math.max(...ys);
  const sx = (x) => ((x - x0) / (x1 - x0 || 1)) * (w - 8) + 4;
  const sy = (y) => h - 6 - ((y - y0) / (y1 - y0 || 1)) * (h - 12);
  ctx.strokeStyle = cv.dataset.color; ctx.lineWidth = 1.5; ctx.beginPath();
  pts.forEach((p, i) => (i ? ctx.lineTo(sx(p[0]), sy(p[1])) : ctx.moveTo(sx(p[0]), sy(p[1]))));
  ctx.stroke();
  const vEl = $("cv-" + cssId(key) + "-v"); if (vEl) vEl.textContent = ys[ys.length - 1].toFixed(2);
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
  $("txState").textContent = t.running ? "running" : "stopped";
  $("txTable").querySelector("tbody").innerHTML = t.entries.map((e) => `
    <tr><td style="text-align:center"><input type="checkbox" ${e.enabled ? "checked" : ""} onchange="txToggle(${e.uid},this.checked)"/></td>
    <td>${e.name}</td><td class="mono">0x${e.id_hex}</td><td class="mono">${e.data}</td>
    <td>${e.cycle_ms} ms</td><td>${e.mode}</td><td>${e.count}</td>
    <td><button class="btn-mini" onclick="txOnce(${e.uid})">Send</button>
        <button class="btn-mini" onclick="txRemove(${e.uid})">${ICONS.close}</button></td></tr>`).join("");
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
  $("dashGroups").innerHTML = (d.groups || []).map((g) => `
    <div class="dash-group">
      <div class="dash-group-title">${g.group}</div>
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
$("btnDtcClearEcu").addEventListener("click", () => {
  if (!confirm("Send Mode 04 to CLEAR diagnostic trouble codes on the vehicle?\nThis erases stored DTCs and freeze-frame data.")) return;
  POST("/api/dtc/clear-ecu").then((r) => setStatus(r.ok ? "Sent Mode 04 clear request" : r.error));
});
async function pollDtc() {
  const d = await api("/api/dtc");
  $("dtcCount").textContent = (d.count || 0) + " codes";
  $("dtcEmpty").classList.toggle("hidden", (d.count || 0) > 0);
  $("dtcGroups").innerHTML = (d.groups || []).map((g) => `
    <div class="dash-group">
      <div class="dash-group-title">${g.group} · ${g.items.length}</div>
      ${g.items.map((it) => `
        <div class="dtc-card ${it.stale ? "stale" : ""}">
          <div class="dtc-code">${it.code}</div>
          <div class="dtc-body">
            <div class="dtc-desc">${it.desc || "<span style='color:var(--muted)'>no description</span>"}</div>
            ${it.status ? `<div class="dtc-status">${it.status}${it.oc !== undefined ? " · OC " + it.oc : ""}</div>` : ""}
          </div>
          <div class="dtc-seen">×${it.seen}</div>
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
      if (dl.state === "downloading") action = `downloading… ${pct}% <button class="btn-mini" onclick="driverPoll('${b.hw}')">refresh</button>`;
      else if (dl.state === "done" || dl.cached) action = `<button class="btn-mini" onclick="driverLaunch('${b.hw}')">Install now</button>`;
      else action = `<button class="btn-mini" onclick="driverDownload('${b.hw}')">Download & install (${r.approx_mb || "?"} MB)</button>`;
    }
    return `<div style="margin:4px 0"><b>${b.label}</b> — <span class="muted-line">${b.detail}</span><br>
      <span class="muted-line">${(r.note || "")}</span> ${action}</div>`;
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

// ----------------------------------- sidebar nav icons (consistent SVG set)
const _svgNav = (body) => `<svg class="nav-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${body}</svg>`;
const NAV_ICONS = {
  dashboard: _svgNav('<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/>'),
  logger: _svgNav('<line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/>'),
  replay: _svgNav('<polygon points="5 3 19 12 5 21 5 3"/>'),
  re: _svgNav('<polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>'),
  autore: _svgNav('<rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6"/><line x1="9" y1="1" x2="9" y2="4"/><line x1="15" y1="1" x2="15" y2="4"/><line x1="9" y1="20" x2="9" y2="23"/><line x1="15" y1="20" x2="15" y2="23"/><line x1="20" y1="9" x2="23" y2="9"/><line x1="20" y1="14" x2="23" y2="14"/><line x1="1" y1="9" x2="4" y2="9"/><line x1="1" y1="14" x2="4" y2="14"/>'),
  framedec: _svgNav('<rect x="3" y="3" width="18" height="18" rx="2"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="3" y1="15" x2="21" y2="15"/><line x1="9" y1="3" x2="9" y2="21"/><line x1="15" y1="3" x2="15" y2="21"/>'),
  convert: _svgNav('<polyline points="17 1 21 5 17 9"/><path d="M3 11V9a4 4 0 0 1 4-4h14"/><polyline points="7 23 3 19 7 15"/><path d="M21 13v2a4 4 0 0 1-4 4H3"/>'),
  dbc: _svgNav('<polygon points="12 2 2 7 12 12 22 7 12 2"/><polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/>'),
  oem: _svgNav('<ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"/><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/>'),
  signals: _svgNav('<polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/><polyline points="17 6 23 6 23 12"/>'),
  scheduler: _svgNav('<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>'),
  automation: _svgNav('<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>'),
  dtc: _svgNav('<path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>'),
  decoder: _svgNav('<polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/>'),
};
document.querySelectorAll(".nav").forEach((b) => {
  const ic = NAV_ICONS[b.dataset.view];
  const label = b.textContent.trim();
  if (ic) b.innerHTML = ic + `<span>${label}</span>`;
  b.title = label;            // tooltip — useful when the rail is collapsed
});

// ----------------------------------- icons on static action buttons (by id)
const BTN_ICONS = {
  btnPlay: [ICONS.play, "Play"], btnPause: [ICONS.pause, "Pause"],
  btnStop: [ICONS.stop, "Stop"], btnStep: [ICONS.step, "Step"],
  btnTxStart: [ICONS.play, "Start all"], btnTxStop: [ICONS.stop, "Stop"],
  btnRestbusStart: [ICONS.play, "Start"], btnRestbusStop: [ICONS.stop, "Stop"],
  btnScriptRun: [ICONS.play, "Run script"],
  btnReplayRescan: [ICONS.refresh, "Logs"], btnReRescan: [ICONS.refresh, "Logs"],
  btnAutoReRescan: [ICONS.refresh, "Logs"], btnOemRefresh: [ICONS.refresh, ""],
  btnRefreshDevs: [ICONS.refresh, "Rescan"], btnDbcToViewer: [ICONS.arrowRight, "Signal Viewer"],
  btnFdToggleFill: [ICONS.clipboard, "Paste frames"],
  btnDbcImport: [ICONS.upload, "Upload .dbc"], btnDbcExport: [ICONS.download, "Download .dbc"],
  btnSigImport: [ICONS.upload, "Upload .dbc"],
};
Object.entries(BTN_ICONS).forEach(([id, [ic, label]]) => {
  const el = $(id);
  if (!el) return;
  el.innerHTML = ic + (label ? `<span>${label}</span>` : "");
  el.classList.add("btn-ico");
});

// --------------------------- sidebar: simple open ↔ collapsed toggle (persisted)
// (auto-hide/hover-flyout mode is disabled for now — needs more work.)
const _appEl = document.querySelector(".app");
let navMode = "open";
function applyNavMode(mode) {
  navMode = mode === "rail" ? "rail" : "open";   // only two states supported
  _appEl.classList.toggle("nav-rail", navMode === "rail");
  $("navToggle").title = navMode === "rail" ? "Expand sidebar" : "Collapse sidebar";
  try { localStorage.setItem("ucando_nav_mode", navMode); } catch (e) {}
}
$("navToggle").addEventListener("click", () => applyNavMode(navMode === "rail" ? "open" : "rail"));
let _savedMode = "open";
try { _savedMode = localStorage.getItem("ucando_nav_mode") || "open"; } catch (e) {}
applyNavMode(_savedMode === "rail" ? "rail" : "open");   // legacy "auto" → open

// ===================== Animated idle / empty states ========================
// One self-contained CAN-bus SVG (no GIF, no library) reused across idle pages:
// ECU chip-nodes tapping a differential bus while data frames flow + nodes pulse.
const CAN_BUS_SVG = `<svg class="bus-anim" viewBox="0 0 440 200" role="img" aria-label="CAN bus animation">
  <line class="bus-line" x1="40" y1="112" x2="400" y2="112" stroke="var(--accent)" stroke-width="2.5"/>
  <line class="bus-line" x1="40" y1="120" x2="400" y2="120" stroke="var(--green)" stroke-width="2.5"/>
  <line class="bus-flow" x1="40" y1="112" x2="400" y2="112" stroke="var(--accent)" stroke-width="2.5"/>
  <line class="bus-flow" x1="40" y1="120" x2="400" y2="120" stroke="var(--green)" stroke-width="2.5"/>
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
  const css = getComputedStyle(document.documentElement);
  const pick = (v, d) => { const x = (css.getPropertyValue(v) || "").trim(); return x || d; };
  const C = { acc: pick("--accent", "#4ea1ff"), grn: pick("--green", "#46b86a"),
              mut: pick("--muted", "#8b9298"), line: pick("--line", "#2b2f36") };
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
      ctx.fillStyle = "rgba(255,255,255,.03)"; ctx.strokeStyle = C.acc; ctx.lineWidth = 1.5; rrect(b.x, b.y, b.w, b.h, 6); ctx.fill(); ctx.stroke();
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

const _SWAP_ICON = _ico('<polyline points="17 1 21 5 17 9"/><path d="M3 11V9a4 4 0 0 1 4-4h14"/><polyline points="7 23 3 19 7 15"/><path d="M21 13v2a4 4 0 0 1-4 4H3"/>');
function idleCard(c) {
  return `<button class="idle-card ${c.primary ? "primary" : ""}" onclick="${c.onclick}">
    <span class="ic-wrap">${c.icon}</span><h4>${c.title}</h4><p>${c.desc}</p></button>`;
}
function emptyHero(id, o) {
  const el = $(id); if (!el) return;
  const cards = (o.cards || []).map(idleCard).join("");
  el.innerHTML = `<div class="idle-hero">
    <div class="hero-stage"><canvas class="hero-canvas"></canvas></div>
    <div class="empty-anim-title">${o.title}</div>
    <div class="empty-anim-sub">${o.sub}</div>
    ${cards ? `<div class="idle-cards">${cards}</div>` : ""}
    ${o.tips ? `<div class="idle-tips">${o.tips.map((t) => `<span>${t}</span>`).join("")}</div>` : ""}
  </div>`;
  try { startHeroCanvas(el.querySelector(".hero-canvas")); }
  catch (e) { el.querySelector(".hero-stage").innerHTML = CAN_BUS_SVG; }   // graceful fallback
}
window.goView = (v) => { const b = document.querySelector(`.nav[data-view="${v}"]`); if (b) b.click(); };
window.quickConnectVirtual = async () => {
  setStatus("Connecting to virtual bus…");
  const r = await POST("/api/connect", { hw: "virtual", channel: "canforge", bitrate: 500000, simulate: true });
  setStatus(r && r.ok !== false ? "Virtual bus connected — streaming demo frames" : "Could not start virtual bus");
};
window.cvUploadClick = () => $("btnCvUpload").click();

emptyHero("dashEmpty", {
  title: "Waiting for live frames…",
  sub: "Connect a bus to start decoding standard protocols (OBD-II · J1939) — no DBC required.",
  cards: [
    { icon: ICON_POWER, title: "Try it now", desc: "Spin up the virtual bus with demo OBD-II + J1939 traffic.", onclick: "quickConnectVirtual()", primary: true },
    { icon: ICONS.grid, title: "Frame Decoder", desc: "Decode payloads against a DBC or Signature JSON.", onclick: "goView('framedec')" },
    { icon: _SWAP_ICON, title: "Converter", desc: "Convert DBC ⇄ JSON ⇄ CSV in any direction.", onclick: "goView('convert')" },
  ],
  tips: [
    "Tip: Frame Decoder → Trace mode highlights which signals change across many payloads.",
    "Tip: the Converter shows DBC/CSV IDs in hex and downloads a clean, sorted layout.",
    "Tip: no hardware? The virtual bus streams realistic CAN traffic for testing.",
  ],
});
emptyHero("cvEmpty", {
  title: "Convert & inspect CAN databases",
  sub: "Upload a DBC, cloud Signature JSON, CSV, or a CanPlus vehicle-library XML to preview its messages & signals — edit fields, pick the signals you want, and download in any format.",
  cards: [{ icon: ICONS.upload, title: "Upload file", desc: "DBC · JSON · CSV · CanPlus XML — auto-detected.", onclick: "cvUploadClick()", primary: true }],
});
emptyHero("dtcEmpty", {
  title: "No trouble codes",
  sub: "Connect a bus and Scan for OBD-II / UDS / J1939 codes. J1939 DM1 codes also appear passively.",
  cards: [{ icon: ICON_POWER, title: "Connect virtual bus", desc: "Stream demo frames to see the flow.", onclick: "quickConnectVirtual()", primary: true }],
});

// Initial header title/description + kick off polling for the Dashboard view.
setViewMeta(state.view);
startPolling(state.view);
