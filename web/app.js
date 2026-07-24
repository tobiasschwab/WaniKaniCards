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

// ---------- Anmeldung (Multi-User: Backend braucht jetzt einen eingeloggten
// Nutzer für praktisch jeden Endpunkt) ----------
let authMode = "login"; // "login" | "signup"

async function checkAuthAndInit() {
  let me;
  try {
    me = await api("/api/auth/me");
  } catch (_) {
    me = { authenticated: false };
  }
  if (me.authenticated) {
    await setUiLanguage(me.native_lang);
    onAuthenticated(me.email);
  } else {
    await setUiLanguage("de"); // vor dem Login noch keine Muttersprache bekannt
    loadAuthLanguageOptions().catch(() => {});
    $("#authOverlay").classList.remove("hidden");
  }
}

function onAuthenticated(email) {
  $("#authOverlay").classList.add("hidden");
  $("#accountEmail").textContent = email;
  $("#accountEmail").classList.remove("hidden");
  $("#logoutBtn").classList.remove("hidden");
  loadSettings().catch(() => {});
  loadLanguages().catch(() => {});
  loadHistory();
  restoreKiStateFromStorage();
}

function setAuthMode(mode) {
  authMode = mode;
  $("#authTitle").textContent = t(mode === "signup" ? "auth.signup.title" : "auth.login.title");
  $("#authSubmit").textContent = t(mode === "signup" ? "auth.signup.submit" : "auth.login.submit");
  $("#authToggleMode").textContent = t(mode === "signup" ? "auth.signup.toggle" : "auth.login.toggle");
  $("#authStatus").textContent = "";
  $("#authLanguageFields").classList.toggle("hidden", mode !== "signup");
}

// Sprachwahl im Registrierungsformular - VOR dem ersten Login gibt es noch
// keinen current_user, dessen Muttersprache/Zielsprache abfragbar wäre,
// deshalb der eigene, login-freie Endpunkt (siehe /api/languages/public).
async function loadAuthLanguageOptions() {
  const nativeSel = $("#authNativeLang");
  nativeSel.innerHTML = "";
  for (const { code, label } of _UI_LANGS) {
    const opt = document.createElement("option");
    opt.value = code; opt.textContent = label;
    nativeSel.appendChild(opt);
  }
  try {
    const data = await api("/api/languages/public");
    const targetSel = $("#authTargetLang");
    targetSel.innerHTML = "";
    for (const { code, display_name } of data.supported_target_langs || []) {
      const opt = document.createElement("option");
      opt.value = code; opt.textContent = display_name;
      targetSel.appendChild(opt);
    }
    targetSel.value = "ja";
  } catch (_) { /* Sprachwahl bleibt leer, Registrierung funktioniert trotzdem mit Serverdefaults */ }
}

async function submitAuthForm() {
  const email = $("#authEmail").value.trim();
  const password = $("#authPassword").value;
  const st = $("#authStatus");
  st.textContent = "";
  const path = authMode === "signup" ? "/api/auth/signup" : "/api/auth/login";
  const body = { email, password };
  if (authMode === "signup") {
    body.native_lang = $("#authNativeLang").value || "de";
    body.active_target_lang = $("#authTargetLang").value || "ja";
  }
  try {
    const r = await api(path, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    $("#authPassword").value = "";
    onAuthenticated(r.email);
  } catch (e) {
    st.textContent = e.message; st.className = "status err";
  }
}

async function doLogout() {
  try { await api("/api/auth/logout", { method: "POST" }); } catch (_) {}
  location.reload();
}

// Einstellungen öffnen und direkt zu einer Sektion springen (z. B. von den
// Status-Pills im Header aus) - schließt zuerst alle anderen offenen
// Sektionen, damit nicht mehrere gleichzeitig aufgeklappt bleiben.
function openSettingsSection(rowName) {
  $("#settingsOverlay").classList.remove("hidden");
  document.querySelectorAll(".settings-row").forEach((row) => {
    const body = row.querySelector(".settings-row-body");
    const isTarget = row.dataset.row === rowName;
    body.classList.toggle("hidden", !isTarget);
    row.classList.toggle("open", isTarget);
  });
  $(`.settings-row[data-row="${rowName}"]`)?.scrollIntoView({ block: "nearest" });
}

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

// "Felder manuell anpassen"-Dialog (Kartentabelle): Subject-ID (String) →
// {feldname: neuer_wert, …} – nur tatsächlich geänderte Felder, wird beim
// Rendern mitgeschickt (siehe doRender()) und serverseitig NACH dem
// Karten-Bau angewendet (kc._apply_field_overrides()). Bleibt über mehrere
// Bearbeitungen/Tabellen hinweg bestehen, bis "Tabelle leeren" geklickt wird.
let fieldOverrides = {};
// Cache der vollen Original-Karten-Felder je Subject-ID (String), damit ein
// erneutes Öffnen des Dialogs nicht jedes Mal neu vom Server holt und der
// "Zurücksetzen"-Button die echten WaniKani-Originalwerte kennt.
let _cardDetailCache = {};
let _fieldEditCurrentId = null;
let _fieldEditCurrentType = null;

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
  el.title = `${name}: ${connected ? "verbunden" : "nicht verbunden"} – zu den Einstellungen`;
}
// Nur für die Anzeige im Dropdown – DeepL selbst braucht nur den Code.
const _LANG_NAMES = {
  BG: "Bulgarisch", CS: "Tschechisch", DA: "Dänisch", DE: "Deutsch", EL: "Griechisch",
  EN: "Englisch", ES: "Spanisch", ET: "Estnisch", FI: "Finnisch", FR: "Französisch",
  HU: "Ungarisch", ID: "Indonesisch", IT: "Italienisch", JA: "Japanisch", KO: "Koreanisch",
  LT: "Litauisch", LV: "Lettisch", NB: "Norwegisch", NL: "Niederländisch", PL: "Polnisch",
  PT: "Portugiesisch", RO: "Rumänisch", RU: "Russisch", SK: "Slowakisch", SL: "Slowenisch",
  SV: "Schwedisch", TR: "Türkisch", UK: "Ukrainisch", ZH: "Chinesisch",
};
function _populateTargetLangSelect(codes, current) {
  const sel = $("#targetLang");
  sel.innerHTML = "";
  codes.forEach((code) => {
    const opt = document.createElement("option");
    opt.value = code; opt.textContent = `${_LANG_NAMES[code] || code} (${code})`;
    sel.appendChild(opt);
  });
  if (current) sel.value = current;
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
  _populateTargetLangSelect(s.target_langs || ["DE"], s.target_lang || "DE");
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
  $("#srsNewPerDay").value = d.srs_new_per_day ?? 20;
  $("#srsReviewsPerDay").value = d.srs_reviews_per_day ?? 200;
}
// UI-Chrome-Sprachen, für die es tatsächlich eine i18n/*.json gibt (siehe
// i18n.js) - unabhängig von den Zielsprachen (SUPPORTED_TARGET_LANGS in
// languages/registry.py), die viel zahlreicher sind, weil sie keine
// eigene UI-Übersetzung brauchen (nur Karteninhalte).
const _UI_LANGS = [
  { code: "de", label: "Deutsch" },
  { code: "en", label: "English" },
];

