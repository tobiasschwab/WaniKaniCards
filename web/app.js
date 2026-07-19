"use strict";

const $ = (s) => document.querySelector(s);
const api = async (url, opts) => {
  const r = await fetch(url, opts);
  let data = null;
  try { data = await r.json(); } catch (_) {}
  if (!r.ok) {
    const err = new Error((data && data.error) || `HTTP ${r.status}`);
    err.status = r.status;
    throw err;
  }
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
// Wird NICHT bei jedem renderTable() zurückgesetzt (siehe dort), sondern
// akkumuliert über mehrere "Zur Tabelle"-Klicks im Text-Popup hinweg.
let sentenceOverrides = {};

// Text-Modus: die zuletzt annotierten Zeilen (für Popup-Lookups und die
// Bekannt-Prozent-Anzeige, ohne bei jeder Markierung neu vom Server zu holen).
let textLines = [];
// KI-Modus: die zuletzt analysierten Satz-Zeilen (gleicher Zweck wie textLines,
// aber pro Satz mit Übersetzung/Grammatik statt reiner Zeilen-Liste).
let kiRows = [];
let activeWordSeg = null;
let activeWordMode = "text"; // "text" | "ki" – welche Datenstruktur/welcher Endpunkt gerade betroffen ist

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
function _setConnPill(el, connected, connectedLabel) {
  el.textContent = connected ? (connectedLabel || "Verbunden") : "Nicht verbunden";
  el.className = "pill " + (connected ? "pill-ok" : "pill-off");
}
function _setConnDot(el, name, connected) {
  el.className = "conn-dot " + (connected ? "on" : "off");
  el.title = `${name}: ${connected ? "verbunden" : "nicht verbunden"}`;
}
function _populateGeminiModelSelect(models) {
  const sel = $("#geminiModel");
  const current = sel.value;
  sel.innerHTML = "";
  models.forEach((m) => {
    const opt = document.createElement("option");
    opt.value = m; opt.textContent = m;
    sel.appendChild(opt);
  });
  _selectGeminiModel(current);
}
function _selectGeminiModel(model) {
  const sel = $("#geminiModel");
  if (!model) return;
  if (![...sel.options].some((o) => o.value === model)) {
    const opt = document.createElement("option");
    opt.value = model; opt.textContent = model;
    sel.appendChild(opt);
  }
  sel.value = model;
}
async function loadSettings() {
  const s = await api("/api/settings");
  _setConnDot($("#connWanikani"), "WaniKani", s.token_set);
  _setConnDot($("#connDeepl"), "DeepL", s.deepl_key_set);
  _setConnDot($("#connGemini"), "Gemini", s.gemini_key_set);
  if (s.token_set) $("#tokenInput").placeholder = s.token_hint || "";
  _setConnPill($("#tokenRowPill"), s.token_set);
  if (s.deepl_key_set) $("#deeplInput").placeholder = s.deepl_key_hint || "";
  _setConnPill($("#deeplRowPill"), s.deepl_key_set);
  if (s.gemini_key_set) $("#geminiInput").placeholder = s.gemini_key_hint || "";
  _setConnPill($("#geminiRowPill"), s.gemini_key_set);
  if (s.gemini_models && s.gemini_models.length) { _populateGeminiModelSelect(s.gemini_models); }
  if (s.gemini_model) { _selectGeminiModel(s.gemini_model); }
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
  composeAccum = []; composeLabels = []; sentenceOverrides = {};
  cards = []; selected.clear();
  renderTable([], "Karten", "subject");
}

// ---------- Text-Modus (reine Janome+WaniKani-Analyse, kein Gemini) ----------
async function doTextProcess() {
  const text = $("#textInput").value;
  if (!text.trim()) return;
  $("#textStatus").textContent = "Analysiere…";
  let r;
  try {
    r = await api("/api/text-annotate", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text, sample: isSample() }),
    });
  } catch (e) {
    $("#textStatus").textContent = "";
    toast(e.message, true);
    return;
  }
  $("#textStatus").textContent = "";
  textLines = r.lines || [];
  renderAnnotatedText(textLines);
  updateTextStats(r.stats);
  $("#textInputWrap").classList.add("hidden");
  $("#textResultWrap").classList.remove("hidden");
}

function backToTextEdit() {
  $("#textResultWrap").classList.add("hidden");
  $("#textInputWrap").classList.remove("hidden");
  closeWordPopup();
}

function updateTextStats(stats) {
  if (!stats || !stats.total) { $("#textStats").innerHTML = '<span class="muted">Keine WaniKani-Wörter im Text erkannt.</span>'; return; }
  $("#textStats").innerHTML = `<span class="pct">${String(stats.percent).replace(".", ",")} %</span> bekannt (${stats.known} von ${stats.total} erkannten Wörtern)`;
}

