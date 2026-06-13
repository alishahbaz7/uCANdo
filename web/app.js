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
  re: "Reverse Engineering", dbc: "DBC Builder", signals: "Signal Viewer",
  scheduler: "TX Scheduler", dtc: "DTC — Diagnostic Trouble Codes", decoder: "Protocol Decoder",
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
  ["replaySelect", "reSelect"].forEach((id) => { if ($(id)) $(id).innerHTML = opts; });
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
$("btnAnalyze").addEventListener("click", async () => {
  const path = $("reSelect").value; if (!path) return;
  setStatus("Analyzing " + path + " …");
  const r = await POST("/api/re/analyze", { path });
  if (!r.ok) return void setStatus("RE error: " + r.error);
  lastRe = r.result; setStatus("Analysis complete");
  $("reSummary").textContent = `${r.result.id_count} IDs · ${r.result.total_frames} frames`;
  $("reTable").querySelector("tbody").innerHTML = r.result.ids.map((id, i) => {
    const ent = id.bytes.map((b) =>
      `<div class="ebyte" title="byte ${b.index}: ${b.kind}, H=${b.entropy}" style="background:${entropyColor(b.entropy)}">${b.entropy.toFixed(1)}</div>`).join("");
    const cands = id.candidates.map((c) => `${c.name}(${c.length}b)`).join(", ") || "—";
    return `<tr><td class="mono">0x${id.id_hex}</td><td>${id.frames}</td><td>${id.period_ms} ms</td>
      <td>${id.length}</td><td><div class="entropy-row">${ent}</div></td><td>${cands}</td>
      <td><button class="btn-mini" onclick="seedDbc(${i})">→ DBC</button></td></tr>`;
  }).join("");
});
window.seedDbc = async (i) => {
  if (!lastRe) return;
  await POST("/api/dbc/seed", lastRe.ids[i]);
  setStatus(`Sent 0x${lastRe.ids[i].id_hex} to DBC Builder`);
};

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
  if (!sigSelected.size) return;
  const res = await api("/api/signals/series?keys=" + encodeURIComponent([...sigSelected].join(",")));
  for (const key of sigSelected) drawChart(key, res.series[key] || []);
}
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

// Kick off polling for the initial (Dashboard) view.
startPolling(state.view);
