# Projektstatus – Superkugel

**Stand:** 28.10.2026 · **Version 1.3: bereitgestellt (eu-north-1, Change Set am 28.10.2026 ausgeführt) und live
per Lambda-Aufruf getestet, Interaction Model neu geladen, auf GitHub (Tag `v1.3.0`).** Version 1.0 ist im Alltag auf einem Echo Dot 5 in Betrieb.

## Version 1.3 (28.10.2026) – doppelte Funktionen entfernt

Gerätetest des Admins (27./28.10.2026): Erinnerungen, Radio und Senderwechsel liefen, **Morgengruß funktioniert**;
die Rätsel waren zu leicht und freie Antworten wurden schlecht erkannt. Entscheidung des Admins: Erinnerungen,
Radio und Rätsel kann die normale Alexa besser → aus der Superkugel entfernt.

- Sagt sie in der Superkugel „erinner mich …“, „spiel Ö3“ oder „mach ein Rätsel“, kommt ein kurzer Hinweis
  („Sag dann einfach: Alexa, …“) und die Superkugel schließt sich – ohne KI, damit nichts versprochen wird.
- Geblieben: Gespräch, Hörbücher, Import, Tagesaktuelles, Mediatheken, Morgengruß, Wochenbericht, Schutz.
- Entfernt: Reminders-API und Berechtigung, ORF-Streams und stündliche Sender-Prüfung, 78 Rätsel; 7 Intents,
  Slot-Typen `RADIO_STATION`/`QUIZ_ANSWER`, KI-Werkzeuge `play_radio`/`set_reminder`, Alarm `ReminderApiAlarm`,
  Metriken `ReminderApiError`/`RadioStationDown` (jetzt 8 eigene Metriken, 9 Alarme).
- Tests: **208 bestanden** (vorher 315; entfernte Funktionen samt Tests weg, neue Tests für Hinweise und alte
  Radio-Token); `ruff`, `cfn-lint`, `pip-audit` ohne Befund. **Kein Gerätetest** für 1.3 (Prüfpunkte 49–50).
- Gemessen 28.10.2026 (Testkennung per `aws lambda invoke`, **kein Gerätetest**): stündlicher Abruf 1,5 s
  (Kaltstart-Init 0,7 s), 3 Quellen; Start mit Morgengruß 0,33 s; Hinweise (Erinnerung, Radio, „Spiel Ö drei“,
  Rätsel) 9–27 ms, ohne KI. Alte DynamoDB-Einträge gelöscht (6: Sender, Rätsel-Listen, Erinnerungs-Kennungen,
  Sender-Prüfung). Alarm `ReminderApiAlarm` entfernt.
- Developer Console (Admin, 28.10.2026): Interaction Model neu geladen, Reminders-Berechtigung ausgeschaltet.
- Offen: Gerätetest 49–50.

## Version 1.2 (27.10.2026) – Erinnerungen, Radio, Rätsel in 1.3 wieder entfernt

Erinnerungen (Alexa Reminders API, immer mit Bestätigung), Radio live (ORF: Ö1, Ö3, FM4, Regionalradio),
Morgengruß ohne KI, Rätsel & Gedächtnistraining (78 Einträge + erzeugte Rechnungen), Wochenbericht an den Admin
(nur Zahlen). Details, geprüfte Fakten mit Quellen, Review-Ergebnis und Grenzen: `docs/plan-erweiterungen-v1.2.md`.
Tests: **315 bestanden**; `ruff`, `cfn-lint --regions eu-north-1`, `pip-audit` ohne Befund. Drei unabhängige
Reviews eingearbeitet. Kostenwirkung ≈ 0 (`docs/kosten.md`), neue Datenflüsse in `docs/datenschutz.md`.
**Kein Gerätetest** – alle neuen Prüfpunkte offen.

## Was läuft