function renderAnnotatedText(lines) {
  const wrap = $("#textDisplay");
  wrap.innerHTML = "";
  for (const line of lines) {
    const p = document.createElement("div");
    p.className = "text-line";
    if (!line.length) { p.innerHTML = "&nbsp;"; wrap.append(p); continue; }
    for (const seg of line) {
      if (seg.type === "word") {
        p.append(makeWordToken(seg, "text"));
      } else {
        p.append(document.createTextNode(seg.text));
      }
    }
    wrap.append(p);
  }
}

// ---------- KI-Modus (Gemini: Satz-Tabelle mit Übersetzung/Grammatik) ----------
const KI_STORAGE_KEY = "shiori_ki_state";

async function doKiProcess() {
  const text = $("#kiInput").value;
  if (!text.trim()) return;
  $("#kiStatus").textContent = "Analysiere mit KI… (kann bei langen Texten 1–2 Minuten dauern)";
  let r;
  try {
    // Gemini-Anfragen laufen gegen eine externe API – ohne Zeitlimit könnte
    // ein Netzwerkproblem die Oberfläche unbegrenzt in "Analysiere…" hängen
    // lassen, ohne dass sichtbar wird, woran es liegt.
    r = await api("/api/text-annotate-ai", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text, sample: isSample() }),
      signal: AbortSignal.timeout(150000),
    });
  } catch (e) {
    $("#kiStatus").textContent = "";
    toast(e.name === "TimeoutError" ? "Zeitüberschreitung – KI hat zu lange gebraucht (Text kürzen oder erneut versuchen)." : e.message, true);
    return;
  }
  $("#kiStatus").textContent = "";
  kiRows = r.rows || [];
  renderKiTable(kiRows);
  updateKiStats(r.stats);
  $("#kiInputWrap").classList.add("hidden");
  $("#kiResultWrap").classList.remove("hidden");
  saveKiStateToStorage();
}

function backToKiEdit() {
  $("#kiResultWrap").classList.add("hidden");
  $("#kiInputWrap").classList.remove("hidden");
  closeWordPopup();
}

function updateKiStats(stats) {
  if (!stats || !stats.total) { $("#kiStats").innerHTML = '<span class="muted">Keine WaniKani-/Dictionary-Wörter erkannt.</span>'; return; }
  $("#kiStats").innerHTML = `<span class="pct">${String(stats.percent).replace(".", ",")} %</span> bekannt (${stats.known} von ${stats.total} erkannten Wörtern)`;
}

// Nach einer clientseitigen Änderung (z. B. Retry für einen Satz) die
// Gesamt-Statistik neu aus den aktuellen kiRows berechnen, statt eine alte
// Server-Antwort mitzuschleppen.
function _recomputeKiStats(rows) {
  let known = 0, total = 0;
  for (const row of rows) {
    for (const s of row.segments) {
      if (s.type !== "word") continue;
      total++;
      if (s.known) known++;
    }
  }
  return { known, total, percent: total ? Math.round((known / total) * 1000) / 10 : 0 };
}

// Zuletzt analysierten KI-Text + Ergebnis lokal merken (localStorage), damit
// ein Reload/Tab-Wechsel nicht die komplette Analyse verwirft – sonst kostet
// jedes versehentliche Neuladen der Seite eine erneute Gemini-Anfrage für
// denselben Text. Rein clientseitig, keine Server-Persistenz nötig.
// Segmente tragen für die Audio-Karten-Erstellung eine `_row`-Rückreferenz
// auf ihre Zeile (siehe renderKiTable) – das macht die Struktur zirkulär und
// würde JSON.stringify() zum Absturz bringen. Für die Persistenz eine
// bereinigte Kopie ohne diese (und andere flüchtige `_`-Felder) bauen.
function _kiRowsForStorage(rows) {
  return rows.map((row) => ({
    sentence: row.sentence,
    translation_de: row.translation_de,
    grammar_notes: row.grammar_notes,
    error: row.error,
    segments: (row.segments || []).map(({ _row, ...rest }) => rest),
  }));
}

function saveKiStateToStorage() {
  try {
    localStorage.setItem(KI_STORAGE_KEY, JSON.stringify({ text: $("#kiInput").value, rows: _kiRowsForStorage(kiRows) }));
  } catch (_) { /* z. B. privater Modus ohne localStorage - einfach nicht persistieren */ }
}

function restoreKiStateFromStorage() {
  let saved = null;
  try { saved = JSON.parse(localStorage.getItem(KI_STORAGE_KEY) || "null"); } catch (_) { saved = null; }
  if (!saved || !Array.isArray(saved.rows) || !saved.rows.length) return;
  $("#kiInput").value = saved.text || "";
  kiRows = saved.rows;
  renderKiTable(kiRows);
  updateKiStats(_recomputeKiStats(kiRows));
  $("#kiInputWrap").classList.add("hidden");
  $("#kiResultWrap").classList.remove("hidden");
}

// Verschwommen/Aufgedeckt für Deutsch/Vokabeln/Bemerkung: standardmäßig
// verschwommen (nicht spoilern), einzelne Zelle anklicken deckt NUR sie auf,
// der Header-Button schaltet global um (löst dabei die Einzel-Aufdeckungen
// wieder ein, damit "alle verschwommen" wieder wirklich alle heißt).
let kiBlurEnabled = true;

