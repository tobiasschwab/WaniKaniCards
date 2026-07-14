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
const selected = new Set();     // ausgewählte ids (als String)
let tableMode = "subject";      // "subject" | "custom"
let pollTimer = null;

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
function fileToDataUri(file) {
  return new Promise((res, rej) => {
    if (!file) { res(null); return; }
    const r = new FileReader();
    r.onload = () => res(r.result); r.onerror = rej; r.readAsDataURL(file);
  });
}

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
  $("#hole").checked = d.hole === true;
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

// ---------- Resolve / Tabelle ----------
async function resolve(body) {
  $("#resolveError").classList.add("hidden");
  body.sample = isSample();
  try {
    const r = await api("/api/resolve", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    if (!r.cards || r.cards.length === 0) { showResolveError("Nichts gefunden."); return null; }
    return r.cards;
  } catch (e) { showResolveError(e.message); return null; }
}
function showResolveError(m) { const el = $("#resolveError"); el.textContent = "⚠ " + m; el.classList.remove("hidden"); }

function renderTable(list, title, mode) {
  cards = list; tableMode = mode || "subject"; selected.clear();
  $("#tableTitle").textContent = title + ` (${list.length})`;
  $("#thActions").classList.toggle("hidden", tableMode !== "custom");
  const tb = $("#tableBody"); tb.innerHTML = "";
  for (const c of list) {
    const id = String(c.id);
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td class="c-check"><input type="checkbox" data-id="${escapeHtml(id)}"></td>
      <td class="c-char">${escapeHtml(c.characters || (c.has_image ? "🖼" : "—"))}</td>
      <td><span class="tag-mini ${c.object}">${escapeHtml(c.kind)}</span></td>
      <td>${escapeHtml(c.meaning)}</td>
      <td class="c-lvl">${c.level ?? ""}</td>
      <td class="c-act ${tableMode === "custom" ? "" : "hidden"}"></td>`;
    const cb = tr.querySelector("input");
    cb.addEventListener("change", () => toggle(id, cb.checked));
    tr.addEventListener("click", (e) => { if (e.target.tagName !== "INPUT" && e.target.tagName !== "BUTTON") { cb.checked = !cb.checked; toggle(id, cb.checked); } });
    if (tableMode === "custom") {
      const act = tr.querySelector(".c-act");
      const ed = document.createElement("button"); ed.className = "chip-btn"; ed.textContent = "✎"; ed.title = "Bearbeiten";
      ed.onclick = () => editCustom(id);
      const del = document.createElement("button"); del.className = "chip-btn danger"; del.textContent = "✕"; del.title = "Löschen";
      del.onclick = async () => { await api(`/api/customcards/${id}`, { method: "DELETE" }); loadCustoms(); };
      act.append(ed, del);
    }
    tb.append(tr);
  }
  selectAll(true);
  $("#tablePanel").classList.remove("hidden");
}
function toggle(id, on) { if (on) selected.add(id); else selected.delete(id); syncChecks(); updateRenderBtn(); }
function selectAll(on) {
  selected.clear(); if (on) cards.forEach((c) => selected.add(String(c.id)));
  syncChecks(); updateRenderBtn();
}
function syncChecks() {
  document.querySelectorAll("#tableBody input[data-id]").forEach((cb) => { cb.checked = selected.has(cb.dataset.id); });
  $("#checkAll").checked = cards.length > 0 && selected.size === cards.length;
}
function updateRenderBtn() {
  const n = selected.size; const b = $("#btnRender");
  b.textContent = `PDF erzeugen (${n})`; b.disabled = n === 0;
}

// ---------- Suche (Kompositions-Modus) ----------
async function doSearch() {
  const q = $("#searchInput").value.trim(); if (!q) return;
  $("#searchResults").innerHTML = '<span class="muted">Suche…</span>';
  const list = await resolve({ mode: "search", q });
  const box = $("#searchResults"); box.innerHTML = "";
  if (!list) return;
  for (const c of list) {
    const b = document.createElement("button"); b.className = "result-chip";
    b.innerHTML = `<span class="rc-char">${escapeHtml(c.characters || "🖼")}</span>
      <span class="rc-meta"><span class="tag-mini ${c.object}">${escapeHtml(c.kind)}</span> ${escapeHtml(c.meaning)}</span>`;
    b.onclick = async () => {
      const comp = await resolve({ mode: "compose", subject_ids: [c.id] });
      if (comp) renderTable(comp, `Komposition: ${c.characters || c.meaning}`, "subject");
    };
    box.append(b);
  }
}

// ---------- Frei-Modus: Editor ----------
function dynRow(kind, label, value, text) {
  const wrap = document.createElement("div"); wrap.className = "dyn-row";
  if (kind === "reading") {
    wrap.innerHTML = `<input class="text dl" placeholder="Label (On/Kun/…)" value="${escapeHtml(label || "")}">
      <input class="text dv" placeholder="Wert" value="${escapeHtml(value || "")}">`;
  } else {
    wrap.innerHTML = `<input class="text dl" placeholder="Label (Meaning/Reading)" value="${escapeHtml(label || "")}">
      <input class="text dt" placeholder="Text" value="${escapeHtml(text || "")}">`;
  }
  const rm = document.createElement("button"); rm.type = "button"; rm.className = "chip-btn danger"; rm.textContent = "✕";
  rm.onclick = () => wrap.remove();
  wrap.append(rm);
  return wrap;
}
function clearEditor() {
  $("#cfId").value = ""; $("#cfFront").value = ""; $("#cfFrontImg").value = "";
  $("#cfTags").value = ""; $("#cfMeaning").value = ""; $("#cfSubline").value = "";
  $("#cfReadings").innerHTML = ""; $("#cfMnemonics").innerHTML = "";
  $("#cfExWord").value = ""; $("#cfExReading").value = ""; $("#cfExMeaning").value = "";
  $("#cfSentJa").value = ""; $("#cfSentEn").value = ""; $("#cfBackImg").value = "";
  $("#cfFront").dataset.img = ""; $("#cfBackImg").dataset.img = "";
  $("#cfStatus").textContent = "";
}
function editorToJSON() {
  const csv = (s) => s.split(",").map((x) => x.trim()).filter(Boolean);
  const readings = [...$("#cfReadings").children].map((w) => ({ label: w.querySelector(".dl").value, value: w.querySelector(".dv").value }));
  const mnemonics = [...$("#cfMnemonics").children].map((w) => ({ label: w.querySelector(".dl").value, text: w.querySelector(".dt").value }));
  return {
    id: $("#cfId").value || undefined,
    front_text: $("#cfFront").value,
    front_image: $("#cfFront").dataset.img || null,
    tags: csv($("#cfTags").value),
    meanings: csv($("#cfMeaning").value),
    subline: $("#cfSubline").value,
    readings, mnemonics,
    example: { word: $("#cfExWord").value, reading: $("#cfExReading").value, meaning: $("#cfExMeaning").value },
    sentence_ja: $("#cfSentJa").value, sentence_en: $("#cfSentEn").value,
    back_image: $("#cfBackImg").dataset.img || null,
  };
}
function fillEditor(c) {
  clearEditor();
  $("#cfId").value = c.id || "";
  $("#cfFront").value = c.front_text || "";
  if (c.front_image) $("#cfFront").dataset.img = c.front_image;
  $("#cfTags").value = (c.tags || []).join(", ");
  $("#cfMeaning").value = (c.meanings || []).join(", ");
  $("#cfSubline").value = c.subline || "";
  (c.readings || []).forEach((r) => $("#cfReadings").append(dynRow("reading", r.label, r.value)));
  (c.mnemonics || []).forEach((m) => $("#cfMnemonics").append(dynRow("mnemonic", m.label, null, m.text)));
  const ex = c.example || {};
  $("#cfExWord").value = ex.word || ""; $("#cfExReading").value = ex.reading || ""; $("#cfExMeaning").value = ex.meaning || "";
  $("#cfSentJa").value = c.sentence_ja || ""; $("#cfSentEn").value = c.sentence_en || "";
  if (c.back_image) $("#cfBackImg").dataset.img = c.back_image;
}
async function editCustom(id) {
  const c = await api(`/api/customcards/${id}`);
  fillEditor(c);
  $("#modeCustom").scrollIntoView({ behavior: "smooth", block: "start" });
}
async function saveCustom() {
  const body = editorToJSON();
  if (!body.front_text && !body.front_image && !(body.meanings || []).length) {
    $("#cfStatus").textContent = "Bitte mindestens Vorderseite oder Bedeutung angeben."; $("#cfStatus").className = "status err"; return;
  }
  try {
    await api("/api/customcards", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    clearEditor(); toast("Karte gespeichert"); loadCustoms();
  } catch (e) { $("#cfStatus").textContent = e.message; $("#cfStatus").className = "status err"; }
}
async function loadCustoms() {
  let list = [];
  try { list = await api("/api/customcards"); } catch (_) {}
  renderTable(list, "Eigene Karten", "custom");
}
async function prefillFromWk() {
  const q = $("#cfPrefill").value.trim(); if (!q) return;
  const list = await resolve({ mode: "search", q });
  if (!list || !list.length) { $("#cfStatus").textContent = "Kein Treffer."; $("#cfStatus").className = "status err"; return; }
  // vollständige Karte über Komposition-Resolver? Nein – wir nehmen den ersten Treffer
  // und rendern die Detailfelder via /api/render nicht; wir füllen aus dem Descriptor
  // plus einem gezielten Nachladen wäre nötig. Einfach: Grundfelder aus Descriptor.
  const c = list[0];
  clearEditor();
  $("#cfFront").value = c.characters || "";
  $("#cfMeaning").value = c.meaning || "";
  $("#cfTags").value = [c.kind, c.level ? "Lv " + c.level : ""].filter(Boolean).join(", ");
  $("#cfStatus").textContent = "Grunddaten übernommen – Details ergänzen."; $("#cfStatus").className = "status ok";
}

// ---------- Rendern ----------
async function doRender() {
  $("#renderError").classList.add("hidden");
  const ids = cards.filter((c) => selected.has(String(c.id))).map((c) => c.id);
  if (!ids.length) return;
  const chosen = cards.filter((c) => selected.has(String(c.id)));
  const title = ids.length === 1 ? (chosen[0].characters || chosen[0].meaning) : `${ids.length} Karten`;
  const body = {
    title, sample: isSample(),
    layout: segValue("layout"), paper: $("#paper").value, duplex: segValue("duplex"),
    cut_marks: $("#cutmarks").checked, hole: $("#hole").checked,
  };
  if (tableMode === "custom") body.custom_ids = ids.map(String); else body.subject_ids = ids;
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
    else if (job.status === "running") $("#progressText").textContent = "PDF wird gebaut…";
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
  initSegmented("type"); initSegmented("duplex"); initSegmented("layout", applyLayoutState);
  initSegmented("modeTabs", (v) => {
    $("#modeLevel").classList.toggle("hidden", v !== "level");
    $("#modeCompose").classList.toggle("hidden", v !== "compose");
    $("#modeCustom").classList.toggle("hidden", v !== "custom");
    $("#tablePanel").classList.add("hidden");
    if (v === "custom") loadCustoms();
  });

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
    if (list) renderTable(list, `Level ${level} · ${type === "radicals" ? "Radicals" : "Kanji"}`, "subject");
  });
  $("#btnSearch").addEventListener("click", doSearch);
  $("#searchInput").addEventListener("keydown", (e) => { if (e.key === "Enter") doSearch(); });

  // Editor
  $("#cfAddReading").addEventListener("click", () => $("#cfReadings").append(dynRow("reading")));
  $("#cfAddMnemonic").addEventListener("click", () => $("#cfMnemonics").append(dynRow("mnemonic")));
  $("#cfFrontImg").addEventListener("change", async (e) => { $("#cfFront").dataset.img = (await fileToDataUri(e.target.files[0])) || ""; if ($("#cfFront").dataset.img) toast("Vorderseiten-Bild geladen"); });
  $("#cfBackImg").addEventListener("change", async (e) => { $("#cfBackImg").dataset.img = (await fileToDataUri(e.target.files[0])) || ""; if ($("#cfBackImg").dataset.img) toast("Rückseiten-Bild geladen"); });
  $("#cfSave").addEventListener("click", saveCustom);
  $("#cfClear").addEventListener("click", clearEditor);
  $("#cfLoadWk").addEventListener("click", prefillFromWk);

  $("#checkAll").addEventListener("change", (e) => selectAll(e.target.checked));
  $("#selAll").addEventListener("click", () => selectAll(true));
  $("#selNone").addEventListener("click", () => selectAll(false));
  $("#btnRender").addEventListener("click", doRender);

  loadSettings().catch(() => {});
  loadHistory();
});
