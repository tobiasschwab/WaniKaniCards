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
   (Artikel, Kapitel, Dialog …) – **eine** gemeinsame Eingabe für zwei
   Analyse-Arten (Segmented-Schalter über dem „Analysieren"-Button), damit
   man denselben Text nicht zweimal einfügen muss:

   **„Schnell (kostenlos)"** – der Text wird **lemmatisiert**
   ([Janome](https://github.com/mocobeta/janome), reines Python – jedes Wort
   auf seine Wörterbuch-Grundform zurückgeführt, z. B. „大きく" → „大きい") und
   gegen WaniKani abgeglichen. Anschließend erscheint der Text
   **schreibgeschützt**, mit jedem erkannten Wort **anklickbar** und farblich
   markiert: <br>
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

   Details (Quelle WaniKani/Wörterbuch, ob manuell markiert oder weil eine
   Karte existiert) zeigt das Popup beim Anklicken des Worts. Für
   Dictionary-Wörter erzeugt das Popup statt „Zur Tabelle" den Button
   **„Dictionary-Karte erstellen"** – ein neuer, WaniKani-unabhängiger
   Kartentyp (siehe [Dictionary-Karten](#dictionary-karten)). Dieser
   Analyse-Weg nutzt **kein** Gemini – ohne API-Key, ohne Kosten.

   **„✨ Mit KI (Übersetzung, Grammatik)"** – derselbe Text, aber satzweise per
   [Gemini-API](https://ai.google.dev/) analysiert (Key + Modell in den
   Einstellungen hinterlegen – die Modell-Liste lässt sich dort per 🔄 live
   von Google abrufen) statt nur lemmatisiert. Ergebnis ist eine Tabelle mit
   einer Zeile pro Satz:

   | Spalte | Inhalt |
   |---|---|
   | Japanisch | der Satz im Original, unverändert |
   | Bekannt | Prozentsatz bekannter Vokabeln des Satzes, als Badge grün (100 %) bis rot (0 %) eingefärbt |
   | Deutsch | natürliche deutsche Übersetzung des Satzes |
   | Vokabeln | die Vokabeln des Satzes in der **Grundform** (Wörterbuchform), einzeln anklickbar |
   | Bemerkung | kurze Grammatik-Erklärung (Besonderheiten, Redewendungen o. Ä.) |

   Deutsch/Vokabeln/Bemerkung sind zum Selbsttest zunächst **verschwommen** –
   einzelne Zelle anklicken deckt nur sie auf, „🙈 Verschwommen"/„👁 Sichtbar"
   oben schaltet alle auf einmal um. Beim **Hovern** über eine Vokabel wird
   die zugehörige Stelle im Original-Satz mit hervorgehoben (und umgekehrt) –
   rein optisch, der Satz selbst bleibt unangetastet. Eine aufgedeckte Vokabel
   anklicken öffnet dasselbe Wort-Popup wie beim „Schnell"-Weg: 家 (in
   WaniKani vorhanden) oder 入りました → Grundform 入る (ebenfalls in
   WaniKani) lassen sich direkt **„Über WaniKani hinzufügen"**. Kennt weder
   WaniKani noch das JMdict-Wörterbuch die Grundform, bietet das Popup
   stattdessen **„KI-Karte erstellen"** an – die kurze deutsche Bedeutung
   stammt dann direkt von Gemini statt aus dem Wörterbuch (siehe
   [Dictionary-Karten](#dictionary-karten), gleiche Karten-Infrastruktur, nur
   mit `Quelle: KI (Gemini)` statt `Quelle: JMdict`). Es wird **nie
   automatisch** für alle Wörter eine Karte erzeugt – nur ein bewusster Klick
   legt eine an. Scheitert die Analyse für einen einzelnen Satz (Netzwerk,
   Quota, Wortgrenzen passen nicht exakt zum Original), bekommt nur dieser
   Satz eine Fehlermeldung statt den ganzen Text abzubrechen – **„🔄 Erneut
   versuchen"** fragt dann nur diesen einen Satz erneut an, statt den ganzen
   Text neu zu analysieren.

   **🔤 Neue Vokabeln in diesem Text (nach Häufigkeit):** eine kompakte,
   deduplizierte Liste aller noch unbekannten Vokabeln über den gesamten
   Text hinweg, sortiert nach Vorkommenshäufigkeit (ein Wort, das 5× auftaucht,
   lohnt sich eher zu lernen als eins, das nur einmal vorkommt) – standardmäßig
   nur die Top 10, „Alle N anzeigen" klappt den Rest auf. Wort anklicken öffnet
   dasselbe Wort-Popup wie in der Vokabeln-Spalte der Tabelle. **„+ Alle
   unbekannten hinzufügen"** übernimmt stattdessen alle unbekannten Vokabeln
   des Textes auf einen Klick in die Karten-Tabelle (WaniKani-Treffer
   gebündelt in einem Abgleich, Dictionary-/KI-Wörter nacheinander) – bleibt
   ein bewusster Klick, spart aber bei langen Texten das einzelne Anklicken
   jedes Worts.

   **🔊 Original-Satz vorlesen:** ein Lautsprecher-Symbol neben jedem Satz
   ruft Gemini's eigene Sprachausgabe auf (`gemini_client.synthesize_speech()`,
   Modell `gemini-2.5-flash-preview-tts`) – nutzt denselben Gemini-Key wie die
   Satzanalyse, kein zusätzlicher Google-Cloud-TTS-Zugang nötig. Wird eine
   Karte aus der Vokabeln-Spalte erstellt (WaniKani oder KI-Karte), landet
   dieselbe Audiodatei automatisch mit auf der Karte (als eingebettetes
   `<audio>`-Element, wie das bestehende WaniKani-Audio). Pro Satz wird nur
   einmal angefragt (client- **und** serverseitig unter `.cache/gemini_tts/`
   gecacht) – erneutes Abspielen oder ein späteres Karte-Erstellen für
   denselben Satz braucht keinen zweiten Request. Aktuell nur beim „Mit
   KI"-Weg verfügbar. **„▶ Alle vorlesen"** spielt alle Sätze nacheinander ab
   (überspringt fehlgeschlagene Zeilen, Button wird währenddessen zum
   Stopp-Schalter); das **Tempo**-Dropdown (0,75×–1,5×) gilt für Einzel- und
   Sammel-Wiedergabe gleichermaßen.

   **Persistenz:** Das zuletzt per „Mit KI" analysierte Ergebnis (Text +
   Tabelle) wird im Browser gemerkt (`localStorage`) – ein versehentlicher
   Reload wirft die Analyse nicht weg und kostet keine erneute Gemini-Anfrage.
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
  Dictionary-/KI-Wörtern hingegen wird die **Karte selbst gelöscht** (und die
  manuelle Markierung, falls gesetzt) – der Eintrag verschwindet komplett,
  da eine solche Karte anders als ein Export jederzeit neu erstellt werden
  kann.
- **📄 Kontext:** Dictionary- und KI-Wörter tragen den Original-Satz, aus dem
  sie stammen (`KanaCard.sentence_ja`/`sentence_translation`/
  `sentence_audio_url`) – ein Klick auf das 📄-Symbol zeigt Satz, Übersetzung
  und (falls vorhanden) die vorgelesene Audio in einem Popup. Für
  WaniKani-Wörter (noch) nicht verfügbar, da dort kein eigener Satz-Kontext
  mitgespeichert wird.

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
On'yomi/Kun'yomi (Kanji-Karten) und die Lesung (Vokabel-Karten) nutzen
[WanaKana](https://github.com/WaniKani/WanaKana) (`vendor/wanakana.min.js`,
im `.apkg` eingebettet) – Romaji wird automatisch in Hiragana umgewandelt,
Großschreibung (Shift) ergibt Katakana. Kein Wechsel zwischen deutscher/
japanischer Tastatur nötig, um auf einer deutschen Tastatur Kana einzutippen.

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

**Vokabel: Bedeutung und Lesung getrennt abfragen.** Analog zu Kanji wird
ein Vokabel-Subject zu **zwei Anki-Karten**: „Bedeutung" (wie bisher) und
„Lesung" (neu, mit WanaKana-Eingabe, s. o.) – beide teilen sich dieselbe
Rückseite. Hat eine Vokabel ausnahmsweise keine gespeicherte Lesung, erzeugt
Anki dafür automatisch keine leere „Lesung"-Karte (gleiches
`{{#Feld}}…{{/Feld}}`-Gating wie bei On'yomi/Kun'yomi).

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
Version) einmalig herunter und baut einen Lesung→{Kanji, Bedeutung,
Zusatzerklärung}-Index, gecacht unter `.cache/jmdict/`. Die deutsche Edition
packt Nutzungshinweise oft direkt in Klammern hinter die erste Glosse (z. B.
„ich (vertraulich im Ton; Männersprache; …)" für 僕/ぼく) – `meaning` ist
deshalb bewusst nur die kurze Kernbedeutung vor der Klammer, alles Weitere
(die Klammer-Erklärung plus etwaige zusätzliche Glossen derselben Sense)
landet in `meaning_extra` und wird auf Karte/Popup/Wortliste kleiner und
gedämpft angezeigt statt in einem langen Satz verkettet. Für
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

Jedes Wort in beiden Text-Modi bekommt zwei rohe Signale vom Backend
(`/api/text-annotate` bzw. `/api/text-annotate-ai`): `manually_known` (aus
`data/known.json`) und `ready` (WaniKani bereits exportiert bzw. Dictionary-/
KI-Karte bereits erstellt) – daraus berechnet sowohl der Server (`status`:
`known`/`unknown`, für die Erstanzeige) als auch das Frontend lokal
(`applySegChange()` in `web/app.js`) denselben Status, ohne bei jedem
Umschalten einen kompletten Server-Roundtrip zu brauchen.

**Zwei getrennte Text-Endpunkte statt einem gemeinsamen mit Gemini-Schalter:**
`kc.annotate_text()` ist reine Janome+WaniKani/JMdict-Lemmatisierung, ganz
ohne Gemini (Modus „Aus Text"). `kc.annotate_text_ai()` ist ein eigenständiger
KI-Modus: er zerlegt den Text in Sätze, lässt **jeden** Satz per Gemini
analysieren (siehe unten) und liefert pro Satz eine Zeile `{"sentence",
"translation_de", "grammar_notes", "error", "segments"}` – Grundlage für die
Satz-Tabelle im Frontend (Spalten Japanisch/Bekannt/Deutsch/Vokabeln/
Bemerkung). Anders als im alten, inzwischen entfernten kombinierten Modus gibt
es hier **keinen** Fallback auf Janome: Scheitert Gemini für einen Satz
(Netzwerk/Quota) oder passen die gelieferten Tokens nicht exakt zum
Original-Satz, bekommt nur diese eine Zeile ein `"error"` statt Segmenten –
kein harter Abbruch für den restlichen Text. Wörter ohne WaniKani-/JMdict-
Treffer, für die Gemini selbst Grundform + Lesung + kurze Bedeutung liefert,
bekommen `source: "ai"` und eine stabile ID (`kc.ai_kana_card_id()`) – eine
echte Karte entsteht daraus aber erst, wenn der Nutzer im Wort-Popup bewusst
auf „KI-Karte erstellen" klickt (siehe [Dictionary-Karten](#dictionary-karten)
– `KanaCard` bekam dafür die neuen Felder `reading`/`source`, `source: "ai"`
zeigt auf der Karte „Quelle: KI (Gemini)" statt „Quelle: JMdict (EDRDG)").

**Gemini-Analyse** (`gemini_client.py`): ein REST-Call gegen
`generativelanguage.googleapis.com` (kein SDK, reines `requests` wie bei
DeepL/GitHub) mit `responseSchema` für garantiert valides JSON (Tokens mit
`dictionary_form`, `reading`, grammatikalischer `function`, kurzer `meaning`)
statt Markdown-Tabellen-Parsing. Ergebnisse werden pro Satz unter
`.cache/gemini/` gecacht (Schlüssel: Modell + Satztext).
`_reconcile_gemini_tokens()` prüft, ob Geminis Tokens zum Original-Satz
rekonstruieren – dabei bewusst **nicht** strikt zeichengleich: Gemini lässt
das abschließende Satzzeichen (｡ 。 ! ?) trotz expliziter Prompt-Anweisung
regelmäßig weg, eine rein strikte Prüfung hätte praktisch jeden normalen (auf
。 endenden) Satz verworfen. Die Funktion ergänzt einen fehlenden reinen
Satzzeichen-Rest am Ende als eigenes Token und ist generisch für Tupel
beliebiger Breite (3er-Tupel im alten Aus-Text-Kontext gibt es nicht mehr,
der KI-Modus nutzt 5er-Tupel `(surface, lemma, reading, function, meaning)`).

**Batch-Verarbeitung statt eines Requests pro Satz**: `analyze_sentences()`
ist die zentrale Funktion – sie sammelt alle eindeutigen Sätze eines Textes,
prüft zuerst den Satz-Cache (`.cache/gemini/`) und schickt nur die noch
ungecachten Sätze in Blöcken von `_BATCH_CHUNK_SIZE` (40) als **ein**
Request an Gemini (`{"sentences": [...]}` rein, `{"sentences": [{sentence,
tokens, grammar_notes, translation_de}, …]}` raus, per `responseSchema`
erzwungen). `analyze_sentence()` (Singular) ist nur noch ein dünner Wrapper
darüber. Das vermeidet bei Texten mit vielen Sätzen die Rate-Limit-Kaskade
eines Requests pro Satz strukturell (siehe 429-Handling unten), nicht nur
durch besseres Backoff. Fehlt eine Übersetzung in Gemini's Antwort (Satz
nicht wiedererkannt, Antwort unvollständig), bekommt nur diese eine Satz-Zeile
einen Fehler statt den ganzen Batch scheitern zu lassen.

