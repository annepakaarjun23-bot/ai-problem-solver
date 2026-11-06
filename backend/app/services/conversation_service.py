"""Conversation, message and generation-start operations (all scoped to the current user)."""

import logging
import re
import uuid
from datetime import datetime, timezone

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.errors import ServiceError, not_found
from app.models import Conversation, Generation, Message, User
from app.services.generation_manager import GenerationManager, GenerationSpec

log = logging.getLogger(__name__)

DEFAULT_TITLE = "New chat"
TITLE_MAX = 60


def make_title(content: str) -> str:
    """Simple title from the first user message (no LLM call)."""
    for line in content.splitlines():
        line = re.sub(r"^[\s#>*\-`]+", "", line)  # strip markdown/list/quote prefixes
        line = " ".join(line.split())
        if line:
            return line if len(line) <= TITLE_MAX else line[: TITLE_MAX - 1].rstrip() + "…"
    return DEFAULT_TITLE


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---- conversations ----------------------------------------------------------------------


async def get_owned_conversation(
    db: AsyncSession, user_id: uuid.UUID, conversation_id: uuid.UUID, lock: bool = False
) -> Conversation:
    """Fetch a conversation owned by the user. Other users' conversations look like 404."""
    stmt = select(Conversation).where(
        Conversation.id == conversation_id, Conversation.user_id == user_id
    )
    if lock:
        stmt = stmt.with_for_update()
    conversation = await db.scalar(stmt)
    if conversation is None:
        raise not_found("Conversation")
    return conversation


async def create_conversation(db: AsyncSession, user: User, title: str | None) -> Conversation:
    conversation = Conversation(user_id=user.id, title=title or DEFAULT_TITLE)
    db.add(conversation)
    await db.commit()
    return conversation


