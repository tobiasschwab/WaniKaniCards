# Backup-Strategie

Shiori hält Nutzerdaten an zwei Stellen: der **Postgres-Datenbank**
(Accounts, Settings, Custom-/Kana-Cards, Job-Metadaten – siehe `models.py`)
und den **generierten Dateien** (PDFs/APKGs, entweder lokal unter
`data/output/` oder in Object Storage, siehe `storage.py`). Beide brauchen
eine Backup-Strategie, bevor echte Nutzerdaten im Spiel sind.

## Postgres

Die Datenbank ist die einzige Quelle für Accounts und alle privaten
Nutzerinhalte (WaniKani-Token, Custom-Karten, gelernte Wörter, Job-Historie)
– ein Datenverlust hier ist nicht aus anderen Quellen rekonstruierbar.

### Verwalteter Postgres-Dienst (empfohlen für Produktion)

Läuft `DATABASE_URL` gegen einen verwalteten Dienst (RDS, Neon, Supabase,
Render, …), nutze dessen eingebautes Backup-Feature:

- **Point-in-Time Recovery (PITR)** aktivieren, falls verfügbar – erlaubt
  Wiederherstellung auf einen beliebigen Zeitpunkt, nicht nur auf den
  letzten Snapshot.
- Automatische tägliche Snapshots mit einer Aufbewahrungsfrist von
  mindestens 7, besser 30 Tagen.
- Snapshots regelmäßig (z. B. quartalsweise) tatsächlich zurückspielen und
  gegen ein Test-System prüfen – ein Backup, das nie restauriert wurde, ist
  keine verifizierte Garantie.

### Selbst gehosteter `db`-Service (`docker-compose.yml`)

Der mitgelieferte `db`-Service ist für Self-Hosting/lokale Entwicklung
gedacht und bringt **kein** automatisches Backup mit. Für einen echten
Betrieb selbst einrichten, z. B.:

```bash
# Täglicher Dump, außerhalb des Containers ablegen (z. B. per Cron)
docker compose exec -T db pg_dump -U shiori shiori | gzip > backup-$(date +%F).sql.gz

# Wiederherstellung (in ein frisches, leeres db-Volume)
gunzip -c backup-2026-01-15.sql.gz | docker compose exec -T db psql -U shiori shiori
```

Empfehlungen:

- Dumps **außerhalb** des Docker-Volumes/Hosts ablegen (Object Storage,
  separater Backup-Host) – ein Backup auf derselben Platte wie die Live-DB
  schützt nicht vor Hardware-Ausfall.
- Aufbewahrung: mind. 7 tägliche + 4 wöchentliche + 3 monatliche Stände
  (klassisches Generationsprinzip), älter automatisch löschen.
- `pg_dump` läuft online (kein Downtime nötig), ist aber ein logischer
  Dump – bei sehr großen Datenmengen ggf. auf `pg_basebackup`/WAL-Archivierung
  für PITR umsteigen.

## Generierte Dateien (PDFs/APKGs)

Diese Dateien sind **reproduzierbar** – sie lassen sich aus den in Postgres
gespeicherten Job-Parametern (`Job.params`) plus den WaniKani-/Custom-/
Kana-Card-Daten jederzeit neu rendern. Ein Backup ist daher optional, ihr
Verlust ist kein Datenverlust im eigentlichen Sinn (nur ein "Nutzer muss den
Export erneut anstoßen").

Trotzdem sinnvoll, je nach Speicher-Backend:

- **Lokales Disk** (`data/output/`, Standard ohne `S3_BUCKET`): liegt im
  selben `./data`-Volume wie die SQLite-Fallback-DB – bei Self-Hosting mit
  Postgres separat, ein einfaches `rsync`/Snapshot des Host-Ordners reicht.
- **S3/MinIO** (`S3_BUCKET` gesetzt): Bucket-Versionierung aktivieren, falls
  versehentliches Löschen/Überschreiben ein Risiko ist; ansonsten trägt der
  Objekt-Storage-Anbieter selbst schon Redundanz (z. B. S3 repliziert
  standardmäßig über mehrere Availability Zones).
- Empfohlen unabhängig vom Backend: eine **Auto-Löschung nach N Tagen**
  (Lifecycle-Regel bei S3, bzw. ein Cron-Job bei lokalem Disk) für alte
  Exporte – reduziert Speicherbedarf und die Menge an (potenziell privaten,
  z. B. Lerninhalte enthaltenden) Dateien, die überhaupt gesichert werden
  müssten.

## Secrets (`WKCARDS_SECRET_KEY`, `WKCARDS_SESSION_SECRET`)

Diese Umgebungsvariablen sind **keine** Backup-Kandidaten im klassischen
Sinn, aber ihr Verlust ist fatal: `WKCARDS_SECRET_KEY` ist der Fernet-
Master-Key, mit dem alle gespeicherten WaniKani-/DeepL-/Gemini-Keys
verschlüsselt sind (siehe `crypto.py`) – geht er verloren, sind alle
gespeicherten Secrets aller Nutzer unwiderruflich unlesbar (die Nutzer
müssten ihre Keys erneut eingeben). Getrennt vom Datenbank-Backup an einem
sicheren Ort aufbewahren (Secret-Manager des Hosting-Anbieters, Passwort-
Manager des Betreibers) – **nicht** im selben Postgres-Dump, da sonst ein
kompromittierter DB-Dump gleichzeitig den Schlüssel zum Entschlüsseln
enthält.
