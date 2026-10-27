"""Rätselsammlung: überlieferte (gemeinfreie) Sprichwörter, selbst formulierte Wissensfragen mit Österreich-Bezug
und leichte Kopfrechnungen. Kein urheberrechtlich geschütztes Material.

``answers``: akzeptierte Antworten (die Prüfung ist tolerant, siehe ``quiz/check.py``); die erste ist die Auflösung.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Item:
    item_id: str
    kind: str  # spruch | wissen | rechnen
    question: str
    answers: tuple[str, ...]
    hint: str
    solution: str = ""  # Auflösung (sonst erste Antwort)

    @property
    def spoken_solution(self) -> str:
        return self.solution or self.answers[0]


def _s(i: int, start: str, end: str, keys: tuple[str, ...], hint: str) -> Item:
    return Item(f"s{i:02d}", "spruch", f"Wie geht das Sprichwort weiter? {start} …", (end, *keys), hint,
                f"{start} {end}")


SPRUECHE = (
    _s(1, "Morgenstund hat", "Gold im Mund", ("gold",), "Es glänzt und ist sehr wertvoll."),
    _s(2, "Wer anderen eine Grube gräbt,", "fällt selbst hinein", ("fällt selbst", "fällt hinein", "selbst hinein"),
       "Es geht um das Hineinfallen."),
    _s(3, "Ohne Fleiß", "kein Preis", ("preis",), "Es reimt sich auf Fleiß."),
    _s(4, "Übung macht", "den Meister", ("meister",), "Gemeint ist einer, der etwas besonders gut kann."),
    _s(5, "Was Hänschen nicht lernt,", "lernt Hans nimmermehr", ("nimmermehr", "hans nimmermehr", "lernt hans nie"),
       "Hänschen wird groß und heißt dann anders."),
    _s(6, "Wer zuletzt lacht,", "lacht am besten", ("am besten", "lacht am besten"), "Es geht ums Lachen."),
    _s(7, "Reden ist Silber,", "Schweigen ist Gold", ("schweigen",), "Das Gegenteil von Reden."),
    _s(8, "Der Apfel fällt nicht weit", "vom Stamm", ("stamm", "vom baum", "baum"), "Ein Teil vom Baum."),
    _s(9, "Lügen haben", "kurze Beine", ("kurze beine",), "Damit geht man."),
    _s(10, "Viele Köche", "verderben den Brei", ("brei", "verderben"), "Etwas, das man kocht und löffelt."),
    _s(11, "Wer nicht wagt,", "der nicht gewinnt", ("nicht gewinnt", "gewinnt"), "Das Gegenteil von verlieren."),
    _s(12, "Aller Anfang", "ist schwer", ("schwer",), "Das Gegenteil von leicht."),
    _s(13, "Ende gut,", "alles gut", ("alles gut",), "Es kommt zweimal das gleiche Wort vor."),
    _s(14, "Eile mit", "Weile", ("weile",), "Es reimt sich auf Eile."),
    _s(15, "Kommt Zeit,", "kommt Rat", ("rat",), "Was man sich von einem guten Freund holt."),
    _s(16, "Wo ein Wille ist,", "ist auch ein Weg", ("weg",), "Darauf geht man spazieren."),
    _s(17, "Der Klügere", "gibt nach", ("gibt nach", "nach"), "Er hört auf zu streiten."),
    _s(18, "In der Not", "frisst der Teufel Fliegen", ("fliegen", "teufel"), "Kleine Tiere, die summen."),
    _s(19, "Wie man in den Wald hineinruft,", "so schallt es heraus", ("schallt", "heraus", "kommt es heraus"),
       "Ein Echo."),
    _s(20, "Hunde, die bellen,", "beißen nicht", ("beissen nicht",), "Was Hunde mit den Zähnen tun."),
    _s(21, "Was du heute kannst besorgen,", "das verschiebe nicht auf morgen", ("morgen", "verschiebe nicht"),
       "Ein Tag, der noch kommt."),
    _s(22, "Ein Unglück kommt", "selten allein", ("selten allein", "allein"), "Ohne Begleitung."),
    _s(23, "Steter Tropfen", "höhlt den Stein", ("stein", "höhlt"), "Etwas Hartes am Bach."),
    _s(24, "Wer A sagt,", "muss auch B sagen", ("b sagen", "b"), "Der nächste Buchstabe."),
    _s(25, "Der Krug geht so lange zum Brunnen,", "bis er bricht", ("bricht", "bis er bricht"),
       "Was mit Glas passiert, wenn es runterfällt."),
    _s(26, "Hochmut kommt", "vor dem Fall", ("fall", "vor dem fall"), "Was passiert, wenn man stolpert."),
    _s(27, "Neue Besen", "kehren gut", ("kehren gut", "kehren"), "Was man mit einem Besen tut."),
    _s(28, "Wer im Glashaus sitzt,", "soll nicht mit Steinen werfen", ("steinen", "steine", "nicht werfen"),
       "Damit gehen Fenster kaputt."),
    _s(29, "Geteiltes Leid", "ist halbes Leid", ("halbes leid", "halbes"), "Eins durch zwei."),
    _s(30, "Doppelt genäht", "hält besser", ("hält besser", "hält"), "Dann reißt es nicht."),
    _s(31, "Kleider", "machen Leute", ("leute",), "Menschen, ganz allgemein."),
    _s(32, "Wer rastet,", "der rostet", ("rostet",), "Was mit altem Eisen passiert."),
)

_W = [
    ("w01", "Wie heißt die Hauptstadt von Kärnten?", ("Klagenfurt",), "Sie liegt am Wörthersee."),
    ("w02", "Wie heißt der höchste Berg Österreichs?", ("Großglockner", "glockner"), "Er liegt an der Grenze von Kärnten und Tirol."),
    ("w03", "Wie viele Bundesländer hat Österreich?", ("neun", "9"), "Mehr als acht, weniger als zehn."),
    ("w04", "Welcher große Fluss fließt durch Wien?", ("Donau",), "Ein berühmter Walzer ist nach ihr benannt."),
    ("w05", "Welcher Komponist wurde in Salzburg geboren und schrieb die Zauberflöte?", ("Mozart", "Wolfgang Amadeus Mozart"),
     "Nach ihm sind auch Kugeln aus Schokolade benannt."),
    ("w06", "Wie heißt der größte See, der ganz in Kärnten liegt?", ("Wörthersee", "wörther see"), "Klagenfurt liegt an seinem Ufer."),
    ("w07", "Wie heißt die Hauptstadt von Tirol?", ("Innsbruck",), "Eine Brücke über den Inn steckt im Namen."),
    ("w08", "In welcher Stadt wurde die Sachertorte erfunden?", ("Wien",), "In der Hauptstadt."),
    ("w09", "Welche Farbe haben die Streifen der österreichischen Fahne?", ("rot weiß rot", "rot und weiß", "rot weiss"),
     "Zwei Farben, eine davon kommt zweimal vor."),
    ("w10", "Wie heißt das Fest am 24. Dezember?", ("Heiliger Abend", "heiligabend", "weihnachten", "christtag"),
     "Da kommt das Christkind."),
    ("w11", "Wie heißt der erste Monat des Jahres auf Österreichisch?", ("Jänner",), "Bei den Deutschen heißt er Januar."),
    ("w12", "Wie viele Tage hat eine Woche?", ("sieben", "7"), "Von Montag bis Sonntag."),
    ("w13", "Welches Tier legt Eier und sagt kikeriki, wenn es ein Männchen ist?", ("Huhn", "henne", "hahn", "hendl"),
     "Man sagt bei uns auch Hendl."),
    ("w14", "Was sagt man in Österreich zu Tomaten?", ("Paradeiser",), "Es klingt ein bisschen nach Paradies."),
    ("w15", "Was sagt man in Österreich zu Kartoffeln?", ("Erdäpfel", "erdapfel", "grundbirnen"), "Äpfel aus der Erde."),
    ("w16", "Wie heißt die Hauptstadt von Österreich?", ("Wien",), "Dort steht der Stephansdom."),
    ("w17", "Welche Jahreszeit kommt nach dem Sommer?", ("Herbst",), "Da fallen die Blätter."),
    ("w18", "Wie heißt die Stadt mit dem Uhrturm auf dem Schlossberg?", ("Graz",), "Die Hauptstadt der Steiermark."),
    ("w19", "Womit sind Kärntner Kasnudeln meistens gefüllt? Mit Erdäpfeln und …", ("Topfen", "quark"),
     "Etwas Weißes, das aus Milch gemacht wird."),
    ("w20", "Wie viele Minuten hat eine Stunde?", ("sechzig", "60"), "Eine Viertelstunde sind fünfzehn davon."),
    ("w21", "Welcher Wochentag kommt nach Mittwoch?", ("Donnerstag",), "Er hat etwas mit einem Gewitter zu tun."),
    ("w22", "In welchem Wiener Park steht das berühmte Riesenrad?", ("Prater", "wurstelprater"),
     "Dort gibt es auch den Wurstelprater."),
    ("w23", "Welcher große Fluss fließt von Osttirol quer durch Kärnten nach Slowenien?", ("Drau",),
     "Ein kurzer Name mit vier Buchstaben."),
    ("w24", "Was trinkt man in Wien gern im Kaffeehaus zu einem Stück Kuchen? Einen kleinen Braunen oder eine …",
     ("Melange", "wiener melange"),
     "Kaffee mit Milchschaum."),
    ("w25", "Wie viele Beine hat eine Spinne?", ("acht", "8"), "Doppelt so viele wie ein Hund."),
    ("w26", "Welcher Planet ist uns am nächsten und leuchtet als Abendstern?", ("Venus",), "Sie ist nach einer Liebesgöttin benannt."),
    ("w27", "In welchem Monat feiert Österreich seinen Nationalfeiertag?", ("Oktober",), "Ein Herbstmonat, am Sechsundzwanzigsten."),
    ("w28", "Was wächst am Weinstock?", ("Trauben", "weintrauben", "weinbeeren"), "Daraus macht man Wein."),
]
WISSEN = tuple(Item(i, "wissen", q, a, h) for i, q, a, h in _W)

_R = [
    ("r01", "Wie viel ist drei plus vier?", 7), ("r02", "Wie viel ist zehn minus drei?", 7),
    ("r03", "Wie viel ist fünf mal zwei?", 10), ("r04", "Wie viel ist zwölf plus acht?", 20),
    ("r05", "Wie viel ist zwanzig minus fünf?", 15), ("r06", "Wie viel ist drei mal drei?", 9),
    ("r07", "Wie viel ist die Hälfte von vierzig?", 20), ("r08", "Wie viel ist sieben plus sechs?", 13),
    ("r09", "Wie viel ist hundert minus zehn?", 90), ("r10", "Wie viel ist vier mal fünf?", 20),
    ("r11", "Wie viel ist fünfzehn plus fünfzehn?", 30), ("r12", "Wie viel ist neun minus vier?", 5),
    ("r13", "Wie viel ist sechs mal zwei?", 12), ("r14", "Wie viel ist ein Dutzend Eier, also wie viele Eier?", 12),
    ("r15", "Wie viel ist fünfzig plus fünfundzwanzig?", 75), ("r16", "Wie viel ist acht plus acht?", 16),
    ("r17", "Wie viel ist ein Viertel von hundert?", 25), ("r18", "Wie viel ist dreißig minus zwölf?", 18),
]
RECHNEN = tuple(Item(i, "rechnen", q, (str(n),), "Ganz in Ruhe, Schritt für Schritt.", str(n))
                for i, q, n in _R)

ITEMS: tuple[Item, ...] = SPRUECHE + WISSEN + RECHNEN
BY_ID = {i.item_id: i for i in ITEMS}
KINDS = ("spruch", "wissen", "rechnen")
