"use strict";

const $ = (s) => document.querySelector(s);
const pad = (n) => String(n).padStart(2, "0");
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const state = { token: null, me: null, weekOffset: 0, users: [], newPasswords: [] };
try { state.token = localStorage.getItem("tt-token"); } catch (e) { /* storage blocked */ }

/* ---------- api ---------- */
async function api(path, opts = {}) {
  const headers = { ...(opts.body ? { "Content-Type": "application/json" } : {}), ...(state.token ? { Authorization: "Bearer " + state.token } : {}) };
  const res = await fetch(path, { ...opts, headers, body: opts.body ? JSON.stringify(opts.body) : undefined });
  if (res.status === 401 && state.token) { signOut(); throw new Error("Your session has expired. Sign in again."); }
  if (!res.ok) {
    let msg = "Something went wrong (" + res.status + ").";
    try { const j = await res.json(); if (typeof j.detail === "string") msg = j.detail; else if (Array.isArray(j.detail)) msg = j.detail.map((d) => d.msg).join(" "); } catch (e) {}
    throw new Error(msg);
  }
  return opts.raw ? res : res.json();
}
async function download(path) {
  try {
    const res = await api(path, { raw: true });
    const blob = await res.blob();
    const name = (res.headers.get("content-disposition") || "").match(/filename="([^"]+)"/)?.[1] || "export.csv";
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob); a.download = name; a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  } catch (e) { toast(e.message); }
}
function toast(msg) { const t = $("#toast"); t.textContent = msg; t.hidden = false; clearTimeout(toast.h); toast.h = setTimeout(() => (t.hidden = true), 3200); }
function showErr(el, msg) { el.textContent = msg; el.hidden = !msg; }

/* ---------- time helpers (browser local time) ---------- */
const d = (iso) => new Date(iso);
const ymd = (dt) => dt.getFullYear() + "-" + pad(dt.getMonth() + 1) + "-" + pad(dt.getDate());
const hm = (dt) => pad(dt.getHours()) + ":" + pad(dt.getMinutes());
const dur = (s) => { const m = Math.max(0, Math.round(s / 60)); return Math.floor(m / 60) + ":" + pad(m % 60); };
const clock = (s) => { s = Math.max(0, Math.floor(s)); return Math.floor(s / 3600) + ":" + pad(Math.floor(s / 60) % 60) + ":" + pad(s % 60); };
const dayName = (dt) => dt.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });
function weekStart(offset) { const t = new Date(); t.setHours(0, 0, 0, 0); t.setDate(t.getDate() - ((t.getDay() + 6) % 7) + offset * 7); return t; }
function addDays(dt, n) { const x = new Date(dt); x.setDate(x.getDate() + n); return x; }
const LOC = { office: "Office", remote: "Remote" };
const SOURCES = { agent: "Computer", phone: "Arrived at office", web: "Clock button", manual: "Correction" };

/* ---------- routing ---------- */
const VIEWS = ["login", "password", "me", "team", "people", "audit"];
function show(view) {
  VIEWS.forEach((v) => ($("#v-" + v).hidden = v !== view));
  $("#bar").hidden = !["me", "team", "people", "audit"].includes(view);
  document.querySelectorAll("#nav a").forEach((a) => a.classList.toggle("active", a.dataset.view === view));
}
function allowed(view) { const a = document.querySelector(`#nav a[data-view="${view}"]`); return a && !a.hidden; }
async function route() {
  if (!state.token) return show("login");
  if (!state.me) await loadMe();
  if (!state.me) return;
  if (state.me.user.must_change_password) return show("password");
  let view = location.hash.slice(1) || "me";
  if (!allowed(view)) view = "me";
  show(view);
  if (view === "me") loadMine();
  if (view === "team") loadTeam();
  if (view === "people") loadPeople();
  if (view === "audit") loadAudit();
}
window.addEventListener("hashchange", route);

async function loadMe() {
  try { state.me = await api("/api/me"); } catch (e) { toast(e.message); return; }
  const u = state.me.user;
  $("#companyName").textContent = state.me.company + " Time Tracking";
  document.title = state.me.company + " Time Tracking";
  $("#whoName").textContent = u.name;
  document.querySelectorAll("#nav a[data-role]").forEach((a) => (a.hidden = !a.dataset.role.split(" ").includes(u.role)));
}
function signOut() { state.token = null; state.me = null; try { localStorage.removeItem("tt-token"); } catch (e) {} location.hash = ""; show("login"); }
$("#logout").addEventListener("click", signOut);

$("#loginForm").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  try {
    const r = await api("/api/auth/login", { method: "POST", body: { email: $("#loginEmail").value, password: $("#loginPassword").value } });
    state.token = r.token; try { localStorage.setItem("tt-token", r.token); } catch (e) {}
    state.me = null; showErr($("#loginErr"), ""); $("#loginPassword").value = ""; route();
  } catch (e) { showErr($("#loginErr"), e.message); }
});
$("#pwForm").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  try {
    await api("/api/auth/change-password", { method: "POST", body: { current_password: $("#pwCurrent").value, new_password: $("#pwNew").value } });
    $("#pwCurrent").value = $("#pwNew").value = ""; state.me = null; toast("Password saved"); route();
  } catch (e) { showErr($("#pwErr"), e.message); }
});

