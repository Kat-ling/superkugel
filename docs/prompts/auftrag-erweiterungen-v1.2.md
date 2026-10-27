# PROJEKTAUFTRAG: Superkugel 1.2 – Erinnerungen, Radio, Morgengruß, Rätsel, Wochenbericht

Grundlage: `CLAUDE.md`, `PROJECT_STATUS.md`, `docs/architektur.md`, `docs/kosten.md`, `docs/datenschutz.md`,
`docs/plan-tagesaktuell.md` (Stand v1.1.0). Repository: dieses Projekt (öffentlich auf GitHub).
AWS-Projektkonto „Superkugel“ (Konto-ID, Skill-ID, Alarm-Mail nur lokal in `infra/samconfig.toml`/`.env`),
Region **eu-north-1**, CLI-Profil `superkugel-admin`, Stack `superkugel`.

## 0. Rolle und Arbeitsweise

Du bist ein erfahrenes Engineering-Team (Alexa Skills, Python, AWS, Conversational AI, Barrierefreiheit für
ältere Menschen, Datenschutz, QA) und arbeitest **vollständig selbstständig** nach den Projektregeln (`CLAUDE.md`).

1. Normale technische Entscheidungen selbst treffen. Keine Rückfragen, die sich durch Doku, Code, Tests oder
   Recherche klären lassen. Entscheidungen mit Begründung in `docs/plan-erweiterungen-v1.2.md` festhalten.
2. Jede Plattform-/API-Annahme **vor** der Umsetzung gegen die aktuelle offizielle Doku prüfen
   (Alexa Reminders API und Berechtigungen, AudioPlayer bei Live-Streams, EventBridge in SAM, SNS,
   Nutzungsbedingungen der Radio-Streams). Ergebnis mit Quelle in der Plandatei dokumentieren.
3. Tests tatsächlich ausführen; nie behaupten, etwas getestet zu haben, das nicht lief.
   Lambda-/Simulator-Aufrufe sind **kein** Gerätetest – Geräteprüfungen als offen kennzeichnen.
4. Keine Gesprächsinhalte, Erinnerungstexte, Rätselantworten, Titel, Namen oder Orte in Logs, Metriken oder Mails.
5. Keine Geheimnisse und keine persönlichen Werte (Name, Wohnort, Konto-IDs, E-Mail) in Git, Logs oder Doku.
6. Bestehende Funktionen (Gespräch, Hörbücher, Mediatheken, Aktuelles, Websuche, Fallback, Kostengrenzen)
   bleiben unverändert zuverlässig. Jeder neue Fehlerpfad endet mit freundlichem Satz + Fallback wie bisher.
7. **Kostengrenzen sind Vorgabe des Admins und werden nicht gelockert:** gesamt ≤ 1 $/Tag, ≤ 15 $/Monat.
   Neue Funktionen sollen möglichst ohne KI-Aufruf auskommen.
8. Nichts erfinden: Was nicht verifiziert ist, als offen kennzeichnen.
9. **Freigaben sammeln, nicht zwischendurch fragen.** Alles vorbereiten, was ohne Freigabe geht (Code, Tests,
   Reviews, Doku, Commit **lokal**, Change Set **erstellen, nicht ausführen**). Erst ganz am Schluss die
   gesammelte Freigabeliste vorlegen (siehe §8). Fragen nur, wenn wirklich blockiert (Passwörter, Schlüssel,
   MFA, kostenpflichtige Ressourcen, Veröffentlichung, Übermittlung personenbezogener Daten, Unumkehrbares).

## 1. Ziel

Fünf Erweiterungen, die den Alltag der Nutzerin erleichtern und im Betrieb praktisch nichts kosten:

| # | Funktion | Kern |
|---|---|---|
| 1 | **Erinnerungen** | „Erinner mich morgen um zehn an den Arzt“ → echte Alexa-Erinnerung |
| 2 | **Radio live** | „Spiel Radio Kärnten“, „Spiel Ö1“ – österreichische Sender per Stream |
| 3 | **Morgengruß** | Beim Öffnen am Morgen: Begrüßung, Datum, Wetter, zwei Schlagzeilen – ohne KI |
| 6 | **Rätsel & Gedächtnistraining** | Sprichwörter ergänzen, kleines Quiz, Rechenrätsel – geduldig, ohne Druck |
| 7 | **Wochenbericht an den Admin** | Wöchentliche Mail: Nutzung, Kosten, Fehler – **ohne** Inhalte |

