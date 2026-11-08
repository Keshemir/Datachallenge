"""Single-workspace authentication and bounded HTTP ingress. No browser-held API keys."""

import asyncio
import hashlib
import hmac
import secrets
import time
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse

from .settings import Settings
from .storage import Store

PASSWORD_N = 131072
PAID_PATHS = {
    "/api/transcriptions/auto-conversation",
    "/api/conversations/parse-text",
    "/api/evaluations",
    "/api/transcriptions",
    "/api/transcriptions/upload",
    "/api/decision-checks",
}
UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}


def password_digest(password: str, salt: bytes) -> str:
    return hashlib.scrypt(
        password.encode(), salt=salt, n=PASSWORD_N, r=8, p=1, maxmem=256 * 1024 * 1024
    ).hex()


def hash_password(password: str) -> str:
    if not 12 <= len(password) <= 128:
        raise ValueError("Use a password between 12 and 128 characters")
    salt = secrets.token_bytes(16)
    return f"scrypt${salt.hex()}${password_digest(password, salt)}"


def valid_password_hash(value: str) -> bool:
    try:
        kind, salt, digest = value.split("$")
        return (
            kind == "scrypt" and len(bytes.fromhex(salt)) == 16 and len(bytes.fromhex(digest)) == 64
        )
    except ValueError:
        return False


def verify_password(password: str, encoded: str) -> bool:
    if not valid_password_hash(encoded):
        return False
    _, salt, digest = encoded.split("$")
    return hmac.compare_digest(password_digest(password, bytes.fromhex(salt)), digest)