/* ---------- my hours ---------- */
let tickTimer = null;
async function loadMine() {
  await loadMe();
  renderClock();
  const u = state.me.user;
  const dismissed = sessionStorage.getItem("tt-consent-later") === "1";
  $("#consentCard").hidden = u.consent || dismissed;
  $("#withdrawBtn").hidden = !u.consent;
  $("#trackStatus").textContent = u.consent
    ? "Automatic tracking is on. Linked computers clock you in when you start working and out after " + state.me.idle_timeout_minutes + " idle minutes."
    : "Automatic tracking is off. Accept the tracking notice to link a computer.";
  $("#pairBtn").disabled = !u.consent;
  $("#herePill").textContent = state.me.here === "office" ? "On office network" : "Working remotely";
  $("#herePill").className = "pill " + state.me.here;
  state.projects = await api("/api/me/projects").catch(() => []);
  fillLeaveTypes();
  const [summary, entries, corrections, devices, leave] = await Promise.all([
    api("/api/me/summary"), loadMyEntries(), api("/api/me/corrections"), api("/api/me/devices"),
    api("/api/me/leave").catch(() => null),
  ]).catch((e) => { toast(e.message); return []; });
  if (summary) renderSummary(summary);
  if (corrections) renderMyCorrections(corrections);
  if (devices) renderDevices(devices);
  if (leave) renderMyLeave(leave);
}

function renderClock() {
  const run = state.me.running;
  $("#clockCard").classList.toggle("on", !!run);
  $("#clockState").textContent = run ? "Working · " + LOC[run.location] + (run.source === "agent" ? " (automatic)" : "") : "Not working";
  $("#clockBtn").textContent = run ? "Clock out" : "Clock in";
  $("#clockBtn").className = "btn big " + (run ? "stop" : "primary");
  $("#clockSince").textContent = run ? "Since " + hm(d(run.start)) + ", " + dayName(d(run.start)) : "Clock in by hand, or let a linked computer do it for you.";
  clearInterval(tickTimer);
  const tick = () => ($("#timer").textContent = run ? clock((Date.now() - d(run.start)) / 1000) : "0:00:00");
  tick(); if (run) tickTimer = setInterval(tick, 1000);
}
$("#clockBtn").addEventListener("click", async () => {
  try {
    if (state.me.running) { const e = await api("/api/me/clock-out", { method: "POST" }); toast("Clocked out · " + dur(e.worked_seconds) + " logged"); }
    else { await api("/api/me/clock-in", { method: "POST", body: { note: $("#clockNote").value } }); toast("Clocked in"); $("#clockNote").value = ""; }
    loadMine();
  } catch (e) { toast(e.message); }
});

function renderSummary(s) {
  $("#sToday").textContent = dur(s.today); $("#sWeek").textContent = dur(s.week); $("#sMonth").textContent = dur(s.month);
  $("#sTarget").textContent = "of " + s.weekly_target_hours + " h";
  $("#sProgress").style.width = Math.min(100, (s.week / 3600 / (s.weekly_target_hours || 40)) * 100) + "%";
  const daily = (s.weekly_target_hours || 40) / 5;
  const max = Math.max(daily, ...s.week_days.map((x) => (x.office + x.remote) / 3600), 1) * 1.1;
  const today = ymd(new Date());
  $("#weekBars").innerHTML = s.week_days.map((x) => {
    const dt = new Date(x.date + "T00:00:00"), tot = x.office + x.remote;
    const seg = (k) => (x[k] ? `<span class="bg-${k}" style="height:${(x[k] / 3600 / max) * 100}%" title="${LOC[k]} ${dur(x[k])}"></span>` : "");
    return `<div class="wb${x.date === today ? " today" : ""}"><span class="muted mono">${tot ? dur(tot) : "–"}</span><div class="stack2">${seg("office")}${seg("remote")}</div><b>${dt.toLocaleDateString(undefined, { weekday: "short" })}</b></div>`;
  }).join("");
}

