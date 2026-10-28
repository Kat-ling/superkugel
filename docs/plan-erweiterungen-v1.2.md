# Superkugel 1.2 – Erinnerungen, Radio, Morgengruß, Rätsel, Wochenbericht

> **Hinweis 28.10.2026 (Version 1.3):** Erinnerungen, Radio und Rätsel wurden nach dem Gerätetest wieder entfernt –
> die normale Alexa kann das besser. Geblieben sind Morgengruß und Wochenbericht. Dieses Dokument beschreibt den
> Stand von 1.2 (Historie); aktueller Stand: `PROJECT_STATUS.md`.

Stand 27.10.2026 · **Status: bereitgestellt (Change Set ausgeführt) und live per Lambda-Aufruf getestet (`PROJECT_STATUS.md`); nicht gepusht.**
Gerätetests offen (Prüfpunkte 35–48 in `tests/acceptance/ACCEPTANCE_TESTS.md`).
Auftrag: `docs/prompts/auftrag-erweiterungen-v1.2.md`. Kosten: `docs/kosten.md`. Datenschutz: `docs/datenschutz.md`.

## Geprüfte Fakten (offizielle Doku, abgerufen 27.10.2026)

| Punkt | Ergebnis | Quelle |
|---|---|---|
| Reminders API | `POST/GET /v1/alerts/reminders`, `GET/DELETE …/{alertToken}`; Host aus `apiEndpoint` (EU: `api.eu.amazonalexa.com`). Anlegen **nur in einer Sitzung** mit dem `apiAccessToken` des Requests (401 `NOT_IN_SESSION` sonst); Lesen/Löschen ginge auch außerhalb. | [Reminders API Reference](https://developer.amazon.com/en-US/docs/alexa/smapi/alexa-reminders-api-reference.html) |
| Berechtigung | Scope `alexa::alerts:reminders:skill:readwrite` im Manifest (`permissions`); Nutzer erteilt sie in der Alexa-App; Skill soll freundlich darauf hinweisen und eine Berechtigungskarte schicken. Ausdrückliche Zustimmung pro Erinnerung im Dialog; Ansage muss Zeitpunkt nennen. | [Reminders Overview](https://developer.amazon.com/en-US/docs/alexa/smapi/alexa-reminders-overview.html) |
| Zeitzone | `SCHEDULED_ABSOLUTE` mit `scheduledTime` (Ortszeit, Format `YYYY-MM-DDTHH:mm:ss.SSS`) + `timeZoneId` (IANA). Ohne `timeZoneId` gilt die Gerätezeitzone. → Skill sendet immer Wiener Ortszeit + `Europe/Vienna`, Sommer-/Winterzeit rechnet Amazon. | Reference |
| Limits | Grenze pro **Gerät** (Beispiel „500“), `403 MAX_REMINDERS_EXCEEDED`; Textlänge ohne Zahl („Text string is too long“) → Skill kürzt auf 120 Zeichen. 429 → später. Ein Skill sieht/löscht nur eigene Erinnerungen; erledigte bleiben 3 Tage in der App sichtbar. | Reference / Overview |
| Wiederkehrend | `recurrence` mit RRULE möglich, Mindestabstand außerhalb en-US **4 Stunden**. → In 1.2 bewusst **nicht** umgesetzt (Dialog einfacher, ungetestet am Gerät); der Skill sagt das ehrlich. | Reference |
| Sprach-Berechtigung (AskFor) | `Connections.SendRequest`/`AskFor` existiert; **de-DE-Unterstützung nicht dokumentiert** → nicht verwendet, nur Karte. Offen für später. | [Voice permissions for reminders](https://developer.amazon.com/en-US/docs/alexa/smapi/voice-permissions-for-reminders.html) |
| AudioPlayer / Streams | Stream-URL muss HTTPS auf Port 443 sein; `offsetInMilliseconds` 0 = Anfang; Token max. 1024 Zeichen, ohne Kundendaten. Zu Live-Streams sagt die Referenz nichts Besonderes. | [AudioPlayer Interface Reference](https://developer.amazon.com/en-US/docs/alexa/custom-skills/audioplayer-interface-reference.html) |
| Slot-Formate | AMAZON.DATE `2026-10-28`, AMAZON.TIME `HH:MM` oder `MO/AF/EV/NI`, AMAZON.DURATION ISO 8601 (`PT1H30M`); Daten ohne Jahr werden in die Zukunft aufgelöst. | [Slot Type Reference](https://developer.amazon.com/en-US/docs/alexa/custom-skills/slot-type-reference.html) |
| AMAZON.SearchQuery + weitere Slots in einem Satz | In der Doku **nicht eindeutig gefunden** → bewusst getrennt: `RemindMeIntent` (nur Freitext, eigener deutscher Zeitparser) und `SetReminderIntent` (nur DATE/TIME/DURATION). | – (offen) |
| EventBridge | Klassische Zeitplan-Regeln: cron **nur in UTC**; EventBridge Scheduler (`ScheduleV2`) kann `ScheduleExpressionTimezone`, legt aber eine eigene IAM-Rolle und einen anderen Dienst an. | [Scheduled rules](https://docs.aws.amazon.com/eventbridge/latest/userguide/eb-scheduled-rule-pattern.html), [SAM ScheduleV2](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/sam-property-function-schedulev2.html) |
| ORF-Streams | `https://orf-live.ors-shoutcast.at/<sender>-q2a` – vom ORF selbst veröffentlicht (Ö1-Seite „Ö1 Webradio“). Live geprüft 27.10.2026: Ö1, Ö3, FM4 und alle 9 Regionalradios liefern über HTTPS direkt `206`/`audio/mpeg`, 192 kbit/s, ohne Weiterleitung; HEAD → `200 audio/mpeg`. | [oe1.orf.at „Ö1 Webradio“](https://oe1.orf.at/artikel/583280/Oe1-Webradio) |
| ORF-Nutzungsbedingungen für Skills | **Nicht gefunden.** Der ORF bietet eigene Alexa-Skills an; ausdrückliche Bedingungen für die Einbindung der Streams in fremde Skills sind nicht veröffentlicht. Bewertung: private, nicht-kommerzielle Nutzung eines öffentlich verlinkten Webradio-Streams im eigenen Haushalt. → **Freigabe durch den Admin** (siehe Freigabeliste); weitere Sender ohne geprüfte Bedingungen wurden **weggelassen**. | Suche ohne Treffer; [der.orf.at Radiothek](https://der.orf.at/unternehmen/aktuell/radiothek102.html) |
| Geoblocking | ORF-**TV** ist geogeblockt; die Radio-Streams sind aus dem Testnetz **und aus AWS Stockholm** erreichbar (Live-Prüfung 27.10.2026: 0 von 4 tot). Schutz im Code bleibt (alle tot → trotzdem spielen). | Testabruf, Live-Lauf |
| SNS | E-Mail-Abo am bestehenden Thema `superkugel-alerts`; `sns:Publish` für die Lambda, kein SES. | Template |

## Entscheidungen

| # | Entscheidung | Begründung |
|---|---|---|
| 1 | Reminders-API **per stdlib-HTTP** mit Zeitlimit 3 s statt SDK-`ReminderManagementServiceClient` | Der SDK-`DefaultApiClient` hat kein Zeitlimit; Alexa wartet nur ≈ 8 s. Token geht nur an `api(.eu/.fe).amazonalexa.com` über HTTPS. |
| 2 | **Eigener deutscher Zeitparser** (`reminders/parse.py`) für Freitext | Österreichische Uhrzeiten („dreiviertel zehn“, „in der Früh“), Zahlwörter, „in einer halben Stunde“; deterministisch, testbar, ohne KI. |
| 3 | Uhrzeiten ohne Tageszeit: 1–5 Uhr = nachmittags; ohne Datum und schon vorbei → dieselbe Uhrzeit am Abend, sonst morgen; nur mit ausdrücklichem Datum (heute) Ablehnung | „um drei“ meint am Tag fast nie 3 Uhr nachts; die Bestätigung nennt die Uhrzeit (15 Uhr) ausdrücklich. „heute in der Früh um sieben“ um 9 Uhr → „schon vorbei“; „um sieben in der Früh“ am Abend → morgen 7 Uhr. Relative Zeiten („in einer Stunde“) sind immer exakt. |
| 4 | Immer **Bestätigung** vor dem Anlegen, auch beim KI-Werkzeug `set_reminder` | Amazon-Richtlinie + Bedienbarkeit. Das Werkzeug wertet **ihren eigenen Satz** deterministisch aus, nicht die Umformulierung des Modells. |
| 5 | Erinnerungstext nur in der Alexa-Sitzung und bei Amazon | Keine Speicherung in DynamoDB, keine Logs. Ausnahme (dokumentiert): entsteht die Erinnerung im KI-Gespräch, kennt OpenAI den Satz ohnehin. |
| 6 | Radio: nur ORF (Ö1, Ö3, FM4 + Regionalradio aus `USER_REGION`), Token `radio-<id>` | Eigene, kurze Liste. Das Präfix wird von der Hörbuchlogik nicht als Buch erkannt → **kein Lesezeichen wird überschrieben**; letzter Sender in eigenem Eintrag `USER#…/RADIO`. |
| 7 | Gesundheitsprüfung stündlich per **HEAD** im bestehenden Abruf; tot = Ansage, **außer alle sind tot** | Fallen alle Sender gleichzeitig aus, liegt es fast sicher an der Prüfung (Netz/Sperre in AWS) → dann trotzdem abspielen statt fälschlich absagen. Prüfung älter als 3 h zählt nicht. |
| 8 | Pause = Stopp, „weiter“ = live neu, „nächster/vorheriger“ = Senderwechsel, Spulen/Kapitel = „geht beim Radio nicht“ | Wie im Auftrag; „Hörbuch weiter“ bleibt Hörbüchern vorbehalten. „Alexa, weiter“ ohne Kontext nimmt das zuletzt Gehörte (Radio-Zeitstempel vs. letztes Lesezeichen). |
| 9 | Morgengruß ohne KI, nur aus `CONTEXT`; Tagesmerker `USER#…/DAYFLAGS` mit TTL 2 Tage | Kein Netzabruf beim Start, kein Verlauf; zwei kurze Schlagzeilen (Bundesland zuerst). |
| 10 | Belastende Meldungen über **Wortliste** (`features/morning.py: DISTRESSING`) | Kriterium: Tod, Gewalt, Unfälle/Unglücke, Krieg/Terror, Katastrophen, Brände, Verletzte, Suizid. Kurze Stämme nur am Wortanfang („tot“, nicht „total“), längere auch in Zusammensetzungen („Verkehrsunfall“). Lieber eine harmlose Meldung zu viel weglassen. |
| 11 | Rätsel: 78 Einträge (32 Sprichwörter, 28 Wissensfragen mit Österreich-Bezug, 18 Rechnungen), selbst formuliert bzw. gemeinfrei | Keine Wiederholung binnen 7 Tagen pro Gerät (`USER#…/QUIZSEEN`, TTL 8 Tage); gemischte Typen; max. 10 pro Runde; 2 Versuche mit Tipp, dann Auflösung; „weiß nicht“ → Auflösung ohne Wertung; „genug“/Stopp → Lob mit Tageszahl. |
| 12 | Antworten über eigenen `QuizAnswerIntent` (Custom-Slot mit allen Antworten) + Zahlen über `ChooseResultIntent` + Trägerwörter | Antworten wie „Gold im Mund“ beginnen mit keinem Trägerwort und landeten sonst im Fallback. Außerhalb eines Rätsels geht der Satz ins Gespräch (statt „nicht verstanden“). |
| 13 | Wochenbericht über **klassische EventBridge-Regel** `cron(0 6,7 ? * MON *)` (UTC) + Prüfung „8-Uhr-Stunde in Wien, einmal pro Woche“ im Code | Gleicher, von der SCP nachweislich erlaubter Dienst wie der stündliche Abruf; keine neue IAM-Rolle (Scheduler bräuchte eine). 6 UTC = 8 Uhr Sommerzeit, 7 UTC = 8 Uhr Winterzeit. |
| 14 | Tageszähler `pk=STATS` (ein UpdateItem pro Ereignis, TTL 45 Tage) | Nur Zahlen. Gesprächsfragen/Websuchen kommen aus den bestehenden `USAGE`-Einträgen. |
| 15 | Neue Metriken nur 3: `ReminderApiError`, `RadioStationDown`, `WeeklyReportFailed` → **10 gesamt** | CloudWatch-Freikontingent (10 Metriken). Alarme: Erinnerungs-API ≥ 3/Tag, Wochenbericht fehlgeschlagen. |
| 18 | Erinnerungen auflisten/löschen nur für dieses Gerät (`USER#…/REMINDERS`, nur alertTokens) | Die API arbeitet pro Konto + Skill; über das gemeinsame Admin-Konto sähe die Nutzerin sonst Erinnerungen des Admins. |
| 16 | Neue Trägerwörter `an`, `ans`, `daran`, `dass`, `übermorgen` | Antworten auf „Woran soll ich dich erinnern?“ / „Wann?“ würden sonst im Fallback landen. Im Gespräch bleibt der Satz vollständig (Träger + Rest). |
| 17 | Sprach-Abschaltung Morgengruß pro Gerät (`USER#…/PREFS`), global per Parameter `MorningBriefing` | Wie beauftragt. |

## Was gebaut wurde

| Funktion | Sätze (Beispiele) | Code |
|---|---|---|
| Erinnerungen | „Erinner mich morgen um zehn an den Arzt“ → „Ich erinner dich morgen, Mittwoch, um 10 Uhr an: den Arzt. Passt das?“ → „ja“. „Welche Erinnerungen hab ich?“, „Lösch eine Erinnerung“ → „die zweite“ → „ja“ | `reminders/`, `handlers/reminders.py` |
| Radio | „Spiel Radio Kärnten“, „Spiel Ö eins“, „Welche Sender gibt es?“, „Alexa, Pause/weiter/nächster“ | `radio/stations.py`, `handlers/radio.py` |
| Morgengruß | erstes Öffnen 5–11 Uhr: „Guten Morgen, …! Heute ist Dienstag, der 27. Oktober. Das Wetter: … In den Nachrichten: … Und: …“; „Lass den Morgengruß weg“ / „Mach den Morgengruß wieder“ | `features/morning.py`, `handlers/morning.py` |
| Rätsel | „Mach ein Rätsel mit mir“, Antwort frei, „weiß nicht“, „Erklär mir das“ (KI, im Budget), „genug“ | `quiz/`, `handlers/quiz.py` |
| Wochenbericht | Montag 8 Uhr Mail (nur Zahlen); `superkugel_admin.py report` zeigt denselben Bericht | `services/report.py`, `services/stats.py` |

## Tests

`pytest`: **315 bestanden** (190 bisherige + 125 neue, davon 34 Regressionstests aus den Reviews; Unit: `tests/unit/test_v12_logic.py`, Integration über den ganzen
Skill: `tests/integration/test_skill_v12.py`). `ruff`, `cfn-lint --regions eu-north-1`, `pip-audit`: ohne Befund.
Abgedeckt u. a.: heute/morgen/relativ, Sommer-/Winterzeit-Wechsel, Mitternacht Wien ≠ UTC-Datum, Bestätigung ja/nein/
Korrektur, fehlende Berechtigung → Karte, API-Fehler/Zeitüberschreitung, Auflisten/Löschen, keine Texte in Logs;
Radio Play/Pause/Weiter/Nächster/Controller, Lesezeichen unverändert, toter Sender, Synonyme; Morgengruß Zeitfenster,
einmal pro Tag und Gerät, alte Daten, Wortfilter, abschaltbar; Rätsel tolerant, zwei Versuche, keine Wiederholung
in 7 Tagen, Abbruch; Wochenbericht nur Zahlen (Test sucht aktiv nach Titel, Name, Ort, Gesprächstext), SNS gemockt,
Fehlerpfad. **Kein Gerätetest** – siehe Prüfpunkte 35–48.

## Review (27.10.2026, drei unabhängige Reviewer: 1. Alexa-Konformität & Bedienbarkeit, 2. Datenschutz & Sicherheit, 3. Korrektheit, Kosten & Latenz)

Behoben und mit Regressionstests abgesichert (`# Regressionen aus den Reviews` in beiden Testdateien):
- **„Ja, aber um elf“** legte die Erinnerung zur alten Zeit an → Korrektur wird immer zuerst ausgewertet und neu
  bestätigt; „lieber um elf“ überschreibt nicht mehr den Inhalt.
- **Relative Zeiten nachts** („in einer Stunde“ um 0:30 → 13:30) → relative Zeiten sind eindeutig, in UTC gerechnet,
  exakter Zeitpunkt wird mitgeführt (auch in der Umstellungsnacht echte Dauer).
- **„Um sieben in der Früh“ abends gesagt** wurde als vorbei abgelehnt → ohne Datum wird auf morgen gerollt; nur
  „heute … früh“ nach der Zeit gilt als vorbei.
- „in zwei Tagen um zehn“, „ein Uhr nachts“, „zwölf in der Nacht“, „zehn nach drei“, „fünf vor acht“, „24 Uhr“,
  „eineinhalb Stunden“, „in einer Woche“, 29. Februar, Jahreszahl in der Ansage.
- **Radio-Intent schluckte Antworten** („Wien“ im Rätsel, „Tabletten“ im Erinnerungsdialog) und Hörbuchwünsche
  („spiel Der Hobbit“) → ohne Sendertreffer zuerst laufender Dialog, dann Hörbuch-/Sendungssuche; bloße
  Ortsnamen nicht mehr als Slot-Synonyme, Beispielsatz nur „{station}“ entfernt.
- **Veralteter Radio-Token** übernahm „nächstes Kapitel“/„was läuft“ → nur bei laufender/pausierter Wiedergabe;
  „von vorn“ startet den Sender neu.
- **Kärntnerisch „na klar/na freilich“** galt als Nein → „na“ nur allein oder mit Nein-Wort; „jo“, „eh“, „sicher“ = ja.
- **Ungefragte Erinnerungsdialoge** durch „um acht“/„am Sonntag“ im Gespräch → eigener `ReminderTimeIntent`,
  der nur im Dialog wirkt (sonst wie bisher „nicht verstanden“).
- **`QuizAnswerIntent` als Sammelbecken** (Trägerwort ging verloren, Hintergrundgeräusche an die KI) → Träger-ähnliche
  Beispielsätze entfernt; außerhalb eines Dialogs wie Fallback (keine KI-Kosten, Abbruchzähler wirkt).
- Endlose Nachfrage im Dialog → nach zwei unverständlichen Antworten freundlich aufgeben; „zehn“ als Antwort auf
  „Wann?“ wird verstanden; „Abbrechen“ im Dialog beendet nur den Dialog; „genug“ im Rätsel beendet nicht die
  Superkugel; „ja/nein“ im Rätsel ist kein Fehlversuch.
- **Rätsel-Fehlerkennungen** („siebzehn“ für 7, „Eile“ für Weile, „Laute“ für Leute) → Zahlen nie unscharf, Wörter
  aus der Frage zählen nicht, strengere Ähnlichkeit für kurze Wörter; „fünf und siebzig“ wird erkannt.
  Sammlung aufgebraucht → frisch erzeugte leichte Rechnungen (nie „keine Rätsel mehr“).
- **Token bei Weiterleitungen**: urllib hätte den `Authorization`-Header weitergegeben → Weiterleitungen werden nicht
  befolgt, Antwortgröße begrenzt; unbekannte Zeitzone in der Liste stürzt nicht mehr ab.
- **Erinnerungen über das gemeinsame Admin-Konto**: die API liefert alle Erinnerungen des Skills im Konto → Liste und
  Löschen nur für die an **diesem Gerät** angelegten (`USER#…/REMINDERS`, nur Kennungen, TTL 400 Tage).
- Letzter Radiosender mit TTL 30 Tage; Speicherlayout dokumentiert; Test prüft den **ganzen** Speicher auf
  Erinnerungstext (auch über das KI-Werkzeug).
- Morgengruß-Wortliste ergänzt („Doppelmord“, „tödlich“, „ums Leben“, „Bluttat“ …); Monatskosten im Bericht für den
  Monat der Berichtswoche; Gesundheitsprüfung fällt auf GET zurück, wenn ein Server HEAD ablehnt.

Bewusst nicht umgesetzt (mit Begründung):
- **Sprach-Berechtigung (AskFor)** statt Karte – de-DE-Unterstützung nicht dokumentiert; offen für später.
- **Neustart eines abgebrochenen Live-Streams** (`PlaybackFailed`) – Risiko einer Wiederholschleife; sie sagt
  einfach erneut „Spiel Radio Kärnten“. Häufung zeigt der Alarm `PlaybackFailed`.
- **Auswahl beim Löschen über den Text** („die vom Arzt“) – Nummernauswahl reicht für ≤ 5 Einträge.
- **AMAZON.TIME „04:00“** (z. B. „vier Uhr früh“ über den Slot-Intent) wird als 16 Uhr gedeutet – Alexa liefert für
  „um vier“ denselben Wert; die Bestätigung nennt die Uhrzeit, „nein, in der Früh“ korrigiert.
- **Zusammenlegen von PREFS/DAYFLAGS** (spart ein GetItem beim Start) – Latenz ohnehin < 0,2 s.
- Wiederkehrende Erinnerungen, Inhalt nach „dass“ grammatisch umformen.

Außerhalb des Codes (→ Freigabeliste): Die **Alarm-E-Mail des Admins steht als Autor-Adresse im README-Commit
`81850c6`** auf GitHub (Web-Editor); zwei **lokale Archiv-Zweige** (`archiv/*`) enthalten Konto-ID, Vorname und Wohnort
– nie mit `--all`/`--mirror` pushen.

## Grenzen

- Nur einzelne Erinnerungen, keine wiederkehrenden. Superkugel ersetzt **keine** Medikamenten- oder
  Notfallerinnerung mit Gewähr (Echo ohne Strom/WLAN, Berechtigung entzogen, Amazon-Störung).
- Erinnerungen gehören zum **Amazon-Konto des Admins** (Kontomodell) und erscheinen auch in dessen Alexa-App;
  Laut Doku sind Erinnerungen gerätebezogen (Limit pro Gerät) – dass sie am Echo der Nutzerin klingeln, auf dem sie
  angelegt wurden, ist **am Gerät zu prüfen** (Prüfpunkt 36).
- Spracherkennung freier Sätze ist Alexa-abhängig; ungewöhnliche Formulierungen führen zur Nachfrage „Wann …?“.
- ORF-Streams können sich ändern; tote Sender meldet der Wochenbericht, die Liste pflegt der Admin im Code.
- Wochenbericht geht an dieselbe Adresse wie die Alarme.
