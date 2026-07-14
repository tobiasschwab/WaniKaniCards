"use strict";

const $ = (s) => document.querySelector(s);
const api = async (url, opts) => {
  const r = await fetch(url, opts);
  let data = null;
  try { data = await r.json(); } catch (_) {}
  if (!r.ok) throw new Error((data && data.error) || `HTTP ${r.status}`);
  return data;
};

let cards = [];                 // aktuelle Tabellenzeilen (Descriptors)
const selected = new Set();     // ausgewählte subject-ids
let pollTimer = null;

const KIND_LABEL = { kanji: "Kanji", radical: "Radical", vocabulary: "Vocab" };

// ---------- Helpers ----------
function toast(msg, isErr) {
  const t = $("#toast");
  t.textContent = msg; t.classList.toggle("err", !!isErr);
  t.classList.remove("hidden"); requestAnimationFrame(() => t.classList.add("show"));
  clearTimeout(toast._t);
  toast._t = setTimeout(() => { t.classList.remove("show"); setTimeout(() => t.classList.add("hidden"), 250); }, 2600);
}
function escapeHtml(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
const isSample = () => $("#sample").checked;

function initSegmented(id, onChange) {
  const el = document.getElementById(id);
  el.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => {
    el.querySelectorAll("button").forEach((x) => x.classList.remove("active"));
    b.classList.add("active"); el.dataset.value = b.dataset.v;
    if (onChange) onChange(b.dataset.v);
  }));
}
const segValue = (id) => document.getElementById(id).dataset.value;
function segSet(id, v) {
  const el = document.getElementById(id);
  el.querySelectorAll("button").forEach((b) => {
    const on = b.dataset.v === v; b.classList.toggle("active", on); if (on) el.dataset.value = v;
  });
}

// ---------- Settings ----------
async function loadSettings() {
  const s = await api("/api/settings");
  const pill = $("#tokenPill");
  if (s.token_set) { pill.textContent = "Token gesetzt"; pill.className = "pill pill-ok"; $("#tokenInput").placeholder = s.token_hint || ""; }
  else { pill.textContent = "Kein Token"; pill.className = "pill pill-warn"; }
  const d = s.defaults || {};
  if (d.level) $("#level").value = d.level;
  if (d.type) segSet("type", d.type);
  if (d.layout) segSet("layout", d.layout);
  if (d.paper) $("#paper").value = d.paper;
  if (d.duplex) segSet("duplex", d.duplex);
  $("#cutmarks").checked = d.cut_marks !== false;
  $("#hole").checked = d.hole !== false;
  applyLayoutState();
}
async function saveDefaults() {
  const defaults = {
    level: parseInt($("#level").value, 10) || 1, type: segValue("type"),
    layout: segValue("layout"), paper: $("#paper").value, duplex: segValue("duplex"),
    cut_marks: $("#cutmarks").checked, hole: $("#hole").checked,
  };
  try { await api("/api/settings", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ defaults }) }); } catch (_) {}
}
function applyLayoutState() { $("#paperOpt").classList.toggle("hidden", segValue("layout") === "a6"); }

