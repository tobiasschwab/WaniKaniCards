"""languages – Abstraktionsschicht für die Multi-Language-Architektur.

Kapselt alles, was sich zwischen Zielsprachen unterscheidet (Content-Quelle,
Lesungen/Furigana, Wörterbuch-Backend, Text-Tokenisierung, Anki-Export-
Konfiguration) hinter einem gemeinsamen `LanguagePack`-Interface (siehe
`languages.base`). Japanisch (`languages.japanese.JapanesePack`) ist der
einzige vollausgestattete Pack – er bündelt die bestehende WaniKani-/Janome-/
JMdict-Integration aus `kanji_cards.py`/`dictionary.py` unverändert hinter
diesem Interface. Jede andere Zielsprache bekommt automatisch den
`languages.generic.GenericPack` (kein WaniKani-Äquivalent, Gemini als
universeller Wörterbuch-Fallback) – siehe README "Multi-Language-
Architektur" für das Gesamtkonzept.

`get_pack(code)` aus `languages.registry` ist der einzige Einstiegspunkt, den
der Rest der App braucht.
"""
