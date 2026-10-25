# Stimmen und Dialekt

## Vier Dinge, sauber getrennt

| Ebene | Wer bestimmt sie? | Was das Projekt tut |
|---|---|---|
| **Spracherkennung** (versteht Alexa ihr Kärntnerisch?) | ausschließlich Amazon (de-DE-Modell) | nichts beeinflussbar. Der Prompt bittet das Modell, unvollständige oder seltsam erkannte Sätze sinnvoll zu deuten oder kurz nachzufragen. |
| **Wortwahl im Text** | unser Systemprompt | drei Stile: `kaernten`, `bayern`, `standard` – leichte regionale Färbung in normaler Rechtschreibung |
| **Akzent der Stimme** | gewählte Alexa-Stimme | nur de-DE-Stimmen verfügbar: Alexa, Vicki, Marlene, Hans |
| **Echte Dialektaussprache** | – | **in Alexa nicht möglich.** Es gibt keine Kärntner oder bairische Stimme. |

Eine hochdeutsche Stimme, die „Griaß di“ in Lautschrift vorliest, klingt hölzern. Deshalb verwendet
der Stil regionale *Wörter* (Servus, gell, heuer, Paradeiser, a bissl) sparsam und in normaler Schreibung.

## Verfügbare Optionen (alle konfigurierbar, siehe `setup-und-deployment.md` §8)

| Option | Stimme | Text | Einschätzung |
|---|---|---|---|
| Alexa-Standard | `alexa` | `kaernten` | stabil, vertraut, keine Zusatzkosten |
| **Eingesetzt** | `Vicki` | `kaernten` | vom Admin nach Hörprobe gewählt |
| Bairisch gefärbt | `alexa`/`Vicki` | `bayern` | nur Wortwahl, Stimme bleibt hochdeutsch |
| Gut verständlich | `Marlene` oder `alexa` | `standard` | wenn Dialektwörter stören |

Sprechtempo: 100 % (`SPEECH_RATE`, eingesetzt), Satzpausen 350 ms. „Wie bitte?“ wiederholt die letzte Antwort mit 85 %.

## Geprüft und bewusst nicht umgesetzt

| Anbieter | Warum nicht |
|---|---|
| Amazon Polly „Hannah“ (de-AT) | Existiert in Polly, aber **nicht** in der Alexa-Liste erlaubter `<voice>`-Namen. Als MP3 per `<audio>` → siehe nächste Zeile. |
| Externe TTS (OpenAI, ElevenLabs, Azure de-AT) als `<audio>` | 1) Alexa-Regel: `<audio>`-Dateien dürfen **keine kundenspezifischen Inhalte** enthalten – eine vorgelesene persönliche KI-Antwort ist genau das. 2) Zeit: KI-Antwort + Sprachsynthese + Umkodierung auf 48 kbit/s MP3 + Upload muss in ca. 8 s passen. 3) OpenAI-Speech-Modelle werden am 6.1.2027 abgeschaltet. 4) ElevenLabs/Azure: zusätzliche Kosten und Abhängigkeit. → Würde die Zuverlässigkeit der Standardausgabe gefährden. |

Würde man trotzdem eine österreichische Stimme wollen, ginge das nur mit anderer Hardware
(siehe Architektur-Review, Option C). Das Projekt bleibt beim Echo Dot.

## Hörproben

```bash
.venv/Scripts/python scripts/make_voice_samples.py
```
erzeugt 24 SSML-Dateien in `docs/voice-samples/` (3 Stile × 4 Stimmen × 2 Tempi). Inhalt in der
Developer Console unter **Test → Voice & Tone** einfügen → so klingt es wirklich auf Alexa.
```bash
.venv/Scripts/python scripts/make_voice_samples.py --polly
```
erzeugt zusätzlich MP3s über Polly (AWS-Zugang, wenige Cent). Hinweis: In eu-north-1 (Stockholm) bietet Polly
nur die Standardstimmen Vicki, Marlene und Hans; Neural-Stimmen und „Hannah“ (de-AT) laufen dort nicht.
**Status:** Der Admin hat die Proben angehört und **Vicki, Stil kaernten, Tempo 100 %** gewählt (eingesetzt).