function toggleKiBlur() {
  kiBlurEnabled = !kiBlurEnabled;
  $("#btnKiBlurToggle").textContent = kiBlurEnabled ? "🙈 Verschwommen" : "👁 Sichtbar";
  renderKiTable(kiRows);
}

// Grün (100 %) bis Rot (0 %) im Verlauf – Farbton linear zwischen 0° (Rot)
// und 120° (Grün) interpoliert.
function _pctBadgeHtml(known, total) {
  if (!total) return '<span class="muted">–</span>';
  const pct = Math.round((known / total) * 100);
  const hue = Math.round((pct / 100) * 120);
  return `<span class="ki-pct-badge" style="--pct-hue:${hue}">${pct}%</span>`;
}

// Original-Satz per Gemini vorlesen lassen (KI-Modus): einmal pro Satz
// abgerufen und auf dem row-Objekt gecacht (data-URI), damit weder erneutes
// Abspielen noch ein späteres Karte-Erstellen denselben Satz zweimal anfragt.
function fetchRowAudio(row) {
  if (row._audioPromise) return row._audioPromise;
  row._audioPromise = api("/api/gemini/tts", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text: row.sentence }),
  }).then((r) => { row._audioDataUri = r.audio_data_uri; return row._audioDataUri; })
    .catch((e) => { row._audioPromise = null; throw e; });
  return row._audioPromise;
}

function _kiPlaybackRate() {
  return parseFloat($("#kiSpeed").value) || 1;
}

async function playRowAudio(row, btn) {
  btn.disabled = true;
  const orig = btn.textContent;
  btn.textContent = "…";
  try {
    const uri = await fetchRowAudio(row);
    const audio = new Audio(uri);
    audio.playbackRate = _kiPlaybackRate();
    await audio.play();
  } catch (e) { toast(e.message, true); }
  finally { btn.disabled = false; btn.textContent = orig; }
}

// "Alle vorlesen": spielt Satz für Satz nacheinander ab (überspringt
// fehlgeschlagene Zeilen), Button wird währenddessen zum Stopp-Schalter.
let kiPlayingAll = false;
let kiPlayAllStop = false;

function _playAudioAndWait(uri, isStopped) {
  return new Promise((resolve) => {
    const audio = new Audio(uri);
    audio.playbackRate = _kiPlaybackRate();
    let done = false;
    const finish = () => { if (!done) { done = true; clearInterval(watcher); resolve(); } };
    audio.addEventListener("ended", finish);
    audio.addEventListener("error", finish);
    audio.play().catch(finish);
    const watcher = setInterval(() => { if (isStopped()) { audio.pause(); finish(); } }, 150);
  });
}

async function toggleKiPlayAll() {
  const btn = $("#btnKiPlayAll");
  if (kiPlayingAll) { kiPlayAllStop = true; return; }
  kiPlayingAll = true; kiPlayAllStop = false;
  btn.textContent = "⏹ Stopp";
  for (const row of kiRows) {
    if (kiPlayAllStop) break;
    if (row.error || !row.sentence) continue;
    try {
      const uri = await fetchRowAudio(row);
      await _playAudioAndWait(uri, () => kiPlayAllStop);
    } catch (_) { /* diesen Satz überspringen, mit dem nächsten weitermachen */ }
  }
  kiPlayingAll = false;
  btn.textContent = "▶ Alle vorlesen";
}

// Einen einzelnen gescheiterten Satz erneut anfragen, statt den ganzen Text
// neu zu analysieren (spart Zeit/Kosten für bereits erfolgreich analysierte
// Sätze).
async function retryKiRow(row, idx, btn) {
  btn.disabled = true;
  const orig = btn.textContent;
  btn.textContent = "…";
  try {
    const r = await api("/api/text-annotate-ai", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: row.sentence, sample: isSample() }),
      signal: AbortSignal.timeout(60000),
    });
    const newRow = (r.rows || [])[0];
    if (newRow) {
      kiRows[idx] = newRow;
      renderKiTable(kiRows);
      updateKiStats(_recomputeKiStats(kiRows));
      saveKiStateToStorage();
    }
  } catch (e) {
    toast(e.message, true);
    btn.disabled = false; btn.textContent = orig;
  }
}

