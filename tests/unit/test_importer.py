from __future__ import annotations

import json
import zipfile
from pathlib import Path

from conftest import make_mp3
from superkugel.audiobooks.importer import Importer, classify, natural_key, order_files, read_audio, slugify
from superkugel.audiobooks.inbox import Inbox
from superkugel.services.storage import MemoryStore


class FakeUploader:
    def __init__(self, fail_after: int | None = None) -> None:
        self.objects: dict[str, str] = {}
        self.uploads = 0
        self.fail_after = fail_after

    def exists(self, key: str, sha256: str) -> bool:
        return self.objects.get(key) == sha256

    def upload(self, path: Path, key: str, content_type: str, sha256: str) -> None:
        if self.fail_after is not None and self.uploads >= self.fail_after:
            raise ConnectionError("Netz weg")
        assert content_type == "audio/mpeg"
        self.objects[key] = sha256
        self.uploads += 1


def _book_folder(tmp: Path, name: str = "Mord im Kräuterbeet", n: int = 3, tags: bool = True) -> Path:
    folder = tmp / name
    for i in range(n):
        # absichtlich Dateinamen, die alphabetisch falsch sortieren würden
        fname = f"Track {i + 1}.mp3" if not tags else f"{['b', 'a', 'c', 'd', 'e'][i]}.mp3"
        make_mp3(folder / fname, 2.0 + i, title=f"{i + 1:02d} - Kapitel {i + 1}" if tags else None,
                 album=name if tags else None, artist="Anna Gärtner" if tags else None,
                 track=f"{i + 1}/{n}" if tags else None, genre="Gartenkrimi" if tags else None, salt=i)
    return folder


def test_helpers() -> None:
    assert slugify("Anna Gärtner-Mord im Kräuterbeet!") == "anna-gartner-mord-im-krauterbeet"
    assert sorted(["Track 10", "Track 2", "Track 1"], key=natural_key) == ["Track 1", "Track 2", "Track 10"]


def test_read_audio_valid_and_invalid(tmp_path: Path) -> None:
    f = read_audio(make_mp3(tmp_path / "a.mp3", 5.0, album="X", track="3"))
    assert 4500 < f.duration_ms < 5500 and f.track == 3 and len(f.sha256) == 64
    bad = tmp_path / "b.mp3"
    bad.write_bytes(b"kein mp3")
    try:
        read_audio(bad)
    except Exception as exc:  # noqa: BLE001
        assert "b.mp3" in str(exc)
    else:
        raise AssertionError("ungültige Datei akzeptiert")


def test_classify_formats(tmp_path: Path) -> None:
    names = ["a.mp3", "b.M4B", "c.aax", "d.epub", "cover.jpg", "e.xyz"]
    audio, problems, ignored = classify([tmp_path / n for n in names])
    assert [p.name for p in audio] == ["a.mp3", "b.M4B"]
    assert any("kopiergeschützt" in p for p in problems) and any("E-Book" in p for p in problems)
    assert ignored == ["cover.jpg"]


def test_chapter_order_by_tags_then_filename(tmp_path: Path) -> None:
    folder = _book_folder(tmp_path)
    files = [read_audio(p) for p in sorted(folder.glob("*.mp3"))]
    assert [f.track for f in order_files(files)] == [1, 2, 3]
    names = [f.path.name for f in order_files(files, "filename")]
    assert names == ["a.mp3", "b.mp3", "c.mp3"]
    plain = _book_folder(tmp_path / "x", "Ohne Tags", 3, tags=False)
    files = [read_audio(p) for p in plain.glob("*.mp3")]
    assert [f.path.name for f in order_files(files)] == ["Track 1.mp3", "Track 2.mp3", "Track 3.mp3"]


def test_import_folder_metadata_and_dedupe(tmp_path: Path) -> None:
    store, up = MemoryStore(), FakeUploader()
    imp = Importer(store, up)
    r = imp.import_path(_book_folder(tmp_path), {"series": "Gartenkrimis", "series_no": 1})
    assert r.status == "imported" and r.chapters == 3 and r.uploaded == 3
    b = store.get_book(r.book_id)
    assert b.title == "Mord im Kräuterbeet" and b.author == "Anna Gärtner" and b.genres == ("gartenkrimi",)
    assert [c.title for c in b.chapters] == ["Kapitel 1", "Kapitel 2", "Kapitel 3"]
    assert b.series_no == 1.0
    again = imp.import_path(_book_folder(tmp_path))
    assert again.status == "already_present" and up.uploads == 3


