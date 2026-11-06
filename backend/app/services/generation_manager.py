"""In-process generation runner.

Each generation is an asyncio task that is independent of any HTTP connection. Events are:
  * published to an in-memory list that live SSE subscribers read from (immediately), and
  * persisted to `generation_events` in batches (roughly every half second, plus at the end),
    so reconnecting clients can replay them using Last-Event-ID.

Token deltas are coalesced (~80 ms) before becoming events, and no database transaction is
held open while the provider streams.

Limitation: tasks live in this process. A backend restart interrupts running generations;
`mark_interrupted_generations` records that honestly on the next startup.
"""

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import Conversation, Generation, GenerationEvent, Message
from app.services.ai_service import AIConfigError, AIProviderError, AIService

log = logging.getLogger(__name__)

TERMINAL_EVENTS = {"message_completed", "generation_failed", "generation_cancelled"}
DELTA_INTERVAL = 0.08  # seconds between coalesced delta events
PERSIST_EVERY_TICKS = 6  # persist pending events about every 0.5 s
HEARTBEAT_SECONDS = 15.0


@dataclass
class GenerationSpec:
    generation_id: uuid.UUID
    user_id: uuid.UUID
    conversation_id: uuid.UUID
    assistant_message_id: uuid.UUID
    assistant_sequence: int  # context is built from messages before this sequence number
    model: str


@dataclass
class RunEvent:
    seq: int
    type: str
    payload: dict[str, Any]


@dataclass
class GenerationRun:
    spec: GenerationSpec
    events: list[RunEvent] = field(default_factory=list)
    persisted: int = 0  # number of events already written to the database
    done: bool = False
    task: asyncio.Task | None = None
    cancel_reason: str | None = None  # "user" | "shutdown"
    pending_text: list[str] = field(default_factory=list)
    content_parts: list[str] = field(default_factory=list)
    usage: dict[str, Any] | None = None
    cond: asyncio.Condition = field(default_factory=asyncio.Condition)
    persist_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def _append(self, event_type: str, payload: dict[str, Any]) -> RunEvent:
        # Synchronous on purpose: sequence numbers are assigned in call order.
        event = RunEvent(seq=len(self.events) + 1, type=event_type, payload=payload)
        self.events.append(event)
        return event

    async def publish(self, event_type: str, payload: dict[str, Any]) -> RunEvent:
        event = self._append(event_type, payload)
        async with self.cond:
            self.cond.notify_all()
        return event

    async def mark_done(self) -> None:
        self.done = True
        async with self.cond:
            self.cond.notify_all()

    async def subscribe(self, after_seq: int):
        """Yield events with seq > after_seq as they appear; yield None as a heartbeat."""
        index = max(after_seq, 0)
        while True:
            try:
                async with self.cond:
                    await asyncio.wait_for(
                        self.cond.wait_for(lambda: len(self.events) > index or self.done),
                        timeout=HEARTBEAT_SECONDS,
                    )
            except asyncio.TimeoutError:
                yield None
                continue
            while index < len(self.events):
                event = self.events[index]
                index += 1
                yield event
            if self.done and index >= len(self.events):
                return


