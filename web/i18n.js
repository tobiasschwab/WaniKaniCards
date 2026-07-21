"use strict";

// i18n.js – schlankes UI-Chrome-Übersetzungssystem (Multi-Language-Umbau,
// siehe README "Multi-Language-Architektur"): NICHT zu verwechseln mit der
// gelernten Zielsprache (WaniKani/Kanji/Karteninhalte bleiben unabhängig
// davon in der jeweiligen Zielsprache) - dies übersetzt nur die feste
// Bedienoberfläche (Menüs, Buttons, Überschriften) nach der Muttersprache
// des Nutzers (`User.native_lang`, siehe /api/auth/me).
//
// Absichtlich klein gehalten: ein `data-i18n="key"`-Attribut ersetzt
// `textContent`, `data-i18n-title` ersetzt das `title`-Attribut (Tooltips).
// Deckt aktuell die wichtigste Chrome ab (Header, Login, Einstellungen,
// Moduswahl) - nicht jeden dynamisch erzeugten String im restlichen
// app.js. Fällt bei fehlendem Key oder fehlender Sprachdatei auf Deutsch
// zurück (der historische Ausgangszustand der App), nie auf einen leeren
// String oder einen rohen Key.

let _i18nDict = {};
let _i18nLang = "de";
const _i18nCache = {};

async function _loadI18nDict(lang) {
  if (_i18nCache[lang]) return _i18nCache[lang];
  try {
    const r = await fetch(`/i18n/${lang}.json`);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const data = await r.json();
    _i18nCache[lang] = data;
    return data;
  } catch (_) {
    return null;
  }
}

function t(key) {
  return _i18nDict[key] || key;
}

function applyI18n(root = document) {
  root.querySelectorAll("[data-i18n]").forEach((el) => {
    el.textContent = t(el.getAttribute("data-i18n"));
  });
  root.querySelectorAll("[data-i18n-title]").forEach((el) => {
    el.title = t(el.getAttribute("data-i18n-title"));
  });
  root.querySelectorAll("[data-i18n-placeholder]").forEach((el) => {
    el.placeholder = t(el.getAttribute("data-i18n-placeholder"));
  });
}

async function setUiLanguage(lang) {
  lang = (lang || "de").toLowerCase();
  const dict = (await _loadI18nDict(lang)) || (await _loadI18nDict("de")) || {};
  _i18nDict = dict;
  _i18nLang = dict === (_i18nCache["de"]) && lang !== "de" ? "de" : lang;
  document.documentElement.lang = _i18nLang;
  applyI18n();
}