async def list_conversations(
    db: AsyncSession, user: User, limit: int, offset: int
) -> tuple[list[Conversation], int]:
    total = await db.scalar(
        select(func.count()).select_from(Conversation).where(Conversation.user_id == user.id)
    )
    rows = (
        await db.scalars(
            select(Conversation)
            .where(Conversation.user_id == user.id)
            .order_by(Conversation.last_message_at.desc(), Conversation.id)
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return list(rows), total or 0


async def get_active_generation_id(db: AsyncSession, conversation_id: uuid.UUID) -> uuid.UUID | None:
    return await db.scalar(
        select(Generation.id).where(
            Generation.conversation_id == conversation_id, Generation.status == "running"
        )
    )


async def rename_conversation(
    db: AsyncSession, user: User, conversation_id: uuid.UUID, title: str
) -> Conversation:
    conversation = await get_owned_conversation(db, user.id, conversation_id)
    conversation.title = title
    conversation.updated_at = _now()
    await db.commit()
    return conversation


async def delete_conversation(
    db: AsyncSession,
    manager: GenerationManager,
    checkpointer: AsyncPostgresSaver,
    user: User,
    conversation_id: uuid.UUID,
) -> None:
    conversation = await get_owned_conversation(db, user.id, conversation_id)
    # Stop any running generation first so it does not write to rows being deleted.
    running = await get_active_generation_id(db, conversation.id)
    if running is not None:
        await manager.cancel(running)
    await db.execute(delete(Conversation).where(Conversation.id == conversation.id))
    await db.commit()  # messages, generations and events are removed by ON DELETE CASCADE
    try:
        await checkpointer.adelete_thread(str(conversation_id))
    except Exception:  # noqa: BLE001 - the checkpoint is auxiliary state; never fail the request
        log.warning("Could not delete checkpoint thread %s", conversation_id, exc_info=True)


# ---- messages ---------------------------------------------------------------------------


async def list_messages(
    db: AsyncSession,
    user: User,
    conversation_id: uuid.UUID,
    limit: int,
    before_sequence: int | None,
) -> tuple[list[Message], bool, dict[uuid.UUID, str]]:
    """Return the latest `limit` messages (ascending), whether older ones exist, and errors."""
    await get_owned_conversation(db, user.id, conversation_id)
    stmt = select(Message).where(Message.conversation_id == conversation_id)
    if before_sequence is not None:
        stmt = stmt.where(Message.sequence_number < before_sequence)
    rows = (
        await db.scalars(stmt.order_by(Message.sequence_number.desc()).limit(limit + 1))
    ).all()
    has_more = len(rows) > limit
    messages = list(reversed(rows[:limit]))

    failed_ids = [m.id for m in messages if m.status in ("failed", "interrupted")]
    errors: dict[uuid.UUID, str] = {}
    if failed_ids:
        gens = (
            await db.execute(
                select(Generation.assistant_message_id, Generation.error_message)
                .where(
                    Generation.assistant_message_id.in_(failed_ids),
                    Generation.error_message.is_not(None),
                )
                .order_by(Generation.started_at)
            )
        ).all()
        errors = {message_id: error for message_id, error in gens}  # latest wins
    return messages, has_more, errors


# ---- generations ------------------------------------------------------------------------


async def get_owned_generation(
    db: AsyncSession, user_id: uuid.UUID, generation_id: uuid.UUID
) -> Generation:
    generation = await db.scalar(
        select(Generation).where(Generation.id == generation_id, Generation.user_id == user_id)
    )
    if generation is None:
        raise not_found("Generation")
    return generation


async def _ensure_none_running(db: AsyncSession, conversation_id: uuid.UUID) -> None:
    if await get_active_generation_id(db, conversation_id) is not None:
        raise ServiceError(409, "A response is already being generated for this conversation")


async def _begin_generation(
    db: AsyncSession,
    manager: GenerationManager,
    user: User,
    conversation: Conversation,
    assistant: Message,
    settings: Settings,
) -> Generation:
    generation = Generation(
        user_id=user.id,
        conversation_id=conversation.id,
        assistant_message_id=assistant.id,
        status="running",
    )
    db.add(generation)
    try:
        await db.flush()  # the partial unique index rejects a second running generation
    except IntegrityError as exc:
        await db.rollback()
        constraint = getattr(exc.orig, "constraint_name", None)
        if constraint is None:
            constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
        if constraint == "uq_generations_one_running_per_conversation" or (
            '"uq_generations_one_running_per_conversation"' in str(exc.orig)
        ):
            raise ServiceError(
                409, "A response is already being generated for this conversation"
            ) from None
        raise
    await db.commit()
    manager.start(
        GenerationSpec(
            generation_id=generation.id,
            user_id=user.id,
            conversation_id=conversation.id,
            assistant_message_id=assistant.id,
            assistant_sequence=assistant.sequence_number,
            model=settings.AI_ROUTER_MODEL,
        )
    )
    return generation


async def send_message(
    db: AsyncSession,
    manager: GenerationManager,
    user: User,
    conversation_id: uuid.UUID,
    content: str,
    settings: Settings,
) -> tuple[Generation, Conversation, Message, Message]:
    # Lock the conversation row so concurrent sends are serialised (sequence numbers, 409s).
    conversation = await get_owned_conversation(db, user.id, conversation_id, lock=True)
    await _ensure_none_running(db, conversation.id)

    last_seq = await db.scalar(
        select(func.coalesce(func.max(Message.sequence_number), 0)).where(
            Message.conversation_id == conversation.id
        )
    )
    user_message = Message(
        id=uuid.uuid4(),
        conversation_id=conversation.id,
        sequence_number=last_seq + 1,
        role="user",
        content=content,
        status="completed",
    )
    assistant = Message(
        id=uuid.uuid4(),
        conversation_id=conversation.id,
        sequence_number=last_seq + 2,
        role="assistant",
        content="",
        status="streaming",
        model_name=settings.AI_ROUTER_MODEL,
    )
    db.add_all([user_message, assistant])
    if last_seq == 0 and conversation.title == DEFAULT_TITLE:
        conversation.title = make_title(content)
    now = _now()
    conversation.last_message_at = now
    conversation.updated_at = now
    await db.flush()
    generation = await _begin_generation(db, manager, user, conversation, assistant, settings)
    return generation, conversation, user_message, assistant


async def start_conversation_with_message(
    db: AsyncSession,
    manager: GenerationManager,
    user: User,
    content: str,
    settings: Settings,
) -> tuple[Generation, Conversation, Message, Message]:
    """Create a conversation and its first message in one transaction."""
    now = _now()
    conversation = Conversation(
        id=uuid.uuid4(),
        user_id=user.id,
        title=make_title(content),
        created_at=now,
        updated_at=now,
        last_message_at=now,
    )
    db.add(conversation)
    # These models use scalar foreign keys without ORM relationships, so flush
    # the parent before its message rows to preserve FK insert order.
    await db.flush()

    user_message = Message(
        id=uuid.uuid4(),
        conversation_id=conversation.id,
        sequence_number=1,
        role="user",
        content=content,
        status="completed",
        created_at=now,
    )
    assistant = Message(
        id=uuid.uuid4(),
        conversation_id=conversation.id,
        sequence_number=2,
        role="assistant",
        content="",
        status="streaming",
        model_name=settings.AI_ROUTER_MODEL,
        created_at=now,
    )
    db.add_all([user_message, assistant])
    await db.flush()
    generation = await _begin_generation(db, manager, user, conversation, assistant, settings)
    return generation, conversation, user_message, assistant


async def regenerate(
    db: AsyncSession,
    manager: GenerationManager,
    user: User,
    conversation_id: uuid.UUID,
    settings: Settings,
) -> tuple[Generation, Conversation, Message]:
    """Re-run the last assistant message in place (same message row, new generation)."""
    conversation = await get_owned_conversation(db, user.id, conversation_id, lock=True)
    await _ensure_none_running(db, conversation.id)

    last = await db.scalar(
        select(Message)
        .where(Message.conversation_id == conversation.id)
        .order_by(Message.sequence_number.desc())
        .limit(1)
    )
    if last is None or last.role != "assistant":
        raise ServiceError(409, "There is no assistant response to regenerate")

    last.content = ""
    last.status = "streaming"
    last.model_name = settings.AI_ROUTER_MODEL
    last.input_tokens = None
    last.output_tokens = None
    conversation.updated_at = _now()
    await db.flush()
    generation = await _begin_generation(db, manager, user, conversation, last, settings)
    return generation, conversation, last
