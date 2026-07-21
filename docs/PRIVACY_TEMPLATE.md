# Datenschutzerklärung – VORLAGE

> **Dies ist eine unverbindliche Vorlage, keine Rechtsberatung.** Vor dem
> Betrieb einer öffentlichen Instanz mit echten Nutzerdaten muss dieser Text
> von einer Juristin/einem Juristen geprüft und an die tatsächliche
> Rechtsform, den Serverstandort, die Nutzerbasis (z. B. EU-Nutzer → DSGVO)
> und die konkret eingesetzten Dienste angepasst werden. Platzhalter in
> `[eckigen Klammern]` müssen vor Veröffentlichung ausgefüllt werden.

## 1. Verantwortlicher

[Name/Firma], [Anschrift], [Kontakt-E-Mail]

## 2. Welche Daten werden verarbeitet?

| Kategorie | Beispiel | Zweck |
|---|---|---|
| Account-Daten | E-Mail-Adresse, gehashtes Passwort | Login, Kontoverwaltung |
| API-Schlüssel (verschlüsselt gespeichert) | WaniKani-API-Token, DeepL-/Gemini-Key | Abruf der Lerninhalte bzw. optionaler KI-/Übersetzungsfunktionen im Namen des Nutzers |
| Lerninhalte | eigene Karteikarten, als "gelernt" markierte Wörter, Job-/Export-Verlauf | Kernfunktion der App |
| Technische Daten | IP-Adresse (nur für Rate-Limiting, nicht dauerhaft gespeichert), Zeitstempel von Requests in Server-Logs | Missbrauchsschutz, Fehlerdiagnose |

Die App speichert **keine** Zahlungsdaten und **keine** besonderen
Kategorien personenbezogener Daten (Art. 9 DSGVO).

## 3. Rechtsgrundlage

Verarbeitung zur Vertragserfüllung (Art. 6 Abs. 1 lit. b DSGVO – Bereitstellung
des angefragten Dienstes) bzw. auf Basis berechtigten Interesses (Art. 6
Abs. 1 lit. f DSGVO) für Missbrauchsschutz/Sicherheitsmaßnahmen
(Rate-Limiting, Logging).

## 4. Weitergabe an Dritte

API-Schlüssel, die Nutzer selbst hinterlegen (BYOK – "Bring Your Own Key"),
werden ausschließlich verwendet, um in ihrem Namen Anfragen an die
jeweiligen Dienste zu stellen:

- **WaniKani** (api.wanikani.com) – Abruf von Lerninhalten.
- **Google Gemini** (falls hinterlegt) – KI-Funktionen (Satzanalyse,
  Sprachausgabe, Bildgenerierung).
- **DeepL** (falls hinterlegt) – Übersetzungsfunktion.

Diese Anbieter erhalten dabei den vom Nutzer selbst eingegebenen Text/Inhalt,
nicht aber Account-Zugangsdaten (E-Mail/Passwort) dieser App. [Betreiber:
prüfen, ob mit diesen Anbietern ein Auftragsverarbeitungsvertrag (AVV)
nötig/vorhanden ist.]

Falls Object Storage (S3/MinIO) für generierte PDFs/APKGs genutzt wird:
[Name des Anbieters/Standort eintragen, z. B. "AWS S3, Region eu-central-1"].

## 5. Speicherdauer

- Account-Daten: bis zur Löschung des Kontos durch den Nutzer.
- Generierte Export-Dateien (PDFs/APKGs): [X Tage – falls eine
  Auto-Löschung konfiguriert ist, siehe README "Object Storage"] bzw. bis
  zur manuellen Löschung durch den Nutzer.
- Server-Logs (inkl. `user_id`-Kontext, siehe README "Strukturiertes
  Logging"): [Aufbewahrungsfrist eintragen, z. B. 30 Tage], danach
  automatische Rotation/Löschung.

## 6. Rechte der betroffenen Person

Nutzer haben nach DSGVO das Recht auf Auskunft (Art. 15), Berichtigung
(Art. 16), Löschung (Art. 17), Einschränkung der Verarbeitung (Art. 18),
Datenübertragbarkeit (Art. 20) sowie Widerspruch (Art. 21). [Betreiber:
konkreten Prozess ergänzen – z. B. "Konto-Löschung über Einstellungen"
oder "Anfrage per E-Mail an ..."; technisch unterstützt `models.py` bereits
eine vollständige Löschung aller Zeilen zu einem `user_id` per Kaskade.]

## 7. Beschwerderecht

Nutzer haben das Recht, sich bei einer Datenschutz-Aufsichtsbehörde zu
beschweren. [Zuständige Behörde je nach Sitz des Betreibers eintragen.]

## 8. Kontakt für Datenschutzanfragen

[E-Mail-Adresse eintragen]

---
*Letzte Aktualisierung: [Datum]. Diese Vorlage ersetzt keine anwaltliche
Prüfung.*
