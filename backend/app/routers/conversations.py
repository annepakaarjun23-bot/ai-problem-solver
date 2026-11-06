"""Conversation, message, send and regenerate endpoints."""

import uuid

from fastapi import APIRouter, Depends, Query, Response, status
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.deps import get_checkpointer, get_current_user, get_db, get_manager, settings_dep
from app.models import Message, User
from app.schemas import (
    ConversationCreate,
    ConversationDetail,
    ConversationOut,
    ConversationPage,
    ConversationUpdate,
    GenerationStarted,
    MessageOut,
    MessagePage,
    SendMessageRequest,
)
from app.services import conversation_service as svc
from app.services.generation_manager import GenerationManager

router = APIRouter(prefix="/api/v1/conversations", tags=["conversations"])


def _message_out(message: Message, error: str | None = None) -> MessageOut:
    out = MessageOut.model_validate(message)
    out.error_message = error
    return out


@router.post("", response_model=ConversationOut, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    body: ConversationCreate | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await svc.create_conversation(db, user, body.title if body else None)


@router.get("", response_model=ConversationPage)
async def list_conversations(
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    items, total = await svc.list_conversations(db, user, limit, offset)
    return ConversationPage(
        items=items, total=total, limit=limit, offset=offset, has_more=offset + len(items) < total
    )


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(
    conversation_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    conversation = await svc.get_owned_conversation(db, user.id, conversation_id)
    detail = ConversationDetail.model_validate(conversation)
    detail.active_generation_id = await svc.get_active_generation_id(db, conversation.id)
    return detail


@router.patch("/{conversation_id}", response_model=ConversationOut)
async def update_conversation(
    conversation_id: uuid.UUID,
    body: ConversationUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await svc.rename_conversation(db, user, conversation_id, body.title)


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    manager: GenerationManager = Depends(get_manager),
    checkpointer: AsyncPostgresSaver = Depends(get_checkpointer),
):
    await svc.delete_conversation(db, manager, checkpointer, user, conversation_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{conversation_id}/messages", response_model=MessagePage)
async def list_messages(
    conversation_id: uuid.UUID,
    limit: int = Query(100, ge=1, le=200),
    before_sequence: int | None = Query(None, ge=1),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    messages, has_more, errors = await svc.list_messages(
        db, user, conversation_id, limit, before_sequence
    )
    return MessagePage(
        items=[_message_out(m, errors.get(m.id)) for m in messages], has_more=has_more
    )


@router.post(
    "/start",
    response_model=GenerationStarted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_conversation_with_message(
    body: SendMessageRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    manager: GenerationManager = Depends(get_manager),
    settings: Settings = Depends(settings_dep),
):
    generation, conversation, user_message, assistant = await svc.start_conversation_with_message(
        db, manager, user, body.content, settings
    )
    return GenerationStarted(
        generation_id=generation.id,
        events_url=f"/api/v1/generations/{generation.id}/events",
        conversation=ConversationOut.model_validate(conversation),
        user_message=_message_out(user_message),
        assistant_message=_message_out(assistant),
    )


@router.post(
    "/{conversation_id}/messages",
    response_model=GenerationStarted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def send_message(
    conversation_id: uuid.UUID,
    body: SendMessageRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    manager: GenerationManager = Depends(get_manager),
    settings: Settings = Depends(settings_dep),
):
    generation, conversation, user_message, assistant = await svc.send_message(
        db, manager, user, conversation_id, body.content, settings
    )
    return GenerationStarted(
        generation_id=generation.id,
        events_url=f"/api/v1/generations/{generation.id}/events",
        conversation=ConversationOut.model_validate(conversation),
        user_message=_message_out(user_message),
        assistant_message=_message_out(assistant),
    )


@router.post(
    "/{conversation_id}/regenerate",
    response_model=GenerationStarted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def regenerate(
    conversation_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    manager: GenerationManager = Depends(get_manager),
    settings: Settings = Depends(settings_dep),
):
    generation, conversation, assistant = await svc.regenerate(
        db, manager, user, conversation_id, settings
    )
    return GenerationStarted(
        generation_id=generation.id,
        events_url=f"/api/v1/generations/{generation.id}/events",
        conversation=ConversationOut.model_validate(conversation),
        user_message=None,
        assistant_message=_message_out(assistant),
    )