async function loadMyEntries() {
  const ws = weekStart(state.weekOffset), we = addDays(ws, 6);
  $("#myRange").textContent = dayName(ws) + " – " + dayName(we);
  $("#myNext").disabled = state.weekOffset >= 0;
  const rows = await api(`/api/me/entries?start=${ymd(ws)}&end=${ymd(we)}`);
  const t = $("#myTable");
  if (!rows.length) { t.innerHTML = `<tr><td><div class="empty">No hours in this week yet.</div></td></tr>`; return rows; }
  const projOpts = (e) => `<option value="">No project</option>` + (state.projects || []).map((p) => `<option value="${p.id}"${p.id === e.project_id ? " selected" : ""}>${esc(p.name)}</option>`).join("");
  t.innerHTML = `<thead><tr><th>Day</th><th>Time</th><th>Where</th><th>How</th><th>Project</th><th class="n">Break</th><th class="n">Hours</th><th>Note</th><th></th></tr></thead><tbody>` +
    rows.slice().reverse().map((e) => {
      const s = d(e.start), en = e.end ? d(e.end) : null;
      const draft = ["agent", "phone"].includes(e.source) && !e.confirmed && !e.running;
      return `<tr><td>${dayName(s)}</td><td class="mono">${hm(s)} – ${en ? hm(en) : "now"}</td>
        <td><span class="pill ${e.location}">${LOC[e.location]}</span></td>
        <td class="small muted">${SOURCES[e.source] || e.source}${e.status === "review" ? ' <span class="pill warn">Review</span>' : ""}${draft ? ` <span class="pill warn">Draft</span> <button class="link small" data-confirm-entry="${e.id}">Confirm</button>` : ""}</td>
        <td><select data-proj-for="${e.id}" aria-label="Project">${projOpts(e)}</select></td>
        <td class="n mono">${e.break_minutes ? e.break_minutes + "m" : "–"}</td><td class="n mono">${dur(e.worked_seconds)}</td>
        <td class="small">${esc(e.note)}</td>
        <td>${e.running ? "" : `<button class="link small" data-fix="${e.id}">Fix</button> <button class="link small" data-remove="${e.id}">Remove</button>`}</td></tr>`;
    }).join("") + "</tbody>";
  t._rows = rows;
  return rows;
}
$("#myTable").addEventListener("change", async (ev) => {
  const id = ev.target.dataset.projFor; if (!id) return;
  const v = ev.target.value;
  try { await api("/api/me/entries/" + id, { method: "PATCH", body: v ? { project_id: Number(v) } : { clear_project: true } }); toast("Project saved"); } catch (e) { toast(e.message); }
});
$("#myPrev").addEventListener("click", () => { state.weekOffset--; loadMyEntries().catch((e) => toast(e.message)); });
$("#myNext").addEventListener("click", () => { if (state.weekOffset < 0) { state.weekOffset++; loadMyEntries().catch((e) => toast(e.message)); } });
$("#myExport").addEventListener("click", () => { const ws = weekStart(state.weekOffset); download(`/api/me/export.csv?start=${ymd(ws)}&end=${ymd(addDays(ws, 6))}`); });

function resetCorrection() {
  $("#corrKind").value = "add"; $("#corrEntry").value = "";
  $("#corrDate").value = ymd(new Date()); $("#corrStart").value = "09:00"; $("#corrEnd").value = "18:00";
  $("#corrBreak").value = 60; $("#corrLoc").value = "office"; $("#corrReason").value = "";
  $("#corrTitle").textContent = "Request a correction"; $("#corrSubmit").textContent = "Send request"; $("#corrCancel").hidden = true;
  ["#corrDate", "#corrStart", "#corrEnd", "#corrBreak", "#corrLoc"].forEach((s) => ($(s).disabled = false));
  showErr($("#corrErr"), "");
}
$("#corrCancel").addEventListener("click", resetCorrection);
$("#myTable").addEventListener("click", async (ev) => {
  const conf = ev.target.closest("[data-confirm-entry]");
  if (conf) { try { await api("/api/me/entries/" + conf.dataset.confirmEntry, { method: "PATCH", body: { confirmed: true } }); toast("Confirmed"); loadMyEntries(); } catch (e) { toast(e.message); } return; }
  const fix = ev.target.closest("[data-fix]"), rm = ev.target.closest("[data-remove]");
  const id = Number((fix || rm)?.dataset.fix || (fix || rm)?.dataset.remove);
  const e = ($("#myTable")._rows || []).find((x) => x.id === id);
  if (!e) return;
  resetCorrection();
  const s = d(e.start), en = d(e.end);
  $("#corrEntry").value = e.id; $("#corrDate").value = ymd(s); $("#corrStart").value = hm(s); $("#corrEnd").value = hm(en);
  $("#corrBreak").value = e.break_minutes; $("#corrLoc").value = e.location; $("#corrCancel").hidden = false;
  if (fix) { $("#corrKind").value = "edit"; $("#corrTitle").textContent = "Fix this entry"; $("#corrSubmit").textContent = "Send fix request"; }
  else {
    $("#corrKind").value = "delete"; $("#corrTitle").textContent = "Remove this entry"; $("#corrSubmit").textContent = "Send removal request";
    ["#corrDate", "#corrStart", "#corrEnd", "#corrBreak", "#corrLoc"].forEach((s2) => ($(s2).disabled = true));
  }
  $("#corrForm").scrollIntoView({ behavior: "smooth", block: "center" }); $("#corrReason").focus({ preventScroll: true });
});
$("#corrForm").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const kind = $("#corrKind").value;
  const [y, m, dd] = $("#corrDate").value.split("-").map(Number);
  const mk = (t) => { const [h, mi] = t.split(":").map(Number); return new Date(y, m - 1, dd, h, mi); };
  let start = mk($("#corrStart").value), end = mk($("#corrEnd").value);
  if (end <= start) end = addDays(end, 1); // shift past midnight
  const body = { kind, reason: $("#corrReason").value, entry_id: Number($("#corrEntry").value) || null };
  if (kind !== "delete") Object.assign(body, { start: start.toISOString(), end: end.toISOString(), break_minutes: Number($("#corrBreak").value) || 0, location: $("#corrLoc").value });
  try { await api("/api/me/corrections", { method: "POST", body }); toast("Request sent to your manager"); resetCorrection(); renderMyCorrections(await api("/api/me/corrections")); }
  catch (e) { showErr($("#corrErr"), e.message); }
});
function correctionText(c) {
  if (c.kind === "delete") return "Remove entry";
  const s = d(c.start), en = d(c.end);
  return (c.kind === "add" ? "Add " : "Change to ") + dayName(s) + ", " + hm(s) + "–" + hm(en) + (c.break_minutes ? " (" + c.break_minutes + "m break)" : "") + ", " + LOC[c.location];
}
const statusPill = (s) => `<span class="pill ${{ pending: "warn", approved: "ok", rejected: "bad" }[s]}">${s[0].toUpperCase() + s.slice(1)}</span>`;
function renderMyCorrections(rows) {
  $("#myCorrections").innerHTML = rows.length ? rows.slice(0, 8).map((c) => `<div class="item"><div class="top"><b>${esc(correctionText(c))}</b>${statusPill(c.status)}</div>
    <span class="small muted">${esc(c.reason)}${c.reviewer_note ? " · Manager: " + esc(c.reviewer_note) : ""}</span></div>`).join("") : `<div class="empty small">No requests yet.</div>`;
}

