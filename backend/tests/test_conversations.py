import uuid

from app.services.ai_service import trim_to_budget
from app.services.conversation_service import make_title

from .conftest import (
    Scenario,
    create_conversation,
    new_user_headers,
    send,
    signup,
    auth,
    wait_finished,
)


def test_make_title():
    assert make_title("How do I fix a flat tire?") == "How do I fix a flat tire?"
    assert make_title("\n\n  # Heading line\nmore") == "Heading line"
    long = make_title("word " * 40)
    assert len(long) <= 60 and long.endswith("…")
    assert make_title("   \n  ") == "New chat"


def test_trim_to_budget_keeps_recent_and_newest():
    msgs = [{"role": "user", "content": "x" * 400} for _ in range(10)]  # ~104 tokens each
    kept = trim_to_budget(msgs, budget=300, max_messages=50)
    assert 1 <= len(kept) <= 3 and kept[-1] is msgs[-1]
    assert trim_to_budget(msgs, budget=1, max_messages=50) == [msgs[-1]]  # newest always kept
    assert len(trim_to_budget(msgs, budget=10_000, max_messages=4)) == 4


async def test_conversation_crud(client):
    h = auth(await signup(client))
    conv = await create_conversation(client, h)
    assert conv["title"] == "New chat"

    got = await client.get(f"/api/v1/conversations/{conv['id']}", headers=h)
    assert got.status_code == 200 and got.json()["active_generation_id"] is None

    renamed = await client.patch(
        f"/api/v1/conversations/{conv['id']}", json={"title": "  My   topic "}, headers=h
    )
    assert renamed.status_code == 200 and renamed.json()["title"] == "My topic"

    blank = await client.patch(f"/api/v1/conversations/{conv['id']}", json={"title": "   "}, headers=h)
    assert blank.status_code == 422

    listing = await client.get("/api/v1/conversations", headers=h)
    assert [c["id"] for c in listing.json()["items"]] == [conv["id"]]

    deleted = await client.delete(f"/api/v1/conversations/{conv['id']}", headers=h)
    assert deleted.status_code == 204
    assert (await client.get(f"/api/v1/conversations/{conv['id']}", headers=h)).status_code == 404
    assert (await client.delete(f"/api/v1/conversations/{conv['id']}", headers=h)).status_code == 404


async def test_conversation_list_pagination_and_order(client):
    h = auth(await signup(client))
    ids = [(await create_conversation(client, h, f"chat {i}"))["id"] for i in range(5)]
    page1 = (await client.get("/api/v1/conversations?limit=2&offset=0", headers=h)).json()
    page2 = (await client.get("/api/v1/conversations?limit=2&offset=2", headers=h)).json()
    page3 = (await client.get("/api/v1/conversations?limit=2&offset=4", headers=h)).json()
    assert page1["total"] == 5 and page1["has_more"] and page2["has_more"] and not page3["has_more"]
    seen = [c["id"] for p in (page1, page2, page3) for c in p["items"]]
    assert sorted(seen) == sorted(ids) and len(set(seen)) == 5
    assert (await client.get("/api/v1/conversations?limit=0", headers=h)).status_code == 422


async def test_user_cannot_access_another_users_conversations(client):
    h_a = auth(await signup(client, "a@example.com"))
    h_b = await new_user_headers(client, "b@example.com")
    conv = await create_conversation(client, h_a, "A's private chat")
    base = f"/api/v1/conversations/{conv['id']}"

    # Every operation by user B behaves exactly like the conversation not existing.
    assert (await client.get(base, headers=h_b)).status_code == 404
    assert (await client.patch(base, json={"title": "hacked"}, headers=h_b)).status_code == 404
    assert (await client.get(f"{base}/messages", headers=h_b)).status_code == 404
    assert (await send(client, h_b, conv["id"])).status_code == 404
    assert (await client.post(f"{base}/regenerate", headers=h_b)).status_code == 404
    assert (await client.delete(base, headers=h_b)).status_code == 404
    unknown = await client.get(f"/api/v1/conversations/{uuid.uuid4()}", headers=h_b)
    assert unknown.status_code == 404
    assert (await client.get(base, headers=h_b)).json() == unknown.json() | {
        "detail": "Conversation not found"
    }

    assert (await client.get("/api/v1/conversations", headers=h_b)).json()["items"] == []
    # ...and A still has it, unchanged.
    still = await client.get(base, headers=h_a)
    assert still.status_code == 200 and still.json()["title"] == "A's private chat"

    # Unauthenticated access is rejected outright.
    assert (await client.get(base)).status_code == 401


