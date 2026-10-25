"""Datenmodell der Hörbuchbibliothek."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class Chapter:
    index: int
    title: str
    s3_key: str
    duration_ms: int
    sha256: str
    size_bytes: int = 0
    url: str = ""  # externe HTTPS-Quelle (Podcast-Folge) statt eigener S3-Datei


@dataclass(frozen=True)
class Book:
    book_id: str
    title: str
    author: str
    genres: tuple[str, ...]
    chapters: tuple[Chapter, ...]
    series: str = ""
    series_no: float | None = None
    narrator: str = ""
    source: str = "eigene"  # thalia | eigene | podcast | frei
    imported_at: str = ""  # ISO-8601 UTC

    @property
    def duration_ms(self) -> int:
        return sum(c.duration_ms for c in self.chapters)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["genres"] = list(self.genres)
        d["chapters"] = [asdict(c) for c in self.chapters]
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Book:
        return cls(
            book_id=str(d["book_id"]),
            title=str(d["title"]),
            author=str(d.get("author", "")),
            genres=tuple(d.get("genres", ())),
            chapters=tuple(
                Chapter(
                    index=int(c["index"]),
                    title=str(c.get("title", "")),
                    s3_key=str(c["s3_key"]),
                    duration_ms=int(c.get("duration_ms", 0)),
                    sha256=str(c.get("sha256", "")),
                    size_bytes=int(c.get("size_bytes", 0)),
                    url=str(c.get("url", "")),
                )
                for c in sorted(d.get("chapters", []), key=lambda c: int(c["index"]))
            ),
            series=str(d.get("series", "")),
            series_no=(float(d["series_no"]) if d.get("series_no") not in (None, "") else None),
            narrator=str(d.get("narrator", "")),
            source=str(d.get("source", "eigene")),
            imported_at=str(d.get("imported_at", "")),
        )


@dataclass
class Progress:
    book_id: str
    chapter: int = 0
    offset_ms: int = 0
    finished: bool = False
    updated_at: float = 0.0
    started: bool = False
    failures: int = 0
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Progress:
        return cls(
            book_id=str(d["book_id"]),
            chapter=int(d.get("chapter", 0)),
            offset_ms=max(0, int(d.get("offset_ms", 0))),
            finished=bool(d.get("finished", False)),
            updated_at=float(d.get("updated_at", 0.0)),
            started=bool(d.get("started", False)),
            failures=int(d.get("failures", 0)),
        )
