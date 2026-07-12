# WaniKani Kanji-Karteikarten

CLI-Tool (Python 3), das aus einem **WaniKani-Level** doppelseitig bedruckbare
**Kanji-Karteikarten als PDF** erzeugt – **4 Karten pro Seite** auf **A4 quer**
(2 × 2).

- **Vorderseite:** nur das Kanji, groß und zentriert.
- **Rückseite:** Bedeutungen · Lesungen (On/Kun) · **Eselsbrücken** (Bedeutung
  & Lesung) · eine Beispielvokabel mit Lesung · ein Beispielsatz mit Übersetzung.

Weitere Eigenschaften:

- **Nur zwei Schnittkanten** je Blatt: die mittige Kreuzlinie (waagerecht +
  senkrecht). Die Karten stoßen in der Mitte aneinander; die Außenkanten sind
  Blattrand und werden nicht geschnitten.
- **Lochbereich oben links** auf jeder Karte (mit dezenter Loch-Markierung) –
  zum Lochen und Aufhängen an einem Ring. Der Bereich ist auf der Rückseite
  spiegelbildlich reserviert, sodass ein einziges Loch durch beide Seiten passt.
- Das Rückseiten-Raster wird für den Duplexdruck automatisch gespiegelt, sodass
  Vorder- und Rückseite exakt zusammenpassen.

## Vorschau

Beispielseite (Level 1, `--sample`):

| Vorderseite | Rückseite |
|---|---|
| ![Vorderseite](previews/sample_page1_front.png) | ![Rückseite](previews/sample_page2_back.png) |

Das fertige PDF liegt unter [`previews/sample_level1.pdf`](previews/sample_level1.pdf).

## Setup

WeasyPrint benötigt die System-Libraries **Pango**, **Cairo** und
**GDK-PixBuf**. Unter Debian/Ubuntu:

```bash
sudo apt-get install libpango-1.0-0 libpangocairo-1.0-0 libcairo2 \
                     libgdk-pixbuf-2.0-0 libffi-dev
```

(macOS: `brew install pango cairo gdk-pixbuf libffi`. Details:
<https://doc.courtbouillon.org/weasyprint/stable/first_steps.html>)

Dann:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

Die japanischen Schriften (Noto Serif JP / Noto Sans JP) liegen bereits unter
`fonts/` im Repo – es ist keine System-Schrift nötig.

## Verwendung

```bash
# WaniKani-Token holen: wanikani.com → Settings → API Tokens (read-only genügt)
export WANIKANI_API_TOKEN="…"

python kanji_cards.py 5                 # Level 5 → cards.pdf
python kanji_cards.py 5 -o level5.pdf   # eigener Dateiname
```

Alternativ kann der Token in einer `.env`-Datei stehen:

```
WANIKANI_API_TOKEN=…
```

### Ohne Token ausprobieren

```bash
python kanji_cards.py --sample          # nutzt fonts/-Demodaten (Level 1)
```

### Optionen

| Option | Default | Beschreibung |
|---|---|---|
| `level` | – | WaniKani-Level (1–60) |
| `--output`, `-o` | `cards.pdf` | Ausgabedatei |
| `--duplex {long-edge,short-edge}` | `long-edge` | Wende-Kante für den Duplexdruck |
| `--paper {a4,letter}` | `a4` | Papierformat |
| `--font PFAD` | `fonts/NotoSerifJP-SemiBold.ttf` | Schrift für das große Kanji |
| `--no-cache` | – | API-Cache unter `.cache/` umgehen |
| `--no-cut-marks` | – | Kreuz-Schnittlinien und Loch-Markierung weglassen |
| `--sample` | – | Beispieldaten ohne API-Token verwenden |

## Drucken

1. PDF mit **beidseitigem Druck (Duplex)** und **Querformat** öffnen.
2. Wende-Option passend zu `--duplex` wählen:
   - `long-edge` → *Wenden an der langen Kante* (Standard).
   - `short-edge` → *Wenden an der kurzen Kante*.
3. „Tatsächliche Größe“ / „100 %“ wählen (nicht „An Seite anpassen“), damit die
   Geometrie exakt bleibt.
4. Jedes Blatt **einmal waagerecht und einmal senkrecht mittig** entlang der
   gestrichelten Kreuzlinie schneiden → 4 Karten.
5. Oben links (Vorderseite) an der gestrichelten Kreis-Markierung lochen und die
   Karten auf einen Ring ziehen.

Tipp: Vor dem Serienlauf eine Seite testen und Vorder-/Rückseite gegen das
Licht halten, um die Ausrichtung der Wende-Kante zu prüfen. Passt es nicht,
`--duplex short-edge` versuchen.

## Architektur

Ein Skript (`kanji_cards.py`), klar in Funktionen getrennt:

- **WaniKani-Client** – `fetch_kanji(level)`, `fetch_vocab(ids)` (Batch + Cache),
  `_request()` mit Auth-/Revision-Header und 429/5xx-Backoff.
- **Modell** – `build_card()`, `pick_example_vocab()` (Default: niedrigstes
  Vokabel-Level, bei Gleichstand das erste).
- **Layout** – `paginate()`, `mirror_backside()` (Duplex-Spiegelung),
  `render_pdf()` (Jinja2-Template → WeasyPrint).

Kanji-Objekte enthalten selbst **keine** Beispiele; die Vokabeln werden über
`amalgamation_subject_ids` **gebündelt** nachgeladen und gecacht.

## Tests

```bash
pip install pytest
pytest
```

Abgedeckt sind die Kernfunktionen `pick_example_vocab`, `mirror_backside`,
`paginate`, `build_card` und `strip_markup`.
