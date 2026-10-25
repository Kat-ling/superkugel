"""DynamoDB-/S3-/SSM-Zugriffe gegen moto (lokal simuliertes AWS – keine echten Ressourcen)."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import boto3
import pytest
from moto import mock_aws

from conftest import ROOT, book, make_mp3, speech
from superkugel.audiobooks.hosting import S3UrlSigner
from superkugel.audiobooks.importer import Importer, S3Uploader
from superkugel.audiobooks.models import Progress
from superkugel.services.storage import DynamoStore

REGION = "eu-west-1"


@pytest.fixture
def aws(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", REGION)
    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name=REGION)
        ddb.create_table(TableName="superkugel", BillingMode="PAY_PER_REQUEST",
                         KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}, {"AttributeName": "sk", "KeyType": "RANGE"}],
                         AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"},
                                               {"AttributeName": "sk", "AttributeType": "S"}])
        s3 = boto3.client("s3", region_name=REGION)
        s3.create_bucket(Bucket="audio-bucket", CreateBucketConfiguration={"LocationConstraint": REGION})
        yield ddb, s3


def test_dynamo_store_roundtrip(aws) -> None:
    ddb, _ = aws
    store = DynamoStore("superkugel", REGION, resource=ddb)
    store.put_book(book())
    assert store.get_book("mord-im-kraeuterbeet") == book()
    assert [b.book_id for b in store.list_books()] == ["mord-im-kraeuterbeet"]
    store.put_progress("u", Progress("mord-im-kraeuterbeet", chapter=2, offset_ms=5, started=True))
    assert store.list_progress("u")[0].chapter == 2
    store.put_state("u", {"book_id": "x"})
    assert store.get_state("u") == {"book_id": "x"}
    store.add_usage("2026-10-24", "2026-10", 100, 10, 55)
    store.add_usage("2026-10-24", "2026-10", 100, 10, 45)
    u = store.get_usage("DAY#2026-10-24")
    assert (u.requests, u.input_tokens, u.cost_micro_usd) == (2, 200, 100)
    store.put_conversation("u", {"turns": [{"role": "user", "content": "hi"}]}, ttl_s=60)
    assert store.get_conversation("u")["turns"][0]["content"] == "hi"
    store.put_conversation("u", {"turns": []}, ttl_s=-1)
    assert store.get_conversation("u") is None  # abgelaufen
    store.delete_book("mord-im-kraeuterbeet")
    assert store.list_books() == []


def test_presigned_url_is_sigv4_https_regional_and_expires(aws) -> None:
    url = S3UrlSigner("audio-bucket", REGION, 6 * 3600).url_for("audiobooks/x/001.mp3")
    q = parse_qs(urlparse(url).query)
    assert url.startswith("https://") and urlparse(url).netloc == f"audio-bucket.s3.{REGION}.amazonaws.com"
    assert q["X-Amz-Expires"] == ["21600"] and q["X-Amz-Algorithm"] == ["AWS4-HMAC-SHA256"]


def test_import_to_s3_dedupes_and_encrypts(aws, tmp_path: Path) -> None:
    ddb, s3 = aws
    folder = tmp_path / "Buch"
    for i in range(2):
        make_mp3(folder / f"{i + 1:02d}.mp3", 2, album="Testbuch", artist="Autorin", track=str(i + 1), salt=i)
    store = DynamoStore("superkugel", REGION, resource=ddb)
    imp = Importer(store, S3Uploader("audio-bucket", s3))
    r1 = imp.import_path(folder)
    assert r1.status == "imported" and r1.uploaded == 2
    key = store.get_book(r1.book_id).chapters[0].s3_key
    head = s3.head_object(Bucket="audio-bucket", Key=key)
    assert head["ServerSideEncryption"] == "AES256" and head["ContentType"] == "audio/mpeg"
    store.delete_book(r1.book_id)  # Bibliothekseintrag weg, Dateien noch da
    r2 = imp.import_path(folder)
    assert r2.status == "imported" and r2.uploaded == 0 and r2.skipped_uploads == 2


def test_lambda_handler_end_to_end_with_mocked_aws(aws, monkeypatch) -> None:
    ssm = boto3.client("ssm", region_name=REGION)
    ssm.put_parameter(Name="/superkugel/mode", Value="maintenance", Type="String")
    monkeypatch.setenv("AUDIO_BUCKET", "audio-bucket")
    monkeypatch.setenv("AWS_REGION", REGION)  # setzt Lambda in AWS automatisch
    import superkugel.app as app

    monkeypatch.setattr(app, "_SKILL", None)
    from conftest import launch as mk

    out = app.lambda_handler(mk(), None)
    assert out["response"]["shouldEndSession"] is True and "Pause" in speech(out)


def test_interaction_model_in_sync_and_every_intent_routed() -> None:
    import subprocess
    import sys

    model_path = ROOT / "skill-package" / "interactionModels" / "custom" / "de-DE.json"
    before = model_path.read_text(encoding="utf-8")
    subprocess.run([sys.executable, str(ROOT / "scripts" / "build_interaction_model.py")], check=True,
                   capture_output=True)
    assert model_path.read_text(encoding="utf-8") == before, "Interaction Model neu generieren!"
    model = json.loads(before)["interactionModel"]["languageModel"]
    assert model["invocationName"] == "superkugel"
    for it in model["intents"]:
        for sample in it.get("samples", []):
            assert sample == sample.lower() and len(sample.split()) <= 12
            slots = [s for s in it.get("slots", []) if "{" + s["name"] + "}" in sample]
            if any(s["type"] == "AMAZON.SearchQuery" for s in slots):
                assert sample.replace("{" + slots[0]["name"] + "}", "").strip(), "SearchQuery braucht Trägerphrase"
    # Jeder Intent landet bei einem eigenen Handler (nicht nur im Catch-all)
    from conftest import intent, make_harness

    h = make_harness()
    h.openai.replies.extend([(200, {"output": [{"type": "message", "content": [{"type": "output_text", "text": "ok"}]}]})] * 200)
    for it in model["intents"]:
        r = h.send(intent(it["name"], session={}))
        assert r["response"] is not None, it["name"]


def test_dynamo_generic_items_counters_and_search_usage(aws) -> None:
    ddb, _ = aws
    store = DynamoStore("superkugel", REGION, resource=ddb)
    store.put_item("CONTEXT", "CURRENT", {"news": {"value": ["a"], "at": 1.5}})
    assert store.get_item("CONTEXT", "CURRENT")["news"]["at"] == 1.5
    store.put_item("EPISODES", "EP#x", {"book_id": "x"}, ttl_s=60)
    assert store.get_item("EPISODES", "EP#x")["book_id"] == "x"
    store.put_item("EPISODES", "EP#old", {"book_id": "o"}, ttl_s=-10)
    assert store.get_item("EPISODES", "EP#old") is None
    store.put_item("PODCASTS", "SHOW#a", {"show_id": "a"})
    store.put_item("PODCASTS", "SHOW#b", {"show_id": "b"})
    assert [d["show_id"] for d in store.query_items("PODCASTS", "SHOW#")] == ["a", "b"]
    store.delete_item("PODCASTS", "SHOW#a")
    assert len(store.query_items("PODCASTS", "SHOW#")) == 1
    assert store.incr_counter("MEDIA#2026-10-25", ttl_s=100) == 1
    assert store.incr_counter("MEDIA#2026-10-25", ttl_s=100) == 2
    assert store.get_counter("MEDIA#2026-10-25") == 2
    store.add_usage("2026-10-25", "2026-10", 10, 1, 12000, searches=1)
    assert store.get_usage("DAY#2026-10-25").searches == 1
