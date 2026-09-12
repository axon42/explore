import jwt
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_proof_disabled_and_secrets_redacted(tmp_path):
    with TestClient(create_app(Settings(data_dir=tmp_path, zoom_proof_enabled=False))) as client:
        assert client.get("/integrations/zoom/proof").json()["enabled"] is False
        assert (
            client.post(
                "/integrations/zoom/proof/join",
                json={"name": "Test"},
                headers={"Origin": "http://localhost:5173"},
            ).status_code
            == 409
        )


def test_proof_tokens_are_scoped_and_bounded(tmp_path):
    secret = "synthetic-test-secret-that-is-at-least-32-bytes"
    settings = Settings(
        data_dir=tmp_path,
        zoom_proof_enabled=True,
        zoom_video_sdk_key="test-key",
        zoom_video_sdk_secret=secret,
    )
    with TestClient(create_app(settings)) as client:
        path = "/integrations/zoom/proof/join"
        headers = {"Origin": "http://localhost:5173"}
        assert client.post(path, json={"name": "A"}).status_code == 403
        assert (
            client.post(
                path, json={"name": "A"}, headers={"Origin": "https://evil.test"}
            ).status_code
            == 403
        )
        assert (
            client.post(path, json={"name": "A", "role_type": 1}, headers=headers).status_code
            == 422
        )
        assert client.post(path, json={"name": "   "}, headers=headers).status_code == 422
        rooms = set()
        for index in range(4):
            result = client.post(path, json={"name": f"Test {index}"}, headers=headers)
            assert result.headers["cache-control"] == "no-store"
            payload = result.json()
            claims = jwt.decode(payload["videoSDKJWT"], secret, algorithms=["HS256"])
            assert claims["role_type"] == (1 if index == 0 else 0)
            assert claims["exp"] - claims["iat"] == 1800
            assert claims["tpc"] == payload["sessionName"]
            assert secret not in result.text
            rooms.add(claims["tpc"])
        assert len(rooms) == 1
        assert client.post(path, json={"name": "Fifth"}, headers=headers).status_code == 429
