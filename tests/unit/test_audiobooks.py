from __future__ import annotations

from conftest import FakeSigner, book
from superkugel.audiobooks import matching, player
from superkugel.audiobooks.models import Book, Progress
from superkugel.audiobooks.player import Position
from superkugel.audiobooks.service import AudiobookService
from superkugel.services.storage import MemoryStore

UID = "u1"
LIB = [
    book(),
    book("tod-am-woerthersee", "Tod am Wörthersee", "Hans Huber", ("regionalkrimi",), imported_at="2026-10-20T00:00:00+00:00",
         series="Kärnten-Krimi", series_no=2),
    book("der-zauberberg", "Der Zauberberg", "Thomas Mann", ("roman",), imported_at="2026-09-01T00:00:00+00:00"),
    book("kein-mucks-1", "Kein Mucks Folge 1", "ARD", ("hörspiel", "krimi"), imported_at="2026-08-01T00:00:00+00:00"),
]


# --- Metadaten -----------------------------------------------------------
def test_book_roundtrip_and_duration() -> None:
    b = LIB[1]
    again = Book.from_dict(b.to_dict())
    assert again == b and again.duration_ms == 3 * 600_000


def test_progress_from_dict_clamps_negative_offset() -> None:
    assert Progress.from_dict({"book_id": "x", "offset_ms": -5}).offset_ms == 0


# --- Titelsuche ----------------------------------------------------------
def test_fuzzy_title_matching() -> None:
    assert matching.best_match("mord im kräuterbeet", LIB)[0].book_id == "mord-im-kraeuterbeet"
    assert matching.best_match("kräuterbeet", LIB)[0].book_id == "mord-im-kraeuterbeet"
    assert matching.best_match("den tod am wörther see", LIB)[0].book_id == "tod-am-woerthersee"
    assert matching.best_match("zauberbergs", LIB)[0].book_id == "der-zauberberg"
    assert matching.best_match("kärnten krimi", LIB)[0].book_id == "tod-am-woerthersee"


def test_unknown_title_returns_nothing() -> None:
    b, candidates = matching.best_match("harry potter", LIB)
    assert b is None and candidates == []


def test_genre_detection_prefers_specific() -> None:
    assert matching.detect_genre("meinen neuen gartenkrimi") == "gartenkrimi"
    assert matching.detect_genre("einen Krimi") == "krimi"
    assert matching.detect_genre("ein Hörspiel") == "hörspiel"
    assert matching.detect_genre("etwas") is None


def test_krimi_includes_subgenres() -> None:
    assert matching.book_has_genre(LIB[0], "krimi") and matching.book_has_genre(LIB[1], "krimi")
    assert not matching.book_has_genre(LIB[2], "krimi")


def test_pick_by_genre_prefers_in_progress_then_unheard() -> None:
    progress = {"kein-mucks-1": Progress("kein-mucks-1", started=True, updated_at=5)}
    assert matching.pick_by_genre(LIB, "krimi", progress).book_id == "kein-mucks-1"
    assert matching.pick_by_genre(LIB, "krimi", {}).book_id == "tod-am-woerthersee"  # neuestes ungehörtes
    assert matching.pick_by_genre(LIB, "gartenkrimi", {}, newest=True).book_id == "mord-im-kraeuterbeet"
    assert matching.pick_by_genre(LIB, "märchen", {}) is None


# --- Offsets & Kapitel ---------------------------------------------------
B = book(chapters=3, dur_ms=60_000)


def test_token_roundtrip_and_invalid() -> None:
    assert player.parse_token(player.make_token("a|b", 2)) == ("a|b", 2)
    for bad in (None, "", "x", "x|y", "|1", "x|-1"):
        assert player.parse_token(bad) is None


def test_rewind_within_and_across_chapter() -> None:
    assert player.rewind(B, Position(1, 45_000), 30) == Position(1, 15_000)
    assert player.rewind(B, Position(1, 10_000), 30) == Position(0, 40_000)
    assert player.rewind(B, Position(0, 10_000), 30) == Position(0, 0)


def test_forward_and_end() -> None:
    assert player.forward(B, Position(0, 10_000), 30) == Position(0, 40_000)
    assert player.forward(B, Position(0, 50_000), 30) == Position(1, 20_000)
    assert player.forward(B, Position(2, 50_000), 30) is None


