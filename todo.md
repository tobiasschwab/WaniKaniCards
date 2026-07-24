# TODO

Konventionen: `- [ ]` offen, `- [x]` erledigt. Neue Einträge unten am Ende
ihres Datumsabschnitts anfügen; neuer Tag → neue `##`-Überschrift (neuestes
Datum oben).

## 2027-06-24

- [x] Textmodus: Wenn eine Karte als bekannt markiert wird, sollen sich die
      Prozentpunkte (Satz + Gesamt) sofort aktualisieren, nicht erst nach
      erneutem Analysieren.
- [x] Bug: "Tabelle leeren" funktioniert nicht mehr.
- [x] Titel "Komposition: <Teile>" durch "Neue Karten" ersetzen.
- [ ] Bei den Druckoptionen (Duplex) gibt es Überlappungen im Layout.
      (Konnte in mehreren Viewport-Breiten/Locales nicht reproduziert werden –
      Screenshot nötig, um die genaue Stelle zu finden.)
- [x] Wortliste: Einträge wie `aikana_4ab7d9b1dba5ad9d`/`kana_ad3aa4bf97f2aa1a`
      statt des tatsächlichen Worts mit Bedeutung anzeigen.
- [ ] Projekt sourcen-mäßig umstrukturieren: aktuell liegen alle `.py`-Dateien
      auf oberster Ebene – in eine Ordnerstruktur nach Best Practices bringen
      (MVC-ähnliches Layout für eine Flask-App).
- [x] Kommandozeilenaufrufe (`kanji_cards.py`-CLI) entfernen – ursprünglicher
      Grundgedanke vor der Webapp, wird nicht mehr gebraucht.
- [x] Diese Datei in ein sauberes Markdown-TODO-Format bringen.
