"""Test fixtures.

Tests run against a real PostgreSQL database (TEST_DATABASE_URL) because the application
relies on PostgreSQL features (JSONB, partial unique indexes, row locks, LangGraph's
PostgreSQL checkpointer). The AI provider is replaced with a scripted fake client so no
network access or API key is needed; the real AsyncOpenAI path is not exercised here.
"""

import asyncio
import json
import os
import time
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/aips_test"
)
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["ENVIRONMENT"] = "test"
os.environ["JWT_SECRET_KEY"] = "test-secret-key-that-is-long-enough-0123456789"
os.environ["AI_ROUTER_API_KEY"] = "test-key-not-real"
os.environ["ALLOWED_ORIGINS"] = "http://localhost:8080"

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.main import app  # noqa: E402

BACKEND_DIR = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session", autouse=True)
def migrated_database():
    """Apply the Alembic migrations from scratch once per test session."""
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    yield


# ---- fake AI provider -------------------------------------------------------------------


class Scenario:
    def __init__(self, chunks=("Hello", " world"), usage=(10, 2), error=None, hang=False, delay=0.01):
        self.chunks = list(chunks)
        self.usage = usage
        self.error = error  # raised after the chunks have been sent
        self.hang = hang  # never finish after the chunks (until cancelled)
        self.delay = delay


def _chunk(text=None, usage=None):
    choices = [SimpleNamespace(delta=SimpleNamespace(content=text))] if text is not None else []
    usage_obj = (
        SimpleNamespace(prompt_tokens=usage[0], completion_tokens=usage[1]) if usage else None
    )
    return SimpleNamespace(choices=choices, usage=usage_obj)


class FakeStream:
    def __init__(self, provider, scenario):
        self.provider = provider
        self.scenario = scenario
        self._gen = self._iterate()

    async def _iterate(self):
        s = self.scenario
        for piece in s.chunks:
            await asyncio.sleep(s.delay)
            yield _chunk(piece)
        if s.error:
            raise s.error
        if s.hang:
            await asyncio.Event().wait()
        if s.usage:
            yield _chunk(None, s.usage)

    def __aiter__(self):
        return self._gen

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        self.provider.closed_streams += 1
        await self._gen.aclose()


class FakeProvider:
    """Stands in for AsyncOpenAI: exposes client.chat.completions.create(...)."""

    def __init__(self):
        self.scenarios: list[Scenario] = []
        self.create_error: Exception | None = None
        self.calls: list[dict] = []
        self.closed_streams = 0
        self.chat = SimpleNamespace(completions=self)

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.create_error:
            raise self.create_error
        scenario = self.scenarios.pop(0) if self.scenarios else Scenario()
        return FakeStream(self, scenario)


@pytest.fixture
async def provider():
    return FakeProvider()


@pytest.fixture
async def client(provider):
    """HTTP client bound to the app with lifespan started and an empty database."""
    async with app.router.lifespan_context(app):
        async with app.state.session_factory() as db:
            await db.execute(text("TRUNCATE users CASCADE"))
            await db.commit()
        app.state.ai.client = provider
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


# ---- helpers ----------------------------------------------------------------------------


async def signup(client, email="a@example.com", password="correct-horse-1"):
    resp = await client.post("/api/v1/auth/signup", json={"email": email, "password": password})
    assert resp.status_code == 201, resp.text
    return resp.json()["access_token"]


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def new_user_headers(client, email):
    """Sign up a user on a separate cookie jar and return its auth headers."""
    resp = await client.post(
        "/api/v1/auth/signup", json={"email": email, "password": "correct-horse-1"}
    )
    assert resp.status_code == 201, resp.text
    return auth(resp.json()["access_token"])


def parse_sse(body: str) -> list[dict]:
    events = []
    for block in body.strip().split("\n\n"):
        if not block or block.startswith(":"):
            continue
        fields = {}
        for line in block.splitlines():
            key, _, value = line.partition(": ")
            fields[key] = value
        events.append(
            {"id": int(fields["id"]), "event": fields["event"], "data": json.loads(fields["data"])}
        )
    return events


async def wait_until(predicate, timeout=8.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("condition not met in time")


async def wait_finished(generation_id: str):
    """Wait until the generation task has finalised and been removed from the manager."""
    import uuid

    gid = uuid.UUID(generation_id)
    await wait_until(lambda: app.state.manager.get(gid) is None)


async def create_conversation(client, headers, title=None):
    resp = await client.post(
        "/api/v1/conversations", json={"title": title} if title else {}, headers=headers
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def send(client, headers, conversation_id, content="Hi there"):
    return await client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"content": content},
        headers=headers,
    )
