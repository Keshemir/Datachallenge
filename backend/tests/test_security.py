import asyncio
import sqlite3
import time

import pytest
from fastapi.testclient import TestClient

from cqa.api import create_app
from cqa.audio import AudioError, download_audio, public_address
from cqa.security import SecurityStore, hash_password
from cqa.settings import Settings
from cqa.storage import Store

PASSWORD = "security-test-long-password"
ENCODED = hash_password(PASSWORD)
ORIGIN = "http://localhost:8000"


def settings(tmp_path, **kwargs):
    return Settings(db_path=tmp_path / "secure.sqlite3", password_hash=ENCODED, **kwargs)


def login(client):
    response = client.post(
        "/api/auth/login",
        json={"password": PASSWORD},
        headers={"Origin": ORIGIN, "X-CQA-Request": "1"},
    )
    assert response.status_code == 200, response.text
    client.headers.update(
        {"Origin": ORIGIN, "X-CQA-Request": "1", "X-CSRF-Token": response.json()["csrf_token"]}
    )
    return response


def test_auth_protects_every_private_surface_and_hides_docs(tmp_path):
    with TestClient(create_app(settings(tmp_path)), base_url=ORIGIN) as client:
        for path in [
            "/api/conversations",
            "/api/evaluations",
            "/api/checklists",
            "/api/usage",
            "/api/transcriptions",
            "/api/transcriptions/unknown/audio",
            "/api/decision-checks",
            "/api/health",
        ]:
            assert client.get(path).status_code == 401
        assert client.get("/healthz").json() == {"status": "ok"}
        assert client.get("/api/auth/session").json()["csrf_token"] is None
        for path in ["/docs", "/redoc", "/openapi.json", "/.env", "/.secrets/admin-password.txt"]:
            assert client.get(path).status_code == 404
        assert client.get("/api/conversations", headers={"Host": "evil.example"}).status_code == 400


def test_cookie_csrf_origin_logout_and_secret_storage(tmp_path):
    cfg = settings(tmp_path)
    with TestClient(create_app(cfg), base_url=ORIGIN) as client:
        response = login(client)
        cookie = response.headers["set-cookie"]
        assert "HttpOnly" in cookie and "SameSite=strict" in cookie
        token = client.cookies.get("cqa_session")
        assert client.get("/api/conversations").status_code == 200
        assert (
            client.post("/api/auth/logout", json={}, headers={"X-CSRF-Token": "wrong"}).status_code
            == 403
        )
        assert (
            client.post(
                "/api/auth/logout", json={}, headers={"Origin": "https://evil.example"}
            ).status_code
            == 403
        )
        assert (
            client.post("/api/auth/logout", json={}, headers={"X-CQA-Request": ""}).status_code
            == 403
        )
        assert (
            client.get("/api/conversations", headers={"Sec-Fetch-Site": "cross-site"}).status_code
            == 403
        )
        with sqlite3.connect(cfg.db_path) as db:
            stored = db.execute("SELECT token_hash FROM auth_sessions").fetchone()[0]
            assert token != stored and len(stored) == 64
        assert client.post("/api/auth/logout", json={}).status_code == 200
        client.cookies.set("cqa_session", token)
        assert client.get("/api/conversations").status_code == 401


def test_session_expiry_and_password_rotation(tmp_path):
    cfg = settings(tmp_path)
    store = Store(cfg.db_path)
    store.initialize()
    security = SecurityStore(store, cfg)
    security.initialize()
    token, _, _ = security.issue()
    assert security.resolve(token)
    changed = SecurityStore(
        store, Settings(db_path=cfg.db_path, password_hash=hash_password("changed-password-12345"))
    )
    assert changed.resolve(token) is None
    with store.connect() as db:
        db.execute("UPDATE auth_sessions SET last_seen=?", (time.time() - 1900,))
    assert security.resolve(token) is None


def test_bruteforce_rate_limit_and_no_password_echo(tmp_path):
    with TestClient(
        create_app(settings(tmp_path)),
        base_url=ORIGIN,
        headers={"Origin": ORIGIN, "X-CQA-Request": "1"},
    ) as client:
        for _ in range(5):
            assert client.post("/api/auth/login", json={"password": "wrong"}).status_code == 401
        assert client.post("/api/auth/login", json={"password": PASSWORD}).status_code == 429


