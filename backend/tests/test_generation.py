import uuid

import httpx
import openai
import pytest
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver  # noqa: F401
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.config import get_settings
from app.main import app
from app.models import Conversation, Generation, GenerationEvent, Message
from app.services.generation_manager import mark_interrupted_generations

from .conftest import (
    Scenario,
    auth,
    create_conversation,
    new_user_headers,
    parse_sse,
    send,
    signup,
    wait_finished,
    wait_until,
)


async def get_events(client, headers, generation_id, last_event_id=None):
    hdrs = dict(headers)
    if last_event_id is not None:
        hdrs["Last-Event-ID"] = str(last_event_id)
    resp = await client.get(f"/api/v1/generations/{generation_id}/events", headers=hdrs)
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/event-stream")
    return parse_sse(resp.text)


async def messages(client, headers, conversation_id):
    resp = await client.get(f"/api/v1/conversations/{conversation_id}/messages", headers=headers)
    return resp.json()["items"]


async def setup_chat(client):
    headers = auth(await signup(client))
    conv = await create_conversation(client, headers)
    return headers, conv


async def test_generation_happy_path_and_event_order(client, provider):
    h, conv = await setup_chat(client)
    provider.scenarios.append(Scenario(chunks=["Hel", "lo ", "world"], usage=(21, 3)))
    resp = await send(client, h, conv["id"], "Say hello")
    assert resp.status_code == 202
    body = resp.json()
    assert body["events_url"] == f"/api/v1/generations/{body['generation_id']}/events"
    assert body["user_message"]["role"] == "user" and body["user_message"]["content"] == "Say hello"
    assert body["assistant_message"]["status"] == "streaming"
    await wait_finished(body["generation_id"])

    events = await get_events(client, h, body["generation_id"])
    types = [e["event"] for e in events]
    assert [e["id"] for e in events] == list(range(1, len(events) + 1))  # strictly ordered ids
    assert types[0] == "generation_started"
    assert types[-1] == "message_completed"
    assert types.count("message_completed") == 1
    statuses = [e["data"]["message"] for e in events if e["event"] == "status"]
    assert statuses == ["Preparing context…", "Generating response…"]
    # status events come before any text; text comes before completion
    assert types.index("message_delta") > max(i for i, t in enumerate(types) if t == "status")
    text = "".join(e["data"]["text"] for e in events if e["event"] == "message_delta")
    assert text == "Hello world"
    assert events[-1]["data"]["input_tokens"] == 21 and events[-1]["data"]["output_tokens"] == 3

    msgs = await messages(client, h, conv["id"])
    assistant = msgs[-1]
    assert assistant["role"] == "assistant" and assistant["status"] == "completed"
    assert assistant["content"] == "Hello world"
    assert assistant["input_tokens"] == 21 and assistant["output_tokens"] == 3
    assert assistant["model_name"] == get_settings().AI_ROUTER_MODEL

    # Provider was called as configured: configured model, streaming on, system prompt first.
    call = provider.calls[0]
    assert call["model"] == get_settings().AI_ROUTER_MODEL and call["stream"] is True
    assert call["messages"][0]["role"] == "system"
    assert call["messages"][-1] == {"role": "user", "content": "Say hello"}

    # Status transitions are persisted on the generation row.
    async with app.state.session_factory() as db:
        gen = await db.get(Generation, uuid.UUID(body["generation_id"]))
        assert gen.status == "completed" and gen.completed_at is not None
    detail = (await client.get(f"/api/v1/conversations/{conv['id']}", headers=h)).json()
    assert detail["active_generation_id"] is None


async def test_context_includes_prior_turns_only(client, provider):
    h, conv = await setup_chat(client)
    provider.scenarios += [Scenario(chunks=["first answer"]), Scenario(chunks=["second answer"])]
    r1 = await send(client, h, conv["id"], "first question")
    await wait_finished(r1.json()["generation_id"])
    r2 = await send(client, h, conv["id"], "second question")
    await wait_finished(r2.json()["generation_id"])
    sent = provider.calls[1]["messages"]
    assert [m["role"] for m in sent] == ["system", "user", "assistant", "user"]
    assert [m["content"] for m in sent][1:] == ["first question", "first answer", "second question"]