Sprache und Ton wie bisher: Kärntner Färbung, Du-Form, Vorname aus `USER_NAME`, Stimme Vicki 100 %,
„ratschen“, keine Nachfrage nach Antworten, feste Ansagen nur über `speech/texts.py` (Du- und Sie-Form).

## 2. Umsetzung

### 2.1 Erinnerungen (Punkt 1)
- Alexa **Reminders API** (`/v1/alerts/reminders`) mit `apiAccessToken` und `apiEndpoint` aus dem Request.
  Berechtigung `alexa::alerts:reminders:skill:readwrite` im Skill-Manifest (Interaction-Model-Generator bzw.
  Manifest-Doku ergänzen). Doku prüfen: nur während einer Sitzung, Limits, Zeitzone, wiederkehrende Erinnerungen.
- Fehlende Berechtigung → `AskForPermissionsConsent`-Karte + kurzer Satz („Schau bitte in die Alexa-App …“);
  Anleitung für den Admin in `docs/betrieb-und-wartung.md`.
- Intents: `SetReminderIntent` (AMAZON.DATE, AMAZON.TIME, Freitext-Slot „was“), `ListRemindersIntent`
  („Welche Erinnerungen hab ich?“), `DeleteReminderIntent` (Auswahl per Nummer, mit Bestätigung).
  Erkennung aus dem freien Gespräch: optional zusätzliches KI-Tool `set_reminder` – nur, wenn es das Kostenbudget
  nicht spürbar erhöht; deterministische Intents haben Vorrang.
- **Immer bestätigen** vor dem Anlegen („Ich erinner dich morgen, Dienstag, um zehn Uhr an: Arzt. Passt das?“).
  Ohne Uhrzeit nachfragen, Uhrzeiten in der Vergangenheit ablehnen, „in einer Stunde“ relativ auflösen (Europe/Vienna).
- Erinnerungstext nur an Amazon (dort ohnehin gespeichert), nicht in DynamoDB, nicht in Logs, nicht an OpenAI,
  außer die Erinnerung entstand im KI-Gespräch (dann ist der Satz ohnehin dort) – in `datenschutz.md` dokumentieren.
- Klar dokumentieren: Erinnerungen gehören zum Amazon-Konto des Admins (Kontomodell), erscheinen auch in dessen
  Alexa-App, und Superkugel ersetzt keine Medikamenten- oder Notfallerinnerung mit Gewähr.

### 2.2 Radio live (Punkt 2)
- Kuratierte Senderliste (Ö1, Ö3, FM4, Radio Kärnten/ORF-Bundesland aus `USER_REGION`, ggf. weitere freie Sender)
  als Konfiguration im Code; **nur offizielle HTTPS-Streams**, deren Nutzung in Skills erlaubt ist
  (Nutzungsbedingungen prüfen und mit Quelle dokumentieren; nicht erlaubte Sender weglassen).
- Stream-URLs beim Start nicht live prüfen (Latenz), aber stündlich im bestehenden `refresh_context`-Lauf per
  `HEAD`/kurzem `GET` über `services/net.py` gesundheitlich prüfen; tote Sender → Metrik, ehrliche Ansage.
- AudioPlayer `Play` mit eigenem Token-Präfix `radio-`, ohne Offset/Lesezeichen; Pause = Stop, „weiter“ startet den
  Sender neu; „nächster/vorheriger“ wechselt den Sender oder sagt freundlich, dass es beim Radio nicht geht.
  Hörbuch-Lesezeichen dürfen durch Radio **nicht** überschrieben werden; „Hörbuch weiter“ bleibt Hörbüchern vorbehalten.
- Intents: `PlayRadioIntent` (Slot Sendername mit Synonymen: „Radio Kärnten“, „Kärnten heute“, „Ö eins“ …),
  `ListRadioIntent`. KI-Tool `play_radio(station_id)` für Wünsche aus dem Gespräch.

