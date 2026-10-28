# Akzeptanztests

Status-Werte: **AUTO ✅** = automatisiert bestanden (Simulation mit echten Alexa-Request-JSONs,
gemockter OpenAI-API, gemocktem AWS) · **GERÄT ✅** = manuell auf echtem Echo Dot bestanden ·
**❌** = fehlgeschlagen · **⏳** = nicht ausgeführt · **🚫** = wegen Plattformgrenze nicht möglich.

> Ein AUTO-Test ist **kein** Gerätetest. Spracherkennung, echte Latenz, Stimme und Streaming
> lassen sich nur am Echo prüfen. Stand 25.10.2026: Gerätetests 1, 2, 9, 10 durch den Admin bestanden; die übrigen stehen aus,
> insbesondere der Test mit der Stimme der Nutzerin.

| # | Test | AUTO | GERÄT | Automatisierter Nachweis | Durchführung am Gerät / Erwartung |
|---|---|---|---|---|---|
| 1 | Skill öffnen | ✅ | ✅ (Admin, 25.10.) | `test_launch_greets_and_keeps_session_open` | „Alexa, öffne Superkugel“ → Begrüßung, Mikro bleibt offen |
| 2 | Einfache Frage | ✅ | ✅ (Admin, 25.10.) | `test_question_answer_and_follow_up_context` | „Sag mal, wie mach ich Kaiserschmarrn?“ → Antwort in 2–4 Sätzen, < 5 s |
| 3 | Folgefrage | ✅ | ⏳ | dito | „Was bedeutet Inflation?“ → „Und warum wird dann alles teurer?“ → Bezug erkannt |
| 4 | Langsam sprechen | 🚫 (ASR) | ⏳ | – | Mit Pausen sprechen; notieren, ab wie vielen Sekunden Pause Alexa abschneidet |
| 5 | Dialektale Formulierung | ✅ (Text-Durchreichung) | ⏳ | `test_dialect_input_passed_through_unchanged` | „Ich hab heut a Jause gmacht“ – Erkennung durch Alexa prüfen, 10 Sätze, Ziel ≥ 8 sinngemäß |
| 6 | Unbekannte Frage | ✅ (Prompt-Regel) | ⏳ | `test_prompt_contains_style_library_and_honesty` | „Wie hoch ist der Lottojackpot heute?“ → ehrliches „weiß ich nicht“ / Verweis auf Alexa |
| 7 | Antwort wiederholen | ✅ | ⏳ | `test_repeat_last_answer_slowly` | „Wie bitte?“ → gleiche Antwort, langsamer |
| 8 | Hörbuch starten | ✅ | ⏳ | `test_play_title_fuzzy_starts_at_beginning` | „Alexa, sag Superkugel, spiel Mord im Kräuterbeet“ |
| 9 | Hörbuch pausieren | ✅ | ✅ (Admin, 25.10.) | `test_pause_saves_position_and_resume_continues` | „Alexa, Pause“ |
| 10 | Hörbuch fortsetzen | ✅ | ✅ (Admin, 25.10.; auch „Alexa, zurück“) | dito | „Alexa, weiter“ → Abweichung < 30 s |
| 11 | Kapitel wechseln | ✅ | ⏳ | `test_next_and_previous_chapter`, `test_playback_events_track_progress_and_enqueue` | „Alexa, nächstes“; Kapitelende abwarten → nächstes Kapitel automatisch |
| 12 | Ungenauer Titel | ✅ | ⏳ | `test_fuzzy_title_matching` | „…spiel das Kräuterbeet“ |
| 13 | Skill verlassen, neu öffnen | ✅ | ⏳ | `test_session_resume_after_relaunch` | „Stopp“, dann „Alexa, öffne Superkugel“ → „Da bin ich wieder“ |
| 14 | Nach Echo-Neustart fortsetzen | ✅ (Fortschritt aus DB) | ⏳ | `test_resume_my_krimi_after_restart_uses_stored_progress` | Stecker ziehen, neu starten, „…spiel meinen Krimi weiter“ |
| 15 | API-Ausfall simulieren | ✅ | ⏳ | `test_auth_error_ends_session_immediately`, `test_first_timeout_offers_retry_second_ends_session` | Falschen Schlüssel in SSM setzen → Fallback-Satz, Sitzung endet |
| 16 | Abgelaufener Audio-Link | ✅ | ⏳ | `test_expired_link_playback_failed_replays_with_fresh_url` | `AUDIO_URL_EXPIRY_S=60`, Kapitel > 2 min, Pause 3 min, „weiter“ |
| 17 | Nicht vorhandener Titel | ✅ | ⏳ | `test_unknown_title_and_empty_library` | „…spiel Harry Potter“ → „hab ich leider nicht“ |
| 18 | Längere Wiedergabe | ✅ (Einreihen) | ⏳ | `test_nearly_finished_enqueues_next_with_expected_token` | 2 h am Stück laufen lassen, Kapitelwechsel lückenlos |
| 19 | Fehlerhafte Eingaben | ✅ | ⏳ | `test_fallback_is_patient_and_ends_only_after_limit`, `test_unknown_intent_handled_like_fallback`, `test_history_from_attributes_rejects_garbage` | Unsinn sagen → kurze Rückfrage, nach 3× freundliches Ende |
| 20 | Kosten- und Nutzungslimits | ✅ | ⏳ | `test_usage_limit_blocks_ai_but_not_audiobooks`, `test_usage_limit_daily_and_monthly` | `DAILY_COST_LIMIT_USD=0.001` → nach 1–2 Fragen „Feierabend“, Hörbuch geht |
| 21 | Neues Thalia-Hörbuch erkennen | 🚫 (keine Thalia-API) / ✅ Ersatzprozess | ⏳ | `test_inbox_processes_moves_logs_and_notifies` | Thalia-ZIP in Eingangsordner → Mail „importiert“ → „…spiel meinen neuen Gartenkrimi“ |
| 22 | Bereits synchronisierter Titel erneut | ✅ | ⏳ | `test_import_folder_metadata_and_dedupe`, `test_same_files_under_other_title_detected` | Gleiches ZIP nochmal einlegen → „bereits vorhanden“, kein Duplikat |
| 23 | Nicht-Audio-Thalia-Titel | ✅ | ⏳ | `test_ebook_only_is_not_audio`, `test_classify_formats` | E-Book-Download einlegen → Ordner `kein-hoerbuch/`, nicht in Bibliothek |
| 24 | OpenAI-Ausfall → normale Alexa | ✅ (Sitzungsende) | ⏳ | `test_quota_exhausted_ends_session`, `test_circuit_breaker_skips_api_after_repeated_failures` | Nach Fallback-Satz sofort „Alexa, wie spät ist es?“ → normale Antwort |
| 25 | Totalausfall Backend | 🚫 lokal (Lambda selbst weg) | ⏳ | `test_exception_in_audio_event_returns_silent_empty_response`, `test_library_outage_does_not_block_chat` | Endpoint in Console auf ungültige ARN → Alexa-Fehlermeldung; danach Timer stellen |
| 26 | Nach Wiederherstellung erneut starten | ✅ | ⏳ | `test_recovery_after_backend_returns` | Endpoint zurücksetzen → Skill startet normal |
| 27 | Antwort ohne Nachfrage, Folgefrage ohne „Alexa“ | ✅ | ⏳ | `test_answer_has_no_reprompt_but_keeps_listening` | Frage stellen → keine Nachfrage; innerhalb ~8 s Folgefrage ohne „Alexa“; danach leises Ende |
| 28 | Nachrichten/Wetter | ✅ | ⏳ | `test_context_block_and_web_search_tool_with_austrian_location`, `test_refresh_stores_all_sources_and_prompt_block` | „Was gibt's Neues in Kärnten?“, „Wie wird das Wetter morgen?“ → Antwort mit „laut ORF“, ohne Wartezeit |
| 29 | Websuche | ✅ | ⏳ | `test_web_search_removed_when_daily_quota_used`, `test_payload_with_web_search_has_max_tool_calls_and_no_retry` | „Wer hat gestern das Skispringen gewonnen?“ → Antwort < 7 s (Stoppuhr), Logs: `searches=1` |
| 30 | Tageslimit Websuche | ✅ | ⏳ | `test_search_quota_and_cost_reserve` | `WebSearchDailyLimit=1`, zwei Suchfragen → zweite: „heute nicht mehr nachschauen“ |
| 31 | Lieblingssendung | ✅ | ⏳ | `test_play_show_latest_then_resume` | „…spiel die neueste Folge von Kein Mucks“ → spielt; Pause; erneut → setzt fort |
| 32 | Freie Mediensuche | ✅ | ⏳ | `test_search_choose_and_play` | „…such ein Krimihörspiel“ → drei Treffer → „die zweite“ → spielt |
| 33 | Datenschutz-Alarm | ✅ | – | `test_privacy_metric_when_search_contains_name` | – |
| 34 | Ohne Admin-PC | ✅ (Zeitplan in AWS) | ⏳ | `test_refresh_event_runs_without_alexa` | PC aus, nächster Morgen: Nachrichten aktuell (Stand-Uhrzeit nennen lassen) |
| 35–43 | Erinnerungen, Radio (1.2) | – | – | – | **in 1.3 entfernt** – macht Alexa selbst; ersetzt durch Prüfpunkt 49 |
| 44 | Morgengruß | ✅ | ✅ 28.10.2026 (Admin) | `test_morning_briefing_once_without_ai`, `test_morning_compose_filters_and_formats` | Erstes Öffnen 5–11 Uhr → Datum, Wetter, zwei Schlagzeilen ohne Unglücksmeldungen; zweites Öffnen → normale Begrüßung |
| 45 | Morgengruß abschalten | ✅ | ⏳ | `test_morning_not_after_eleven_and_switchable` | „…lass den Morgengruß weg“ → nächster Morgen ohne; „…mach den Morgengruß wieder“ |
| 46–47 | Rätsel (1.2) | – | – | – | **in 1.3 entfernt** – macht Alexa selbst; ersetzt durch Prüfpunkt 49 |
| 48 | Wochenbericht | ✅ | ⏳ | `test_report_contains_only_numbers`, `test_report_due_once_per_week_and_only_at_eight`, `test_run_weekly_report_error_path` | Montag 8 Uhr Mail im Postfach des Admins, nur Zahlen |
| 49 | Hinweis „macht Alexa selbst“ (1.3) | ✅ | ⏳ | `test_reminder_radio_quiz_get_alexa_hint_without_ai_and_end_session`, `test_spiel_station_name_gives_radio_hint_but_books_and_shows_win` | In der Superkugel: „erinner mich morgen um zehn an den Arzt“, „spiel Ö3“, „mach ein Rätsel“ → jeweils kurzer Hinweis, Superkugel schließt sich; danach direkt „Alexa, …“ sagen → Alexa erledigt es |
| 50 | Laufendes Hörbuch nach dem Update | ✅ | ⏳ | `test_old_radio_token_on_device_does_not_break_book_commands` | „…spiel meinen Krimi weiter“, Pause, Weiter → gleiche Stelle wie vorher |