async function loadLanguages() {
  const data = await api("/api/languages");
  const nativeSel = $("#nativeLangSelect");
  nativeSel.innerHTML = "";
  for (const { code, label } of _UI_LANGS) {
    const opt = document.createElement("option");
    opt.value = code; opt.textContent = label;
    nativeSel.appendChild(opt);
  }
  nativeSel.value = data.native_lang || "de";

  const targetSel = $("#activeTargetLangSelect");
  targetSel.innerHTML = "";
  for (const { code, display_name } of data.supported_target_langs || []) {
    const opt = document.createElement("option");
    opt.value = code; opt.textContent = display_name;
    targetSel.appendChild(opt);
  }
  targetSel.value = data.active_target_lang || "ja";

  _applyLanguageCapabilities(data.active_capabilities || {});
  return data;
}

// Modi, die eine externe Lernstufen-Quelle wie WaniKani brauchen (siehe
// languages/base.py has_content_provider), für Zielsprachen ohne
// spezialisierten LanguagePack ausblenden - "Frei erstellen"/"Aus Text"/
// "Wortliste" funktionieren dagegen für jede Sprache.
function _applyLanguageCapabilities(caps) {
  const hasContentProvider = !!caps.has_content_provider;
  for (const v of ["level", "compose"]) {
    const btn = document.querySelector(`#modeTabs button[data-v="${v}"]`);
    if (btn) btn.classList.toggle("hidden", !hasContentProvider);
  }
  // Falls der aktuell aktive Tab durch den Sprachwechsel weggefallen ist,
  // auf "Frei erstellen" zurückfallen (immer verfügbar).
  const active = $("#modeTabs").dataset.value;
  if (!hasContentProvider && (active === "level" || active === "compose")) {
    segSet("modeTabs", "custom");
    $("#modeLevel").classList.add("hidden");
    $("#modeCompose").classList.add("hidden");
    $("#modeCustom").classList.remove("hidden");
  }
}

async function onLanguageSelectChanged() {
  const st = $("#languagesStatus");
  st.textContent = "";
  try {
    const body = {
      native_lang: $("#nativeLangSelect").value,
      active_target_lang: $("#activeTargetLangSelect").value,
    };
    await api("/api/settings/language", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    await setUiLanguage(body.native_lang);
    const data = await loadLanguages();
    _applyLanguageCapabilities(data.active_capabilities || {});
    // Sprachwechsel = neuer "Kurs" - Karten-/Wort-/Job-Listen sind serverseitig
    // nach der neuen Zielsprache gefiltert, clientseitige Caches müssen daher
    // neu geladen werden statt die alten (jetzt falschen) Daten weiter anzuzeigen.
    loadHistory();
    if (segValue("modeTabs") === "custom") loadCustoms();
    if (segValue("modeTabs") === "wortliste") loadWortliste();
    // Eine laufende Review-Session zeigt Karten der ALTEN Zielsprache - die
    // Queue wurde für diese geladen und Antworten würden sonst gegen die neu
    // aktive Sprache verbucht (Server scoped /api/srs/* immer nach der
    // AKTUELL aktiven Sprache, nicht nach der Sprache der Session). Deshalb
    // die Session hart abbrechen statt sie weiterlaufen zu lassen.
    resetReviewSession();
    if (segValue("modeTabs") === "review") enterReviewMode();
    toast("Gespeichert");
  } catch (e) {
    st.textContent = e.message; st.className = "status err";
  }
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

// Objekt-Typen, für die "Felder manuell anpassen" verfügbar ist – reine
// WaniKani-Subjects mit numerischer ID (nicht kana_/manual_-Einträge, die
// über /api/kanacards bzw. Wortliste eigene Bearbeitungswege haben).
const _EDITABLE_OBJECT_TYPES = new Set(["kanji", "vocabulary", "radical"]);

function renderTable(list, title, mode) {
  cards = list; tableMode = mode || "subject"; selected.clear();
  $("#tableTitle").textContent = title + ` (${list.length})`;
  const tb = $("#tableBody"); tb.innerHTML = "";
  for (const c of list) {
    const id = String(c.id);
    const editable = tableMode !== "custom" && _EDITABLE_OBJECT_TYPES.has(c.object);
    const tr = document.createElement("tr");
    tr.classList.toggle("is-exported", !!c.already_exported);
    const hasImageOverride = !!(fieldOverrides[id] && fieldOverrides[id].image_data_uri);
    if (fieldOverrides[id]) tr.classList.add("has-field-overrides");
    tr.innerHTML = `
      <td class="c-check"><input type="checkbox" data-id="${escapeHtml(id)}"></td>
      <td class="c-char">${escapeHtml(c.characters || (c.has_image ? "🖼" : "—"))}</td>
      <td><span class="tag-mini ${c.object}">${escapeHtml(c.kind)}</span></td>
      <td>${escapeHtml(c.meaning)}${c.already_exported ? '<span class="tag-mini exported" title="Bereits exportiert">✓ exportiert</span>' : ""}${fieldOverrides[id] ? '<span class="tag-mini" title="Felder manuell angepasst">✎ angepasst</span>' : ""}${hasImageOverride ? '<span class="tag-mini" title="Bildkarte">🖼 Bildkarte</span>' : ""}</td>
      <td class="c-lvl">${c.level ?? ""}</td>
      <td class="c-act"></td>`;
    const cb = tr.querySelector("input");
    cb.addEventListener("change", () => toggle(id, cb.checked));
    tr.addEventListener("click", (e) => { if (e.target.tagName !== "INPUT" && e.target.tagName !== "BUTTON") { cb.checked = !cb.checked; toggle(id, cb.checked); } });
    const act = tr.querySelector(".c-act");
    if (tableMode === "custom") {
      const ed = document.createElement("button"); ed.className = "chip-btn"; ed.textContent = "✎"; ed.title = "Bearbeiten";
      ed.onclick = () => editCustom(id);
      const del = document.createElement("button"); del.className = "chip-btn danger"; del.textContent = "✕"; del.title = "Löschen";
      del.onclick = async () => { await api(`/api/customcards/${id}`, { method: "DELETE" }); loadCustoms(); };
      act.append(ed, del);
    } else if (editable) {
      const ed = document.createElement("button"); ed.className = "chip-btn"; ed.textContent = "✎"; ed.title = "Felder manuell anpassen";
      ed.onclick = (e) => { e.stopPropagation(); openFieldEditModal(id, c.object); };
      act.append(ed);
      if (c.object === "vocabulary") {
        const img = document.createElement("button"); img.className = "chip-btn"; img.textContent = "🖼"; img.title = "Bildkarte erzeugen";
        img.onclick = (e) => { e.stopPropagation(); openImageCardModal(id, c); };
        act.append(img);
      }
    }
    tb.append(tr);
  }
  selectDefault();
  $("#tablePanel").classList.remove("hidden");
}

// ---------- Felder manuell anpassen (Kartentabelle) ----------
const FIELD_SCHEMAS = {
  kanji: [
    { key: "meanings", label: "Bedeutungen", list: true, translatable: true },
    { key: "onyomi", label: "On'yomi", list: true },
    { key: "kunyomi", label: "Kun'yomi", list: true },
    { key: "meaning_mnemonic", label: "Bedeutungs-Merkhilfe", translatable: true },
    { key: "reading_mnemonic", label: "Lesungs-Merkhilfe", translatable: true },
    { key: "vocab", label: "Beispielvokabel" },
    { key: "vocab_reading", label: "Lesung der Beispielvokabel" },
    { key: "vocab_meaning", label: "Bedeutung der Beispielvokabel", translatable: true },
    { key: "sentence_ja", label: "Beispielsatz (Japanisch)" },
    { key: "sentence_en", label: "Beispielsatz-Übersetzung", translatable: true },
  ],
  vocabulary: [
    { key: "readings", label: "Lesungen", list: true },
    { key: "meanings", label: "Bedeutungen", list: true, translatable: true },
    { key: "meaning_mnemonic", label: "Bedeutungs-Merkhilfe", translatable: true },
    { key: "reading_mnemonic", label: "Lesungs-Merkhilfe", translatable: true },
    { key: "sentence_ja", label: "Beispielsatz (Japanisch)" },
    { key: "sentence_en", label: "Beispielsatz-Übersetzung", translatable: true },
  ],
  radical: [
    { key: "meaning", label: "Bedeutung", translatable: true },
    { key: "mnemonic", label: "Merkhilfe", translatable: true },
  ],
};

async function openFieldEditModal(id, objectType) {
  _fieldEditCurrentId = String(id);
  _fieldEditCurrentType = objectType;
  $("#fieldEditOverlay").classList.remove("hidden");
  $("#fieldEditStatus").textContent = "Lade…";
  $("#fieldEditBody").innerHTML = "";
  let detail = _cardDetailCache[_fieldEditCurrentId];
  if (!detail) {
    try {
      const r = await api("/api/card-detail", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ subject_ids: [id], sample: isSample() }),
      });
      detail = r.cards[_fieldEditCurrentId];
    } catch (e) {
      $("#fieldEditStatus").textContent = ""; toast(e.message, true);
      $("#fieldEditOverlay").classList.add("hidden");
      return;
    }
    if (detail) _cardDetailCache[_fieldEditCurrentId] = detail;
  }
  if (!detail) {
    $("#fieldEditStatus").textContent = "";
    toast("Karte nicht gefunden.", true);
    $("#fieldEditOverlay").classList.add("hidden");
    return;
  }
  $("#fieldEditStatus").textContent = "";
  $("#fieldEditTitle").textContent = `Bearbeiten: ${detail.kanji || detail.vocab || detail.radical || ""}`;
  renderFieldEditBody(detail, objectType);
}

