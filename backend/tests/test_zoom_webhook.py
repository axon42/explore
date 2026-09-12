import hashlib
import hmac
import json
import sqlite3
import time

from fastapi.testclient import TestClient

from app.config import Settings
from app.zoom_webhook import create_webhook_app

SECRET = "synthetic-webhook-secret"


def send(client, event, timestamp=None, secret=SECRET):
    raw = json.dumps(event).encode()
    timestamp = str(timestamp or int(time.time()))
    signature = hmac.new(
        secret.encode(), b"v0:" + timestamp.encode() + b":" + raw, hashlib.sha256
    ).hexdigest()
    return client.post(
        "/webhooks/zoom",
        content=raw,
        headers={
            "Content-Type": "application/json",
            "x-zm-request-timestamp": timestamp,
            "x-zm-signature": "v0=" + signature,
        },
    )


def test_challenge_signature_and_isolation(tmp_path):
    app = create_webhook_app(Settings(data_dir=tmp_path, zoom_webhook_secret_token=SECRET))
    event = {"event": "endpoint.url_validation", "event_ts": 1, "payload": {"plainToken": "test"}}
    with TestClient(app) as client:
        result = send(client, event)
        assert result.status_code == 200
        assert (
            result.json()["encryptedToken"]
            == hmac.new(SECRET.encode(), b"test", hashlib.sha256).hexdigest()
        )
        assert send(client, event, secret="wrong").status_code == 401
        assert send(client, event, timestamp=int(time.time()) - 301).status_code == 401
        assert send(client, event, timestamp=int(time.time()) + 301).status_code == 401
        for path in ["/sessions", "/docs", "/openapi.json", "/integrations/zoom/proof"]:
            assert client.get(path).status_code == 404


def test_durable_duplicate_and_invalid_events(tmp_path):
    settings = Settings(data_dir=tmp_path, zoom_webhook_secret_token=SECRET)
    event = {
        "event": "session.rtms_started",
        "event_ts": 123,
        "payload": {
            "session_id": "session",
            "rtms_stream_id": "stream",
            "server_urls": "wss://untrusted.invalid",
        },
    }
    for _ in range(2):
        with TestClient(create_webhook_app(settings)) as client:
            assert send(client, event).status_code == 200
    with sqlite3.connect(tmp_path / "zoom-webhooks.sqlite3") as db:
        assert db.execute("SELECT count(*) FROM zoom_events").fetchone()[0] == 1
    with TestClient(create_webhook_app(settings)) as client:
        assert (
            send(
                client,
                {
                    "event": "session.rtms_stopped",
                    "event_ts": 124,
                    "payload": {
                        "session_id": "session",
                        "rtms_stream_id": "stream",
                        "stop_reason": 6,
                    },
                },
            ).status_code
            == 200
        )
        assert send(client, {**event, "payload": {}}).status_code == 400
        assert send(client, {"event": "unrelated", "event_ts": 1, "payload": {}}).json() == {
            "status": "ignored"
        }
        assert send(client, {**event, "payload": {"huge": "x" * 33000}}).status_code == 413


def test_missing_secret_fails_closed(tmp_path):
    with TestClient(
        create_webhook_app(Settings(data_dir=tmp_path, zoom_webhook_secret_token=""))
    ) as client:
        assert send(client, {}).status_code == 503