def test_same_files_under_other_title_detected(tmp_path: Path) -> None:
    store, up = MemoryStore(), FakeUploader()
    imp = Importer(store, up)
    folder = _book_folder(tmp_path)
    imp.import_path(folder)
    r = imp.import_path(folder, {"title": "Anderer Name"})
    assert r.status == "already_present" and "bereits" in r.message


def test_import_zip_with_sidecar_and_ebook(tmp_path: Path) -> None:
    folder = _book_folder(tmp_path, tags=False)
    (folder / "book.json").write_text(json.dumps({"title": "Tod am See", "author": "H. Huber",
                                                  "genres": ["regionalkrimi"]}), encoding="utf-8")
    (folder / "bonus.pdf").write_bytes(b"%PDF")
    z = tmp_path / "download.zip"
    with zipfile.ZipFile(z, "w") as zf:
        for p in folder.rglob("*"):
            zf.write(p, p.relative_to(tmp_path))
    store = MemoryStore()
    r = Importer(store, FakeUploader()).import_path(z)
    assert r.status == "imported" and store.get_book(r.book_id).title == "Tod am See"
    assert any("E-Book" in w for w in r.warnings)


def test_ebook_only_is_not_audio(tmp_path: Path) -> None:
    (tmp_path / "e" ).mkdir()
    (tmp_path / "e" / "roman.epub").write_bytes(b"PK")
    store = MemoryStore()
    r = Importer(store, FakeUploader()).import_path(tmp_path / "e")
    assert r.status == "not_audio" and store.list_books() == []


def test_zip_slip_rejected(tmp_path: Path) -> None:
    z = tmp_path / "evil.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("../../evil.mp3", b"x")
    r = Importer(MemoryStore(), FakeUploader()).import_path(z)
    assert r.status == "failed" and "Unsicherer Pfad" in r.message


def test_interrupted_upload_resumes_without_duplicates(tmp_path: Path) -> None:
    store, up = MemoryStore(), FakeUploader(fail_after=2)
    imp = Importer(store, up)
    folder = _book_folder(tmp_path)
    try:
        imp.import_path(folder)
    except ConnectionError:
        pass
    assert store.list_books() == []  # nicht halb sichtbar
    up.fail_after = None
    r = imp.import_path(folder)
    assert r.status == "imported" and r.uploaded == 1 and r.skipped_uploads == 2


def test_zip_without_tags_at_root_uses_zip_name(tmp_path: Path) -> None:
    z = tmp_path / "Tod am Woerthersee.zip"
    src = tmp_path / "src"
    for i in range(2):
        make_mp3(src / f"{i + 1}.mp3", 2, salt=i)
    with zipfile.ZipFile(z, "w") as zf:
        for p in src.iterdir():
            zf.write(p, p.name)
    store = MemoryStore()
    r = Importer(store, FakeUploader()).import_path(z)
    assert store.get_book(r.book_id).title == "Tod am Woerthersee"


def test_book_id_sanitized_and_collision_refused(tmp_path: Path) -> None:
    store, up = MemoryStore(), FakeUploader()
    imp = Importer(store, up)
    r1 = imp.import_path(_book_folder(tmp_path / "a"), {"book_id": "../Böse ID!"})
    assert r1.book_id == "bose-id"
    other = tmp_path / "c" / "Mord im Kräuterbeet"
    for i in range(2):
        make_mp3(other / f"{i}.mp3", 4, album="Mord im Kräuterbeet", artist="Anna Gärtner", track=str(i + 1), salt=50 + i)
    assert imp.import_path(other).status == "imported"  # andere ID als r1
    third = tmp_path / "d" / "Mord im Kräuterbeet"
    for i in range(2):
        make_mp3(third / f"{i}.mp3", 5, album="Mord im Kräuterbeet", artist="Anna Gärtner", track=str(i + 1), salt=80 + i)
    clash = imp.import_path(third)
    assert clash.status == "failed" and "--replace" in clash.message
    assert imp.import_path(third, replace_existing=True).status == "imported"


def test_dry_run_uploads_nothing(tmp_path: Path) -> None:
    store, up = MemoryStore(), FakeUploader()
    r = Importer(store, up).import_path(_book_folder(tmp_path), dry_run=True)
    assert r.status == "imported" and up.uploads == 0 and store.list_books() == []


