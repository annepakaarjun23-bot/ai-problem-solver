from datetime import datetime, timedelta, timezone

import jwt
from sqlalchemy import select, text, update

from app.main import app
from app.models import AuthSession, User
from app.security import hash_password, verify_password_sync

from .conftest import auth, signup

ORIGIN = {"Origin": "http://localhost:8080"}


def test_password_hashing_is_argon2id():
    hashed = hash_password("s3cret-pass")
    assert hashed.startswith("$argon2id$")
    assert hashed != "s3cret-pass"
    assert verify_password_sync(hashed, "s3cret-pass")
    assert not verify_password_sync(hashed, "wrong")


async def test_signup_login_me(client):
    resp = await client.post(
        "/api/v1/auth/signup", json={"email": "User@Example.com", "password": "correct-horse-1"}
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["user"]["email"] == "user@example.com"  # normalised
    assert body["token_type"] == "bearer"
    assert "refresh_token" in resp.cookies or "refresh_token" in client.cookies
    set_cookie = resp.headers["set-cookie"].lower()
    assert "httponly" in set_cookie and "samesite=lax" in set_cookie

    me = await client.get("/api/v1/auth/me", headers=auth(body["access_token"]))
    assert me.status_code == 200 and me.json()["email"] == "user@example.com"

    login = await client.post(
        "/api/v1/auth/login", json={"email": "user@example.com", "password": "correct-horse-1"}
    )
    assert login.status_code == 200
    assert login.json()["access_token"]

    # The stored hash is Argon2id, never the plaintext.
    async with app.state.session_factory() as db:
        user = await db.scalar(select(User))
        assert user.password_hash.startswith("$argon2id$")
        assert "correct-horse-1" not in user.password_hash


async def test_signup_rejects_duplicates_and_bad_input(client):
    await signup(client, "dup@example.com")
    dup = await client.post(
        "/api/v1/auth/signup", json={"email": "DUP@example.com", "password": "correct-horse-1"}
    )
    assert dup.status_code == 409
    short = await client.post(
        "/api/v1/auth/signup", json={"email": "x@example.com", "password": "short"}
    )
    assert short.status_code == 422
    bad_email = await client.post(
        "/api/v1/auth/signup", json={"email": "not-an-email", "password": "correct-horse-1"}
    )
    assert bad_email.status_code == 422


async def test_login_failures_are_generic(client):
    await signup(client, "real@example.com")
    wrong_pw = await client.post(
        "/api/v1/auth/login", json={"email": "real@example.com", "password": "nope-nope-nope"}
    )
    unknown = await client.post(
        "/api/v1/auth/login", json={"email": "ghost@example.com", "password": "nope-nope-nope"}
    )
    assert wrong_pw.status_code == unknown.status_code == 401
    assert wrong_pw.json() == unknown.json()


async def test_jwt_validation(client):
    token = await signup(client)
    assert (await client.get("/api/v1/auth/me")).status_code == 401
    assert (await client.get("/api/v1/auth/me", headers=auth("garbage"))).status_code == 401
    assert (await client.get("/api/v1/auth/me", headers=auth(token + "x"))).status_code == 401

    claims = jwt.decode(token, options={"verify_signature": False})
    assert claims["type"] == "access" and "exp" in claims
    assert claims["exp"] - claims["iat"] <= 15 * 60  # short-lived

    expired = jwt.encode(
        {**claims, "exp": datetime.now(timezone.utc) - timedelta(minutes=1)},
        "test-secret-key-that-is-long-enough-0123456789",
        algorithm="HS256",
    )
    assert (await client.get("/api/v1/auth/me", headers=auth(expired))).status_code == 401

    wrong_key = jwt.encode(claims, "another-secret-another-secret-123456", algorithm="HS256")
    assert (await client.get("/api/v1/auth/me", headers=auth(wrong_key))).status_code == 401

    refresh_typed = jwt.encode(
        {**claims, "type": "refresh"},
        "test-secret-key-that-is-long-enough-0123456789",
        algorithm="HS256",
    )
    assert (await client.get("/api/v1/auth/me", headers=auth(refresh_typed))).status_code == 401


async def test_refresh_rotation_and_hashed_storage(client):
    await signup(client)
    old_cookie = client.cookies.get("refresh_token")
    assert old_cookie

    resp = await client.post("/api/v1/auth/refresh", headers=ORIGIN)
    assert resp.status_code == 200
    new_cookie = client.cookies.get("refresh_token")
    assert new_cookie and new_cookie != old_cookie
    assert (
        await client.get("/api/v1/auth/me", headers=auth(resp.json()["access_token"]))
    ).status_code == 200

    async with app.state.session_factory() as db:
        sessions = (await db.scalars(select(AuthSession).order_by(AuthSession.created_at))).all()
        assert len(sessions) == 2
        assert sessions[0].revoked_at is not None and sessions[1].revoked_at is None
        for s in sessions:  # raw tokens are never stored
            assert len(s.refresh_token_hash) == 64
            assert s.refresh_token_hash not in (old_cookie, new_cookie)

    # Presenting the rotated-out token again is rejected.
    client.cookies.set("refresh_token", old_cookie, path="/api/v1/auth")
    assert (await client.post("/api/v1/auth/refresh", headers=ORIGIN)).status_code == 401


async def test_refresh_token_reuse_revokes_all_sessions(client):
    await signup(client)
    old_cookie = client.cookies.get("refresh_token")
    assert (await client.post("/api/v1/auth/refresh", headers=ORIGIN)).status_code == 200
    newest = client.cookies.get("refresh_token")

    # Pretend the rotation happened long ago, then replay the old token.
    async with app.state.session_factory() as db:
        await db.execute(
            update(AuthSession)
            .where(AuthSession.revoked_at.is_not(None))
            .values(revoked_at=datetime.now(timezone.utc) - timedelta(hours=1))
        )
        await db.commit()
    client.cookies.set("refresh_token", old_cookie, path="/api/v1/auth")
    assert (await client.post("/api/v1/auth/refresh", headers=ORIGIN)).status_code == 401

    client.cookies.set("refresh_token", newest, path="/api/v1/auth")
    assert (await client.post("/api/v1/auth/refresh", headers=ORIGIN)).status_code == 401


async def test_logout_revokes_session(client):
    await signup(client)
    cookie = client.cookies.get("refresh_token")
    assert (await client.post("/api/v1/auth/logout", headers=ORIGIN)).status_code == 204
    async with app.state.session_factory() as db:
        assert await db.scalar(select(AuthSession.revoked_at)) is not None
    client.cookies.set("refresh_token", cookie, path="/api/v1/auth")
    assert (await client.post("/api/v1/auth/refresh", headers=ORIGIN)).status_code == 401


async def test_origin_validation_on_cookie_endpoints(client):
    await signup(client)
    bad = await client.post("/api/v1/auth/refresh", headers={"Origin": "http://evil.example"})
    assert bad.status_code == 403
    bad_logout = await client.post("/api/v1/auth/logout", headers={"Origin": "http://evil.example"})
    assert bad_logout.status_code == 403
    ok = await client.post("/api/v1/auth/refresh", headers=ORIGIN)
    assert ok.status_code == 200


async def test_cors_is_explicit(client):
    allowed = await client.options(
        "/api/v1/auth/me",
        headers={"Origin": "http://localhost:8080", "Access-Control-Request-Method": "GET"},
    )
    assert allowed.headers.get("access-control-allow-origin") == "http://localhost:8080"
    assert allowed.headers.get("access-control-allow-credentials") == "true"
    denied = await client.options(
        "/api/v1/auth/me",
        headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "GET"},
    )
    assert "access-control-allow-origin" not in denied.headers


async def test_health(client):
    resp = await client.get("/api/v1/health")
    assert resp.status_code == 200 and resp.json()["status"] == "ok"
    assert (await client.get("/api/v1/health")).json()["ai_configured"] is True
    async with app.state.session_factory() as db:
        assert await db.scalar(text("SELECT 1")) == 1