function renderFieldEditBody(detail, objectType) {
  const schema = FIELD_SCHEMAS[objectType] || [];
  const overrides = fieldOverrides[_fieldEditCurrentId] || {};
  const wrap = $("#fieldEditBody");
  wrap.innerHTML = "";
  for (const f of schema) {
    const hasOverride = Object.prototype.hasOwnProperty.call(overrides, f.key);
    const value = hasOverride ? overrides[f.key] : detail[f.key];
    const textValue = f.list ? (value || []).join("\n") : (value || "");
    const row = document.createElement("div");
    row.className = "field-edit-row" + (hasOverride ? " is-overridden" : "");
    row.dataset.field = f.key;
    row.dataset.list = f.list ? "1" : "0";
    row.innerHTML = `
      <div class="field-edit-label-row">
        <span class="label">${escapeHtml(f.label)}</span>
        <div class="field-edit-actions">
          ${f.translatable ? '<button type="button" class="chip-btn field-translate" title="Übersetzen (Original bleibt zur Kontrolle erhalten)">🌐 Übersetzen</button>' : ""}
          <button type="button" class="chip-btn field-reset" title="Zurücksetzen auf WaniKani-Original">↺</button>
        </div>
      </div>
      <textarea rows="${f.list || textValue.length > 60 ? 3 : 1}">${escapeHtml(textValue)}</textarea>`;
    const ta = row.querySelector("textarea");
    row.querySelector(".field-reset").onclick = () => {
      ta.value = f.list ? (detail[f.key] || []).join("\n") : (detail[f.key] || "");
      row.classList.remove("is-overridden");
    };
    const translateBtn = row.querySelector(".field-translate");
    if (translateBtn) {
      translateBtn.onclick = async () => {
        const original = ta.value;
        if (!original.trim()) return;
        translateBtn.disabled = true; translateBtn.textContent = "…";
        try {
          const r = await api("/api/translate", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ text: original, source_lang: "EN" }),
          });
          // Übersetzung VOR den Original-Text setzen, nicht überschreiben –
          // so bleibt die Original-WaniKani-Angabe zur Kontrolle sichtbar.
          ta.value = `${r.translation}\n—\n${original}`;
          row.classList.add("is-overridden");
        } catch (e) { toast(e.message, true); }
        translateBtn.disabled = false; translateBtn.textContent = "🌐 Übersetzen";
      };
    }
    wrap.append(row);
  }
}

function saveFieldEdits() {
  const id = _fieldEditCurrentId;
  const detail = _cardDetailCache[id];
  if (!id || !detail) return;
  const overrides = {};
  $("#fieldEditBody").querySelectorAll(".field-edit-row").forEach((row) => {
    const key = row.dataset.field;
    const isList = row.dataset.list === "1";
    const raw = row.querySelector("textarea").value;
    const newValue = isList ? raw.split("\n").map((s) => s.trim()).filter(Boolean) : raw.trim();
    const original = isList ? (detail[key] || []) : (detail[key] || "");
    const changed = isList ? JSON.stringify(newValue) !== JSON.stringify(original) : newValue !== original;
    if (changed) overrides[key] = newValue;
  });
  if (Object.keys(overrides).length) fieldOverrides[id] = overrides;
  else delete fieldOverrides[id];
  $("#fieldEditOverlay").classList.add("hidden");
  toast(Object.keys(overrides).length ? "Änderungen gespeichert – wirken beim Erzeugen der Karten." : "Keine Änderungen.");
  renderTable(cards, $("#tableTitle").textContent.replace(/\s*\(\d+\)$/, ""), tableMode);
}

// ---------- Bildkarten (Vokabel-Vorderseite = Gemini-Clipart) ----------
let _imageCardCurrentId = null;
let _imageCardPreviewUri = null; // noch nicht übernommenes, frisch generiertes Bild

function openImageCardModal(id, c) {
  _imageCardCurrentId = String(id);
  _imageCardPreviewUri = null;
  $("#imageCardTitle").textContent = `Bildkarte: ${c.characters || c.meaning || ""}`;
  $("#imageCardStatus").textContent = "";
  $("#imageCardGenerate").textContent = "Generieren";
  $("#imageCardAccept").disabled = true;
  const existing = (fieldOverrides[_imageCardCurrentId] || {}).image_data_uri;
  const existingShowMeaning = (fieldOverrides[_imageCardCurrentId] || {}).show_meaning_on_front;
  $("#imageCardShowMeaning").checked = !!existingShowMeaning;
  const preview = $("#imageCardPreview");
  if (existing) {
    preview.innerHTML = `<img src="${existing}" alt="">`;
    $("#imageCardGenerate").textContent = "Neu generieren";
  } else {
    preview.innerHTML = '<span class="muted">Noch kein Bild generiert.</span>';
  }
  $("#imageCardOverlay").classList.remove("hidden");
}

async function generateImageCard() {
  const c = cards.find((x) => String(x.id) === _imageCardCurrentId);
  if (!c) return;
  const btn = $("#imageCardGenerate");
  btn.disabled = true;
  $("#imageCardStatus").textContent = "Generiere Bild… (kann einige Sekunden dauern)";
  try {
    const r = await api("/api/gemini/generate-image", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ word: c.characters, meaning: c.meaning }),
    });
    _imageCardPreviewUri = r.image_data_uri;
    $("#imageCardPreview").innerHTML = `<img src="${r.image_data_uri}" alt="">`;
    $("#imageCardAccept").disabled = false;
    $("#imageCardStatus").textContent = "";
    btn.textContent = "Neu generieren";
  } catch (e) {
    $("#imageCardStatus").textContent = "";
    toast(e.message, true);
  }
  btn.disabled = false;
}