Zusätzlich automatisiert: Modus `maintenance`/`audiobooks_only`, Ja/Nein nach der Begrüßung,
KI-Werkzeugaufruf nur für vorhandene Bücher, Zwischenmeldung bei langsamer KI, keine
Gesprächsinhalte in Logs, Interaction Model ↔ Code synchron, DynamoDB/S3/SSM gegen moto,
Zip-Slip-Schutz, abgebrochener Upload ohne Duplikate.

## Hardware-Testplan (Echo Dot 5, ca. 60 Minuten)

Vorbereitung: Backend deployt, ein gemeinfreies Testhörbuch (LibriVox, ≥ 3 Kapitel) importiert,
Developer Console → Test auf „Development“, CloudWatch-Logs offen. Ihr Echo ist auf dein Konto registriert,
Standort/Zeitzone gesetzt, „Einkaufen per Sprache“ aus (Setup §1).

1. Tests 1–3, 6, 7 mit der eigenen Stimme; Antwortzeit mit Stoppuhr (Ziel < 5 s, notieren).
2. Tests 8–12, 17 mit dem Testhörbuch; Test 18 nebenbei laufen lassen.
3. Test 13, dann Test 14 (Stecker ziehen).
4. Tests 15 und 24: `aws ssm put-parameter --name /superkugel/openai-api-key --type SecureString --value falsch --overwrite`, danach echten Schlüssel zurück.
5. Test 20 mit niedrigem Limit (Deploy-Parameter), danach zurücksetzen.
6. Test 16 mit `AUDIO_URL_EXPIRY_S=60`.
7. Tests 25/26 über den Endpoint in der Developer Console.
8. **Mit ihr gemeinsam** (wichtigster Test): Tests 1–5, 7–10 mit **ihrer** Stimme, ihrem Tempo,
   ihren Kärntner Ausdrücken; den Spickzettel benutzen lassen, ohne zu helfen. Ziel: 9 von 10 Starts ohne Hilfe.
9. Ergebnis je Zeile oben in Spalte GERÄT eintragen (✅/❌ + Notiz).