// "Alle unbekannten hinzufügen": bewusster Sammel-Klick statt automatischem
// Hinzufügen aller Wörter – WaniKani-Treffer werden gebündelt in einem
// resolve()-Aufruf abgeglichen, Dictionary-/KI-Wörter einzeln nacheinander
// (nicht parallel, um DeepL/den Server nicht mit Anfragen zu fluten).
async function addAllUnknownFromKi() {
  if (!kiRows.length) return;
  activeWordMode = "ki";
  const allWords = kiRows.flatMap((row) => row.segments.filter((s) => s.type === "word"));
  const unknown = allWords.filter((s) => !s.known);
  if (!unknown.length) { toast("Keine unbekannten Wörter gefunden."); return; }

  const btn = $("#btnKiAddAllUnknown");
  btn.disabled = true;
  let added = 0;
  try {
    const wkWords = unknown.filter((s) => s.source === "wanikani");
    if (wkWords.length) {
      const ids = [...new Set(wkWords.map((s) => s.id))];
      const comp = await resolve({ mode: "compose", subject_ids: ids });
      if (comp) {
        for (const s of wkWords) {
          if (s.kind === "Vocab" && s.sentence) sentenceOverrides[String(s.id)] = { ja: s.sentence, en: null };
        }
        appendComposition(comp, `${ids.length} Wörter`);
        added += ids.length;
      }
    }
    for (const seg of unknown) {
      if (seg.source === "wanikani" || seg.ready) continue;
      try {
        const audioUrl = await _rowAudioForCard(seg);
        const body = seg.source === "ai"
          ? { word: seg.lemma || seg.text, source: "ai", meaning: seg.meaning, reading: seg.reading, sentence: seg.sentence, sentence_audio_url: audioUrl }
          : { word: seg.lemma || seg.text, sentence: seg.sentence, sentence_audio_url: audioUrl };
        const card = await api("/api/kanacards", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
        setSegReady(seg, true);
        appendComposition([card], _wpLabel(seg));
        added++;
      } catch (_) { /* einzelnes Wort überspringen, Rest weiter hinzufügen */ }
    }
  } finally {
    btn.disabled = false;
  }
  saveKiStateToStorage();
  toast(added ? `${added} Wörter zur Tabelle hinzugefügt` : "Nichts hinzugefügt");
}

function renderKiTable(rows) {
  const wrap = $("#kiTable");
  wrap.innerHTML = "";
  rows.forEach((row, idx) => {
    const tr = document.createElement("div");
    tr.className = "ki-row";
    const jpCell = document.createElement("div"); jpCell.className = "ki-cell ki-sentence";
    const jpText = document.createElement("span"); jpText.textContent = row.sentence;
    const speakBtn = document.createElement("button");
    speakBtn.type = "button"; speakBtn.className = "ki-speak-btn"; speakBtn.textContent = "🔊";
    speakBtn.title = "Satz vorlesen (Gemini)";
    speakBtn.addEventListener("click", () => playRowAudio(row, speakBtn));
    jpCell.append(jpText, speakBtn);
    if (row.error) {
      const errCell = document.createElement("div"); errCell.className = "ki-cell ki-error"; errCell.dataset.label = "Fehler";
      errCell.textContent = "⚠ " + row.error + " ";
      const retryBtn = document.createElement("button");
      retryBtn.type = "button"; retryBtn.className = "ki-retry-btn"; retryBtn.textContent = "🔄 Erneut versuchen";
      retryBtn.addEventListener("click", () => retryKiRow(row, idx, retryBtn));
      errCell.append(retryBtn);
      tr.append(jpCell, errCell);
      wrap.append(tr);
      return;
    }
    const words = row.segments.filter((s) => s.type === "word");
    words.forEach((s) => { s._row = row; });
    const knownCount = words.filter((s) => s.known).length;

    const pctCell = document.createElement("div"); pctCell.className = "ki-cell ki-pct"; pctCell.dataset.label = "Bekannt";
    pctCell.innerHTML = _pctBadgeHtml(knownCount, words.length);

    const deCell = document.createElement("div");
    deCell.className = "ki-cell" + (kiBlurEnabled ? " ki-blur" : ""); deCell.dataset.label = "Deutsch";
    deCell.textContent = row.translation_de || "";

    const vocabCell = document.createElement("div");
    vocabCell.className = "ki-cell ki-components" + (kiBlurEnabled ? " ki-blur" : ""); vocabCell.dataset.label = "Vokabeln";
    words.forEach((seg, i) => {
      if (i > 0) vocabCell.append(document.createTextNode(" · "));
      vocabCell.append(makeWordToken(seg, "ki", seg.lemma || seg.text));
    });

    const remarkCell = document.createElement("div");
    remarkCell.className = "ki-cell" + (kiBlurEnabled ? " ki-blur" : ""); remarkCell.dataset.label = "Bemerkung";
    remarkCell.textContent = row.grammar_notes || "";

    tr.append(jpCell, pctCell, deCell, vocabCell, remarkCell);
    wrap.append(tr);
  });
}

// ---------- Wort-Popup (gemeinsam für Text- und KI-Modus) ----------
// Im KI-Modus zeigt die Vokabeln-Spalte die Grundform (seg.lemma), nicht die
// im Satz vorkommende, ggf. flektierte Schreibweise (seg.text) – Popup-Titel
// und Toasts sollen dasselbe Wort nennen, das gerade angeklickt/hinzugefügt wurde.
function _wpLabel(seg) {
  return activeWordMode === "ki" ? (seg.lemma || seg.text) : seg.text;
}

function makeWordToken(seg, mode, label) {
  const span = document.createElement("span");
  span.className = "word-token " + seg.status.replace(/_/g, "-");
  span.dataset.id = String(seg.id);
  span.textContent = label || seg.text;
  span._seg = seg;
  span.addEventListener("click", (e) => openWordPopup(e.currentTarget, seg, mode));
  return span;
}

function openWordPopup(el, seg, mode = "text") {
  activeWordSeg = seg;
  activeWordMode = mode;
  const pop = $("#wordPopup");
  const isDict = seg.source === "dictionary";
  const isAi = seg.source === "ai";
  $("#wpChar").textContent = _wpLabel(seg);
  $("#wpKind").textContent = isAi ? "✨ " + seg.kind : seg.kind;
  $("#wpKind").className = "tag-mini " + (isDict ? "dictionary" : isAi ? "gemini" : seg.object);
  $("#wpSource").textContent = isDict ? "Quelle: Wörterbuch" : isAi ? "Quelle: KI (Gemini)" : "Quelle: WaniKani";
  $("#wpLevel").textContent = isDict
    ? (seg.kanji_hint ? `auch ${seg.kanji_hint}` : "")
    : isAi ? (seg.reading ? `Lesung: ${seg.reading}` : "") : (seg.level ? `Lv ${seg.level}` : "");
  $("#wpMeaning").textContent = seg.meaning || "";
  $("#wpMeaningExtra").textContent = seg.meaning_extra || "";
  $("#wpMeaningExtra").classList.toggle("hidden", !seg.meaning_extra);
  let note = "";
  if (seg.manually_known) note = "✓ manuell als bekannt markiert";
  else if (seg.ready) note = (isDict || isAi) ? "✓ Karte bereits erstellt" : "✓ bereits exportiert";
  $("#wpExportedNote").textContent = note;
  $("#wpExportedNote").classList.toggle("hidden", !note);
  $("#wpAdd").textContent = isAi ? "+ KI-Karte erstellen" : isDict ? "+ Dictionary-Karte erstellen" : "+ Zur Tabelle";
  $("#wpAdd").disabled = (isDict || isAi) && seg.ready;
  $("#wpKnown").textContent = seg.manually_known ? "Bekannt-Markierung entfernen" : "Als bekannt markieren";

  const rect = el.getBoundingClientRect();
  pop.classList.remove("hidden");
  const popW = pop.offsetWidth || 240;
  let left = rect.left;
  if (left + popW > window.innerWidth - 10) left = window.innerWidth - popW - 10;
  pop.style.left = `${Math.max(10, left)}px`;
  pop.style.top = `${rect.bottom + 8}px`;
}
function closeWordPopup() { $("#wordPopup").classList.add("hidden"); activeWordSeg = null; }

function wpAddClicked() {
  const seg = activeWordSeg;
  if (!seg) return;
  if (seg.source === "ai") createAiKanaCardFromPopup();
  else if (seg.source === "dictionary") createKanaCardFromPopup();
  else addWordFromPopup();
}

async function addWordFromPopup() {
  const seg = activeWordSeg;
  if (!seg) return;
  const comp = await resolve({ mode: "compose", subject_ids: [seg.id] });
  if (!comp) return;
  if (seg.kind === "Vocab" && seg.sentence) {
    sentenceOverrides[String(seg.id)] = { ja: seg.sentence, en: null };
  }
  appendComposition(comp, _wpLabel(seg));
  toast(`${_wpLabel(seg)} zur Tabelle hinzugefügt`);
  closeWordPopup();
}

// Falls das Wort aus einer KI-Modus-Satzzeile stammt (seg._row gesetzt),
// wird die per Gemini vorgelesene Satz-Audio mit in die Karte übernommen –
// bereits abgespielte/gecachte Audio wird wiederverwendet, sonst jetzt
// nachgeladen. Schlägt das fehl (Netzwerk/Quota), wird die Karte trotzdem
// ohne Audio erstellt statt das Hinzufügen ganz zu blockieren.
async function _rowAudioForCard(seg) {
  if (!seg._row) return null;
  try { return await fetchRowAudio(seg._row); } catch (_) { return null; }
}

async function createKanaCardFromPopup() {
  const seg = activeWordSeg;
  if (!seg || seg.ready) return;
  const sentenceAudioUrl = await _rowAudioForCard(seg);
  let card;
  try {
    card = await api("/api/kanacards", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ word: seg.lemma || seg.text, sentence: seg.sentence, sentence_audio_url: sentenceAudioUrl }),
    });
  } catch (e) { toast(e.message, true); return; }
  setSegReady(seg, true);
  appendComposition([card], _wpLabel(seg));
  toast(`Dictionary-Karte für ${_wpLabel(seg)} erstellt und zur Tabelle hinzugefügt`);
  closeWordPopup();
}

