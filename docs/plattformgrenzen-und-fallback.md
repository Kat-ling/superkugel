# Plattformgrenzen und Ausfallverhalten

## Was die normale Alexa betrifft – und was nicht

Ein Custom Skill ist ein **Zusatz**. Er kann Alexa weder ersetzen noch abschalten. Timer, Wetter,
Radio, Wecker funktionieren immer mit „Alexa, …“, solange **keine Skill-Sitzung offen** ist –
auch wenn das ganze Backend ausgefallen ist.

| Frage aus dem Auftrag | Antwort |
|---|---|
| 1. Kann der Skill bei Fehlern die Sitzung kontrolliert beenden? | **Ja.** Jeder Fehlerpfad antwortet mit `shouldEndSession: true`. Getestet in `tests/integration/test_fallback.py`. |
| 2. Direkte Übergabe einer Anfrage an die normale Alexa? | **Nein, gibt es offiziell nicht.** Kein nahtloser Fallback. |
| 3. Bleiben Timer/Wetter/Musik nutzbar? | **Ja**, unabhängig vom Skill. Während einer offenen Sitzung landet Gesagtes allerdings beim Skill – der verweist dann auf „Alexa, stopp“ und danach den normalen Befehl. |
| 4. API-Ausfall, Timeout, kein Netz, Backend-Fehler? | Abgefangen: Timeout (7-s-Budget), Netzfehler, 429/5xx (1 Wiederholung), 401/Quota (sofort), fehlender Schlüssel, Speicher-Ausfall, jede unerwartete Ausnahme (Sicherheitsnetz). |
| 5. Hinweis „Das klappt gerade nicht …“? | **Ja**, genau dieser Satz (Du- oder Sie-Form). |
| 6. Hängenbleiben verhindern? | Alle Fehlerpfade schließen die Sitzung; Alexa schließt sie ohnehin nach einem unbeantworteten Reprompt. Auf Audio-Ereignisse wird nie mit Sprache geantwortet (das wäre ein Plattformfehler). |
| 7. Fernabschaltung? | `superkugel_admin.py mode maintenance` (alle Befehle außer Stopp/Pause werden mit kurzer Ansage beendet) oder `audiobooks_only` (KI aus). Notfalls Endpoint in der Developer Console entfernen oder den Skill in der Alexa-App deaktivieren. |
| Totalausfall Lambda/AWS | Alexa selbst sagt dann „Bei der Antwort des Skills ist ein Problem aufgetreten“ und beendet. Normale Alexa geht weiter. |
| Nach Wiederherstellung | Nächstes „Alexa, öffne Superkugel“ funktioniert wieder (getestet: `test_recovery_after_backend_returns`). Circuit-Breaker schließt sich nach 5 Minuten selbst. |

### Ablauf bei Problemen mit der KI

1. Erster vorübergehender Fehler (Timeout/Netz/Überlast): „Da hat's gerade gehakt. Sag's bitte nochmal.“ – Sitzung bleibt **einmal** offen.
2. Zweiter Fehler, Schlüssel-/Guthabenproblem oder offener Circuit-Breaker: „Das klappt gerade leider nicht. Du kannst Alexa aber ganz normal weiterverwenden.“ – Sitzung endet.
3. Bei wiederholten Fehlern: Alarm-E-Mail an dich.

## Grenzen, die bleiben (nicht lösbar innerhalb von Alexa)

| Grenze | Auswirkung | Beste Annäherung im Projekt |
|---|---|---|
| Start nur mit „Alexa, öffne Superkugel“ | ein fester Satz zu lernen | kurzer Name; optional Routine „Alexa, ich möchte plaudern“ |
| Mikrofon nur wenige Sekunden offen, 1 Reprompt | lange Denkpausen beenden die Sitzung | kurzer Reprompt; Verlauf 30 Min. gespeichert („Da bin ich wieder. Wo waren wir?“) |
| Freie Rede nur mit Trägerwort | Sätze, die mit einem unbekannten Wort beginnen, landen im Fallback | 86 typische Satzanfänge; Fallback bittet um Wiederholung, nach 2× Tipp „Sag mal …“ |
| Konkurrenz Chat ↔ feste Befehle | ~45 feste Sätze beginnen mit einem Trägerwort („ich will plaudern“, „wie bitte“, „mein hörbuch“). Exakte Treffer gewinnen meist, Varianten können im Gespräch landen | Das Modell kennt die Bibliothek und kann per Werkzeug abspielen; **vor Übergabe im Test-Tab der Developer Console prüfen (JSON Input zeigt den Intent)** |
| Kein Hineinreden während Alexa spricht (außer mit „Alexa“) | lange Antworten abwarten | Antworten kurz (2–4 Sätze) |
| ca. 8 s Antwortzeit | lange Denkaufgaben unmöglich | schnelles Modell, Token-Limit, Zwischenmeldung |
| Spracherkennung = Amazon de-DE | starkes Kärntnerisch evtl. schlecht erkannt | Modell deutet unklare Sätze; nur am Gerät mit ihrer Stimme prüfbar |
| Keine österreichische/bairische Stimme | Stimme klingt hochdeutsch | regionale Wortwahl |
| Eigene Hörbuchbefehle ohne Skillname | „Ein Stück zurück“ allein geht während der Wiedergabe nicht | „Alexa, zurück“ = 30 s zurück (eingebauter Befehl); sonst „Alexa, sag Superkugel ein Stück zurück“ |
| „Alexa, weiter“ nach anderer Audioquelle | setzt evtl. Radio statt Hörbuch fort | „Alexa, sag Superkugel, mein Hörbuch weiter“ oder Routine „Alexa, mein Krimi“ |
| Entwicklungsmodus ohne Zusage von Amazon | Amazon könnte Regeln ändern | monatlicher Kurztest; Alarm-Mails; Code bleibt portabel |
| Thalia ohne Schnittstelle | Neue Käufe nicht vollautomatisch | Eingangsordner, ca. 2 Min. Admin-Aufwand pro Buch |
