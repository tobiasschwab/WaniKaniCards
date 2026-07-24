"""base.py – das `LanguagePack`-Interface.

Jede Zielsprache bekommt eine `LanguagePack`-Instanz, die beschreibt, welche
Fähigkeiten sie hat (externe Lernstufen-Quelle wie WaniKani? Lesungen wie
Onyomi/Kunyomi? Furigana? ein eigener Offline-Tokenizer?). `webapp.py` und
das Frontend fragen diese Flags ab, um Modi ein-/auszublenden, statt
Sprachnamen im Code zu vergleichen (`if target_lang == "ja"` soll außerhalb
von `languages/` möglichst nicht mehr vorkommen).

Bewusst KEINE Neuimplementierung der bestehenden WaniKani-/Janome-/JMdict-
Logik: `JapanesePack` (siehe `languages/japanese.py`) ist ein dünner Wrapper
um die unverändert weiterlaufenden Module `kanji_cards.py`/`dictionary.py`.
Der Wert dieser Schicht liegt darin, dass der Rest der App diese Fähigkeiten
über ein einheitliches Interface abfragt, statt Japanisch-Annahmen fest
einzubauen.
"""
from __future__ import annotations

from dataclasses import dataclass, field


# Anzeigenamen der Sprache in verschiedenen Muttersprachen - ergänzt bei
# Bedarf; fällt für unbekannte Kombinationen auf den ISO-Code selbst zurück
# (siehe LanguagePack.display_name()).
_DISPLAY_NAMES: dict[str, dict[str, str]] = {
    "ja": {"de": "Japanisch", "en": "Japanese"},
    "en": {"de": "Englisch", "en": "English"},
    "es": {"de": "Spanisch", "en": "Spanish"},
    "fr": {"de": "Französisch", "en": "French"},
    "it": {"de": "Italienisch", "en": "Italian"},
    "pt": {"de": "Portugiesisch", "en": "Portuguese"},
    "nl": {"de": "Niederländisch", "en": "Dutch"},
    "pl": {"de": "Polnisch", "en": "Polish"},
    "ru": {"de": "Russisch", "en": "Russian"},
    "zh": {"de": "Chinesisch", "en": "Chinese"},
    "ko": {"de": "Koreanisch", "en": "Korean"},
    "tr": {"de": "Türkisch", "en": "Turkish"},
    "sv": {"de": "Schwedisch", "en": "Swedish"},
    "de": {"de": "Deutsch", "en": "German"},
}


@dataclass
class LanguagePack:
    """Basisklasse/Default-Implementierung - `GenericPack` nutzt sie direkt,
    `JapanesePack` überschreibt die Capability-Flags und Methoden, die auf
    echter WaniKani-/Janome-/JMdict-Funktionalität aufsetzen."""

    code: str

    # Externe, kuratierte Lernstufen-Quelle wie WaniKani (Level-Stapel/Suche/
    # Komposition-Modus im Frontend). Ohne das: nur Custom-Cards/Wortliste/
    # Text-Import verfügbar.
    has_content_provider: bool = False
    # Beschriftungen für zusätzliche Lesungs-Spalten in der Karten-/Anki-
    # Feldstruktur, z. B. ["Onyomi", "Kunyomi"] bei Japanisch. Leer = keine
    # gesonderten Lesungsfelder (die meisten Sprachen brauchen das nicht).
    reading_labels: list[str] = field(default_factory=list)
    # Furigana-artige Aussprachehilfe über dem Wort (steuert u. a. den
    # Hinweistext im OCR-/Text-Import-Prompt, siehe gemini_client.py).
    has_furigana: bool = False
    # Eigener Offline-Satz-/Wort-Tokenizer (Janome bei Japanisch) für den
    # schnellen, Gemini-freien Text-Annotate-Modus (`/api/text-annotate`).
    # Ohne das: nur der Gemini-gestützte "KI"-Modus (`/api/text-annotate-ai`)
    # verfügbar, der für jede Sprache funktioniert.
    has_offline_tokenizer: bool = False
    # WanaKana-Bindung im Anki-Export (Romaji-zu-Kana-Tippfeld) - nur für
    # Sprachen mit Kana-Eingabe sinnvoll.
    has_kana_input: bool = False

    def display_name(self, native_lang: str = "de") -> str:
        names = _DISPLAY_NAMES.get(self.code, {})
        return names.get(native_lang) or names.get("en") or self.code.upper()

    def capabilities(self) -> dict[str, object]:
        """Kompaktes Dict fürs Frontend (`GET /api/languages`) - dieselben
        Flags wie oben, aber JSON-serialisierbar unter stabilen Keys."""
        return {
            "code": self.code,
            "has_content_provider": self.has_content_provider,
            "reading_labels": list(self.reading_labels),
            "has_furigana": self.has_furigana,
            "has_offline_tokenizer": self.has_offline_tokenizer,
            "has_kana_input": self.has_kana_input,
        }
