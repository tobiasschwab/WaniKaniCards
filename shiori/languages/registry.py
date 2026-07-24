"""registry.py – `get_pack(code)`: der einzige Einstiegspunkt in dieses
Package für den Rest der App."""
from __future__ import annotations

from .base import LanguagePack
from .generic import generic_pack
from .japanese import JapanesePack

_SPECIALIZED: dict[str, LanguagePack] = {
    "ja": JapanesePack,
}

# Sprachen, die in der UI als Zielsprache angeboten werden (Sprachwechsler,
# siehe web/app.js) - unabhängig davon, ob sie einen spezialisierten Pack
# haben oder auf GenericPack zurückfallen. Reine Kuratierungsliste, keine
# technische Einschränkung: `get_pack()` funktioniert für jeden Code.
SUPPORTED_TARGET_LANGS = (
    "ja", "en", "es", "fr", "it", "pt", "nl", "pl", "ru", "zh", "ko", "tr", "sv",
)


def get_pack(code: str) -> LanguagePack:
    """Spezialisierten Pack liefern, falls vorhanden, sonst den generischen
    Fallback (siehe `languages.generic.generic_pack`) - JEDER ISO-Code
    funktioniert, auch außerhalb von `SUPPORTED_TARGET_LANGS`."""
    code = (code or "ja").strip().lower()
    return _SPECIALIZED.get(code) or generic_pack(code)
