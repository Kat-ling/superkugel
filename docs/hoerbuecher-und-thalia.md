# Hörbücher, Thalia und Import

## Ehrlicher Automatisierungsgrad

| Schritt | Wer | automatisch? |
|---|---|---|
| Hörbuch bei Thalia kaufen (mit ihrem Konto, Guthaben, Gutscheinen) | sie oder du | – (bleibt unverändert, kein Abo nötig) |
| Erkennen, dass etwas Neues gekauft wurde | du (Bestellbestätigung per Mail) | **nein** – Thalia bietet keine Schnittstelle dafür |
| Download der MP3/ZIP aus „Meine Downloads“ | du | **nein** – erfordert Anmeldung im Thalia-Konto |
| Prüfen, Kapitel ordnen, hochladen, in die Bibliothek eintragen | Eingangsordner-Werkzeug | **ja** |
| Benachrichtigung „importiert“ / Fehler | Werkzeug → E-Mail | **ja** (mit `ALERT_TOPIC_ARN`) |
| „Alexa, sag Superkugel, spiel meinen neuen Gartenkrimi“ | sie | **ja** |

**Warum keine Vollautomatik?** Thalia hat (Stand 10/2026) keine offizielle API oder Exportfunktion
für die Kundenbibliothek. Eine Automatisierung müsste sich mit ihrem Passwort einloggen und die
Webseite auslesen. Das verstößt sehr wahrscheinlich gegen die Nutzungsbedingungen, bricht bei
jeder Seitenänderung, scheitert an Zwei-Faktor-Abfragen und würde ihr Passwort auf einem Server
speichern. Das wurde bewusst **nicht** gebaut.

**Damit sie trotzdem nichts tun muss:** Du bekommst die Kaufbestätigung. Am einfachsten richtest du
(mit ihrem Einverständnis ✋) in ihrem Mailprogramm eine Weiterleitung nur für Absender `thalia`
an deine Adresse ein. Dann: Download → in den Eingangsordner ziehen → fertig. Aufwand ca. 2 Minuten pro Buch.

## Welche Titel funktionieren

- ✅ Thalia-Hörbücher als **MP3-Download** (Produktseite: „Format/Medium: MP3“). Meist ein ZIP mit einer MP3 je Kapitel.
- ✅ Eigene, kopierschutzfreie MP3/M4A/M4B/AAC-Dateien.
- ✅ Gemeinfreie Aufnahmen (z. B. LibriVox, deutsche Sprache) – ideal als erstes Testhörbuch.
- ❌ Hörbücher mit Kopierschutz (`.aax`, `.aa`, `.m4p`, Audible, Streaming-Abos) – werden erkannt und abgelehnt, nicht umgangen.
- ❌ E-Books/Bücher (`.epub`, `.pdf`, `.mobi`, `.acsm`) – werden als „kein Hörbuch“ einsortiert und **nie** als abspielbar angezeigt.
- ⚠️ Vor dem Kauf auf der Produktseite prüfen, dass es ein Download mit MP3 ist, keine CD und kein Stream.

Rechtlicher Hinweis (keine Rechtsberatung): Die Dateien bleiben in einem privaten,
verschlüsselten Speicher und werden nur über kurzlebige Links an ihren eigenen Echo gestreamt.
Nie öffentlich teilen, nie ins Git-Repo.

## Eingangsordner einrichten (einmalig)

Eingang: `superkugel-eingang/` im Projektordner (von Git ausgeschlossen). Die Automatik läuft mit einem eigenen
IAM-Benutzer **`superkugel-importer`** mit Minimalrechten: Hörbuchdateien hochladen und prüfen, Bibliothek
lesen und ergänzen, Benachrichtigung senden. Nicht mit dem Admin-Benutzer.

1. Stack mit dem `ImporterUser` bereitstellen (`sam build` + `sam deploy`, siehe Setup).
2. Zugriffsschlüssel für den Import-Benutzer anlegen und als Profil speichern. Der Schlüssel wird dabei nicht angezeigt:
   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\setup_importer_profile.ps1
   ```
3. Stündliche Windows-Aufgabe „Superkugel Hoerbuch-Eingang“ einrichten. Sie läuft ohne Fenster, ohne Adminrechte und nur, solange du angemeldet bist:
   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\install_inbox_task.ps1
   ```
4. Einmal von Hand testen:
   ```powershell
   .venv\Scripts\python.exe scripts\superkugel_admin.py --profile superkugel-importer inbox superkugel-eingang
   ```