def test_clamp_and_resume() -> None:
    assert player.clamp(B, Position(9, 999_999)) == Position(2, 59_000)
    assert player.resume_position(B, 1, 3_000) == Position(1, 0)
    assert player.resume_position(B, 1, 30_000) == Position(1, 25_000)


def test_chapter_navigation() -> None:
    assert player.next_chapter(B, 1) == 2 and player.next_chapter(B, 2) is None
    assert player.previous_chapter(B, 0) == 0


# --- Fortschritt & Ereignisse --------------------------------------------
def _svc() -> tuple[AudiobookService, MemoryStore, FakeSigner]:
    store, signer = MemoryStore(), FakeSigner()
    store.put_book(B)
    return AudiobookService(store, signer, clock=lambda: 1000.0), store, signer


def test_progress_saved_on_stop_and_resumed() -> None:
    svc, store, _ = _svc()
    cmd = svc.start_or_resume(UID, B)
    assert cmd.offset_ms == 0 and cmd.behavior == "REPLACE_ALL"
    svc.on_stopped(UID, cmd.token, 42_000)
    assert store.get_progress(UID, B.book_id).offset_ms == 42_000
    again = svc.start_or_resume(UID, B)
    assert again.chapter == 0 and again.offset_ms == 37_000  # 5 s Rücksprung


def test_nearly_finished_enqueues_next_with_expected_token() -> None:
    svc, _, signer = _svc()
    cmd = svc.on_nearly_finished(UID, player.make_token(B.book_id, 0))
    assert cmd.behavior == "ENQUEUE" and cmd.chapter == 1 and cmd.expected_previous_token == f"{B.book_id}|0"
    assert signer.calls[-1].endswith("002.mp3")
    assert svc.on_nearly_finished(UID, player.make_token(B.book_id, 2)) is None


def test_finished_last_chapter_marks_book_done() -> None:
    svc, store, _ = _svc()
    svc.on_started(UID, player.make_token(B.book_id, 2), 0)
    svc.on_finished(UID, player.make_token(B.book_id, 2))
    p = store.get_progress(UID, B.book_id)
    assert p.finished and p.chapter == 0
    assert svc.current_book(UID) is None
    assert svc.start_or_resume(UID, B).offset_ms == 0  # fertig gehört → von vorne


def test_failed_playback_retries_with_fresh_url_then_gives_up() -> None:
    svc, store, _signer = _svc()
    tok = player.make_token(B.book_id, 1)
    first = svc.on_failed(UID, tok, 30_000, "MEDIA_ERROR_SERVICE_UNAVAILABLE")
    assert first and first.offset_ms == 30_000 and first.behavior == "REPLACE_ALL"
    assert svc.on_failed(UID, tok, 30_000, "x") is not None
    assert svc.on_failed(UID, tok, 30_000, "x") is None  # max. 2 Wiederholungen
    svc.on_started(UID, tok, 30_000)  # Start allein beweist nichts → keine Endlosschleife
    assert store.get_progress(UID, B.book_id).failures == 2
    svc.on_finished(UID, tok)  # erst ein fertig gespieltes Kapitel setzt zurück
    assert store.get_progress(UID, B.book_id).failures == 0


def test_failure_loop_is_bounded() -> None:
    svc, _, _ = _svc()
    tok = player.make_token(B.book_id, 1)
    replays = 0
    for _ in range(10):
        if svc.on_failed(UID, tok, 1000, "x"):
            replays += 1
        svc.on_started(UID, tok, 1000)
    assert replays == 2


def test_failed_without_position_keeps_saved_offset() -> None:
    svc, store, _ = _svc()
    store.put_progress(UID, Progress(B.book_id, chapter=1, offset_ms=44_000, started=True))
    cmd = svc.on_failed(UID, player.make_token(B.book_id, 1), None, "x")
    assert cmd.offset_ms == 44_000


def test_unknown_token_is_ignored() -> None:
    svc, _, _ = _svc()
    assert svc.on_nearly_finished(UID, "gibtsnicht|0") is None
    assert svc.on_failed(UID, "kaputt", 0, "x") is None
    svc.on_stopped(UID, "kaputt", 5)  # darf nicht crashen


def test_book_without_chapters_hidden() -> None:
    store = MemoryStore()
    store.put_book(Book("leer", "Leer", "", (), ()))
    assert AudiobookService(store, FakeSigner()).books() == []