async def test_messages_are_persisted_and_paginated(client, provider):
    h = auth(await signup(client))
    conv = await create_conversation(client, h)
    for i in range(3):
        provider.scenarios.append(Scenario(chunks=[f"answer {i}"]))
        resp = await send(client, h, conv["id"], f"question {i}")
        assert resp.status_code == 202
        await wait_finished(resp.json()["generation_id"])

    history = (await client.get(f"/api/v1/conversations/{conv['id']}/messages", headers=h)).json()
    assert not history["has_more"]
    items = history["items"]
    assert [m["sequence_number"] for m in items] == [1, 2, 3, 4, 5, 6]
    assert [m["role"] for m in items] == ["user", "assistant"] * 3
    assert [m["content"] for m in items][:2] == ["question 0", "answer 0"]
    assert all(m["status"] == "completed" for m in items)

    latest = (
        await client.get(f"/api/v1/conversations/{conv['id']}/messages?limit=2", headers=h)
    ).json()
    assert latest["has_more"] and [m["sequence_number"] for m in latest["items"]] == [5, 6]
    older = (
        await client.get(
            f"/api/v1/conversations/{conv['id']}/messages?limit=2&before_sequence=5", headers=h
        )
    ).json()
    assert [m["sequence_number"] for m in older["items"]] == [3, 4] and older["has_more"]

    # History survives "a new login": a second session for the same user sees it.
    login = await client.post(
        "/api/v1/auth/login", json={"email": "a@example.com", "password": "correct-horse-1"}
    )
    h2 = auth(login.json()["access_token"])
    again = await client.get(f"/api/v1/conversations/{conv['id']}/messages", headers=h2)
    assert len(again.json()["items"]) == 6


async def test_first_message_sets_title_without_llm_call(client, provider):
    h = auth(await signup(client))
    conv = await create_conversation(client, h)
    resp = await send(client, h, conv["id"], "Why is my build failing on CI?\nLong details...")
    await wait_finished(resp.json()["generation_id"])
    assert resp.json()["conversation"]["title"] == "Why is my build failing on CI?"
    assert len(provider.calls) == 1  # only the chat completion, no extra title request

    # A manually renamed conversation keeps its title.
    conv2 = await create_conversation(client, h, "Custom name")
    resp2 = await send(client, h, conv2["id"], "something else")
    await wait_finished(resp2.json()["generation_id"])
    assert resp2.json()["conversation"]["title"] == "Custom name"


async def test_start_creates_conversation_and_sends_first_message(client, provider):
    h = auth(await signup(client))
    provider.scenarios.append(Scenario(chunks=["first answer"]))

    resp = await client.post(
        "/api/v1/conversations/start",
        json={"content": "Why is my build failing?"},
        headers=h,
    )
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["conversation"]["title"] == "Why is my build failing?"
    assert body["user_message"]["content"] == "Why is my build failing?"
    assert body["user_message"]["sequence_number"] == 1
    assert body["assistant_message"]["sequence_number"] == 2

    await wait_finished(body["generation_id"])
    history = await client.get(
        f"/api/v1/conversations/{body['conversation']['id']}/messages", headers=h
    )
    assert [message["content"] for message in history.json()["items"]] == [
        "Why is my build failing?",
        "first answer",
    ]


async def test_message_validation(client):
    h = auth(await signup(client))
    conv = await create_conversation(client, h)
    base = f"/api/v1/conversations/{conv['id']}/messages"
    assert (await client.post(base, json={"content": ""}, headers=h)).status_code == 422
    assert (await client.post(base, json={"content": "   \n"}, headers=h)).status_code == 422
    assert (await client.post(base, json={"content": "x" * 32001}, headers=h)).status_code == 422
    assert (await client.post(base, json={}, headers=h)).status_code == 422
