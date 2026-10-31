"""Kleiner erfundener Fahrplan (GTFS) für Tests – keine echten Orte der Nutzerin."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

DAY = "20261103"  # Dienstag

STOPS = [
    ("stop_id,stop_name,stop_lat,stop_lon,location_type,parent_station"),
    ("Pat:99:1,Teststadt Hbf,47.0000,13.0000,1,"),
    ("at:99:1:0:1,Teststadt Hbf,47.0000,13.0001,,Pat:99:1"),
    ("at:99:1:0:2,Teststadt Hbf,47.0001,13.0000,,Pat:99:1"),
    ("at:99:2:0:1,Teststadt Marktplatz,47.0100,13.0000,,"),
    ("at:99:5:0:1,Teststadt Marktplatz Nord,47.0118,13.0000,,"),  # ≈ 200 m → Fußweg
    ("at:99:3:0:1,Bergdorf Bahnhof,47.3000,13.2000,,"),
    ("at:99:4:0:1,Seeort Kirche,47.3200,13.2500,,"),
]
ROUTES = ["route_id,agency_id,route_short_name,route_long_name,route_type",
          "R1,A,REX1,,2", "B7,A,7,,3", "B8,A,8,,3"]
TRIPS = ["route_id,service_id,trip_id,trip_headsign,trip_short_name",
         "R1,WD,t_rex_910,Bergdorf Bahnhof,REX 1234",
         "R1,WD,t_rex_1110,Bergdorf Bahnhof,REX 1236",
         "R1,WD,t_night,Bergdorf Bahnhof,REX 1299",
         "R1,SU,t_sunday,Bergdorf Bahnhof,REX 1300",
         "B7,WD,t_bus_820,Teststadt Hbf,",
         "B7,WD,t_bus_850,Teststadt Hbf,",
         "B8,WD,t_bus_1000,Seeort Kirche,"]
STOP_TIMES = ["trip_id,arrival_time,departure_time,stop_id,stop_sequence,pickup_type,drop_off_type",
              "t_rex_910,09:10:00,09:10:00,at:99:1:0:1,1,0,1",
              "t_rex_910,09:50:00,09:50:00,at:99:3:0:1,2,1,0",
              "t_rex_1110,11:10:00,11:10:00,at:99:1:0:1,1,0,1",
              "t_rex_1110,11:50:00,11:50:00,at:99:3:0:1,2,1,0",
              "t_night,23:50:00,23:50:00,at:99:1:0:2,1,0,1",
              "t_night,24:30:00,24:30:00,at:99:3:0:1,2,1,0",
              "t_sunday,10:10:00,10:10:00,at:99:1:0:1,1,0,1",
              "t_sunday,10:50:00,10:50:00,at:99:3:0:1,2,1,0",
              "t_bus_820,08:20:00,08:20:00,at:99:2:0:1,1,0,1",
              "t_bus_820,08:30:00,08:30:00,at:99:1:0:2,2,1,0",
              "t_bus_850,08:50:00,08:50:00,at:99:2:0:1,1,0,1",
              "t_bus_850,09:00:00,09:00:00,at:99:1:0:2,2,1,0",
              "t_bus_1000,10:00:00,10:00:00,at:99:3:0:1,1,0,1",
              "t_bus_1000,10:20:00,10:20:00,at:99:4:0:1,2,1,0"]
CALENDAR = ["service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date",
            "WD,1,1,1,1,1,0,0,20261101,20261212", "SU,0,0,0,0,0,0,1,20261101,20261212"]
CALENDAR_DATES = ["service_id,date,exception_type", "WD,20261104,2"]  # Mittwoch 4.11.: Feiertag, kein Verkehr


def _zip(files: dict[str, list[str]]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, lines in files.items():
            z.writestr(name, "\n".join(lines) + "\n")
    return buf.getvalue()


def write_feeds(folder: Path) -> list[Path]:
    """Zwei Feeds: Bahn/Bus und ein „flex“-Feed mit Rufbus-Zone (plus doppelter Fahrt wie bei den Kärntner Linien)."""
    folder.mkdir(parents=True, exist_ok=True)
    base = {"agency.txt": ["agency_id,agency_name,agency_url,agency_timezone", "A,Testbahn,https://x,Europe/Vienna"],
            "stops.txt": STOPS, "routes.txt": ROUTES, "trips.txt": TRIPS, "stop_times.txt": STOP_TIMES,
            "calendar.txt": CALENDAR, "calendar_dates.txt": CALENDAR_DATES,
            "shapes.txt": ["shape_id,shape_pt_lat,shape_pt_lon,shape_pt_sequence"]}
    flex = {
        "agency.txt": base["agency.txt"],
        "stops.txt": STOPS,
        "routes.txt": ["route_id,agency_id,route_short_name,route_long_name,route_type", "B8,A,8,,3", "F1,A,Ruf,,715"],
        "trips.txt": ["route_id,service_id,trip_id,trip_headsign,trip_short_name", "B8,WD,t_bus_1000,Seeort Kirche,",
                      "F1,WD,t_flex,,"],
        "stop_times.txt": ["trip_id,arrival_time,departure_time,stop_id,location_group_id, location_id,stop_sequence,"
                           "start_pickup_drop_off_window,end_pickup_drop_off_window,pickup_booking_rule_id,"
                           "drop_off_booking_rule_id,pickup_type,drop_off_type",
                           "t_bus_1000,10:00:00,10:00:00,at:99:3:0:1,,,1,,,,,0,1",
                           "t_bus_1000,10:20:00,10:20:00,at:99:4:0:1,,,2,,,,,1,0",
                           "t_flex,,,,G1,,1,06:00:00,20:00:00,BR1,BR1,2,2",
                           "t_flex,,,,G1,,2,06:00:00,20:00:00,BR1,BR1,2,2",
                           "t_flex,,,,,Z1,1,08:00:00,18:00:00,BR1,BR1,2,2"],
        "calendar.txt": CALENDAR,
        "location_groups.txt": ["location_group_id,location_group_name", "G1,Testrufbus"],
        "location_group_stops.txt": ["location_group_id,stop_id", "G1,at:99:2:0:1", "G1,at:99:5:0:1"],
        "booking_rules.txt": ["booking_rule_id,booking_type,booking_url,message,phone_number,"
                              "prior_notice_duration_max,prior_notice_duration_min",
                              "BR1,1,https://x,,+43 1234 5678,,60"],
    }
    paths = []
    for name, files in (("test_bahn.zip", base), ("test_flex.zip", flex)):
        p = folder / name
        p.write_bytes(_zip(files))
        paths.append(p)
    return paths


def package(folder: Path) -> bytes:
    from superkugel.transit.build import build

    out = folder / "paket.zip"
    build(write_feeds(folder / "gtfs"), out)
    return out.read_bytes()
