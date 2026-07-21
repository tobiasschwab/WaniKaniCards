"""generic.py – Fallback-`LanguagePack` für jede Sprache ohne eigene
Spezialisierung (alles außer Japanisch, aktuell).

Kein WaniKani-Äquivalent, keine gesonderten Lesungsfelder, kein Offline-
Tokenizer - nutzbare Modi sind Custom-Cards (Frei erstellen), Wortliste und
der Gemini-gestützte Text-Import/"KI"-Modus (`/api/text-annotate-ai`, siehe
gemini_client.py – Prompts sind dort auf Ziel-/Muttersprache parametrisiert,
nicht mehr fest auf Japanisch/Deutsch). Wörterbuch-Lookups (z. B. für
Dictionary-Karten aus dem Text-Modus) laufen über Gemini statt über ein
sprachspezifisches Wörterbuch wie JMdict (siehe README "Multi-Language-
Architektur", Entscheidung 3)."""
from __future__ import annotations

from languages.base import LanguagePack


def generic_pack(code: str) -> LanguagePack:
    """Ein `GenericPack` für einen beliebigen ISO-639-1-Code - alle
    Capability-Flags bleiben auf den (sprachneutralen) Defaults."""
    return LanguagePack(code=code)
