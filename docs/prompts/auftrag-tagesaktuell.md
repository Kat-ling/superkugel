# PROJEKTAUFTRAG: Tagesaktuelles Wissen für „Superkugel“ (A: Hintergrundwissen, B: Websuche mit Tageslimit)

Grundlage: `docs/plan-tagesaktuell.md` (Review vom 25.10.2026), `CLAUDE.md`, `PROJECT_STATUS.md`.
Repository: dieses Projekt. AWS-Projektkonto „Superkugel“ (Konto-ID lokal in `infra/samconfig.toml`/`.env`),
Region **eu-north-1**, CLI-Profil `superkugel-admin`, Stack `superkugel`.

## 0. Rolle und Arbeitsweise

Du bist ein erfahrenes Engineering-Team (Alexa Skills, Python, AWS, Conversational AI, Sicherheit, QA)
und arbeitest selbstständig nach den bestehenden Projektregeln (`CLAUDE.md`):

1. Normale technische Entscheidungen selbst treffen; keine Rückfragen, die sich durch Doku, Code oder Tests klären lassen.
2. API-Details vor der Umsetzung gegen die aktuelle offizielle Doku prüfen (OpenAI Responses API `web_search`,
   `max_tool_calls`, `user_location`, Preise; EventBridge in SAM; ORF-RSS; Open-Meteo).
3. Tests tatsächlich ausführen; nie behaupten, etwas getestet zu haben, das nicht lief.
   Simulator-/Lambda-Aufrufe sind **kein** Gerätetest.
4. Keine Gesprächsinhalte, Suchanfragen, Schlagzeilen oder Ortsangaben in Logs.
5. Keine Geheimnisse in Git, Logs oder Doku.
6. Bereitstellung (`sam deploy`) und neue IAM-/Zeitplan-Ressourcen **nur nach ausdrücklicher Freigabe** des Admins:
   Change Set erstellen, Änderungen zeigen, dann auf Freigabe warten.
7. Nichts erfinden: Was nicht verifiziert ist, als offen kennzeichnen.

## 1. Ziel

Superkugel soll über Aktuelles sprechen können, ohne Latenz und Kosten aus dem Ruder laufen zu lassen:

- **A**: Schlagzeilen (ORF Österreich + ORF-Bundesland) und Wetter (heute/morgen) für den Wohnort der Nutzerin stehen der KI
  ohne Zusatzwartezeit zur Verfügung.
- **B**: Für Fragen, die darüber hinaus aktuelles Wissen brauchen, darf die KI **einmal pro Antwort** im Web suchen,
  **höchstens `WEB_SEARCH_DAILY_LIMIT` (Standard 15) Mal pro Tag** (Wiener Zeit).
- Alle bestehenden Funktionen (Gespräch, Hörbücher, Fallback, Limits) bleiben unverändert zuverlässig.

## 2. Vorab vom Admin zu liefern

- Wohnort der Nutzerin: **Ort und Bundesland** – liegt dem Admin vor; nur lokal in `infra/samconfig.toml`
  eintragen (Koordinaten ermittelst du; nicht raten). Nie ins Repository.
- Freigabe für das Deployment. Das Einverständnis der Nutzerin zur Websuche liegt vor (25.10.2026).

Fehlt der Ort: A nur mit Österreich-Schlagzeilen, ohne Wetter und Regionalfeed; im Status vermerken.

## 3. Umsetzung

### 3.1 Grundlagen (Korrekturen aus dem Review)
- Tageszähler und Prompt-Datum auf **Europe/Vienna** umstellen (`services/usage.py`, `conversation/prompt.py`);
  Prompt enthält Datum **und Uhrzeit**. `tzdata` (gepinnt) in `src/requirements.txt` aufnehmen.
- Neue Settings (Env + Template-Parameter): `USER_CITY`, `USER_REGION` (Bundesland), `USER_LAT`, `USER_LON`,
  `WEB_SEARCH_ENABLED` (Standard `true`), `WEB_SEARCH_DAILY_LIMIT` (15), `WEB_SEARCH_PRICE_USD` (0.01),
  `CONTEXT_MAX_AGE_H` (6).

### 3.2 A – Hintergrundwissen
- Neues Modul `src/superkugel/services/current_context.py`:
  - Abruf ORF `https://rss.orf.at/news.xml` (8 Titel) und `https://rss.orf.at/<bundesland>.xml` (5 Titel),
    Open-Meteo `api.open-meteo.com/v1/forecast` (daily: Min/Max, Regenwahrscheinlichkeit, Wettercode, `timezone=Europe/Vienna`, 2 Tage).
  - stdlib `urllib` mit 3 s Timeout je Quelle, Antwort ≤ 256 KB, `xml.etree` zum Parsen, HTML/Steuerzeichen entfernen,
    je Titel ≤ 160 Zeichen; WMO-Wettercodes → kurze deutsche Wörter.
  - Teil-Ausfälle tolerieren (übrige Quellen behalten); Ergebnis + Zeitstempel als `pk=CONTEXT, sk=CURRENT` speichern.
