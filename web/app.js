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

const VIEW_TITLES = {
  dashboard: "Dashboard — Standard Decoded Values",
  logger: "CAN Logger — Live Capture", replay: "TX Replay — Log Playback",
  re: "Reverse Engineering", dbc: "DBC Builder", oem: "OEM CAN Database", signals: "Signal Viewer",
  scheduler: "TX Scheduler", automation: "Automation — Rules, Jobs, Restbus & Scripting",
  dtc: "DTC — Diagnostic Trouble Codes", decoder: "Protocol Decoder",
};

// ---------------------------------------------------------------- navigation
document.querySelectorAll(".nav").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".nav").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    const view = btn.dataset.view;
    state.view = view;
    document.querySelectorAll(".view").forEach((v) => v.classList.add("hidden"));
    $("view-" + view).classList.remove("hidden");
    $("viewTitle").textContent = VIEW_TITLES[view] || view;
    startPolling(view);
    if (view === "replay" || view === "re") refreshLogs();
    if (view === "dbc") renderDbc();
    if (view === "logger") loadLogDir();
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
  $("btnConnect").textContent = state.connected ? "⏼ Disconnect" : "⏻ Connect";
  $("btnRecord").disabled = !state.connected;
  $("btnRecord").dataset.on = state.recording ? "1" : "0";
  $("btnRecord").textContent = state.recording ? "■ Stop" : "● Record";
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
  ["replaySelect", "reSelect", "cmpA", "cmpB"].forEach((id) => { if ($(id)) $(id).innerHTML = opts; });
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
      <td><button class="btn-mini" onclick="seedDbc(${i})">→ DBC</button></td></tr>`;
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
      <td><button class="btn-mini" onclick="promoteChanged('${ns}','${c.id_hex}')">→ DBC</button></td></tr>`;
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
      <td><button class="btn-mini" onclick="promoteCorr('${d.id_hex}')">→ DBC</button></td></tr>`).join("")).join("");
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
      <td>${apply} <button class="btn-mini" onclick="oemDelete(${p.id})">✕</button></td></tr>`;
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
      <td><button class="btn-mini" onclick="delRule(${r.uid})">✕</button></td></tr>`).join("")
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
      <td><button class="btn-mini" onclick="runJob(${j.id})">Run</button> <button class="btn-mini" onclick="delJob(${j.id})">✕</button></td></tr>`).join("")
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
        <button class="btn-mini" onclick="dbcDelMsg(${mi})">✕</button>
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
        <td><button class="btn-mini" onclick="dbcDelSig(${mi},${si})">✕</button></td>
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
  const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = "canforge.dbc"; a.click();
});
$("btnDbcToViewer").addEventListener("click", async () => {
  const r = await POST("/api/signals/use-builder");
  setStatus(r.ok ? `Loaded ${r.signals.length} signals into Signal Viewer` : r.error);
});

// ------------------------------------------------------------- Signal Viewer
const sigSelected = new Set();
const SIG_COLORS = ["#4ea1ff", "#46b86a", "#e2a055", "#c46bde", "#e25555", "#3fc7c7", "#d4d04e"];
$("btnSigUseBuilder").addEventListener("click", async () => { await POST("/api/signals/use-builder"); refreshSigList(); });
$("btnSigImport").addEventListener("click", () => $("sigDbcFile").click());
$("sigDbcFile").addEventListener("change", async (e) => { const f = e.target.files[0]; if (f) { await apiUpload("/api/signals/import", f); refreshSigList(); } });
$("btnSigClear").addEventListener("click", () => POST("/api/signals/clear"));
async function refreshSigList() {
  const info = await api("/api/signals");
  $("sigStatus").textContent = info.loaded ? `${info.signals.length} signals · ${info.messages} messages` : "No DBC loaded";
  $("sigList").innerHTML = (info.signals || []).map((s, i) => `
    <label class="sig-item"><input type="checkbox" data-key="${s.key}" ${sigSelected.has(s.key) ? "checked" : ""} onchange="toggleSig('${s.key}')"/>
    <span class="sig-swatch" style="background:${SIG_COLORS[i % SIG_COLORS.length]}"></span>${s.key} ${s.unit ? "(" + s.unit + ")" : ""}</label>`).join("");
}
window.toggleSig = (key) => { sigSelected.has(key) ? sigSelected.delete(key) : sigSelected.add(key); renderChartShells(); };
function renderChartShells() {
  $("charts").innerHTML = [...sigSelected].map((k, i) => `
    <div class="chart-card"><div class="chart-title"><span>${k}</span><span id="cv-${cssId(k)}-v"></span></div>
    <canvas class="chart" id="cv-${cssId(k)}" data-key="${k}" data-color="${SIG_COLORS[i % SIG_COLORS.length]}"></canvas></div>`).join("");
}
const cssId = (k) => k.replace(/[^a-zA-Z0-9]/g, "_");
async function pollSignals() {
  pollDerived();
  if (!sigSelected.size) return;
  const res = await api("/api/signals/series?keys=" + encodeURIComponent([...sigSelected].join(",")));
  for (const key of sigSelected) drawChart(key, res.series[key] || []);
}

// ----- computed signals & alarms -----
let computedDefs = [], alarmDefs = [];
async function pollDerived() {
  const d = await api("/api/signals/derived");
  const active = (d.alarms || []).filter((a) => a.active);
  $("sigAlarmBanner").innerHTML = active.length
    ? `<span class="cand-chip" style="border-color:#e25555;color:#e25555">⚠ ${active.map((a) => a.name).join(", ")}</span>` : "";
  $("almList").innerHTML = (d.alarms || []).map((a, i) =>
    `<span class="cand-chip" style="border-color:${a.active ? "#e25555" : "#6b7280"};color:${a.active ? "#e25555" : "#9aa0a6"}">
      ${a.name} [${a.min ?? "−∞"},${a.max ?? "∞"}]${a.active ? " ⚠" : ""} <a href="#" onclick="delAlarm(${i});return false">✕</a></span>`).join("") || "none";
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
    `<span class="cand-chip" style="border-color:#61afef;color:#61afef">${c.name} = ${c.expr} <a href="#" onclick="delComp(${i});return false">✕</a></span>`).join("") || "none";
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
  setStatus("Added 5 OBD-II PID request rows — press ▶ Start all to begin polling.");
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
        <button class="btn-mini" onclick="txRemove(${e.uid})">✕</button></td></tr>`).join("");
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

// Kick off polling for the initial (Dashboard) view.
startPolling(state.view);
