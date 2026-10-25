"""Verwaltungswerkzeug für den Administrator (nicht für die Nutzerin).

Beispiele:
  python scripts/superkugel_admin.py import "D:/Thalia/Mord im Kräuterbeet.zip" --genre gartenkrimi
  python scripts/superkugel_admin.py inbox  "D:/Hoerbuch-Eingang"            # einmal verarbeiten
  python scripts/superkugel_admin.py inbox  "D:/Hoerbuch-Eingang" --watch    # dauerhaft beobachten
  python scripts/superkugel_admin.py list
  python scripts/superkugel_admin.py remove <book_id> [--delete-files]
  python scripts/superkugel_admin.py mode [normal|audiobooks_only|maintenance]
  python scripts/superkugel_admin.py usage
  python scripts/superkugel_admin.py reset-progress <book_id>

Konfiguration über Umgebungsvariablen bzw. .env: AWS_PROFILE, AWS_REGION, TABLE_NAME,
AUDIO_BUCKET, MODE_PARAM, ALERT_TOPIC_ARN (optional, für E-Mail-Benachrichtigungen).
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def _load_dotenv() -> None:
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip('"'))


def _session():
    import boto3

    return boto3.Session(profile_name=os.environ.get("AWS_PROFILE") or None,
                         region_name=os.environ.get("AWS_REGION", "eu-north-1"))


def _store(session):
    from superkugel.services.storage import DynamoStore

    return DynamoStore(os.environ.get("TABLE_NAME", "superkugel"), session.region_name,
                       resource=session.resource("dynamodb"))


def _importer(session):
    from superkugel.audiobooks.importer import Importer, S3Uploader

    bucket = os.environ.get("AUDIO_BUCKET")
    if not bucket:
        sys.exit("AUDIO_BUCKET ist nicht gesetzt (siehe .env.example).")
    return Importer(_store(session), S3Uploader(bucket, session.client("s3")))


def _notifier(session):
    arn = os.environ.get("ALERT_TOPIC_ARN")
    if not arn:
        return None
    sns = session.client("sns")
    return lambda subject, body: sns.publish(TopicArn=arn, Subject=subject[:99], Message=body)


def _meta(args: argparse.Namespace) -> dict:
    meta = {k: v for k, v in {"book_id": args.book_id, "title": args.title, "author": args.author, "series": args.series,
                              "series_no": args.series_no, "narrator": args.narrator,
                              "source": args.origin}.items() if v}
    if args.genre:
        meta["genres"] = [g.strip() for g in args.genre.split(",") if g.strip()]
    return meta


def cmd_import(args: argparse.Namespace) -> int:
    report = _importer(_session()).import_path(Path(args.path), _meta(args), order=args.order, dry_run=args.dry_run,
                                               replace_existing=args.replace)
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    return 0 if report.status in ("imported", "already_present", "updated") else 1


def cmd_inbox(args: argparse.Namespace) -> int:
    from superkugel.audiobooks.inbox import Inbox

    folder = Path(args.folder)
    try:
        session = _session()
        inbox = Inbox(folder, _importer(session), _notifier(session), min_age_s=args.min_age)
    except Exception as exc:  # noqa: BLE001 - läuft unbeaufsichtigt: Fehler protokollieren statt still scheitern
        _log_failure(folder, exc)
        return 1
    while True:
        try:
            result = inbox.process()
        except Exception as exc:  # noqa: BLE001
            _log_failure(folder, exc, inbox.notifier)
            if not args.watch:
                return 1
        else:
            if result.processed or not args.watch:
                print(result.summary, flush=True)
        if not args.watch:
            return 0
        time.sleep(args.interval)


def _log_failure(folder: Path, exc: Exception, notifier=None) -> None:
    """Schreibt Fehler des unbeaufsichtigten Laufs nach <Eingang>/sync-fehler.log (+ Mail, wenn möglich)."""
    line = f"{dt.datetime.now():%Y-%m-%d %H:%M:%S} {type(exc).__name__}: {str(exc)[:300]}\n"
    try:
        folder.mkdir(parents=True, exist_ok=True)
        with (folder / "sync-fehler.log").open("a", encoding="utf-8") as f:
            f.write(line)
    except OSError:
        pass
    print(line, file=sys.stderr)
    if notifier:
        with contextlib.suppress(Exception):  # Mail ist Zusatz; das Protokoll oben ist maßgeblich
            notifier("Superkugel: Hörbuch-Import fehlgeschlagen", line)


def cmd_list(_: argparse.Namespace) -> int:
    for b in sorted(_store(_session()).list_books(), key=lambda b: b.imported_at, reverse=True):
        hours = b.duration_ms / 3_600_000
        print(f"{b.book_id:40} {b.title[:40]:40} {b.author[:24]:24} {','.join(b.genres):20} "
              f"{len(b.chapters):3} Kap. {hours:5.1f} h  {b.imported_at}")
    return 0


def cmd_remove(args: argparse.Namespace) -> int:
    session = _session()
    store = _store(session)
    book = store.get_book(args.book_id)
    if not book:
        sys.exit("Unbekannte book_id.")
    store.delete_book(book.book_id)
    if args.delete_files:
        s3 = session.client("s3")
        for ch in book.chapters:
            s3.delete_object(Bucket=os.environ["AUDIO_BUCKET"], Key=ch.s3_key)
    print(f"Entfernt: {book.title}" + (" (inkl. Dateien)" if args.delete_files else " (Dateien bleiben im Speicher)"))
    return 0


def cmd_mode(args: argparse.Namespace) -> int:
    from superkugel.services.ops import Mode

    ssm = _session().client("ssm")
    name = os.environ.get("MODE_PARAM", "/superkugel/mode")
    if args.value:
        ssm.put_parameter(Name=name, Value=Mode(args.value).value, Type="String", Overwrite=True)
        print(f"Modus gesetzt: {args.value} (wirkt nach spätestens ca. 1 Minute)")
    else:
        print(ssm.get_parameter(Name=name)["Parameter"]["Value"])
    return 0


def cmd_usage(_: argparse.Namespace) -> int:
    store = _store(_session())
    now = dt.datetime.now(dt.UTC)
    for label, key in (("Heute", f"DAY#{now:%Y-%m-%d}"), ("Monat", f"MONTH#{now:%Y-%m}")):
        u = store.get_usage(key)
        print(f"{label}: {u.requests} KI-Anfragen, {u.input_tokens} Eingabe- / {u.output_tokens} Ausgabe-Tokens, "
              f"geschätzt {u.cost_usd:.4f} USD")
    return 0


def cmd_reset_progress(args: argparse.Namespace) -> int:
    from superkugel.audiobooks.models import Progress

    store = _store(_session())
    uid = args.user_hash
    if not uid:
        sys.exit("--user-hash erforderlich (steht in den Logs als pseudonymisierte Kennung).")
    store.put_progress(uid, Progress(book_id=args.book_id))
    print("Fortschritt zurückgesetzt.")
    return 0


def main() -> int:
    # --profile vor allem anderen auswerten, damit es Vorrang vor AWS_PROFILE aus .env hat
    if "--profile" in sys.argv:
        i = sys.argv.index("--profile")
        if i + 1 < len(sys.argv):
            os.environ["AWS_PROFILE"] = sys.argv[i + 1]
            del sys.argv[i:i + 2]
    _load_dotenv()
    p = argparse.ArgumentParser(description="Superkugel – Verwaltung (Option --profile <name> wählt das AWS-Profil)")
    sub = p.add_subparsers(dest="cmd", required=True)

    imp = sub.add_parser("import", help="Hörbuch (ZIP/Ordner/Datei) importieren")
    imp.add_argument("path", help="ZIP, Ordner oder einzelne Audiodatei")
    for opt in ("title", "author", "series", "narrator", "genre"):
        imp.add_argument(f"--{opt}")
    imp.add_argument("--series-no", dest="series_no", type=float)
    imp.add_argument("--book-id", dest="book_id", help="feste ID (z. B. zum Korrigieren mit --replace ohne Neu-Upload)")
    imp.add_argument("--source", dest="origin", default="thalia", choices=["thalia", "eigene", "podcast", "frei"])
    imp.add_argument("--order", default="auto", choices=["auto", "tags", "filename"])
    imp.add_argument("--dry-run", action="store_true")
    imp.add_argument("--replace", action="store_true", help="vorhandenes Hörbuch mit gleicher ID ersetzen")
    imp.set_defaults(fn=cmd_import)

    inb = sub.add_parser("inbox", help="Eingangsordner verarbeiten")
    inb.add_argument("folder")
    inb.add_argument("--watch", action="store_true")
    inb.add_argument("--interval", type=int, default=300)
    inb.add_argument("--min-age", type=float, default=60.0)
    inb.set_defaults(fn=cmd_inbox)

    sub.add_parser("list", help="Bibliothek anzeigen").set_defaults(fn=cmd_list)
    rm = sub.add_parser("remove", help="Hörbuch entfernen")
    rm.add_argument("book_id")
    rm.add_argument("--delete-files", action="store_true")
    rm.set_defaults(fn=cmd_remove)
    md = sub.add_parser("mode", help="Betriebsmodus lesen/setzen")
    md.add_argument("value", nargs="?", choices=["normal", "audiobooks_only", "maintenance"])
    md.set_defaults(fn=cmd_mode)
    sub.add_parser("usage", help="KI-Nutzung und geschätzte Kosten").set_defaults(fn=cmd_usage)
    rp = sub.add_parser("reset-progress", help="Fortschritt eines Buchs zurücksetzen")
    rp.add_argument("book_id")
    rp.add_argument("--user-hash", dest="user_hash")
    rp.set_defaults(fn=cmd_reset_progress)

    args = p.parse_args()
    return int(args.fn(args))


if __name__ == "__main__":
    raise SystemExit(main())
