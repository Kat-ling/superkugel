# Projektstatus – Superkugel

**Stand:** 9.11.2026 · **Version 1.7.1 bereitgestellt (Lambda), Interaction Model neu laden, Gerätetest offen.** **Version 1.5 (Orte besser verstehen, kürzere Antworten): bereitgestellt (Change Set am
31.10.2026 ausgeführt), live per Lambda-Aufruf getestet; Interaction Model in der Developer Console neu laden.** Version 1.4 (Fahrplanauskunft) bereitgestellt, Fahrplan gültig bis 12.12.2026, auf GitHub (Tag
`v1.4.0`). Version 1.0 ist im Alltag auf einem Echo Dot 5 in Betrieb.

## Version 1.7.1 (9.11.2026) – Hörbuch nur, wenn gewünscht: bereitgestellt, live per Lambda geprüft, Gerätetest offen

Gerätetest am Wochenende: Die KI startete bei Fragen nach Podcasts oder bei Missverständnissen ein Hörbuch, weil
sie für Hörwünsche nur `play_audiobook` hat (Podcast-Suche ohne Schlüssel, keine Lieblingssendungen). Jetzt startet
der Code ein Hörbuch der KI nur direkt, wenn der Satz das Buch nennt (Titel, Autor, Reihe), „weiter“ beim
angefangenen Buch sagt oder mit „Spiel …“ begann (`audio.from_ai`). Sonst fragt die Superkugel: „Möchtest du … hören?“
Der Prompt verbietet ein Hörbuch als Ersatz. Kein neuer Intent, Sprachmodell bleibt. Prüfpunkt 75.

## Version 1.7.0 (6.11.2026) – Minutengenau springen, Buch von vorne: bereitgestellt, live per Lambda geprüft, Gerätetest offen

„Zehn Minuten zurück“ und „fünf Minuten vor“ springen über beliebig viele Kapitel (`player.jump`, Dauer aus
`AMAZON.DURATION`). „Fang das Buch von vorne an“ fragt nach, wenn eine Hörstelle verloren ginge. Neue Intents
`JumpBackIntent`, `JumpForwardIntent`, `RestartBookIntent` → **Interaction Model neu laden**. Prüfpunkte 73 und 74.

## Version 1.6.0 (5.11.2026) – Reise-Stand und Nachrichten: bereitgestellt, live per Lambda geprüft, Gerätetest offen

Schritte 2 und 3 von `docs/plan-fahrplan-dialog.md` sind fertig: Reise-Stand (`transit/trip.py`) ersetzt
`transit_last`, „gegen zehn“ und „am Freitag“ ändern nur Zeit oder Tag, die Reise übersteht „Stopp“ 30 Minuten.

Nachrichten fertig: Vorrat aus ORF-Feeds (`services/news.py`), Werkzeug `nachrichten`, keine Wiederholung für
36 Stunden, Regionales und Interessen zuerst, Aufregendes als Beimischung, Websuche nur bei Ort oder Thema ohne Treffer.
Neue Trägerwörter → **Interaction Model neu laden**. KI-Dolmetscher (Schritte 4 bis 9) offen.

## Version 1.5.2 (5.11.2026) – „Danke“ korrigiert: bereitgestellt, live per Lambda geprüft, Gerätetest offen

Beim Gerätetest löste „Danke“ eine Rückfahrt aus: Das Log zeigt `TransitBackIntent`, vermutlich als ähnlichster kurzer
Befehl. Dieser Befehl entfällt. Neu ist `ThanksIntent` („danke“, „passt“); er beendet das Fahrplan-Thema mit „Gerne.“,
ohne Fahrplan-Thema geht der Satz ans Gespräch. Neue Trägerwörter: „gegen“, „später“, „früher“, „lieber“, „eher“,
„danach“, „wieder“, „zurück“ → **Interaction Model neu laden**. „Und zurück?“ bleibt; ob ein einzelnes „zurück“ noch
ankommt, zeigt der Gerätetest. Weiterer Plan: `docs/plan-fahrplan-dialog.md`.

## Version 1.5.1 (5.11.2026) – Fahrplan-Dialog korrigiert: bereitgestellt, live per Lambda geprüft, Gerätetest offen

Anlass: Prüfbericht nach den Arbeitsmethoden von `obra/superpowers`. Die Fehler wurden zuerst als fehlschlagende
Tests nachgestellt, dann behoben.

- Folgefragen („danach“, „genauer“) gelten nur noch als ganzer kurzer Satz; nach einer KI-Antwort ist das
  Fahrplan-Thema beendet. „Dann mach ich mir einen Kaffee“ geht an die KI.
- Ein neues Ziel gewinnt („und der nächste Bus nach …“, „und dann nach …“); anderes Verkehrsmittel = neue Frage.
- Datum und relative Zeit: „am 20. November“, „am 20.“, „in zwei Stunden“, „in drei Tagen“, „nächsten Dienstag“,
  „am Abend“. Unklare Tage („nächste Woche“, „zu Weihnachten“) → Rückfrage „Welchen Tag?“, die Antwort ergänzt die Frage.
