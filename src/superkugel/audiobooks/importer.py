"""Import rechtmäßig erworbener, kopierschutzfreier Hörbücher (Ordner oder ZIP).

Ablauf: einlesen → prüfen → Kapitelreihenfolge → Metadaten → Upload (dedupliziert) →
Bibliothekseintrag. Der Eintrag wird erst geschrieben, wenn alle Dateien hochgeladen sind;
ein abgebrochener Import kann daher gefahrlos wiederholt werden (bereits hochgeladene
Dateien werden über ihre SHA-256-Prüfsumme erkannt und übersprungen).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import shutil
import tempfile
import unicodedata
import zipfile
from collections import Counter
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Protocol

from superkugel.audiobooks.models import Book, Chapter
from superkugel.services.storage import Store

AUDIO_EXT = {".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".m4b": "audio/mp4", ".aac": "audio/aac"}
DRM_EXT = {".aax", ".aa", ".m4p"}  # kopiergeschützt – nicht abspielbar, wird nicht umgangen
EBOOK_EXT = {".epub", ".pdf", ".mobi", ".azw", ".azw3", ".acsm"}
IGNORE_EXT = {".jpg", ".jpeg", ".png", ".gif", ".txt", ".nfo", ".m3u", ".m3u8", ".pls", ".cue", ".url",
              ".ini", ".db", ".ds_store", ".json", ".xml", ".html", ".htm", ".log", ".sfv"}
MAX_ZIP_BYTES = 8 * 1024**3


class ImportError_(Exception):
    """Verständliche Fehlermeldung für den Administrator."""


class Uploader(Protocol):
    def exists(self, key: str, sha256: str) -> bool: ...
    def upload(self, path: Path, key: str, content_type: str, sha256: str) -> None: ...


@dataclass
class AudioFile:
    path: Path
    duration_ms: int
    sha256: str
    size: int
    tags: dict[str, str] = field(default_factory=dict)
    track: int | None = None
    disc: int | None = None


@dataclass
class ImportReport:
    status: str  # imported | already_present | not_audio | failed
    book_id: str = ""
    title: str = ""
    chapters: int = 0
    uploaded: int = 0
    skipped_uploads: int = 0
    warnings: list[str] = field(default_factory=list)
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def slugify(text: str, max_len: int = 48) -> str:
    text = unicodedata.normalize("NFKD", text.replace("ß", "ss"))
    text = text.encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")[:max_len].strip("-") or "hoerbuch"


def natural_key(name: str) -> list[Any]:
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _num(value: str | None) -> int | None:
    if not value:
        return None
    m = re.match(r"\s*(\d+)", str(value))
    return int(m.group(1)) if m else None


def read_audio(path: Path) -> AudioFile:
    """Prüft eine Audiodatei mit mutagen und liest Dauer und Tags."""
    import mutagen

    try:
        audio = mutagen.File(str(path), easy=True)
    except Exception as exc:
        raise ImportError_(f"{path.name}: Datei ist beschädigt oder kein gültiges Audio ({type(exc).__name__}).") from exc
    if audio is None or not getattr(audio, "info", None):
        raise ImportError_(f"{path.name}: kein erkennbares Audioformat.")
    length = float(getattr(audio.info, "length", 0) or 0)
    if length <= 0.5:
        raise ImportError_(f"{path.name}: Audiodauer nicht lesbar oder zu kurz.")
    bitrate = int(getattr(audio.info, "bitrate", 0) or 0)
    if path.suffix.lower() == ".mp3" and bitrate and not 16_000 <= bitrate <= 384_000:
        raise ImportError_(f"{path.name}: Bitrate {bitrate // 1000} kbit/s wird von Alexa nicht unterstützt (16–384).")
    tags: dict[str, str] = {}
    for key in ("title", "album", "artist", "albumartist", "genre", "tracknumber", "discnumber", "composer"):
        try:
            val = audio.get(key) if audio.tags is not None else None
        except Exception:  # noqa: BLE001
            val = None
        if val:
            tags[key] = str(val[0]).strip()
    return AudioFile(path=path, duration_ms=int(length * 1000), sha256=sha256_file(path), size=path.stat().st_size,
                     tags=tags, track=_num(tags.get("tracknumber")), disc=_num(tags.get("discnumber")))


def classify(paths: list[Path]) -> tuple[list[Path], list[str], list[str]]:
    """Trennt Audiodateien von E-Books, DRM-Dateien und Beiwerk."""
    audio, problems, ignored = [], [], []
    for p in paths:
        ext = p.suffix.lower()
        if ext in AUDIO_EXT:
            audio.append(p)
        elif ext in DRM_EXT:
            problems.append(f"{p.name}: kopiergeschütztes Format ({ext}) – wird nicht unterstützt.")
        elif ext in EBOOK_EXT:
            problems.append(f"{p.name}: E-Book/Dokument, kein Hörbuch.")
        elif ext in IGNORE_EXT or p.name.startswith("."):
            ignored.append(p.name)
        else:
            problems.append(f"{p.name}: unbekanntes Format ({ext or 'ohne Endung'}) – übersprungen.")
    return audio, problems, ignored


def order_files(files: list[AudioFile], mode: str = "auto") -> list[AudioFile]:
    """Kapitelreihenfolge: 'tags' (Disc/Track), 'filename' (natürliche Sortierung) oder 'auto'."""
    by_name = sorted(files, key=lambda f: natural_key(str(f.path.relative_to(f.path.anchor))))
    if mode == "filename":
        return by_name
    keys = [((f.disc or 1), f.track) for f in files]
    tags_usable = all(k[1] is not None for k in keys) and len(set(keys)) == len(keys)
    if mode == "tags":
        if not tags_usable:
            raise ImportError_("Reihenfolge per Tags gewünscht, aber Tracknummern fehlen oder sind doppelt.")
        return sorted(files, key=lambda f: ((f.disc or 1), f.track or 0))
    return sorted(files, key=lambda f: ((f.disc or 1), f.track or 0)) if tags_usable else by_name


def _majority(files: list[AudioFile], key: str) -> str:
    values = [f.tags[key] for f in files if f.tags.get(key)]
    return Counter(values).most_common(1)[0][0] if values else ""


def _clean_chapter_title(f: AudioFile, idx: int) -> str:
    title = f.tags.get("title") or f.path.stem
    title = re.sub(r"^\s*\d+\s*[-_.]\s*", "", title).strip()
    return title[:120] or f"Kapitel {idx + 1}"


_GENERIC_TRACK = re.compile(r"^\s*(track|titel|kapitel|teil|part|chapter|cd)?\s*\d+\s*$", re.IGNORECASE)


def build_book(files: list[AudioFile], meta: dict[str, Any], key_prefix: str = "audiobooks",
               fallback_title: str = "") -> Book:
    # Einzeldatei (z. B. Podcast-Folge): Der Track-Titel ist der Buchtitel, das Album oft nur der Sendungsname.
    single = files[0].tags.get("title", "").strip() if len(files) == 1 else ""
    if single and _GENERIC_TRACK.match(single):
        single = ""
    title = str(meta.get("title") or single or _majority(files, "album") or fallback_title
                or files[0].path.parent.name).strip()
    author = str(meta.get("author") or _majority(files, "albumartist") or _majority(files, "artist")).strip()
    if not title:
        raise ImportError_("Kein Titel gefunden. Bitte mit --title angeben.")
    raw_genres = meta.get("genres") or [g for g in re.split(r"[;,/]", _majority(files, "genre")) if g.strip()]
    genres = tuple(sorted({str(g).strip().lower() for g in raw_genres if str(g).strip()}))
    book_id = slugify(str(meta.get("book_id") or (f"{author}-{title}" if author else title)), max_len=64)
    chapters = []
    for i, f in enumerate(files):
        ext = f.path.suffix.lower()
        chapters.append(Chapter(index=i, title=_clean_chapter_title(f, i),
                                s3_key=f"{key_prefix}/{book_id}/{i + 1:03d}-{f.sha256[:12]}{ext}",
                                duration_ms=f.duration_ms, sha256=f.sha256, size_bytes=f.size))
    series_no = meta.get("series_no")
    return Book(
        book_id=book_id, title=title, author=author, genres=genres, chapters=tuple(chapters),
        series=str(meta.get("series") or ""),
        series_no=float(series_no) if series_no not in (None, "") else None,
        narrator=str(meta.get("narrator") or _majority(files, "composer")),
        source=str(meta.get("source") or "eigene"),
        imported_at=dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
    )


def _safe_extract(zip_path: Path, target: Path) -> None:
    with zipfile.ZipFile(zip_path) as zf:
        total = sum(i.file_size for i in zf.infolist())
        if total > MAX_ZIP_BYTES:
            raise ImportError_("ZIP ist ungewöhnlich groß (> 8 GB) – Import abgebrochen.")
        root = target.resolve()
        for info in zf.infolist():
            dest = (target / info.filename).resolve()
            if not dest.is_relative_to(root):
                raise ImportError_(f"Unsicherer Pfad im ZIP: {info.filename}")
        zf.extractall(target)


def _load_sidecar(folder: Path) -> dict[str, Any]:
    # ZIPs enthalten oft einen Unterordner – flachste Fundstelle gewinnt
    found = sorted((p for name in ("book.json", "hoerbuch.json") for p in folder.rglob(name)),
                   key=lambda p: len(p.parts))
    for p in found[:1]:
        if p.exists():
            name = p.name
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise ImportError_(f"{name} ist kein gültiges JSON: {exc}") from exc
            if not isinstance(data, dict):
                raise ImportError_(f"{name} muss ein JSON-Objekt sein.")
            return data
    return {}


class Importer:
    def __init__(self, store: Store, uploader: Uploader) -> None:
        self.store = store
        self.uploader = uploader

    def import_path(self, source: Path, meta: dict[str, Any] | None = None, order: str = "auto",
                    dry_run: bool = False, replace_existing: bool = False) -> ImportReport:
        source = Path(source)
        if not source.exists():
            return ImportReport(status="failed", message=f"Nicht gefunden: {source}")
        tmp: Path | None = None
        try:
            if source.is_file() and source.suffix.lower() == ".zip":
                tmp = Path(tempfile.mkdtemp(prefix="hoerbuch-"))
                _safe_extract(source, tmp)
                folder = tmp
            elif source.is_dir():
                folder = source
            elif source.is_file():
                folder = source.parent
            else:
                return ImportReport(status="failed", message="Quelle ist weder Ordner noch ZIP.")
            meta = {**_load_sidecar(folder), **(meta or {})}
            # Titel-Notlösung: Name des ZIPs/Ordners (nicht der temporäre Entpack-Ordner)
            fallback = source.stem if source.is_file() else source.name
            if source.is_file() and source.suffix.lower() != ".zip":
                paths = [source]
            else:
                paths = [p for p in folder.rglob("*") if p.is_file() and "__MACOSX" not in p.parts]
            return self._import_files(paths, meta, order, dry_run, replace_existing, fallback)
        except ImportError_ as exc:
            return ImportReport(status="failed", message=str(exc))
        except zipfile.BadZipFile:
            return ImportReport(status="failed", message="ZIP-Datei ist beschädigt.")
        finally:
            if tmp:
                shutil.rmtree(tmp, ignore_errors=True)

    def _import_files(self, paths: list[Path], meta: dict[str, Any], order: str, dry_run: bool,
                      replace_existing: bool = False, fallback_title: str = "") -> ImportReport:
        audio_paths, problems, _ignored = classify(paths)
        if not audio_paths:
            msg = "Keine abspielbare Audiodatei gefunden."
            return ImportReport(status="not_audio", message=msg + (" " + " ".join(problems) if problems else ""),
                                warnings=problems)
        files = [read_audio(p) for p in audio_paths]
        seen: dict[str, Path] = {}
        unique: list[AudioFile] = []
        for f in files:
            if f.sha256 in seen:
                problems.append(f"{f.path.name}: identisch mit {seen[f.sha256].name} – doppelt, übersprungen.")
                continue
            seen[f.sha256] = f.path
            unique.append(f)
        ordered = order_files(unique, order)
        # Liegen die Dateien direkt im temporären Entpack-Ordner, ist dessen Name sinnlos → ZIP-Name verwenden
        in_tmp_root = ordered[0].path.parent.name.startswith("hoerbuch-")
        book = build_book(ordered, meta, fallback_title=fallback_title if in_tmp_root else "")
        report = ImportReport(status="imported", book_id=book.book_id, title=book.title,
                              chapters=len(book.chapters), warnings=problems)

        existing = self.store.get_book(book.book_id)
        if existing and [c.sha256 for c in existing.chapters] == [c.sha256 for c in book.chapters]:
            if not replace_existing:
                report.status, report.message = "already_present", "Dieses Hörbuch ist bereits in der Bibliothek."
                return report
            # Gleiche Dateien, neue Metadaten: nur den Bibliothekseintrag aktualisieren (kein Upload)
            book = replace(book, imported_at=existing.imported_at or book.imported_at)
            if not dry_run:
                self.store.put_book(book)
            report.status, report.message = "updated", f"Metadaten von „{book.title}“ aktualisiert (keine Dateien hochgeladen)."
            return report
        hashes = {c.sha256 for c in book.chapters}
        for other in self.store.list_books():
            if other.book_id != book.book_id and hashes and hashes == {c.sha256 for c in other.chapters}:
                report.status = "already_present"
                report.message = f"Dieselben Dateien sind bereits als „{other.title}“ ({other.book_id}) importiert."
                return report
        if existing and not replace_existing:
            report.status = "failed"
            report.message = (f"Es gibt schon ein anderes Hörbuch mit der ID „{book.book_id}“ (andere Dateien). "
                              "Mit --replace ersetzen (Fortschritt bleibt) oder per --title/book.json einen anderen Titel wählen.")
            return report
        if existing:
            report.warnings.append("Bestehendes Hörbuch wird ersetzt; alte Dateien bleiben im Speicher.")
            book = replace(book, imported_at=existing.imported_at or book.imported_at)
        missing = [n for n, v in (("Autor", book.author), ("Genre", book.genres)) if not v]
        if missing:
            report.warnings.append(f"Metadaten fehlen: {', '.join(missing)} – bitte mit „import --replace --book-id "
                                   f"{book.book_id} …“ ergänzen, sonst findet z. B. „Spiel einen Krimi“ das Buch nicht.")
        if dry_run:
            report.message = "Probelauf – nichts hochgeladen."
            return report

        by_sha = {f.sha256: f for f in unique}
        for ch in book.chapters:
            if self.uploader.exists(ch.s3_key, ch.sha256):
                report.skipped_uploads += 1
                continue
            f = by_sha[ch.sha256]
            self.uploader.upload(f.path, ch.s3_key, AUDIO_EXT[f.path.suffix.lower()], ch.sha256)
            report.uploaded += 1
        self.store.put_book(book)  # erst jetzt sichtbar für den Skill
        report.message = f"„{book.title}“ mit {len(book.chapters)} Kapiteln importiert."
        return report


class S3Uploader:
    """Lädt in den privaten Bucket (serverseitig verschlüsselt, kein öffentlicher Zugriff)."""

    def __init__(self, bucket: str, client: Any) -> None:
        self.bucket = bucket
        self.client = client

    def exists(self, key: str, sha256: str) -> bool:
        try:
            head = self.client.head_object(Bucket=self.bucket, Key=key)
        except Exception as exc:
            code = getattr(exc, "response", {}).get("Error", {}).get("Code", "")
            if code in ("404", "NoSuchKey", "NotFound"):
                return False
            raise
        return bool(head.get("Metadata", {}).get("sha256") == sha256)

    def upload(self, path: Path, key: str, content_type: str, sha256: str) -> None:
        self.client.upload_file(
            str(path), self.bucket, key,
            ExtraArgs={"ContentType": content_type, "Metadata": {"sha256": sha256},
                       "ServerSideEncryption": "AES256"},
        )
