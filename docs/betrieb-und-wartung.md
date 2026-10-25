# Betrieb, Wartung, Backup (nur für den Administrator)

## Monatliche Routine (≈ 15 Minuten)

1. `superkugel_admin.py usage` – Nutzung und geschätzte Kosten ansehen.
2. OpenAI-Dashboard: Guthaben > 2 $? Sonst aufladen ✋.
3. Kurztest: „Alexa, öffne Superkugel“ → eine Frage → „Stopp“. (Ruf sie an oder teste beim Besuch.)
4. Alarm-Mails des Monats durchsehen.
5. Einmal im Quartal: `pip-audit -r src/requirements.txt`, ggf. Abhängigkeiten aktualisieren, Tests laufen lassen, neu deployen.

## Tagesaktuelles und Sendungen

| Aufgabe | Befehl / Ort |
|---|---|
| Nachrichten/Wetter/Sendungen sofort aktualisieren | `superkugel_admin.py refresh` |
| Lieblingssendung hinzufügen / anzeigen / entfernen | `superkugel_admin.py podcast add <RSS-URL> …` / `podcast list` / `podcast remove <show_id>` |
| Websuche abschalten | `WebSearchDailyLimit=0` in `infra/samconfig.toml`, dann `sam deploy` |
| Limits ändern | `WebSearchDailyLimit`, `DailyCostLimitUsd` (max. 0,95), `MonthlyCostLimitUsd` (max. 14,50) |
| Wohnort ändern | `UserCity`, `UserRegion`, `UserLat`, `UserLon` in `infra/samconfig.toml` (nur lokal) |
| Suchen heute | `superkugel_admin.py usage` zeigt KI-Anfragen und Websuchen |

Alarm-Mails: Tageskosten > 0,60 $, ≥ 3 langsame Antworten (> 6,5 s) pro Stunde, Vorname in einer Websuche,
wiederholte Abruffehler (Nachrichten/Wetter/Feeds).

## Betriebsmodus (Fernschalter)

```bash
.venv/Scripts/python scripts/superkugel_admin.py mode
```
```bash
.venv/Scripts/python scripts/superkugel_admin.py mode audiobooks_only
```
| Modus | Verhalten |
|---|---|
| `normal` | alles an |
| `audiobooks_only` | KI aus („Ratschen geht gerade nicht, aber Hörbücher …“) – z. B. bei OpenAI-Problemen oder Kostenspitzen |
| `maintenance` | Skill sagt nur „Die Superkugel macht gerade eine kleine Pause. Alexa funktioniert ganz normal weiter.“ |

Wirkt nach spätestens 60 Sekunden (Cache). Ist der Parameter-Speicher kurz nicht erreichbar, gilt der zuletzt gelesene Wert weiter (nach einem Kaltstart ohne Verbindung: `normal`). Stopp/Pause funktionieren in jedem Modus.

## Typische Probleme (Admin)

| Symptom | Ursache prüfen | Lösung |
|---|---|---|
| „Das klappt gerade leider nicht“ bei jeder Frage | Logs: `llm_error` mit `kind` | `auth` → Schlüssel erneuern (Setup §3.4); `quota` → Guthaben aufladen; `timeout` → OpenAI-Status prüfen, ggf. `OPENAI_MODEL` wechseln |
| „Für heute haben wir schon sehr viel geratscht“ | Tageslimit erreicht | `usage` prüfen; Limit in samconfig erhöhen oder bis morgen warten |
| Alexa: „Problem mit der Antwort des Skills“ | Lambda-Fehler (Alarm-Mail) | CloudWatch Logs `/aws/lambda/superkugel-skill`, Ereignis `unhandled_error` |
| Hörbuch startet nicht | Logs: `playback_failed` | Datei in S3 vorhanden? `list`; Endpoint/Region; MP3-Format |
| Skill reagiert gar nicht mehr | Developer Console → Test → „Development“ noch aktiv? Endpoint gesetzt? | wieder aktivieren; Interaction Model neu bauen |
| Neues Hörbuch nicht gefunden | `inbox`-Log `sync-log.jsonl`, Ordner `fehler/` | Meldung lesen, ggf. `book.json` ergänzen und erneut in den Eingang legen |
| Falscher Titel wird gespielt | Titel zu ähnlich | `book.json` mit eindeutigerem Titel/Serie, neu importieren |

Logs enthalten **keine** Gesprächsinhalte, Titel oder Amazon-IDs – nur Ereignisnamen, Fehlertypen,
Tokenzahlen, Zeiten und im Ereignis `request_done` die pseudonyme Kennung `user_hash` (SHA-256, gekürzt;
wird für `reset-progress --user-hash` gebraucht).

## Daten und Datenschutz

| Daten | Ort | Aufbewahrung | Löschen |
|---|---|---|---|
| Gesprächsverlauf | Alexa-Sitzung + DynamoDB | 30 Min. (TTL) | „Vergiss unser Gespräch“ oder `RESUME_WINDOW_S=0` (dann gar nicht gespeichert) |
| Hörbuchfortschritt (pro Echo-Gerät) | DynamoDB | dauerhaft | `reset-progress` |
| Nutzungszähler (nur Zahlen) | DynamoDB | dauerhaft | Tabelle `pk=USAGE` |
| Gesprächsinhalte bei OpenAI | OpenAI | `store: false`; API-Aufbewahrung laut OpenAI-Richtlinie (Missbrauchsprüfung) | – |
| Sprachaufnahmen | Amazon (in **deinem** Konto) | laut Alexa-Datenschutzeinstellungen | deine Alexa-App → Alexa-Datenschutz; automatisches Löschen empfohlen (mit ihr abgesprochen ✋) |

Kein Langzeitgedächtnis implementiert (bewusst: datensparsam). 

## Backup und Wiederherstellung

- **DynamoDB**: Point-in-Time-Recovery ist bewusst **aus** – es würde Gesprächstexte 35 Tage lang aufbewahren.
  Stattdessen monatlich ein On-Demand-Backup (enthält höchstens die letzten 30 Minuten Gespräch):
  `aws dynamodb create-backup --table-name superkugel --backup-name superkugel-JJJJ-MM --profile superkugel-admin`.
  Wiederherstellen: AWS-Konsole → DynamoDB → Backups → Restore in neue Tabelle, dann `TABLE_NAME` umstellen.
  Ohne Backup gehen bei Datenverlust nur Lesezeichen verloren; die Bibliothek lässt sich aus den Originalen neu importieren.
- **Hörbuchdateien**: Originale (Thalia-ZIPs im Ordner `fertig/`) aufbewahren – sie sind das eigentliche Backup. Erneuter Import ist idempotent.
- **Code/Konfiguration**: Git-Repository; `samconfig.toml` und `.env` separat sicher aufbewahren (enthalten keine Geheimnisse außer Adressen).
- **Stack versehentlich gelöscht**: Tabelle und Bucket bleiben erhalten (`Retain`). Neu deployen; ggf. vorhandene Ressourcen per Import übernehmen.
- **OpenAI-Schlüssel kompromittiert**: Im OpenAI-Dashboard widerrufen, neuen Schlüssel per `aws ssm put-parameter --overwrite` setzen; der Skill liest ihn nach dem ersten Anmeldefehler automatisch neu.