function renderDevices(rows) {
  $("#deviceList").innerHTML = rows.length ? rows.map((x) => `<div class="item"><div class="top"><b>${esc(x.name)}</b><button class="link small" data-unpair="${x.id}">Unlink</button></div>
    <span class="small muted">${esc(x.platform || "")} · last seen ${x.last_seen_at ? dayName(d(x.last_seen_at)) + " " + hm(d(x.last_seen_at)) : "never"}</span></div>`).join("") : `<div class="empty small">No computers linked.</div>`;
}
$("#deviceList").addEventListener("click", async (ev) => {
  const b = ev.target.closest("[data-unpair]"); if (!b) return;
  if (b.dataset.confirm !== "1") { b.dataset.confirm = "1"; b.textContent = "Confirm unlink"; return; }
  try { await api("/api/me/devices/" + b.dataset.unpair, { method: "DELETE" }); toast("Computer unlinked"); renderDevices(await api("/api/me/devices")); } catch (e) { toast(e.message); }
});
$("#pairBtn").addEventListener("click", async () => {
  try {
    const r = await api("/api/me/pairing-code", { method: "POST" });
    $("#pairCode").textContent = r.code; $("#pairCode2").textContent = r.code; $("#pairServer").textContent = location.origin; $("#pairBox").hidden = false;
  } catch (e) { toast(e.message); }
});
$("#consentYes").addEventListener("click", async () => { try { await api("/api/me/consent", { method: "POST", body: { accept: true } }); toast("Automatic tracking is on"); loadMine(); } catch (e) { toast(e.message); } });
$("#consentLater").addEventListener("click", () => { sessionStorage.setItem("tt-consent-later", "1"); $("#consentCard").hidden = true; });
$("#withdrawBtn").addEventListener("click", async (ev) => {
  const b = ev.currentTarget;
  if (b.dataset.confirm !== "1") { b.dataset.confirm = "1"; b.textContent = "Click again to stop automatic tracking"; return; }
  b.dataset.confirm = ""; b.textContent = "Withdraw consent and stop automatic tracking";
  try { await api("/api/me/consent", { method: "POST", body: { accept: false } }); sessionStorage.setItem("tt-consent-later", "1"); toast("Automatic tracking stopped"); loadMine(); } catch (e) { toast(e.message); }
});

