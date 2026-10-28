# CLAUDE.md – Arbeitsnotizen für KI-Assistenten

Privater Alexa-Skill „Superkugel“ (KI-Gespräch + Hörbücher) für den Echo Dot 5 einer älteren
Nutzerin in Österreich. Aktueller Stand: siehe `PROJECT_STATUS.md`.

## Befehle

```bash
.venv/Scripts/python -m pytest              # alle Tests (Windows-Sandbox: ggf. --basetemp=<scratchpad>/pt)
.venv/Scripts/ruff check .                  # Lint
.venv/Scripts/python scripts/build_interaction_model.py   # Interaction Model aus Code erzeugen
.venv/Scripts/pip-audit -r src/requirements.txt -r requirements-dev.txt
sam build --template infra/template.yaml --config-file samconfig.toml
sam deploy --template-file .aws-sam/build/template.yaml --config-file <absoluter Pfad>/infra/samconfig.toml
```

## Architekturentscheidungen (Details: docs/architektur.md)

- Ein Skill, Locale de-DE, eigener AWS-Stack (SAM, eu-north-1): Lambda Python 3.14 arm64, 1 DynamoDB-Tabelle (pk/sk), privater S3-Bucket, SSM für API-Schlüssel und Modus.
- OpenAI Responses API per stdlib (`conversation/llm.py`), Modell `gpt-6-luna`, `reasoning.effort=none`, `store=false`.
- Freie Rede: ein Intent pro Trägerwort (`conversation/carriers.py`) → Satz wird rekonstruiert. Interaction Model **nie von Hand** editieren, sondern generieren.
- Bibliothek steht im Systemprompt; einziges Tool `play_audiobook(book_id)`. Offsets/Kapitel nur deterministisch (`audiobooks/player.py`).
- Stimmen nur `alexa|Vicki|Marlene|Hans` (Alexa-Doku). Keine externe TTS (Regel gegen kundenspezifisches `<audio>`, OpenAI-TTS-Abschaltung 6.1.2027).
- Thalia: keine API → Eingangsordner (`audiobooks/inbox.py`). Kein Login-Scraping.
- Jeder Fehler: Fallback-Satz + `shouldEndSession=true`. Auf AudioPlayer-/System-Events nie Sprache.
- Tagesaktuelles/Mediatheken (v1.1): stündlicher EventBridge-Abruf (`services/current_context.py`, `audiobooks/media.py`),
  Websuche nur mit Budget (`services/usage.py: searches_left`), alle externen Abrufe über `services/net.py`
  (HTTPS, keine internen Adressen, Größenlimit, keine XML-Entitäten). Fremde Texte nur im Datenteil des Prompts.
  Kostengrenzen sind Vorgabe des Admins: ≤ 1 $/Tag, ≤ 15 $/Monat gesamt – nicht lockern. Keine Nachfrage nach Antworten.
- Kontomodell: Developer-Account und Echo der Nutzerin laufen über das Amazon-Konto des Admins.
  Deshalb sind Speicherschlüssel = Hash(userId + deviceId) (`services/logs.py: hash_user`) – Geräte nicht vermischen.

- v1.2: Morgengruß ohne KI (`features/morning.py`), Wochenbericht nur Zahlen (`services/report.py`).
- v1.3: Erinnerungen, Radio, Rätsel **bewusst entfernt** (macht die normale Alexa besser – Entscheidung des Admins).
  Solche Sätze bekommen nur einen Hinweis und die Sitzung endet (`handlers/alexa_hints.py`); nicht wieder einbauen,
  ohne den Admin zu fragen. Höchstens 10 eigene CloudWatch-Metriken (aktuell 8).

## Regeln

- Keine Gesprächsinhalte, Titel oder rohen User-IDs loggen (`services/logs.py` filtert, trotzdem nicht übergeben).
- Feste Ansagen nur über `speech/texts.py` (Du- und Sie-Form pflegen).
- Keine Secrets, MP3s, ZIPs oder `pre-info.docx` committen (`.gitignore`).
- Abhängigkeiten exakt pinnen; nach Änderungen Tests + pip-audit.
- Simulator-/Unit-Tests nie als Gerätetest ausgeben (`tests/acceptance/ACCEPTANCE_TESTS.md`).
- Neue Intents: in `scripts/build_interaction_model.py` + Route in `app.py` + Test.

## Status (28.10.2026)

Version 1.0 im Alltag in Betrieb, Version 1.1 (Tagesaktuelles A+B, Mediatheken) bereitgestellt, Gerätetests offen.
Version 1.2 bereitgestellt und gepusht (Tag `v1.2.0`); Morgengruß am Gerät bestätigt.
Version 1.3 (Erinnerungen, Radio, Rätsel entfernt) lokal committet, nicht bereitgestellt.
Offene Punkte: `PROJECT_STATUS.md`, `docs/plan-tagesaktuell.md`.
Persönliche Werte (Konto-IDs, Skill-ID, E-Mail, Name/Wohnort der Nutzerin) stehen nur in den lokal ignorierten
Dateien `infra/samconfig.toml` und `.env` – nie ins Repository.
