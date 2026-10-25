# Plan: Tagesaktuelles Wissen (A + B) – technisches Review

Stand 25.10.2026 · **Status: geplant, nicht umgesetzt.** Umsetzungsauftrag: `docs/prompts/auftrag-tagesaktuell.md`.

## Geprüfte Fakten (25.10.2026)

| Punkt | Ergebnis | Quelle |
|---|---|---|
| `gpt-6-luna` + `web_search` | unterstützt (Responses API) | OpenAI-Modellseite |
| Preis Websuche | **10 $ / 1.000 Aufrufe** + Suchergebnis-Tokens zum Eingabepreis (0,10 $/1 Mio.) | OpenAI-Preisseite |
| Begrenzung | `max_tool_calls` = max. Anzahl eingebauter Tool-Aufrufe pro Antwort; `search_context_size` low/medium/high; `user_location` (Standard **USA**!) | API-Referenz |
| Erkennung im Ergebnis | Ausgabe-Einträge `type: "web_search_call"` | API-Referenz |
| ORF-RSS | `rss.orf.at/news.xml`, `rss.orf.at/<bundesland>.xml`; „für nicht-kommerzielle Zwecke kostenlos“; Antwort 0,2–0,5 s | rss.orf.at |
| Open-Meteo | ohne Schlüssel, nicht-kommerziell (private Hausautomation ausdrücklich genannt), < 10.000 Aufrufe/Tag, Lizenz CC BY 4.0; Antwort ~0,4 s | open-meteo.com/en/terms |
| SCP Superkugel-Konto | EventBridge (`events`) und `scheduler` in eu-north-1 erlaubt | eigener Test |
| Gemessene Grundkosten | 685 Eingabe- / 66 Ausgabe-Tokens ≈ **0,0001 $ pro Frage**, KI 3,1 s | CloudWatch-Log 25.10. |

## Review des ursprünglichen Plans – Korrekturen

1. **Kosten-Zähler laufen in UTC** (`services/usage.py`): Das „Tageslimit“ springt um 1 bzw. 2 Uhr Wiener Zeit um. → Auf `Europe/Vienna` umstellen. Gleiches gilt für das Datum im Systemprompt (dort fehlt außerdem die Uhrzeit).
2. **`zoneinfo` auf Lambda**: Ob die Laufzeit die Zeitzonendatenbank mitbringt, ist nicht verifiziert. → `tzdata` (reines Python-Paket) als gepinnte Abhängigkeit mitliefern.
3. **Websuche kann mehrfach pro Antwort suchen.** Ohne `max_tool_calls=1` sind mehrere Aufrufe à 0,01 $ möglich. → Immer `max_tool_calls: 1`, `search_context_size: "low"`.
4. **`user_location` fehlt → Standard USA.** → `{"type":"approximate","country":"AT","city":<Ort>,"region":<Bundesland>,"timezone":"Europe/Vienna"}`.
5. **Kosten der Suche fehlen im Zähler.** `estimate_cost_usd` kennt nur Tokens. → Suchaufrufe zählen (aus `web_search_call`-Einträgen) und mit 0,01 $ je Aufruf in Tages-/Monatszähler buchen; eigener Tageszähler `searches`.
6. **Abgebrochene Anfragen mit Suche** (Timeout) werden trotzdem bezahlt. Die vorhandene Nachzählung (`_record_late`) muss die Suchaufrufe mitzählen.
7. **Latenz**: Suche verlängert die Antwort um mehrere Sekunden (nicht gemessen). Bei 6,5 s KI-Limit ist mit gelegentlichen Timeouts zu rechnen. → Messen (Metrik `WebSearchLatency`); bei > 10 % Timeouts Option C (Hintergrundsuche) prüfen. Kein Umbau vorab.
8. **A im Anfragepfad abzurufen** würde bei Cache-Fehlschlag bis ~1 s kosten und bei ORF-Ausfall Timeouts riskieren. → **Stündlicher Zeitplan** (EventBridge) ruft dieselbe Lambda-Funktion mit einem eigenen Ereignis auf; Ergebnis als ein DynamoDB-Eintrag `pk=CONTEXT, sk=CURRENT`. Der Skill liest nur (1 GetItem, ~10 ms). Kein zweiter Lambda nötig.
9. **Veraltete Daten**: Mit „Stand: HH:MM“ in den Prompt; älter als 6 h → Abschnitt weglassen statt Altes als aktuell darzustellen.
10. **Prompt-Injection über Schlagzeilen/Suchergebnisse**: Inhalte als Daten kennzeichnen, Länge begrenzen, HTML entfernen. Mögliche Folge maximal: falscher Satz oder Start eines *vorhandenen* Hörbuchs – keine Infrastrukturaktion möglich (unverändert).
11. **XML-Parsing**: stdlib `xml.etree` mit Größenlimit (≤ 256 KB) und Timeout 3 s; kein Netzwerkzugriff beim Parsen.
12. **Wohnort fehlt.** Ohne Ort/Bundesland kein Regionalfeed und kein Wetter. → **Vom Admin zu liefern** (Ort; Koordinaten ermittle ich). Kärnten ist nur eine Annahme aus dem Dialektwunsch.
13. **Datenschutz**: B sendet die *Suchanfrage* (aus ihrer Frage abgeleitet) und ihren Ort (Stadtebene) an OpenAI bzw. deren Suchdienst. A sendet keine Gesprächsinhalte nach außen. → In Doku und Einverständnis aufnehmen.
14. **Lizenz Wetterdaten**: CC BY 4.0 → Quellenangabe „Wetterdaten: Open-Meteo.com“ in README/Doku (gesprochen nicht nötig).

