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

   **📄 PDF/Bild hochladen:** statt Copy-Paste lässt sich über den Button
   über der Textbox direkt eine **PDF-Datei oder ein Bild** hochladen (z. B.
   ein Foto einer Buchseite oder ein Scan) – der extrahierte Text landet in
   derselben Textarea und läuft danach exakt wie manuell eingefügter Text
   durch „Schnell" oder „Mit KI". Zweistufig statt „alles auf einmal": PDF-Seiten
   mit **Textlayer** werden direkt und kostenlos ausgelesen ([PyMuPDF](https://pymupdf.readthedocs.io/),
   keine System-Abhängigkeit wie poppler-utils). Nur Seiten **ohne** Textlayer
   (Scans) sowie direkt hochgeladene Bilder werden per **Gemini-Vision**
   transkribiert – dafür ist ein Gemini-Key in den Einstellungen nötig, reine
   Textlayer-PDFs funktionieren auch ganz ohne Key. Grenzen: max. 20 MB pro
   Datei, max. 30 Seiten pro PDF (danach werden nur die ersten 30 verarbeitet);
   schlägt die Texterkennung für einzelne Seiten fehl, werden nur diese
   übersprungen statt das ganze Dokument abzubrechen.

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

   **🔤 Vokabeln in diesem Text (nach Häufigkeit):** eine kompakte,
   deduplizierte Liste **aller** Vokabeln über den gesamten Text hinweg
   (bekannt und unbekannt), sortiert nach Vorkommenshäufigkeit (ein Wort,
   das 5× auftaucht, lohnt sich eher zu lernen als eins, das nur einmal
   vorkommt) – standardmäßig nur die Top 10, „Alle N anzeigen" klappt den
   Rest auf. Grün/Blau zeigt sofort, welche der häufigsten Wörter schon
   bekannt sind und welche noch fehlen. Wort anklicken öffnet dasselbe
   Wort-Popup wie in der Vokabeln-Spalte der Tabelle. **„+ Alle unbekannten
   hinzufügen"** übernimmt stattdessen alle unbekannten Vokabeln des Textes
   auf einen Klick in die Karten-Tabelle (WaniKani-Treffer gebündelt in
   einem Abgleich, Dictionary-/KI-Wörter nacheinander) – bleibt ein
   bewusster Klick, spart aber bei langen Texten das einzelne Anklicken
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

**Felder manuell anpassen (✎ pro Zeile):** WaniKani-Kanji/Vokabeln/Radicals in
der Tabelle lassen sich vor dem Export **einzeln bearbeiten** – „✎" öffnet ein
Pop-up mit allen Karten-Feldern (Bedeutungen, On'yomi/Kun'yomi bzw. Lesungen,
Beispielvokabel/-satz, Merkhilfen, je nach Kartentyp), jedes Feld einzeln als
Text-/Mehrzeilenfeld editierbar, „↺" setzt ein einzelnes Feld auf den
WaniKani-Original­wert zurück. Bearbeitete Zeilen bekommen ein „✎ angepasst"-
Badge in der Tabelle; die Änderungen wirken erst beim tatsächlichen Erzeugen
der Karten (PDF/Anki) und bleiben bis „Tabelle leeren" erhalten – die
WaniKani-Originaldaten selbst werden nie verändert, nur das jeweils
exportierte Kartenfeld.

**🌐 Übersetzen:** Für alle textlichen (englischen) Felder – Bedeutungen,
Merkhilfen, Beispielvokabel-Bedeutung, Beispielsatz-Übersetzung – übersetzt
ein „🌐 Übersetzen"-Button den aktuellen Feldinhalt per DeepL in die in den
Einstellungen hinterlegte **Zielsprache** (Default Deutsch, unter
DeepL → „Zielsprache" umstellbar). Die Übersetzung wird dem Original dabei
**vorangestellt statt es zu überschreiben** (`Übersetzung\n—\nOriginal`) –
so bleibt der WaniKani-Originaltext zur Kontrolle sichtbar und lässt sich bei
Bedarf weiter von Hand anpassen, statt blind einer maschinellen Übersetzung zu
vertrauen. Braucht einen DeepL-Key in den Einstellungen (derselbe, der auch
für Beispielsatz-Übersetzungen auf Dictionary-Karten genutzt wird).

**🖼 Bildkarten (nur für Vokabeln):** Für Vokabeln, die sich gut bildlich
darstellen lassen (z. B. 家/„Haus"), lässt sich statt der üblichen Text-
Vorderseite ein einfaches **Clipart-Bild** generieren – „🖼"-Button pro
Vokabel-Zeile öffnet einen Dialog mit „Generieren" (per Gemini, kein Text/
Kanji im Bild selbst), Vorschau, „Neu generieren" (Bildgenerierung ist nicht
deterministisch, jeder Klick liefert ein neues Ergebnis) und „Übernehmen".
Manche Begriffe sind als reines Bild mehrdeutig – die Checkbox „Bedeutung
zusätzlich auf der Vorderseite anzeigen" druckt die Bedeutung klein mit
darunter. Übernommene Zeilen bekommen ein „🖼 Bildkarte"-Badge; wie bei
„Felder manuell anpassen" wirkt die Änderung erst beim Erzeugen der Karten
und lässt sich über „Bild entfernen" wieder rückgängig machen. **Rückseite
bleibt unverändert** (Lesungen, Bedeutungen, Beispielsatz wie bei jeder
anderen Vokabelkarte). Im **Anki-Export** entsteht für Bildkarten statt der
üblichen zwei Karten (Bedeutung/Lesung) nur **eine**: Bild + Wort vorne,
Lesung eintippen (per WanaKana, kein IME-Umschalten nötig) – die Bedeutung
separat abzufragen wäre redundant, wenn sie ohnehin (optional) schon auf dem
Bild steht. Braucht einen Gemini-Key in den Einstellungen; bewusst **manuell
pro Karte** angestoßen statt automatisch für alle Vokabeln, da nicht jeder
Begriff sich gut als Bild darstellen lässt.

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
Direkt-Download. Jeder Nutzer hat dabei sein **eigenes** Konto (E-Mail/
Passwort) mit eigenen Einstellungen/API-Keys, eigener Wortliste, eigenen
Karten und eigenem Job-Verlauf (siehe [Multi-User-Architektur](#multi-user-architektur-umbau-in-arbeit)
unten) – Accounts/Einstellungen/Karten/Jobs liegen in einer Datenbank
(SQLite lokal, Postgres in Produktion), nur die generierten PDFs/APKGs
selbst sowie API-Caches bleiben dateibasiert unter `data/`:

```
data/
├── shiori.db          # SQLite-Fallback ohne DATABASE_URL (nur Demo/Entwicklung)
├── output/<id>.pdf    # erzeugte PDFs
├── output/<id>.apkg   # erzeugte Anki-Pakete
└── .cache/            # WaniKani-API-, JMdict- und Gemini-Cache (geteilt, nutzerunabhängig)
```

![Web-Frontend](previews/webui.png)

### Mit Docker starten (empfohlen)

> ⚠️ **Host mit nur Python 2 (z. B. QNAP/Synology-NAS)?** Die Befehle unten
> mit `python3 -c "from crypto import ..."` funktionieren dort **nicht** –
> `crypto.py` nutzt Python-3-Syntax (f-Strings, Type Hints) und das
> `cryptography`-Paket, beides gibt es unter Python 2 nicht. Das ist auch
> **keine Encoding-Frage** – ein `# -*- coding: utf-8 -*-`-Header in `crypto.py`
> würde daran nichts ändern, der `SyntaxError` kommt von der Sprachversion,
> nicht von der Zeichenkodierung. Lies stattdessen direkt weiter unten bei
> „Kein Python 3 auf dem Host?" – dort erzeugst du denselben Key ganz ohne
> `crypto.py` auszuführen, z. B. rein mit `openssl`.

```bash
export WKCARDS_SECRET_KEY=$(python3 -c "from crypto import generate_master_key; print(generate_master_key())")
export WKCARDS_SESSION_SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")
docker compose up --build      # baut das Image, startet zusätzlich einen Postgres-Service
# → Frontend auf http://localhost:9020
```

**Kein Python 3 auf dem Host?** (z. B. QNAP/Synology-NAS mit nur Python 2.7):
Ein Fernet-Master-Key ist einfach 32 Zufallsbytes, URL-safe base64-kodiert –
beide Befehle erzeugen einen gleichwertigen, gültigen Key ganz ohne Python 3
und ohne `crypto.py` je auszuführen:

```bash
# Variante A: openssl (auf praktisch jedem NAS vorhanden, empfohlen) - oder
# gleich das mitgelieferte Skript nutzen (WICHTIG: mit "source"/"." aufrufen,
# sonst geht der Key beim Skriptende als Subshell-Variable wieder verloren):
source ./create_secret.sh
echo "$WKCARDS_SECRET_KEY"   # aufschreiben/sichern - bei Verlust sind gespeicherte Keys unlesbar

# Variante B: falls kein openssl vorhanden ist, tut's auch das System-Python 2.7
export WKCARDS_SECRET_KEY=$(python -c "import os,base64; print(base64.urlsafe_b64encode(os.urandom(32)))")

# Session-Secret (beliebiger langer Zufalls-Hex-String, kein Fernet-Key nötig):
export WKCARDS_SESSION_SECRET=$(openssl rand -hex 32)
```

> ⚠️ **`sudo docker compose up` findet die Variablen trotzdem nicht?** `sudo`
> setzt standardmäßig die Umgebungsvariablen der aufrufenden Shell zurück –
> ein zuvor per `export`/`source ./create_secret.sh` gesetzter Key ist für den
> `sudo`-Prozess dann unsichtbar (Fehlermeldung: „required variable
> WKCARDS_SECRET_KEY is missing a value"). Robuster (unabhängig von `sudo`
> und der Shell-Sitzung): die Werte direkt in eine `.env`-Datei im selben
> Verzeichnis wie `docker-compose.yml` schreiben – die liest Docker Compose
> automatisch ein, unabhängig davon, wer/wie es aufgerufen wird:
>
> ```bash
> {
>   echo "WKCARDS_SECRET_KEY=$(openssl rand -base64 32 | tr '+/' '-_')"
>   echo "WKCARDS_SESSION_SECRET=$(openssl rand -hex 32)"
> } >> .env
> ```
>
> `.env` steht bereits in `.gitignore` – landet also nicht versehentlich im
> Repo. Dort können auch andere Variablen wie `WANIKANI_API_TOKEN` stehen
> (falls für eigene Skripte/Tools genutzt) – für die Web-App selbst genügt
> aber der WaniKani-Token in den Einstellungen nach dem ersten Login,
> `WANIKANI_API_TOKEN` als Umgebungsvariable ist nur für das CLI-Skript
> (`kanji_cards.py`) relevant.
>
> Kurz zusammengefasst, als ein Block zum Kopieren:
>
> ```bash
> {
>   echo "WKCARDS_SECRET_KEY=$(openssl rand -base64 32 | tr '+/' '-_')"
>   echo "WKCARDS_SESSION_SECRET=$(openssl rand -hex 32)"
> } >> .env
>
> sudo docker compose up --build
> ```

Diese beiden `export`-Zeilen ersetzen die zwei `python3 -c "..."`-Zeilen im
Codeblock oben 1:1 – der Rest (`docker compose up --build`) bleibt gleich.
`crypto.py` selbst muss auf dem NAS-Host **nie** ausgeführt werden; der Key
wird nur als Umgebungsvariable an den Docker-Container weitergereicht, in dem
Python 3 + `cryptography` bereits enthalten sind (siehe `Dockerfile`).

> ⚠️ **Build läuft durch, aber die Container melden sofort `exec
> ./docker-entrypoint.sh: no such file or directory`?** Das ist ein
> Zeilenenden-Problem, keines mit Dateirechten – `docker-entrypoint.sh` hat
> CRLF- statt LF-Zeilenenden bekommen (typischerweise, wenn der Docker-Build-
> Kontext von einem Windows-Checkout kommt, z. B. über eine Netzwerkfreigabe
> zu einem NAS, und Git dort `core.autocrlf=true` gesetzt hat). Die Shebang-
> Zeile wird dadurch zu `#!/bin/sh\r`, wonach kein Interpreter mehr gefunden
> wird. Ab dieser Version räumt das `Dockerfile` das selbst per `sed` auf
> (`sed -i 's/\r$//' docker-entrypoint.sh`, siehe dort), ein einfaches
> `docker compose up --build` mit dem aktuellen Stand sollte also reichen.
> Tritt es trotzdem auf (z. B. mit einem älteren Checkout), hilft `git pull`
> gefolgt von `docker compose build --no-cache`.

> ⚠️ **`db-1`/`shiori` melden `column "was_new" is of type boolean but
> default expression is of type integer` beim Anwenden der Migrationen?**
> Ein Fehler in der Migration `0839f2a16194` (behoben) – sie setzte für die
> Spalte `review_logs.was_new` einen Integer-Default (`0`), den SQLite
> stillschweigend akzeptiert (dort ist `BOOLEAN` nur eine `INTEGER`-Affinität
> mit CHECK-Constraint), Postgres mit seiner echten `BOOLEAN`-Spalte aber
> ablehnt. `git pull` holt den Fix; da die Migration transaktional läuft,
> hat Postgres beim Fehlschlagen automatisch zurückgerollt (kein
> Datenverlust, kein manueller Eingriff an der DB nötig) – einfach
> `docker compose up --build` erneut ausführen, die Migration setzt an
> derselben Stelle sauber fort.

Der Host-Ordner `./data` ist als Volume eingehängt (`./data:/data`), sodass
PDFs/APKGs und API-Caches einen Neustart überdauern; Accounts/Einstellungen
liegen im `db`-Postgres-Service (eigenes Volume). Im Browser zunächst ein
Konto registrieren (E-Mail/Passwort), danach oben rechts auf ⚙ klicken, den
**WaniKani API-Token** eintragen und speichern.

### Ohne Docker (lokal)

```bash
pip install -r requirements.txt -r requirements-web.txt
python webapp.py               # http://localhost:8000  (Entwicklungsserver, SQLite-Fallback)
# produktiv:
gunicorn -b 0.0.0.0:8000 -w 2 --timeout 600 webapp:app
```

Der Token wird über die Oberfläche gesetzt und landet in `data/settings.json`
(nicht im Repo – `data/` ist in `.gitignore`). Alternativ funktioniert weiter
`WANIKANI_API_TOKEN` als Umgebungsvariable fürs CLI.

## Multi-User-Architektur (Umbau in Arbeit)

Shiori wird schrittweise von einer Single-Tenant-Installation (ein Betreiber,
ein globaler `data/`-Ordner) zu einer öffentlichen Multi-User-SaaS umgebaut.
Getroffene Design-Entscheidungen: **öffentliches Self-Signup**, **E-Mail/
Passwort** als Login (nicht der WaniKani-Token selbst), **PostgreSQL** statt
einer NoSQL-Datenbank (siehe Abwägung unten) und **BYOK** – jeder Nutzer
hinterlegt seine eigenen DeepL-/Gemini-Keys, keine geteilten Kontingente.

**PostgreSQL statt NoSQL – die Abwägung:** Die heutigen JSON-Dateien
(Settings, Custom-/Kana-Cards, Job-Params) sehen auf den ersten Blick nach
einer Dokument-Datenbank aus. Postgres' `JSON`-Spaltentyp bietet aber genau
dieselbe Flexibilität für diese Felder, **ohne** die relationalen Stärken zu
verlieren, die eine Multi-User-SaaS mit Konten/Quotas/Cross-Table-Auswertungen
("welche meiner Wörter sind schon exportiert") braucht: native Joins, ACID-
Transaktionen (z. B. "Job anlegen + Quota-Zähler erhöhen" atomar), riesiges
BI-/Tooling-Ökosystem. Eine Dokument-DB (z. B. MongoDB) lohnt sich vor allem
bei sehr hohem Schreibdurchsatz mit horizontalem Dokument-Sharding – für ein
Flashcard-Tool in realistischer Nutzergrößenordnung nicht der limitierende
Faktor. Zwei unterschiedliche Datenbank-Paradigmen zu betreiben (Postgres
UND Mongo) wäre zusätzlicher Betriebsaufwand ohne einen Vorteil, den JSONB-
Spalten nicht auch böten.

**Aktueller Stand – Phase 1 (Fundament: Auth & Datenmodell), umgesetzt:**

- `models.py`: SQLAlchemy-Schema (`User`, `UserSettings`, `KnownWord`,
  `CustomCard`, `KanaCard`, `Job`) – die künftigen Postgres-Pendants zu den
  heutigen JSON-Dateien/Verzeichnissen. Bewusst `db.JSON` (portabler
  SQLAlchemy-Typ) statt `postgresql.JSONB`, damit dasselbe Schema unverändert
  gegen SQLite (Tests, lokale Entwicklung) UND Postgres (Produktion) läuft.
- `extensions.py`: gemeinsame `db`/`login_manager`-Instanzen (eigenes Modul,
  damit `models.py` `db` importieren kann, ohne einen Zirkelimport mit
  `webapp.py` zu erzeugen).
- `auth.py`: `POST /api/auth/signup`, `/login`, `/logout`, `GET /api/auth/me`
  – E-Mail/Passwort-Auth über `Flask-Login`-Sessions, Passwort-Hashing über
  `werkzeug.security` (kein zusätzlicher Auth-Dienst nötig).
- **`webapp.py` in Blueprints aufgeteilt** (P2-Refactor: war auf ~2300 Zeilen
  mit 10+ fachlichen Bereichen zu einem wachsenden „God File" geworden):
  - `services.py`: geteilte Storage-/Domänen-Helfer OHNE eigene Flask-Routen
    (Settings, Jobs, eigene/Dictionary-Karten, Render-Worker inkl.
    `_build_mixed_deck`/`_run_render`) – von `webapp.py` UND den drei
    Blueprints unten importiert (eine Richtung, kein Zirkelimport).
  - `srs_api.py`: die SRS-Endpunkte (`/api/srs/add`/`queue`/`check`/`answer`/
    `stats`), analog zu `auth.py` als eigener Blueprint. NICHT zu verwechseln
    mit `srs.py` (dem FSRS-Scheduling-Wrapper, siehe unten) – ähnlicher Name,
    andere Verantwortung.
  - `cards_api.py`: CRUD für eigene Karten (`/api/customcards`) und
    Dictionary-/KI-Karten (`/api/kanacards`).
  - `jobs_api.py`: Rendern (`/api/render`) + Job-Verlauf (`/api/jobs/*`).
  - Der RQ-Worker-Prozess (`rq worker renders`) importiert dadurch nur noch
    `services.py`, nicht mehr das komplette `webapp.py` – `services._run_render`
    importiert `webapp.app` bewusst ERST zur Laufzeit (innerhalb der Funktion),
    da `webapp.py` beim Modulstart die drei Blueprints importiert und ein
    Import von `webapp.py` auf Modulebene in `services.py` sonst ein
    Zirkelimport wäre.
  - `webapp.py` selbst enthält nur noch App-Setup, Auth-Verdrahtung und die
    verbleibenden „Kern"-Endpunkte (Einstellungen, Sprachen, Auflisten/
    Resolve, Text-Modus, Wortliste, Frontend-Auslieferung).
- `crypto.py`: Fernet-Verschlüsselung für ruhende Secrets (WaniKani-Token,
  DeepL-/Gemini-Key) – im bisherigen Single-Tenant-Betrieb lagen diese im
  Klartext (akzeptabel, nur der Betreiber selbst betroffen); bei einer
  öffentlichen Instanz mit fremden Nutzern nicht mehr. Braucht einen
  serverseitigen Master-Key (`WKCARDS_SECRET_KEY`, erzeugen mit
  `python -c "from crypto import generate_master_key; print(generate_master_key())"`).
- `migrations/` (Alembic): versioniertes Schema-Management für Postgres.
  `alembic upgrade head` (läuft automatisch beim Container-Start, siehe
  `docker-entrypoint.sh`) statt `db.create_all()` in Produktion – Letzteres
  bleibt ein Komfort-Fallback nur für die lokale SQLite-Entwicklungs-DB.
- `docker-compose.yml`: zusätzlicher `db`-Service (Postgres 16); `DATABASE_URL`
  zeigt bei einem verwalteten Postgres-Dienst (RDS/Neon/Supabase) stattdessen
  direkt dorthin, der `db`-Service ist nur für Self-Hosting/lokale Entwicklung.

**Nötige Umgebungsvariablen für den Multi-User-Betrieb** (ohne sie fällt die
App auf eine lokale SQLite-Datei + einen unsicheren Default-Session-Key
zurück – **nur** für Demo/Entwicklung geeignet, nicht für einen echten
öffentlichen Betrieb):

| Variable | Zweck |
|---|---|
| `DATABASE_URL` | Postgres-Verbindung, z. B. `postgresql+psycopg2://user:pass@host/db`. Ohne gesetzt: SQLite unter `data/shiori.db`. |
| `WKCARDS_SECRET_KEY` | Fernet-Master-Key zum Ver-/Entschlüsseln gespeicherter API-Keys (`crypto.py`). |
| `WKCARDS_SESSION_SECRET` | Flasks Session-Signing-Key (`SECRET_KEY`) – bewusst **eine andere** Variable als `WKCARDS_SECRET_KEY`: unterschiedliche Rotationsanforderungen/Formate. |
| `SESSION_COOKIE_SECURE` | `1` = Session-Cookie nur über HTTPS senden. In Produktion hinter HTTPS-Terminierung setzen; in der lokalen `http://localhost`-Entwicklung weglassen (sonst wird das Cookie nicht gesetzt und der Login schlägt fehl). |
| `TRUST_PROXY` | Anzahl vertrauenswürdiger Reverse-Proxy-Hops davor (meist `1`). Aktiviert `ProxyFix`, damit `X-Forwarded-For` ausgewertet wird und Rate-Limiting/Client-IP hinter einem Proxy stimmen. **Nur setzen, wenn wirklich ein Proxy davor steht** – sonst könnte ein Client die Header fälschen und das per-IP-Limit umgehen. |

**Aktueller Stand – Phase 2 (Datenmigration & Autorisierung), umgesetzt:**

- Alle bisherigen Datei-Speicher (`settings.json`, `known.json`/
  `known_meta.json`, `customcards/*.json`, `kanacards/*.json`, `jobs/*.json`)
  sind auf die Postgres/SQLite-Tabellen aus `models.py` umgezogen, jede
  Zeile trägt einen `user_id` und jede Lese-Funktion filtert danach
  (`load_settings()`, `load_known()`, `list_customs()`, `list_kana()`,
  `list_jobs()` – alle über `current_user.id`).
- **Ownership-Checks statt bloßem Scoping**: für Zugriffe per ID (Job/
  Custom-/Kana-Card) gibt es eigene `*_owned()`-Funktionen
  (`read_job_owned()`, `read_custom_owned()`, `read_kana_owned()`), die
  `None` liefern, wenn die ID entweder nicht existiert ODER einem anderen
  Nutzer gehört – **bewusst dieselbe Antwort für beide Fälle** (404 in
  beiden Fällen), damit kein Endpunkt verrät, ob eine fremde ID überhaupt
  existiert (IDOR-Schutz). `/api/render` validiert zusätzlich VOR dem
  Job-Anlegen, dass alle angegebenen `custom_ids`/`kana_ids` dem
  anfragenden Nutzer gehören – sonst könnte man fremden Karteninhalt in ein
  eigenes Export hineinrendern lassen.
- **`KanaCard` bekam einen zusammengesetzten Primärschlüssel** `(user_id, id)`
  statt `id` allein: die ID ist ein reiner Wort-Hash (`kc.kana_card_id()`),
  unabhängig vom Nutzer – zwei Nutzer, die dieselbe Vokabel als Karte
  anlegen, hätten sonst denselben Primärschlüssel gehabt und sich
  gegenseitig überschrieben (live nachgestellt und gefixt, siehe Tests
  `test_api_kanacards_same_word_different_users_no_collision`).
- **Alle zentralen Endpunkte sind jetzt `@login_required`** (Ausnahmen:
  `/api/auth/*` selbst sowie die statischen Frontend-Dateien). Ohne Login
  liefert jeder geschützte Endpunkt `401` statt Daten preiszugeben.
- **Render-Worker im eigenen App-Context**: `_run_render()` braucht für
  DB-Zugriffe `with app.app_context():` (kein Request-Kontext im Worker
  verfügbar) – Nutzer-Settings werden explizit über den im Job gespeicherten
  `user_id` geladen (`load_settings_for_user()`), nicht über `current_user`.
  Seit Phase 3 läuft dieser Worker-Code in einem eigenen RQ-Prozess statt in
  einem `threading.Thread` im Webserver-Prozess (siehe unten).
- **Minimaler Login/Signup-Gate im Frontend** (`web/index.html`/`app.js`):
  ein Vollbild-Overlay blockiert die App, bis `/api/auth/me` eine
  eingeloggte Sitzung bestätigt; „Registrieren"/„Anmelden" wechselbar per
  Klick, „Abmelden" oben rechts im Header.
- **WaniKani-Token wird explizit durchgereicht, nicht mehr prozessglobal**:
  `kanji_cards.py`s öffentliche Funktionen (`resolve_level()`,
  `search_subjects()`, `resolve_composition()`, `resolve_subject_ids()`,
  `resolve_subject_deck()`, `card_details_for_ids()`, `annotate_text()`,
  `annotate_text_ai()`, `_make_client()`) akzeptieren jetzt ein optionales
  `token`-Keyword – webapp.py übergibt dabei den Token des jeweils
  eingeloggten Nutzers (`load_settings().get("token")`) statt wie zuvor
  `_apply_token_env()` über `os.environ["WANIKANI_API_TOKEN"]` zu setzen
  (eine **prozessglobale** Variable, unter echter Nebenläufigkeit mehrerer
  Nutzer-Requests im selben Worker ein Race-Condition-Risiko – ein Request
  hätte potenziell mit dem gerade von einem ANDEREN Nutzer gesetzten Token
  laufen können). `WANIKANI_API_TOKEN` bleibt weiterhin der Fallback fürs
  CLI (`python kanji_cards.py <level>`), wo pro Prozessaufruf ohnehin nur
  ein Nutzer relevant ist – `_make_client()` liest die Variable nur, wenn
  kein `token` explizit übergeben wurde.

**Testbarkeit**: `tests/conftest.py` stellt dafür die Fixtures `db_session`
(frische Tabellen pro Test), `client` (Testclient mit frisch registriertem
Nutzer) und `logged_in_user` (nur `current_user`, ohne echten HTTP-Request)
bereit. Bemerkenswerte Falle dabei: Flask reaktiviert bei einem bereits
aktiven App-Context **denselben** `g`, wenn eine WSGI-Anfrage über den
Testclient läuft (`flask.ctx.RequestContext.push()`) – hält ein Test also
absichtlich einen App-Context offen (nötig für Modell-Queries im Testkörper
ohne Umweg über einen Request) UND simuliert zwei verschiedene Nutzer über
zwei Testclients, bleibt der zuerst eingeloggte Nutzer in `g` hängen. Behoben
über ein `before_request`-Sicherheitsnetz in `webapp.py`
(`_reset_login_cache()`), das `g._login_user` vor jedem Request verwirft –
in Produktion ein No-Op (dort bekommt jeder Request ohnehin einen frischen
Context), in Tests aber notwendig für korrekte Multi-Tenant-Isolationstests.

**Aktueller Stand – Phase 3 (Jobs/Dateien SaaS-tauglich, Schutzmechanismen,
Betrieb & Recht), umgesetzt:**

- **Job-Queue statt `threading.Thread`**: `/api/render` reiht Render-Jobs
  jetzt über `render_queue.enqueue(_run_render, job_id, job_timeout=600)`
  ([RQ](https://python-rq.org/) + Redis) ein, statt sie im Webserver-Prozess
  selbst per Hintergrund-Thread abzuarbeiten. Ein oder mehrere separate
  `rq worker renders`-Prozesse holen Jobs von der Queue – ein hängender
  Render-Job blockiert dadurch weder den Webserver noch andere Nutzer, und
  die Worker-Anzahl skaliert unabhängig von den Webserver-Instanzen
  (`docker compose up --scale worker=3`). Weil jeder Job in einer eigenen
  Worker-Ausführung läuft (keine parallelen Threads mehr im selben Prozess),
  entfällt das frühere `_export_lock`.
- **Object-Storage-Abstraktion (`storage.py`)**: generierte PDFs/APKGs
  liegen standardmäßig weiterhin lokal unter `data/output/` (Zero-Config,
  wie bisher), können aber ohne Code-Änderung in S3/MinIO umgezogen werden –
  einfach `S3_BUCKET` (und optional `S3_ENDPOINT_URL` für MinIO) setzen.
  `_run_render()` rendert dafür zunächst in ein `tempfile.TemporaryDirectory()`
  (WeasyPrint/genanki brauchen einen echten Dateipfad), liest danach die
  fertigen Bytes und übergibt sie an `storage.save_output()`. Downloads
  (`/api/jobs/<id>/pdf`, `/apkg`) fragen `storage.generate_download_url()`
  ab: liefert die Funktion eine signierte, zeitlich begrenzte S3-URL, wird
  per `redirect()` direkt dorthin verwiesen (kein Umweg über den App-Server);
  ohne Object Storage liefert sie `None`, und die Datei geht wie bisher per
  `send_file()` vom lokalen Disk raus. Getestet über
  [moto](https://github.com/getmoto/moto) (`tests/test_storage.py`) – kein
  echtes AWS/MinIO nötig, um die S3-Pfade zu verifizieren.
- **Rate-Limiting (`Flask-Limiter`)**: alle Endpunkte greifen auf ein
  globales Default-Limit von 120 Requests/Minute zurück (pro eingeloggtem
  Nutzer, sonst pro IP – `key_func` nutzt `current_user.get_id()`).
  Teurere Endpunkte (externe API-Aufrufe/Rendering) haben zusätzlich ein
  enges eigenes Limit: `/api/render` 10/Minute, `/api/gemini/*` sowie
  `/api/text-extract`/`/api/text-annotate-ai` je 20/Minute. Nutzt dieselbe
  Redis-Instanz wie die Job-Queue (`storage_uri=REDIS_URL`) – eine
  Infrastruktur für zwei Zwecke.
- **Limit an gleichzeitigen Render-Jobs pro Nutzer**: `/api/render` zählt vor
  dem Anlegen eines neuen Jobs, wie viele `Job`-Zeilen des anfragenden
  Nutzers noch `queued`/`running` sind, und lehnt ab `_MAX_CONCURRENT_JOBS_PER_USER`
  (3) mit `429` ab. Grund: anders als WaniKanis eigenes Rate-Limit (das
  bereits pro Token/Nutzer gilt) ist die Render-Worker-Kapazität geteilte
  Infrastruktur – ein einzelner Nutzer soll sie nicht durch beliebig viele
  parallele Jobs blockieren können.
- **Strukturiertes Logging mit `user_id`-Kontext**: jede Log-Zeile bekommt
  automatisch den eingeloggten Nutzer angehängt
  (`%(asctime)s %(levelname)s %(name)s [user=%(user_id)s]: %(message)s`),
  über einen `logging.Filter`, der auf den **Root-Handler** registriert ist
  (nicht auf den Root-Logger selbst – Logger-Filter greifen nur für Records,
  die direkt auf diesem Logger erzeugt wurden, nicht für Records, die von
  Kind-Loggern wie `werkzeug`/`gunicorn.error` dorthin propagiert werden;
  ein Filter auf dem Root-*Logger* hätte solche Records ohne `user_id`
  durchgelassen und beim Formatieren mit `ValueError` gecrasht – live
  nachgestellt und gefixt). Außerhalb eines Requests (z. B. im RQ-Worker-
  Prozess) steht `user_id` auf `"-"`.
- **Backups & Betrieb**: siehe [`docs/BACKUP.md`](docs/BACKUP.md) für die
  Postgres-Backup-Strategie.
- **Datenschutz/ToS**: siehe [`docs/PRIVACY_TEMPLATE.md`](docs/PRIVACY_TEMPLATE.md)
  und [`docs/TERMS_TEMPLATE.md`](docs/TERMS_TEMPLATE.md) – **Vorlagen**, die
  vor einem echten öffentlichen Betrieb von einem Juristen geprüft/angepasst
  werden müssen, keine Rechtsberatung.

**Zusätzliche Umgebungsvariablen für Phase 3** (alle optional – ohne sie
läuft die App wie zuvor mit einem lokalen Redis-Fallback bzw. rein lokalem
Disk-Speicher):

| Variable | Zweck |
|---|---|
| `REDIS_URL` | Redis-Verbindung für Job-Queue + Rate-Limiting. Ohne gesetzt: `redis://localhost:6379/0`. |
| `RUN_MIGRATIONS` | `1` = dieser Container wendet beim Start `alembic upgrade head` an. **Genau einem** Container (dem Web-Service) setzen – nie gleichzeitig Web und Worker, sonst könnten sie sich beim Schema-DDL in die Quere kommen (siehe `docker-entrypoint.sh`). |
| `S3_BUCKET` | Aktiviert Object Storage für generierte PDFs/APKGs (siehe `storage.py`). Ohne gesetzt: lokales Disk unter `data/output/`. |
| `S3_ENDPOINT_URL` | Für selbst gehostetes S3-kompatibles Storage (z. B. MinIO). Bei AWS S3 weglassen. |
| `S3_REGION` | AWS-Region, Default `us-east-1`. Bei MinIO i. d. R. irrelevant. |

Lokal einen Worker-Prozess starten (zusätzlich zum Webserver):

```bash
rq worker renders --url redis://localhost:6379/0
```

Mit Docker startet `docker compose up` automatisch einen `redis`- und einen
`worker`-Service mit (siehe `docker-compose.yml`).

### Migrationsdisziplin ab Produktivbetrieb

Alle bisherigen Migrationen (`0983277a4bb3` … `0839f2a16194`) begründen ihr
Vorgehen mit „kein Projekt mit Produktivdaten bislang, kein Backfill nötig".
Das gilt nur bis zum ersten echten Nutzer – ab dann gelten für neue
Migrationen andere Regeln:

- **Additiv statt destruktiv**: neue Spalten `nullable=True` (oder mit
  serverseitigem `default`) anlegen, NIE direkt `NOT NULL` ohne Default auf
  eine Tabelle mit bestehenden Zeilen – das schlägt in Postgres sofort fehl
  bzw. würde in SQLite alle Zeilen mit `NULL` befüllen.
- **Backfill als eigener Schritt**: ein `NOT NULL`-Constraint erst NACH einem
  Backfill (`op.execute("UPDATE … SET spalte = default WHERE spalte IS
  NULL")`) in einer zweiten `alembic`-Revision ergänzen, nicht in derselben
  Migration wie das Anlegen der Spalte – sonst gibt es kein sauberes
  Zwischen-Deployment, in dem alter und neuer Code parallel laufen können
  (Rolling-Deployment/Zero-Downtime).
- **Kein Datenverlust durch Spalten-/Tabellen-Löschung** ohne vorherige
  Rücksprache – vor dem Entfernen einer Spalte/Tabelle in `downgrade()`
  *und* `upgrade()` prüfen, ob noch produktive Daten darin stehen, und im
  Zweifel erst in einer separaten Migration deprecaten (Spalte behalten,
  aber nicht mehr befüllen) statt sofort zu löschen.
- **Migrationen lokal gegen eine Kopie der Produktions-Struktur testen**
  (`alembic upgrade head` auf einer frischen SQLite-/Postgres-DB mit
  Beispieldaten), bevor sie deployed werden – die Tests in `tests/` decken
  nur das ORM-Modell ab, nicht den Migrationspfad selbst.
- **Ein Rollback-Pfad pro Migration**: `downgrade()` muss tatsächlich
  funktionieren (nicht nur `pass`), sobald die Migration produktive Daten
  betrifft – vorher genügte das, weil es ohnehin nichts zurückzurollen gab.

## Multi-Language-Architektur

Shiori war ursprünglich ein reines Japanisch-Lernwerkzeug – WaniKani, Kanji,
Onyomi/Kunyomi-Lesungen, Janome-Tokenisierung und JMdict waren fest in jede
Schicht eingebaut. Der Umbau macht daraus ein **Multi-Language-Tool**: jeder
Nutzer hat eine **Muttersprache** (`User.native_lang`, steuert u. a. die
UI-Sprache) und genau eine **aktive Zielsprache** (`UserSettings.active_target_lang`,
der gerade gelernte "Kurs") – umschaltbar über den Sprachwechsler in den
Einstellungen, ohne dass Fortschritt/Karten verloren gehen (siehe unten,
"Datenmodell").

**Grundprinzip: `LanguagePack`.** Alles, was sich zwischen Zielsprachen
unterscheidet (externe Lernstufen-Quelle wie WaniKani, Lesungsfelder,
Furigana, Offline-Tokenizer, Wörterbuch-Backend, Anki-Deck-Struktur), steckt
hinter einem gemeinsamen Interface (`languages/base.py: LanguagePack`).
Japanisch (`languages/japanese.py`) ist der einzige **vollausgestattete**
Pack – er deklariert nur die Capability-Flags (`has_content_provider=True`,
`reading_labels=["Onyomi","Kunyomi"]`, `has_furigana=True`,
`has_offline_tokenizer=True`, `has_kana_input=True`); die eigentliche Logik
bleibt bewusst **unverändert** in `kanji_cards.py`/`dictionary.py` (kein
riskanter Rewrite der ~2300 Zeilen WaniKani-/Janome-Integration). Jede
andere Zielsprache bekommt automatisch den `GenericPack`
(`languages/generic.py`, alle Flags auf `False`) über `languages/registry.py:
get_pack(code)`.

**Was funktioniert wo:**

| Modus | Japanisch (`JapanesePack`) | andere Sprachen (`GenericPack`) |
|---|---|---|
| Level-Stapel / Suche (WaniKani) | ✅ | ❌ (Endpunkt liefert 400, siehe `_require_content_provider()`) |
| Aus Text (Janome, offline) | ✅ | ❌ (kein Offline-Tokenizer) |
| Mit KI (Gemini-Satzanalyse) | ✅ | ✅ (Prompts sind auf Ziel-/Muttersprache parametrisiert, siehe unten) |
| Frei erstellen / Wortliste | ✅ | ✅ |
| Wörterbuch-Lookup für Dictionary-Karten | JMdict | Gemini als universeller Fallback (Entscheidung: kein zweites JMdict-Analogon pro Sprache pflegen) |

**Datenmodell:** `KnownWord`/`CustomCard`/`KanaCard`/`Job` haben eine neue
`target_lang`-Spalte – Fortschritt/Karten/Job-Verlauf sind pro Zielsprache
getrennt (ein Sprachwechsel zeigt also eine andere, aber vollständig
erhaltene Ansicht, kein Datenverlust). `KanaCard`s Primärschlüssel wurde um
`target_lang` erweitert (`(user_id, target_lang, id)`), weil der Wort-Hash
sonst über Sprachen hinweg kollidieren könnte. Der WaniKani-Token wandert
von `UserSettings` (pro Nutzer global) in eine neue Tabelle
`UserLanguageSecrets` (pro Nutzer **und** Zielsprache) – er ergibt nur für
`target_lang="ja"` einen Sinn, DeepL-/Gemini-Keys bleiben dagegen global
(Provider-übergreifend nutzbar). Migration `c7691d3fd577` legt die neuen
Spalten an und befüllt Bestandsdaten mit `target_lang="ja"`.

**Gemini-Prompts parametrisiert statt hartcodiert:** `gemini_client.py`
nahm Japanisch→Deutsch fest an (Antwortfeld hieß `translation_de`,
Prompt-Text erwähnte "Japanisch"/"Hiragana" wörtlich). Jetzt nehmen
`analyze_sentences()`/`transcribe_image()` `target_lang_name`/
`native_lang_name`/`has_reading`(bzw. `has_furigana`) als Parameter, das
Antwortfeld heißt generisch `translation`. Der Japanisch-spezifische
Partikel-Beispieltext (は/が/を/…) bleibt nur bei `has_reading=True`
erhalten – für andere Sprachen eine gekürzte, aber inhaltlich identische
Anweisung. `kanji_cards.annotate_text_ai()` bekam einen `target_lang`-
Parameter: der WaniKani-/JMdict-Abgleich läuft nur bei `"ja"`, für andere
Sprachen fällt jedes erkannte Inhaltswort automatisch auf den bereits
sprachunabhängigen `source: "ai"`-Zweig zurück (Bedeutung/Lesung/Funktion
kommen direkt von Gemini, kein externes Wörterbuch nötig – das ist
zugleich die Umsetzung von Entscheidung 3 unten).

**Anki-Export generalisiert:** Der Root-Deck-Name war fest `"Japanisch"`
(`anki_export._ROOT_DECK`) – jetzt ein Parameter `root_deck_name`
(`export_deck(..., root_deck_name=...)`), den `webapp.py` aus
`get_pack(target_lang).display_name("de")` befüllt. Ein Export in einer
anderen Zielsprache landet dadurch z. B. unter `Englisch::sonstige` statt
fälschlich unter `Japanisch::…`.

**Frontend-i18n:** `web/i18n.js` + `web/i18n/{de,en}.json` übersetzen die
UI-Chrome (Header, Login/Signup, komplette Einstellungen, alle Moduswahl-
Bereiche inkl. Level/Suche/Text/Frei-erstellen/Wortliste, Kartentabelle,
Render-Optionen, Verlauf, Footer) nach der Muttersprache – bewusst
**getrennt** von der Zielsprache (Karteninhalte bleiben in der gelernten
Sprache, nur Menüs/Buttons wechseln). Deckt die statische Chrome breit ab
(`data-i18n`-Attribute), **nicht** dynamisch von JavaScript erzeugte
Strings (z. B. Toast-Meldungen, Fehlertexte) – eine Erweiterung um weitere
Sprachen/Strings ist rein additiv (neue `i18n/<code>.json` + Attribute).
Der Sprachwechsler (Einstellungen → „Sprachen") ruft `GET /api/languages`
(Capabilities + verfügbare Zielsprachen) und `POST /api/settings/language`
auf; die Level-Stapel-/Suche-Tabs blenden sich automatisch aus, wenn die
aktive Zielsprache keinen `has_content_provider`-Pack hat (mit Fallback auf
„Frei erstellen"). Das Registrierungsformular fragt Mutter-/Zielsprache
gleich mit ab (`GET /api/languages/public`, bewusst ohne Login – vor dem
ersten Login gibt es noch keinen `current_user`).

**Generischer Wörterbuch-Fallback:** `gemini_client.lookup_word()` +
`kanji_cards.build_generic_dictionary_card()` lassen ein manuell
eingegebenes Wort (Standard-Endpunkt `POST /api/kanacards`, `source`
fehlt/`"dictionary"`) für Zielsprachen ohne JMdict-Äquivalent per Gemini
statt per Wörterbuch-Datei nachschlagen – braucht dafür einen hinterlegten
Gemini-Key. Bei Japanisch bleibt JMdict die Quelle (schneller, kein
API-Call nötig).

**Testabdeckung:** `tests/test_webapp.py` prüft `/api/languages`,
`/api/settings/language`, die Isolation von Custom-/Kana-/Known-Words/Jobs
zwischen Zielsprachen sowie das Blockieren der WaniKani-only-Endpunkte für
Nicht-Japanisch; `tests/test_gemini_client.py`/`tests/test_kanji_cards.py`
decken `lookup_word()`/`build_generic_dictionary_card()` ab.

**Offene Entscheidungen (Defaults gesetzt, bei Bedarf ändern):**

1. **UI-Chrome-Sprache**: an `native_lang` gekoppelt (aktuell `de`/`en`
   übersetzt), nicht an die Zielsprache – ein Nutzer, der Japanisch lernt,
   soll nicht zwangsläufig eine japanische Oberfläche bekommen.
2. **Ein aktiver "Kurs"**: genau eine `active_target_lang` gleichzeitig,
   umschaltbar ohne Datenverlust (kein Multi-Kurs-Dashboard mit mehreren
   gleichzeitig sichtbaren Sprachen).
3. **Gemini als universeller Wörterbuch-Fallback**: für Sprachen ohne
   eigenes Wörterbuch-Backend (alle außer Japanisch) übernimmt Gemini die
   Bedeutungs-/Lesungs-Ermittlung im KI-Textmodus UND beim manuellen
   Wort-Nachschlagen – braucht also zwingend einen hinterlegten Gemini-Key,
   um für diese Sprachen nutzbar zu sein.

**Nächste mögliche Schritte** (nicht Teil dieses Umbaus, da erst bei
Bedarf): ein zweiter vollausgestatteter `LanguagePack` (z. B. Chinesisch
mit Pinyin-Lesungen/jieba-Tokenizer/CC-CEDICT) – dank der Abstraktion ein
in sich geschlossener Task, der keinen bestehenden Code anfasst; i18n für
dynamisch erzeugte JS-Strings (Toasts/Fehlermeldungen); weitere UI-Sprachen
über zusätzliche `i18n/<code>.json`-Dateien.

## Vokabeltrainer (SRS, Fundament – Phase 1)

Shiori exportiert Karten bisher nur als PDF oder Anki-Paket. Geplant ist
eine dritte Option: Karten direkt **in Shiori selbst** mit Spaced Repetition
lernen (Auswahl-Tabelle → „Zum Lernen hinzufügen" statt/zusätzlich zu
„PDF erzeugen"/„Anki exportieren"). Aktuell umgesetzt ist nur das
**Datenmodell-Fundament**, noch ohne Endpunkte/UI:

- `models.ReviewState`: ein SRS-Lernstand pro `(user_id, target_lang,
  card_type, card_id, item_type)` – zeigt per `card_type`+`card_id` auf eine
  der drei bestehenden, heterogenen Kartenquellen (WaniKani-Subject-ID,
  `CustomCard.id`, `KanaCard.id`) statt Karteninhalte zu duplizieren.
  `item_type` bildet WaniKanis Verhalten nach: ein Kanji/eine Vokabel
  bekommt zwei unabhängige Zeilen (`meaning` + `reading`, getrennter
  Fortschritt pro Prüfrichtung), eine Custom-/Dictionary-Karte nur eine
  (`front` bzw. `meaning`).
- `srs.py`: dünner Wrapper um die [`fsrs`](https://pypi.org/project/fsrs/)-
  Bibliothek (Free Spaced Repetition Scheduler, seit Anki 23.10 dessen
  Standard-Algorithmus, Nachfolger von SM-2) – die eigentliche Scheduling-
  Mathematik kommt vollständig aus der Bibliothek, nicht selbst
  nachgebaut. `new_review_state()` erzeugt eine sofort fällige neue Karte,
  `review(state, rating)` verarbeitet eine Bewertung (`"again"`/`"hard"`/
  `"good"`/`"easy"`, wie bei Anki) und liefert den aktualisierten Zustand.
- Geplanter Prüf-Flow (noch nicht gebaut): Freitext-Eingabe (Bedeutung/
  Lesung, WanaKana-Eingabehilfe fürs Japanische) wird automatisch geprüft
  (Fuzzy-Match) und schlägt eine Bewertung vor – der Nutzer bestätigt oder
  überschreibt sie manuell, bevor sie ins FSRS-Scheduling einfließt.
  Kombiniert damit WaniKanis strenge Eingabe-Prüfung mit Ankis
  Selbsteinschätzungs-Flexibilität.

**Phase 2 (umgesetzt) – Warteschlange & Hinzufügen:**

- `POST /api/srs/add` – nimmt dieselbe Auswahl-Form wie `/api/render`
  entgegen (`subject_ids`/`custom_ids`/`kana_ids`) und legt pro Karte die
  passenden `ReviewState`-Zeilen an: Kanji/Vokabel bekommen `meaning`+
  `reading`, Radicals (keine Lesung bei WaniKani) nur `meaning`, Custom-
  Karten `front`, Dictionary-/KI-Karten `meaning` (+`reading`, falls die
  Karte selbst eine Lesung hat). **Idempotent** – ein erneutes Hinzufügen
  überschreibt nie den Fortschritt bereits vorhandener Zeilen.
- `GET /api/srs/queue` – fällige Karten der aktiven Zielsprache, älteste
  Fälligkeit zuerst, mit aufgelöstem Vorschautext (`front`) und `is_new`-
  Flag; `due_total` unabhängig vom `limit`-Parameter fürs „X fällig"-Badge.
  WaniKani-Subjects werden gebündelt in einem Request aufgelöst (nutzt den
  bestehenden Disk-Cache aus `kanji_cards.py`) und fallen ohne gespeicherten
  Token automatisch auf die Sample-Registry zurück (Demo-Modus, wie überall
  sonst in der App).

**Phase 3 (umgesetzt) – Eingabe-Prüfung & Review-Screen:**

- `POST /api/srs/check` – getippte Antwort per Fuzzy-Match gegen die
  akzeptierten Antworten prüfen (Levenshtein-Toleranz: 1 Tippfehler erlaubt
  ab 4 normalisierten Zeichen, sonst exakt – wie bei WaniKani) und eine
  Bewertung **vorschlagen**, OHNE den FSRS-Lernstand zu verändern. Bei
  Kanji/Vokabel kommen die akzeptierten Antworten aus den WaniKani-Daten
  selbst (Meanings bzw. Onyomi+Kunyomi/Vokabel-Lesungen), bei Dictionary-/
  KI-Karten aus `meaning`/`reading`. Custom-Karten sind nicht automatisch
  prüfbar (freies HTML auf beiden Seiten) – dort bleibt `correct`/
  `suggested_rating` `None`, der Nutzer bewertet sich rein selbst wie bei Anki.
- `POST /api/srs/answer` – übernimmt die (ggf. vom Nutzer überschriebene)
  Bewertung und schreibt den FSRS-Lernstand fort. Vertraut der übergebenen
  Bewertung, ohne selbst nochmal zu prüfen – die Prüfung ist bewusst vom
  Fortschreiben getrennt (`/api/srs/check` bleibt ein reiner Lesevorgang).
- Frontend: neuer „Üben"-Tab mit vollständigem Review-Screen (Vorderseite
  zeigen → Antwort eintippen → prüfen → Bewertung vorgeschlagen/bestätigen/
  überschreiben → nächste Karte). Die Auswahl-Tabelle bekommt einen dritten
  Button „Zum Lernen hinzufügen" neben „PDF erzeugen"/„Anki exportieren"
  (ruft `/api/srs/add` mit derselben Auswahl auf).
- Live-Test (Playwright) deckte eine echte, vorbestehende Race-Condition
  auf: `_get_or_create_user_settings()`/`_get_or_create_language_secrets()`
  crashten mit einem UNIQUE-constraint-`IntegrityError`, wenn das Frontend
  mehrere Requests beim Login parallel abfeuert (`loadSettings()`/
  `loadLanguages()`, keiner wartet auf den anderen) und beide gleichzeitig
  "existiert noch nicht" sehen – gefixt (Rollback + Zeile des Gewinners
  erneut lesen statt crashen), mit Regressionstest.

**Phase 4 (umgesetzt) – Dashboard & Tageslimits:**

- Neue Tabelle `models.ReviewLog`: ein Eintrag pro tatsächlich abgeschickter
  Bewertung (User, Zielsprache, Karte, Bewertung, war die Karte davor neu).
  Getrennt von `ReviewState` (das nur den *aktuellen* FSRS-Zustand hält,
  keine Historie) – ohne dieses Log ließen sich weder Tageslimits noch eine
  ehrliche Retention-Rate berechnen.
- **Tageslimits** wie bei Anki-Deck-Optionen: `srs_new_per_day` (Default 20)
  und `srs_reviews_per_day` (Default 200), über den bestehenden generischen
  `defaults`-Mechanismus einstellbar (`POST /api/settings {"defaults":
  {"srs_new_per_day": 10}}`) – kein neues Einstellungs-Schema nötig.
  `GET /api/srs/queue` liefert dadurch nie mehr neue Karten oder Reviews
  aus, als die Tageslimits erlauben; bereits fällige Karten, die das Limit
  sprengen, bleiben einfach bis zum nächsten Tag liegen (kein Datenverlust).
- `GET /api/srs/stats`: Reviews/neue Karten heute, **Retention der letzten
  7 Tage** (Anteil NICHT „again" bewerteter Reviews – Standarddefinition
  bei Anki/FSRS), sowie die Kartenanzahl je Lernstufe (neu/Learning/Review/
  Relearning). Alles pro aktiver Zielsprache isoliert.
- Frontend: kompaktes Statistik-Dashboard auf dem „Üben"-Startbildschirm
  (4 Kennzahlen-Kacheln + ein Fortschrittsbalken nach Lernstufe), das sich
  nach jeder abgeschlossenen Wiederholungs-Session automatisch aktualisiert.

Damit ist der Vokabeltrainer aus dem ursprünglichen Brainstorming
vollständig umgesetzt: FSRS-Scheduling, kombinierte Eingabe-Prüfung +
Selbstbewertung, dritter Export-Weg neben PDF/Anki, Tageslimits und
Statistik-Dashboard.

**Phase 5 (umgesetzt) – Karten-Verwaltung & Eingabe-Komfort:**

- `GET /api/srs/cards` / `POST /api/srs/remove`: ein Karten-Browser („Karten
  verwalten" auf dem Üben-Startbildschirm) listet alle Karten im Training der
  aktiven Zielsprache – gruppiert je Karte (Meaning+Reading zusammengefasst),
  mit Vorschautext, Fälligkeit und Wiederholungszahl – und erlaubt das gezielte
  Entfernen einer versehentlich hinzugefügten Karte. Nur der SRS-Lernstand
  wird verworfen, das Kartenobjekt (WaniKani/eigene Karte) bleibt bestehen.
- **WanaKana im Review-Screen**: bei japanischen Lesungen wird das
  Antwortfeld automatisch mit WanaKana gebunden (Romaji→Kana live), ohne
  IME-Umschalten. Nur bei `item_type=="reading"` und aktiver Zielsprache
  Japanisch – für Bedeutungen/andere Sprachen wird die Bindung wieder gelöst,
  damit normale Texteingabe nicht ins Kana verfälscht wird. Ausgeliefert über
  die neue `/vendor/`-Route (dieselbe Path-Traversal-Härtung wie `web/`).
- **Tastatur-Shortcuts** wie bei Anki: nach dem Aufdecken bewerten die Tasten
  `1`–`4` (Nochmal/Schwer/Gut/Leicht), `Enter` übernimmt den vorgeschlagenen
  Wert – nur aktiv, solange die Antwort aufgedeckt ist.

**Konto-Verwaltung (umgesetzt):** `POST /api/auth/change-password` (altes
Passwort zur Bestätigung nötig) und `DELETE /api/auth/account` (Passwort-
Bestätigung, löscht das Konto samt aller zugehörigen Daten – Karten,
Lernstände, Verlauf, Job-Ausgabedateien – da die Fremdschlüssel bewusst kein
`ON DELETE CASCADE` haben, siehe `services.delete_all_user_data`). Beide im
Einstellungs-Panel unter „Konto".

**Phase 6 (umgesetzt) – Streak, Heatmap & PWA:**

- **Streak + Kalender-Heatmap** im Üben-Dashboard: `/api/srs/stats` liefert
  zusätzlich `streak_days` (aufeinanderfolgende Lerntage; ein noch review-
  freier heutiger Tag bricht den Streak nicht, solange gestern gelernt wurde –
  übliche Duolingo-/WaniKani-Semantik, siehe `srs_api._compute_streak`) und
  `activity` (Reviews pro UTC-Kalendertag der letzten ~26 Wochen, serverseitig
  per `GROUP BY date(...)` aggregiert – funktioniert in SQLite UND Postgres).
  Das Frontend rendert daraus eine GitHub-artige Heatmap (26 Wochen × 7 Tage,
  Montag oben) mit fünf Intensitätsstufen plus eine „🔥 N"-Streak-Kachel.
- **PWA**: `web/manifest.webmanifest` (standalone, generierte 栞-Icons in
  192/512 px + Apple-Touch-Icon, per PyMuPDF aus der gebündelten Noto-Serif-
  JP erzeugt) und ein minimaler Service Worker (`web/sw.js`) machen Shiori
  aufs Handy-Homescreen installierbar. Der SW arbeitet bewusst
  **network-first** mit Cache-Fallback (online immer der frische Stand direkt
  nach einem Deploy, der Cache dient nur als Offline-Notnagel – vermeidet die
  klassische „PWA liefert ewig die alte Version"-Falle) und fasst `/api/`-
  Requests gar nicht an (Sitzungs-/Lernstands-Daten werden nie gecacht).

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

**Felder manuell anpassen** (`kc.card_details_for_ids()` / `kc._apply_field_overrides()`,
Endpunkte `/api/card-detail` und `/api/render`): Der Bearbeiten-Dialog in der
Kartentabelle braucht zunächst die **vollen** Karten-Felder statt der
Kurzfassung aus `_subject_descriptor()` (nur Zeichen/Bedeutung/Level) –
`card_details_for_ids()` baut dieselben Card/RadicalCard/VocabCard-Objekte
wie `resolve_subject_deck()` (gemeinsame Registry-Lade-Logik in
`_build_subject_registry()`, kein doppelter API-Aufruf-Code) und exportiert
sie per `dataclasses.asdict()` als JSON statt daraus ein PDF zu erzeugen.
Gespeicherte Änderungen landen clientseitig in `field_overrides`
(Subject-ID → `{feldname: neuer_wert}`, analog zu `sentence_overrides`) und
werden erst beim eigentlichen Rendern angewendet: `_apply_field_overrides()`
prüft für jeden übergebenen Feldnamen per `dataclasses.fields()`, ob er
tatsächlich auf der jeweiligen Dataclass existiert, und `setattr()`t nur dann
– unbekannte/falsche Keys (z. B. durch einen Frontend-Bug oder manipulierte
Requests) werden defensiv ignoriert statt einen Fehler zu werfen oder
beliebige Attribute auf dem Objekt zu erzeugen. Die WaniKani-Originaldaten
selbst bleiben dabei unangetastet – die Overrides wirken nur auf das jeweils
frisch gebaute Karten-Objekt für **diesen** Export.

**🌐 Übersetzen-Button & Zielsprache-Einstellung** (`/api/translate`): nutzt
dieselbe DeepL-Anbindung wie die Beispielsatz-Übersetzung für Dictionary-
Karten (`dictionary.translate_sentence()`), nur mit `source_lang="EN"` statt
`"JA"` (die WaniKani-Texte sind englisch) und der in `settings.json`
hinterlegten `target_lang` (Default `"DE"`, wählbar aus einer festen Liste
`_TARGET_LANGS` in `webapp.py`) statt eines hartkodierten Zielsprachcodes.
Frontend-seitig wird die Übersetzung dem Original-Text **vorangestellt**
(`Übersetzung\n—\nOriginal`) statt ihn zu ersetzen – rein clientseitige
Textkonvention (kein zusätzliches Datenmodell-Feld nötig), die den
Originaltext zur Kontrolle sichtbar hält, wie im Feld-Dialog gespeichert wird
es dann wie jedes andere manuell bearbeitete Feld über `field_overrides`.

**Bildkarten** (`gemini_client.generate_image()`, Endpunkt
`/api/gemini/generate-image`): eigenes Bild-Modell (`IMAGE_MODEL =
"gemini-2.5-flash-image"`) statt des Text-Chat-Modells der Satzanalyse – nur
bestimmte Gemini-Modelle können überhaupt Bilder erzeugen, die „-latest"-
Text-Aliase (siehe `DEFAULT_MODEL`) nicht. Anders als `transcribe_image()`/
`synthesize_speech()` **bewusst ungecacht**: Bildgenerierung ist nicht
deterministisch, „Neu generieren" im Frontend muss bei jedem Klick
tatsächlich ein neues Ergebnis liefern statt denselben gecachten Treffer.
Zwei neue, optionale Felder auf `kc.VocabCard` (`image_data_uri`,
`show_meaning_on_front`) statt eines eigenen Kartentyps – die Rückseite ist
identisch zur normalen Vokabelkarte, nur die Vorderseite unterscheidet sich
(PDF-Template: neuer Zweig in `templates/cards.html.j2` für `cell.type ==
"vocab"`, analog zum bestehenden `image_uri`-Fallback bei Radicals). Landet
im Frontend über denselben `field_overrides`-Mechanismus wie „Felder manuell
anpassen" – ein generiertes Bild wird als `image_data_uri` in
`fieldOverrides[id]` gespeichert, kein separater Persistenz-Weg nötig.

Anki-seitig bekommt das `vocab`-Notiztyp-Modell (`anki_export.py`) ein
drittes Template „Bild" zusätzlich zu „Bedeutung"/„Lesung": über Mustache-
Bedingungen (`{{#ImageHtml}}…{{/ImageHtml}}` für das neue Template,
`{{^ImageHtml}}…{{/ImageHtml}}` – die **Inversion** – für die beiden
bestehenden) entsteht für eine Bildkarte **nur** die Bild→Lesung-Karte, die
beiden Text-Karten bekommen eine leere Vorderseite und werden von Anki
automatisch übersprungen (Standard-Anki-Verhalten: leere Vorderseite ⇒ keine
Karte) – kein zusätzlicher Python-seitiger Verzweigungscode nötig, nur
Template-Bedingungen.

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
`dictionary_form`, `reading`, grammatikalischer `function`, kurzer `meaning`,
`is_content_word`) statt Markdown-Tabellen-Parsing. Ergebnisse werden pro
Satz unter `.cache/gemini/` gecacht (Schlüssel: Modell + Satztext).
`_reconcile_gemini_tokens()` prüft, ob Geminis Tokens zum Original-Satz
rekonstruieren – dabei bewusst **nicht** strikt zeichengleich: Gemini lässt
das abschließende Satzzeichen (｡ 。 ! ?) trotz expliziter Prompt-Anweisung
regelmäßig weg, eine rein strikte Prüfung hätte praktisch jeden normalen (auf
。 endenden) Satz verworfen. Die Funktion ergänzt einen fehlenden reinen
Satzzeichen-Rest am Ende als eigenes Token und ist generisch für Tupel
beliebiger Breite (3er-Tupel im alten Aus-Text-Kontext gibt es nicht mehr,
der KI-Modus nutzt 6er-Tupel `(surface, lemma, reading, function, meaning,
is_content_word)`).

**`is_content_word` verhindert falsche Wörterbuch-Treffer bei Partikeln:**
JMdict indiziert Wörter über ihre Lesung – kurze Kana-Folgen wie „は" haben
dort oft einen zufälligen Homograph-Eintrag als eigenständiges Wort (z. B.
„は" = „Flügel", von 羽), unabhängig von der Themen-Partikel は, die dieselbe
Lautung hat. Eine reine Lesungs-Suche kann das nicht unterscheiden und würde
die Partikel fälschlich mit der falschen Wortbedeutung anzeigen. Gemini
liefert pro Token deshalb `is_content_word` (echte Vokabel: Nomen/Verb/
Adjektiv/Adverb vs. Partikel/Kopula/Hilfsverb/Satzzeichen) – nur bei
`is_content_word: true` versucht `annotate_text_ai()` überhaupt einen
WaniKani-/JMdict-/KI-Treffer; alles andere bleibt normaler, nicht anklick-
barer Text (die Bemerkung-Spalte erklärt die grammatikalische Funktion).

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

**PDF-/Bild-Import** (`pdf_import.py`, Endpunkt `POST /api/text-extract`):
zweistufig statt „alles auf einmal mit Gemini", damit Text mit Textlayer
kostenlos bleibt. [PyMuPDF](https://pymupdf.readthedocs.io/) (`fitz`, reines
Python-Wheel ohne System-Abhängigkeit wie poppler-utils) liest jede PDF-Seite
zunächst direkt aus (`page.get_text()`); nur Seiten, bei denen das (fast)
nichts liefert – gescannte Seiten ohne Textlayer – werden als Bild gerendert
(`page.get_pixmap(dpi=200)`) und per `gemini_client.transcribe_image()`
transkribiert (dieselbe Gemini-Vision-Anfrage wie für direkt hochgeladene
Bilder, `inlineData`/Base64 im `generateContent`-Request, kein
`responseSchema` nötig, da reiner Text statt strukturiertem JSON). OCR-Ergebnisse
werden wie die Satzanalyse unter `.cache/gemini_ocr/` gecacht (Schlüssel:
Modell + Bild-Hash). Fehl-soft auf Seiten-/Bild-Ebene: scheitert OCR für eine
einzelne Seite oder fehlt schlicht der Gemini-Key, wird nur diese Seite
übersprungen statt das ganze Dokument abzubrechen; Bilder ohne Key liefern
dagegen einen klaren Fehler (ein Bild hat per Definition keinen Textlayer,
ohne OCR gäbe es sonst stillschweigend gar keinen Text). Ein Deckel von 30
Seiten pro PDF und 20 MB pro Datei (`app.config["MAX_CONTENT_LENGTH"]` in
`webapp.py`, lehnt zu große Uploads schon auf Werkzeug-Ebene ab, bevor der
komplette Body in den Speicher gelesen wird) verhindert, dass ein
versehentlich hochgeladenes sehr großes Dokument den Server minutenlang
blockiert. Der extrahierte Text landet unverändert in derselben Textarea wie
manuell eingefügter Text – „Schnell" und „Mit KI" behandeln ihn identisch,
ohne eigenen Codepfad fürs Datei-Upload.

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
pip install -r requirements.txt -r requirements-web.txt pytest
pytest
```

(Die Web-Requirements sind seit dem Multi-User-Fundament nötig, weil
`webapp.py` jetzt beim Import auch `Flask-SQLAlchemy`/`Flask-Login`
braucht – `tests/conftest.py` zeigt `DATABASE_URL` dabei automatisch auf eine
temporäre SQLite-Datei, keine laufende Postgres-Instanz nötig zum Testen.)

Abgedeckt sind die Kernfunktionen `pick_example_vocab`, `mirror_backside`,
`paginate`, `build_card`, `strip_markup`, `lemmatize_text`/`annotate_text`
(Aus-Text-Modus, inkl. Wörterbuch-Fallback) sowie `annotate_text_ai` (KI-Modus,
Satz-Tabelle inkl. Fehlerfälle), `dictionary.py`
(JMdict-Download/-Index, DeepL-Übersetzung), `gemini_client.py`
(Satzanalyse, Caching, 429-Backoff, Fehlerfälle, Bild-Transkription),
`pdf_import.py` (Textlayer-Extraktion, OCR-Fallback für Scans/Bilder,
Seiten-Deckel, Fehlerfälle), `card_details_for_ids`/`_apply_field_overrides`
(Felder-manuell-anpassen-Dialog, inkl. defensivem Ignorieren unbekannter
Feldnamen), `webapp.api_card_detail`/`api_translate` (inkl. Zielsprache aus
den Einstellungen), `gemini_client.generate_image` (Bildkarten, inkl.
Fehlerfälle und dass NICHT gecacht wird), `anki_export`-Vokabelmodell (drei
Templates, Bild-Feld/Bedeutung-Flag nur bei gesetztem Bild), `KanaCard`-Bau sowie das
Auflösen bereits exportierter bzw. manuell als bekannt markierter Subject-/
Dictionary-IDs, die Wortlisten-Aggregation und die Anki-Notiztypen im
Web-Frontend (`webapp._already_exported_ids`, `webapp.load_known`/
`_upsert_known_word`, `webapp.api_wortliste`, `anki_export._kana_note`). Für
den Multi-User-Umbau zusätzlich: `crypto.py` (Verschlüsselungs-Roundtrip,
Fehlerfälle bei fehlendem/rotiertem Master-Key), `models.py` (Schema-
Constraints wie Unique-per-User, Cascade-Delete, zusammengesetzter
Primärschlüssel bei `KanaCard`), `auth.py` (Signup/Login/Logout, inkl.
Ablehnung doppelter E-Mails und falscher Passwörter), Cross-Tenant-
Isolationstests für Settings/Custom-/Kana-Cards/Jobs (IDOR-Schutz) sowie
`kanji_cards._make_client` sowie mehrere `/api/*`-Endpunkte (verifizieren,
dass der WaniKani-Token explizit pro Nutzer durchgereicht wird statt über
die prozessglobale `WANIKANI_API_TOKEN`-Variable).

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