function acceptImageCard() {
  const id = _imageCardCurrentId;
  if (!id || !_imageCardPreviewUri) return;
  fieldOverrides[id] = {
    ...(fieldOverrides[id] || {}),
    image_data_uri: _imageCardPreviewUri,
    show_meaning_on_front: $("#imageCardShowMeaning").checked,
  };
  $("#imageCardOverlay").classList.add("hidden");
  toast("Bildkarte übernommen – wirkt beim Erzeugen der Karten.");
  renderTable(cards, $("#tableTitle").textContent.replace(/\s*\(\d+\)$/, ""), tableMode);
}

function removeImageCard() {
  const id = _imageCardCurrentId;
  if (id && fieldOverrides[id]) {
    delete fieldOverrides[id].image_data_uri;
    delete fieldOverrides[id].show_meaning_on_front;
    if (!Object.keys(fieldOverrides[id]).length) delete fieldOverrides[id];
  }
  _imageCardPreviewUri = null;
  $("#imageCardOverlay").classList.add("hidden");
  renderTable(cards, $("#tableTitle").textContent.replace(/\s*\(\d+\)$/, ""), tableMode);
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
  $("#btnSrsAdd").disabled = n === 0;
}

// Sammelt dieselben IDs wie doRender() (subject_ids/custom_ids/kana_ids),
// aber legt ReviewState-Zeilen an statt eine PDF/Anki-Datei zu erzeugen -
// der dritte, gleichwertige Export-Weg (siehe README "Vokabeltrainer").
async function addSelectionToSrs() {
  const ids = cards.filter((c) => selected.has(String(c.id))).map((c) => c.id);
  if (!ids.length) return;
  const body = { sample: isSample() };
  if (tableMode === "custom") {
    body.custom_ids = ids.map(String);
  } else {
    const kanaIds = ids.filter((i) => String(i).startsWith("kana_"));
    const subjectIds = ids.filter((i) => !String(i).startsWith("kana_"));
    body.subject_ids = subjectIds;
    if (kanaIds.length) body.kana_ids = kanaIds;
  }
  $("#btnSrsAdd").disabled = true;
  try {
    const result = await api("/api/srs/add", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    toast(result.added > 0 ? `${result.added} zum Lernen hinzugefügt` : "Bereits in der Lernwarteschlange");
  } catch (e) {
    toast(e.message);
  } finally {
    $("#btnSrsAdd").disabled = selected.size === 0;
  }
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
  composeAccum = []; composeLabels = []; sentenceOverrides = {}; fieldOverrides = {};
  cards = []; selected.clear();
  renderTable([], "Karten", "subject");
}

// ---------- Text-Modus: eine Eingabe, zwei Analyse-Arten ----------
// "Schnell" (reine Janome+WaniKani-Analyse, kein Gemini) und "KI" (Gemini,
// siehe unten) teilen sich Textarea + Analysieren-Button, damit man
// denselben Text nicht zweimal einfügen muss – der Segmented-Schalter
// entscheidet, welcher Endpunkt/welche Ergebnisansicht dran ist.
function doTextProcess() {
  return segValue("textAnalysisMode") === "ki" ? doKiProcess() : doTextProcessFast();
}

// PDF/Bild-Upload: Text serverseitig extrahieren (Textlayer oder Gemini-OCR,
// siehe pdf_import.py) und in dieselbe Textarea füllen wie manuell eingefügter
// Text – die eigentliche Analyse läuft danach exakt wie sonst.
async function doTextUpload(file) {
  if (!file) return;
  $("#textUploadStatus").textContent = `Extrahiere Text aus „${file.name}“… (kann bei Scans/OCR etwas dauern)`;
  const fd = new FormData();
  fd.append("file", file);
  let r;
  try {
    r = await api("/api/text-extract", { method: "POST", body: fd, signal: AbortSignal.timeout(300000) });
  } catch (e) {
    $("#textUploadStatus").textContent = "";
    toast(e.name === "TimeoutError" ? "Zeitüberschreitung bei der Texterkennung." : e.message, true);
    return;
  }
  $("#textUploadStatus").textContent = "";
  $("#textInput").value = r.text || "";
  $("#textInput").focus();
  toast(`Text aus „${file.name}“ eingefügt (${(r.text || "").length} Zeichen).`);
}

async function doTextProcessFast() {
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
  $("#kiResultWrap").classList.add("hidden");
}

function backToTextEdit() {
  $("#textResultWrap").classList.add("hidden");
  $("#kiResultWrap").classList.add("hidden");
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
  const text = $("#textInput").value;
  if (!text.trim()) return;
  $("#textStatus").textContent = "Analysiere mit KI… (kann bei langen Texten mehrere Minuten dauern)";
  let r;
  try {
    // Gemini-Anfragen laufen gegen eine externe API – ohne Zeitlimit könnte
    // ein Netzwerkproblem die Oberfläche unbegrenzt in "Analysiere…" hängen
    // lassen, ohne dass sichtbar wird, woran es liegt. Serverseitig kann ein
    // einzelner Batch (bis zu 40 Sätze) bis zu ~280s + Retry brauchen, bei
    // langen Texten mit mehreren Batches entsprechend länger – das clientseitige
    // Zeitlimit muss großzügiger sein als der einzelne Server-Timeout.
    r = await api("/api/text-annotate-ai", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text, sample: isSample() }),
      signal: AbortSignal.timeout(600000),
    });
  } catch (e) {
    $("#textStatus").textContent = "";
    toast(e.name === "TimeoutError" ? "Zeitüberschreitung – KI hat zu lange gebraucht (Text kürzen oder erneut versuchen)." : e.message, true);
    return;
  }
  $("#textStatus").textContent = "";
  kiRows = r.rows || [];
  renderKiTable(kiRows);
  renderKiFrequencyList();
  updateKiStats(r.stats);
  $("#textInputWrap").classList.add("hidden");
  $("#textResultWrap").classList.add("hidden");
  $("#kiResultWrap").classList.remove("hidden");
  saveKiStateToStorage();
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
    translation: row.translation,
    grammar_notes: row.grammar_notes,
    error: row.error,
    segments: (row.segments || []).map(({ _row, _hlKey, ...rest }) => rest),
  }));
}

function saveKiStateToStorage() {
  try {
    localStorage.setItem(KI_STORAGE_KEY, JSON.stringify({ text: $("#textInput").value, rows: _kiRowsForStorage(kiRows) }));
  } catch (_) { /* z. B. privater Modus ohne localStorage - einfach nicht persistieren */ }
}

function restoreKiStateFromStorage() {
  let saved = null;
  try { saved = JSON.parse(localStorage.getItem(KI_STORAGE_KEY) || "null"); } catch (_) { saved = null; }
  if (!saved || !Array.isArray(saved.rows) || !saved.rows.length) return;
  $("#textInput").value = saved.text || "";
  segSet("textAnalysisMode", "ki");
  kiRows = saved.rows;
  renderKiTable(kiRows);
  renderKiFrequencyList();
  updateKiStats(_recomputeKiStats(kiRows));
  $("#textInputWrap").classList.add("hidden");
  $("#textResultWrap").classList.add("hidden");
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
      signal: AbortSignal.timeout(120000),
    });
    const newRow = (r.rows || [])[0];
    if (newRow) {
      kiRows[idx] = newRow;
      renderKiTable(kiRows);
      renderKiFrequencyList();
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
  renderKiFrequencyList();
  toast(added ? `${added} Wörter zur Tabelle hinzugefügt` : "Nichts hinzugefügt");
}

