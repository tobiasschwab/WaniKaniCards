# WaniKani Kanji-Karteikarten

CLI-Tool (Python 3) **und Web-Frontend**, das aus einem **WaniKani-Level**
doppelseitig bedruckbare **Karteikarten als PDF** erzeugt – wahlweise für die
**Kanji** oder die **Radicals** des Levels (`--type`).

> **Web-Frontend & Docker:** Für die grafische Oberfläche (API-Token setzen,
> Level wählen, Download, Verlauf) siehe [Shiori (Docker)](#web-frontend-shiori-docker).

**Kanji-Karten**

- **Vorderseite:** nur das Kanji, groß und zentriert.
- **Rückseite:** das Kanji als Referenz (oben, etwas größer als der Text) ·
  Bedeutungen · Lesungen (On/Kun) · **Zusammensetzung** (die Radicals, aus denen
  das Kanji besteht, mit Bedeutung) · **Eselsbrücken** (Mnemonic & Reading) ·
  eine Beispielvokabel mit Lesung · **Beispielsätze** mit Übersetzung – WaniKani
  liefert pro Vokabel oft mehrere `context_sentences`; das PDF zeigt aus
  Platzgründen (feste Kartenhöhe) maximal **zwei**, der Anki-Export **alle**
  vorhandenen. Vokabel + Sätze können optional mit **Vertonung**
  (`vocab_audio_url` / `sentence_audio_url` je Satz auf der `Card`) versehen
  sein, die als abspielbarer Player **nur im Anki-Export** erscheint (im PDF
  ohne Wirkung, da Papier nicht abspielbar ist). Vokabel-Audio wird
  automatisch aus WaniKanis `pronunciation_audios` übernommen; für
  Beispielsätze liefert WaniKani selbst keine Vertonung – dieses Feld
  (`context_sentences[…].audios`, gleiches Schema) lässt sich manuell in den
  Subject-Daten nachtragen. Im Anki-Export werden diese Audio-URLs als echte
  MP3/OGG-Dateien heruntergeladen und direkt ins `.apkg` eingebettet (nicht
  nur verlinkt) – die Karten sind danach vollständig offline abspielbar, ganz
  ohne laufende Verbindung zu WaniKani.

**Radical-Karten**

- **Vorderseite:** das Radical (Zeichen, oder – falls kein Unicode-Zeichen
  existiert – das WaniKani-Bild).
- **Rückseite:** das Radical als Referenz (Zeichen oder Bild, oben) · Bedeutung ·
  **Mnemonic** · eine Liste der ersten zugehörigen Kanji mit Lesung und Bedeutung.

**Vokabel-Karten**

- **Vorderseite:** das Wort, groß (automatisch an die Länge angepasst).
- **Rückseite:** das Wort als Referenz (oben) · Bedeutungen · Wortart · Lesung ·
  optional die eigene **Vertonung** (Anki-Export, s. o.) · **Mnemonics** ·
  Beispielsätze (PDF max. zwei, Anki alle vorhandenen).

Im Anki-Export trägt jede Rückseite (Radical/Kanji/Vokabel) außerdem einen
dezenten Link **„WaniKani ↗"** zur Original-Seite des Subjects
(`document_url`) – nur dort, das PDF verzichtet darauf (ein Link auf Papier
wäre nutzlos).

Damit man zum Abfragen nicht umdrehen muss, steht das Zeichen der Vorderseite
(Kanji/Radical/Vokabel) **auch auf der Rückseite oben** – deutlich kleiner als
vorne, aber etwas größer als der übrige Text.

Jede **Vorderseite** trägt oben rechts schlichte **Tags** (Typ + WaniKani-Level,
z. B. `KANJI` / `LV 1`); die Rückseite zeigt – sofern ein Token gesetzt ist –
dezent unten rechts den **WaniKani-Benutzernamen**.

## Vier Wege zu den Karten (Web)

Die Moduswahl ist in zwei Gruppen sortiert: **„Karten erstellen"** (die vier
Wege unten) und **„Wortschatz"** (die [Wortliste](#wortliste) – dort geht es
ums Nachschlagen/Verfolgen, nicht ums Erzeugen neuer Karten).

1. **Level-Stapel:** ein Level auflisten – per Checkbox **Radicals**, **Kanji**
   und/oder **Vokabeln** kombinieren (mehrere gleichzeitig möglich; alle drei
   angehakt exportiert den kompletten Levelinhalt in einem Rutsch).
