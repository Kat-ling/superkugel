"""Alle festen Ansagen in Du- und Sie-Form. Kurz, freundlich, ohne Technikbegriffe."""

from __future__ import annotations

TEXTS: dict[str, tuple[str, str]] = {
    # Fehler / Betrieb
    "fallback": ("Das klappt gerade leider nicht. Du kannst Alexa aber ganz normal weiterverwenden.",
                 "Das klappt gerade leider nicht. Sie können Alexa aber ganz normal weiterverwenden."),
    "maintenance": ("Die Superkugel macht gerade eine kleine Pause. Alexa funktioniert ganz normal weiter.",) * 2,
    "limit": ("Für heute haben wir schon sehr viel geratscht, ich mach jetzt Feierabend. "
              "Hörbücher kann ich trotzdem gern abspielen, und Alexa funktioniert ganz normal.",) * 2,
    "ai_off": ("Ratschen geht gerade nicht, aber Hörbücher kann ich abspielen. Sag zum Beispiel: Spiel mein Hörbuch weiter.",
               "Ratschen geht gerade nicht, aber Hörbücher kann ich abspielen. Sagen Sie zum Beispiel: Spiel mein Hörbuch weiter."),
    "ai_off_short": ("Ratschen geht gerade leider nicht, aber Hörbücher schon.",) * 2,
    "glitch": ("Da hat's gerade gehakt. Sag's bitte nochmal.", "Da hat's gerade gehakt. Sagen Sie es bitte nochmal."),
    "not_understood": ("Das hab ich nicht ganz verstanden. Sag's bitte nochmal, gern mit anderen Worten.",
                       "Das hab ich nicht ganz verstanden. Sagen Sie es bitte nochmal, gern mit anderen Worten."),
    "tip": ("Entschuldige, nochmal bitte. Fang am besten mit „Sag mal“ an, zum Beispiel: Sag mal, wie geht ein Apfelstrudel?",
            "Entschuldigung, nochmal bitte. Fangen Sie am besten mit „Sag mal“ an, zum Beispiel: Sag mal, wie geht ein Apfelstrudel?"),
    "tip_short": ("Fang einfach mit „Sag mal“ an.", "Fangen Sie einfach mit „Sag mal“ an."),
    "give_up": ("Ich versteh dich gerade schlecht. Ruf mich einfach später wieder, mit: Alexa, öffne Superkugel.",
                "Ich verstehe Sie gerade schlecht. Rufen Sie mich einfach später wieder, mit: Alexa, öffne Superkugel."),
    # Gespräch
    "ask_topic": ("Worüber magst du ratschen?", "Worüber möchten Sie ratschen?"),
    "start_chat": ("Gern! Worüber magst du ratschen?", "Gern! Worüber möchten Sie ratschen?"),
    "no_book_then": ("Gut. Worüber magst du ratschen?", "Gut. Worüber möchten Sie ratschen?"),
    "choose": ("Magst du ratschen, oder soll ich dein Hörbuch weiterspielen?",
               "Möchten Sie ratschen, oder soll ich Ihr Hörbuch weiterspielen?"),
    "resume_q": ("Soll ich dein Hörbuch weiterspielen?", "Soll ich Ihr Hörbuch weiterspielen?"),
    "welcome_back": ("Da bin ich wieder. Wo waren wir?", "Da bin ich wieder. Wo waren wir stehen geblieben?"),
    "nothing_said": ("Ich hab noch nichts gesagt. Worüber magst du ratschen?",
                     "Ich hab noch nichts gesagt. Worüber möchten Sie ratschen?"),
    "help": ("Du kannst einfach mit mir ratschen, zum Beispiel: Sag mal, was koch ich heute? "
             "Oder Hörbücher hören: Spiel mein Hörbuch weiter. Oder nach dem Fahrplan fragen: "
             "Wann fährt der nächste Zug nach Klagenfurt? Zum Aufhören sag: Stopp.",
             "Sie können einfach mit mir ratschen, zum Beispiel: Sag mal, was koch ich heute? "
             "Oder Hörbücher hören: Spiel mein Hörbuch weiter. Oder nach dem Fahrplan fragen: "
             "Wann fährt der nächste Zug nach Klagenfurt? Zum Aufhören sagen Sie: Stopp."),
    "help_q": ("Was magst du machen?", "Was möchten Sie machen?"),
    "forgotten": ("Erledigt, ich hab unser Gespräch vergessen. Worüber magst du ratschen?",
                  "Erledigt, ich hab unser Gespräch vergessen. Worüber möchten Sie ratschen?"),
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
    # Sendungen / Mediatheken
    "show_latest": ("Gern, die neueste Folge von {name}: {title}.", "Gern, die neueste Folge von {name}: {title}."),
    "show_resume": ("Gern, es geht weiter mit {name}: {title}.",) * 2,
    "show_no_episodes": ("Von {name} hab ich gerade keine Folge zum Abspielen.",) * 2,
    "which_show": ("Welche Sendung magst du hören?", "Welche Sendung möchten Sie hören?"),
    "no_shows": ("Du hast noch keine Lieblingssendungen. Du kannst aber suchen, zum Beispiel: Such ein Krimihörspiel.",
                 "Sie haben noch keine Lieblingssendungen. Sie können aber suchen, zum Beispiel: Such ein Krimihörspiel."),
    "no_shows_nosearch": ("Du hast noch keine Lieblingssendungen.", "Sie haben noch keine Lieblingssendungen."),
    "you_have_shows": ("Deine Sendungen sind: {listing}.", "Ihre Sendungen sind: {listing}."),
    "search_what": ("Was soll ich suchen?",) * 2,
    "search_unavailable": ("In den Mediatheken suchen kann ich gerade nicht. Deine Hörbücher und Sendungen gehen aber.",
                           "In den Mediatheken suchen kann ich gerade nicht. Ihre Hörbücher und Sendungen gehen aber."),
    "search_limit": ("Für heute hab ich schon genug gesucht. Morgen wieder.",) * 2,
    "search_failed": ("Die Suche hat gerade nicht geklappt. Probier's später nochmal.",
                      "Die Suche hat gerade nicht geklappt. Bitte später nochmal probieren."),
    "search_none": ("Dazu hab ich leider nichts gefunden.",) * 2,
    "search_results": ("Ich hab gefunden – {results}. Welche magst du hören?",
                       "Ich habe gefunden – {results}. Welche möchten Sie hören?"),
    "search_later": ("Das hat jetzt zu lang gedauert. Sag bitte nochmal: Such {query}.",
                     "Das hat jetzt zu lang gedauert. Sagen Sie bitte nochmal: Such {query}."),
    "search_cancelled": ("Gut, dann nicht.",) * 2,
    "search_choose": ("Sag einfach die Nummer, zum Beispiel: die erste.", "Sagen Sie einfach die Nummer, zum Beispiel: die erste."),
    # Erinnerungen, Radio, Rätsel macht Alexa selbst (Sitzung endet danach)
    "hint_reminder": ("Erinnerungen macht Alexa selbst am besten. Ich mach dir Platz – sag dann einfach: "
                      "Alexa, erinnere mich morgen um zehn an den Arzt.",
                      "Erinnerungen macht Alexa selbst am besten. Ich mache Ihnen Platz – sagen Sie dann einfach: "
                      "Alexa, erinnere mich morgen um zehn an den Arzt."),
    "hint_radio": ("Radio spielt Alexa selbst am besten. Ich mach dir Platz – sag dann einfach: Alexa, spiel Ö3.",
                   "Radio spielt Alexa selbst am besten. Ich mache Ihnen Platz – sagen Sie dann einfach: "
                   "Alexa, spiel Ö3."),
    "hint_quiz": ("Rätsel macht Alexa selbst am besten. Ich mach dir Platz – sag dann einfach: "
                  "Alexa, stell mir ein Rätsel.",
                  "Rätsel macht Alexa selbst am besten. Ich mache Ihnen Platz – sagen Sie dann einfach: "
                  "Alexa, stell mir ein Rätsel."),
    # Fahrplan (v1.4) – Zeiten und Orte setzt der Code ein, nie die KI
    "transit_departure_first": ("Laut Fahrplan fährt ab {stop} {when}um {time} {line} Richtung {head}.",) * 2,
    "transit_departure_more": ("Danach um {time} {line} Richtung {head}.",) * 2,
    "transit_departure_last": ("Laut Fahrplan fährt ab {stop} {when}als Letztes um {time} {line} Richtung {head}.",) * 2,
    "transit_no_departures": ("Laut Fahrplan fährt ab {stop} {when} in den nächsten Stunden nichts mehr.",) * 2,
    "transit_leg_first": ("Laut Fahrplan: {day}um {time} ab {stop} mit {vehicle} Richtung {head}, "
                          "an {to} um {arr}.",) * 2,
    "transit_leg_last": ("Die letzte Verbindung laut Fahrplan: {day}um {time} ab {stop} mit {vehicle} "
                         "Richtung {head}, an {to} um {arr}.",) * 2,
    "transit_leg_next": ("Dann um {time} mit {vehicle} Richtung {head}, an {to} um {arr}.",) * 2,
    "transit_walk": ("Dann etwa {minutes} Minuten zu Fuß zur Haltestelle {stop}.",) * 2,
    "transit_walk_first": ("Erst etwa {minutes} Minuten zu Fuß zur Haltestelle {stop}.",) * 2,
    # Kurzfassung bei Umstiegen (v1.5): Einzelheiten auf „genauer“
    "transit_brief": ("Laut Fahrplan: {day}um {time} ab {stop} mit {vehicle}, {changes}, an {to} um {arr}. "
                      "Insgesamt {duration}. Die Umstiege genau: sag einfach „genauer“.",
                      "Laut Fahrplan: {day}um {time} ab {stop} mit {vehicle}, {changes}, an {to} um {arr}. "
                      "Insgesamt {duration}. Die Umstiege genau: sagen Sie einfach „genauer“."),
    "transit_brief_last": ("Die letzte Verbindung laut Fahrplan: {day}um {time} ab {stop} mit {vehicle}, {changes}, "
                           "an {to} um {arr}. Die Umstiege genau: sag einfach „genauer“.",
                           "Die letzte Verbindung laut Fahrplan: {day}um {time} ab {stop} mit {vehicle}, {changes}, "
                           "an {to} um {arr}. Die Umstiege genau: sagen Sie einfach „genauer“."),
    # Gleichnamige Orte (v1.5): erst nachfragen
    "transit_confirm": ("Meinst du {name}?", "Meinen Sie {name}?"),
    "transit_confirm_other": ("Oder meinst du {name}?", "Oder meinen Sie {name}?"),
    "transit_confirm_none": ("Dann sag mir bitte den Ort genauer, zum Beispiel mit dem Bundesland: "
                             "Sankt Johann in Tirol.",
                             "Dann sagen Sie mir bitte den Ort genauer, zum Beispiel mit dem Bundesland: "
                             "Sankt Johann in Tirol."),
    "transit_summary": ("Insgesamt {duration}, {changes}.",) * 2,
    "transit_flex": ("Außerdem fährt hier der Rufbus {name}, von {start} bis {end}. Den musst du mindestens {notice} "
                     "Minuten vorher anrufen: {phone}.",
                     "Außerdem fährt hier der Rufbus {name}, von {start} bis {end}. Den müssen Sie mindestens {notice} "
                     "Minuten vorher anrufen: {phone}."),
    "transit_no_connection": ("Laut Fahrplan finde ich {when} keine Verbindung nach {dest}.",) * 2,
    "transit_unknown_place": ("Die Haltestelle {name} kenne ich leider nicht. Sag bitte den Ort, zum Beispiel: "
                              "nach Salzburg.",
                              "Die Haltestelle {name} kenne ich leider nicht. Sagen Sie bitte den Ort, zum Beispiel: "
                              "nach Salzburg."),
    "transit_same_place": ("Da bist du ja schon, in {name}.", "Da sind Sie ja schon, in {name}."),
    "transit_no_home": ("Sag mir bitte, von wo du fährst, zum Beispiel: von Salzburg nach Linz.",
                        "Sagen Sie mir bitte, von wo Sie fahren, zum Beispiel: von Salzburg nach Linz."),
    "transit_no_data_day": ("{day} hab ich noch keinen Fahrplan.", "{day} habe ich noch keinen Fahrplan."),
    "news_intro": ("Laut ORF:",) * 2,
    "news_no_more": ("Mehr Neues habe ich gerade nicht.",) * 2,
    "news_nothing": ("Dazu habe ich gerade nichts Neues.",) * 2,
    "transit_thanks": ("Gerne.",) * 2,
    "transit_ask_day": ("Welchen Tag meinst du? Sag zum Beispiel: am Dienstag, oder: am 20. November.",
                        "Welchen Tag meinen Sie? Sagen Sie zum Beispiel: am Dienstag, oder: am 20. November."),
    "transit_unavailable": ("Den Fahrplan hab ich gerade nicht zur Hand. Probier's bitte später nochmal.",
                            "Den Fahrplan habe ich gerade nicht zur Hand. Bitte später nochmal probieren."),
    # Morgengruß
    "morning_hello": ("Guten Morgen{n}!",) * 2,
    "morning_date": ("Heute ist {weekday}, der {day}. {month}.",) * 2,
    "morning_weather": ("Das Wetter: {desc}, {low} bis {high} Grad.",) * 2,
    "morning_rain": ("Nimm lieber einen Schirm mit.", "Nehmen Sie lieber einen Schirm mit."),
    "morning_news_one": ("In den Nachrichten: {first}.",) * 2,
    "morning_news_two": ("In den Nachrichten: {first}. Und: {second}.",) * 2,
    "morning_off": ("Gut, ab morgen lass ich den Morgengruß weg. Wenn du ihn wieder magst, sag: Mach den Morgengruß wieder.",
                    "Gut, ab morgen lasse ich den Morgengruß weg. Wenn Sie ihn wieder möchten, sagen Sie: "
                    "Mach den Morgengruß wieder."),
    "morning_on": ("Gern, ab morgen gibt's wieder einen Morgengruß.",) * 2,
}


def text(form: str, key: str, **kwargs: object) -> str:
    du, sie = TEXTS[key]
    return (du if form == "du" else sie).format(**kwargs)