### 2.3 Morgengruß (Punkt 3)
- Bei `LaunchRequest` zwischen 5 und 11 Uhr (Wiener Zeit) und nur beim **ersten Start des Tages pro Gerät**:
  „Guten Morgen, <Vorname>! Heute ist Dienstag, der 27. Oktober. Es wird … Grad und … In den Nachrichten: … und …“
  Danach normal weiter (still zuhören wie bisher). Später am Tag: bisherige Begrüßung.
- Daten **nur** aus dem bestehenden `CONTEXT`-Eintrag (kein KI-Aufruf, kein Netzabruf); fehlende/alte Daten
  (> `CONTEXT_MAX_AGE_H`) → Teil weglassen. Schlagzeilen kürzen, belastende Meldungen (Gewalt, Unglücke)
  per einfacher Wortliste überspringen; das Kriterium in der Doku nennen.
- Abschaltbar per Parameter `MORNING_BRIEFING` (Standard an) und per Sprache („Lass den Morgengruß weg“ → pro Gerät).
- Tagesflag pro Gerät in DynamoDB mit TTL (kein Verlauf).

### 2.4 Rätsel & Gedächtnistraining (Punkt 6)
- Intents: `StartQuizIntent` („Mach ein Rätsel mit mir“, „Spielen wir was“), Antworten über bestehende
  Freitext-/Trägerwort-Logik, `AMAZON.StopIntent`/„genug“ beendet freundlich.
- Inhalte **deterministisch** aus einer kuratierten, gemeinfreien bzw. selbst formulierten Sammlung im Code
  (Sprichwörter ergänzen, einfache Allgemeinwissen-Fragen mit Österreich-Bezug, leichte Kopfrechnungen).
  Kein urheberrechtlich geschütztes Material. Mindestens 60 Einträge, gemischt, ohne Wiederholung innerhalb
  von 7 Tagen pro Gerät.
- Antwortprüfung tolerant (Groß/Klein, Umlaute, Füllwörter, Zahlwörter; mehrere gültige Antworten).
  Falsch → ermutigender Hinweis, zweiter Versuch, dann Auflösung. Nie belehrend, kein Punktedruck;
  optional „Du hast heute drei gewusst“.
- KI nur optional als Fallback für „Erklär mir das“ – innerhalb der bestehenden Budgets.

### 2.5 Wochenbericht (Punkt 7)
- Zweiter EventBridge-Zeitplan (z. B. Montag 8:00 Wiener Zeit, `cron` mit Zeitzone prüfen) mit Payload
  `{"superkugel":"weekly_report"}` an dieselbe Lambda. Versand über das **bestehende SNS-Alarmthema**
  (keine neue kostenpflichtige Ressource, kein SES).
- Inhalt nur Zahlen: Anzahl Sitzungen/Gesprächsfragen/Websuchen/Mediensuchen/Radio- und Hörbuchstarts,
  KI-Kosten Woche und Monat vs. Grenzen, Fehler- und Langsam-Zähler, Alter der letzten Kontextdaten,
  tote Radiosender, neue Hörbücher. **Keine** Fragen, Titel, Erinnerungen, Namen, Orte.
- Zähler aus vorhandenen Usage-Daten bzw. neuen Tageszählern (TTL ≥ 40 Tage); Fehler beim Bericht → Metrik, kein Absturz.
- `superkugel_admin.py report` zeigt denselben Bericht lokal an.

## 3. Querschnitt

- Neue Intents im Generator `scripts/build_interaction_model.py` + Route in `app.py` + Tests; Konflikte mit
  bestehenden Intents (Chat-Träger, Mediensuche, `ChooseResultIntent`) prüfen und testen.
- Hilfe-Text und Spickzettel (`docs/benutzer/…`) um die neuen Sätze ergänzen; Sie-Form mitpflegen.
- Neue Settings mit Template-Parametern und Grenzen; Privates nur in `infra/samconfig.toml`.
- Latenz: alle neuen Pfade ohne KI < 1,5 s Lambda-Zeit; Reminders-API-Aufruf mit Timeout ≤ 3 s.
- Alarme ergänzen, wo sinnvoll (Reminder-API-Fehler, Wochenbericht fehlgeschlagen); ≤ 10 eigene Metriken gesamt
  beibehalten (CloudWatch-Freikontingent).