/* ---------- time off ---------- */
function leaveTypes() { return (state.me && state.me.leave_types) || []; }
function fillLeaveTypes() {
  const sel = $("#lType");
  if (!sel || sel.dataset.filled === "1") return;
  sel.innerHTML = leaveTypes().map((t) => `<option value="${t.key}">${esc(t.label)}</option>`).join("");
  sel.dataset.filled = "1";
  updateLeaveFields();
}
function updateLeaveFields() {
  const t = leaveTypes().find((x) => x.key === $("#lType").value);
  const hourly = t && t.unit === "hours";
  $("#lHoursWrap").hidden = !hourly;
  $("#lHalfWrap").hidden = !!hourly;
  if (hourly) { $("#lEnd").value = $("#lStart").value; }
}
function leaveText(r) {
  if (r.unit === "hours") return `${r.type_label}: ${r.hours}h on ${r.start_date}`;
  const span = r.start_date === r.end_date ? r.start_date + (r.half_day ? " (half day)" : "") : `${r.start_date} – ${r.end_date}`;
  return `${r.type_label}: ${span} · ${r.days} ${r.days === 1 ? "day" : "days"}`;
}
function renderMyLeave(data) {
  const b = data.balance;
  $("#leaveBalance").textContent = `Annual leave: ${b.remaining_days} of ${b.entitlement_days} days left${b.pending_days ? " · " + b.pending_days + " pending" : ""}`;
  const rows = data.requests || [];
  $("#myLeave").innerHTML = rows.length ? rows.slice(0, 10).map((r) => `<div class="item"><div class="top"><b>${esc(leaveText(r))}</b>${statusPill(r.status)}</div>
    <span class="small muted">${r.reason ? esc(r.reason) + " · " : ""}${r.reviewer_note ? "Manager: " + esc(r.reviewer_note) + " · " : ""}${(r.status === "pending" || r.status === "approved") ? `<button class="link" data-cancel-leave="${r.id}">Cancel</button>` : ""}</span></div>`).join("") : `<div class="empty small">No requests yet.</div>`;
}
$("#lType").addEventListener("change", updateLeaveFields);
$("#lStart").addEventListener("change", () => { if (!$("#lEnd").value || $("#lEnd").value < $("#lStart").value) $("#lEnd").value = $("#lStart").value; });
$("#leaveForm").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  showErr($("#leaveErr"), "");
  const t = leaveTypes().find((x) => x.key === $("#lType").value);
  const body = { type: $("#lType").value, start_date: $("#lStart").value, end_date: $("#lEnd").value,
    half_day: !$("#lHalfWrap").hidden && $("#lHalf").checked, hours: t && t.unit === "hours" ? Number($("#lHours").value) : 0,
    reason: $("#lReason").value };
  try {
    await api("/api/me/leave", { method: "POST", body });
    toast("Request sent to your manager");
    $("#lReason").value = ""; $("#lHalf").checked = false;
    renderMyLeave(await api("/api/me/leave"));
  } catch (e) { showErr($("#leaveErr"), e.message); }
});
$("#myLeave").addEventListener("click", async (ev) => {
  const b = ev.target.closest("[data-cancel-leave]"); if (!b) return;
  if (b.dataset.confirm !== "1") { b.dataset.confirm = "1"; b.textContent = "Confirm cancel"; return; }
  try { await api(`/api/me/leave/${b.dataset.cancelLeave}/cancel`, { method: "POST" }); toast("Request cancelled"); renderMyLeave(await api("/api/me/leave")); } catch (e) { toast(e.message); }
});

