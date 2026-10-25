"""Alle festen Ansagen in Du- und Sie-Form. Kurz, freundlich, ohne Technikbegriffe."""

from __future__ import annotations

TEXTS: dict[str, tuple[str, str]] = {
    # Fehler / Betrieb
    "fallback": ("Das klappt gerade leider nicht. Du kannst Alexa aber ganz normal weiterverwenden.",
                 "Das klappt gerade leider nicht. Sie können Alexa aber ganz normal weiterverwenden."),
    "maintenance": ("Die Superkugel macht gerade eine kleine Pause. Alexa funktioniert ganz normal weiter.",) * 2,
    "limit": ("Für heute haben wir schon sehr viel geplaudert, ich mach jetzt Feierabend. "
              "Hörbücher kann ich trotzdem gern abspielen, und Alexa funktioniert ganz normal.",) * 2,
    "ai_off": ("Plaudern geht gerade nicht, aber Hörbücher kann ich abspielen. Sag zum Beispiel: Spiel mein Hörbuch weiter.",
               "Plaudern geht gerade nicht, aber Hörbücher kann ich abspielen. Sagen Sie zum Beispiel: Spiel mein Hörbuch weiter."),
    "ai_off_short": ("Plaudern geht gerade leider nicht, aber Hörbücher schon.",) * 2,
    "glitch": ("Da hat's gerade gehakt. Sag's bitte nochmal.", "Da hat's gerade gehakt. Sagen Sie es bitte nochmal."),
    "not_understood": ("Das hab ich nicht ganz verstanden. Sag's bitte nochmal, gern mit anderen Worten.",
                       "Das hab ich nicht ganz verstanden. Sagen Sie es bitte nochmal, gern mit anderen Worten."),
    "tip": ("Entschuldige, nochmal bitte. Fang am besten mit „Sag mal“ an, zum Beispiel: Sag mal, wie geht ein Apfelstrudel?",
            "Entschuldigung, nochmal bitte. Fangen Sie am besten mit „Sag mal“ an, zum Beispiel: Sag mal, wie geht ein Apfelstrudel?"),
    "tip_short": ("Fang einfach mit „Sag mal“ an.", "Fangen Sie einfach mit „Sag mal“ an."),
    "give_up": ("Ich versteh dich gerade schlecht. Ruf mich einfach später wieder, mit: Alexa, öffne Superkugel.",
                "Ich verstehe Sie gerade schlecht. Rufen Sie mich einfach später wieder, mit: Alexa, öffne Superkugel."),
    # Gespräch
    "ask_topic": ("Worüber magst du plaudern?", "Worüber möchten Sie plaudern?"),
    "start_chat": ("Gern! Worüber magst du plaudern?", "Gern! Worüber möchten Sie plaudern?"),
    "no_book_then": ("Gut. Worüber magst du plaudern?", "Gut. Worüber möchten Sie plaudern?"),
    "choose": ("Magst du plaudern, oder soll ich dein Hörbuch weiterspielen?",
               "Möchten Sie plaudern, oder soll ich Ihr Hörbuch weiterspielen?"),
    "resume_q": ("Soll ich dein Hörbuch weiterspielen?", "Soll ich Ihr Hörbuch weiterspielen?"),
    "welcome_back": ("Da bin ich wieder. Wo waren wir?", "Da bin ich wieder. Wo waren wir stehen geblieben?"),
    "nothing_said": ("Ich hab noch nichts gesagt. Worüber magst du plaudern?",
                     "Ich hab noch nichts gesagt. Worüber möchten Sie plaudern?"),
    "help": ("Du kannst einfach mit mir plaudern, zum Beispiel: Sag mal, was koch ich heute? "
             "Oder Hörbücher hören: Spiel mein Hörbuch weiter. Zum Aufhören sag: Stopp.",
             "Sie können einfach mit mir plaudern, zum Beispiel: Sag mal, was koch ich heute? "
             "Oder Hörbücher hören: Spiel mein Hörbuch weiter. Zum Aufhören sagen Sie: Stopp."),
    "help_q": ("Was magst du machen?", "Was möchten Sie machen?"),
    "forgotten": ("Erledigt, ich hab unser Gespräch vergessen. Worüber magst du plaudern?",
                  "Erledigt, ich hab unser Gespräch vergessen. Worüber möchten Sie plaudern?"),
    # Hörbücher
    "no_books": ("In deiner Bibliothek ist noch kein Hörbuch. Das richtet dir die Familie ein.",
                 "In Ihrer Bibliothek ist noch kein Hörbuch. Das richtet Ihnen die Familie ein."),
    "nothing_to_resume": ("Ich hab gerade kein angefangenes Hörbuch. Sag zum Beispiel: Spiel einen Krimi.",
                          "Ich hab gerade kein angefangenes Hörbuch. Sagen Sie zum Beispiel: Spiel einen Krimi."),
    "which_book": ("Welches Hörbuch magst du hören?", "Welches Hörbuch möchten Sie hören?"),
    "did_you_mean": ("Meinst du {names}?", "Meinen Sie {names}?"),
    "say_title_again": ("Sag einfach „Spiel“ und dann den Titel.", "Sagen Sie einfach „Spiel“ und dann den Titel."),
    "unknown_title": ("Das Hörbuch hab ich leider nicht. Frag mich einfach: Welche Hörbücher hab ich?",
                      "Das Hörbuch hab ich leider nicht. Fragen Sie mich einfach: Welche Hörbücher hab ich?"),
    "no_genre": ("So ein Hörbuch hab ich gerade nicht. Soll ich dir sagen, welche du hast?",
                 "So ein Hörbuch hab ich gerade nicht. Soll ich Ihnen sagen, welche Sie haben?"),
    "say_list": ("Sag: Welche Hörbücher hab ich?", "Sagen Sie: Welche Hörbücher hab ich?"),
    "all_heard": ("Da hast du schon alles fertig gehört. Wenn du eines nochmal hören magst, sag „Spiel“ und den Titel.",
                  "Da haben Sie schon alles fertig gehört. Wenn Sie eines nochmal hören möchten, sagen Sie „Spiel“ und den Titel."),
    "you_have": ("Du hast: {listing}.{more} Welches magst du hören?", "Sie haben: {listing}.{more} Welches möchten Sie hören?"),
    "say_title": ("Sag einfach „Spiel“ und dann den Titel.", "Sagen Sie einfach „Spiel“ und dann den Titel."),
    "books_paused": ("Die Hörbücher machen gerade eine kleine Pause. Alexa funktioniert ganz normal weiter.",) * 2,
    "last_chapter": ("Das war schon das letzte Kapitel.",) * 2,
    "nothing_playing": ("Gerade läuft kein Hörbuch.",) * 2,
    "unsupported": ("Das geht bei Hörbüchern leider nicht.",) * 2,
}


def text(form: str, key: str, **kwargs: object) -> str:
    du, sie = TEXTS[key]
    return (du if form == "du" else sie).format(**kwargs)