| Bereich | Stand |
|---|---|
| Skill | Alexa Custom Skill „Superkugel“ (de-DE), Entwicklungsmodus auf dem Amazon-Konto des Admins, auf das auch der Echo der Nutzerin registriert ist |
| Backend | AWS SAM-Stack `superkugel` in **eu-north-1** (Stockholm): Lambda python3.14/arm64, DynamoDB, privater S3-Bucket, SSM, CloudWatch-Alarme, SNS |
| Gespräch | OpenAI `gpt-6-luna` (Responses API, `store=false`), Kärntner Färbung, Du-Form mit Vornamen, Stimme Vicki 100 %, Verlauf + 30-Min-Wiederaufnahme, Lückenfüller erst nach 4,5 s |
| Hörbücher | AudioPlayer mit Lesezeichen pro Gerät, Kapitelwechsel, Spulen, Titel-/Genre-Suche mit KI-Rückfall auf die vorhandene Bibliothek |
| Import | Eingangsordner + stündliche Windows-Aufgabe, eigener IAM-Benutzer mit Minimalrechten, Mail bei Import/Fehler |
| Tagesaktuelles (1.1) | stündlicher Abruf in AWS (ORF + Wetter), Websuche mit Tageslimit, Lieblingssendungen; freie Mediensuche erst mit Podcast-Index-Schlüssel |
| Morgengruß, Wochenbericht (1.2) | Morgengruß ohne KI (am Gerät bestätigt), Wochenbericht montags per SNS-Mail, nur Zahlen |
| Hinweise (1.3) | Erinnerungen, Radio, Rätsel → kurzer Hinweis auf die normale Alexa, Sitzung endet |
| Schutz | harte Tages-/Monatskostengrenze, Circuit-Breaker, Fernschalter, Prepaid bei OpenAI, Budget-Warnung im Management-Konto |

Gemessen (25.10.2026, per `aws lambda invoke`): Kaltstart 0,8 s Init + 1,5 s; Gesprächsantwort 3,2 s gesamt
(KI 3,1 s) bei ≈ 0,0001 $ pro Frage. Signierte Audio-Links liefern `206 Partial Content`.

Gemessen v1.1 (25.10.2026, Testnutzer per `aws lambda invoke`, kein Gerätetest): Abruf 1,3 s, 3 Quellen ohne Fehler;
„Was gibt's Neues?“ aus dem ORF-Datenteil ohne Websuche, KI 2,0 s, 0,0006 $ (≈ 6.000 Eingabe-Tokens, davon
im Prompt-Cache 0,00008 $); Wetter 1,3 s; Frage mit Websuche 4,6 s, 0,024 $ (OpenAI meldete 2 Suchvorgänge –
beide gezählt). Live gefunden und behoben: erste Anfrage nach dem stündlichen Abruf erbte die Kaltstart-Uhr und
brach sofort ab; Nachrichtenfrage löste unnötige Websuche aus; Wetter wurde dem ORF zugeschrieben; Pause in „26. Oktober“.

## Tests

- `pytest`: **208 bestanden** (Stand 1.3; Python 3.14, Windows). Unit- und Integrationstests mit echten Alexa-Request-JSONs,
  gemockter OpenAI-API und moto (DynamoDB/S3/SSM). `ruff`, `cfn-lint --regions eu-north-1`, `pip-audit`: ohne Befund.
- Zwei unabhängige Reviews (Alexa-Konformität, Wiedergabe, Ausfallsicherheit, Sicherheit, Kosten, Bedienbarkeit,
  Import) – alle berechtigten Befunde behoben und mit Regressionstests abgesichert.
- Auf dem Gerät durch den Admin bestätigt: natürliches Gespräch, Pause / Weiter / Zurück.
- Akzeptanzprotokoll: `tests/acceptance/ACCEPTANCE_TESTS.md`.

## Offen

1. Restliche Gerätetests (Kapitelwechsel, Neustart, Ausfallszenarien, Test mit der Stimme der Nutzerin).
2. Zugriffsschlüssel des Admin-Benutzers deaktivieren, wenn gerade nicht deployt wird (wieder aktivierbar).
3. **Version 1.1 (bereitgestellt, Gerätetests 27–34 offen):** Tagesaktuelles (Nachrichten/Wetter, Websuche
   mit Tageslimit), Lieblingssendungen + freie Mediensuche, „ratschen“, keine Nachfrage nach Antworten,
   Kostengrenzen 1 $/Tag bzw. 15 $/Monat gesamt – `docs/plan-tagesaktuell.md`, `docs/kosten.md`, `docs/datenschutz.md`.
   Wohnort und Einverständnis der Nutzerin liegen vor (nur lokal in `infra/samconfig.toml`).
4. Lieblingssendungen eintragen (`podcast add`), Podcast-Index-Schlüssel hinterlegen (`set-podcastindex`),
   OpenAI-Projektlimit 14 $/Monat setzen.
5. **Version 1.3:** Gerätetest 49–50 (✋ Admin); Console-Schritte erledigt. Morgengruß (Prüfpunkt 44) am 28.10.2026 bestätigt; Wochenbericht (48) am nächsten Montag.
6. GitHub: „Keep my email addresses private“ und „Block command line pushes that expose my email“ sind seit
   27.10.2026 an; die Adresse im bereits öffentlichen Commit `81850c6` bleibt sichtbar (Entfernen nur per
   Force-Push). Lokale Zweige `archiv/*` gelöscht (waren nie auf GitHub).

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