/* ---------- team ---------- */
function teamRange() {
  if (!$("#tFrom").value) { const ws = weekStart(0); $("#tFrom").value = ymd(ws); $("#tTo").value = ymd(addDays(ws, 6)); }
  const dept = $("#tDept").value;
  return `start=${$("#tFrom").value}&end=${$("#tTo").value}${dept ? "&department=" + encodeURIComponent(dept) : ""}`;
}
async function loadTeam() {
  try {
    const [live, summary, pending, leave] = await Promise.all([api("/api/team/live"), api("/api/team/summary?" + teamRange()), api("/api/team/corrections"), api("/api/team/leave").catch(() => [])]);
    $("#liveCount").textContent = live.working + " of " + live.total + " working";
    $("#liveGrid").innerHTML = live.people.map((p) => `<div class="person${p.working ? "" : " off"}"><b>${esc(p.user.name)}</b>
      <span class="small muted">${esc(p.user.department || "")}</span>
      <span class="small">${p.working ? `<span class="pill ${p.location}">${LOC[p.location]}</span> since ${hm(d(p.since))}${["agent", "phone"].includes(p.source) ? " · auto" : ""}` : "Not working"}</span></div>`).join("") || `<div class="empty">No one on your team yet.</div>`;
    const sel = $("#tDept"), cur = sel.value;
    sel.innerHTML = `<option value="">All</option>` + summary.departments.map((x) => `<option${x === cur ? " selected" : ""}>${esc(x)}</option>`).join("");
    renderTeamTable(summary.rows);
    const projTotal = summary.projects.reduce((a, p) => a + p.seconds, 0) || 1;
    $("#projTotals").innerHTML = summary.projects.length ? `<h3>By project</h3>` + summary.projects.map((p) => `<div class="item"><div class="top"><span><i class="sw" style="background:${esc(p.color)}"></i>${esc(p.name)}</span><b class="mono">${dur(p.seconds)}</b></div><div class="bar-mini"><span style="width:${(p.seconds / projTotal) * 100}%;background:${esc(p.color)}"></span></div></div>`).join("") : "";
    $("#pendingCount").hidden = !pending.length; $("#pendingCount").textContent = pending.length + " waiting";
    $("#pendingList").innerHTML = pending.length ? pending.map((c) => `<div class="item"><div class="top"><b>${esc(c.user_name)}: ${esc(correctionText(c))}</b>
      <span class="row-btns"><button class="btn small primary" data-approve="${c.id}">Approve</button><button class="btn small danger" data-reject="${c.id}">Reject</button></span></div>
      <span class="small muted">${esc(c.reason)} · asked ${dayName(d(c.created_at))}</span></div>`).join("") : `<div class="empty small">Nothing waiting. Corrections from your team appear here.</div>`;
    $("#leavePendingCount").hidden = !leave.length; $("#leavePendingCount").textContent = leave.length + " waiting";
    $("#teamLeaveList").innerHTML = leave.length ? leave.map((r) => `<div class="item"><div class="top"><b>${esc(r.user_name)}: ${esc(leaveText(r))}</b>
      <span class="row-btns"><button class="btn small primary" data-leave-approve="${r.id}">Approve</button><button class="btn small danger" data-leave-reject="${r.id}">Reject</button></span></div>
      ${r.reason ? `<span class="small muted">${esc(r.reason)}</span>` : ""}</div>`).join("") : `<div class="empty small">Nothing waiting. Time-off requests from your team appear here.</div>`;
  } catch (e) { toast(e.message); }
}
$("#teamLeaveList").addEventListener("click", async (ev) => {
  const a = ev.target.closest("[data-leave-approve]"), r = ev.target.closest("[data-leave-reject]");
  const b = a || r; if (!b) return;
  const id = (a || r).dataset.leaveApprove || (a || r).dataset.leaveReject;
  try { await api(`/api/team/leave/${id}/${a ? "approve" : "reject"}`, { method: "POST", body: { note: "" } }); toast(a ? "Approved" : "Rejected"); loadTeam(); } catch (e) { toast(e.message); }
});
function renderTeamTable(rows) {
  $("#teamTable").innerHTML = rows.length ? `<thead><tr><th>Name</th><th>Code</th><th>Department</th><th class="n">Office</th><th class="n">Remote</th><th class="n">Total</th><th class="n">Target</th><th class="n">Days</th><th></th></tr></thead><tbody>` +
    rows.map((r) => {
      const tot = r.total_seconds || 1;
      return `<tr class="clickable" data-person="${r.user.id}" data-name="${esc(r.user.name)}"><td><b>${esc(r.user.name)}</b></td><td class="mono small">${esc(r.user.employee_code || "")}</td><td>${esc(r.user.department || "")}</td>
      <td class="n mono">${dur(r.office_seconds)}</td><td class="n mono">${dur(r.remote_seconds)}</td><td class="n mono"><b>${dur(r.total_seconds)}</b></td>
      <td class="n mono muted">${dur(r.target_seconds)}</td><td class="n mono">${r.days_worked}</td>
      <td>${r.unconfirmed ? '<span class="pill">' + r.unconfirmed + " unconfirmed</span>" : ""}<div class="bar-mini"><span class="bg-office" style="width:${(r.office_seconds / tot) * 100}%"></span><span class="bg-remote" style="width:${(r.remote_seconds / tot) * 100}%"></span></div>${r.needs_review ? '<span class="pill warn">' + r.needs_review + " to review</span>" : ""}</td></tr>`;
    }).join("") + "</tbody>" : `<tr><td><div class="empty">No people in this view.</div></td></tr>`;
}
["#tFrom", "#tTo", "#tDept"].forEach((s) => $(s).addEventListener("change", loadTeam));
$("#tExportSum").addEventListener("click", () => download("/api/team/export.csv?kind=summary&" + teamRange()));
$("#tExportAll").addEventListener("click", () => download("/api/team/export.csv?kind=entries&" + teamRange()));
$("#teamTable").addEventListener("click", async (ev) => {
  const tr = ev.target.closest("[data-person]"); if (!tr) return;
  try {
    const rows = await api(`/api/team/entries?user_id=${tr.dataset.person}&start=${$("#tFrom").value}&end=${$("#tTo").value}`);
    $("#personName").textContent = tr.dataset.name; $("#personDetail").hidden = false;
    $("#personTable").innerHTML = rows.length ? `<thead><tr><th>Day</th><th>Time</th><th>Where</th><th>How</th><th class="n">Hours</th><th>Note</th></tr></thead><tbody>` +
      rows.map((e) => `<tr><td>${dayName(d(e.start))}</td><td class="mono">${hm(d(e.start))} – ${e.end ? hm(d(e.end)) : "now"}</td><td><span class="pill ${e.location}">${LOC[e.location]}</span></td>
      <td class="small muted">${SOURCES[e.source] || e.source}${e.project ? " · " + esc(e.project.name) : ""}${e.status === "review" ? ' <span class="pill warn">Review</span>' : ""}</td><td class="n mono">${dur(e.worked_seconds)}</td><td class="small">${esc(e.note)}</td></tr>`).join("") + "</tbody>"
      : `<tr><td><div class="empty">No entries in this range.</div></td></tr>`;
    $("#personDetail").scrollIntoView({ behavior: "smooth", block: "nearest" });
  } catch (e) { toast(e.message); }
});
$("#personClose").addEventListener("click", () => ($("#personDetail").hidden = true));
$("#pendingList").addEventListener("click", async (ev) => {
  const a = ev.target.closest("[data-approve]"), r = ev.target.closest("[data-reject]");
  if (!a && !r) return;
  const id = (a || r).dataset.approve || (a || r).dataset.reject;
  try { await api(`/api/team/corrections/${id}/${a ? "approve" : "reject"}`, { method: "POST", body: { note: "" } }); toast(a ? "Approved" : "Rejected"); loadTeam(); } catch (e) { toast(e.message); }
});