async def test_reconnect_replays_from_last_event_id(client, provider):
    h, conv = await setup_chat(client)
    provider.scenarios.append(Scenario(chunks=["a", "b", "c", "d"], delay=0.12))
    resp = await send(client, h, conv["id"])
    gid = resp.json()["generation_id"]
    await wait_finished(gid)

    full = await get_events(client, h, gid)
    assert len(full) >= 4
    tail = await get_events(client, h, gid, last_event_id=2)
    assert [e["id"] for e in tail] == [e["id"] for e in full if e["id"] > 2]
    assert tail[-1]["event"] == "message_completed"
    assert await get_events(client, h, gid, last_event_id=full[-1]["id"]) == []
    # Garbage ids fall back to a full replay rather than failing.
    assert len(await get_events(client, h, gid, last_event_id="oops")) == len(full)


async def test_live_stream_follows_run_and_resumes(client, provider):
    """An SSE connection opened mid-generation receives the rest of the events."""
    h, conv = await setup_chat(client)
    provider.scenarios.append(Scenario(chunks=["x"] * 6, delay=0.15))
    resp = await send(client, h, conv["id"])
    gid = resp.json()["generation_id"]
    # Connect while the generation is still running; the response completes on the terminal event.
    events = await get_events(client, h, gid)
    assert events[0]["event"] == "generation_started"
    assert events[-1]["event"] == "message_completed"
    assert "".join(e["data"]["text"] for e in events if e["event"] == "message_delta") == "x" * 6


async def test_only_one_active_generation_per_conversation(client, provider):
    h, conv = await setup_chat(client)
    provider.scenarios.append(Scenario(chunks=["partial"], hang=True))
    first = await send(client, h, conv["id"], "first")
    assert first.status_code == 202
    gid = first.json()["generation_id"]

    second = await send(client, h, conv["id"], "second")
    assert second.status_code == 409
    regen = await client.post(f"/api/v1/conversations/{conv['id']}/regenerate", headers=h)
    assert regen.status_code == 409
    detail = (await client.get(f"/api/v1/conversations/{conv['id']}", headers=h)).json()
    assert detail["active_generation_id"] == gid
    assert len(await messages(client, h, conv["id"])) == 2  # the rejected send stored nothing

    # The database itself also refuses a second running generation.
    async with app.state.session_factory() as db:
        first_gen = await db.get(Generation, uuid.UUID(gid))
        db.add(
            Generation(
                user_id=first_gen.user_id,
                conversation_id=first_gen.conversation_id,
                assistant_message_id=first_gen.assistant_message_id,
                status="running",
            )
        )
        with pytest.raises(IntegrityError):
            await db.flush()
        await db.rollback()

    # A different conversation is unaffected.
    other = await create_conversation(client, h)
    provider.scenarios.append(Scenario(chunks=["ok"]))
    assert (await send(client, h, other["id"], "hello")).status_code == 202

    cancel = await client.post(f"/api/v1/generations/{gid}/cancel", headers=h)
    assert cancel.status_code == 200


async def test_cancel_stops_task_closes_provider_stream_and_keeps_partial(client, provider):
    h, conv = await setup_chat(client)
    provider.scenarios.append(Scenario(chunks=["Par", "tial ", "text"], hang=True))
    resp = await send(client, h, conv["id"], "long question")
    gid = resp.json()["generation_id"]
    run = app.state.manager.get(uuid.UUID(gid))
    assert run is not None
    await wait_until(lambda: any(e.type == "message_delta" for e in run.events))
    assert provider.closed_streams == 0

    cancel = await client.post(f"/api/v1/generations/{gid}/cancel", headers=h)
    assert cancel.status_code == 200 and cancel.json()["status"] == "cancelled"
    assert run.task.done()  # the asyncio task really ended
    assert provider.closed_streams == 1  # the provider stream was closed
    assert app.state.manager.get(uuid.UUID(gid)) is None

    assistant = (await messages(client, h, conv["id"]))[-1]
    assert assistant["status"] == "cancelled"
    assert assistant["content"] in ("Par", "Partial ", "Partial text", "")  # whatever arrived
    events = await get_events(client, h, gid)
    assert events[-1]["event"] == "generation_cancelled"
    assert [e["id"] for e in events] == list(range(1, len(events) + 1))

    # Cancelling again is harmless, and the conversation accepts new messages afterwards.
    again = await client.post(f"/api/v1/generations/{gid}/cancel", headers=h)
    assert again.status_code == 200 and again.json()["status"] == "cancelled"
    provider.scenarios.append(Scenario(chunks=["fine"]))
    nxt = await send(client, h, conv["id"], "next")
    assert nxt.status_code == 202
    await wait_finished(nxt.json()["generation_id"])

    # The cancelled assistant message is not fed back to the model as context.
    sent = provider.calls[-1]["messages"]
    assert [m["content"] for m in sent if m["role"] == "assistant"] == []


