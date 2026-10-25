"""Eingangsordner-Synchronisation: der Ersatz für eine (nicht vorhandene) Thalia-Schnittstelle.

Der Administrator legt Thalia-Downloads (ZIP oder Ordner) in ``<inbox>/`` ab. ``process``
verarbeitet jeden Eintrag einmal, protokolliert das Ergebnis in ``sync-log.jsonl`` und
verschiebt ihn nach ``fertig/``, ``fehler/`` oder ``kein-hoerbuch/``.

Zustände je Eintrag (in ``.sync-state.json``, zur Nachvollziehbarkeit): importing → done | failed |
not_audio | pending (= Netz-/Dateifehler, Eintrag bleibt liegen). Maßgeblich für die Wiederholung
ist, dass der Eintrag noch im Eingang liegt; dank Prüfsummen entstehen dabei keine doppelten Uploads.
Einzelne Audiodateien (.mp3/.m4b …) direkt im Eingang werden als eigenes Hörbuch importiert.
"""

from __future__ import annotations

import datetime as dt
import json
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from superkugel.audiobooks.importer import AUDIO_EXT, Importer, ImportReport

DONE, FAILED, NOT_AUDIO = "fertig", "fehler", "kein-hoerbuch"
STATE_FILE, LOG_FILE = ".sync-state.json", "sync-log.jsonl"
_SKIP = {DONE, FAILED, NOT_AUDIO, STATE_FILE, LOG_FILE}

Notifier = Callable[[str, str], None]


@dataclass
class InboxResult:
    processed: list[tuple[str, ImportReport]] = field(default_factory=list)

    @property
    def summary(self) -> str:
        if not self.processed:
            return "Keine neuen Einträge."
        lines = []
        for name, r in self.processed:
            lines.append(f"- {name}: {r.status} – {r.message}")
            lines.extend(f"    Hinweis: {w}" for w in r.warnings)
        return "\n".join(lines)


class Inbox:
    def __init__(self, root: Path, importer: Importer, notifier: Notifier | None = None,
                 min_age_s: float = 60.0, clock: Callable[[], float] | None = None) -> None:
        self.root = Path(root)
        self.importer = importer
        self.notifier = notifier
        self.min_age_s = min_age_s  # halb kopierte Downloads nicht anfassen
        self.clock = clock or (lambda: dt.datetime.now().timestamp())
        for sub in (DONE, FAILED, NOT_AUDIO):
            (self.root / sub).mkdir(parents=True, exist_ok=True)

    def _state(self) -> dict[str, Any]:
        p = self.root / STATE_FILE
        try:
            data = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return {}

    def _save_state(self, state: dict[str, Any]) -> None:
        tmp = self.root / (STATE_FILE + ".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.root / STATE_FILE)

    def _log(self, name: str, report: ImportReport) -> None:
        entry = {"ts": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"), "item": name, **report.to_dict()}
        with (self.root / LOG_FILE).open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def pending(self) -> list[Path]:
        items = []
        for p in sorted(self.root.iterdir()):
            if p.name in _SKIP or p.name.startswith(".") or p.suffix.lower() in (".part", ".crdownload", ".tmp"):
                continue
            if not (p.is_dir() or p.suffix.lower() in (".zip", *AUDIO_EXT)):
                continue
            entries = [p, *p.rglob("*")] if p.is_dir() else [p]
            # Windows-Kopien behalten die Änderungszeit der Quelle → zusätzlich Erstellzeit (ctime) beachten
            newest = max(max(e.stat().st_mtime, e.stat().st_ctime) for e in entries)
            if self.clock() - newest < self.min_age_s:
                continue
            items.append(p)
        return items

    def process(self) -> InboxResult:
        result = InboxResult()
        state = self._state()
        for item in self.pending():
            name = item.name
            state[name] = {"status": "importing", "since": dt.datetime.now(dt.UTC).isoformat(timespec="seconds")}
            self._save_state(state)
            try:
                report = self.importer.import_path(item, meta={"source": "thalia"})
            except Exception as exc:  # noqa: BLE001 - Netzwerk/S3-Fehler: später erneut versuchen
                report = ImportReport(status="failed", message=f"Unerwarteter Fehler ({type(exc).__name__}); "
                                                               f"wird beim nächsten Lauf erneut versucht.")
                state[name] = {"status": "pending", "error": type(exc).__name__}
                self._save_state(state)
                self._log(name, report)
                result.processed.append((name, report))
                continue
            target = {"imported": DONE, "already_present": DONE, "not_audio": NOT_AUDIO}.get(report.status, FAILED)
            dest = self.root / target / name
            if dest.exists():
                dest = self.root / target / f"{dt.datetime.now():%Y%m%d-%H%M%S}-{name}"
            try:
                shutil.move(str(item), str(dest))
            except OSError as exc:  # z. B. Datei unter Windows noch geöffnet: beim nächsten Lauf erneut
                report.warnings.append(f"Konnte nicht verschoben werden ({type(exc).__name__}); wird erneut geprüft.")
                state[name] = {"status": "pending", "error": type(exc).__name__}
                self._save_state(state)
                self._log(name, report)
                result.processed.append((name, report))
                continue
            state[name] = {"status": {"fertig": "done", "fehler": "failed", "kein-hoerbuch": "not_audio"}[target],
                           "book_id": report.book_id}
            self._save_state(state)
            self._log(name, report)
            result.processed.append((name, report))
        if result.processed and self.notifier:
            ok = sum(1 for _, r in result.processed if r.status == "imported")
            self.notifier(f"Superkugel: {ok} Hörbuch/Hörbücher importiert", result.summary)
        return result
