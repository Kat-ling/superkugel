"""Abgesicherter HTTPS-Abruf für externe Quellen (ORF, Open-Meteo, Podcast-Feeds, Podcast Index).

* nur HTTPS – auch bei Weiterleitungen (kein Downgrade auf http://)
* keine Weiterleitung auf interne/private Adressen (z. B. 127.0.0.1, 169.254.x – Lambda-Laufzeit-API)
* Größen- und Zeitlimit
* XML mit Entitätsdefinitionen wird abgewiesen (Schutz vor „Billion Laughs“)
"""

from __future__ import annotations

import ipaddress
import socket
import urllib.error
import urllib.parse
import urllib.request
from typing import IO, Any

UA = "Superkugel/1.0 (privater Sprachassistent)"


class UnsafeUrl(ValueError):
    pass


def check_url(url: str) -> None:
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https" or not parts.hostname:
        raise UnsafeUrl("nur HTTPS erlaubt")
    host = parts.hostname
    try:
        infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise UnsafeUrl("Host nicht auflösbar") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise UnsafeUrl("interne Adresse")


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(_SafeRedirect())


def open_url(url: str, timeout: float, headers: dict[str, str] | None = None) -> Any:
    check_url(url)
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})  # noqa: S310 - geprüft
    return _OPENER.open(req, timeout=timeout)


def probe(url: str, timeout: float) -> tuple[int, str]:
    """Erreichbarkeit prüfen, ohne Inhalt zu laden (HEAD): (Status, Content-Type)."""
    check_url(url)
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": UA})  # noqa: S310 - geprüft
    try:
        with _OPENER.open(req, timeout=timeout) as resp:
            return int(resp.status), str(resp.headers.get("Content-Type", ""))
    except urllib.error.HTTPError as exc:
        if exc.code not in (400, 405, 501):
            raise
    # Server ohne HEAD: kurzer GET, Inhalt wird nicht gelesen
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Range": "bytes=0-0"})  # noqa: S310 - geprüft
    with _OPENER.open(req, timeout=timeout) as resp:
        return int(resp.status), str(resp.headers.get("Content-Type", ""))


def get_bytes(url: str, timeout: float, max_bytes: int, headers: dict[str, str] | None = None) -> bytes:
    with open_url(url, timeout, headers) as resp:
        data: bytes = resp.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError("Antwort zu groß")
    return data


class LimitedXmlStream:
    """Datei-Wrapper: Größenlimit und Abweisung von XML-Entitätsdefinitionen."""

    def __init__(self, f: IO[bytes], limit: int) -> None:
        self.f, self.left, self._tail = f, limit, b""

    def read(self, n: int = -1) -> bytes:
        if self.left <= 0:
            return b""
        chunk = self.f.read(min(n if n > 0 else 65536, self.left))
        self.left -= len(chunk)
        window = self._tail + chunk
        if b"<!ENTITY" in window.upper():
            raise ValueError("XML mit Entitätsdefinitionen abgewiesen")
        self._tail = window[-16:]
        return chunk


def reject_entities(data: bytes) -> bytes:
    if b"<!ENTITY" in data.upper():
        raise ValueError("XML mit Entitätsdefinitionen abgewiesen")
    return data
