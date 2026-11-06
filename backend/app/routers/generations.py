"""Generation endpoints: SSE event stream and cancellation."""

import asyncio
import json
import uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Header, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.deps import get_current_user, get_db, get_manager
from app.models import Generation, GenerationEvent, User
from app.schemas import GenerationOut
from app.services import conversation_service as svc
from app.services.generation_manager import TERMINAL_EVENTS, GenerationManager

router = APIRouter(prefix="/api/v1/generations", tags=["generations"])


def format_sse(seq: int, event_type: str, payload: dict) -> str:
    return f"id: {seq}\nevent: {event_type}\ndata: {json.dumps(payload, separators=(',', ':'))}\n\n"


async def event_stream(
    generation_id: uuid.UUID,
    last_seq: int,
    manager: GenerationManager,
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[str]:
    """Replay persisted events after `last_seq`, then follow the live run until it ends.

    A live run keeps every event in memory, so we read from there while it is active and
    fall back to the database once it has finished (or after a restart).
    """
    orphan_checks = 0
    while True:
        run = manager.get(generation_id)
        if run is not None:
            async for event in run.subscribe(last_seq):
                if event is None:
                    yield ": keepalive\n\n"
                    continue
                last_seq = event.seq
                yield format_sse(event.seq, event.type, event.payload)
                if event.type in TERMINAL_EVENTS:
                    return
            continue  # subscription ended without a terminal event; re-check the database

        async with session_factory() as db:
            rows = (
                await db.execute(
                    select(
                        GenerationEvent.event_sequence,
                        GenerationEvent.event_type,
                        GenerationEvent.payload,
                    )
                    .where(
                        GenerationEvent.generation_id == generation_id,
                        GenerationEvent.event_sequence > last_seq,
                    )
                    .order_by(GenerationEvent.event_sequence)
                )
            ).all()
            status_value = await db.scalar(select(Generation.status).where(Generation.id == generation_id))
        for seq, event_type, payload in rows:
            last_seq = seq
            yield format_sse(seq, event_type, payload)
            if event_type in TERMINAL_EVENTS:
                return
        if status_value != "running":
            return  # finished (or interrupted) and everything has been replayed
        # Row says running but no live run: the run just finished (re-check) or is orphaned.
        orphan_checks += 1
        if orphan_checks > 20:
            return
        await asyncio.sleep(0.25)


def _parse_last_event_id(value: str | None) -> int:
    try:
        return max(int(value), 0) if value else 0
    except ValueError:
        return 0


@router.get("/{generation_id}/events")
async def stream_events(
    generation_id: uuid.UUID,
    request: Request,
    last_event_id: str | None = Header(default=None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    manager: GenerationManager = Depends(get_manager),
):
    await svc.get_owned_generation(db, user.id, generation_id)  # 404 for other users' ids
    await db.close()  # do not hold a connection for the lifetime of the stream
    return StreamingResponse(
        event_stream(
            generation_id,
            _parse_last_event_id(last_event_id),
            manager,
            request.app.state.session_factory,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/{generation_id}/cancel", response_model=GenerationOut, status_code=status.HTTP_200_OK)
async def cancel_generation(
    generation_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    manager: GenerationManager = Depends(get_manager),
):
    user_id = user.id  # read now: rollback() below expires loaded ORM objects
    await svc.get_owned_generation(db, user_id, generation_id)
    await manager.cancel(generation_id)  # no-op if it already finished
    await db.rollback()  # end the read transaction so the next read sees the final state
    return await svc.get_owned_generation(db, user_id, generation_id)