/* ---------- people (admin) ---------- */
async function loadPeople() {
  try { state.users = await api("/api/admin/users"); } catch (e) { toast(e.message); return; }
  loadProjectsAdmin(); loadOfficesAdmin();
  const managers = state.users.filter((u) => u.active && u.role !== "worker");
  $("#aManager").innerHTML = `<option value="">None</option>` + managers.map((u) => `<option value="${esc(u.email)}">${esc(u.name)}</option>`).join("");
  $("#deptList").innerHTML = [...new Set(state.users.map((u) => u.department).filter(Boolean))].map((x) => `<option value="${esc(x)}">`).join("");
  renderPeople();
}
function renderPeople() {
  const q = $("#peopleSearch").value.trim().toLowerCase();
  const rows = state.users.filter((u) => !q || [u.name, u.email, u.department, u.employee_code].join(" ").toLowerCase().includes(q));
  const mgrOpts = (u) => `<option value="">None</option>` + state.users.filter((m) => m.active && m.role !== "worker" && m.id !== u.id).map((m) => `<option value="${m.id}"${m.id === u.manager_id ? " selected" : ""}>${esc(m.name)}</option>`).join("");
  $("#peopleTable").innerHTML = `<thead><tr><th>Name</th><th>Email</th><th>Code</th><th>Department</th><th>Role</th><th>Manager</th><th>Tracking</th><th></th></tr></thead><tbody>` +
    rows.map((u) => `<tr class="${u.active ? "" : "inactive"}"><td><b>${esc(u.name)}</b></td><td class="small">${esc(u.email)}</td><td class="mono small">${esc(u.employee_code || "")}</td><td>${esc(u.department || "")}</td>
      <td><select data-role-for="${u.id}" aria-label="Role">${["worker", "manager", "admin"].map((r) => `<option${r === u.role ? " selected" : ""}>${r}</option>`).join("")}</select></td>
      <td><select data-mgr-for="${u.id}" aria-label="Manager">${mgrOpts(u)}</select></td>
      <td>${u.consent ? '<span class="pill ok">Automatic</span>' : '<span class="pill">By hand</span>'}</td>
      <td class="row-btns"><button class="link small" data-reset="${u.id}">Reset password</button> <button class="link small" data-toggle="${u.id}">${u.active ? "Deactivate" : "Reactivate"}</button></td></tr>`).join("") + "</tbody>";
}
$("#peopleSearch").addEventListener("input", renderPeople);
$("#peopleTable").addEventListener("change", async (ev) => {
  const role = ev.target.dataset.roleFor, mgr = ev.target.dataset.mgrFor;
  if (!role && !mgr) return;
  const id = role || mgr;
  const body = role ? { role: ev.target.value } : ev.target.value ? { manager_id: Number(ev.target.value) } : { clear_manager: true };
  try { await api("/api/admin/users/" + id, { method: "PATCH", body }); toast("Saved"); loadPeople(); } catch (e) { toast(e.message); loadPeople(); }
});
$("#peopleTable").addEventListener("click", async (ev) => {
  const reset = ev.target.closest("[data-reset]"), tog = ev.target.closest("[data-toggle]");
  const b = reset || tog; if (!b) return;
  if (b.dataset.confirm !== "1") { b.dataset.confirm = "1"; b.textContent = "Confirm"; return; }
  try {
    if (reset) { const r = await api(`/api/admin/users/${reset.dataset.reset}/reset-password`, { method: "POST" }); const u = state.users.find((x) => x.id === Number(reset.dataset.reset)); showPasswords([{ name: u.name, email: u.email, temporary_password: r.temporary_password }], []); }
    else { const u = state.users.find((x) => x.id === Number(tog.dataset.toggle)); await api("/api/admin/users/" + u.id, { method: "PATCH", body: { active: !u.active } }); toast(u.active ? "Deactivated" : "Reactivated"); }
    loadPeople();
  } catch (e) { toast(e.message); loadPeople(); }
});
$("#addForm").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  try {
    const r = await api("/api/admin/users", { method: "POST", body: { name: $("#aName").value, email: $("#aEmail").value, employee_code: $("#aCode").value || null, department: $("#aDept").value || null, role: $("#aRole").value, manager_email: $("#aManager").value || null } });
    showPasswords([{ name: r.user.name, email: r.user.email, temporary_password: r.temporary_password }], []);
    $("#addForm").reset(); showErr($("#addErr"), ""); loadPeople();
  } catch (e) { showErr($("#addErr"), e.message); }
});
$("#importFile").addEventListener("change", async (ev) => { const f = ev.target.files[0]; if (f) $("#importText").value = await f.text(); ev.target.value = ""; });
$("#importBtn").addEventListener("click", async () => {
  try {
    const r = await api("/api/admin/users/import", { method: "POST", body: { csv_text: $("#importText").value } });
    showPasswords(r.created, r.errors); toast(r.created.length + " added" + (r.errors.length ? ", " + r.errors.length + " skipped" : ""));
    if (r.created.length) $("#importText").value = "";
    loadPeople();
  } catch (e) { toast(e.message); }
});
function showPasswords(created, errors) {
  state.newPasswords = created.concat(state.newPasswords);
  $("#passwordsCard").hidden = false;
  $("#pwTable").innerHTML = `<thead><tr><th>Name</th><th>Email</th><th>Temporary password</th></tr></thead><tbody>` +
    state.newPasswords.map((p) => `<tr><td>${esc(p.name)}</td><td>${esc(p.email)}</td><td class="mono">${esc(p.temporary_password)}</td></tr>`).join("") + "</tbody>";
  $("#importErrors").innerHTML = errors.map((e) => `<div>${esc(e.row)}: ${esc(e.error)}</div>`).join("");
}
$("#pwExport").addEventListener("click", () => {
  const csv = "﻿name,email,temporary_password\r\n" + state.newPasswords.map((p) => [p.name, p.email, p.temporary_password].map((v) => '"' + String(v).replace(/"/g, '""') + '"').join(",")).join("\r\n");
  const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" })); a.download = "temporary-passwords.csv"; a.click();
});

async function loadProjectsAdmin() {
  try {
    const rows = await api("/api/admin/projects");
    $("#projList").innerHTML = rows.length ? rows.map((p) => `<div class="item"><div class="top"><span><i class="sw" style="background:${esc(p.color)}"></i><b>${esc(p.name)}</b>${p.client ? ' <span class="muted small">' + esc(p.client) + "</span>" : ""}</span>
      <button class="link small" data-proj-toggle="${p.id}" data-active="${p.active}">${p.active ? "Archive" : "Restore"}</button></div></div>`).join("") : `<div class="empty small">No projects yet.</div>`;
  } catch (e) { toast(e.message); }
}
$("#projForm").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  try { await api("/api/admin/projects", { method: "POST", body: { name: $("#pName").value, client: $("#pClient").value || null, color: $("#pColor").value } }); $("#pName").value = $("#pClient").value = ""; toast("Project added"); loadProjectsAdmin(); } catch (e) { toast(e.message); }
});
$("#projList").addEventListener("click", async (ev) => {
  const b = ev.target.closest("[data-proj-toggle]"); if (!b) return;
  try { await api("/api/admin/projects/" + b.dataset.projToggle, { method: "PATCH", body: { active: b.dataset.active !== "true" } }); loadProjectsAdmin(); } catch (e) { toast(e.message); }
});
async function loadOfficesAdmin() {
  try {
    const rows = await api("/api/admin/offices");
    $("#officeList").innerHTML = rows.length ? rows.map((o) => `<div class="item"><div class="top"><b>${esc(o.name)}</b><button class="link small" data-office-toggle="${o.id}" data-active="${o.active}">${o.active ? "Turn off" : "Turn on"}</button></div>
      <span class="small muted mono">${o.latitude.toFixed(5)}, ${o.longitude.toFixed(5)} · ${o.radius_m} m${o.active ? "" : " · off"}</span>
      <a class="small" href="https://www.google.com/maps?q=${o.latitude},${o.longitude}" target="_blank" rel="noopener">Check on map</a></div>`).join("") : `<div class="empty small">No office areas yet. Add one so the phone app can check people in.</div>`;
  } catch (e) { toast(e.message); }
}
$("#officeForm").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  try {
    await api("/api/admin/offices", { method: "POST", body: { name: $("#oName").value, latitude: Number($("#oLat").value), longitude: Number($("#oLon").value), radius_m: Number($("#oRadius").value) || 150 } });
    $("#officeForm").reset(); showErr($("#officeErr"), ""); toast("Office area added"); loadOfficesAdmin();
  } catch (e) { showErr($("#officeErr"), e.message); }
});
$("#officeList").addEventListener("click", async (ev) => {
  const b = ev.target.closest("[data-office-toggle]"); if (!b) return;
  try { await api("/api/admin/offices/" + b.dataset.officeToggle, { method: "PATCH", body: { active: b.dataset.active !== "true" } }); loadOfficesAdmin(); } catch (e) { toast(e.message); }
});