async def test_cancel_keeps_partial_text(client, provider):
    h, conv = await setup_chat(client)
    provider.scenarios.append(Scenario(chunks=["keep ", "me"], hang=True, delay=0.01))
    gid = (await send(client, h, conv["id"])).json()["generation_id"]
    run = app.state.manager.get(uuid.UUID(gid))
    await wait_until(lambda: len(run.content_parts) == 2)
    await client.post(f"/api/v1/generations/{gid}/cancel", headers=h)
    assert (await messages(client, h, conv["id"]))[-1]["content"] == "keep me"


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (
            openai.AuthenticationError(
                "bad key",
                response=httpx.Response(401, request=httpx.Request("POST", "http://x")),
                body=None,
            ),
            "API key",
        ),
        (
            openai.RateLimitError(
                "slow down",
                response=httpx.Response(429, request=httpx.Request("POST", "http://x")),
                body=None,
            ),
            "rate limit",
        ),
        (
            openai.NotFoundError(
                "no model",
                response=httpx.Response(404, request=httpx.Request("POST", "http://x")),
                body=None,
            ),
            "model",
        ),
        (openai.APITimeoutError(request=httpx.Request("POST", "http://x")), "timed out"),
        (
            openai.APIConnectionError(request=httpx.Request("POST", "http://x")),
            "connection",
        ),
    ],
)
async def test_provider_errors_fail_cleanly(client, provider, error, expected):
    h, conv = await setup_chat(client)
    provider.create_error = error
    resp = await send(client, h, conv["id"], "hello")
    assert resp.status_code == 202
    gid = resp.json()["generation_id"]
    await wait_finished(gid)

    events = await get_events(client, h, gid)
    assert events[-1]["event"] == "generation_failed"
    assert expected.lower() in events[-1]["data"]["error"].lower()
    assert "message_completed" not in [e["event"] for e in events]

    assistant = (await messages(client, h, conv["id"]))[-1]
    assert assistant["status"] == "failed" and assistant["content"] == ""
    assert expected.lower() in assistant["error_message"].lower()  # visible after a reload
    async with app.state.session_factory() as db:
        gen = await db.get(Generation, uuid.UUID(gid))
        assert gen.status == "failed" and gen.error_message
    # No stuck "active" generation: the user can retry.
    detail = (await client.get(f"/api/v1/conversations/{conv['id']}", headers=h)).json()
    assert detail["active_generation_id"] is None


async def test_interrupted_stream_keeps_partial_and_reports_failure(client, provider):
    h, conv = await setup_chat(client)
    provider.scenarios.append(
        Scenario(chunks=["Half an ans"], error=httpx.RemoteProtocolError("connection dropped"))
    )
    gid = (await send(client, h, conv["id"])).json()["generation_id"]
    await wait_finished(gid)
    events = await get_events(client, h, gid)
    assert events[-1]["event"] == "generation_failed"
    assert "cut off" in events[-1]["data"]["error"] and events[-1]["data"]["partial"] is True
    assistant = (await messages(client, h, conv["id"]))[-1]
    assert assistant["status"] == "failed" and assistant["content"] == "Half an ans"


