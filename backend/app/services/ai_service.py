import logging
from collections.abc import AsyncIterator
from typing import Any, TypedDict

import httpx
import openai
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from openai import AsyncOpenAI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.models import Message

log = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are AI Problem Solver, a helpful assistant that helps people understand and solve "
    "problems. Give clear, accurate, practical answers. Break complex problems into steps when "
    "that helps, ask a brief clarifying question if the request is ambiguous, and use Markdown "
    "(lists, tables, fenced code blocks with a language tag) when it improves readability."
)


class AIConfigError(Exception):
    """The AI provider is not configured (for example, the API key is missing)."""


class AIProviderError(Exception):
    """A provider failure. The message is safe to show to the user."""


class ChatState(TypedDict, total=False):
    transcript: list[dict[str, str]]  # input: recent messages from the application database
    context: list[dict[str, str]]  # bounded messages sent to the model (incl. system prompt)
    response: str  # the model's final answer for this run


def build_client(settings: Settings) -> AsyncOpenAI | None:
    """Create the AsyncOpenAI client for the AI Router, or None if no API key is set."""
    if not settings.ai_configured:
        return None
    return AsyncOpenAI(
        api_key=settings.AI_ROUTER_API_KEY,
        base_url=settings.AI_ROUTER_BASE_URL,
        timeout=httpx.Timeout(settings.AI_REQUEST_TIMEOUT, connect=15.0),
        max_retries=1,
    )


def estimate_tokens(text: str) -> int:
    return len(text) // 4 + 4


def trim_to_budget(
    messages: list[dict[str, str]], budget: int, max_messages: int
) -> list[dict[str, str]]:
    """Keep the most recent messages that fit the budget. The newest is always kept."""
    kept: list[dict[str, str]] = []
    used = 0
    for msg in reversed(messages):
        cost = estimate_tokens(msg["content"])
        if kept and (used + cost > budget or len(kept) >= max_messages):
            break
        kept.append(msg)
        used += cost
    kept.reverse()
    return kept


def describe_provider_error(exc: BaseException, model: str) -> str:
    """Translate a provider/network exception into a safe, user-facing message."""
    if isinstance(exc, openai.AuthenticationError):
        return "The AI provider rejected the API key. Check AI_ROUTER_API_KEY."
    if isinstance(exc, openai.PermissionDeniedError):
        return "The AI provider denied access. Check that your key is allowed to use this model."
    if isinstance(exc, openai.NotFoundError):
        return f"The AI provider could not find the model '{model}'. Check AI_ROUTER_MODEL."
    if isinstance(exc, openai.RateLimitError):
        return "The AI provider's rate limit or quota was reached. Please try again later."
    if isinstance(exc, (openai.APITimeoutError, httpx.TimeoutException)):
        return "The AI provider timed out. Please try again."
    if isinstance(exc, (openai.APIConnectionError, httpx.TransportError)):
        return "The connection to the AI provider failed or was interrupted. Please try again."
    if isinstance(exc, openai.BadRequestError):
        return "The AI provider rejected the request. Check AI_ROUTER_MODEL and the provider settings."
    if isinstance(exc, openai.APIStatusError):
        return f"The AI provider returned an error (HTTP {exc.status_code}). Please try again."
    return "The AI provider request failed unexpectedly."