/* ---------- audit ---------- */
const ACTIONS = { consent_given: "Accepted automatic tracking", consent_withdrawn: "Withdrew automatic tracking", device_paired: "Linked a device", device_removed: "Unlinked a device",
  correction_requested: "Requested a correction", correction_approved: "Approved a correction", correction_rejected: "Rejected a correction", export: "Exported a timesheet",
  user_created: "Created an account", user_updated: "Changed an account", password_reset: "Reset a password", password_changed: "Changed own password", project_created: "Added a project", project_updated: "Changed a project",
  office_created: "Added an office area", office_updated: "Changed an office area" };
async function loadAudit() {
  try {
    const rows = await api("/api/admin/audit");
    $("#auditTable").innerHTML = `<thead><tr><th>When</th><th>Who</th><th>What</th><th>For</th><th>Details</th></tr></thead><tbody>` +
      rows.map((r) => `<tr><td class="mono small">${dayName(d(r.at))} ${hm(d(r.at))}</td><td>${esc(r.actor || "System")}</td><td>${esc(ACTIONS[r.action] || r.action)}</td><td>${esc(r.target || "")}</td><td class="mono small">${esc(JSON.stringify(r.detail))}</td></tr>`).join("") + "</tbody>";
  } catch (e) { toast(e.message); }
}

/* ---------- boot ---------- */
resetCorrection();
route();
setInterval(() => { if (!document.hidden && state.me && location.hash.replace("#", "") === "team") loadTeam(); }, 60000);
