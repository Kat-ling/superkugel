# Projektstatus – Superkugel

**Stand:** 25.10.2026 · **Version 1.0 (MVP): implementiert, automatisiert getestet, bereitgestellt und im Alltag auf einem
Echo Dot 5 in Betrieb.** Nicht alle Akzeptanztests sind auf dem Gerät abgearbeitet (siehe unten).

## Was läuft

| Bereich | Stand |
|---|---|
| Skill | Alexa Custom Skill „Superkugel“ (de-DE), Entwicklungsmodus auf dem Amazon-Konto des Admins, auf das auch der Echo der Nutzerin registriert ist |
| Backend | AWS SAM-Stack `superkugel` in **eu-north-1** (Stockholm): Lambda python3.14/arm64, DynamoDB, privater S3-Bucket, SSM, CloudWatch-Alarme, SNS |
| Gespräch | OpenAI `gpt-6-luna` (Responses API, `store=false`), Kärntner Färbung, Du-Form mit Vornamen, Stimme Vicki 100 %, Verlauf + 30-Min-Wiederaufnahme, Lückenfüller erst nach 4,5 s |
| Hörbücher | AudioPlayer mit Lesezeichen pro Gerät, Kapitelwechsel, Spulen, Titel-/Genre-Suche mit KI-Rückfall auf die vorhandene Bibliothek |
| Import | Eingangsordner + stündliche Windows-Aufgabe, eigener IAM-Benutzer mit Minimalrechten, Mail bei Import/Fehler |
| Schutz | harte Tages-/Monatskostengrenze, Circuit-Breaker, Fernschalter, Prepaid bei OpenAI, Budget-Warnung im Management-Konto |

Gemessen (25.10.2026, per `aws lambda invoke`): Kaltstart 0,8 s Init + 1,5 s; Gesprächsantwort 3,2 s gesamt
(KI 3,1 s) bei ≈ 0,0001 $ pro Frage. Signierte Audio-Links liefern `206 Partial Content`.

## Tests

- `pytest`: **187 bestanden** (Python 3.14, Windows). Unit- und Integrationstests mit echten Alexa-Request-JSONs,
  gemockter OpenAI-API und moto (DynamoDB/S3/SSM). `ruff`, `cfn-lint --regions eu-north-1`, `pip-audit`: ohne Befund.
- Zwei unabhängige Reviews (Alexa-Konformität, Wiedergabe, Ausfallsicherheit, Sicherheit, Kosten, Bedienbarkeit,
  Import) – alle berechtigten Befunde behoben und mit Regressionstests abgesichert.
- Auf dem Gerät durch den Admin bestätigt: natürliches Gespräch, Pause / Weiter / Zurück.
- Akzeptanzprotokoll: `tests/acceptance/ACCEPTANCE_TESTS.md`.

## Offen

1. Restliche Gerätetests (Kapitelwechsel, Neustart, Ausfallszenarien, Test mit der Stimme der Nutzerin).
2. Zugriffsschlüssel des Admin-Benutzers deaktivieren, wenn gerade nicht deployt wird (wieder aktivierbar).
3. **Version 1.1 (implementiert, Bereitstellung wartet auf Freigabe):** Tagesaktuelles (Nachrichten/Wetter, Websuche
   mit Tageslimit), Lieblingssendungen + freie Mediensuche, „ratschen“, keine Nachfrage nach Antworten,
   Kostengrenzen 1 $/Tag bzw. 15 $/Monat gesamt – `docs/plan-tagesaktuell.md`, `docs/kosten.md`, `docs/datenschutz.md`.
   Wohnort und Einverständnis der Nutzerin liegen vor (nur lokal in `infra/samconfig.toml`).

## Entscheidungen (Details: `docs/architektur.md`)

Ein Skill; eigenes AWS statt Alexa-hosted; eine Tabelle; OpenAI ohne SDK; Bibliothek im Prompt + ein Tool;
nur Alexa-Stimmen (keine externe TTS); signierte URLs mit Selbstheilung; Eingangsordner statt Thalia-Scraping;
harte Sperren im Skill + Prepaid; Region Stockholm, weil die Organisationsrichtlinie (SCP) des Projektkontos nur
diese Region zulässt; Kontomodell: alles über das Admin-Konto, Speicherschlüssel = Hash(Konto + Gerät).

## Risiken

| Risiko | Gegenmaßnahme |
|---|---|
| Amazon ändert Regeln für Skills im Entwicklungsmodus | Alarme, monatlicher Kurztest; Code portabel |
| Echo hängt am Admin-Konto (Einkäufe, Listen, Benachrichtigungen) | Schutzeinstellungen laut Setup §1 |
| Spracherkennung bei starkem Dialekt / unbekanntem Satzanfang | 86 Trägerwörter, geduldiger Fallback; anhand der Praxis ergänzen |
| Feste Befehle landen im Chat-Intent | KI kann per Werkzeug trotzdem abspielen; im Test-Tab prüfbar |
| Import-Automatik nur bei eingeschaltetem, angemeldetem Admin-PC | bewusst einfach gehalten; Mail bei Erfolg/Fehler |
| Kostenschätzung weicht ab | Zähler + Prepaid als harte Grenzen |