class AIService:
    def __init__(
        self,
        settings: Settings,
        session_factory: async_sessionmaker[AsyncSession],
        checkpointer: AsyncPostgresSaver,
        client: AsyncOpenAI | None = None,
    ):
        self.settings = settings
        self.session_factory = session_factory
        self.client = client  # replaceable (tests inject a fake provider client)
        self.graph = self._build_graph(checkpointer)

    # ---- graph -------------------------------------------------------------------------

    def _build_graph(self, checkpointer: AsyncPostgresSaver):
        graph = StateGraph(ChatState)
        graph.add_node("prepare_context", self._prepare_context)
        graph.add_node("generate", self._generate)
        graph.add_edge(START, "prepare_context")
        graph.add_edge("prepare_context", "generate")
        graph.add_edge("generate", END)
        return graph.compile(checkpointer=checkpointer)

    async def _prepare_context(self, state: ChatState) -> dict[str, Any]:
        writer = get_stream_writer()
        writer({"type": "status", "stage": "preparing", "message": "Preparing context…"})
        trimmed = trim_to_budget(
            state.get("transcript", []),
            self.settings.CONTEXT_TOKEN_BUDGET,
            self.settings.CONTEXT_MAX_MESSAGES,
        )
        context = [{"role": "system", "content": SYSTEM_PROMPT}, *trimmed]
        # Clear the transcript so full history is not kept in the checkpoint.
        return {"context": context, "transcript": []}

    async def _generate(self, state: ChatState) -> dict[str, Any]:
        writer = get_stream_writer()
        client = self.client
        if client is None:
            raise AIConfigError(
                "The AI provider is not configured. Set AI_ROUTER_API_KEY in your .env file "
                "and restart the backend."
            )
        model = self.settings.AI_ROUTER_MODEL
        writer({"type": "status", "stage": "generating", "message": "Generating response…"})

        parts: list[str] = []
        usage: dict[str, int | None] | None = None
        kwargs: dict[str, Any] = {}
        if self.settings.AI_STREAM_USAGE:
            kwargs["stream_options"] = {"include_usage": True}
        try:
            stream = await client.chat.completions.create(
                model=model, messages=state["context"], stream=True, **kwargs
            )
            # `async with` closes the provider's HTTP stream, including when we are cancelled.
            async with stream:
                async for chunk in stream:
                    if getattr(chunk, "usage", None):
                        usage = {
                            "input_tokens": chunk.usage.prompt_tokens,
                            "output_tokens": chunk.usage.completion_tokens,
                        }
                    if not chunk.choices:
                        continue
                    text = chunk.choices[0].delta.content
                    if text:
                        parts.append(text)
                        writer({"type": "delta", "text": text})
        except AIConfigError:
            raise
        except Exception as exc:  # noqa: BLE001 - mapped to a safe message below
            # asyncio.CancelledError is a BaseException and is deliberately not caught here.
            log.warning("AI provider error (%s): %s", type(exc).__name__, exc)
            message = describe_provider_error(exc, model)
            if parts:
                message = f"The response was cut off. {message}"
            raise AIProviderError(message) from exc

        if usage:
            writer({"type": "usage", **usage})
        return {"response": "".join(parts)}

    # ---- public API --------------------------------------------------------------------

    async def _load_transcript(self, conversation_id, before_sequence: int) -> list[dict[str, str]]:
        async with self.session_factory() as db:
            rows = (
                await db.execute(
                    select(Message.role, Message.content)
                    .where(
                        Message.conversation_id == conversation_id,
                        Message.sequence_number < before_sequence,
                        Message.status == "completed",
                    )
                    .order_by(Message.sequence_number.desc())
                    .limit(self.settings.CONTEXT_MAX_MESSAGES)
                )
            ).all()
        return [{"role": role, "content": content} for role, content in reversed(rows)]

    async def stream_reply(self, conversation_id, before_sequence: int) -> AsyncIterator[dict]:
        """Run the graph for a conversation and yield user-facing events.

        Yields dicts: {"type": "status", ...}, {"type": "delta", "text": ...},
        {"type": "usage", ...}. Raises AIConfigError / AIProviderError on failure.
        """
        if self.client is None:
            raise AIConfigError(
                "The AI provider is not configured. Set AI_ROUTER_API_KEY in your .env file "
                "and restart the backend."
            )
        transcript = await self._load_transcript(conversation_id, before_sequence)
        config = {"configurable": {"thread_id": str(conversation_id)}}
        async for item in self.graph.astream(
            {"transcript": transcript}, config=config, stream_mode="custom"
        ):
            yield item