// "Neue Vokabeln in diesem Text" (nach Häufigkeit, nur noch unbekannte):
// zeigt kompakt die Top 10, damit man bei langen Texten nicht von der schieren
// Menge erschlagen wird – "Alle anzeigen" klappt bei Bedarf den Rest auf.
let kiFreqExpanded = false;

function _kiFrequencyEntries() {
  const counts = new Map();
  for (const row of kiRows) {
    for (const s of row.segments || []) {
      if (s.type !== "word") continue;
      const key = s.source + ":" + s.id;
      if (!counts.has(key)) counts.set(key, { seg: s, count: 0 });
      counts.get(key).count++;
    }
  }
  return [...counts.values()].sort((a, b) => b.count - a.count);
}

function renderKiFrequencyList() {
  const outerWrap = $("#kiFreqWrap");
  const listWrap = $("#kiFreqList");
  const entries = _kiFrequencyEntries();
  outerWrap.classList.toggle("hidden", !entries.length);
  if (!entries.length) return;
  const shown = kiFreqExpanded ? entries : entries.slice(0, 10);
  listWrap.innerHTML = "";
  const chips = document.createElement("div");
  chips.className = "ki-freq-chips";
  for (const { seg, count } of shown) {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "ki-freq-chip " + (seg.status || "unknown").replace(/_/g, "-");
    chip.title = seg.meaning || "";
    chip.innerHTML = `<span>${escapeHtml(seg.lemma || seg.text)}</span><span class="c">×${count}</span>`;
    chip.addEventListener("click", (e) => openWordPopup(e.currentTarget, seg, "ki"));
    chips.append(chip);
  }
  listWrap.append(chips);
  if (entries.length > 10) {
    const toggle = document.createElement("button");
    toggle.type = "button"; toggle.className = "btn small";
    toggle.textContent = kiFreqExpanded ? "Weniger anzeigen" : `Alle ${entries.length} anzeigen`;
    toggle.addEventListener("click", () => { kiFreqExpanded = !kiFreqExpanded; renderKiFrequencyList(); });
    listWrap.append(toggle);
  }
}

