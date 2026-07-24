# CLAUDE.md

Anleitung für Claude Code für dieses Projekt. Bitte vor jeder Implementierung lesen.

## Projektziel

> **Historischer Ursprung dieses Dokuments:** Der Rest dieses Abschnitts
> beschreibt den ursprünglichen Plan als reines CLI-Tool. Das Projekt ist
> seitdem zu einer Multi-User-Webapp (**Shiori**, Flask) gewachsen; das CLI
> (`kanji_cards.py`-Aufruf mit `argparse`) wurde entfernt, `kanji_cards.py`
> selbst lebt als reine Kartenbau-/Render-Bibliothek weiter (siehe README
> "Architektur" für den aktuellen Stand). Die Kartenlogik/Layout-Ziele unten
> gelten unverändert.

CLI-Tool (Python 3), das aus einem **WaniKani-Level** doppelseitig bedruckbare
**Kanji-Karteikarten als PDF** erzeugt – **6 Karten pro Seite** (2 Spalten × 3 Zeilen).

**Vorderseite:** nur das Kanji, groß und zentriert.
**Rückseite:**
- Bedeutungen (primär zuerst)
- Lesungen, getrennt nach On'yomi / Kun'yomi
- eine Beispielvokabel + Bedeutung
- ein Beispielsatz + Übersetzung

Ziel ist ein *sehr sauberes, druckfertiges* Layout – Ästhetik zählt, nicht nur Korrektheit.

---

## Setup & Befehle

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python -m shiori.webapp    # Webapp unter http://localhost:8000, Token nach Login in den Einstellungen
```

- Token **niemals** hardcoden – wird nach dem Login pro Nutzer in den Einstellungen hinterlegt.
- `.env`, `*.pdf` und `.cache/` gehören in `.gitignore`.

---

## WaniKani API v2 – die relevanten Fakten

- Base URL: `https://api.wanikani.com/v2/`
- Auth-Header bei **jedem** Request: `Authorization: Bearer <token>` (nur HTTPS).
- Optional zur Stabilität: `Wanikani-Revision: 20170710`.
- Rate Limit ~60 Requests/Minute → bei HTTP **429** mit Backoff wiederholen.

### Alle Kanji eines Levels holen

```
GET /subjects?types=kanji&levels=<N>
```

Antwort ist eine *collection* mit `data: [ { id, object, data{…} }, … ]`.
Ein Level hat ~30–40 Kanji → passt in eine Seite (Limit 1000/Seite), **keine Paginierung nötig**.

**Wichtig – Filter-Parameter unterscheiden sich je Endpoint:**
Beim `/subjects`-Endpoint heißt der ID-Filter `ids` (NICHT `subject_ids`).
`subject_ids` gilt nur für `assignments` / `reviews` / `review_statistics`. Häufige Fehlerquelle.

### Felder eines **Kanji**-Objekts (`data`)

- `characters` – das Kanji (String)
- `meanings` – Liste von `{ meaning, primary, accepted_answer }`
- `readings` – Liste von `{ reading, primary, accepted_answer, type }`,
  `type` ∈ `onyomi | kunyomi | nanori`
- `amalgamation_subject_ids` – IDs der Vokabeln, die dieses Kanji verwenden ← **Schlüssel für Beispiele!**

### Felder eines **Vokabel**-Objekts (`data`)

- `characters`, `meanings` (wie oben), `readings` (`{ reading, primary, … }`, ohne on/kun-Typ)
- `context_sentences` – Liste von `{ en, ja }`
- `parts_of_speech`

---

## ⚠️ Zentraler Knackpunkt: Beispielvokabel & Beispielsatz

**Kanji-Objekte enthalten selbst KEINE Beispielvokabeln oder -sätze.**
Der Ablauf ist zweistufig:

1. Aus jedem Kanji `amalgamation_subject_ids` sammeln.
2. Diese Vokabel-Objekte **gebündelt** nachladen:
   `GET /subjects?ids=<id1,id2,…>` (Batch, nicht einzeln → schont Rate Limit).
3. Pro Kanji **eine** repräsentative Vokabel wählen (Default: die mit der **niedrigsten `level`**,
   bei Gleichstand die erste). Aus ihr:
   - Beispielvokabel = `characters` + primäre Bedeutung
   - Beispielsatz = erstes Element aus `context_sentences` (`ja` + `en`)
4. Fallback, wenn ein Kanji keine Vokabel/keinen Satz hat: Feld auf der Rückseite still weglassen,
   Karte trotzdem erzeugen. Nie hart abbrechen.

Alle Vokabeln **einmal** vorab laden und in einer Map `{id: vocab}` cachen.

---

## ⚠️ Doppelseitiger Druck: Rückseiten spaltenweise spiegeln

Damit beim Duplexdruck (Standard: **Wenden an der langen Kante**) die Rückseite exakt
zur Vorderseite passt, muss das Rückseiten-Raster **pro Zeile in der Spaltenreihenfolge gespiegelt** werden.

Bei 2 Spalten heißt das je Zeile: Karte an Position `(zeile, spalte)` landet hinten auf
`(zeile, 1 - spalte)`. Für die 6er-Seite wird aus Vorderseiten-Reihenfolge

```
1 2        2 1
3 4   →    4 3   (Rückseite)
5 6        6 5
```