class SecurityStore:
    def __init__(self, store: Store, settings: Settings):
        self.store, self.settings = store, settings
        self.cookie = (
            "__Host-cqa_session" if settings.environment == "production" else "cqa_session"
        )
        self.credential_version = hashlib.sha256(settings.password_hash.encode()).hexdigest()
        self.password_slots = asyncio.Semaphore(2)

    def initialize(self):
        with self.store.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS auth_sessions (
                    token_hash TEXT PRIMARY KEY, csrf TEXT NOT NULL,
                    expires REAL NOT NULL, last_seen REAL NOT NULL, credential_version TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS rate_limits (
                    bucket TEXT PRIMARY KEY, expires REAL NOT NULL, count INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS processing_leases (
                    id TEXT PRIMARY KEY, expires REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS security_events (
                    id INTEGER PRIMARY KEY, created REAL NOT NULL, event TEXT NOT NULL
                );
            """)

    def event(self, name: str):
        with self.store.connect() as db:
            db.execute(
                "INSERT INTO security_events(created,event) VALUES (?,?)", (time.time(), name)
            )
            db.execute(
                "DELETE FROM security_events WHERE id < (SELECT max(id)-1000 FROM security_events)"
            )

    def rate(self, bucket: str, limit: int, seconds: int) -> bool:
        now = time.time()
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM rate_limits WHERE expires <= ?", (now,))
            row = db.execute("SELECT count FROM rate_limits WHERE bucket=?", (bucket,)).fetchone()
            if row and row["count"] >= limit:
                return False
            db.execute(
                "INSERT INTO rate_limits VALUES (?,?,1) ON CONFLICT(bucket) DO UPDATE SET count=count+1",
                (bucket, now + seconds),
            )
        return True

    def issue(self):
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        now = time.time()
        expires = now + self.settings.session_hours * 3600
        with self.store.connect() as db:
            db.execute(
                "DELETE FROM auth_sessions WHERE expires<=? OR last_seen<=? OR credential_version != ?",
                (now, now - 1800, self.credential_version),
            )
            db.execute(
                "INSERT INTO auth_sessions VALUES (?,?,?,?,?)",
                (
                    hashlib.sha256(token.encode()).hexdigest(),
                    csrf,
                    expires,
                    now,
                    self.credential_version,
                ),
            )
            db.execute(
                "DELETE FROM auth_sessions WHERE token_hash NOT IN (SELECT token_hash FROM auth_sessions ORDER BY last_seen DESC LIMIT 10)"
            )
        return token, csrf, expires

    def resolve(self, token: str | None):
        if not token or len(token) > 128:
            return None
        digest, now = hashlib.sha256(token.encode()).hexdigest(), time.time()
        with self.store.connect() as db:
            row = db.execute(
                "SELECT * FROM auth_sessions WHERE token_hash=? AND expires>? AND last_seen>? AND credential_version=?",
                (digest, now, now - 1800, self.credential_version),
            ).fetchone()
            if row:
                db.execute("UPDATE auth_sessions SET last_seen=? WHERE token_hash=?", (now, digest))
        return dict(row) if row else None

    def revoke(self, token: str | None):
        if token:
            with self.store.connect() as db:
                db.execute(
                    "DELETE FROM auth_sessions WHERE token_hash=?",
                    (hashlib.sha256(token.encode()).hexdigest(),),
                )

    def lease(self):
        now, identifier = time.time(), secrets.token_hex(16)
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM processing_leases WHERE expires<=?", (now,))
            if db.execute("SELECT count(*) FROM processing_leases").fetchone()[0] >= 2:
                return None
            db.execute("INSERT INTO processing_leases VALUES (?,?)", (identifier, now + 600))
        return identifier

    def release(self, identifier):
        with self.store.connect() as db:
            db.execute("DELETE FROM processing_leases WHERE id=?", (identifier,))


class SecurityMiddleware:
    def __init__(self, app, security: SecurityStore):
        self.app, self.security = app, security

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        request = Request(scope)
        path, method = scope["path"], scope["method"]
        settings, security = self.security.settings, self.security

        async def secured_send(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.extend(
                    [
                        (b"x-content-type-options", b"nosniff"),
                        (b"x-frame-options", b"DENY"),
                        (b"referrer-policy", b"no-referrer"),
                        (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
                        (
                            b"content-security-policy",
                            b"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; media-src 'self' blob:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
                        ),
                    ]
                )
                if path.startswith("/api"):
                    headers.extend([(b"cache-control", b"no-store"), (b"vary", b"Cookie")])
                if settings.environment == "production":
                    headers.append((b"strict-transport-security", b"max-age=31536000"))
                message = {**message, "headers": headers}
            await send(message)

        async def reject(status, detail):
            await JSONResponse({"detail": detail}, status_code=status)(scope, receive, secured_send)

        try:
            host = urlparse("http://" + request.headers.get("host", "")).hostname
        except ValueError:
            return await reject(400, "Invalid host")
        if host not in {urlparse(o).hostname for o in settings.allowed_origins}:
            return await reject(400, "Invalid host")
        if settings.environment == "production" and scope["scheme"] != "https":
            return await reject(400, "HTTPS is required")
        if not path.startswith("/api"):
            return await self.app(scope, receive, secured_send)
        ip = request.client.host if request.client else "unknown"
        if not security.rate("requests-" + ip, 300, 60):
            return await reject(429, "Too many requests")
        if request.headers.get("sec-fetch-site") == "cross-site":
            return await reject(403, "Cross-site requests are not allowed")
        if method in UNSAFE:
            if request.headers.get("origin") not in settings.allowed_origins:
                return await reject(403, "Request origin is not allowed")
            if request.headers.get("x-cqa-request") != "1":
                return await reject(403, "Application request header is required")

        is_login = path == "/api/auth/login" and method == "POST"
        public = is_login or path == "/api/auth/session" and method == "GET"
        session = security.resolve(request.cookies.get(security.cookie))
        if not public:
            if not session:
                return await reject(401, "Sign in to continue")
            if method in UNSAFE and not hmac.compare_digest(
                request.headers.get("x-csrf-token", ""), session["csrf"]
            ):
                return await reject(403, "Invalid CSRF token")
        scope.setdefault("state", {})["auth_session"] = session
        if is_login:
            if not security.rate("login-global", 30, 300) or not security.rate(
                "login-" + ip, 5, 300
            ):
                return await reject(429, "Too many sign-in attempts. Try again later")

        lease = None
        if method == "POST" and path in PAID_PATHS:
            if not security.rate("paid-minute", 3, 60) or not security.rate(
                "paid-hour", settings.paid_per_hour, 3600
            ):
                security.event("processing_rate_limited")
                return await reject(429, "Processing limit reached. Try again later")
            lease = security.lease()
            if lease is None:
                return await reject(429, "Two conversations are already being processed")
        try:
            if method in UNSAFE:
                limit = (
                    26 * 1024 * 1024 if path == "/api/transcriptions/upload" else 2 * 1024 * 1024
                )
                if is_login:
                    limit = 2048
                if request.headers.get("content-encoding", "identity").lower() != "identity":
                    return await reject(415, "Compressed request bodies are not accepted")
                content_type = request.headers.get("content-type", "").split(";")[0].lower()
                expected = (
                    "multipart/form-data"
                    if path == "/api/transcriptions/upload"
                    else "application/json"
                )
                if content_type != expected:
                    return await reject(415, "Unsupported content type")
                try:
                    declared = int(request.headers.get("content-length", "0"))
                except ValueError:
                    return await reject(400, "Invalid content length")
                if declared < 0 or declared > limit:
                    return await reject(413, "Request body is too large")
                chunks, size = [], 0
                try:
                    async with asyncio.timeout(60):
                        while True:
                            message = await receive()
                            if message["type"] == "http.disconnect":
                                return
                            chunk = message.get("body", b"")
                            size += len(chunk)
                            if size > limit:
                                return await reject(413, "Request body is too large")
                            chunks.append(chunk)
                            if not message.get("more_body", False):
                                break
                except TimeoutError:
                    return await reject(408, "Upload timed out")
                payload, delivered = b"".join(chunks), False

                async def bounded_receive():
                    nonlocal delivered
                    if not delivered:
                        delivered = True
                        return {"type": "http.request", "body": payload, "more_body": False}
                    return await receive()

                return await self.app(scope, bounded_receive, secured_send)
            return await self.app(scope, receive, secured_send)
        finally:
            if lease:
                security.release(lease)


class LoginInput(BaseModel):
    password: str = Field(min_length=1, max_length=128)


def auth_router(security: SecurityStore):
    router = APIRouter(prefix="/api/auth")

    @router.get("/session")
    def session(request: Request):
        record = request.state.auth_session
        return {
            "authenticated": bool(record),
            "configured": bool(security.settings.password_hash),
            "csrf_token": record["csrf"] if record else None,
        }

    @router.post("/login")
    async def login(payload: LoginInput, request: Request, response: Response):
        if not security.settings.password_hash:
            raise HTTPException(503, "Administrator password is not configured")
        async with security.password_slots:
            valid = await run_in_threadpool(
                verify_password, payload.password, security.settings.password_hash
            )
        if not valid:
            security.event("login_failed")
            raise HTTPException(401, "Invalid password")
        security.revoke(request.cookies.get(security.cookie))
        token, csrf, _ = security.issue()
        response.set_cookie(
            security.cookie,
            token,
            max_age=security.settings.session_hours * 3600,
            httponly=True,
            secure=security.settings.environment == "production",
            samesite="strict",
            path="/",
        )
        security.event("login_succeeded")
        return {"authenticated": True, "csrf_token": csrf}

    @router.post("/logout")
    def logout(request: Request, response: Response):
        security.revoke(request.cookies.get(security.cookie))
        response.delete_cookie(
            security.cookie,
            path="/",
            httponly=True,
            secure=security.settings.environment == "production",
            samesite="strict",
        )
        security.event("logout")
        return {"authenticated": False}

    return router