function renderKiTable(rows) {
  const wrap = $("#kiTable");
  wrap.innerHTML = "";
  rows.forEach((row, idx) => {
    const tr = document.createElement("div");
    tr.className = "ki-row";
    const jpCell = document.createElement("div"); jpCell.className = "ki-cell ki-sentence";
    const jpTextWrap = document.createElement("span");
    const speakBtn = document.createElement("button");
    speakBtn.type = "button"; speakBtn.className = "ki-speak-btn"; speakBtn.textContent = "🔊";
    speakBtn.title = "Satz vorlesen (Gemini)";
    speakBtn.addEventListener("click", () => playRowAudio(row, speakBtn));
    if (row.error) {
      jpTextWrap.textContent = row.sentence;
      jpCell.append(jpTextWrap, speakBtn);
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

    // Original-Satz aus den Segmenten aufbauen (statt einem Text-Knoten),
    // damit jedes Wort einen Hover-Verknüpfungs-Hook (data-hl) zur
    // gleichnamigen Vokabeln-Spalten-Stelle bekommt – rein visuell/optional,
    // der Satz selbst bleibt unverändert (kein Einfärben nach bekannt/unbekannt).
    let wordIdx = 0;
    for (const seg of row.segments) {
      if (seg.type === "word") {
        const span = document.createElement("span");
        span.className = "ki-jp-word";
        span.textContent = seg.text;
        seg._hlKey = `${idx}-${wordIdx++}`;
        span.dataset.hl = seg._hlKey;
        jpTextWrap.append(span);
      } else {
        jpTextWrap.append(document.createTextNode(seg.text));
      }
    }
    jpCell.append(jpTextWrap, speakBtn);

    const pctCell = document.createElement("div"); pctCell.className = "ki-cell ki-pct"; pctCell.dataset.label = "Bekannt";
    pctCell.innerHTML = _pctBadgeHtml(knownCount, words.length);

    const deCell = document.createElement("div");
    deCell.className = "ki-cell" + (kiBlurEnabled ? " ki-blur" : ""); deCell.dataset.label = "Deutsch";
    deCell.textContent = row.translation || "";

    const vocabCell = document.createElement("div");
    vocabCell.className = "ki-cell ki-components" + (kiBlurEnabled ? " ki-blur" : ""); vocabCell.dataset.label = "Vokabeln";
    words.forEach((seg, i) => {
      if (i > 0) vocabCell.append(document.createTextNode(" · "));
      const tok = makeWordToken(seg, "ki", seg.lemma || seg.text);
      if (seg._hlKey) tok.dataset.hl = seg._hlKey;
      vocabCell.append(tok);
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
  else if (seg.card_exists) note = "📚 Im Vokabeltrainer, noch nicht bewertet";
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
      s.status = (s.manually_known || s.ready) ? "known" : (s.card_exists ? "card_exists" : "unknown");
      s.known = s.manually_known || s.ready;
    }
    if (s.known) known++;
  }
  document.querySelectorAll(`.word-token[data-id="${seg.id}"]`).forEach((span) => {
    if (span._seg.source !== seg.source) return;
    span.className = "word-token " + span._seg.status.replace(/_/g, "-");
  });
  const stats = { known, total, percent: total ? Math.round((known / total) * 1000) / 10 : 0 };
  if (isKi) { updateKiStats(stats); saveKiStateToStorage(); renderKiFrequencyList(); } else updateTextStats(stats);
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
    if (e.sentence_ja) {
      const ctx = document.createElement("button");
      ctx.className = "chip-btn"; ctx.textContent = "📄"; ctx.title = "Satz-Kontext anzeigen";
      ctx.onclick = (ev) => openWlContext(ev.currentTarget, e);
      row.append(ctx);
    }
    if (e.removable) {
      const del = document.createElement("button");
      del.className = "chip-btn danger"; del.textContent = "✕"; del.title = "Entfernen";
      del.onclick = () => removeWortlisteEntry(e);
      row.append(del);
    }
    list.append(row);
  }
}

// Zeigt den Satz, aus dem ein Dictionary-/KI-Wort ursprünglich stammt (auf
// der KanaCard gespeichert, siehe kanji_cards.KanaCard.sentence_ja) – für
// WaniKani-Wörter (noch) nicht verfügbar, da dort kein eigener Satz-Kontext
// mitgespeichert wird.
function openWlContext(el, entry) {
  $("#wlContextJa").textContent = entry.sentence_ja || "";
  $("#wlContextDe").textContent = entry.sentence_translation || "";
  $("#wlContextDe").classList.toggle("hidden", !entry.sentence_translation);
  const audioEl = $("#wlContextAudio");
  if (entry.sentence_audio_url) { audioEl.src = entry.sentence_audio_url; audioEl.classList.remove("hidden"); }
  else { audioEl.removeAttribute("src"); audioEl.classList.add("hidden"); }
  const pop = $("#wlContextPopup");
  pop.classList.remove("hidden");
  const rect = el.getBoundingClientRect();
  const popW = pop.offsetWidth || 260;
  let left = rect.left;
  if (left + popW > window.innerWidth - 10) left = window.innerWidth - popW - 10;
  pop.style.left = `${Math.max(10, left)}px`;
  pop.style.top = `${rect.bottom + 8}px`;
}
function closeWlContext() { $("#wlContextPopup").classList.add("hidden"); }

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
  if ((e.source === "dictionary" || e.source === "ai") && e.card_created) {
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
// ---------- Übungs-Modus (SRS-Vokabeltrainer, Fundament) ----------
//
// Dritter Export-Weg neben PDF/Anki: Karten werden über "Zum Lernen
// hinzufügen" (siehe Render-Bar) in die ReviewState-Tabelle aufgenommen und
// hier mit FSRS wiederholt. Ablauf pro Karte: Eingabe -> /api/srs/check
// (Fuzzy-Match, ändert nichts am Lernstand) -> Bewertung anzeigen/vorschlagen
// -> Nutzer bestätigt/überschreibt -> /api/srs/answer (schreibt den FSRS-
// Lernstand fort) -> nächste Karte. Custom-Karten sind nicht automatisch
// prüfbar (freies HTML) - dort nur "Antwort zeigen" + Selbstbewertung wie bei Anki.
let reviewQueueItems = [];
let reviewIndex = 0;
let reviewCurrentItem = null;
let reviewSuggestedRating = null;
let reviewDueTotal = 0;

function resetReviewSession() {
  reviewQueueItems = [];
  reviewIndex = 0;
  reviewCurrentItem = null;
  reviewSuggestedRating = null;
  reviewDueTotal = 0;
  $("#reviewSession").classList.add("hidden");
  $("#reviewDone").classList.add("hidden");
  $("#reviewIntro").classList.add("hidden");
  $("#reviewLimitHint").classList.add("hidden");
}

async function enterReviewMode() {
  let data;
  try {
    data = await api("/api/srs/queue?limit=100");
  } catch (e) {
    data = { items: [], due_total: 0 };
  }
  reviewQueueItems = data.items;
  reviewDueTotal = data.due_total;
  $("#reviewIntro").classList.remove("hidden");
  $("#reviewSession").classList.add("hidden");
  $("#reviewDone").classList.add("hidden");
  $("#reviewCardsPanel").classList.add("hidden");
  $("#reviewDueCount").textContent = data.due_total > 0
    ? `${data.due_total} ${t("review.due_suffix")}`
    : t("review.none_due");
  $("#btnReviewStart").disabled = data.due_total === 0;
  updateReviewLimitHint();
  loadReviewStats();
}

function updateReviewLimitHint() {
  // `due_total` zählt ALLE fälligen Karten, `reviewQueueItems.length` nur
  // die nach Tageslimit ausgelieferten - ohne diesen Hinweis suggeriert
  // "Alle fälligen Karten geschafft" fälschlich, dass wirklich nichts mehr
  // offen ist, obwohl nur das Tageslimit weitere Karten zurückhält.
  const hint = $("#reviewLimitHint");
  const throttled = reviewDueTotal - reviewQueueItems.length;
  if (throttled > 0) {
    hint.textContent = `${t("review.limit_hint_prefix")} ${throttled} ${t("review.limit_hint_suffix")}`;
    hint.classList.remove("hidden");
  } else {
    hint.classList.add("hidden");
  }
}

async function loadReviewStats() {
  let stats;
  try {
    stats = await api("/api/srs/stats");
  } catch (e) {
    return;
  }
  $("#statReviewsToday").textContent = stats.reviews_today;
  $("#statNewToday").textContent = stats.new_today;
  $("#statRetention").textContent = stats.retention_7d === null ? "–" : `${stats.retention_7d}%`;
  $("#statTotalCards").textContent = stats.total_cards;
  $("#statStreak").textContent = stats.streak_days > 0 ? `🔥 ${stats.streak_days}` : "0";
  renderReviewHeatmap(stats.activity || {});

  const stage = stats.by_stage || {};
  const total = Math.max(1, stats.total_cards || 0);
  const bar = $("#reviewStageBar");
  bar.innerHTML = "";
  for (const key of ["new", "learning", "review", "relearning"]) {
    const n = stage[key] || 0;
    if (!n) continue;
    const seg = document.createElement("span");
    seg.className = `stage-${key}`;
    seg.style.width = `${(n / total) * 100}%`;
    seg.title = `${key}: ${n}`;
    bar.appendChild(seg);
  }
}

// Kalender-Heatmap (26 Wochen × 7 Tage, Montag oben) aus `activity`
// ({"YYYY-MM-DD": anzahl}, UTC-Tage wie im Backend). Die Zellen werden in
// Datumsreihenfolge ab dem Montag vor 25 Wochen emittiert - mit
// `grid-auto-flow: column` + 7 Zeilen füllt CSS daraus automatisch
// Spalte-für-Spalte (= Woche-für-Woche); die laufende Woche endet einfach
// beim heutigen Tag.
function renderReviewHeatmap(activity) {
  const wrap = $("#reviewHeatmapWrap");
  const grid = $("#reviewHeatmap");
  const hasActivity = Object.keys(activity).length > 0;
  wrap.classList.toggle("hidden", !hasActivity);
  if (!hasActivity) return;

  const DAY = 86400000;
  const todayUtc = Math.floor(Date.now() / DAY) * DAY;
  const weekday = (new Date(todayUtc).getUTCDay() + 6) % 7; // 0=Mo … 6=So
  const start = todayUtc - weekday * DAY - 25 * 7 * DAY;    // Montag vor 25 Wochen

  const level = (n) => (!n ? 0 : n < 10 ? 1 : n < 25 ? 2 : n < 50 ? 3 : 4);
  grid.innerHTML = "";
  for (let ts = start; ts <= todayUtc; ts += DAY) {
    const iso = new Date(ts).toISOString().slice(0, 10);
    const n = activity[iso] || 0;
    const cell = document.createElement("span");
    cell.className = `hm-cell hm-${level(n)}`;
    cell.title = `${iso}: ${n} ${t("review.heatmap.reviews")}`;
    grid.appendChild(cell);
  }
}

async function toggleReviewManage() {
  const panel = $("#reviewCardsPanel");
  if (panel.classList.contains("hidden")) {
    panel.classList.remove("hidden");
    await loadReviewCards();
  } else {
    panel.classList.add("hidden");
  }
}

async function loadReviewCards() {
  const list = $("#reviewCardsList");
  list.innerHTML = `<div class="wl-row"><span class="muted">${escapeHtml(t("common.loading"))}</span></div>`;
  let data;
  try {
    data = await api("/api/srs/cards");
  } catch (e) {
    list.innerHTML = `<div class="wl-row"><span class="status err">${escapeHtml(e.message)}</span></div>`;
    return;
  }
  list.innerHTML = "";
  if (!data.cards.length) {
    list.innerHTML = `<div class="wl-row"><span class="muted">${escapeHtml(t("review.manage_empty"))}</span></div>`;
    return;
  }
  for (const c of data.cards) {
    const row = document.createElement("div");
    row.className = "review-card-row";
    const info = document.createElement("div");
    info.className = "review-card-info";
    const front = document.createElement("span");
    front.className = "review-card-front";
    front.textContent = c.front;
    const meta = document.createElement("span");
    meta.className = "review-card-meta muted";
    const dueLabel = c.due_now ? t("review.manage_due") : t("review.manage_scheduled");
    meta.textContent = `${dueLabel} · ${c.items} ${t("review.manage_directions")} · ${c.reps} ${t("review.manage_reps")}`;
    info.append(front, meta);
    const del = document.createElement("button");
    del.className = "btn small danger";
    del.textContent = t("review.manage_remove");
    del.addEventListener("click", () => removeReviewCard(c.card_type, c.card_id));
    row.append(info, del);
    list.append(row);
  }
}

async function removeReviewCard(cardType, cardId) {
  if (!confirm(t("review.manage_remove_confirm"))) return;
  try {
    await api("/api/srs/remove", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ card_type: cardType, card_id: cardId }),
    });
    toast(t("review.manage_removed"));
    await loadReviewCards();
    // Zähler/Fällig-Anzeige aktualisieren.
    await enterReviewMode();
    $("#reviewCardsPanel").classList.remove("hidden");
  } catch (e) { toast(e.message, true); }
}