# --- Eingangsordner (Ersatz für Thalia-Synchronisation) --------------------
def test_inbox_processes_moves_logs_and_notifies(tmp_path: Path) -> None:
    inbox_dir = tmp_path / "inbox"
    _book_folder(inbox_dir)
    (inbox_dir / "Nur E-Book").mkdir()
    (inbox_dir / "Nur E-Book" / "x.epub").write_bytes(b"PK")
    notes: list[tuple[str, str]] = []
    store = MemoryStore()
    inbox = Inbox(inbox_dir, Importer(store, FakeUploader()), lambda s, b: notes.append((s, b)), min_age_s=0)
    result = inbox.process()
    statuses = {name: r.status for name, r in result.processed}
    assert statuses == {"Mord im Kräuterbeet": "imported", "Nur E-Book": "not_audio"}
    assert (inbox_dir / "fertig" / "Mord im Kräuterbeet").exists()
    assert (inbox_dir / "kein-hoerbuch" / "Nur E-Book").exists()
    assert len((inbox_dir / "sync-log.jsonl").read_text(encoding="utf-8").splitlines()) == 2
    assert notes and "1 Hörbuch" in notes[0][0]
    assert inbox.process().processed == []  # nichts doppelt


def test_inbox_retries_after_network_error(tmp_path: Path) -> None:
    inbox_dir = tmp_path / "inbox"
    _book_folder(inbox_dir)
    up = FakeUploader(fail_after=1)
    store = MemoryStore()
    inbox = Inbox(inbox_dir, Importer(store, up), min_age_s=0)
    first = inbox.process()
    assert first.processed[0][1].status == "failed"
    assert (inbox_dir / "Mord im Kräuterbeet").exists()  # bleibt liegen
    state = json.loads((inbox_dir / ".sync-state.json").read_text(encoding="utf-8"))
    assert state["Mord im Kräuterbeet"]["status"] == "pending"
    up.fail_after = None
    assert inbox.process().processed[0][1].status == "imported"
    assert len(store.list_books()) == 1


def test_inbox_accepts_single_audio_file(tmp_path: Path) -> None:
    inbox_dir = tmp_path / "inbox"
    make_mp3(inbox_dir / "Kurzgeschichte.mp3", 3, album="Kurzgeschichte", artist="X")
    store = MemoryStore()
    result = Inbox(inbox_dir, Importer(store, FakeUploader()), min_age_s=0).process()
    assert result.processed[0][1].status == "imported"
    assert (inbox_dir / "fertig" / "Kurzgeschichte.mp3").exists()


def test_inbox_ignores_fresh_and_partial_downloads(tmp_path: Path) -> None:
    inbox_dir = tmp_path / "inbox"
    _book_folder(inbox_dir)
    (inbox_dir / "halb.zip.part").write_bytes(b"x")
    inbox = Inbox(inbox_dir, Importer(MemoryStore(), FakeUploader()), min_age_s=3600)
    assert inbox.pending() == []


def test_single_file_uses_track_title_not_podcast_name(tmp_path: Path) -> None:
    f = make_mp3(tmp_path / "abc123.mp3", 3, title="Cherringham - Mord an der Themse",
                 album="Bücher! Der Lübbe Audio-Podcast", artist="Lübbe Audio")
    store = MemoryStore()
    r = Importer(store, FakeUploader()).import_path(f)
    assert store.get_book(r.book_id).title == "Cherringham - Mord an der Themse"
    g = make_mp3(tmp_path / "x" / "t.mp3", 3, title="Track 1", album="Echter Buchtitel", salt=9)
    r2 = Importer(store, FakeUploader()).import_path(g)
    assert store.get_book(r2.book_id).title == "Echter Buchtitel"


def test_missing_metadata_is_reported(tmp_path: Path) -> None:
    f = make_mp3(tmp_path / "Ordner" / "01.mp3", 2)
    r = Importer(MemoryStore(), FakeUploader()).import_path(f.parent)
    assert r.status == "imported" and any("Metadaten fehlen: Autor, Genre" in w for w in r.warnings)


def test_replace_with_same_files_updates_metadata_only(tmp_path: Path) -> None:
    store, up = MemoryStore(), FakeUploader()
    imp = Importer(store, up)
    folder = _book_folder(tmp_path)
    r1 = imp.import_path(folder)
    r2 = imp.import_path(folder, {"book_id": r1.book_id, "title": "Neuer Titel", "genres": ["krimi"]}, replace_existing=True)
    assert r2.status == "updated" and up.uploads == 3
    b = store.get_book(r1.book_id)
    assert b.title == "Neuer Titel" and b.genres == ("krimi",)
