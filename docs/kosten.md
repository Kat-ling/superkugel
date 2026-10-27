# Kosten

Preise Stand 25.10.2026, USD, Region eu-north-1 (Stockholm). 1 USD ≈ 0,9 EUR.

## Vorgabe

**Gesamtkosten höchstens 1 $ pro Tag und 15 $ pro Monat.** Umsetzung siehe „Grenzen“ unten.

## Grundlagen

- `gpt-6-luna`: 0,10 $ / 1 Mio. Eingabe-Tokens, 0,01 $ gecacht, 0,50 $ / 1 Mio. Ausgabe.
- **Gemessen** (25.10.2026): ein Gesprächswechsel v1.0 ≈ 685 Eingabe- / 66 Ausgabe-Tokens ≈ **0,0001 $**.
  v1.1 (Websuche angeboten, Nachrichten/Wetter im Prompt) ≈ 6.000 Eingabe-Tokens: **0,0006 $** ohne Cache,
  **0,00008 $** wenn der Prompt im Cache liegt (Folgefragen kurz danach). Rechenwert unten: 0,0002 $ pro Wechsel.
  Live wurden bei einer Antwort mit Websuche 2 Suchvorgänge gemeldet (0,024 $) – der Skill zählt und bucht jeden.
- **Websuche**: 10 $ pro 1.000 Aufrufe + Suchergebnis-Tokens zum Eingabepreis. Der Skill bucht vorsichtig
  **0,012 $ pro Suche** (mit Puffer für die Suchergebnisse).
- Annahme: 3 Wortwechsel pro Gesprächsminute, 10–30 % davon brauchen eine Suche.
- Nachrichten, Wetter, Podcast-Feeds, Podcast Index: kostenlos. Stündlicher Abruf in AWS: im Freikontingent.

## Monatlich (Schätzung)

| Gespräch/Tag | Ratschen inkl. Aktuelles | + Websuche (B, max. 25/Tag) | AWS | **Summe** |
|---|---|---|---|---|
| 10 min | 0,18 $ | 1,10–3,30 $ | ≈ 0,30 $ | **≈ 1,60–3,80 $** |
| 30 min | 0,54 $ | 3,30–9,00 $ | ≈ 0,30 $ | **≈ 4,10–9,80 $** |
| 60 min | 1,08 $ | 9,00 $ (Deckel 25/Tag) | ≈ 0,30 $ | **≈ 10,40 $** |

AWS: Lambda/DynamoDB/S3-Streaming im Always-Free-Rahmen; S3-Speicher ≈ 0,10 $; 7 eigene CloudWatch-Metriken
(≤ 10 sind frei; Metriken werden nur bei Ereignissen geschrieben); Rest Cent-Beträge.
Podcast-Folgen streamt der Echo direkt beim Anbieter – keine AWS-Kosten.

## Version 1.2 (Erinnerungen, Radio, Morgengruß, Rätsel, Wochenbericht)

| Posten | Wirkung | Kosten |
|---|---|---|
| Erinnerungen, Radio, Morgengruß, Rätsel | **ohne KI-Aufruf** (deterministisch); Radio streamt der Echo direkt beim ORF | 0 $ |
| Zwei neue KI-Werkzeuge (`play_radio`, `set_reminder`) + Senderliste im Prompt | ≈ 150 Eingabe-Tokens mehr pro Gesprächsfrage, meist aus dem Prompt-Cache | ≈ 0,000015 $/Frage ungecacht, ≈ 0,05 $/Monat bei 100 Fragen/Tag |
| „Erklär mir das“ im Rätsel | normale Gesprächsfrage, innerhalb der bestehenden Tages-/Monatsgrenzen | ≈ 0,0002 $ |
| DynamoDB: Tageszähler, Tagesmerker, Rätsel-Liste | ≈ 1–3 zusätzliche Schreibzugriffe pro Sitzung | Always-Free (25 WCU) |
| Stündliche Radio-Prüfung (4 HEAD-Anfragen, ≈ 0,3 s) im bestehenden Abruf | – | Always-Free |
| Wochenbericht: 1 EventBridge-Regel (2 Auslösungen/Woche), 1 SNS-Mail | – | frei (SNS: 1.000 Mails/Monat frei) |
| CloudWatch: 3 neue Metriken → **10 gesamt**, 2 neue Alarme → 10 Alarme | Metriken nur bei Ereignissen | frei (10 Metriken, 10 Alarme) |

**Wirkung auf die Vorgabe: praktisch null** – die Grenzen (≤ 1 $/Tag, ≤ 15 $/Monat) bleiben unverändert und hart.

## Grenzen (Sperren vs. Warnungen)

| Mechanismus | Wert | Art | Wirkung |
|---|---|---|---|
| Suchen pro Antwort (`max_tool_calls`) | 1 | **harte Sperre** | eine Frage kostet höchstens eine Suche |
| Suchen pro Tag (`WEB_SEARCH_DAILY_LIMIT`) | 25 (Wiener Zeit) | **harte Sperre** | danach Websuche aus, Ratschen geht weiter; max. 0,30 $/Tag |
| Reserve-Prüfung vor jeder Suche | Suche nur, wenn sie das Tages-/Monatslimit nicht überschreitet | **harte Sperre** | – |
| KI-Kosten pro Tag inkl. Suche (`DAILY_COST_LIMIT_USD`) | **0,90 $**, im Code auf max. 0,95 $ gedeckelt | **harte Sperre** | KI aus, Hörbücher gehen weiter |
| KI-Kosten pro Monat (`MONTHLY_COST_LIMIT_USD`) | **14 $**, im Code auf max. 14,50 $ gedeckelt | **harte Sperre** | KI aus bis Monatsende |
| Zähler nicht lesbar | – | Websuche **aus** (teuer), Ratschen an (≈ 0,0001 $/Frage) | Prepaid bleibt letzte Grenze |
| Abgebrochene Anfrage (Zeitüberschreitung) | sofort vorsichtig gebucht (geschätzte Tokens + 1 Suche, falls angeboten) | Zählung | lieber zu hoch als zu niedrig |
| Mediensuche pro Tag | 50 | Sperre (kostenlos, Schutz vor Missbrauch) | – |
| OpenAI-Prepaid ohne Auto-Recharge (+ Projekt-Limit 14 $/Monat empfohlen) | Guthaben | **harte Sperre** bei OpenAI | „klappt gerade nicht“ |
| Circuit-Breaker | 3 Fehler → 5 Min. | technische Sperre | keine Dauerschleifen |
| Alarm Tageskosten | > 0,60 $ | Warnung (Mail) | Vorwarnung vor der harten Grenze |
| Alarm langsame Antworten | ≥ 3 × > 6,5 s pro Stunde | Warnung (Mail) | – |
| AWS-Budget (Management-Konto) | 5 $/Monat | Warnung (Mail) | stoppt nichts |

Damit gilt: KI ≤ 0,90 $/Tag + AWS ≈ 0,01 $/Tag → **< 1 $/Tag**; KI ≤ 14 $/Monat + AWS ≈ 0,30 $ → **< 15 $/Monat**.
Hinweis: Der Zähler ist eine Schätzung aus den von OpenAI gemeldeten Tokens. Die verbindliche Obergrenze
bei OpenAI selbst ist das Prepaid-Guthaben.