async def test_empty_provider_response_is_a_failure(client, provider):
    h, conv = await setup_chat(client)
    provider.scenarios.append(Scenario(chunks=[], usage=None))
    gid = (await send(client, h, conv["id"])).json()["generation_id"]
    await wait_finished(gid)
    events = await get_events(client, h, gid)
    assert events[-1]["event"] == "generation_failed"
    assert "empty" in events[-1]["data"]["error"].lower()


async def test_missing_api_key_gives_clear_error_but_app_works(client, provider):
    app.state.ai.client = None  # what the app does at startup when no key is configured
    h, conv = await setup_chat(client)  # auth and conversation management still work
    assert (await client.get("/api/v1/conversations", headers=h)).status_code == 200
    resp = await send(client, h, conv["id"], "hello?")
    assert resp.status_code == 202
    gid = resp.json()["generation_id"]
    await wait_finished(gid)
    events = await get_events(client, h, gid)
    assert events[-1]["event"] == "generation_failed"
    assert "AI_ROUTER_API_KEY" in events[-1]["data"]["error"]
    assert provider.calls == []  # nothing was sent anywhere
    assistant = (await messages(client, h, conv["id"]))[-1]
    assert assistant["status"] == "failed" and "AI_ROUTER_API_KEY" in assistant["error_message"]


async def test_regenerate_replaces_last_assistant_message(client, provider):
    h, conv = await setup_chat(client)
    provider.scenarios += [Scenario(chunks=["old answer"]), Scenario(chunks=["new answer"])]
    r1 = await send(client, h, conv["id"], "question")
    await wait_finished(r1.json()["generation_id"])
    before = await messages(client, h, conv["id"])

    regen = await client.post(f"/api/v1/conversations/{conv['id']}/regenerate", headers=h)
    assert regen.status_code == 202
    body = regen.json()
    assert body["user_message"] is None
    assert body["assistant_message"]["id"] == before[-1]["id"]
    assert body["generation_id"] != r1.json()["generation_id"]
    await wait_finished(body["generation_id"])

    after = await messages(client, h, conv["id"])
    assert [m["sequence_number"] for m in after] == [1, 2]
    assert after[-1]["content"] == "new answer" and after[-1]["status"] == "completed"
    # The regenerated answer was produced from the same context (old answer excluded).
    assert [m["content"] for m in provider.calls[1]["messages"][1:]] == ["question"]
    async with app.state.session_factory() as db:
        gens = (await db.scalars(select(Generation))).all()
        assert len(gens) == 2 and all(g.status == "completed" for g in gens)


async def test_regenerate_after_failure_recovers(client, provider):
    h, conv = await setup_chat(client)
    provider.create_error = openai.APIConnectionError(request=httpx.Request("POST", "http://x"))
    r1 = await send(client, h, conv["id"], "question")
    await wait_finished(r1.json()["generation_id"])
    assert (await messages(client, h, conv["id"]))[-1]["status"] == "failed"

    provider.create_error = None
    provider.scenarios.append(Scenario(chunks=["recovered"]))
    regen = await client.post(f"/api/v1/conversations/{conv['id']}/regenerate", headers=h)
    await wait_finished(regen.json()["generation_id"])
    last = (await messages(client, h, conv["id"]))[-1]
    assert last["status"] == "completed" and last["content"] == "recovered"
    assert last["error_message"] is None


async def test_regenerate_without_assistant_message_is_rejected(client):
    h, conv = await setup_chat(client)
    resp = await client.post(f"/api/v1/conversations/{conv['id']}/regenerate", headers=h)
    assert resp.status_code == 409


async def test_generation_endpoints_enforce_ownership(client, provider):
    h_a, conv = await setup_chat(client)
    h_b = await new_user_headers(client, "b@example.com")
    gid = (await send(client, h_a, conv["id"])).json()["generation_id"]
    await wait_finished(gid)
    assert (await client.get(f"/api/v1/generations/{gid}/events", headers=h_b)).status_code == 404
    assert (await client.post(f"/api/v1/generations/{gid}/cancel", headers=h_b)).status_code == 404
    unknown = uuid.uuid4()
    assert (await client.get(f"/api/v1/generations/{unknown}/events", headers=h_a)).status_code == 404
    assert (await client.get(f"/api/v1/generations/{gid}/events")).status_code == 401