## 4. Tests (automatisiert, ohne echte Netzaufrufe)

- Erinnerungen: Datums-/Zeitauflösung (heute/morgen/relativ, Sommer-/Winterzeit, Mitternacht Wien), Bestätigung
  ja/nein, fehlende Berechtigung → Consent-Karte, API-Fehler/Timeout, Auflisten/Löschen, keine Texte in Logs.
- Radio: Play/Pause/Weiter/Next, kein Überschreiben von Hörbuch-Lesezeichen, toter Sender, Sendersynonyme.
- Morgengruß: Zeitfenster, einmal pro Tag und Gerät, alte/fehlende Daten, Wortfilter, abschaltbar.
- Rätsel: tolerante Auswertung, zwei Versuche, keine Wiederholung binnen 7 Tagen, Abbruch.
- Wochenbericht: Inhalt nur Zahlen (Test sucht aktiv nach verbotenen Feldern), SNS-Aufruf gemockt, Fehlerpfad.
- Regression: alle bestehenden Tests grün; `ruff`, `cfn-lint --regions eu-north-1`, `pip-audit`.

## 5. Reviews

Mindestens **drei unabhängige, tiefe Reviewer-Agenten** (1. Alexa-Konformität & Bedienbarkeit für ältere Menschen,
2. Datenschutz & Sicherheit, 3. Korrektheit, Kosten & Latenz). Alle berechtigten Befunde beheben und mit
Regressionstests absichern; verworfene Befunde mit Begründung in der Plandatei.

## 6. Dokumentation

`docs/plan-erweiterungen-v1.2.md` (Entscheidungen, geprüfte Fakten mit Quellen, Review-Ergebnis, Grenzen),
`docs/kosten.md`, `docs/datenschutz.md` (neue Datenflüsse: Amazon Reminders, Radio-Hoster sehen die IP des Echo,
Wochenbericht), `docs/architektur.md`, `docs/betrieb-und-wartung.md` (Berechtigung erteilen, Sender pflegen,
Morgengruß/Bericht abschalten), Benutzer-Doku/Spickzettel, `PROJECT_STATUS.md`, `CLAUDE.md`,
`tests/acceptance/ACCEPTANCE_TESTS.md` (neue Geräteprüfpunkte ab 35).

## 7. Definition of Done

- Punkte 1, 2, 3, 6, 7 implementiert, alle Tests grün, Lint/Template/Audit ohne Befund, Reviews eingearbeitet.
- Repository nachweislich frei von Geheimnissen und persönlichen Werten (Scan über Arbeitskopie **und** Historie
  des zu pushenden Zweigs); lokal committet, **nicht** gepusht.
- Change Set erstellt und inhaltlich zusammengefasst, **nicht** ausgeführt.
- Kosten- und Datenschutzwirkung beziffert; Gerätetests als offen gekennzeichnet.

## 8. Abschluss: gesammelte Freigaben (erst jetzt fragen)

Zum Schluss **eine** übersichtliche Liste vorlegen, jeweils mit Wirkung, Kosten und Rückweg:

1. Change Set ausführen (neue Ressourcen: zweiter Zeitplan + Berechtigung; geänderte Lambda/Alarme).
2. Interaction Model und Skill-Manifest (Reminders-Berechtigung) in der Alexa-Developer-Console aktualisieren
   bzw. die Schritte für den Admin bereitstellen.
3. Push von `main` und Tag `v1.2.0` auf GitHub.
4. Aufgaben des Admins: Erinnerungs-Berechtigung in der Alexa-App erteilen; Gerätetests ab Prüfpunkt 35;
   ggf. Senderauswahl bestätigen.

Nach Freigabe: ausführen, live per `aws lambda invoke` testen (Morgengruß, Radio-Start, Rätsel, Bericht an SNS;
Erinnerungen nur so weit ohne echten Token möglich), Messwerte und Kosten berichten, Statusdoku aktualisieren.
