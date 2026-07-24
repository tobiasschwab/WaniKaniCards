#!/bin/sh
# create_secret.sh – erzeugt einen WKCARDS_SECRET_KEY (Fernet-Master-Key zum
# Ver-/Entschlüsseln der in der Datenbank gespeicherten API-Keys, siehe
# crypto.py) ganz ohne Python 3 – nur mit openssl (siehe README, Abschnitt
# "Mit Docker starten").
#
# Aufruf:
#   ./create_secret.sh
#
# Den ausgegebenen Key als WKCARDS_SECRET_KEY hinterlegen, bevor
# "docker compose up" läuft. Aufschreiben/sichern - bei Verlust sind bereits
# gespeicherte Keys (WaniKani-Token, DeepL-/Gemini-Keys) unlesbar.
export WKCARDS_SECRET_KEY=$(openssl rand -base64 32 | tr '+/' '-_')
echo "$WKCARDS_SECRET_KEY"
