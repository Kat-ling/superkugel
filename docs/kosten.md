# Kosten

Preise Stand 25.10.2026, USD, Region eu-north-1 (Stockholm). 1 USD ≈ 0,9 EUR.

## Vorgabe

**Gesamtkosten höchstens 1 $ pro Tag und 15 $ pro Monat.** Umsetzung siehe „Grenzen“ unten.

## Grundlagen

- `gpt-6-luna`: 0,10 $ / 1 Mio. Eingabe-Tokens, 0,01 $ gecacht, 0,50 $ / 1 Mio. Ausgabe.
- **Gemessen** (25.10.2026): ein Gesprächswechsel ≈ 685 Eingabe- / 66 Ausgabe-Tokens ≈ **0,0001 $**.
  Mit Nachrichten/Wetter im Prompt (+ ≈ 225 Tokens, live gemessen) ≈ 0,00012 $.
- **Websuche**: 10 $ pro 1.000 Aufrufe + Suchergebnis-Tokens zum Eingabepreis. Der Skill bucht vorsichtig
  **0,012 $ pro Suche** (mit Puffer für die Suchergebnisse).
- Annahme: 3 Wortwechsel pro Gesprächsminute, 10–30 % davon brauchen eine Suche.
- Nachrichten, Wetter, Podcast-Feeds, Podcast Index: kostenlos. Stündlicher Abruf in AWS: im Freikontingent.

## Monatlich (Schätzung)

| Gespräch/Tag | Ratschen | + Aktuelles (A) | + Websuche (B, max. 25/Tag) | AWS | **Summe** |
|---|---|---|---|---|---|
| 10 min | 0,09 $ | +0,02 $ | 1,10–3,30 $ | ≈ 0,30 $ | **≈ 1,50–3,70 $** |
| 30 min | 0,27 $ | +0,06 $ | 3,30–9,00 $ | ≈ 0,30 $ | **≈ 3,90–9,60 $** |
| 60 min | 0,54 $ | +0,12 $ | 9,00 $ (Deckel 25/Tag) | ≈ 0,30 $ | **≈ 10,00 $** |

AWS: Lambda/DynamoDB/S3-Streaming im Always-Free-Rahmen; S3-Speicher ≈ 0,10 $; 7 eigene CloudWatch-Metriken
(≤ 10 sind frei; Metriken werden nur bei Ereignissen geschrieben); Rest Cent-Beträge.
Podcast-Folgen streamt der Echo direkt beim Anbieter – keine AWS-Kosten.

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