Diese Spiegelung als eigene, getestete Funktion kapseln (`mirror_backside(cards, cols)`).
Flip-Kante über `--duplex {long-edge|short-edge}` konfigurierbar machen; bei `short-edge`
werden stattdessen die **Zeilen** gespiegelt. Das ist der häufigste Fehler bei Karteikarten –
mit einer kleinen Test-Seite (Karten durchnummeriert) verifizieren.

---

## PDF-Erzeugung

**Empfehlung: HTML/CSS → WeasyPrint.**
Grund: „sehr schöne" Karten mit sauberem CJK-Umbruch, Typografie und exaktem 2×3-Raster
sind über CSS (`@page`, CSS-Grid, `page-break`) deutlich einfacher und hübscher als mit
manueller Koordinaten-Rechnung.

- Ein Jinja2-Template rendert Vorder- und Rückseiten abwechselnd; `@page { size: A4; margin: … }`.
- Karten via CSS-Grid `grid-template-columns: 1fr 1fr; grid-template-rows: repeat(3, 1fr)`.
- Optionale Schnittmarken/dezente Rahmen als Schnitthilfe.
- Nachteil: WeasyPrint braucht System-Libs (Pango/Cairo). In `README` dokumentieren.

**Alternative: reportlab** (reine Python-Lösung, keine System-Libs), falls WeasyPrint-Setup
stört. Dann Layout über `platypus`/Canvas mit fester mm-Geometrie. Aufwändiger für schöne
Typografie und Umbruch.

Bei der gewählten Engine bleiben – nicht mischen.

### Geometrie (A4, Default)

- Seite 210 × 297 mm, Außenrand ~10 mm.
- 2×3 → Karte ~95 × 92 mm. Innenabstand (Gutter) ~4 mm.
- Kanji auf der Vorderseite riesig (z. B. 120–160 pt), vertikal + horizontal zentriert.

---

## CJK-Font (Pflicht!)

Ohne japanische Schrift werden Kanji als Tofu (□) gerendert.

- Empfehlung: **Noto Sans JP** oder **Noto Serif JP** (statische TTF, keine Variable Fonts –
  die machen bei PDF-Engines Probleme).
- Font ins Repo unter `fonts/` legen **oder** Pfad per `--font` übergeben; Default sinnvoll setzen.
- Bei WeasyPrint über `@font-face` einbinden; bei reportlab via `pdfmetrics.registerFont(TTFont(...))`.
- Fürs Kanji selbst gern eine kräftige Serifen-/Mincho-Variante, für Lesungen/Text eine gut
  lesbare Sans – nicht zwingend, aber wertet die Karten auf.

---

## Vorgeschlagene Architektur

Ein Skript reicht, aber klar in Funktionen trennen (einzeln testbar):

```
kanji_cards.py
├── cli()                      # argparse: level, --output, --font, --duplex
├── wk_client
│   ├── fetch_kanji(level)             # GET /subjects?types=kanji&levels=N
│   ├── fetch_vocab(ids)              # GET /subjects?ids=…  (Batch, gecacht)
│   └── _request()                    # Auth-Header, 429-Backoff, Revision-Header
├── model
│   ├── build_card(kanji, vocab_map)  # → Card-Dataclass (front/back-Felder)
│   └── pick_example_vocab(kanji, vocab_map)
├── layout
│   ├── paginate(cards, per_page=6)   # 6er-Chunks
│   ├── mirror_backside(chunk, cols)  # Duplex-Spiegelung
│   └── render_pdf(pages, output)     # HTML+WeasyPrint (oder reportlab)
└── main()
```

Dataclass `Card`: `kanji`, `meanings: list[str]`, `onyomi: list[str]`, `kunyomi: list[str]`,
`vocab: str|None`, `vocab_meaning: str|None`, `sentence_ja: str|None`, `sentence_en: str|None`.

---

## Konventionen & Robustheit

- Nur `requests`, `weasyprint`/`reportlab`, `jinja2`, `python-dotenv`. Schlank halten.
- **Response-Cache** unter `.cache/` (JSON pro Level), damit Iterationen am Layout nicht ständig
  die API treffen. `--no-cache` zum Umgehen.
- 429/5xx: exponentielles Backoff, wenige Retries, dann klare Fehlermeldung.
- Fehlender/ungültiger Token → verständliche Meldung, kein Stacktrace.
- Falls ein Textfeld WaniKani-Markup enthält (`<kanji>`, `<ja>`, `<reading>` …): Tags strippen.
  Bedeutungen und `context_sentences` sind i. d. R. plain – trotzdem defensiv behandeln.
- Type Hints überall. Kernfunktionen (`pick_example_vocab`, `mirror_backside`, `paginate`)
  mit kleinen `pytest`-Tests absichern.

---

## Offene Entscheidungen (Defaults gesetzt, bei Bedarf ändern)

1. **Sprache der Rückseite:** Default **Englisch** (WaniKani liefert nur EN). Deutsch nur über
   zusätzliche Übersetzungs-API → bewusst nicht im MVP. Falls gewünscht, als optionalen
   `--lang de`-Schalter mit klar getrenntem Übersetzer-Modul nachrüsten.
2. **PDF-Engine:** Default **WeasyPrint**. Vor Umsetzung bestätigen lassen, falls reportlab bevorzugt.
3. **Duplex-Flip:** Default **lange Kante**. Über `--duplex` änderbar.
4. **Papierformat:** Default **A4**. Ggf. `--paper letter` ergänzen.

Bei Unklarheit in diesen Punkten kurz nachfragen, bevor größere Layout-Arbeit beginnt.
