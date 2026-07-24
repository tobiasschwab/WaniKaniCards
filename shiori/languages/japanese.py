"""japanese.py – der einzige vollausgestattete `LanguagePack`.

Bewusst KEIN Rewrite von `kanji_cards.py`/`dictionary.py`: dieser Pack ist
nur die Capability-Deklaration ("Japanisch hat WaniKani, Onyomi/Kunyomi,
Furigana, Janome-Tokenizer, Kana-Eingabe") - die eigentliche Logik bleibt
unverändert in den bestehenden Modulen, die weiterhin direkt von webapp.py
aus aufgerufen werden (`kc.resolve_level()`, `kc.annotate_text()`, …). Ein
vollständiges Verschieben der ~2300 Zeilen wäre ein hohes Risiko ohne echten
Mehrwert, solange Japanisch der einzige Pack mit dieser Tiefe ist.
"""
from __future__ import annotations

from .base import LanguagePack

JapanesePack = LanguagePack(
    code="ja",
    has_content_provider=True,
    reading_labels=["Onyomi", "Kunyomi"],
    has_furigana=True,
    has_offline_tokenizer=True,
    has_kana_input=True,
)