async function createAiKanaCardFromPopup() {
  const seg = activeWordSeg;
  if (!seg || seg.ready) return;
  const sentenceAudioUrl = await _rowAudioForCard(seg);
  let card;
  try {
    card = await api("/api/kanacards", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        word: seg.lemma || seg.text, source: "ai", meaning: seg.meaning, reading: seg.reading, sentence: seg.sentence,
        sentence_audio_url: sentenceAudioUrl,
      }),
    });
  } catch (e) { toast(e.message, true); return; }
  setSegReady(seg, true);
  appendComposition([card], _wpLabel(seg));
  toast(`KI-Karte für ${_wpLabel(seg)} erstellt und zur Tabelle hinzugefügt`);
  closeWordPopup();
}

// Nach Toggle/Erstellung: Status eines Worts (über alle Vorkommen im Text
// hinweg, per id) lokal aktualisieren, DOM-Klassen + Statistik neu ziehen –
// ohne kompletten Server-Roundtrip über /api/text-annotate(-ai). Funktioniert
// für beide Modi: Text-Modus hat "Zeilen aus Segmenten", KI-Modus hat
// "Satz-Zeilen mit .segments" – je nach activeWordMode wird die passende
// Struktur durchlaufen.
function setSegReady(seg, ready) { applySegChange(seg, { ready }); }
function setSegManuallyKnown(seg, manuallyKnown) { applySegChange(seg, { manually_known: manuallyKnown }); }