Was passiert: Jeder neue Ordner, jedes ZIP und jede einzelne Audiodatei (mindestens 1 Minute seit dem
letzten Schreiben bzw. Kopieren, also fertig) wird importiert und danach verschoben nach `fertig/`, `fehler/` oder
`kein-hoerbuch/`. Jeder Lauf steht in `sync-log.jsonl`, unerwartete Fehler (z. B. fehlende Anmeldung) in
`sync-fehler.log`, und du bekommst eine Mail. Bricht ein Import ab (z. B. Internet weg) oder lässt sich ein
Eintrag nicht verschieben (Datei noch geöffnet), bleibt er liegen und wird beim nächsten Lauf erneut
verarbeitet. Schon hochgeladene Dateien werden per Prüfsumme erkannt. Eine einzelne beschädigte MP3 lässt das
ganze Buch in `fehler/` landen, die Meldung nennt die Datei. FLAC, OGG und WAV werden nicht unterstützt.

**Fehlen Autor oder Genre** (häufig bei Thalia-Downloads ohne Tags), steht in der Mail ein Hinweis. Dann die
Metadaten nachtragen, ohne erneuten Upload:
```powershell
.venv\Scripts\python.exe scripts\superkugel_admin.py import "superkugel-eingang\fertig\<datei>.zip" --book-id <id> --replace --title "…" --author "…" --genre krimi
```

## Metadaten verbessern (optional)

Thalia-MP3s haben meist gute ID3-Tags (Album = Titel, Interpret = Autor, Tracknummer). Fehlt etwas
oder soll das Genre stimmen, lege in den Ordner eine `book.json`:

```json
{"title": "Mord im Kräuterbeet", "author": "Anna Gärtner", "genres": ["gartenkrimi"],
 "series": "Gartenkrimis", "series_no": 3}
```

Genres, die die Sprachsteuerung kennt: `krimi`, `gartenkrimi`, `regionalkrimi`, `hörspiel`, `roman`,
`geschichte`, `märchen`, `humor`. („Spiel einen Krimi“ findet auch Garten- und Regionalkrimis.)

## Einzelimport von Hand

```bash
.venv/Scripts/python scripts/superkugel_admin.py import "D:/Downloads/Mord im Kräuterbeet.zip" --genre gartenkrimi --series "Gartenkrimis" --series-no 3
```
Optionen: `--title`, `--author`, `--narrator`, `--order auto|tags|filename`, `--dry-run` (nur prüfen),
`--replace` (ein vorhandenes Hörbuch mit gleicher ID, aber anderen Dateien ersetzen – ohne diese Option
wird abgebrochen, damit nicht versehentlich eine andere Ausgabe ein Buch überschreibt).

Bibliothek ansehen / Titel entfernen:
```bash
.venv/Scripts/python scripts/superkugel_admin.py list
```
```bash
.venv/Scripts/python scripts/superkugel_admin.py remove mord-im-kraeuterbeet --delete-files
```

## Kostenlose Hörspiele

Podcasts/Hörspiele von ARD, Deutschlandfunk & Co. sind über die **normale Alexa** am einfachsten
(„Alexa, spiel den Podcast Kein Mucks“). Eine Einbindung in den Skill würde die Weiterverbreitung
fremder Inhalte über den eigenen Speicher bedeuten – das ist nur bei ausdrücklich freier Lizenz
zulässig und wurde daher nicht automatisiert. Gemeinfreie Aufnahmen kannst du normal importieren
(`--source frei`).

## Wiedergabe – was technisch passiert

- Pro Kapitel eine Datei; Alexa streamt per HTTPS mit Byte-Range-Requests direkt aus S3.
- Kurz vor Kapitelende (PlaybackNearlyFinished) wird das nächste Kapitel mit frischem Link eingereiht.
- Position wird bei Pause/Stopp/Start gespeichert; „weiter“ setzt 5 Sekunden vorher wieder ein.
- Läuft ein Link ab oder bricht das Netz kurz weg (PlaybackFailed), startet der Skill an derselben
  Stelle mit neuem Link neu (höchstens 2×, danach Alarm-Mail an dich).
- Linkgültigkeit 6 Stunden (`AUDIO_URL_EXPIRY_S`), praktisch begrenzt durch die Gültigkeit der
  Lambda-Zugangsdaten – deshalb die automatische Erneuerung.
