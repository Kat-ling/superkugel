"""Privater S3-Speicher mit zeitlich begrenzten, signierten HTTPS-Links."""

from __future__ import annotations

from typing import Any, Protocol


class UrlSigner(Protocol):
    def url_for(self, s3_key: str) -> str: ...


class S3UrlSigner:
    """Erzeugt SigV4-signierte GET-URLs (HTTPS, unterstützen Byte-Range-Requests).

    Hinweis: Mit temporären Lambda-Rollen-Credentials endet eine signierte URL spätestens,
    wenn diese Credentials ablaufen – auch wenn ``expires_s`` länger ist. Deshalb erzeugt der
    Skill bei *jedem* Play-Befehl (Start, Fortsetzen, nächstes Kapitel, Fehler-Wiederholung)
    eine frische URL, und PlaybackFailed wird mit einer neuen URL beantwortet.
    """

    def __init__(self, bucket: str, region: str, expires_s: int, client: Any | None = None) -> None:
        if client is None:
            import boto3
            from botocore.config import Config

            client = boto3.client(
                "s3",
                region_name=region,
                endpoint_url=f"https://s3.{region}.amazonaws.com",
                config=Config(signature_version="s3v4", s3={"addressing_style": "virtual"}),
            )
        self.client = client
        self.bucket = bucket
        self.expires_s = expires_s

    def url_for(self, s3_key: str) -> str:
        url: str = self.client.generate_presigned_url(
            "get_object", Params={"Bucket": self.bucket, "Key": s3_key}, ExpiresIn=self.expires_s
        )
        if not url.startswith("https://"):
            raise ValueError("Audio-URL muss HTTPS sein")
        return url