function startReviewSession() {
  reviewIndex = 0;
  $("#reviewIntro").classList.add("hidden");
  $("#reviewDone").classList.add("hidden");
  $("#reviewSession").classList.remove("hidden");
  showReviewCard();
}

async function showReviewCard() {
  if (reviewIndex >= reviewQueueItems.length) {
    $("#reviewSession").classList.add("hidden");
    $("#reviewDone").classList.remove("hidden");
    updateReviewLimitHint();
    loadReviewStats();
    return;
  }
  const item = reviewQueueItems[reviewIndex];
  reviewCurrentItem = item;
  reviewSuggestedRating = null;
  $("#reviewProgress").textContent = `${reviewIndex + 1} / ${reviewQueueItems.length}`;
  $("#reviewItemType").textContent = t(item.item_type === "reading" ? "review.reading_label" : "review.meaning_label");

  const frontEl = $("#reviewFront");
  if (item.card_type === "custom") {
    try {
      const full = await api(`/api/customcards/${item.card_id}`);
      frontEl.innerHTML = full.front_html || "";
    } catch (_) {
      frontEl.textContent = item.front;
    }
  } else {
    frontEl.textContent = item.front;
  }

  const input = $("#reviewInput");
  input.value = "";
  applyKanaInput(item);
  $("#reviewInputWrap").classList.toggle("hidden", item.card_type === "custom");
  $("#btnReviewSubmit").textContent = t(item.card_type === "custom" ? "review.show_answer_button" : "review.submit_button");
  $("#reviewRevealWrap").classList.add("hidden");
  document.querySelectorAll(".review-ratings button").forEach((b) => b.classList.remove("suggested"));
  if (item.card_type !== "custom") input.focus();
}

// WanaKana wandelt getippte Romaji live in Kana um - aber NUR bei japanischen
// Lesungen sinnvoll. Bei Bedeutungen (englischer/deutscher Text) oder anderen
// Zielsprachen muss die Bindung wieder gelöst werden, sonst würde die normale
// Texteingabe ins Kana-Alphabet verfälscht. Da immer dasselbe #reviewInput
// wiederverwendet wird, vor jeder Karte neu entscheiden.
function applyKanaInput(item) {
  const input = $("#reviewInput");
  if (typeof wanakana === "undefined") return;  // Vendor-Skript nicht geladen
  const activeLang = $("#activeTargetLangSelect").value || "ja";
  const wantKana = activeLang === "ja" && item.item_type === "reading" && item.card_type !== "custom";
  try {
    if (wantKana) {
      if (!input.dataset.kanaBound) { wanakana.bind(input); input.dataset.kanaBound = "1"; }
    } else if (input.dataset.kanaBound) {
      wanakana.unbind(input); delete input.dataset.kanaBound;
    }
  } catch (_) { /* WanaKana-Bindung ist optional, nie hart abbrechen */ }
}

function revealReview(correct, acceptedText) {
  const fb = $("#reviewFeedback");
  if (correct === true) { fb.textContent = t("review.feedback_correct"); fb.className = "review-feedback ok"; }
  else if (correct === false) { fb.textContent = t("review.feedback_incorrect"); fb.className = "review-feedback err"; }
  else { fb.textContent = ""; fb.className = "review-feedback"; }
  $("#reviewAccepted").innerHTML = acceptedText || "";
  $("#reviewInputWrap").classList.add("hidden");
  $("#reviewRevealWrap").classList.remove("hidden");
  document.querySelectorAll(".review-ratings button").forEach((b) => {
    b.classList.toggle("suggested", b.dataset.rating === reviewSuggestedRating);
  });
}

async function onReviewSubmit() {
  const item = reviewCurrentItem;
  if (!item) return;
  if (item.card_type === "custom") {
    let backHtml = "";
    try { backHtml = (await api(`/api/customcards/${item.card_id}`)).back_html || ""; } catch (_) {}
    reviewSuggestedRating = null;
    revealReview(null, backHtml);
    return;
  }
  const answer = $("#reviewInput").value;
  let result;
  try {
    result = await api("/api/srs/check", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ card_type: item.card_type, card_id: item.card_id, item_type: item.item_type, answer }),
    });
  } catch (e) { toast(e.message); return; }
  reviewSuggestedRating = result.suggested_rating;
  revealReview(result.correct, escapeHtml((result.accepted_answers || []).join(", ")));
}