function applySegChange(seg, patch) {
  const isKi = activeWordMode === "ki";
  const allSegments = isKi
    ? kiRows.flatMap((row) => row.segments)
    : textLines.flatMap((line) => line);
  let known = 0, total = 0;
  for (const s of allSegments) {
    if (s.type !== "word") continue;
    total++;
    if (s.id === seg.id && s.source === seg.source) {
      Object.assign(s, patch);
      s.status = (s.manually_known || s.ready) ? "known" : "unknown";
      s.known = s.manually_known || s.ready;
    }
    if (s.known) known++;
  }
  document.querySelectorAll(`.word-token[data-id="${seg.id}"]`).forEach((span) => {
    if (span._seg.source !== seg.source) return;
    span.className = "word-token " + span._seg.status.replace(/_/g, "-");
  });
  const stats = { known, total, percent: total ? Math.round((known / total) * 1000) / 10 : 0 };
  if (isKi) { updateKiStats(stats); saveKiStateToStorage(); } else updateTextStats(stats);
}

async function toggleKnownFromPopup() {
  const seg = activeWordSeg;
  if (!seg) return;
  const makeKnown = !seg.manually_known;
  try {
    await api(`/api/known/${seg.id}`, { method: makeKnown ? "POST" : "DELETE" });
  } catch (e) { toast(e.message, true); return; }
  setSegManuallyKnown(seg, makeKnown);
  toast(makeKnown ? `${_wpLabel(seg)} als bekannt markiert` : `${_wpLabel(seg)} nicht mehr als bekannt markiert`);
  closeWordPopup();
}
// ---------- Wortliste: alle bekannten Wörter (WaniKani + Dictionary + manuell) ----------
let wortlisteEntries = [];

async function loadWortliste() {
  $("#wlList").innerHTML = '<div class="wl-row"><span class="muted">Lädt…</span></div>';
  try {
    wortlisteEntries = (await api(`/api/wortliste?sample=${isSample() ? 1 : 0}`)).entries || [];
  } catch (e) {
    $("#wlList").innerHTML = "";
    toast(e.message, true);
    wortlisteEntries = [];
  }
  renderWortliste();
}

function renderWortliste() {
  const q = $("#wlSearch").value.trim().toLowerCase();
  const filtered = q
    ? wortlisteEntries.filter((e) => (e.characters || "").toLowerCase().includes(q) || (e.meaning || "").toLowerCase().includes(q))
    : wortlisteEntries;

  $("#wlCount").textContent = wortlisteEntries.length
    ? `${filtered.length} von ${wortlisteEntries.length} Wörtern`
    : "";
  $("#wlEmpty").classList.toggle("hidden", wortlisteEntries.length > 0);

  const list = $("#wlList");
  list.innerHTML = "";
  for (const e of filtered) {
    const row = document.createElement("div");
    row.className = "wl-row";
    const badges = [];
    badges.push(`<span class="tag-mini ${e.source === "wanikani" ? e.object : e.source}">${escapeHtml(e.kind || e.source)}</span>`);
    if (e.level) badges.push(`<span class="muted">Lv ${e.level}</span>`);
    if (e.already_exported) badges.push('<span class="tag-mini exported">✓ exportiert</span>');
    if (e.card_created) badges.push('<span class="tag-mini exported">✓ Karte erstellt</span>');
    if (e.manually_known) badges.push('<span class="tag-mini manual">bekannt markiert</span>');
    const extra = e.meaning_extra ? `<span class="wl-meaning-extra">${escapeHtml(e.meaning_extra)}</span>` : "";
    row.innerHTML = `
      <span class="wl-char">${escapeHtml(e.characters)}</span>
      <span class="wl-meaning">${escapeHtml(e.meaning)}${extra}</span>
      <span class="wl-badges">${badges.join("")}</span>`;
    if (e.removable) {
      const del = document.createElement("button");
      del.className = "chip-btn danger"; del.textContent = "✕"; del.title = "Entfernen";
      del.onclick = () => removeWortlisteEntry(e);
      row.append(del);
    }
    list.append(row);
  }
}