**Modellwahl**: `list_models()` fragt die verfügbaren Modelle live per
`GET /v1beta/models` ab (gefiltert auf Text-Chat-fähige `gemini-*`-Modelle),
statt eine feste Liste im Code zu pflegen – Google fügt laufend neue Modelle
hinzu und deprecatet alte für neue Projekte/Keys ("model X is no longer
available to new users"). Der Endpunkt `POST /api/gemini/models` liefert
diese Liste ans Frontend (🔄-Button neben der Modell-Auswahl in den
Einstellungen); `AVAILABLE_MODELS`/`DEFAULT_MODEL` (`-latest`-Aliase wie
`gemini-flash-latest`) dienen nur noch als Fallback-Vorauswahl, falls noch
keine Liste abgerufen wurde oder der Abruf fehlschlägt. `pro`-Modelle haben
auf dem kostenlosen Tier meist **kein** Kontingent (HTTP 429 "quota
exceeded", `limit: 0`) und brauchen ein Konto mit aktivierter Abrechnung.
Jeder in `settings.json` gespeicherte Modellname, der mit `gemini-`
beginnt, wird vertrauensvoll durchgereicht (auch wenn er nicht in der
kleinen Fallback-Liste steht) – nur ein wirklich ungültiger Wert fällt auf
den Default zurück.

Jeder Gemini-Request nutzt ein (Connect-, Read-)Timeout statt eines
einzelnen 30s-Werts, damit eine tote Verbindung (z. B. Netzwerk-Policy im
Docker-Deployment) nicht unbegrenzt hängt. Für Satz-Batches skaliert der
Read-Timeout mit der Satzanzahl (`_batch_read_timeout()`: 60s + 8s pro Satz,
gedeckelt auf 280s) statt eines fixen 60s-Werts – live beobachtet hat schon
ein einzelner Satz ~46s gebraucht und ein 19er-Batch ist am fixen 60s-Limit
gescheitert (`ReadTimeout`), ein pauschaler Wert unabhängig von der
Satzanzahl war schlicht zu knapp. Ein einzelner `ReadTimeout`/Netzwerkfehler
wird zusätzlich einmal wiederholt (nicht wie 429/5xx bis zu 5×, da hier jeder
Versuch selbst schon lange dauern kann) – ein zweiter Versuch schlägt bei
Gemini oft durch. Bei HTTP 429 wird die von Google selbst empfohlene
Wartezeit (`Retry-After`-Header bzw. `RetryInfo.retryDelay` in der
Fehlerantwort) befolgt statt eines geratenen Backoffs – ein Rate-Limit-
Fenster läuft oft über ~60s, ein Backoff, der nach 8s aufgibt, schlägt in
der Zeit einfach mehrfach erfolglos fehl, statt einmal lange genug zu
warten. Insgesamt darf ein einzelner Batch höchstens ~70s auf
Rate-Limit-Erholung warten, danach bekommt genau dieser Satz/Batch einen
Fehler statt endlos zu blockieren (gunicorn selbst läuft mit
`--timeout 600`, damit ein langer Batch nicht vom Worker-Timeout
abgeschossen wird, bevor der Gemini-Timeout überhaupt greift). Start, Dauer
und Fehlerursache jeder Gemini-Anfrage werden per `logging` protokolliert
(INFO/WARNING, sichtbar über `docker logs`) – vorher war ein hängender oder
an Rate-Limits scheiternder Request von außen nicht zu unterscheiden.

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
(Aus-Text-Modus, inkl. Wörterbuch-Fallback) sowie `annotate_text_ai` (KI-Modus,
Satz-Tabelle inkl. Fehlerfälle), `dictionary.py`
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
Gemini-Fehlerpfad wurde live gegen die echte
`generativelanguage.googleapis.com`-API verifiziert (mit ungültigem Key:
Request schlägt fehl, betroffene Satz-Zeile bekommt `error` statt Segmenten).
In einer späteren Session wurde mit einem echten, vom Nutzer bereitgestellten
Gemini-Key auch der Erfolgsfall live getestet – dabei wurden zwei reale Bugs
gefunden und behoben (deprecatete Modellnamen, siehe `DEFAULT_MODEL`; sowie
die Tokens-Rekonstruktion, siehe `_reconcile_gemini_tokens()`).
