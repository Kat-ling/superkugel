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
        "ratschen", "ich will ratschen", "ich möchte ratschen", "lieber ratschen", "ratschen bitte",
        "ein bisschen ratschen", "a bissl ratschen", "reden", "ich will reden", "unterhalten",
        "ich möchte mich unterhalten",
        # „plaudern“ wird zusätzlich verstanden, gesagt wird es nirgends
        "plaudern", "ich will plaudern", "lieber plaudern",
    ]},
    {"name": "PlayShowIntent", "slots": [{"name": "show", "type": "AMAZON.SearchQuery"}], "samples": [
        "spiel die neueste folge von {show}", "spiel die neue folge von {show}", "spiel die letzte folge von {show}",
        "spiel den podcast {show}", "spiel die sendung {show}", "spiel das hörspiel {show}",
        "neueste folge von {show}", "die neue folge von {show}", "ich will die sendung {show} hören",
    ]},
    {"name": "ListShowsIntent", "slots": [], "samples": [
        "welche podcasts hab ich", "welche sendungen hab ich", "welche hörspiele hab ich",
        "was für podcasts gibt es", "welche sendungen gibt es", "meine sendungen", "meine podcasts",
    ]},
    {"name": "SearchMediaIntent", "slots": [{"name": "query", "type": "AMAZON.SearchQuery"}], "samples": [
        "such in der mediathek nach {query}", "such in der mediathek {query}", "such einen podcast über {query}",
        "such einen podcast {query}", "such ein hörspiel über {query}", "such ein hörspiel {query}",
        "such mir ein hörspiel {query}", "such mir einen podcast {query}", "such eine sendung über {query}",
        "such hörspiele über {query}", "such podcasts über {query}", "such was zum hören über {query}",
        "finde ein hörspiel {query}", "finde einen podcast {query}",
    ]},
    {"name": "ChooseResultIntent", "slots": [{"name": "ordinal", "type": "ORDINAL"},
                                             {"name": "number", "type": "AMAZON.NUMBER"}], "samples": [
        "die {ordinal}", "das {ordinal}", "den {ordinal}", "{ordinal}", "die {ordinal} bitte",
        "nummer {number}", "die nummer {number}", "{number}",
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

REMINDER_SLOTS = [{"name": "date", "type": "AMAZON.DATE"}, {"name": "time", "type": "AMAZON.TIME"},
                  {"name": "duration", "type": "AMAZON.DURATION"}]

# Erinnerungen, Radio, Rätsel macht Alexa selbst (1.3). Die Intents bleiben, damit solche Sätze nicht bei der KI
# landen, sondern einen kurzen Hinweis bekommen. Morgengruß-Schalter seit 1.2.
EXTRA_INTENTS = [
    {"name": "RemindMeIntent", "slots": [{"name": "query", "type": "AMAZON.SearchQuery"}], "samples": [
        "erinner mich {query}", "erinnere mich {query}", "erinner mich bitte {query}", "erinnere mich bitte {query}",
        "stell eine erinnerung {query}", "mach eine erinnerung {query}", "ich brauch eine erinnerung {query}",
        "neue erinnerung {query}",
    ]},
    # Ohne Freitext (AMAZON.SearchQuery und Datums-Slots bewusst getrennt)
    {"name": "ReminderIntent", "slots": REMINDER_SLOTS, "samples": [
        "erinnerung für {date} um {time}", "erinnerung am {date} um {time}", "erinnerung um {time}",
        "erinnerung in {duration}", "stell eine erinnerung für {date} um {time}", "erinnerung für {date}",
        "erinner mich", "erinnere mich", "stell eine erinnerung", "neue erinnerung", "ich brauch eine erinnerung",
        "mach eine erinnerung", "welche erinnerungen hab ich", "welche erinnerungen habe ich", "meine erinnerungen",
        "an was erinnerst du mich", "lösch eine erinnerung", "erinnerung löschen", "lösch die erinnerung",
    ]},
    {"name": "PlayRadioIntent", "slots": [], "samples": [
        "spiel radio", "mach das radio an", "radio", "radio hören", "ich will radio hören",
        "ich möchte radio hören", "welche sender gibt es", "welche radiosender hast du", "schalt das radio ein",
    ]},
    {"name": "StartQuizIntent", "slots": [], "samples": [
        "mach ein rätsel mit mir", "ein rätsel", "rätsel", "quiz", "mach ein quiz", "gedächtnistraining",
        "lass uns rätseln", "stell mir ein rätsel", "gib mir ein rätsel", "ich will rätseln", "rätseln",
        "noch ein rätsel",
    ]},
    {"name": "MorningOffIntent", "slots": [], "samples": [
        "lass den morgengruß weg", "kein morgengruß mehr", "morgengruß aus", "ich will keinen morgengruß",
        "schalt den morgengruß aus", "keinen morgengruß",
    ]},
    {"name": "MorningOnIntent", "slots": [], "samples": [
        "mach den morgengruß wieder", "morgengruß wieder an", "ich will wieder einen morgengruß",
        "schalt den morgengruß ein", "morgengruß an",
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
                          "auf wiederschauen", "schluss", "genug", "es ist genug", "das reicht", "hören wir auf",
                          "aufhören"],
    "AMAZON.HelpIntent": ["was kannst du", "was kann ich sagen", "hilfe bitte"],
}


def ordinal_type() -> dict:
    values = {"erste": ["ersten", "erstes", "eins"], "zweite": ["zweiten", "zweites", "zwei"],
              "dritte": ["dritten", "drittes", "drei", "letzte", "letzten"]}
    return {"name": "ORDINAL", "values": [{"name": {"value": k, "synonyms": v}} for k, v in values.items()]}


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
    intents.extend(EXTRA_INTENTS)
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
            "languageModel": {"invocationName": INVOCATION, "intents": intents,
                              "types": [genre_type(), ordinal_type()]},
        }
    }


def main() -> None:
    out = ROOT / "skill-package" / "interactionModels" / "custom" / "de-DE.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(build(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"geschrieben: {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