// ---------- Resolve (Tabelle füllen) ----------
async function resolve(body, title) {
  $("#resolveError").classList.add("hidden");
  body.sample = isSample();
  try {
    const r = await api("/api/resolve", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    if (!r.cards || r.cards.length === 0) { showResolveError("Nichts gefunden."); return null; }
    return r.cards;
  } catch (e) { showResolveError(e.message); return null; }
}
function showResolveError(m) { const el = $("#resolveError"); el.textContent = "⚠ " + m; el.classList.remove("hidden"); }

function renderTable(list, title) {
  cards = list; selected.clear();
  $("#tableTitle").textContent = title + ` (${list.length})`;
  const tb = $("#tableBody"); tb.innerHTML = "";
  for (const c of list) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td class="c-check"><input type="checkbox" data-id="${c.id}"></td>
      <td class="c-char">${escapeHtml(c.characters || (c.has_image ? "🖼" : "—"))}</td>
      <td><span class="tag-mini ${c.object}">${escapeHtml(c.kind)}</span></td>
      <td>${escapeHtml(c.meaning)}</td>
      <td class="c-lvl">${c.level ?? ""}</td>`;
    const cb = tr.querySelector("input");
    cb.addEventListener("change", () => { toggle(c.id, cb.checked); });
    tr.addEventListener("click", (e) => { if (e.target.tagName !== "INPUT") { cb.checked = !cb.checked; toggle(c.id, cb.checked); } });
    tb.append(tr);
  }
  // Standardmäßig alles auswählen
  selectAll(true);
  $("#tablePanel").classList.remove("hidden");
  $("#tablePanel").scrollIntoView({ behavior: "smooth", block: "nearest" });
}
function toggle(id, on) { if (on) selected.add(id); else selected.delete(id); syncChecks(); updateRenderBtn(); }
function selectAll(on) {
  selected.clear();
  if (on) cards.forEach((c) => selected.add(c.id));
  syncChecks(); updateRenderBtn();
}
function syncChecks() {
  document.querySelectorAll("#tableBody input[data-id]").forEach((cb) => {
    cb.checked = selected.has(parseInt(cb.dataset.id, 10));
  });
  $("#checkAll").checked = cards.length > 0 && selected.size === cards.length;
}
function updateRenderBtn() {
  const n = selected.size;
  const b = $("#btnRender"); b.textContent = `PDF erzeugen (${n})`; b.disabled = n === 0;
}

// ---------- Suche (Kompositions-Modus) ----------
async function doSearch() {
  const q = $("#searchInput").value.trim();
  if (!q) return;
  $("#searchResults").innerHTML = '<span class="muted">Suche…</span>';
  const list = await resolve({ mode: "search", q });
  const box = $("#searchResults"); box.innerHTML = "";
  if (!list) { box.innerHTML = ""; return; }
  if (list.length === 0) { box.innerHTML = '<span class="muted">Keine Treffer.</span>'; return; }
  for (const c of list) {
    const b = document.createElement("button");
    b.className = "result-chip";
    b.innerHTML = `<span class="rc-char">${escapeHtml(c.characters || "🖼")}</span>
      <span class="rc-meta"><span class="tag-mini ${c.object}">${escapeHtml(c.kind)}</span> ${escapeHtml(c.meaning)}</span>`;
    b.onclick = async () => {
      const comp = await resolve({ mode: "compose", subject_ids: [c.id] });
      if (comp) renderTable(comp, `Komposition: ${c.characters || c.meaning}`);
    };
    box.append(b);
  }
}

// ---------- Rendern ----------
async function doRender() {
  $("#renderError").classList.add("hidden");
  const ids = cards.filter((c) => selected.has(c.id)).map((c) => c.id);
  if (!ids.length) return;
  const chosen = cards.filter((c) => selected.has(c.id));
  const title = ids.length === 1 ? (chosen[0].characters || chosen[0].meaning) : `${ids.length} Karten`;
  const body = {
    subject_ids: ids, title, sample: isSample(),
    layout: segValue("layout"), paper: $("#paper").value, duplex: segValue("duplex"),
    cut_marks: $("#cutmarks").checked, hole: $("#hole").checked,
  };
  $("#btnRender").disabled = true;
  $("#progress").classList.remove("hidden"); $("#progressText").textContent = "Wird erzeugt…";
  try {
    saveDefaults();
    const job = await api("/api/render", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    pollJob(job.id);
  } catch (e) {
    $("#btnRender").disabled = false; $("#progress").classList.add("hidden");
    const el = $("#renderError"); el.textContent = "⚠ " + e.message; el.classList.remove("hidden");
  }
}

function pollJob(id) {
  clearTimeout(pollTimer);
  const tick = async () => {
    let job;
    try { job = await api(`/api/jobs/${id}`); } catch (_) { pollTimer = setTimeout(tick, 1500); return; }
    if (job.status === "queued") $("#progressText").textContent = "In Warteschlange…";
    else if (job.status === "running") $("#progressText").textContent = "WaniKani wird abgefragt & PDF gebaut…";
    if (job.status === "done" || job.status === "error") {
      updateRenderBtn(); $("#progress").classList.add("hidden");
      if (job.status === "done") { showPreview(job); toast(`Fertig: ${job.n_cards} Karten`); }
      else { const el = $("#renderError"); el.textContent = "⚠ " + (job.error || "Fehlgeschlagen"); el.classList.remove("hidden"); toast("Fehlgeschlagen", true); }
      loadHistory();
      return;
    }
    pollTimer = setTimeout(tick, 1500);
  };
  tick();
}

// ---------- Vorschau + Verlauf ----------
function showPreview(job) {
  const f = $("#previewFrame"); f.src = `/api/jobs/${job.id}/pdf#view=FitH`; f.classList.remove("hidden");
  $("#previewEmpty").classList.add("hidden");
  const dl = $("#downloadBtn"); dl.href = `/api/jobs/${job.id}/pdf?download=1`; dl.classList.remove("hidden");
}
async function loadHistory() {
  let jobs = [];
  try { jobs = await api("/api/jobs"); } catch (_) {}
  const ul = $("#historyList"); ul.innerHTML = "";
  $("#historyEmpty").classList.toggle("hidden", jobs.length > 0);
  for (const j of jobs) {
    const li = document.createElement("li"); li.className = "hist";
    const p = j.params || {};
    const sub = j.status === "error"
      ? `<span class="err-text">${escapeHtml(j.error || "Fehler")}</span>`
      : `${(p.layout === "a6" ? "A6·1/Seite" : "A4·4/Seite")} · ${new Date(j.created_at).toLocaleString()}` + (j.n_cards ? ` · ${j.n_cards} Karten` : "");
    li.innerHTML = `<span class="dot ${j.status}"></span>
      <div class="h-main"><div class="h-title">${escapeHtml(j.title || j.id)}</div><div class="h-sub">${sub}</div></div>
      <div class="h-actions"></div>`;
    const act = li.querySelector(".h-actions");
    if (j.status === "done") {
      const v = document.createElement("button"); v.className = "chip-btn"; v.textContent = "Vorschau"; v.onclick = () => showPreview(j);
      const d = document.createElement("a"); d.className = "chip-btn"; d.textContent = "PDF"; d.href = `/api/jobs/${j.id}/pdf?download=1`; d.setAttribute("download", "");
      act.append(v, d);
    }
    const del = document.createElement("button"); del.className = "chip-btn danger"; del.textContent = "✕"; del.title = "Löschen";
    del.onclick = async () => { await api(`/api/jobs/${j.id}`, { method: "DELETE" }); loadHistory(); };
    act.append(del); ul.append(li);
  }
}

// ---------- Wire up ----------
document.addEventListener("DOMContentLoaded", () => {
  initSegmented("type"); initSegmented("duplex");
  initSegmented("layout", applyLayoutState);

  initSegmented("modeTabs", (v) => {
    $("#modeLevel").classList.toggle("hidden", v !== "level");
    $("#modeCompose").classList.toggle("hidden", v !== "compose");
  });
  // Tabs nutzen dieselbe Segmented-Logik, aber sind größer gestylt.

  $("#settingsToggle").addEventListener("click", () => $("#settingsPanel").classList.toggle("hidden"));
  $("#tokenShow").addEventListener("click", () => { const i = $("#tokenInput"); i.type = i.type === "password" ? "text" : "password"; });
  $("#tokenSave").addEventListener("click", async () => {
    try { await api("/api/settings", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ token: $("#tokenInput").value }) });
      $("#tokenInput").value = ""; await loadSettings(); toast("Gespeichert"); const st = $("#tokenStatus"); st.textContent = "Token gespeichert ✓"; st.className = "status ok";
    } catch (e) { const st = $("#tokenStatus"); st.textContent = e.message; st.className = "status err"; }
  });
  $("#tokenTest").addEventListener("click", async () => {
    const st = $("#tokenStatus"); st.textContent = "Teste…"; st.className = "status";
    try {
      const b = $("#tokenInput").value ? { token: $("#tokenInput").value } : {};
      const r = await api("/api/test-token", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(b) });
      st.textContent = `OK – ${r.username} (Level ${r.level})`; st.className = "status ok";
    } catch (e) { st.textContent = "Fehlgeschlagen: " + e.message; st.className = "status err"; }
  });

  $("#btnLevel").addEventListener("click", async () => {
    const level = parseInt($("#level").value, 10);
    if (!isSample() && !(level >= 1 && level <= 60)) { showResolveError("Level 1–60 angeben."); return; }
    const type = segValue("type");
    const list = await resolve({ mode: "level", level, type });
    if (list) renderTable(list, `Level ${level} · ${type === "radicals" ? "Radicals" : "Kanji"}`);
  });
  $("#btnSearch").addEventListener("click", doSearch);
  $("#searchInput").addEventListener("keydown", (e) => { if (e.key === "Enter") doSearch(); });

  $("#checkAll").addEventListener("change", (e) => selectAll(e.target.checked));
  $("#selAll").addEventListener("click", () => selectAll(true));
  $("#selNone").addEventListener("click", () => selectAll(false));
  $("#btnRender").addEventListener("click", doRender);

  loadSettings().catch(() => {});
  loadHistory();
});
