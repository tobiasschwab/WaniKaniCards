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

// Kompositions-Modus: über mehrere Suchen hinweg angehängte Karten, bis der
// Nutzer "Tabelle leeren" klickt oder neu startet.
let composeAccum = [];
let composeLabels = [];

// Text-Modus: Subject-ID → {ja, en} – eigener Beispielsatz aus dem Text,
// wird beim Rendern mitgeschickt und dort als erster Satz eingesetzt.
let sentenceOverrides = {};

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
function initChipcheck(id, onChange) {
  const el = document.getElementById(id);
  el.querySelectorAll("input[type=checkbox]").forEach((cb) => cb.addEventListener("change", () => {
    cb.closest(".chipcheck").classList.toggle("active", cb.checked);
    if (onChange) onChange(chipcheckValues(id));
  }));
}
function chipcheckValues(id) {
  return [...document.getElementById(id).querySelectorAll("input[type=checkbox]:checked")].map((cb) => cb.value);
}
function chipcheckSet(id, values) {
  const wanted = new Set(values);
  document.getElementById(id).querySelectorAll("input[type=checkbox]").forEach((cb) => {
    cb.checked = wanted.has(cb.value);
    cb.closest(".chipcheck").classList.toggle("active", cb.checked);
  });
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
  if (d.types && d.types.length) chipcheckSet("type", d.types);
  if (d.format) segSet("format", d.format);
  if (d.layout) segSet("layout", d.layout);
  if (d.paper) $("#paper").value = d.paper;
  if (d.duplex) segSet("duplex", d.duplex);
  $("#cutmarks").checked = d.cut_marks !== false;
  $("#hole").checked = d.hole === true;
  applyLayoutState();
  applyFormatState();
}
async function saveDefaults() {
  const defaults = {
    level: parseInt($("#level").value, 10) || 1, types: chipcheckValues("type"),
    format: segValue("format"),
    layout: segValue("layout"), paper: $("#paper").value, duplex: segValue("duplex"),
    cut_marks: $("#cutmarks").checked, hole: $("#hole").checked,
  };
  try { await api("/api/settings", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ defaults }) }); } catch (_) {}
}
function applyLayoutState() { $("#paperOpt").classList.toggle("hidden", segValue("layout") === "a6"); }
function applyFormatState() {
  const anki = segValue("format") === "anki";
  $("#printOpts").classList.toggle("hidden", anki);
  $("#ankiHint").classList.toggle("hidden", !anki);
  updateRenderBtn();
}

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
  sentenceOverrides = {}; // nur der Text-Modus setzt das direkt danach wieder
  $("#tableTitle").textContent = title + ` (${list.length})`;
  $("#thActions").classList.toggle("hidden", tableMode !== "custom");
  const tb = $("#tableBody"); tb.innerHTML = "";
  for (const c of list) {
    const id = String(c.id);
    const tr = document.createElement("tr");
    tr.classList.toggle("is-exported", !!c.already_exported);
    tr.innerHTML = `
      <td class="c-check"><input type="checkbox" data-id="${escapeHtml(id)}"></td>
      <td class="c-char">${escapeHtml(c.characters || (c.has_image ? "🖼" : "—"))}</td>
      <td><span class="tag-mini ${c.object}">${escapeHtml(c.kind)}</span></td>
      <td>${escapeHtml(c.meaning)}${c.already_exported ? '<span class="tag-mini exported" title="Bereits exportiert">✓ exportiert</span>' : ""}</td>
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
  selectDefault();
  $("#tablePanel").classList.remove("hidden");
}
function toggle(id, on) { if (on) selected.add(id); else selected.delete(id); syncChecks(); updateRenderBtn(); }
function selectAll(on) {
  selected.clear(); if (on) cards.forEach((c) => selected.add(String(c.id)));
  syncChecks(); updateRenderBtn();
}
// Default-Auswahl: alles außer bereits exportierten Karten (Text-Modus u. a.).
function selectDefault() {
  selected.clear();
  cards.forEach((c) => { if (!c.already_exported) selected.add(String(c.id)); });
  syncChecks(); updateRenderBtn();
}
function syncChecks() {
  document.querySelectorAll("#tableBody input[data-id]").forEach((cb) => { cb.checked = selected.has(cb.dataset.id); });
  $("#checkAll").checked = cards.length > 0 && selected.size === cards.length;
}
function updateRenderBtn() {
  const n = selected.size; const b = $("#btnRender");
  const anki = segValue("format") === "anki";
  b.textContent = `${anki ? "Anki-Paket" : "PDF"} erzeugen (${n})`;
  b.disabled = n === 0;
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
      if (comp) appendComposition(comp, c.characters || c.meaning);
    };
    box.append(b);
  }
}

// Neue Kompositions-Ergebnisse an die bestehende Tabelle anhängen (dedupliziert
// nach id), statt sie zu ersetzen – so lassen sich mehrere Vokabeln nacheinander
// kombinieren, bis der Nutzer "Tabelle leeren" klickt.
function appendComposition(newCards, label) {
  const seen = new Set(composeAccum.map((x) => String(x.id)));
  for (const item of newCards) {
    if (!seen.has(String(item.id))) { composeAccum.push(item); seen.add(String(item.id)); }
  }
  if (label) composeLabels.push(label);
  const title = composeLabels.length && composeLabels.length <= 4
    ? `Komposition: ${composeLabels.join(", ")}`
    : "Komposition";
  renderTable(composeAccum, title, "subject");
}
function clearCompose() {
  composeAccum = []; composeLabels = [];
  cards = []; selected.clear();
  $("#tablePanel").classList.add("hidden");
}

// ---------- Text-Modus ----------
async function doTextResolve() {
  const text = $("#textInput").value;
  if (!text.trim()) return;
  $("#textStatus").textContent = "Analysiere…";
  $("#resolveError").classList.add("hidden");
  let r;
  try {
    r = await api("/api/resolve", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ mode: "text", text, sample: isSample() }) });
  } catch (e) {
    $("#textStatus").textContent = "";
    showResolveError(e.message);
    return;
  }
  $("#textStatus").textContent = "";
  if (!r.cards || r.cards.length === 0) { showResolveError("Keine WaniKani-Treffer im Text gefunden."); return; }
  renderTable(r.cards, "Aus Text", "subject");
  sentenceOverrides = r.sentence_overrides || {};
}

// ---------- Frei-Modus: freier Karten-Editor (zwei Rich-Text-Felder) ----------
const FRONT_TEMPLATE = '<div class="free-big">Vorderseite</div>';
const BACK_TEMPLATE =
  '<div class="c-title">Titel</div>' +
  '<p>Freitext – hier kannst du frei formulieren, formatieren und Bilder einfügen.</p>' +
  '<div class="c-box">Notiz / Merkhilfe …</div>';

function setTemplates() {
  $("#cfFront").innerHTML = FRONT_TEMPLATE;
  $("#cfBack").innerHTML = BACK_TEMPLATE;
}
function clearEditor() {
  $("#cfId").value = "";
  setTemplates();
  $("#cfTags").value = "";
  $("#cfStatus").textContent = "";
}
function editorToJSON() {
  const csv = (s) => s.split(",").map((x) => x.trim()).filter(Boolean);
  return {
    id: $("#cfId").value || undefined,
    front_html: $("#cfFront").innerHTML,
    back_html: $("#cfBack").innerHTML,
    tags: csv($("#cfTags").value),
  };
}
function fillEditor(c) {
  $("#cfId").value = c.id || "";
  $("#cfFront").innerHTML = c.front_html || FRONT_TEMPLATE;
  $("#cfBack").innerHTML = c.back_html || BACK_TEMPLATE;
  $("#cfTags").value = (c.tags || []).join(", ");
  $("#cfStatus").textContent = "";
}
// Toolbar: Formatierung auf das jeweilige contenteditable-Feld anwenden.
async function runToolbar(btn) {
  const target = $("#" + btn.dataset.t);
  target.focus();
  const cmd = btn.dataset.cmd;
  switch (cmd) {
    case "bold": case "italic": case "underline":
      document.execCommand(cmd, false, null); break;
    case "ul":
      document.execCommand("insertUnorderedList", false, null); break;
    case "big": {
      const sel = document.getSelection();
      const text = sel && sel.toString() ? sel.toString() : "Großer Text";
      document.execCommand("insertHTML", false, `<span class="free-big">${escapeHtml(text)}</span>`);
      break;
    }
    case "title": {
      const sel = document.getSelection();
      const text = sel && sel.toString() ? sel.toString() : "Titel";
      document.execCommand("insertHTML", false, `<div class="c-title">${escapeHtml(text)}</div>`);
      break;
    }
    case "box": {
      const sel = document.getSelection();
      const text = sel && sel.toString() ? sel.toString() : "Notiz / Merkhilfe …";
      document.execCommand("insertHTML", false, `<div class="c-box">${escapeHtml(text)}</div>`);
      break;
    }
    case "image": {
      const inp = document.createElement("input");
      inp.type = "file"; inp.accept = "image/*";
      inp.onchange = async () => {
        const uri = await fileToDataUri(inp.files[0]);
        if (uri) { target.focus(); document.execCommand("insertHTML", false, `<img src="${uri}">`); }
      };
      inp.click();
      break;
    }
  }
}
async function editCustom(id) {
  const c = await api(`/api/customcards/${id}`);
  fillEditor(c);
  $("#modeCustom").scrollIntoView({ behavior: "smooth", block: "start" });
}
async function saveCustom() {
  const body = editorToJSON();
  if (!$("#cfFront").textContent.trim() && !$("#cfFront").querySelector("img")) {
    $("#cfStatus").textContent = "Bitte die Vorderseite ausfüllen."; $("#cfStatus").className = "status err"; return;
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
  const c = list[0];
  $("#cfId").value = "";
  $("#cfFront").innerHTML = `<div class="free-big">${escapeHtml(c.characters || "")}</div>`;
  $("#cfBack").innerHTML =
    `<div class="c-title">${escapeHtml(c.meaning || "")}</div>` +
    '<p>Freitext ergänzen …</p>' +
    '<div class="c-box">Merkhilfe …</div>';
  $("#cfTags").value = [c.kind, c.level ? "Lv " + c.level : ""].filter(Boolean).join(", ");
  $("#cfStatus").textContent = "Grunddaten übernommen – frei ergänzen."; $("#cfStatus").className = "status ok";
}

// ---------- Rendern ----------
async function doRender() {
  $("#renderError").classList.add("hidden");
  const ids = cards.filter((c) => selected.has(String(c.id))).map((c) => c.id);
  if (!ids.length) return;
  const chosen = cards.filter((c) => selected.has(String(c.id)));
  const title = ids.length === 1 ? (chosen[0].characters || chosen[0].meaning) : `${ids.length} Karten`;
  const format = segValue("format");
  const body = { title, sample: isSample(), format };
  if (format === "pdf") {
    Object.assign(body, {
      layout: segValue("layout"), paper: $("#paper").value, duplex: segValue("duplex"),
      cut_marks: $("#cutmarks").checked, hole: $("#hole").checked,
    });
  }
  if (tableMode === "custom") body.custom_ids = ids.map(String);
  else { body.subject_ids = ids; if (Object.keys(sentenceOverrides).length) body.sentence_overrides = sentenceOverrides; }
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
    const isAnki = (job.params && job.params.format) === "anki";
    if (job.status === "queued") $("#progressText").textContent = "In Warteschlange…";
    else if (job.status === "running") $("#progressText").textContent = isAnki ? "Anki-Paket wird gebaut…" : "PDF wird gebaut…";
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
  const isAnki = (job.params && job.params.format) === "anki";
  const url = isAnki ? `/api/jobs/${job.id}/apkg` : `/api/jobs/${job.id}/pdf`;
  if (isAnki) {
    $("#previewFrame").classList.add("hidden");
    const pe = $("#previewEmpty");
    pe.innerHTML = '<div class="ph-icon">🎴</div><p>Anki-Paket bereit – <strong>herunterladen</strong> und in Anki importieren (Datei → Importieren).</p>';
    pe.classList.remove("hidden");
  } else {
    $("#previewEmpty").classList.add("hidden");
    const f = $("#previewFrame"); f.src = `${url}#view=FitH`; f.classList.remove("hidden");
  }
  const dl = $("#downloadBtn"); dl.href = `${url}?download=1`; dl.classList.remove("hidden");
}
async function loadHistory() {
  let jobs = [];
  try { jobs = await api("/api/jobs"); } catch (_) {}
  const ul = $("#historyList"); ul.innerHTML = "";
  $("#historyEmpty").classList.toggle("hidden", jobs.length > 0);
  for (const j of jobs) {
    const li = document.createElement("li"); li.className = "hist";
    const p = j.params || {};
    const isAnki = p.format === "anki";
    const fmtLabel = isAnki ? "Anki-Paket (.apkg)" : (p.layout === "a6" ? "A6·1/Seite" : "A4·4/Seite");
    const sub = j.status === "error"
      ? `<span class="err-text">${escapeHtml(j.error || "Fehler")}</span>`
      : `${fmtLabel} · ${new Date(j.created_at).toLocaleString()}` + (j.n_cards ? ` · ${j.n_cards} Karten` : "");
    li.innerHTML = `<span class="dot ${j.status}"></span>
      <div class="h-main"><div class="h-title">${escapeHtml(j.title || j.id)}</div><div class="h-sub">${sub}</div></div>
      <div class="h-actions"></div>`;
    const act = li.querySelector(".h-actions");
    if (j.status === "done") {
      const v = document.createElement("button"); v.className = "chip-btn"; v.textContent = "Vorschau"; v.onclick = () => showPreview(j);
      const d = document.createElement("a"); d.className = "chip-btn"; d.textContent = isAnki ? "Anki" : "PDF";
      d.href = `/api/jobs/${j.id}/${isAnki ? "apkg" : "pdf"}?download=1`; d.setAttribute("download", "");
      act.append(v, d);
    }
    const del = document.createElement("button"); del.className = "chip-btn danger"; del.textContent = "✕"; del.title = "Löschen";
    del.onclick = async () => { await api(`/api/jobs/${j.id}`, { method: "DELETE" }); loadHistory(); };
    act.append(del); ul.append(li);
  }
}

