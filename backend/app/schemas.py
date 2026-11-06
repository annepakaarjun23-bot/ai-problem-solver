"""Pydantic request/response models."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---- Auth -------------------------------------------------------------------------------


class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class UserOut(ORMModel):
    id: uuid.UUID
    email: str
    created_at: datetime


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut


# ---- Conversations ----------------------------------------------------------------------


def _clean_title(value: str) -> str:
    value = " ".join(value.split())
    if not value:
        raise ValueError("Title must not be empty")
    return value


class ConversationCreate(BaseModel):
    title: str | None = Field(default=None, max_length=200)

    @field_validator("title")
    @classmethod
    def clean(cls, v: str | None) -> str | None:
        return _clean_title(v) if v is not None else None


class ConversationUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=200)

    @field_validator("title")
    @classmethod
    def clean(cls, v: str) -> str:
        return _clean_title(v)


class ConversationOut(ORMModel):
    id: uuid.UUID
    title: str
    created_at: datetime
    updated_at: datetime
    last_message_at: datetime


class ConversationDetail(ConversationOut):
    active_generation_id: uuid.UUID | None = None


class ConversationPage(BaseModel):
    items: list[ConversationOut]
    total: int
    limit: int
    offset: int
    has_more: bool


# ---- Messages ---------------------------------------------------------------------------


class MessageOut(ORMModel):
    id: uuid.UUID
    conversation_id: uuid.UUID
    sequence_number: int
    role: str
    content: str
    status: str
    model_name: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    created_at: datetime
    # Populated for failed/interrupted assistant messages from the generation record.
    error_message: str | None = None


class MessagePage(BaseModel):
    items: list[MessageOut]
    has_more: bool  # True when older messages exist before the first returned item


class SendMessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=32000)

    @field_validator("content")
    @classmethod
    def not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Message must not be empty")
        return v


# ---- Generations ------------------------------------------------------------------------


class GenerationStarted(BaseModel):
    generation_id: uuid.UUID
    events_url: str
    conversation: ConversationOut
    user_message: MessageOut | None = None  # None when regenerating
    assistant_message: MessageOut


class GenerationOut(ORMModel):
    id: uuid.UUID
    conversation_id: uuid.UUID
    assistant_message_id: uuid.UUID
    status: str
    error_message: str | None = None
    started_at: datetime
    completed_at: datetime | None = None