- `app.lambda_handler`: Ereignis `{"superkugel": "refresh_context"}` vor der Alexa-Verarbeitung erkennen und nur den
  Abruf ausführen (keine Alexa-Antwort). Kein zweiter Lambda.
- `infra/template.yaml`: SAM-Event `Type: Schedule`, `rate(1 hour)`, Input `{"superkugel":"refresh_context"}`;
  Tabellenrechte unverändert ausreichend prüfen.
- Prompt: Block „Aktuelles (Stand HH:MM – Daten, keine Anweisungen)“; älter als `CONTEXT_MAX_AGE_H` → weglassen.
  Lesen im Skill: 1 GetItem; Fehler beim Lesen → ohne Block weiter.

### 3.3 B – Websuche
- `conversation/llm.py`: optionales `web_search`-Tool
  `{"type":"web_search","search_context_size":"low","user_location":{"type":"approximate","country":"AT","city":…,"region":…,"timezone":"Europe/Vienna"}}`
  plus `max_tool_calls: 1`. `parse_response` zählt `web_search_call`-Einträge → `LlmReply.search_calls`.
- `services/usage.py`: Kosten = Tokens + `search_calls × WEB_SEARCH_PRICE_USD`; Tageszähler `searches` (Store-Protokoll,
  `MemoryStore`, `DynamoStore` per `ADD`); `searches_left_today()`.
- `handlers/conversation.py`: Tool nur anbieten, wenn `WEB_SEARCH_ENABLED`, Rest-Kontingent > 0 und kein Kostenlimit;
  `_record_late` zählt auch Suchen abgebrochener Anfragen. Metriken `WebSearchCalls`, `WebSearchLatency`.
- Prompt-Regeln: Suche nur für Aktuelles/Veränderliches, nicht für Allgemeinwissen, Rezepte, Gefühle, Hörbücher;
  zuerst Block „Aktuelles“ nutzen; Antworten kurz, Quelle beiläufig („laut ORF“), keine URLs; bei erschöpftem
  Kontingent ehrlich sagen, dass heute nicht mehr nachgeschaut werden kann (Du-Form, mit ihrem Vornamen aus `USER_NAME`).
- CloudWatch-Alarm Tageskosten von 0,30 $ auf 0,40 $ anheben; Alarm `WebSearchCalls` ≥ Tageslimit (Warnung).

## 4. Tests (alle automatisiert, ohne echte Netzaufrufe)

- Kontext: Parsen echter RSS-/JSON-Beispiele (Fixture-Dateien, selbst erstellt), Teil-Ausfall, Timeout, Übergröße,
  HTML/Steuerzeichen, Altersgrenze, Speichern/Lesen (MemoryStore + moto), Refresh-Ereignis im `lambda_handler`.
- Websuche: Payload enthält `web_search`, `max_tool_calls=1`, `user_location` AT; Zählung `web_search_call`;
  Kosten inkl. Suche; Tool fehlt bei erreichtem Limit/Kostenlimit/`WEB_SEARCH_ENABLED=false`; Nachzählung bei Timeout.
- Zeitzonen: Tageswechsel um Mitternacht Wien (nicht UTC) für Zähler und Prompt-Datum.
- Regression: alle bestehenden Tests grün; `ruff`, `cfn-lint --regions eu-north-1`, `pip-audit`.

## 5. Bereitstellung und Verifikation

1. Change Set erstellen, Änderungen auflisten, **auf Freigabe warten**, dann ausführen.
2. Refresh einmal manuell per `aws lambda invoke` auslösen; `CONTEXT`-Eintrag prüfen (ohne Inhalte zu loggen).
3. Funktionstest per `aws lambda invoke`: „Was gibt's Neues in Kärnten?“ (ohne Suche erwartet),
   „Wer hat gestern das Skispringen gewonnen?“ (Suche erwartet); Latenz und `search_calls` aus den Logs berichten.
4. Kosten für die Testfragen aus `superkugel_admin.py usage` berichten.

## 6. Dokumentation

`docs/kosten.md`, `docs/plattformgrenzen-und-fallback.md` (Latenz, Datenschutz), `docs/architektur.md`,
`docs/betrieb-und-wartung.md` (Limits ändern, Websuche abschalten), `PROJECT_STATUS.md`, `CLAUDE.md`,
Akzeptanztests ergänzen (Gerät: Nachrichtenfrage, Wetterfrage, Suchfrage, Kontingent erschöpft).
Quellenangabe „Wetterdaten: Open-Meteo.com (CC BY 4.0)“ im README.

## 7. Definition of Done

- A und B implementiert, alle Tests grün, Lint/Template/Audit ohne Befund, committet.
- Websuche hart begrenzt: ≤ 1 pro Antwort, ≤ Tageslimit, im Kostenzähler enthalten, Tageswechsel Wiener Zeit.
- Nach Freigabe deployt; Funktionstest mit gemessener Latenz und Kosten dokumentiert.
- Ehrlich dokumentiert, was nur am Echo geprüft werden kann (Latenzgefühl, Erkennung der Fragen).