- Reisesätze ohne KI nur für die Sprecherin selbst: keine Verneinung, kein „zu Fuß“, kein Umzug, nichts Vergangenes.
- „Und zurück?“: Rückfahrt ohne KI, Orte aus der letzten Auskunft, Start 10 Minuten nach der Ankunft, gleicher Tag.
  Neu: die Trägerwörter „am“, „um“, „in“ → **Interaction Model neu laden**.
- Fahrplan-Import: Ein Paket, das noch nicht gilt, wartet unter `TRANSIT/NEXT`; die Lambda wechselt ab dem Startdatum
  von selbst. Abgelaufene Pakete werden abgelehnt, Lücken gemeldet.

## Version 1.5 (31.10.2026) – Orte besser verstehen, kürzere Antworten

Anlass: „Ich möchte morgen nach … fahren“ mit Zusatz („… bei <Stadt>“) wurden nicht erkannt; lange Ansagen.

- **Tolerantere Ortssuche** (`transit/places.py`): Zusätze wie „bei X“ oder „in Tirol“ wählen nur unter
  gleichnamigen Orten aus (nächster Treffer zu X bzw. zur Mitte des Bundeslands); folgen dem Namen weitere Wörter,
  zählt der längste bekannte Anfang; Stoppwörter („in“, „bei“) stören den Namensvergleich nicht mehr; Einrichtungen
  wie „Krankenhaus“ finden auch „LKH …“ (nächstgelegene).
- **Reisesätze ohne KI** (`transit/ask.py: travel_dest`): „ich möchte/will/muss … nach X (fahren)“, „zu meiner
  Tochter nach X“ – nur wenn X eine bekannte Haltestelle ist (ganze Wörter, keine Annäherung), sonst KI.
- **„In die Stadt“**: Zentrum des Heimatorts = Bushaltestelle mit den meisten Abfahrten im Heimatort, aus den
  Fahrplandaten berechnet (keine feste Haltestelle). Die KI ordnet freie Formulierungen selbst zu („zum Einkaufen
  in die Innenstadt“ → `Stadtzentrum`, „ins Krankenhaus“ → `Krankenhaus`). Datenschutz: Es gehen weiterhin keine
  Orts- oder Haltestellennamen des Wohnorts an OpenAI – die Zuordnung zur echten Haltestelle macht der Code.
- **KI-Werkzeug abgesichert:** `ziel` nur der Ortsname, Zusatz im neuen Feld `naehe`; kennt der Fahrplan das Ziel
  der KI nicht, zählt der Originalsatz.
- **Rückfrage bei gleichnamigen Orten** (weiter als 40 km auseinander, keiner in der Nähe, kein Alias): „Meinen Sie
  Sankt Johann in Tirol?“ → „Ja“, „Nein“ (nächster Kandidat, dann Bitte um genauere Angabe) oder gleich „in Salzburg“.
- **Kürzere Antworten:** KI meist ein bis zwei Sätze (höchstens etwa 80 Wörter). Verbindungen mit Umstiegen zuerst als
  Kurzfassung (Abfahrt, Umstiegsorte, Ankunft, Dauer); „genauer“ (neuer `TransitDetailIntent`, auch „wo muss ich
  umsteigen“, „und dann“) sagt alle Abschnitte, „und danach?“ die nächste Verbindung.
- **Anleitungen:** Tipp „Einfach ‚Alexa‘ sagen – sie hört sofort auf und hört zu“ steht jetzt ganz oben auf
  Spickzettel und Kurzanleitung. („Stopp“ beendet die Superkugel weiterhin – bewusst so gelassen.)
- Tests: **246 bestanden**, `ruff` ohne Befund. Mit echten Daten am Admin-PC geprüft (kein Gerätetest): Ort mit
  Zusatz „bei …“, „in die Stadt“, „Krankenhaus“, gleichnamige Orte mit Rückfrage. **Kein Gerätetest** (Prüfpunkte 57–61).
- **Gemessen in AWS (31.10.2026, Testkennung per `aws lambda invoke`, kein Gerätetest):** Kaltstart + Reisesatz mit
  Zusatz „bei …“ 2,8 s (Init 0,9 s, Paket laden); „in die Stadt“ 0,08 s; Verbindung mit zwei Umstiegen (Kurzfassung)
  0,35 s; „genauer“ 0,29 s; Rückfrage gleichnamiger Ort 0,03 s, „Nein“ → nächster Kandidat, Antwort mit Bundesland
  und „Ja“ je 0,4–0,5 s; „Innenstadt“ über die KI → Werkzeug `Stadtzentrum` 3,2 s.
- Nach dem Bereitstellen: Interaction Model in der Developer Console neu laden (neuer Intent).

## Version 1.4 (31.10.2026) – Fahrplanauskunft Bus und Zug