// Beide möglichen Löschungen (manuelle Markierung, Dictionary-Karte)
// unabhängig voneinander versuchen, statt beim ersten Fehler abzubrechen –
// ein 404 heißt nur "schon weg" (z. B. nach einem Doppelklick) und zählt als
// Erfolg. Nur ein unerwarteter Fehler verhindert das Entfernen aus der Liste,
// mit einer Meldung, was genau schiefging.
async function removeWortlisteEntry(e) {
  const errors = [];
  if (e.manually_known) {
    try { await api(`/api/known/${e.id}`, { method: "DELETE" }); }
    catch (err) { if (err.status !== 404) errors.push(err.message); }
  }
  if (e.source === "dictionary" && e.card_created) {
    try { await api(`/api/kanacards/${e.id}`, { method: "DELETE" }); }
    catch (err) { if (err.status !== 404) errors.push(err.message); }
  }
  if (errors.length) { toast(`${e.characters} konnte nicht entfernt werden: ${errors.join("; ")}`, true); return; }
  wortlisteEntries = wortlisteEntries.filter((x) => x.id !== e.id);
  renderWortliste();
  toast(`${e.characters} entfernt`);
}

async function addManualWortliste() {
  const characters = $("#wlAddChar").value.trim();
  const meaning = $("#wlAddMeaning").value.trim();
  if (!characters) return;
  try {
    const entry = await api("/api/wortliste", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ characters, meaning }) });
    wortlisteEntries.unshift(entry);
    renderWortliste();
    $("#wlAddChar").value = ""; $("#wlAddMeaning").value = "";
    toast(`${characters} zur Wortliste hinzugefügt`);
  } catch (e) { toast(e.message, true); }
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
  sentenceOverrides = {};
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
  else {
    const kanaIds = ids.filter((i) => String(i).startsWith("kana_"));
    const subjectIds = ids.filter((i) => !String(i).startsWith("kana_"));
    body.subject_ids = subjectIds;
    if (kanaIds.length) body.kana_ids = kanaIds;
    if (Object.keys(sentenceOverrides).length) body.sentence_overrides = sentenceOverrides;
  }
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
      if (job.status === "done") toast(`Fertig: ${job.n_cards} Karten`);
      else { const el = $("#renderError"); el.textContent = "⚠ " + (job.error || "Fehlgeschlagen"); el.classList.remove("hidden"); toast("Fehlgeschlagen", true); }
      loadHistory();
      return;
    }
    pollTimer = setTimeout(tick, 1500);
  };
  tick();
}

