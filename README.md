# AI Problem Solver

A conversational assistant for working through problems. React + FastAPI + PostgreSQL, with a LangGraph workflow that calls an OpenAI-compatible provider (AI Router) and streams answers to the browser over Server-Sent Events.

Visitors first see a landing page. After signing up or logging in they go straight to the chat application, and signed-in users opening the site land in the chat directly.

## Quick start

```bash
cp .env.example .env
# edit .env: set AI_ROUTER_API_KEY and a long random JWT_SECRET_KEY
docker compose up --build
```

Open <http://localhost:8080>.

First-time configuration:

| Variable | Purpose |
| --- | --- |
| `AI_ROUTER_API_KEY` | Your AI Router key. Stays on the backend and is never sent to the browser. Without it the app still starts; auth and conversation management work, and sending a message shows a clear "provider is not configured" error. |
| `AI_ROUTER_BASE_URL` | Default `https://api.airouter.in/v1` |
| `AI_ROUTER_MODEL` | Default `openai/gpt-6-luna`. Used exactly as configured; no silent substitution. |
| `JWT_SECRET_KEY` | Random string, 32+ characters. With `ENVIRONMENT=production` the backend refuses to start if it is weak. |
| `ALLOWED_ORIGINS` | Browser origin(s) allowed for cookie-based refresh/logout. Must match the URL you open (default `http://localhost:8080`). |
| `COOKIE_SECURE` | Set `true` when serving over HTTPS (forced on when `ENVIRONMENT=production`). |

Generate a secret: `python -c "import secrets; print(secrets.token_urlsafe(48))"`

## Architecture

A modular monolith with one backend instance:

```text
React frontend -> nginx (static files, /api proxy) -> FastAPI routers
   -> application services -> PostgreSQL
   -> AI service -> LangGraph (prepare_context -> generate) -> AsyncOpenAI -> AI Router
```

```text
backend/app/
  config.py        settings from environment
  models.py        SQLAlchemy models (users, auth_sessions, conversations, messages, generations, generation_events)
  security.py      Argon2id hashing, JWT access tokens, refresh-token hashing
  deps.py          FastAPI dependencies (DB session, current user, origin check)
  routers/         HTTP layer: auth, conversations, generations (SSE, cancel)
  services/
    auth_service.py          signup/login, refresh rotation and reuse detection
    conversation_service.py  conversations, messages, send/regenerate
    generation_manager.py    in-process asyncio generation tasks, event batching
    ai_service.py            LangGraph graph + AsyncOpenAI streaming
backend/alembic/   migrations for the application tables
frontend/src/
  components/      Landing, AuthPage, AppShell, Sidebar, ChatView, Message, Markdown, Composer
  context/         AuthContext, ChatContext (React Context, no Redux)
  hooks/           useCopy, useAutoScroll, useReveal
  api/             fetch wrapper (token refresh) and SSE-over-fetch reader
```

### Chat flow

1. `POST /api/v1/conversations/{id}/messages` stores the user message, an assistant placeholder and a `generation` row, starts an asyncio task, and returns `generation_id` plus the events URL (HTTP 202).
2. `GET /api/v1/generations/{id}/events` streams SSE: `generation_started`, `status`, `message_delta`, then one of `message_completed`, `generation_failed`, `generation_cancelled`. Each event has an incrementing `id`; reconnect with `Last-Event-ID` to replay what was missed.
3. The task runs independently of the HTTP connection, so closing the tab does not discard the answer. `POST /api/v1/generations/{id}/cancel` cancels the task and closes the provider stream.
4. Deltas are coalesced (~80 ms) and events are written to the database in batches (~0.5 s). No transaction is held open while the model streams.
5. One running generation per conversation is enforced by a partial unique index in PostgreSQL (and returns HTTP 409).

### LangGraph and transcript handling

The graph is `START -> prepare_context -> generate -> END`, checkpointed with `AsyncPostgresSaver` (`thread_id` = conversation UUID). The checkpointer creates its own tables at startup (`setup()`); they are not in Alembic.

The application database is the source of truth for the visible conversation. Before each run, recent completed messages are loaded from it and trimmed to a token budget (`CONTEXT_TOKEN_BUDGET`, estimated at 4 characters per token). The graph state is overwritten each run, never appended to, so history is not accumulated in checkpoints. Only completed messages are sent to the model; failed or cancelled partial answers are not.

Only user-facing status messages ("Preparing context", "Generating response") are shown. The model's reasoning is neither requested nor stored.

### Security

Argon2id password hashes; 15-minute JWT access tokens (kept in memory in the browser); refresh tokens are random, stored only as SHA-256 hashes, rotated on every use, delivered in an HttpOnly `SameSite=Lax` cookie scoped to `/api/v1/auth`, with reuse detection that revokes all of the user's sessions. `refresh` and `logout` validate the `Origin` header against `ALLOWED_ORIGINS`. CORS is an explicit allow-list. Every conversation, message and generation query is scoped to the authenticated user and returns 404 for anything that belongs to someone else.

## Local development

Requirements: Python 3.12+, Node 20+, PostgreSQL 16.

```bash
# Backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
export DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/ai_problem_solver
export AI_ROUTER_API_KEY=your_api_key_here
alembic upgrade head
uvicorn app.main:app --reload --port 8000

# Frontend (separate terminal; proxies /api to localhost:8000)
cd frontend
npm install
npm run dev
```

For local development open <http://localhost:5173> and add it to `ALLOWED_ORIGINS` (the default already includes it).

## Tests

The backend tests need a PostgreSQL database (they use JSONB, partial indexes, row locks and the LangGraph checkpointer) and replace the AI provider with a scripted fake, so no API key or network is needed.

```bash
createdb aips_test
cd backend
TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/aips_test pytest
```

The tests cover signup/login, Argon2id and JWT validation, refresh rotation and reuse, origin checks, cross-user isolation, message persistence and pagination, one-active-generation enforcement, status transitions, SSE ordering and `Last-Event-ID` replay, cancellation (task ended and provider stream closed), provider error handling, empty/missing-key behaviour, restart interruption and checkpoint cleanup.

## Known limitations

- Generations run in the backend process. A backend restart interrupts them; on the next start any generation still marked running is recorded as `interrupted` (never claimed to have resumed), and the user can regenerate.
- Designed for a single backend instance (no Redis, queues or workers).
- Context trimming uses a character-based token estimate, not a model tokenizer.
- The provider's own rate limits and quotas still apply and are reported as errors.
- Serve over HTTPS in production (set `COOKIE_SECURE=true` and `ENVIRONMENT=production`).