class GenerationManager:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        ai: AIService,
    ):
        self.session_factory = session_factory
        self.ai = ai
        self._runs: dict[uuid.UUID, GenerationRun] = {}

    # ---- public API --------------------------------------------------------------------

    def get(self, generation_id: uuid.UUID) -> GenerationRun | None:
        return self._runs.get(generation_id)

    def is_active(self, generation_id: uuid.UUID) -> bool:
        run = self._runs.get(generation_id)
        return run is not None and not run.done

    def start(self, spec: GenerationSpec) -> GenerationRun:
        run = GenerationRun(spec=spec)
        self._runs[spec.generation_id] = run
        run.task = asyncio.create_task(self._run(run), name=f"generation-{spec.generation_id}")
        return run

    async def cancel(self, generation_id: uuid.UUID, reason: str = "user") -> bool:
        """Cancel a running generation and wait until it has been finalised."""
        run = self._runs.get(generation_id)
        if run is None or run.done:
            return False
        run.cancel_reason = reason
        assert run.task is not None
        run.task.cancel()
        await asyncio.wait({run.task}, timeout=15)
        if not run.done:
            # The task was cancelled before it ever started, so it could not clean up itself.
            await self._finalize(run, "cancelled" if reason == "user" else "interrupted", None)
        return True

    async def shutdown(self) -> None:
        for generation_id in list(self._runs):
            await self.cancel(generation_id, reason="shutdown")

    # ---- task body ---------------------------------------------------------------------

    async def _run(self, run: GenerationRun) -> None:
        outcome: tuple[str, str | None] = ("failed", "The generation ended unexpectedly.")
        ticker = asyncio.create_task(self._ticker(run))
        try:
            await self._produce(run)
            outcome = ("completed", None)
        except asyncio.CancelledError:
            outcome = ("interrupted" if run.cancel_reason == "shutdown" else "cancelled", None)
        except (AIConfigError, AIProviderError) as exc:
            outcome = ("failed", str(exc))
        except Exception:  # noqa: BLE001
            log.exception("Unexpected error in generation %s", run.spec.generation_id)
            outcome = ("failed", "An unexpected error occurred while generating the response.")
        finally:
            ticker.cancel()
            await asyncio.gather(ticker, return_exceptions=True)
            await self._finalize(run, *outcome)

    async def _produce(self, run: GenerationRun) -> None:
        spec = run.spec
        await run.publish(
            "generation_started",
            {
                "generation_id": str(spec.generation_id),
                "assistant_message_id": str(spec.assistant_message_id),
                "model": spec.model,
            },
        )
        async for item in self.ai.stream_reply(spec.conversation_id, spec.assistant_sequence):
            kind = item.get("type")
            if kind == "status":
                await self._flush_text(run)
                await run.publish("status", {"stage": item["stage"], "message": item["message"]})
            elif kind == "delta":
                run.pending_text.append(item["text"])
                run.content_parts.append(item["text"])
            elif kind == "usage":
                run.usage = {
                    "input_tokens": item.get("input_tokens"),
                    "output_tokens": item.get("output_tokens"),
                }
        await self._flush_text(run)
        if not "".join(run.content_parts).strip():
            raise AIProviderError("The AI provider returned an empty response.")

    async def _flush_text(self, run: GenerationRun) -> None:
        if run.pending_text:
            text = "".join(run.pending_text)
            run.pending_text.clear()
            await run.publish("message_delta", {"text": text})

    async def _ticker(self, run: GenerationRun) -> None:
        """Coalesce deltas into events and persist pending events in batches."""
        ticks = 0
        while True:
            await asyncio.sleep(DELTA_INTERVAL)
            await self._flush_text(run)
            ticks += 1
            if ticks % PERSIST_EVERY_TICKS == 0:
                try:
                    await self._persist_pending(run)
                except Exception:  # noqa: BLE001 - retried on the next tick / at finalisation
                    log.warning("Could not persist events for %s", run.spec.generation_id, exc_info=True)

    # ---- persistence -------------------------------------------------------------------

    @staticmethod
    def _event_rows(generation_id: uuid.UUID, events: list[RunEvent]) -> list[dict[str, Any]]:
        return [
            {
                "generation_id": generation_id,
                "event_sequence": e.seq,
                "event_type": e.type,
                "payload": e.payload,
            }
            for e in events
        ]

    @staticmethod
    async def _insert_events(db: AsyncSession, rows: list[dict[str, Any]]) -> None:
        # Idempotent: if a persist was interrupted after its commit (e.g. the ticker was
        # cancelled before the counter was updated), re-inserting the same events is a no-op.
        if rows:
            await db.execute(
                pg_insert(GenerationEvent).on_conflict_do_nothing(
                    constraint="uq_generation_events_sequence"
                ),
                rows,
            )

    async def _persist_pending(self, run: GenerationRun) -> None:
        async with run.persist_lock:
            batch = run.events[run.persisted :]
            if not batch:
                return
            async with self.session_factory() as db:
                await self._insert_events(db, self._event_rows(run.spec.generation_id, batch))
                await db.commit()
            run.persisted += len(batch)

    async def _finalize(self, run: GenerationRun, status: str, error: str | None) -> None:
        """Write the final state, then publish the terminal event to live subscribers."""
        if run.done:
            return
        spec = run.spec
        try:
            await self._flush_text(run)
            content = "".join(run.content_parts)
            has_partial = bool(content.strip())

            if status == "completed":
                event_type = "message_completed"
                payload: dict[str, Any] = {
                    "message_id": str(spec.assistant_message_id),
                    "input_tokens": (run.usage or {}).get("input_tokens"),
                    "output_tokens": (run.usage or {}).get("output_tokens"),
                }
            elif status == "cancelled":
                event_type, payload = "generation_cancelled", {"partial": has_partial}
            elif status == "interrupted":
                error = "The generation was interrupted because the server is shutting down."
                event_type, payload = "generation_failed", {"error": error, "interrupted": True}
            else:
                event_type, payload = "generation_failed", {"error": error, "partial": has_partial}

            terminal = run._append(event_type, payload)
            try:
                await self._write_final(run, status, error, content, terminal, with_events=True)
            except Exception:  # noqa: BLE001
                log.exception("Final write failed for %s; retrying without events", spec.generation_id)
                await self._write_final(run, status, error, content, terminal, with_events=False)
        except Exception:  # noqa: BLE001
            log.exception("Could not finalise generation %s", spec.generation_id)
        finally:
            async with run.cond:
                run.cond.notify_all()
            await run.mark_done()
            self._runs.pop(spec.generation_id, None)

    async def _write_final(
        self,
        run: GenerationRun,
        status: str,
        error: str | None,
        content: str,
        terminal: RunEvent,
        with_events: bool,
    ) -> None:
        spec = run.spec
        now = datetime.now(timezone.utc)
        async with run.persist_lock:
            async with self.session_factory() as db:
                if with_events:
                    batch = run.events[run.persisted :]
                    await self._insert_events(db, self._event_rows(spec.generation_id, batch))
                usage = run.usage or {}
                await db.execute(
                    update(Message)
                    .where(Message.id == spec.assistant_message_id)
                    .values(
                        content=content,
                        status=status,
                        input_tokens=usage.get("input_tokens"),
                        output_tokens=usage.get("output_tokens"),
                    )
                )
                await db.execute(
                    update(Generation)
                    .where(Generation.id == spec.generation_id)
                    .values(status=status, error_message=error, completed_at=now)
                )
                if status == "completed":
                    await db.execute(
                        update(Conversation)
                        .where(Conversation.id == spec.conversation_id)
                        .values(last_message_at=now, updated_at=now)
                    )
                await db.commit()
            if with_events:
                run.persisted = len(run.events)


async def mark_interrupted_generations(session_factory: async_sessionmaker[AsyncSession]) -> int:
    """On startup, any generation still 'running' was cut off by a restart. Record that."""
    message = "The generation was interrupted by a server restart."
    async with session_factory() as db:
        stale = (await db.scalars(select(Generation).where(Generation.status == "running"))).all()
        for gen in stale:
            last_seq = await db.scalar(
                select(func.coalesce(func.max(GenerationEvent.event_sequence), 0)).where(
                    GenerationEvent.generation_id == gen.id
                )
            )
            db.add(
                GenerationEvent(
                    generation_id=gen.id,
                    event_sequence=last_seq + 1,
                    event_type="generation_failed",
                    payload={"error": message, "interrupted": True},
                )
            )
            gen.status = "interrupted"
            gen.error_message = message
            gen.completed_at = datetime.now(timezone.utc)
            await db.execute(
                update(Message)
                .where(Message.id == gen.assistant_message_id, Message.status == "streaming")
                .values(status="interrupted")
            )
        await db.commit()
    if stale:
        log.warning("Marked %d generation(s) as interrupted after restart", len(stale))
    return len(stale)
