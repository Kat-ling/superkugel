# Phase 1 – Technische Verifikation (Stand 24.10.2026)

Legende: **[Doku]** = offizielle Dokumentation am 24.10.2026 geprüft · **[Wissen]** = etablierte
Plattformregel aus meinem Kenntnisstand, nicht erneut nachgelesen · **[offen]** = nur am echten Gerät klärbar.

## Ergebnis auf einen Blick

| Punkt | Ergebnis | Konsequenz im Projekt |
|---|---|---|
| Antwortzeit des Skills | ca. 8 s inklusive Progressive Response; Progressive Responses verlängern das **nicht**, höchstens 5 vor der Antwort **[Doku]** | Internes Zeitbudget 7 s, KI-Timeout 5,5 s, max. 1 Wiederholung nur bei genug Restzeit, Zwischenmeldung erst nach 1,2 s |
| Freie Rede | `AMAZON.SearchQuery` braucht eine Trägerphrase und muss der einzige Slot im Satz sein; Alexa liefert das Trägerwort nicht mit **[Wissen]** | 86 Chat-Intents, je einer pro Trägerwort („warum“, „heute“, „nein“ …), Satz wird verlustfrei rekonstruiert. Kein fragiler Catch-all-Slot. |
| Sitzungen / Denkpausen | Mikrofon nach Antwort nur wenige Sekunden offen, ein Reprompt, dann Ende; nicht konfigurierbar **[Wissen, im Architektur-Review mit Doku belegt]** | Reprompt mit kurzer Rückfrage. Gesprächsverlauf bleibt 30 Min. gespeichert: Nach „Alexa, öffne Superkugel“ geht es dort weiter. |
| Stimmen | `<voice>` erlaubt für de-DE nur **Hans, Marlene, Vicki**; keine de-AT-Stimme in Alexa **[Doku: SSML-Referenz]** | Konfigurierbar `alexa` (Standard) / `Vicki` / `Marlene` / `Hans`. Polly „Hannah“ (de-AT) ist im Skill **nicht** nutzbar → nur in den Hörproben zum Vergleich. |
| `amazon:domain`/Emotion (de) | Domain nur `music` (nicht mit `<voice>` kombinierbar), Emotion `excited`/`disappointed` **[Doku]** | Nicht verwendet (bringt für Gespräche nichts). |
| Externe Stimme per `<audio>` | MP3, 48 kbit/s, 16/22,05/24 kHz, HTTPS, max. 240 s pro Antwort, max. 5 Dateien; **Dateien dürfen keine kundenspezifischen oder sensiblen Inhalte enthalten** **[Doku]** | Gesprochene KI-Antworten *sind* kundenspezifisch → per `<audio>` regelwidrig. Dazu Latenz für TTS + Umkodierung + Upload innerhalb von 8 s. **Nicht umgesetzt.** |
| OpenAI-TTS | `gpt-4o-mini-tts`, `tts-1`, `tts-1-hd` sind abgekündigt, Abschaltung **6.1.2027** **[Doku]** | Wäre ohnehin in 10 Wochen tot → nicht umgesetzt. |
| OpenAI-Modell | `gpt-6-luna`: 0,10 $/1 Mio. Eingabe, 0,01 $ gecacht, 0,50 $ Ausgabe; Responses API; Function Calling; `reasoning.effort = none` möglich **[Doku]** | Standardmodell, `effort=none` für minimale Latenz. Austauschbar per `OPENAI_MODEL`. |
| AudioPlayer | Play (REPLACE_ALL/ENQUEUE + `expectedPreviousToken`), Stop, Offset, Ereignisse Started/Stopped/NearlyFinished/Finished/Failed; auf Ereignisse nur AudioPlayer-Direktiven, keine Sprache **[Wissen]** | Vollständig umgesetzt, inkl. PlaybackController (Tasten) und System.ExceptionEncountered. |
| Eingebaute Audio-Befehle | Pause/Weiter/Nächstes/Zurück/Von vorne/Stopp kommen ohne Skillnamen beim Skill an, solange er die Audiowiedergabe „besitzt“ **[Wissen]** | „Alexa, Pause“ / „Alexa, weiter“ / „Alexa, nächstes“ / „Alexa, zurück“ funktionieren direkt. Eigene Befehle („ein Stück zurück“) brauchen den Skillnamen. |
| Weitergabe an normale Alexa | Es gibt **keine** offizielle Schnittstelle, mit der ein Custom Skill eine laufende Anfrage an Alexa übergibt **[Wissen]** | Kein nahtloser Fallback. Umgesetzt: Sitzung kontrolliert beenden + Hinweis. Danach reagiert Alexa normal. |
| Dauerbetrieb privat | Betatest max. 90 Tage, nicht verlängerbar (NO-GO). Entwicklungsmodus läuft auf Geräten, die auf dasselbe Konto wie der Developer-Account registriert sind; keine dokumentierte Ablauffrist **[im Architektur-Review mit Doku belegt]** | Entwicklungsmodus auf dem Amazon-Konto des Admins, auf das auch ihr Echo registriert ist (sie braucht kein eigenes Konto). Restrisiko: keine Zusage von Amazon. |
| Österreich | Kein eigener de-AT-Skill-Locale; Echo-Geräte in AT nutzen amazon.de / de-DE **[Wissen]** | Skill-Locale `de-DE`, Vertriebsland AT/DE (Skill bleibt ohnehin unveröffentlicht). |
| Request-Validierung | Bei AWS-Lambda-Endpunkt prüft Amazon die Signatur nicht im Skill-Code; Absicherung über Lambda-Trigger mit Skill-ID + Skill-ID-Prüfung im SDK **[Wissen]** | Beides umgesetzt (`AlexaSkill`-Event mit `SkillId`, `skill_id` im SkillBuilder). |
| Thalia | Keine öffentliche Kunden-/Bibliotheks-API bekannt; Anmeldung im Konto automatisiert auslesen wäre Scraping hinter Login (Nutzungsbedingungen, 2FA, fragil) | **Keine Automatisierung des Thalia-Kontos.** Ersatz: Eingangsordner mit automatischem Import (siehe `docs/hoerbuecher-und-thalia.md`). |
| Alexa Routines Kit (Entwickler-API) | im Mai 2026 eingestellt (laut Architektur-Review) | Nicht verwendet. Normale Routinen in der Alexa-App (vom Admin eingerichtet) bleiben möglich, mit Aktion „Benutzerdefiniert“ **[offen: am Gerät prüfen]**. |

## Showstopper?

Keiner für das, was mit Alexa machbar ist. Die bekannten Grenzen (Aktivierung per „Alexa, öffne …“,
kurzes Mikrofonfenster, keine echte Dialektstimme, kein Thalia-Zugriff) sind im Projekt offen
dokumentiert und so gut wie möglich umgangen – nicht verdeckt.

## Quellen

- Alexa SSML-Referenz: https://developer.amazon.com/en-US/docs/alexa/custom-skills/speech-synthesis-markup-language-ssml-reference.html
- Progressive Response: https://developer.amazon.com/en-US/docs/alexa/custom-skills/send-the-user-a-progressive-response.html
- OpenAI Modelle: https://developers.openai.com/api/docs/models und …/models/gpt-6-luna
- OpenAI Text-to-Speech (Abkündigung): https://developers.openai.com/api/docs/guides/text-to-speech
- Vorangegangenes Architektur-Review (pre-info.docx, privat, nicht im Repo)
