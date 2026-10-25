"""Erzeugt skill-package/interactionModels/custom/de-DE.json.

Aufruf:  python scripts/build_interaction_model.py
Die Chat-Intents kommen aus src/superkugel/conversation/carriers.py, damit Code und
Interaction Model nie auseinanderlaufen.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from superkugel.audiobooks.matching import GENRE_SYNONYMS  # noqa: E402
from superkugel.conversation.carriers import CARRIERS, chat_intent_name  # noqa: E402

INVOCATION = "superkugel"

AUDIO_INTENTS = [
    {"name": "ResumeAudiobookIntent", "slots": [], "samples": [
        "spiel meinen krimi weiter", "spiel mein hörbuch weiter", "mach mit meinem hörbuch weiter",
        "mach mit meinem krimi weiter", "weiterhören", "ich will weiterhören", "spiel weiter",
        "wo war ich", "mein hörbuch", "mein hörbuch weiter", "lies weiter", "weiter vorlesen",
        "das hörbuch weiter", "mach weiter mit dem buch", "mein buch weiter", "spiel das hörbuch weiter",
        "hörbuch", "das hörbuch", "hörbuch bitte", "hörbuch weiterspielen", "weiterspielen", "krimi",
        "den krimi", "mein krimi", "lieber hörbuch", "lieber das hörbuch", "hörbuch hören",
    ]},
    {"name": "StartChatIntent", "slots": [], "samples": [
        "plaudern", "ich will plaudern", "ich möchte plaudern", "lieber plaudern", "reden", "ich will reden",
        "unterhalten", "ich möchte mich unterhalten", "plaudern bitte", "ein bisschen plaudern",
    ]},
    {"name": "PlayAudiobookIntent", "slots": [{"name": "title", "type": "AMAZON.SearchQuery"}], "samples": [
        "spiel {title}", "spiele {title}", "spiel mir {title}", "lies mir {title} vor", "lies {title}",
        "ich möchte {title} hören", "ich will {title} hören", "spiel das hörbuch {title}",
        "spiel das buch {title}", "starte {title}", "spiel bitte {title}",
    ]},
    {"name": "PlayGenreIntent", "slots": [{"name": "genre", "type": "GENRE"}], "samples": [
        "spiel einen {genre}", "spiel ein {genre}", "spiel mir einen {genre}", "ich möchte einen {genre} hören",
        "ich will einen {genre} hören", "hast du einen {genre}", "spiel was {genre}", "lies mir einen {genre} vor",
        "spiel irgendein hörbuch", "spiel irgendwas zum hören",
    ]},
    {"name": "PlayNewestIntent", "slots": [{"name": "genre", "type": "GENRE"}], "samples": [
        "spiel meinen neuen {genre}", "spiel mein neues {genre}", "spiel den neuen {genre}",
        "spiel das neue hörbuch", "spiel mein neues hörbuch", "spiel mein neuestes hörbuch",
        "spiel das neue buch", "was ist neu", "gibt es was neues zum hören",
    ]},
    {"name": "ListAudiobooksIntent", "slots": [{"name": "genre", "type": "GENRE"}], "samples": [
        "welche {genre} hab ich noch", "welche {genre} habe ich", "welche hörbücher hab ich",
        "welche hörbücher habe ich", "was hab ich zum hören", "was kann ich hören",
        "was gibt es zum hören", "was hab ich noch nicht gehört", "welche bücher hab ich",
        "zeig mir meine hörbücher", "was ist in meiner bibliothek", "welche {genre} gibt es",
    ]},
    {"name": "RewindIntent", "slots": [], "samples": [
        "ein stück zurück", "ein stückchen zurück", "ein bissl zurück", "ein bisschen zurück",
        "spul zurück", "zurückspulen", "geh ein stück zurück", "nochmal die letzte minute",
        "das hab ich nicht gehört", "nochmal das letzte stück",
    ]},
    {"name": "ForwardIntent", "slots": [], "samples": [
        "ein stück vor", "ein stückchen vor", "ein bisschen vor", "spul vor", "vorspulen",
        "geh ein stück vor",
    ]},
    {"name": "NextChapterIntent", "slots": [], "samples": [
        "nächstes kapitel", "das nächste kapitel", "nächste kapitel", "kapitel weiter",
        "spring zum nächsten kapitel",
    ]},
    {"name": "PreviousChapterIntent", "slots": [], "samples": [
        "voriges kapitel", "vorheriges kapitel", "das vorige kapitel", "letztes kapitel",
        "kapitel zurück", "ein kapitel zurück",
    ]},
    {"name": "WhatIsPlayingIntent", "slots": [], "samples": [
        "was hör ich gerade", "was läuft gerade", "welches buch ist das", "welches kapitel ist das",
        "wie heißt das buch",
    ]},
    {"name": "ForgetConversationIntent", "slots": [], "samples": [
        "vergiss unser gespräch", "lösch unser gespräch", "vergiss alles was ich gesagt hab",
        "lösch das gespräch",
    ]},
]

BUILTIN = [
    "AMAZON.CancelIntent", "AMAZON.HelpIntent", "AMAZON.StopIntent", "AMAZON.NavigateHomeIntent",
    "AMAZON.FallbackIntent", "AMAZON.PauseIntent", "AMAZON.ResumeIntent", "AMAZON.NextIntent",
    "AMAZON.PreviousIntent", "AMAZON.StartOverIntent", "AMAZON.RepeatIntent", "AMAZON.LoopOnIntent",
    "AMAZON.LoopOffIntent", "AMAZON.ShuffleOnIntent", "AMAZON.ShuffleOffIntent", "AMAZON.YesIntent",
    "AMAZON.NoIntent",
]

BUILTIN_SAMPLES = {
    "AMAZON.RepeatIntent": ["wie bitte", "was hast du gesagt", "sag das nochmal", "nochmal bitte",
                            "das hab ich nicht verstanden", "bitte wiederholen"],
    "AMAZON.StopIntent": ["danke das wars", "das wars", "ende", "tschüss", "pfiat di", "servus und danke",
                          "auf wiederschauen", "schluss"],
    "AMAZON.HelpIntent": ["was kannst du", "was kann ich sagen", "hilfe bitte"],
}


def genre_type() -> dict:
    canon: dict[str, list[str]] = {}
    for syn, c in GENRE_SYNONYMS.items():
        canon.setdefault(c, []).append(syn)
    values = [{"name": {"value": c, "synonyms": sorted(set(s) - {c})}} for c, s in sorted(canon.items())]
    return {"name": "GENRE", "values": values}


def build() -> dict:
    intents: list[dict] = []
    for name in BUILTIN:
        intents.append({"name": name, "samples": BUILTIN_SAMPLES.get(name, [])})
    intents.extend(AUDIO_INTENTS)
    seen: set[str] = set()
    for carrier in CARRIERS:
        name = chat_intent_name(carrier)
        if name in seen:
            raise SystemExit(f"Doppelter Intent-Name: {name}")
        seen.add(name)
        intents.append({"name": name, "slots": [{"name": "query", "type": "AMAZON.SearchQuery"}],
                        "samples": [f"{carrier} {{query}}"]})
    return {
        "interactionModel": {
            "languageModel": {"invocationName": INVOCATION, "intents": intents, "types": [genre_type()]},
        }
    }


def main() -> None:
    out = ROOT / "skill-package" / "interactionModels" / "custom" / "de-DE.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(build(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"geschrieben: {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