// ---------- Verlauf ----------
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
      const d = document.createElement("a"); d.className = "chip-btn"; d.textContent = isAnki ? "Anki" : "PDF";
      d.href = `/api/jobs/${j.id}/${isAnki ? "apkg" : "pdf"}?download=1`; d.setAttribute("download", "");
      act.append(d);
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
    $("#modeKi").classList.toggle("hidden", v !== "ki");
    $("#modeCustom").classList.toggle("hidden", v !== "custom");
    $("#modeWortliste").classList.toggle("hidden", v !== "wortliste");
    document.querySelectorAll(".tab-group").forEach((g) => {
      g.classList.toggle("sel", !!g.querySelector(`button[data-v="${v}"]`));
    });
    if (v === "custom") loadCustoms();
    if (v === "wortliste") loadWortliste();
  });

  // Ausklapp-Elemente (Text-Modus-Erklärung, erweiterte Druckoptionen): ein
  // Klick auf den Toggle blendet das dazugehörige data-target-Element ein/aus.
  document.querySelectorAll(".disclosure-toggle").forEach((btn) => {
    const body = document.getElementById(btn.dataset.target);
    btn.addEventListener("click", () => {
      const open = body.classList.toggle("hidden") === false;
      btn.textContent = (open ? "▴ " : "▾ ") + btn.textContent.slice(2);
    });
  });

  // Einstellungen: pro Integration (WaniKani/DeepL/Gemini) eine Zeile, die
  // erst beim Anklicken das Key-Feld aufklappt (statt drei Formularen, die
  // immer alle offen sind).
  document.querySelectorAll(".settings-row-head").forEach((head) => {
    const row = head.closest(".settings-row");
    const body = row.querySelector(".settings-row-body");
    head.addEventListener("click", () => {
      const nowOpen = body.classList.toggle("hidden") === false;
      row.classList.toggle("open", nowOpen);
    });
  });

  $("#settingsToggle").addEventListener("click", () => $("#settingsOverlay").classList.remove("hidden"));
  $("#settingsClose").addEventListener("click", () => $("#settingsOverlay").classList.add("hidden"));
  $("#settingsOverlay").addEventListener("click", (e) => { if (e.target === $("#settingsOverlay")) $("#settingsOverlay").classList.add("hidden"); });
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
  $("#deeplShow").addEventListener("click", () => { const i = $("#deeplInput"); i.type = i.type === "password" ? "text" : "password"; });
  $("#deeplSave").addEventListener("click", async () => {
    const st = $("#deeplStatus");
    try {
      await api("/api/settings", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ deepl_key: $("#deeplInput").value }) });
      $("#deeplInput").value = ""; await loadSettings(); toast("Gespeichert"); st.textContent = "DeepL-Key gespeichert ✓"; st.className = "status ok";
    } catch (e) { st.textContent = e.message; st.className = "status err"; }
  });
  $("#geminiShow").addEventListener("click", () => { const i = $("#geminiInput"); i.type = i.type === "password" ? "text" : "password"; });
  $("#geminiSave").addEventListener("click", async () => {
    const st = $("#geminiStatus");
    try {
      await api("/api/settings", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ gemini_key: $("#geminiInput").value, gemini_model: $("#geminiModel").value }) });
      $("#geminiInput").value = ""; await loadSettings(); toast("Gespeichert"); st.textContent = "Gemini-Einstellungen gespeichert ✓"; st.className = "status ok";
    } catch (e) { st.textContent = e.message; st.className = "status err"; }
  });
  $("#geminiRefreshModels").addEventListener("click", async () => {
    const st = $("#geminiStatus");
    st.textContent = "Rufe verfügbare Modelle ab…"; st.className = "status";
    try {
      const key = $("#geminiInput").value;
      const body = key ? { key } : {};
      const r = await api("/api/gemini/models", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const current = $("#geminiModel").value;
      _populateGeminiModelSelect(r.models);
      _selectGeminiModel(current);
      st.textContent = `${r.models.length} Modelle geladen ✓`; st.className = "status ok";
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
    if (list) { sentenceOverrides = {}; renderTable(list, `Level ${level} · ${types.map((t) => labels[t]).join(" + ")}`, "subject"); }
  });
  $("#btnSearch").addEventListener("click", doSearch);
  $("#searchInput").addEventListener("keydown", (e) => { if (e.key === "Enter") doSearch(); });
  $("#btnComposeClear").addEventListener("click", clearCompose);
  $("#btnComposeClear2").addEventListener("click", clearCompose);
  $("#btnComposeClear3").addEventListener("click", clearCompose);
  $("#btnTextProcess").addEventListener("click", doTextProcess);
  $("#btnTextEdit").addEventListener("click", backToTextEdit);
  $("#btnKiProcess").addEventListener("click", doKiProcess);
  $("#btnKiEdit").addEventListener("click", backToKiEdit);
  $("#btnKiBlurToggle").addEventListener("click", toggleKiBlur);
  $("#btnKiAddAllUnknown").addEventListener("click", addAllUnknownFromKi);
  $("#btnKiPlayAll").addEventListener("click", toggleKiPlayAll);
  // Einzelne verschwommene Zelle anklicken deckt NUR sie auf (capture-Phase,
  // damit ein Klick auf ein Vokabel-Token darin zuerst nur aufdeckt statt
  // gleichzeitig auch das Hinzufügen-Popup zu öffnen).
  $("#kiTable").addEventListener("click", (e) => {
    const cell = e.target.closest(".ki-blur");
    if (cell) { cell.classList.remove("ki-blur"); e.stopPropagation(); }
  }, true);
  $("#wpAdd").addEventListener("click", wpAddClicked);
  $("#wpKnown").addEventListener("click", toggleKnownFromPopup);
  $("#wordPopupClose").addEventListener("click", closeWordPopup);
  document.addEventListener("click", (e) => {
    const pop = $("#wordPopup");
    if (!pop.classList.contains("hidden") && !pop.contains(e.target) && !e.target.classList.contains("word-token")) closeWordPopup();
  });

  // Frei-Editor: Rich-Text-Toolbars (mousedown, damit die Auswahl erhalten bleibt)
  document.querySelectorAll(".rt-toolbar button").forEach((b) => {
    b.addEventListener("mousedown", (e) => { e.preventDefault(); runToolbar(b); });
  });
  setTemplates();
  $("#cfSave").addEventListener("click", saveCustom);
  $("#cfClear").addEventListener("click", clearEditor);
  $("#cfLoadWk").addEventListener("click", prefillFromWk);

  $("#wlSearch").addEventListener("input", renderWortliste);
  $("#wlAddBtn").addEventListener("click", addManualWortliste);
  $("#wlAddMeaning").addEventListener("keydown", (e) => { if (e.key === "Enter") addManualWortliste(); });

  $("#checkAll").addEventListener("change", (e) => selectAll(e.target.checked));
  $("#selAll").addEventListener("click", () => selectAll(true));
  $("#selNone").addEventListener("click", () => selectAll(false));
  $("#btnRender").addEventListener("click", doRender);

  loadSettings().catch(() => {});
  loadHistory();
  restoreKiStateFromStorage();
});