def test_body_limits_before_parsing_and_security_headers(tmp_path):
    with TestClient(create_app(settings(tmp_path)), base_url=ORIGIN) as client:
        response = client.post(
            "/api/auth/login",
            json={"password": "sensitive" * 30},
            headers={"Origin": ORIGIN, "X-CQA-Request": "1"},
        )
        assert response.status_code == 422 and "sensitive" not in response.text
        login(client)
        r = client.post(
            "/api/conversations",
            content=b"x" * (2 * 1024 * 1024 + 1),
            headers={"Content-Type": "application/json"},
        )
        assert r.status_code == 413
        assert (
            client.post(
                "/api/conversations", json={}, headers={"Content-Encoding": "gzip"}
            ).status_code
            == 415
        )
        response = client.get("/api/conversations")
        assert response.headers["cache-control"] == "no-store"
        assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
        assert response.headers["x-content-type-options"] == "nosniff"


def test_chunked_limit_without_content_length(tmp_path):
    with TestClient(create_app(settings(tmp_path)), base_url=ORIGIN) as client:
        login(client)
        response = client.post(
            "/api/conversations",
            content=iter([b"x" * 1048576] * 3),
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 413


def test_paid_limits_shared_between_sessions_and_leases(tmp_path):
    with TestClient(create_app(settings(tmp_path)), base_url=ORIGIN) as client:
        login(client)
        for _ in range(3):
            assert client.post("/api/evaluations", json={}).status_code == 422
        assert client.post("/api/evaluations", json={}).status_code == 429
    store = Store(tmp_path / "leases.sqlite3")
    store.initialize()
    first = SecurityStore(store, settings(tmp_path))
    second = SecurityStore(store, settings(tmp_path))
    first.initialize()
    lease = first.lease()
    assert lease and second.lease() and first.lease() is None
    second.release(lease)
    assert first.lease()


def test_production_fails_closed_and_secure_cookie(tmp_path):
    with pytest.raises(ValueError, match="password"):
        create_app(Settings(db_path=tmp_path / "missing.sqlite3", environment="production"))
    with pytest.raises(ValueError, match="HTTPS"):
        create_app(settings(tmp_path, environment="production"))
    origin = "https://qa.example.com"
    with TestClient(
        create_app(settings(tmp_path, environment="production", allowed_origins=(origin,))),
        base_url=origin,
    ) as client:
        response = client.post(
            "/api/auth/login",
            json={"password": PASSWORD},
            headers={"Origin": origin, "X-CQA-Request": "1"},
        )
        assert response.status_code == 200
        assert "__Host-cqa_session" in response.headers["set-cookie"]
        assert "Secure" in response.headers["set-cookie"]
        assert response.headers["strict-transport-security"] == "max-age=31536000"
        assert client.get("http://qa.example.com/healthz").status_code == 400


def test_signed_audio_url_never_reaches_browser(tmp_path, conversation):
    with TestClient(create_app(settings(tmp_path)), base_url=ORIGIN) as client:
        login(client)
        body = conversation.model_dump(exclude={"transcript"})
        body["transcript"] = [m.model_dump(exclude={"message_id"}) for m in conversation.transcript]
        body["audio_url"] = "https://example.com/recording?sig=secret-signature"
        response = client.post("/api/conversations", json=body)
        assert response.status_code == 201
        assert "secret-signature" not in response.text
        record = client.get("/api/conversations/" + response.json()["hash"])
        assert "audio_url" not in record.json()["conversation"]


def test_private_dns_and_invalid_url_are_rejected(monkeypatch):
    async def run():
        loop = asyncio.get_running_loop()

        async def fake(*args, **kwargs):
            return [(None, None, None, None, ("127.0.0.1", 443))]

        monkeypatch.setattr(loop, "getaddrinfo", fake)
        with pytest.raises(AudioError, match="non-public"):
            await public_address("trusted.example")
        with pytest.raises(AudioError, match="Invalid audio URL"):
            await download_audio("https://trusted.example:invalid/a", ("trusted.example",))

    asyncio.run(run())