async function onReviewRate(rating) {
  const item = reviewCurrentItem;
  if (!item) return;
  try {
    await api("/api/srs/answer", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ card_type: item.card_type, card_id: item.card_id, item_type: item.item_type, rating }),
    });
  } catch (e) {
    // Bewertung ist NICHT gespeichert worden - bei der nächsten Karte
    // weiterzumachen würde sie stillschweigend verlieren. Stattdessen auf
    // derselben Karte bleiben, damit der Nutzer erneut bewerten kann.
    toast(e.message);
    return;
  }
  reviewIndex++;
  showReviewCard();
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
    if (Object.keys(fieldOverrides).length) body.field_overrides = fieldOverrides;
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
  initSegmented("textAnalysisMode");
  initSegmented("modeTabs", (v) => {
    $("#modeLevel").classList.toggle("hidden", v !== "level");
    $("#modeCompose").classList.toggle("hidden", v !== "compose");
    $("#modeText").classList.toggle("hidden", v !== "text");
    $("#modeCustom").classList.toggle("hidden", v !== "custom");
    $("#modeWortliste").classList.toggle("hidden", v !== "wortliste");
    $("#modeReview").classList.toggle("hidden", v !== "review");
    document.querySelectorAll(".tab-group").forEach((g) => {
      g.classList.toggle("sel", !!g.querySelector(`button[data-v="${v}"]`));
    });
    // Tabelle + Verlauf sind eigene <section>-Panels UNTERHALB der Moduswahl,
    // nicht Teil von #modeReview - sie blieben bisher auch während des Übens
    // sichtbar und lenkten dort nur ab (kein Bezug zum aktuellen Review-Screen).
    $("#tablePanel").classList.toggle("hidden", v === "review");
    $("#historyPanel").classList.toggle("hidden", v === "review");
    if (v === "custom") loadCustoms();
    if (v === "wortliste") loadWortliste();
    if (v === "review") enterReviewMode();
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

  // Status-Pills im Header (WaniKani/DeepL/Gemini) führen direkt zur
  // passenden Einstellungen-Sektion, statt nur den Verbindungsstatus
  // anzuzeigen - ein Klick öffnet die Settings UND klappt die Sektion auf.
  [["connWanikani", "wanikani"], ["connDeepl", "deepl"], ["connGemini", "gemini"]].forEach(([id, rowName]) => {
    const el = $(`#${id}`);
    el.addEventListener("click", () => openSettingsSection(rowName));
    // role="button" auf einem <span> bekommt von sich aus keine Enter/Space-
    // Aktivierung wie ein echtes <button> - hier nachrüsten.
    el.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openSettingsSection(rowName); }
    });
  });

  $("#nativeLangSelect").addEventListener("change", onLanguageSelectChanged);
  $("#activeTargetLangSelect").addEventListener("change", onLanguageSelectChanged);
  $("#settingsToggle").addEventListener("click", () => $("#settingsOverlay").classList.remove("hidden"));
  $("#settingsClose").addEventListener("click", () => $("#settingsOverlay").classList.add("hidden"));
  $("#fieldEditClose").addEventListener("click", () => $("#fieldEditOverlay").classList.add("hidden"));
  $("#fieldEditSave").addEventListener("click", saveFieldEdits);
  $("#fieldEditResetAll").addEventListener("click", () => {
    delete fieldOverrides[_fieldEditCurrentId];
    const detail = _cardDetailCache[_fieldEditCurrentId];
    if (detail) renderFieldEditBody(detail, _fieldEditCurrentType);
  });
  $("#settingsOverlay").addEventListener("click", (e) => { if (e.target === $("#settingsOverlay")) $("#settingsOverlay").classList.add("hidden"); });
  $("#fieldEditOverlay").addEventListener("click", (e) => { if (e.target === $("#fieldEditOverlay")) $("#fieldEditOverlay").classList.add("hidden"); });
  $("#imageCardClose").addEventListener("click", () => $("#imageCardOverlay").classList.add("hidden"));
  $("#imageCardOverlay").addEventListener("click", (e) => { if (e.target === $("#imageCardOverlay")) $("#imageCardOverlay").classList.add("hidden"); });
  $("#imageCardGenerate").addEventListener("click", generateImageCard);
  $("#imageCardAccept").addEventListener("click", acceptImageCard);
  $("#imageCardRemove").addEventListener("click", removeImageCard);
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
      await api("/api/settings", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ deepl_key: $("#deeplInput").value, target_lang: $("#targetLang").value }) });
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

  $("#srsLimitsSave").addEventListener("click", async () => {
    const st = $("#srsLimitsStatus");
    st.textContent = ""; st.className = "status";
    try {
      await api("/api/settings", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          defaults: {
            srs_new_per_day: parseInt($("#srsNewPerDay").value, 10) || 0,
            srs_reviews_per_day: parseInt($("#srsReviewsPerDay").value, 10) || 0,
          },
        }),
      });
      toast("Gespeichert");
      st.textContent = "Gespeichert ✓"; st.className = "status ok";
      // Betrifft direkt, wie viele Karten "Wiederholen" ausliefert - Dashboard
      // neu laden, falls der Üben-Tab gerade offen ist.
      if (segValue("modeTabs") === "review") enterReviewMode();
    } catch (e) { st.textContent = e.message; st.className = "status err"; }
  });

  $("#accChangePw").addEventListener("click", async () => {
    const st = $("#accPwStatus");
    st.textContent = ""; st.className = "status";
    try {
      await api("/api/auth/change-password", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ current_password: $("#accCurrentPw").value, new_password: $("#accNewPw").value }),
      });
      $("#accCurrentPw").value = ""; $("#accNewPw").value = "";
      toast("Passwort geändert");
      st.textContent = t("settings.account.change_pw_ok"); st.className = "status ok";
    } catch (e) { st.textContent = e.message; st.className = "status err"; }
  });
  $("#accDelete").addEventListener("click", async () => {
    const st = $("#accDeleteStatus");
    st.textContent = ""; st.className = "status";
    if (!confirm(t("settings.account.delete_confirm"))) return;
    try {
      await api("/api/auth/account", {
        method: "DELETE", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password: $("#accDeletePw").value }),
      });
      location.reload();
    } catch (e) { st.textContent = e.message; st.className = "status err"; }
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
  $("#btnTextUpload").addEventListener("click", () => $("#textUploadFile").click());
  $("#textUploadFile").addEventListener("change", (e) => {
    const file = e.target.files && e.target.files[0];
    doTextUpload(file);
    e.target.value = "";
  });
  $("#btnTextEdit").addEventListener("click", backToTextEdit);
  $("#btnKiEdit").addEventListener("click", backToTextEdit);
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
  // Hover-Verknüpfung: Vokabel-Chip <-> Stelle im Original-Satz (data-hl teilt
  // sich Vokabeln-Token und Japanisch-Wort-Span über dieselbe Zeile/Position).
  $("#kiTable").addEventListener("mouseover", (e) => {
    const el = e.target.closest("[data-hl]");
    if (!el) return;
    document.querySelectorAll(`#kiTable [data-hl="${el.dataset.hl}"]`).forEach((n) => n.classList.add("ki-hl"));
  });
  $("#kiTable").addEventListener("mouseout", (e) => {
    const el = e.target.closest("[data-hl]");
    if (!el) return;
    document.querySelectorAll(`#kiTable [data-hl="${el.dataset.hl}"]`).forEach((n) => n.classList.remove("ki-hl"));
  });
  $("#wpAdd").addEventListener("click", wpAddClicked);
  $("#wpKnown").addEventListener("click", toggleKnownFromPopup);
  $("#wordPopupClose").addEventListener("click", closeWordPopup);
  $("#wlContextClose").addEventListener("click", closeWlContext);
  document.addEventListener("click", (e) => {
    const pop = $("#wordPopup");
    if (!pop.classList.contains("hidden") && !pop.contains(e.target) && !e.target.closest(".word-token, .ki-freq-chip")) closeWordPopup();
    const wlPop = $("#wlContextPopup");
    if (!wlPop.classList.contains("hidden") && !wlPop.contains(e.target) && !e.target.closest(".chip-btn")) closeWlContext();
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

  $("#btnReviewStart").addEventListener("click", startReviewSession);
  $("#btnReviewManage").addEventListener("click", toggleReviewManage);
  $("#btnReviewSubmit").addEventListener("click", onReviewSubmit);
  $("#reviewInput").addEventListener("keydown", (e) => { if (e.key === "Enter") onReviewSubmit(); });
  document.querySelectorAll(".review-ratings button").forEach((b) => {
    b.addEventListener("click", () => onReviewRate(b.dataset.rating));
  });
  // Tastatur-Shortcuts wie bei Anki: nach dem Aufdecken 1–4 = Nochmal/Schwer/
  // Gut/Leicht, Enter übernimmt den vorgeschlagenen Wert. Nur aktiv, wenn der
  // Review-Screen läuft UND die Antwort aufgedeckt ist - sonst würde das
  // Tippen von Ziffern in andere Felder abgefangen.
  const _ratingKeys = { "1": "again", "2": "hard", "3": "good", "4": "easy" };
  document.addEventListener("keydown", (e) => {
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    if ($("#modeReview").classList.contains("hidden")) return;
    if ($("#reviewSession").classList.contains("hidden")) return;
    if ($("#reviewRevealWrap").classList.contains("hidden")) return;
    if (e.key in _ratingKeys) { e.preventDefault(); onReviewRate(_ratingKeys[e.key]); }
    else if (e.key === "Enter" && reviewSuggestedRating) { e.preventDefault(); onReviewRate(reviewSuggestedRating); }
  });

  $("#checkAll").addEventListener("change", (e) => selectAll(e.target.checked));
  $("#selAll").addEventListener("click", () => selectAll(true));
  $("#selNone").addEventListener("click", () => selectAll(false));
  $("#btnRender").addEventListener("click", doRender);
  $("#btnSrsAdd").addEventListener("click", addSelectionToSrs);

  $("#authToggleMode").addEventListener("click", () => setAuthMode(authMode === "signup" ? "login" : "signup"));
  $("#authSubmit").addEventListener("click", submitAuthForm);
  $("#authPassword").addEventListener("keydown", (e) => { if (e.key === "Enter") submitAuthForm(); });
  $("#logoutBtn").addEventListener("click", doLogout);

  // PWA: Service Worker registrieren (best-effort - ohne SW funktioniert die
  // App unverändert, nur Installieren/Offline-Fallback entfallen dann).
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  }

  checkAuthAndInit();
});
