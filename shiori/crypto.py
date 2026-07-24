#!/usr/bin/env python3
"""crypto.py – Verschlüsselung ruhender Secrets (WaniKani-Token, DeepL-/
Gemini-Key) pro Nutzer.

Im bisherigen Single-Tenant-Betrieb lagen diese Keys im Klartext in
settings.json – akzeptabel, weil nur der Betreiber selbst betroffen war. Bei
einer öffentlichen Multi-User-Instanz betrifft ein kompromittiertes Backup/
eine DB-Kopie plötzlich fremde Personen, deshalb symmetrische Verschlüsselung
(Fernet) mit einem serverseitigen Master-Key statt Klartext.
"""
from __future__ import annotations

import os

from cryptography.fernet import Fernet, InvalidToken


class SecretCryptoError(RuntimeError):
    """Verständlicher Fehler ohne Stacktrace bei fehlendem/ungültigem Master-Key."""


def _get_fernet() -> Fernet:
    key = os.environ.get("WKCARDS_SECRET_KEY")
    if not key:
        raise SecretCryptoError(
            "Kein WKCARDS_SECRET_KEY gesetzt – für Multi-User-Betrieb Pflicht "
            "(verschlüsselt WaniKani-Token/DeepL-/Gemini-Keys ruhend in der "
            "Datenbank). Erzeugen: python -c \"from crypto import generate_master_key; "
            "print(generate_master_key())\""
        )
    try:
        return Fernet(key.encode("utf-8") if isinstance(key, str) else key)
    except (ValueError, TypeError) as exc:
        raise SecretCryptoError(f"WKCARDS_SECRET_KEY ist kein gültiger Fernet-Key: {exc}") from exc


def encrypt_secret(plaintext: str | None) -> str | None:
    """Klartext verschlüsseln – leere/None-Werte bleiben None (kein Key
    hinterlegt), damit `if not settings.deepl_key_enc` weiterhin funktioniert."""
    if not plaintext:
        return None
    return _get_fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_secret(ciphertext: str | None) -> str | None:
    """Verschlüsselten Wert entschlüsseln.

    Fail-soft (gibt `None` statt eine Exception zu werfen) bei kaputten Werten
    oder einem Wert, der mit einem inzwischen rotierten Master-Key
    verschlüsselt wurde – der Nutzer sieht dann nur „kein Key hinterlegt" und
    kann ihn neu eingeben, statt dass die ganze Seite abstürzt."""
    if not ciphertext:
        return None
    try:
        return _get_fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        return None


def generate_master_key() -> str:
    """Hilfsfunktion für Setup/CLI: einen neuen Master-Key erzeugen (einmalig,
    dann als WKCARDS_SECRET_KEY hinterlegen – ein Rotieren macht alle
    bestehenden verschlüsselten Secrets unlesbar, siehe `decrypt_secret()`).

    Braucht Python 3 + `cryptography`. Auf Hosts ohne Python 3 (z. B. NAS mit
    nur Python 2) einen gleichwertigen Key ohne dieses Modul erzeugen – ein
    Fernet-Key ist schlicht 32 Zufallsbytes, URL-safe base64-kodiert:

        openssl rand -base64 32 | tr '+/' '-_'
    """
    return Fernet.generate_key().decode("ascii")