Züge in ganz Österreich (ÖBB, WESTbahn u. a.), Kärntner Linien inkl. Rufbus-Zonen und Verkehrsverbund Tirol –
aus den GTFS-Sollfahrplänen der Mobilitätsverbünde Österreich. Ohne KI, ohne Echtzeit (keine Verspätungen).

- **Fragen:** „Wann fährt der nächste Bus?“, „… der nächste Zug nach Klagenfurt?“, „Wie komm ich morgen um halb
  neun nach …?“, „Wann geht der letzte Bus von … heim?“, „und danach?“. Freie Sätze laufen über die Trägerwörter
  und werden vor der KI erkannt; kurze Befehle („nächster Bus“, „letzter Zug“) haben eigene Intents; indirekte
  Fragen erkennt die KI und ruft das Werkzeug `fahrplan` auf – die Zeiten rechnet immer der Code.
- **Technik:** `superkugel_admin.py fahrplan import <ZIPs>` baut am PC ein Paket (15 MB, 3,1 Mio. Teilstrecken,
  12 069 Haltestellenbereiche, 59 Rufbus-Zonen) und lädt es nach S3; die Lambda lädt es einmal pro Container und
  sucht per Connection-Scan (vorwärts: früheste Ankunft, rückwärts: späteste Abfahrt). Umsteigezeit 5 Minuten,
  Fußwege bis 400 m großzügig gerechnet. Lambda-Speicher 1769 MB (= 1 vCPU).
- **Gemessen am Admin-PC (31.10.2026, echte Daten, kein Gerätetest):** Paket laden 0,3–0,9 s; Abfahrten 0,15 s;
  kurze Verbindungen 0,2–0,4 s; Heimat-Haltestelle → Ziel in Tirol (4 Fahrten, 3 Umstiege) 1,4–1,9 s.
- **Grenzen:** Daten gelten bis **12.12.2026** (Fahrplanwechsel) – danach neu herunterladen und importieren
  (Wochenbericht warnt 3 Wochen vorher). Rufbus-Gebiete als Fläche (GeoJSON, z. B. GO-Mobil) werden nicht
  ausgewertet; ein Rufbus in den Daten verkehrt laut Kalender nur an einem Tag (Datenlage, nicht korrigiert).
- **Datenschutz:** Heimat-Haltestelle, Heimatbahnhof und Ziel-Aliase nur in `infra/samconfig.toml`/`.env`
  (ignoriert); ins Log kommen nur Art und Dauer einer Auskunft, keine Orte.
- Tests: **231 bestanden** (neu: erfundener Testfahrplan in `tests/transit_fixture.py`); `ruff`, `cfn-lint`,
  `pip-audit` ohne Befund. **Kein Gerätetest** (Prüfpunkte 51–56).
- **Gemessen in AWS (31.10.2026, Testkennung per `aws lambda invoke`, kein Gerätetest):** Kaltstart + Paket laden +
  „nächster Bus“ 1,6 s (Init 0,7 s); Zug nach Klagenfurt 0,41 s; Verbindung nach Tirol (5 Fahrten) 0,85 s;
  „und danach?“ 0,79 s; letzte Verbindung heim 0,22 s; letzter Zug 0,06 s; unbekannter Ort 0,04 s. Keine KI-Kosten.
- Offen (✋ Admin): Interaction Model in der Developer Console neu laden (falls noch nicht geschehen), Gerätetest 51–56.

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
| Fahrplan (1.4) | Züge Österreich, Kärntner Linien inkl. Rufbus, VVT Tirol – Abfahrten, Verbindungen, letzte Verbindung |
| Schutz | harte Tages-/Monatskostengrenze, Circuit-Breaker, Fernschalter, Prepaid bei OpenAI, Budget-Warnung im Management-Konto |

Gemessen (25.10.2026, per `aws lambda invoke`): Kaltstart 0,8 s Init + 1,5 s; Gesprächsantwort 3,2 s gesamt
(KI 3,1 s) bei ≈ 0,0001 $ pro Frage. Signierte Audio-Links liefern `206 Partial Content`.

Gemessen v1.1 (25.10.2026, Testnutzer per `aws lambda invoke`, kein Gerätetest): Abruf 1,3 s, 3 Quellen ohne Fehler;
„Was gibt's Neues?“ aus dem ORF-Datenteil ohne Websuche, KI 2,0 s, 0,0006 $ (≈ 6.000 Eingabe-Tokens, davon
im Prompt-Cache 0,00008 $); Wetter 1,3 s; Frage mit Websuche 4,6 s, 0,024 $ (OpenAI meldete 2 Suchvorgänge –
beide gezählt). Live gefunden und behoben: erste Anfrage nach dem stündlichen Abruf erbte die Kaltstart-Uhr und
brach sofort ab; Nachrichtenfrage löste unnötige Websuche aus; Wetter wurde dem ORF zugeschrieben; Pause in „26. Oktober“.

## Tests

- `pytest`: **312 bestanden** (Stand 1.5.1; Python 3.14, Windows). Unit- und Integrationstests mit echten Alexa-Request-JSONs,
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
