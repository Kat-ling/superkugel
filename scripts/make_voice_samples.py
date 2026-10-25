"""Reproduzierbare Hörproben für die Stimm- und Stilvarianten.

1) Immer: schreibt SSML-Dateien nach docs/voice-samples/ – genau so, wie der Skill sie an Alexa
   schickt. Diese im Alexa Developer Console unter „Test → Voice & Tone“ einfügen und anhören.
   Das ist der einzige verlässliche Test, was Alexa wirklich ausgibt.
2) Optional (--polly): erzeugt MP3s über Amazon Polly mit dem eigenen AWS-Konto, zum bequemen
   Vorspielen auf dem PC. Kostet wenige Cent. Enthält zum Vergleich auch „Hannah“ (de-AT) –
   diese Stimme gibt es nur in Polly, NICHT im Alexa-Skill.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from superkugel.speech.ssml import to_ssml  # noqa: E402

# Vergleichstexte: gleiche Situation, drei Stile (so formuliert, wie das Modell es laut Prompt soll)
TEXTS = {
    "kaernten": "Servus! Heut ist's draußen recht frisch, gell. Für den Garten passt's trotzdem, "
                "die Paradeiser sind eh schon geerntet. Magst nachher a bissl weiterhören bei deinem Krimi?",
    "bayern": "Servus! Heut is' recht frisch draußen, gell. Für den Garten passt's freilich trotzdem. "
              "Magst nachher a bisserl weiterhören bei deinem Krimi?",
    "standard": "Hallo! Heute ist es draußen ziemlich frisch. Für den Garten reicht es trotzdem. "
                "Möchtest du nachher bei deinem Krimi weiterhören?",
}
ALEXA_VOICES = ["alexa", "Vicki", "Marlene", "Hans"]
POLLY = {"Vicki": ("de-DE", "neural"), "Daniel": ("de-DE", "neural"), "Hannah": ("de-AT", "neural"),
         "Marlene": ("de-DE", "standard"), "Hans": ("de-DE", "standard")}


def write_ssml(out: Path) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for style, text in TEXTS.items():
        for voice in ALEXA_VOICES:
            for rate in ("95%", "100%"):
                p = out / f"{style}_{voice.lower()}_{rate.rstrip('%')}.ssml"
                p.write_text(to_ssml(text, voice=voice, rate=rate) + "\n", encoding="utf-8")
                written.append(p)
    return written


def polly(out: Path) -> None:
    import boto3

    client = boto3.client("polly", region_name=os.environ.get("AWS_REGION", "eu-north-1"))
    for voice, (lang, engine) in POLLY.items():
        for style, text in TEXTS.items():
            ssml = to_ssml(text, rate="95%")  # ohne <voice>: Polly wählt die Stimme per VoiceId
            resp = client.synthesize_speech(Text=ssml, TextType="ssml", VoiceId=voice, Engine=engine,
                                            LanguageCode=lang, OutputFormat="mp3", SampleRate="24000")
            (out / f"polly_{voice.lower()}_{style}.mp3").write_bytes(resp["AudioStream"].read())
            print(f"polly_{voice.lower()}_{style}.mp3")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--polly", action="store_true", help="zusätzlich MP3s über Amazon Polly erzeugen (AWS-Zugang nötig)")
    args = ap.parse_args()
    out = ROOT / "docs" / "voice-samples"
    print(f"{len(write_ssml(out))} SSML-Proben in {out.relative_to(ROOT)}")
    if args.polly:
        polly(out)


if __name__ == "__main__":
    main()