async def test_startup_marks_running_generations_interrupted(client):
    h, conv = await setup_chat(client)
    async with app.state.session_factory() as db:
        conv_row = await db.get(Conversation, uuid.UUID(conv["id"]))
        user_id = conv_row.user_id
        msg = Message(
            conversation_id=conv_row.id,
            sequence_number=1,
            role="assistant",
            content="",
            status="streaming",
        )
        db.add(msg)
        await db.flush()
        gen = Generation(
            user_id=user_id, conversation_id=conv_row.id, assistant_message_id=msg.id, status="running"
        )
        db.add(gen)
        await db.flush()
        db.add(
            GenerationEvent(
                generation_id=gen.id, event_sequence=1, event_type="generation_started", payload={}
            )
        )
        await db.commit()
        gen_id, msg_id = gen.id, msg.id

    assert await mark_interrupted_generations(app.state.session_factory) == 1

    async with app.state.session_factory() as db:
        gen = await db.get(Generation, gen_id)
        msg = await db.get(Message, msg_id)
        assert gen.status == "interrupted" and "restart" in gen.error_message
        assert msg.status == "interrupted"
    events = await get_events(client, h, str(gen_id))
    assert [e["event"] for e in events] == ["generation_started", "generation_failed"]
    assert events[-1]["data"]["interrupted"] is True
    # The conversation is usable again.
    detail = (await client.get(f"/api/v1/conversations/{conv['id']}", headers=h)).json()
    assert detail["active_generation_id"] is None


async def test_shutdown_interrupts_running_generation(client, provider):
    h, conv = await setup_chat(client)
    provider.scenarios.append(Scenario(chunks=["abc"], hang=True))
    gid = (await send(client, h, conv["id"])).json()["generation_id"]
    run = app.state.manager.get(uuid.UUID(gid))
    await wait_until(lambda: any(e.type == "message_delta" for e in run.events))
    await app.state.manager.shutdown()
    async with app.state.session_factory() as db:
        gen = await db.get(Generation, uuid.UUID(gid))
        assert gen.status == "interrupted"
    assert provider.closed_streams == 1


async def test_langgraph_checkpoint_is_written_and_removed_with_conversation(client, provider):
    h, conv = await setup_chat(client)
    provider.scenarios.append(Scenario(chunks=["checkpointed"]))
    gid = (await send(client, h, conv["id"], "remember me")).json()["generation_id"]
    await wait_finished(gid)

    config = {"configurable": {"thread_id": conv["id"]}}
    checkpoint = await app.state.checkpointer.aget_tuple(config)
    assert checkpoint is not None
    values = checkpoint.checkpoint["channel_values"]
    assert values["response"] == "checkpointed"
    assert values["transcript"] == []  # full history is not kept in checkpoint state
    assert values["context"][0]["role"] == "system"

    assert (await client.delete(f"/api/v1/conversations/{conv['id']}", headers=h)).status_code == 204
    assert await app.state.checkpointer.aget_tuple(config) is None
    async with app.state.session_factory() as db:  # cascade removed everything else
        assert (await db.scalars(select(Message))).all() == []
        assert (await db.scalars(select(Generation))).all() == []
        assert (await db.scalars(select(GenerationEvent))).all() == []


async def test_delete_conversation_cancels_running_generation(client, provider):
    h, conv = await setup_chat(client)
    provider.scenarios.append(Scenario(chunks=["abc"], hang=True))
    gid = (await send(client, h, conv["id"])).json()["generation_id"]
    run = app.state.manager.get(uuid.UUID(gid))
    await wait_until(lambda: any(e.type == "message_delta" for e in run.events))
    assert (await client.delete(f"/api/v1/conversations/{conv['id']}", headers=h)).status_code == 204
    assert run.task.done() and provider.closed_streams == 1
    assert (await client.get(f"/api/v1/conversations/{conv['id']}", headers=h)).status_code == 404