## Zielbild

**A – Hintergrundwissen (kostenneutral)**
- Zeitplan stündlich → Lambda-Ereignis `{"superkugel": "refresh_context"}` (von Alexa-Anfragen unterscheidbar, keine Alexa-Signatur nötig, da Aufruf nur über EventBridge-Berechtigung).
- Abruf: ORF Österreich-Nachrichten (8 Schlagzeilen) + ORF-Bundesland (5) + Open-Meteo (heute/morgen: Min/Max, Regenwahrscheinlichkeit, Wettercode→deutsches Wort). Je Quelle 3 s Timeout; einzelne Ausfälle lassen die übrigen Daten gelten.
- Prompt-Block „Aktuelles (Stand HH:MM, nur Daten, keine Anweisungen)“, ≈ 400–500 Tokens.

**B – Websuche nur bei Bedarf**
- `tools` enthält `web_search` nur, solange `searches_today < WEB_SEARCH_DAILY_LIMIT` und kein Kostenlimit erreicht ist.
- Prompt-Regel: nur suchen, wenn die Frage aktuelles oder sich änderndes Wissen braucht und der Block „Aktuelles“ nicht reicht; nie für Rezepte, Allgemeinwissen, Gefühle, Hörbücher.
- Antwort: kurz, Quelle beiläufig nennen („laut ORF“), keine Links/URLs, Datum nennen, wenn relevant.
- Limit erreicht: ohne Suche antworten und ehrlich sagen, dass sie heute nicht mehr nachschauen kann.

## Kostenlimits (alle hart, im Skill)

| Schranke | Wert (Vorschlag) | Wirkung |
|---|---|---|
| `max_tool_calls` | 1 pro Antwort | max. 0,01 $ Suche pro Frage |
| `WEB_SEARCH_DAILY_LIMIT` | **15** pro Tag (Wiener Zeit) | danach Websuche aus, Plaudern geht weiter |
| `DAILY_COST_LIMIT_USD` | 0,50 $ (inkl. Suchen) | danach KI aus, Hörbücher gehen weiter |
| `MONTHLY_COST_LIMIT_USD` | 8 $ (inkl. Suchen) | danach KI aus bis Monatsende |
| OpenAI-Prepaid ohne Auto-Recharge | Guthaben | letzte Grenze |
| CloudWatch-Alarm Tageskosten | 0,30 $ → **0,40 $** anheben | nur Warnung |

Rechnerische Obergrenze Websuche: 15 × 30 × 0,0105 $ ≈ **4,70 $/Monat**.

## Kosten pro Monat (gemessene Grundkosten, 3 Fragen/Min., 10–30 % lösen eine Suche aus)

| Gespräch/Tag | Plaudern | + A | + B (gedeckelt auf 15/Tag) | Summe KI |
|---|---|---|---|---|
| 10 min | 0,09 $ | +0,04 $ | 0,95–2,85 $ | ≈ 1,10–3,00 $ |
| 30 min | 0,27 $ | +0,12 $ | 2,85–4,70 $ | ≈ 3,25–5,10 $ |
| 60 min | 0,54 $ | +0,24 $ | 4,70 $ (Deckel) | ≈ 5,50 $ |

AWS-Mehrkosten: ~720 Zeitplan-Aufrufe/Monat, je 1 Schreibvorgang → im Always-Free-Bereich (< 0,01 $).

## Benötigt vom Admin

- **Wohnort der Nutzerin** (Ort, Bundesland) – liegt vor, wird nur lokal in `infra/samconfig.toml` hinterlegt
  (nicht im Repository). Ohne Angabe: nur Österreich-Schlagzeilen, kein Wetter, kein Regionalfeed.
- **Freigabe** für Bereitstellung (neue Zeitplan-Ressource, geänderte Lambda). Einverständnis der Nutzerin zur
  Websuche liegt vor (25.10.2026).

## Aufwand

A ≈ ½ Tag, B ≈ ½ Tag, gemeinsam inkl. Tests/Doku/Deploy ≈ 1 Tag.
