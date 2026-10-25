# Kosten

Preise Stand 24.10.2026, USD, Region eu-north-1. 1 USD ≈ 0,9 EUR.

## Annahmen

- 3 Wortwechsel pro Gesprächsminute.
- Pro Anfrage ca. 1.500 Eingabe-Tokens (Systemprompt ~900 inkl. Bibliothek mit ≈ 10 Titeln + bis zu 8 Wortwechsel Verlauf;
  jeder weitere Titel kostet ≈ 35 Tokens pro Anfrage, 60 Titel ≈ +1.800 Tokens → Kosten etwa ×2)
  und ca. 80 Ausgabe-Tokens. Prompt-Caching **nicht** eingerechnet (würde Eingabekosten senken).
- `gpt-6-luna`: 0,10 $ / 1 Mio. Eingabe, 0,50 $ / 1 Mio. Ausgabe.
- Hörbücher: 2 h pro Tag bei 128 kbit/s (≈ 58 MB/h).

Pro Gesprächsminute: 4.500 × 0,10/1e6 + 240 × 0,50/1e6 ≈ **0,00057 $**.

## Monatlich

| Posten | 10 min/Tag | 30 min/Tag | 60 min/Tag |
|---|---|---|---|
| OpenAI (300 / 900 / 1.800 min) | 0,17 $ | 0,51 $ | 1,03 $ |
| Lambda (Always-Free: 1 Mio. Aufrufe, 400.000 GB-s) | 0 $ | 0 $ | 0 $ |
| DynamoDB On-Demand (einige 10.000 Schreibvorgänge), monatliches On-Demand-Backup | < 0,05 $ | < 0,05 $ | < 0,10 $ |
| S3 Speicher (10 Hörbücher ≈ 4 GB) | 0,09 $ | 0,09 $ | 0,09 $ |
| S3 Streaming (~3,5 GB/Monat; 100 GB/Monat Datentransfer Always-Free) | 0 $ | 0 $ | 0 $ |
| CloudWatch (Logs < 5 GB, 5 Alarme < 10 frei), SNS, SSM Standard, Budgets | 0 $ | 0 $ | 0 $ |
| Alexa-Skill | 0 $ | 0 $ | 0 $ |
| Externe TTS | – (nicht verwendet) | – | – |
| Thalia-Synchronisation (läuft auf deinem PC) | 0 $ | 0 $ | 0 $ |
| **Summe laufend** | **≈ 0,30 $** | **≈ 0,65 $** | **≈ 1,25 $** |

Einmalig/variabel: Hörbücher je Titel (Thalia-Einzelkauf, typ. 10–25 €), OpenAI-Mindestaufladung (z. B. 5 $),
die bei dieser Nutzung viele Monate reicht. Neue AWS-Konten haben je nach Anmeldedatum ein
Guthaben-Modell statt 12-Monate-Free-Tier – die oben genutzten Always-Free-Kontingente gelten unabhängig davon.

**Unsicherheit:** Die Token-Zahlen sind Schätzungen. Echte Werte: `superkugel_admin.py usage`.

## Sperren vs. Warnungen

| Mechanismus | Art | Wirkung |
|---|---|---|
| OpenAI-Prepaid ohne Auto-Recharge | **harte Sperre** | Ist das Guthaben leer, lehnt OpenAI ab → Skill sagt „klappt gerade nicht“, Sitzung endet |
| `DAILY_COST_LIMIT_USD` (0,50 $) / `MONTHLY_COST_LIMIT_USD` (8 $) im Skill | **harte Sperre** (auf Basis der Schätzung; auch abgebrochene, aber bezahlte Anfragen werden nachgezählt; ist der Zähler selbst nicht lesbar, greift nur noch das Prepaid) | KI aus, Hörbücher gehen weiter |
| Circuit-Breaker (3 Fehler → 5 Min. Pause) | technische Sperre | verhindert Dauerschleifen gegen eine kaputte API |
| `ReservedConcurrency` (optional) | technische Sperre | begrenzt gleichzeitige Aufrufe |
| Modus `audiobooks_only` / `maintenance` | manueller Schalter | sofort wirksam (≤ 1 Min.) |
| CloudWatch-Alarm Tageskosten > 0,30 $ | **nur Warnung** | E-Mail |
| AWS Budget 5 $/Monat (80 % / Prognose 100 %) – von Hand in *Abrechnung → Budgets* anlegen (CloudFormation kann Budgets in Stockholm nicht anlegen) | **nur Warnung** | E-Mail, stoppt **nichts** |