2. **Suche (Vokabel/Kanji, rekursiv):** eine Vokabel oder ein Kanji suchen und über
   die **Komposition absteigen** – die enthaltenen Kanji und Radicals werden
   rekursiv mit aufgelöst (Vokabel → Kanji → Radicals). Mehrere Vokabeln
   nacheinander suchen und anklicken **hängt** deren Kompositionen an dieselbe
   Tabelle an (dedupliziert); **„Tabelle leeren“** setzt zurück.
3. **Aus Text:** einen kompletten mehrzeiligen japanischen Text einfügen
   (Artikel, Kapitel, Dialog …) und **verarbeiten**. Der Text wird
   **lemmatisiert** ([Janome](https://github.com/mocobeta/janome), reines
   Python – jedes Wort auf seine Wörterbuch-Grundform zurückgeführt, z. B.
   „大きく" → „大きい") und gegen WaniKani abgeglichen. Anschließend erscheint
   der Text **schreibgeschützt**, mit jedem erkannten Wort **anklickbar** und
   farblich markiert: <br>
   ![Text-Modus: farbig markierte Wörter](previews/webui_text.png) <br>
   Ein Klick öffnet ein Popup mit Bedeutung, Typ und Level – von dort aus
   **gezielt einzelne Wörter** zur Tabelle hinzufügen (rekursiv inkl. Kanji &amp;
   Radicals, wie im Kompositions-Modus) oder als **„bekannt" markieren**, ganz
   ohne eine Karte zu erzeugen (z. B. für Wörter, die man von woanders schon
   kann). Anders als bei den anderen drei Wegen landet **nicht automatisch
   alles** aus dem Text in der Tabelle – nur was per Popup bewusst hinzugefügt
   wird. Oben eine laufende **Prozentanzeige**, wie viel des Textes durch
   bekannte Wörter „verstanden" wird (Vorkommen-basiert, nicht nur eindeutige
   Wörter – ein zehnmal vorkommendes bekanntes Wort zählt entsprechend mehr).
   **Besonderheit bei Vokabeln:** Wird eine im Text gefundene Vokabel zur
   Tabelle hinzugefügt, wird der Original-Satz aus deinem Text als **erster
   Beispielsatz** auf der Karte verwendet (WaniKanis eigener Beispielsatz
   rutscht dafür als weiterer Satz nach hinten, geht also nicht verloren) –
   sowohl auf der eigenständigen Vokabel-Karte als auch im eingebetteten
   Beispiel einer Kanji-Karte, falls dieselbe Vokabel dort herangezogen wird.

   **Wörterbuch-Fallback für kanji-freie Wörter:** WaniKani indiziert Vokabeln
   über ihre Kanji-Schreibweise – vereinfachte Lesetexte, die bewusst
   Hiragana statt Kanji verwenden (z. B. NHK Easy News), treffen darüber also
   fast nie. Für Wörter **ohne jedes Kanji**, die WaniKani nicht kennt, greift
   deshalb automatisch ein Fallback über [JMdict](https://www.edrdg.org/wiki/index.php/JMdict-EDICT_Dictionary_Project)
   (Open-Source-Wörterbuch, deutsche Edition, einmalig als JSON geladen und
   unter `.cache/jmdict/` zwischengespeichert). Kanji-haltige unbekannte Wörter bleiben bewusst
   Klartext (die gehören als Kanji gelernt, nicht als Dictionary-Karte).
   Zwei Farben im Text zeigen den Status jedes Worts – unabhängig davon, ob
   es über WaniKani oder das Wörterbuch kommt und ob es manuell markiert oder
   über eine Karte „bekannt" wurde:

   | Farbe | Bedeutung |
   |---|---|
   | Grün „bekannt" | manuell als bekannt markiert **oder** Karte/Export existiert bereits |
   | Blau „unbekannt" | weder markiert noch Karte/Export vorhanden |
   | Violett „Grammatik-Info" | nur mit Gemini-Analyse (s. u.): Partikel/Grammatikform ohne WaniKani-/Dictionary-Treffer, aber von Gemini erklärt – rein informativ, keine Karte erzeugbar |

   Details (Quelle WaniKani/Wörterbuch/Gemini, ob manuell markiert oder weil
   eine Karte existiert) zeigt das Popup beim Anklicken des Worts.

   Für Dictionary-Wörter erzeugt das Popup statt „Zur Tabelle" den Button
   **„Dictionary-Karte erstellen"** – ein neuer, WaniKani-unabhängiger
   Kartentyp (siehe [Dictionary-Karten](#dictionary-karten)).

   **Optional: Analyse per Gemini.** Der Button **„✨ Mit Gemini analysieren"**
   (statt „Verarbeiten") schickt jeden Satz an Googles
   [Gemini-API](https://ai.google.dev/) (Key + Modell in den Einstellungen
   hinterlegen) und liefert bessere Wortgrenzen, die grammatikalische
   Funktion jedes Worts/Partikels sowie – per **ⓘ**-Symbol am Satzende – eine
   kurze Grammatik-Erklärung und eine natürliche deutsche Übersetzung des
   ganzen Satzes. Kein automatischer Ersatz für „Verarbeiten": ein expliziter
   Klick, da jeder Aufruf Kosten verursacht und Satztexte an Google sendet.
   Schlägt Gemini für einen Satz fehl (kein Key, Netzwerkfehler, Quota) oder
   passen seine Wortgrenzen nicht exakt zum Original, bleibt für genau diesen
   Satz die normale Janome-Analyse bestehen – nie ein harter Abbruch.
4. **Frei erstellen:** eigene Karten in zwei **freien Rich-Text-Feldern**
   (Vorder- und Rückseite) anlegen – Text formatieren (fett/kursiv/unterstrichen,
   Titel, Merk-Box, Liste, große Schrift) und **Bilder** einfügen. Beide Felder
   starten mit einem **Layout-Vorschlag** (Vorderseite: groß & zentriert;
   Rückseite: Titel · Freitext · Merk-Box). Die **Tags** werden separat eingegeben
   und immer vorne oben rechts gedruckt. Optional aus WaniKani vorbefüllen.

Alle vier Wege füllen dieselbe **Tabelle**; dort wählt man ein oder mehrere
Elemente aus und erzeugt daraus **ein PDF** oder **Anki-Paket**.

**Bereits Exportiertes wird sich gemerkt:** Jede Zeile, deren Subject-ID schon
einmal in einem erfolgreich abgeschlossenen Export (PDF oder Anki, aus dem
**Verlauf**) enthalten war, wird in der Tabelle mit einem dezenten
„✓ exportiert"-Badge markiert und ist **standardmäßig abgewählt** – alles
andere bleibt wie gewohnt angehakt (Level-Stapel, Kompositions- und Text-Modus).
Ermittelt sich zentral aus dem Job-Verlauf – keine eigene Datenbank nötig.

**„Bekannt" ist mehr als „exportiert":** Im Text-Modus lässt sich ein Wort auch
**manuell als bekannt markieren**, ohne je eine Karte dafür zu erzeugen (z. B.
weil man es schon aus dem Unterricht kennt). Das fließt in dieselbe Färbung im
Text und in die Prozentanzeige ein wie tatsächlich exportierte/erstellte
Wörter – landet aber in einer eigenen, kleinen Datei (`data/known.json`),
getrennt vom Export-/Karten-Verlauf.

## Dictionary-Karten

Ein fünfter, WaniKani-**unabhängiger** Kartentyp für kanji-freie Wörter aus
dem Text-Modus (siehe oben), z. B. für vereinfachte Lesetexte:

- **Vorderseite:** das Wort in Hiragana/Katakana, groß und zentriert.
- **Rückseite:** das Wort als Referenz, die Bedeutung (aus JMdict), optional
  ein Kanji-Hinweis („auch 試合") und – falls beim Erstellen ein Beispielsatz
  aus dem Text vorlag – dieser Satz mitsamt **deutscher Übersetzung**.

Die Übersetzung läuft optional über die [DeepL-API](https://www.deepl.com/de/pro-api):
API-Key in den Einstellungen eintragen (⚙ → **DeepL-API-Key**, landet wie der
WaniKani-Token nur in `data/settings.json`, nie im Repo) – ohne Key wird die
Karte trotzdem erstellt, nur ohne Satzübersetzung. Dictionary-Karten landen
im Anki-Export mit einem eigenen, blauen Akzent und lassen sich zusammen mit
WaniKani- und freien Karten in **einem** gemeinsamen Export kombinieren.

## Wortliste

Ein eigener Tab **„Wortliste"** zeigt alle bekannten Wörter an einem Ort –
egal ob sie über „Als bekannt markieren" im Text-Modus, über eine erstellte
WaniKani-/Dictionary-Karte oder **manuell direkt hier** hinzugekommen sind:

![Web-Frontend: Wortliste](previews/webui_wortliste.png)

- **Volltextsuche** filtert clientseitig nach Zeichen oder Bedeutung.
- **Manuell hinzufügen:** Wort + Bedeutung eintragen – unabhängig von
  WaniKani/Wörterbuch, für Wörter, die man einfach schon von woanders kennt.
- **Entfernen** (✕): rein manuelle Einträge verschwinden komplett. Bei
  WaniKani-Wörtern entfernt es nur die manuelle „bekannt"-Markierung – bleibt
  das Wort exportiert, taucht es weiterhin auf, jetzt aber ohne den „bekannt
  markiert"-Badge (ein Export lässt sich nicht rückgängig machen). Bei
  Dictionary-Wörtern hingegen wird die **Karte selbst gelöscht** (und die
  manuelle Markierung, falls gesetzt) – der Eintrag verschwindet komplett,
  da eine Dictionary-Karte anders als ein Export jederzeit neu erstellt
  werden kann.

## Druck-Layouts (`--layout`)

| Layout | Beschreibung |
|---|---|
| `a6` (Default) | **Eine Karte pro A6-Seite** (quer). Zum **direkten Bedrucken von A6-Karten** – kein Schneiden. |
| `a4-4up` | 4 Karten pro **A4-Blatt** (quer). Nur die mittige Kreuzlinie wird geschnitten → 4 Karten. |

Weitere Eigenschaften:

- **Optionales Stanzloch** (Default **aus**; `--hole` bzw. Toggle im Web): oben
  links auf der Vorderseite, mit dezenter Loch-Markierung zum Aufhängen an einem
  Ring. Der Bereich ist auf der Rückseite spiegelbildlich reserviert, sodass ein
  einziges Loch durch beide Seiten passt.
- Beim `a4-4up`-Layout wird die mittige Kreuzlinie als einzige Schnittkante
  gedruckt (abschaltbar mit `--no-cut-marks`).
- Jedes Layout funktioniert mit allen Kartentypen – mit `--layout a6` lässt sich
  jede Karte einzeln **ohne Schneiden** direkt auf A6-Karten drucken.
- Die Rückseite wird für den Duplexdruck automatisch gespiegelt, sodass
  Vorder- und Rückseite exakt zusammenpassen.

## Vorschau

**Kanji (A4, 4 Karten/Seite):**

| Vorderseite (mit Tags) | Rückseite |
|---|---|
| ![Vorderseite](previews/sample_page1_front.png) | ![Rückseite](previews/sample_page2_back.png) |

**Rekursive Komposition** (Vokabel 一人 → Kanji 一, 人 → Radicals):

| Vorderseite | Rückseite |
|---|---|
| ![Komposition vorne](previews/composition_front.png) | ![Komposition hinten](previews/composition_back.png) |

Mehrere Vokabeln nacheinander gesucht und angeklickt – die Kompositionen hängen
sich an dieselbe Tabelle an (hier 一人 + 大きい, 8 Karten kombiniert):

![Web-Frontend: Komposition anhängen](previews/webui_compose_append.png)

**Aus Text:** Wort anklicken → Popup mit Bedeutung, „Zur Tabelle" oder „Als
bekannt markieren":

![Web-Frontend: Wort-Popup im Text-Modus](previews/webui_text_popup.png)

**Radicals** und **A6 (eine Karte/Seite)**:

| Radical (hinten) | A6-Karte (hinten) |
|---|---|
| ![Radicals hinten](previews/radicals_back.png) | ![A6 Rückseite](previews/a6_back.png) |

**Frei erstellte Karte** (freier Inhalt, Tags vorne):

| Vorderseite | Rückseite |
|---|---|
| ![Frei vorne](previews/custom_front.png) | ![Frei hinten](previews/custom_back.png) |

Fertige PDFs: [`sample_level1.pdf`](previews/sample_level1.pdf) ·
[`sample_composition.pdf`](previews/sample_composition.pdf) ·
[`sample_radicals.pdf`](previews/sample_radicals.pdf) ·
[`sample_a6.pdf`](previews/sample_a6.pdf).

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
python kanji_cards.py --sample                    # A4, Kanji (Level 1)
python kanji_cards.py --sample --type radicals    # Radicals statt Kanji
python kanji_cards.py --sample --layout a6        # A6, eine Karte pro Seite
```

### Optionen

| Option | Default | Beschreibung |
|---|---|---|
| `level` | – | WaniKani-Level (1–60) |
| `--output`, `-o` | `cards.pdf` | Ausgabedatei |
| `--type {kanji,radicals}` | `kanji` | Welcher Stapel exportiert wird |
| `--layout {a4-4up,a6}` | `a4-4up` | Druck-Layout (A4 4-fach mit Schnitt / A6 pro Karte) |
| `--duplex {long-edge,short-edge}` | `long-edge` | Wende-Kante für den Duplexdruck |
| `--paper {a4,letter}` | `a4` | Papierformat (nur für `a4-4up`) |
| `--font PFAD` | `fonts/NotoSerifJP-SemiBold.ttf` | Schrift für das große Kanji |
| `--no-cache` | – | API-Cache unter `.cache/` umgehen |
| `--no-cut-marks` | – | Kreuz-Schnittlinien weglassen |
| `--hole` | – | Stanzloch-Bereich reservieren (Default: aus) |
| `--no-cover` | – | keine Deckkarte voranstellen (CLI-only) |
| `--sample` | – | Beispieldaten ohne API-Token verwenden |
| `--anki` | – | Anki-Paket (`.apkg`) statt PDF erzeugen, siehe [Anki-Export](#anki-export) |

> Hinweis: Die **Deckkarte** gibt es nur noch im CLI (Default an, `--no-cover`
> zum Abschalten). Das Web-Frontend erzeugt bewusst **keine** Deckkarte.

## Drucken

Allgemein: PDF mit **beidseitigem Druck (Duplex)** und **Querformat** öffnen,
Wende-Option passend zu `--duplex` wählen (`long-edge` = lange Kante, Standard;
sonst `short-edge`) und **„Tatsächliche Größe“ / „100 %“** wählen (nicht „An
Seite anpassen“), damit die Geometrie exakt bleibt.

**Layout `a4-4up` (schneiden):**

1. Auf A4 drucken.
2. Jedes Blatt **einmal waagerecht und einmal senkrecht mittig** entlang der
   gestrichelten Kreuzlinie schneiden → 4 Karten.
3. Oben links (Vorderseite) an der Kreis-Markierung lochen und auf einen Ring
   ziehen.

**Layout `a6` (kein Schneiden):**

1. Im Druckdialog als Papierformat **A6** wählen und die A6-Karten einlegen.
2. Duplex drucken – jede Karte belegt genau eine A6-Seite, Vorder- und
   Rückseite liegen exakt übereinander.
3. Oben links (Vorderseite) an der Kreis-Markierung lochen und auf einen Ring
   ziehen.

Tipp: Vor dem Serienlauf eine Karte testen und Vorder-/Rückseite gegen das
Licht halten, um die Ausrichtung der Wende-Kante zu prüfen. Passt es nicht,
`--duplex short-edge` versuchen.

## Anki-Export

Zusätzlich zum PDF lässt sich derselbe Kartenstapel als **Anki-Paket (`.apkg`)**
exportieren – für alle drei Kartentypen (Radical/Kanji/Vokabel), für frei
erstellte Karten sowie für [Dictionary-Karten](#dictionary-karten), jeweils
mit einem eigenen, an die gedruckten Karten angelehnten Anki-Notiztyp
(Tag-Chips, On/Kun/Composition-Farben, Mnemonic-Box, Referenz-Zeichen auf der
Rückseite). Alle vier Kartentypen lassen sich in **einem** gemeinsamen Export
kombinieren (z. B. Text-Modus: WaniKani-Vokabel + Dictionary-Wort zusammen
ausgewählt).

**Anki läuft lokal, dieses Tool im Container – die beiden müssen dafür nicht
verbunden sein:** Der Export passiert komplett offline mit
[`genanki`](https://github.com/kerrickstaley/genanki) (reines Python, baut die
`.apkg`-Datei direkt als SQLite+Medien-Zip). Die Datei wird wie die PDF über
den Browser heruntergeladen und in Anki ganz normal importiert
(**Datei → Importieren**) – keine Netzwerkverbindung zwischen Container und
lokalem Anki, kein AnkiConnect nötig.

```bash
python kanji_cards.py 5 --anki -o level5.apkg
python kanji_cards.py --sample --anki              # Demo, cards.apkg
```

Im Web-Frontend: bei **Format** auf **„Anki · .apkg“** umschalten (ersetzt die
druckspezifischen Optionen) und wie gewohnt **erzeugen**.

![Web-Frontend: Anki-Export](previews/webui_anki.png)

Jeder Kartentyp bekommt einen eigenen Anki-Notiztyp im Look der gedruckten
Karten – inklusive eines farbigen Streifens oben an der Karte (Radical =
Türkis, Kanji = Ocker, Vokabel = Violett, Dictionary = Blau), damit man in
gemischten Lernsitzungen auf einen Blick sieht, welcher Kartentyp gerade dran
ist. Freie Karten bleiben ohne Akzent.

**Feste Deck-Struktur in Anki:** Jeder Export landet unabhängig vom
Job-Titel immer in derselben Ablage, damit sich Karten aus verschiedenen
Exporten wiederfinden statt in immer neuen, einzeln benannten Decks zu
zersplittern:

```
Japanisch
├── WaniKani
│   ├── Level 1
│   ├── Level 2
│   └── …
└── sonstige       (Frei- und Dictionary-Karten, kein WaniKani-Level)
```

Radical-/Kanji-/Vokabel-Karten tragen ihr WaniKani-Level (`Card.level` /
`RadicalCard.level` / `VocabCard.level`) und landen automatisch in
`Japanisch::WaniKani::Level N`; alles ohne Level (freie und Dictionary-
Karten) in `Japanisch::sonstige`. Ein `.apkg` kann mehrere Anki-Decks
enthalten – wiederholte Exporte aktualisieren dieselben Decks (stabile
Deck-IDs aus dem Namen abgeleitet, wie bei den Notizen) statt neue
anzulegen.

**Japanische Eingabe ohne Tastatur-Wechsel:** Die Eintippen-Felder für
On'yomi/Kun'yomi (Kanji-Karten) nutzen [WanaKana](https://github.com/WaniKani/WanaKana)
(`vendor/wanakana.min.js`, im `.apkg` eingebettet) – Romaji wird automatisch
in Hiragana umgewandelt, Großschreibung (Shift) ergibt Katakana. Kein Wechsel
zwischen deutscher/japanischer Tastatur nötig, um auf einer deutschen Tastatur
Kana einzutippen.

| | Vorderseite | Rückseite |
|---|---|---|
| **Kanji** | ![Kanji vorne](previews/anki_kanji_front.png) | ![Kanji hinten](previews/anki_kanji_back.png) |
| **Radical** | ![Radical vorne](previews/anki_radical_char_front.png) | ![Radical hinten](previews/anki_radical_char_back.png) |
| **Radical (nur Bild)** | ![Radical-Bild vorne](previews/anki_radical_image_front.png) | ![Radical-Bild hinten](previews/anki_radical_image_back.png) |
| **Vokabel** | ![Vokabel vorne](previews/anki_vocab_front.png) | ![Vokabel hinten](previews/anki_vocab_back.png) |
| **Frei erstellt** | ![Frei vorne](previews/anki_custom_front.png) | ![Frei hinten](previews/anki_custom_back.png) |

**Antwort eintippen:** Radical-, Kanji- und Vokabel-Karten fragen auf der
Vorderseite aktiv die **Bedeutung** ab (Ankis natives `{{type:Field}}`) – Anki
zeigt beim Aufdecken einen farbigen Vergleich zwischen Eingabe und korrekter
Antwort. Freie Karten haben keine feste „richtige Antwort" und bleiben reine
Aufdeck-Karten.

**Kanji: On'yomi und Kun'yomi getrennt abfragen.** Ein Kanji-Subject wird zu
**bis zu drei Anki-Karten**: „Meaning", „On'yomi", „Kun'yomi" – jede mit
eigenem Eintippen-Prompt, alle mit derselben ausführlichen Rückseite. Fehlt
eine Lesungsart (z. B. kein Kun'yomi), erzeugt Anki für dieses Kanji
automatisch keine leere Karte dafür.

| „On'yomi"-Karte | „Kun'yomi"-Karte |
|---|---|
| ![On'yomi eingeben](previews/anki_kanji_onyomi_front.png) | ![Kun'yomi eingeben](previews/anki_kanji_kunyomi_front.png) |

Die WaniKani-Subject-ID (bzw. bei freien Karten deren gespeicherte ID) wird als
stabile Anki-Notiz-ID verwendet: ein erneuter Export nach Lernfortschritt
**aktualisiert** bestehende Notizen in Anki, statt sie zu duplizieren. Die
Noto-JP-Schriften sind im `.apkg` eingebettet, Kanji werden also auch ohne
lokal installierte japanische Schrift sauber dargestellt.

## Web-Frontend: Shiori (Docker)

**Shiori** (栞, jap. „Lesezeichen") ist das Web-Frontend (`webapp.py`, Flask)
zu diesem Projekt – gewachsen von einem reinen WaniKani-PDF-Export zu einem
Werkzeug, das WaniKani, ein deutsches Wörterbuch (JMdict) und optional
Gemini-Grammatikanalyse kombiniert: Karten über **Level-Stapel**, **Suche**
(rekursive Komposition), den **Text-Modus** oder **frei** erstellen, in einer
**Tabelle auswählen**, daraus **ein PDF oder Anki-Paket** erzeugen, dazu eine
**Wortliste** über alles, was schon bekannt ist, und ein **Verlauf** mit
Direkt-Download. Es gibt **keine Datenbank** – alles wird dateibasiert im
Ordner `data/` gespeichert:

```
data/
├── settings.json          # API-Token, DeepL-/Gemini-Key (+ zuletzt genutzte Optionen)
├── known.json             # manuell als „bekannt" markierte IDs (Text-Modus/Wortliste)
├── known_meta.json        # Anzeige-Metadaten dazu (Zeichen/Bedeutung/…), für die Wortliste
├── customcards/<id>.json  # frei erstellte Karten
├── kanacards/<id>.json    # Dictionary-Karten (Wort/Bedeutung/Beispielsatz)
├── output/<id>.pdf        # erzeugte PDFs
├── output/<id>.apkg       # erzeugte Anki-Pakete
├── jobs/<id>.json         # Job-Status/Metadaten
└── .cache/                # WaniKani-API-, JMdict- und Gemini-Cache
```

![Web-Frontend](previews/webui.png)

### Mit Docker starten (empfohlen)

```bash
docker compose up --build      # baut das Image inkl. WeasyPrint-System-Libs
# → Frontend auf http://localhost:8000
```

Der Host-Ordner `./data` ist als Volume eingehängt (`./data:/data`), sodass
Einstellungen und PDFs einen Neustart überdauern. Danach im Browser oben rechts
auf ⚙ klicken, den **WaniKani API-Token** eintragen und speichern.

### Ohne Docker (lokal)

```bash
pip install -r requirements.txt -r requirements-web.txt
python webapp.py               # http://localhost:8000  (Entwicklungsserver)
# produktiv:
gunicorn -b 0.0.0.0:8000 -w 2 --timeout 600 webapp:app
```

Der Token wird über die Oberfläche gesetzt und landet in `data/settings.json`
(nicht im Repo – `data/` ist in `.gitignore`). Alternativ funktioniert weiter
`WANIKANI_API_TOKEN` als Umgebungsvariable fürs CLI.

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

Der Anki-Export lebt in einem eigenen Modul (`anki_export.py`), das dieselben
Card-Objekte wie der PDF-Pfad wiederverwendet (`kc.resolve_subject_deck()` /
`kc.build_custom_card()`) und `genanki` nur bei tatsächlicher Nutzung importiert
(`--anki` bzw. Format „Anki“ im Web-Frontend).

Der Text-Modus (`annotate_text()`, intern via `lemmatize_text()`) nutzt
[Janome](https://github.com/mocobeta/janome) für die Lemmatisierung (reines
Python, keine System-Abhängigkeit) und zerlegt den Text zeilenweise in
Anzeige-Segmente (erkanntes Wort vs. reiner Text), die exakt zur Original-
Zeile zusammensetzbar bleiben. Ein Klick auf ein Wort im Frontend nutzt für
das „Zur Tabelle"-Hinzufügen denselben `/api/resolve`-Kompositionspfad wie der
Kompositions-Modus (`kc.resolve_composition()`, ein Subject rekursiv). „Eigener
Beispielsatz aus dem Text" wird dabei clientseitig als `sentence_overrides`
(Vokabel-Subject-ID → `{"ja", "en"}`) mitgeschickt und erst beim Rendern
angewendet (`resolve_subject_deck()` → `build_card()` / `build_vocab_card()`)
– WaniKanis eigene Beispielsätze gehen dabei nicht verloren, sie rutschen nur
eine Position nach hinten.

**Wörterbuch-Fallback** (`dictionary.py`, unabhängig von WaniKani): lädt die
deutsche Edition von [JMdict-simplified](https://github.com/scriptin/jmdict-simplified)
(`jmdict-ger-*.json.zip`, JSON, per GitHub-Releases-API immer die neueste
Version) einmalig herunter und baut einen Lesung→{Kanji, deutsche Bedeutung}-
Index, gecacht unter `.cache/jmdict/`. Für
Text-Modus-Wörter ohne Kanji UND ohne WaniKani-Treffer liefert
`dictionary.lookup_reading()` die Anzeige-Daten für den neuen, WaniKani-
unabhängigen Kartentyp `KanaCard` (`kanji_cards.build_kana_card()`) –
Vorderseite Hiragana/Katakana, Rückseite Bedeutung + optionaler, per
[DeepL-API](https://www.deepl.com/de/pro-api) übersetzter Beispielsatz
(`dictionary.translate_sentence()`, DeepL-Key aus `data/settings.json`, wie
der WaniKani-Token nie hardgecodet). `webapp._build_mixed_deck()` kombiniert
WaniKani-, freie und Dictionary-Karten in **einem** Export – die niedrig-
levelig­en `kc.render_deck()`/`ae.export_deck()`-Funktionen unterstützen
beliebig gemischte Card-Objektlisten per `isinstance`-Dispatch, das war schon
vorher so angelegt.

Jedes Wort im Text-Modus bekommt zwei rohe Signale vom Backend
(`/api/text-annotate`): `manually_known` (aus `data/known.json`) und `ready`
(WaniKani bereits exportiert bzw. Dictionary-Karte bereits erstellt) – daraus
berechnet sowohl der Server (`status`: `known`/`unknown`, für die Erstanzeige)
als auch das Frontend lokal (`applySegChange()` in `web/app.js`) denselben
Status, ohne bei jedem Umschalten („bekannt markieren"/entfernen, Dictionary-
Karte erstellen) einen kompletten Server-Roundtrip über `/api/text-annotate`
zu brauchen. Wörter ohne WaniKani-/Dictionary-Treffer, die nur über Gemini
erklärt werden (`source: "gemini"`), haben `id: null`, bekommen `status:
"info"` und fließen nicht in die Bekannt/Unbekannt-Statistik ein.

**Gemini-Analyse** (`gemini_client.py`, optional, unabhängig von WaniKani/
Dictionary): ein REST-Call pro Satz gegen `generativelanguage.googleapis.com`
(kein SDK, reines `requests` wie bei DeepL/GitHub) mit `responseSchema` für
garantiert valides JSON (Tokens mit `dictionary_form` + grammatikalischer
Funktion, `grammar_notes`, `translation_de`) statt Markdown-Tabellen-Parsing.
Ergebnisse werden pro Satz unter `.cache/gemini/` gecacht (Schlüssel: Modell +
Satztext). `annotate_text()` ersetzt eine Janome-Satzgruppe nur durch Gemini,
wenn dessen Tokens **exakt** zum Original-Text rekonstruieren – sonst (kein
Key, Netzwerkfehler, Quota, kaputte/abweichende Antwort) bleibt die
Janome-Tokenisierung für genau diesen Satz unverändert (nie ein harter
Abbruch für den gesamten Text). `dictionary_form` ersetzt dabei Janomes
`base_form` als Schlüssel für den WaniKani-/JMdict-Abgleich.

Die **Wortliste** (`/api/wortliste`) vereinigt drei Quellen zu einer Anzeige-
Liste: bereits exportierte/manuell markierte WaniKani-Subjects (Anzeige-Daten
über das neue, nicht-rekursive `kc.resolve_subject_ids()` aufgelöst – anders
als `resolve_composition()` steigt es **nicht** in die Komposition ab, da die
Wortliste die Wörter selbst zeigen soll, nicht ihre Bestandteile), erstellte
Dictionary-Karten sowie rein manuelle Einträge ohne jede Karte/Subject
(`manual_<hash>`-IDs, Anzeige-Daten aus `data/known_meta.json`, da es dafür
keine andere Quelle gibt).

## Tests

```bash
pip install pytest
pytest
```

Abgedeckt sind die Kernfunktionen `pick_example_vocab`, `mirror_backside`,
`paginate`, `build_card`, `strip_markup`, `lemmatize_text`/`annotate_text`
(Text-Modus, inkl. Wörterbuch- und Gemini-Fallback), `dictionary.py`
(JMdict-Download/-Index, DeepL-Übersetzung), `gemini_client.py`
(Satzanalyse, Caching, 429-Backoff, Fehlerfälle), `KanaCard`-Bau sowie das
Auflösen bereits exportierter bzw. manuell als bekannt markierter Subject-/
Dictionary-IDs, die Wortlisten-Aggregation und die Anki-Notiztypen im
Web-Frontend (`webapp._already_exported_ids`, `webapp.load_known`/
`save_known`, `webapp.api_wortliste`, `anki_export._kana_note`).

Die Test-Suite selbst läuft gemockt (kein Netzwerkzugriff nötig, `pytest`
ist offline lauffähig). Live gegen echte Endpunkte verifiziert wurden
zusätzlich: WaniKani-API (Subjects, Text-Modus end-to-end inkl. Anki-Export)
und DeepL (`translate_sentence`, mit `:fx`-Free-Key gegen
`api-free.deepl.com`) – beide funktionieren wie erwartet. Der JMdict-Download
selbst (`dictionary.download_jmdict()` gegen die echte GitHub-Releases-API
von `scriptin/jmdict-simplified`) konnte in der Entwicklungsumgebung aus
Netzwerk-Policy-Gründen noch nicht live getestet werden; der übrige
Dictionary-Pfad (Index-Aufbau, Kartenerstellung, Anki-Export) wurde mit
einem simulierten Index-Eintrag live durchgespielt und funktioniert. Der
Gemini-Fallback auf Janome wurde live gegen die echte
`generativelanguage.googleapis.com`-API verifiziert (mit ungültigem Key:
Request schlägt fehl, `annotate_text()` liefert unverändert das
Janome-Ergebnis) – ein echter Gemini-Key lag in dieser Session nicht vor,
die Analyse-Qualität selbst ist daher nur gegen Mocks getestet.