// ---------- Wire up ----------
document.addEventListener("DOMContentLoaded", () => {
  initChipcheck("type"); initSegmented("duplex"); initSegmented("layout", applyLayoutState);
  initSegmented("format", applyFormatState);
  initSegmented("modeTabs", (v) => {
    $("#modeLevel").classList.toggle("hidden", v !== "level");
    $("#modeCompose").classList.toggle("hidden", v !== "compose");
    $("#modeText").classList.toggle("hidden", v !== "text");
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
    const types = chipcheckValues("type");
    $("#levelTypeError").classList.toggle("hidden", types.length > 0);
    if (!types.length) return;
    const labels = { radicals: "Radicals", kanji: "Kanji", vocabulary: "Vokabeln" };
    const list = await resolve({ mode: "level", level, types });
    if (list) renderTable(list, `Level ${level} · ${types.map((t) => labels[t]).join(" + ")}`, "subject");
  });
  $("#btnSearch").addEventListener("click", doSearch);
  $("#searchInput").addEventListener("keydown", (e) => { if (e.key === "Enter") doSearch(); });
  $("#btnComposeClear").addEventListener("click", clearCompose);
  $("#btnTextResolve").addEventListener("click", doTextResolve);

  // Frei-Editor: Rich-Text-Toolbars (mousedown, damit die Auswahl erhalten bleibt)
  document.querySelectorAll(".rt-toolbar button").forEach((b) => {
    b.addEventListener("mousedown", (e) => { e.preventDefault(); runToolbar(b); });
  });
  setTemplates();
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
