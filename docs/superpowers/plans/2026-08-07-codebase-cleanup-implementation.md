# Codebase Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split `backend/pipeline/` into layered packages (`db/`, `ingest/`, `services/`, `routers/`), remove the 10 duplicated `get_connection()`/try-finally blocks via a FastAPI `Depends` dependency, and dedupe 3 repeated patterns in the vanilla-JS frontend — with zero behavior change, verified by the existing test suite at every step.

**Architecture:** This is a pure refactor of an already-working system (85 passing backend tests, clean `vite build`), not new functionality. Every task's "test" is: existing tests still pass after the change. No new test *behavior* is introduced except in Task 4, where the dependency-injection mechanism itself changes (still zero HTTP-level behavior change).

**Tech Stack:** FastAPI, psycopg2, pytest, monkeypatch/`unittest.mock`, vanilla JS (Vite), Packery.

## Global Constraints

- No behavior change anywhere in this plan. If a task would change a response shape, status code, or DB query, it does not belong in this plan — flag it and stop instead of doing it.
- Backend: run `pytest backend/ -q` after every task; it must report the same pass count as before the task started (85 passed at plan start) unless a task explicitly says a test moved/was renamed (count stays the same either way).
- Frontend: run `npx vite build` after Task 5; must complete clean with the same module count as before (38 modules at plan start).
- Use `git mv` for every file relocation (preserves history) — never delete-and-recreate.
- Do not touch `docs/superpowers/specs/*.md` (historical design docs, not live references) even though they mention `backend/pipeline/...` paths.
- Do not touch the flagged-off wide-tile code in `src/cardRender.js` (`isWideCard`, `ART_CROP_OVERRIDES`'s sibling `ENABLE_WIDE_TILES` gate) — deliberately deferred, out of scope per `docs/notes/polish-backlog.md`.
- Do not add connection pooling, do not touch `SESSION_SECRET_KEY`/`FRONTEND_ORIGIN` env handling, do not start the Supabase/Vercel migration — all explicitly deferred to `FUTURE_IMPROVEMENTS.md`.

---

## Task 1: Move the DB-access layer out of `backend/pipeline/`

**Files:**
- Move: `backend/pipeline/db.py` → `backend/db/connection.py`
- Move: `backend/pipeline/cards.py` → `backend/db/cards.py`
- Move: `backend/pipeline/interactions.py` → `backend/db/interactions.py`
- Move: `backend/pipeline/users.py` → `backend/db/users.py`
- Create: `backend/db/__init__.py` (empty, matches `backend/pipeline/__init__.py`)
- Move: `backend/pipeline/tests/test_db.py` → `backend/db/tests/test_connection.py`
- Move: `backend/pipeline/tests/test_cards.py` → `backend/db/tests/test_cards.py`
- Move: `backend/pipeline/tests/test_interactions.py` → `backend/db/tests/test_interactions.py`
- Move: `backend/pipeline/tests/test_users.py` → `backend/db/tests/test_users.py`
- Create: `backend/db/tests/__init__.py` (empty)
- Modify: `backend/cards_router.py`, `backend/recommendations_router.py`, `backend/saves_router.py`, `backend/search_router.py`, `backend/views_router.py`, `backend/auth.py`, `backend/pipeline/run.py`

**Interfaces:**
- Produces: `backend.db.connection.get_connection()`, `backend.db.connection.init_schema(conn)`, `backend.db.connection.CREATE_EXTENSION_SQL`, `backend.db.connection.SCHEMA_SQL` (all unchanged signatures, just a new import path — was `backend.pipeline.db`)
- Produces: `backend.db.cards` module (unchanged contents — was `backend.pipeline.cards`)
- Produces: `backend.db.interactions` module (unchanged contents — was `backend.pipeline.interactions`)
- Produces: `backend.db.users` module (unchanged contents — was `backend.pipeline.users`)

- [ ] **Step 1: Move the 4 source files and their tests**

```bash
mkdir -p backend/db/tests
git mv backend/pipeline/db.py backend/db/connection.py
git mv backend/pipeline/cards.py backend/db/cards.py
git mv backend/pipeline/interactions.py backend/db/interactions.py
git mv backend/pipeline/users.py backend/db/users.py
touch backend/db/__init__.py
git add backend/db/__init__.py
git mv backend/pipeline/tests/test_db.py backend/db/tests/test_connection.py
git mv backend/pipeline/tests/test_cards.py backend/db/tests/test_cards.py
git mv backend/pipeline/tests/test_interactions.py backend/db/tests/test_interactions.py
git mv backend/pipeline/tests/test_users.py backend/db/tests/test_users.py
touch backend/db/tests/__init__.py
git add backend/db/tests/__init__.py
```

- [ ] **Step 2: Fix imports in the 4 moved files' own tests**

In `backend/db/tests/test_connection.py`, replace every occurrence of `backend.pipeline.db` with `backend.db.connection` (there are 3: the `from backend.pipeline import db` import line, and two `patch("backend.pipeline.db...."` strings):

```python
from unittest.mock import MagicMock, patch
from backend.db import connection as db
```
(the rest of the file is unchanged except `patch("backend.pipeline.db.psycopg2.connect", ...)` → `patch("backend.db.connection.psycopg2.connect", ...)` and `patch("backend.pipeline.db.register_vector", ...)` → `patch("backend.db.connection.register_vector", ...)`)

In `backend/db/tests/test_cards.py`, change the import line:
```python
from backend.db import cards
```

In `backend/db/tests/test_interactions.py`, change the import line:
```python
from backend.db import interactions
```

In `backend/db/tests/test_users.py`, change the import line:
```python
from backend.db import users
```

- [ ] **Step 3: Fix imports in the 5 API routers**

In `backend/cards_router.py`, change:
```python
from backend.pipeline import cards
from backend.pipeline.db import get_connection
```
to:
```python
from backend.db import cards
from backend.db.connection import get_connection
```

In `backend/recommendations_router.py`, change:
```python
from backend.pipeline import cards, interactions
from backend.pipeline.db import get_connection
```
to:
```python
from backend.db import cards, interactions
from backend.db.connection import get_connection
```

In `backend/saves_router.py`, change:
```python
from backend.pipeline import interactions
from backend.pipeline.db import get_connection
```
to:
```python
from backend.db import interactions
from backend.db.connection import get_connection
```

In `backend/search_router.py`, change:
```python
from backend.pipeline import cards
from backend.pipeline.db import get_connection
```
to:
```python
from backend.db import cards
from backend.db.connection import get_connection
```

In `backend/views_router.py`, change:
```python
from backend.pipeline import interactions
from backend.pipeline.db import get_connection
```
to:
```python
from backend.db import interactions
from backend.db.connection import get_connection
```

- [ ] **Step 4: Fix imports in `backend/auth.py`**

Change:
```python
from backend.pipeline import users
from backend.pipeline.db import get_connection
```
to:
```python
from backend.db import users
from backend.db.connection import get_connection
```

- [ ] **Step 5: Fix imports in `backend/pipeline/run.py`** (still lives at this path until Task 2)

Change:
```python
from backend.pipeline import cards
from backend.pipeline import db
```
to:
```python
from backend.db import cards
from backend.db import connection as db
```
(keeping the `db` local name means every other line in this file — `db.get_connection()`, `db.init_schema(conn)` — needs no further edits)

- [ ] **Step 6: Fix router test monkeypatch/import targets**

The 5 router test files patch module-level names like `"backend.cards_router.get_connection"` — those strings are unaffected by this task (the *router* module path hasn't moved yet, only what it imports from). No changes needed in `backend/tests/test_cards_router.py`, `test_recommendations_router.py`, `test_saves_router.py`, `test_search_router.py`, `test_views_router.py`, `test_auth.py` for this task.

- [ ] **Step 7: Remove the now-empty test dir, verify nothing else references the old paths**

```bash
rmdir backend/pipeline/tests 2>/dev/null || true
grep -rn "backend\.pipeline\.db\|backend\.pipeline import db\|backend\.pipeline\.cards\|backend\.pipeline import cards\|backend\.pipeline\.interactions\|backend\.pipeline import interactions\|backend\.pipeline\.users\|backend\.pipeline import users" backend/
```
Expected: no output (empty grep = all references updated). `backend/pipeline/` should now contain only `run.py`, `embed.py`, `config.py`, `rate_limit.py`, `gemini_retry.py`, `__init__.py`, and an empty `tests/` dir if `rmdir` didn't fire (fine, Task 2 removes it for good).

- [ ] **Step 8: Run the full suite**

Run: `pytest backend/ -q`
Expected: `85 passed` (same count as before this task — files moved, nothing behavioral changed)

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "refactor: move DB-access layer from backend/pipeline to backend/db"
```

---

## Task 2: Move the ingest-only pipeline into `backend/ingest/`

**Files:**
- Move: `backend/pipeline/run.py` → `backend/ingest/run.py`
- Move: `backend/pipeline/embed.py` → `backend/ingest/embed.py`
- Move: `backend/pipeline/config.py` → `backend/ingest/config.py`
- Move: `backend/pipeline/rate_limit.py` → `backend/ingest/rate_limit.py`
- Move: `backend/pipeline/gemini_retry.py` → `backend/ingest/gemini_retry.py`
- Create: `backend/ingest/__init__.py` (empty)
- Move: `backend/pipeline/tests/test_run.py` → `backend/ingest/tests/test_run.py`
- Move: `backend/pipeline/tests/test_embed.py` → `backend/ingest/tests/test_embed.py`
- Move: `backend/pipeline/tests/test_config.py` → `backend/ingest/tests/test_config.py`
- Move: `backend/pipeline/tests/test_rate_limit.py` → `backend/ingest/tests/test_rate_limit.py`
- Create: `backend/ingest/tests/__init__.py` (empty)
- Delete: `backend/pipeline/` (now empty)
- Modify: `.github/workflows/data_pipeline.yml`

**Interfaces:**
- Consumes: `backend.db.connection` (as `db`), `backend.db.cards` — from Task 1
- Produces: `backend.ingest.run.run()` (CLI entrypoint, unchanged), `backend.ingest.embed.build_embedder`, `backend.ingest.config.load_config`, `backend.ingest.rate_limit.{RateLimiter,DailyQuota,DailyQuotaExceeded,with_backoff}`, `backend.ingest.gemini_retry.is_transient_gemini_error`

- [ ] **Step 1: Move the 5 source files and their tests**

```bash
mkdir -p backend/ingest/tests
git mv backend/pipeline/run.py backend/ingest/run.py
git mv backend/pipeline/embed.py backend/ingest/embed.py
git mv backend/pipeline/config.py backend/ingest/config.py
git mv backend/pipeline/rate_limit.py backend/ingest/rate_limit.py
git mv backend/pipeline/gemini_retry.py backend/ingest/gemini_retry.py
touch backend/ingest/__init__.py
git add backend/ingest/__init__.py
git mv backend/pipeline/tests/test_run.py backend/ingest/tests/test_run.py
git mv backend/pipeline/tests/test_embed.py backend/ingest/tests/test_embed.py
git mv backend/pipeline/tests/test_config.py backend/ingest/tests/test_config.py
git mv backend/pipeline/tests/test_rate_limit.py backend/ingest/tests/test_rate_limit.py
touch backend/ingest/tests/__init__.py
git add backend/ingest/tests/__init__.py
```

- [ ] **Step 2: Fix internal imports in the moved source files**

In `backend/ingest/embed.py`, change:
```python
from backend.pipeline.config import PipelineConfig
from backend.pipeline.gemini_retry import is_transient_gemini_error
from backend.pipeline.rate_limit import DailyQuota, RateLimiter, with_backoff
```
to:
```python
from backend.ingest.config import PipelineConfig
from backend.ingest.gemini_retry import is_transient_gemini_error
from backend.ingest.rate_limit import DailyQuota, RateLimiter, with_backoff
```

In `backend/ingest/run.py`, change:
```python
from backend.db import cards
from backend.db import connection as db
from backend.pipeline.config import load_config
from backend.pipeline.embed import build_embedder
from backend.pipeline.rate_limit import DailyQuota, DailyQuotaExceeded, RateLimiter
```
to:
```python
from backend.db import cards
from backend.db import connection as db
from backend.ingest.config import load_config
from backend.ingest.embed import build_embedder
from backend.ingest.rate_limit import DailyQuota, DailyQuotaExceeded, RateLimiter
```
(the two `backend.db` lines are already correct from Task 1 — only the 3 `backend.pipeline.*` lines change)

- [ ] **Step 3: Fix imports in the moved test files**

In `backend/ingest/tests/test_run.py`, change:
```python
from backend.pipeline import run
from backend.pipeline.rate_limit import DailyQuotaExceeded
```
to:
```python
from backend.ingest import run
from backend.ingest.rate_limit import DailyQuotaExceeded
```

In `backend/ingest/tests/test_embed.py`, change:
```python
from backend.pipeline.config import PipelineConfig
from backend.pipeline.embed import Embedder, build_embedder
from backend.pipeline.rate_limit import RateLimiter, DailyQuota, DailyQuotaExceeded
```
to:
```python
from backend.ingest.config import PipelineConfig
from backend.ingest.embed import Embedder, build_embedder
from backend.ingest.rate_limit import RateLimiter, DailyQuota, DailyQuotaExceeded
```
Also change the two `patch("backend.pipeline.embed.genai")` calls to `patch("backend.ingest.embed.genai")`.

In `backend/ingest/tests/test_config.py`, change:
```python
from backend.pipeline.config import load_config, PipelineConfig
```
to:
```python
from backend.ingest.config import load_config, PipelineConfig
```

In `backend/ingest/tests/test_rate_limit.py`, change:
```python
from backend.pipeline.rate_limit import RateLimiter, DailyQuota, DailyQuotaExceeded, with_backoff
```
to:
```python
from backend.ingest.rate_limit import RateLimiter, DailyQuota, DailyQuotaExceeded, with_backoff
```

- [ ] **Step 4: Update the CI workflow**

In `.github/workflows/data_pipeline.yml`, change:
```yaml
      - name: Run pipeline
        env:
          GOOGLE_API_KEY: ${{ secrets.GOOGLE_API_KEY }}
          DATABASE_URL: ${{ secrets.DATABASE_URL }}
        run: python -m backend.pipeline.run
```
to:
```yaml
      - name: Run pipeline
        env:
          GOOGLE_API_KEY: ${{ secrets.GOOGLE_API_KEY }}
          DATABASE_URL: ${{ secrets.DATABASE_URL }}
        run: python -m backend.ingest.run
```

- [ ] **Step 5: Delete the now-empty `backend/pipeline/`**

```bash
rmdir backend/pipeline/tests 2>/dev/null || true
rm -f backend/pipeline/__init__.py
rmdir backend/pipeline 2>/dev/null || true
git add -A
```

- [ ] **Step 6: Verify no stale references remain**

```bash
grep -rn "backend\.pipeline\|backend/pipeline" backend/ .github/ --include="*.py" --include="*.yml"
```
Expected: no output.

- [ ] **Step 7: Run the full suite**

Run: `pytest backend/ -q`
Expected: `85 passed`

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "refactor: move ingest-only pipeline from backend/pipeline to backend/ingest"
```

---

## Task 3: Split routers/services out of the flat `backend/` package

**Files:**
- Create: `backend/routers/__init__.py`, `backend/routers/tests/__init__.py`
- Create: `backend/services/__init__.py`, `backend/services/tests/__init__.py`
- Move: `backend/cards_router.py` → `backend/routers/cards_router.py`
- Move: `backend/recommendations_router.py` → `backend/routers/recommendations_router.py`
- Move: `backend/saves_router.py` → `backend/routers/saves_router.py`
- Move: `backend/search_router.py` → `backend/routers/search_router.py`
- Move: `backend/views_router.py` → `backend/routers/views_router.py`
- Split `backend/auth.py` into: `backend/routers/auth_router.py` (router/OAuth endpoints) + `backend/services/auth.py` (`get_current_user`/`require_user`)
- Move: `backend/nl_search.py` → `backend/services/nl_search.py`
- Move: `backend/query_parser.py` → `backend/services/query_parser.py`
- Move: `backend/recommendations.py` → `backend/services/recommendations.py`
- Move+split: `backend/tests/test_auth.py` → `backend/services/tests/test_auth.py` (get_current_user/require_user tests) + `backend/routers/tests/test_auth_router.py` (me endpoint tests)
- Move: `backend/tests/test_cards_router.py` → `backend/routers/tests/test_cards_router.py`
- Move: `backend/tests/test_recommendations_router.py` → `backend/routers/tests/test_recommendations_router.py`
- Move: `backend/tests/test_saves_router.py` → `backend/routers/tests/test_saves_router.py`
- Move: `backend/tests/test_search_router.py` → `backend/routers/tests/test_search_router.py`
- Move: `backend/tests/test_views_router.py` → `backend/routers/tests/test_views_router.py`
- Move: `backend/tests/test_nl_search.py` → `backend/services/tests/test_nl_search.py`
- Move: `backend/tests/test_query_parser.py` → `backend/services/tests/test_query_parser.py`
- Move: `backend/tests/test_recommendations.py` → `backend/services/tests/test_recommendations.py`
- Delete: `backend/tests/` (now empty)
- Modify: `backend/main.py`

**Interfaces:**
- Produces: `backend.services.auth.get_current_user(request) -> dict | None`, `backend.services.auth.require_user(request) -> dict` (same signatures as before, new location)
- Produces: `backend.routers.auth_router.router`, `.me(request)`, `.login_google(request)`, `.auth_callback(request)` (same behavior, new location)
- Consumes (from Task 1/2): `backend.db.{cards,interactions,users}`, `backend.db.connection.get_connection`

- [ ] **Step 1: Scaffold the new packages**

```bash
mkdir -p backend/routers/tests backend/services/tests
touch backend/routers/__init__.py backend/routers/tests/__init__.py
touch backend/services/__init__.py backend/services/tests/__init__.py
git add backend/routers/__init__.py backend/routers/tests/__init__.py backend/services/__init__.py backend/services/tests/__init__.py
```

- [ ] **Step 2: Move the 5 plain routers and their tests**

```bash
git mv backend/cards_router.py backend/routers/cards_router.py
git mv backend/recommendations_router.py backend/routers/recommendations_router.py
git mv backend/saves_router.py backend/routers/saves_router.py
git mv backend/search_router.py backend/routers/search_router.py
git mv backend/views_router.py backend/routers/views_router.py
git mv backend/tests/test_cards_router.py backend/routers/tests/test_cards_router.py
git mv backend/tests/test_recommendations_router.py backend/routers/tests/test_recommendations_router.py
git mv backend/tests/test_saves_router.py backend/routers/tests/test_saves_router.py
git mv backend/tests/test_search_router.py backend/routers/tests/test_search_router.py
git mv backend/tests/test_views_router.py backend/routers/tests/test_views_router.py
```

- [ ] **Step 3: Move `nl_search.py`, `query_parser.py`, `recommendations.py` into `services/`**

```bash
git mv backend/nl_search.py backend/services/nl_search.py
git mv backend/query_parser.py backend/services/query_parser.py
git mv backend/recommendations.py backend/services/recommendations.py
git mv backend/tests/test_nl_search.py backend/services/tests/test_nl_search.py
git mv backend/tests/test_query_parser.py backend/services/tests/test_query_parser.py
git mv backend/tests/test_recommendations.py backend/services/tests/test_recommendations.py
```

`backend/services/nl_search.py` has one internal import to fix — change:
```python
from backend.query_parser import QueryParseError, parse_query
```
to:
```python
from backend.services.query_parser import QueryParseError, parse_query
```

`backend/services/tests/test_nl_search.py` — no import changes needed (`from backend import nl_search` → must become `from backend.services import nl_search`; `from backend.nl_search import resolve_search_query, translate_natural_language_query` → `from backend.services.nl_search import resolve_search_query, translate_natural_language_query`).

`backend/services/tests/test_query_parser.py` — change:
```python
from backend.query_parser import QueryParseError, parse_query
```
to:
```python
from backend.services.query_parser import QueryParseError, parse_query
```

`backend/services/tests/test_recommendations.py` — change:
```python
from backend.recommendations import compute_taste_vector
```
to:
```python
from backend.services.recommendations import compute_taste_vector
```

- [ ] **Step 4: Split `backend/auth.py`**

Create `backend/services/auth.py`:
```python
from fastapi import HTTPException, Request

from backend.db import users
from backend.db.connection import get_connection


def get_current_user(request: Request) -> dict | None:
    user_id = request.session.get("user_id")
    if user_id is None:
        return None
    conn = get_connection()
    try:
        return users.get_user_by_id(conn, user_id)
    finally:
        conn.close()


def require_user(request: Request) -> dict:
    user = get_current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Login required")
    return user
```

Create `backend/routers/auth_router.py`:
```python
import os

from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, HTTPException, Request
from starlette.responses import RedirectResponse

from backend.db import users
from backend.db.connection import get_connection
from backend.services.auth import get_current_user

router = APIRouter()

oauth = OAuth()
oauth.register(
    name="google",
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_id=os.environ.get("GOOGLE_OAUTH_CLIENT_ID"),
    client_secret=os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET"),
    client_kwargs={"scope": "openid email profile"},
)


@router.get("/auth/login/google")
async def login_google(request: Request):
    redirect_uri = request.url_for("auth_callback")
    return await oauth.google.authorize_redirect(request, redirect_uri)


@router.get("/auth/callback", name="auth_callback")
async def auth_callback(request: Request):
    token = await oauth.google.authorize_access_token(request)
    userinfo = token.get("userinfo")
    if not userinfo:
        raise HTTPException(status_code=400, detail="Google did not return user info")

    conn = get_connection()
    try:
        user = users.get_or_create_user(conn, userinfo["sub"], userinfo["email"])
        conn.commit()
    finally:
        conn.close()

    request.session["user_id"] = user["id"]
    return RedirectResponse(url="/")


@router.get("/api/v1/me")
async def me(request: Request):
    user = get_current_user(request)
    if user is None:
        return {"logged_in": False}
    return {"logged_in": True, "email": user["email"]}
```

Delete the old file:
```bash
git rm backend/auth.py
```

- [ ] **Step 5: Split `backend/tests/test_auth.py`**

Create `backend/services/tests/test_auth.py`:
```python
from unittest.mock import MagicMock
import pytest
from fastapi import HTTPException
from backend.services import auth


def test_get_current_user_returns_none_without_session():
    request = MagicMock()
    request.session = {}
    assert auth.get_current_user(request) is None


def test_get_current_user_looks_up_user_from_session(monkeypatch):
    request = MagicMock()
    request.session = {"user_id": 5}
    conn = MagicMock()
    monkeypatch.setattr(auth, "get_connection", lambda: conn)
    monkeypatch.setattr(auth.users, "get_user_by_id", lambda conn, uid: {"id": 5, "email": "a@b.com"})

    result = auth.get_current_user(request)

    assert result == {"id": 5, "email": "a@b.com"}
    conn.close.assert_called_once()


def test_require_user_raises_401_when_not_logged_in(monkeypatch):
    request = MagicMock()
    monkeypatch.setattr(auth, "get_current_user", lambda r: None)

    with pytest.raises(HTTPException) as exc_info:
        auth.require_user(request)
    assert exc_info.value.status_code == 401


def test_require_user_returns_user_when_logged_in(monkeypatch):
    request = MagicMock()
    monkeypatch.setattr(auth, "get_current_user", lambda r: {"id": 1})
    assert auth.require_user(request) == {"id": 1}
```

Create `backend/routers/tests/test_auth_router.py`:
```python
import asyncio
from unittest.mock import MagicMock
from backend.routers import auth_router


def test_me_returns_logged_in_false_when_no_session(monkeypatch):
    request = MagicMock()
    monkeypatch.setattr(auth_router, "get_current_user", lambda r: None)

    result = asyncio.run(auth_router.me(request))

    assert result == {"logged_in": False}


def test_me_returns_logged_in_true_with_email(monkeypatch):
    request = MagicMock()
    monkeypatch.setattr(auth_router, "get_current_user", lambda r: {"id": 1, "email": "a@b.com"})

    result = asyncio.run(auth_router.me(request))

    assert result == {"logged_in": True, "email": "a@b.com"}
```

Delete the old file:
```bash
git rm backend/tests/test_auth.py
```

- [ ] **Step 6: Fix imports in the 4 routers that depend on `require_user`**

In `backend/routers/recommendations_router.py`, change:
```python
from backend.auth import require_user
```
to:
```python
from backend.services.auth import require_user
```

In `backend/routers/saves_router.py`, change:
```python
from backend.auth import require_user
```
to:
```python
from backend.services.auth import require_user
```

In `backend/routers/views_router.py`, change:
```python
from backend.auth import require_user
```
to:
```python
from backend.services.auth import require_user
```

`backend/routers/search_router.py` imports `resolve_search_query` from `nl_search` — change:
```python
from backend.nl_search import resolve_search_query
```
to:
```python
from backend.services.nl_search import resolve_search_query
```

`backend/routers/recommendations_router.py` also imports `compute_taste_vector` — change:
```python
from backend.recommendations import compute_taste_vector
```
to:
```python
from backend.services.recommendations import compute_taste_vector
```

- [ ] **Step 7: Fix the 5 router test files' import lines and dependency-override targets**

In `backend/routers/tests/test_cards_router.py`, change:
```python
from backend.cards_router import router
```
to:
```python
from backend.routers.cards_router import router
```
and every `monkeypatch.setattr("backend.cards_router...."` string prefix to `"backend.routers.cards_router...."` (6 occurrences: `get_connection`, `cards.fetch_cards_page`, `cards.search_cards`, `cards.get_card`, `cards.get_card_embedding` x2, `cards.nearest_neighbors`).

In `backend/routers/tests/test_recommendations_router.py`, change:
```python
from backend.recommendations_router import router
```
to:
```python
from backend.routers.recommendations_router import router
```
and `"backend.recommendations_router...."` → `"backend.routers.recommendations_router...."` (3 occurrences), and:
```python
from backend.auth import require_user
```
to:
```python
from backend.services.auth import require_user
```

In `backend/routers/tests/test_saves_router.py`, change:
```python
from backend.saves_router import router
```
to:
```python
from backend.routers.saves_router import router
```
and `"backend.saves_router...."` → `"backend.routers.saves_router...."` (4 occurrences), and:
```python
from backend.auth import require_user
```
to:
```python
from backend.services.auth import require_user
```

In `backend/routers/tests/test_search_router.py`, change:
```python
from backend.search_router import router
```
to:
```python
from backend.routers.search_router import router
```
and `"backend.search_router...."` → `"backend.routers.search_router...."` (4 occurrences).

In `backend/routers/tests/test_views_router.py`, change:
```python
from backend.views_router import router
```
to:
```python
from backend.routers.views_router import router
```
and `"backend.views_router...."` → `"backend.routers.views_router...."` (1 occurrence), and:
```python
from backend.auth import require_user
```
to:
```python
from backend.services.auth import require_user
```

- [ ] **Step 8: Update `backend/main.py`**

Change:
```python
from backend.auth import router as auth_router
from backend.cards_router import router as cards_router
from backend.recommendations_router import router as recommendations_router
from backend.saves_router import router as saves_router
from backend.search_router import router as search_router
from backend.views_router import router as views_router
```
to:
```python
from backend.routers.auth_router import router as auth_router
from backend.routers.cards_router import router as cards_router
from backend.routers.recommendations_router import router as recommendations_router
from backend.routers.saves_router import router as saves_router
from backend.routers.search_router import router as search_router
from backend.routers.views_router import router as views_router
```

- [ ] **Step 9: Delete the now-empty `backend/tests/`**

```bash
rmdir backend/tests 2>/dev/null || true
git add -A
```

- [ ] **Step 10: Verify no stale references remain**

```bash
grep -rn "from backend\.auth\|from backend\.cards_router\|from backend\.recommendations_router\|from backend\.saves_router\|from backend\.search_router\|from backend\.views_router\|from backend\.nl_search\|from backend\.query_parser\|from backend\.recommendations import\|backend\.cards_router\.\|backend\.recommendations_router\.\|backend\.saves_router\.\|backend\.search_router\.\|backend\.views_router\." backend/ --include="*.py"
```
Expected: no output.

- [ ] **Step 11: Run the full suite**

Run: `pytest backend/ -q`
Expected: `85 passed`

- [ ] **Step 12: Commit**

```bash
git add -A
git commit -m "refactor: split routers/services out of flat backend/ into backend/routers and backend/services"
```

---

## Task 4: Dedupe the `get_connection()`/try-finally boilerplate via FastAPI `Depends`

**Files:**
- Modify: `backend/db/connection.py` (add `get_db`)
- Modify: `backend/routers/cards_router.py`, `backend/routers/recommendations_router.py`, `backend/routers/saves_router.py`, `backend/routers/search_router.py`, `backend/routers/views_router.py`
- Modify: `backend/routers/tests/test_cards_router.py`, `test_recommendations_router.py`, `test_saves_router.py`, `test_search_router.py`, `test_views_router.py`

**Interfaces:**
- Produces: `backend.db.connection.get_db()` — a generator dependency: `yield`s a connection, closes it in `finally`. Route handlers get it via `conn=Depends(get_db)`.
- This task intentionally does **not** touch `backend/services/auth.py`'s `get_current_user`/`backend/routers/auth_router.py`'s `auth_callback` — both call `get_current_user` directly (not just as a route dependency), so folding them into `Depends(get_db)` would change their call shape, not just dedupe boilerplate. Out of scope per Global Constraints (no behavior change).

- [ ] **Step 1: Add `get_db` to `backend/db/connection.py`**

Append to the end of the file:
```python


def get_db():
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()
```

- [ ] **Step 2: Refactor `backend/routers/cards_router.py`**

Replace the whole file with:
```python
from fastapi import APIRouter, Depends, HTTPException, Query

from backend.db import cards
from backend.db.connection import get_db
from backend.services.query_parser import QueryParseError, parse_query

router = APIRouter()


@router.get("/api/v1/cards")
def list_cards(
    cursor: str | None = None,
    limit: int = 30,
    seed: str | None = None,
    show_all: bool = False,
    conn=Depends(get_db),
):
    return cards.fetch_cards_page(conn, cursor, limit, seed, include_all=show_all)


@router.get("/api/v1/cards/search")
def search_cards(q: str = Query(...), conn=Depends(get_db)):
    try:
        where_sql, params = parse_query(q)
    except QueryParseError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return cards.search_cards(conn, where_sql, params)


@router.get("/api/v1/cards/{card_id}")
def get_card(card_id: str, conn=Depends(get_db)):
    card = cards.get_card(conn, card_id)
    if card is None:
        raise HTTPException(status_code=404, detail="Card not found")
    return card


@router.get("/api/v1/cards/{card_id}/similar")
def similar_cards(card_id: str, limit: int = 8, conn=Depends(get_db)):
    embedding = cards.get_card_embedding(conn, card_id)
    if embedding is None:
        raise HTTPException(status_code=404, detail="Card not found or has no embedding yet")
    return cards.nearest_neighbors(conn, embedding, limit=limit, exclude_card_id=card_id)
```

- [ ] **Step 3: Refactor `backend/routers/recommendations_router.py`**

Replace the whole file with:
```python
from fastapi import APIRouter, Depends

from backend.db import cards, interactions
from backend.db.connection import get_db
from backend.services.auth import require_user
from backend.services.recommendations import compute_taste_vector

router = APIRouter()


@router.get("/api/v1/recommendations")
def get_recommendations(user=Depends(require_user), conn=Depends(get_db)):
    embeddings = interactions.list_saved_card_embeddings(conn, user["id"])
    taste_vector = compute_taste_vector(embeddings)
    if taste_vector is None:
        return {"recommendations": [], "message": "Save some cards to get recommendations."}
    return {"recommendations": cards.nearest_neighbors(conn, taste_vector, limit=20)}
```

- [ ] **Step 4: Refactor `backend/routers/saves_router.py`**

Replace the whole file with:
```python
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from backend.db import interactions
from backend.db.connection import get_db
from backend.services.auth import require_user

router = APIRouter()


class SaveRequest(BaseModel):
    card_id: str


@router.get("/api/v1/saves")
def list_saves(user=Depends(require_user), conn=Depends(get_db)):
    return interactions.list_saves(conn, user["id"])


@router.post("/api/v1/saves")
def create_save(body: SaveRequest, user=Depends(require_user), conn=Depends(get_db)):
    interactions.add_save(conn, user["id"], body.card_id)
    conn.commit()
    return {"saved": True, "card_id": body.card_id}


@router.delete("/api/v1/saves/{card_id}")
def delete_save(card_id: str, user=Depends(require_user), conn=Depends(get_db)):
    interactions.remove_save(conn, user["id"], card_id)
    conn.commit()
    return {"saved": False, "card_id": card_id}
```

- [ ] **Step 5: Refactor `backend/routers/search_router.py`**

Replace the whole file with:
```python
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from backend.db import cards
from backend.db.connection import get_db
from backend.services.nl_search import resolve_search_query

router = APIRouter()


class NaturalSearchRequest(BaseModel):
    query: str


@router.post("/api/v1/search/natural")
def natural_search(body: NaturalSearchRequest, conn=Depends(get_db)):
    where_sql, params = resolve_search_query(body.query)
    return cards.search_cards(conn, where_sql, params)
```

- [ ] **Step 6: Refactor `backend/routers/views_router.py`**

Replace the whole file with:
```python
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from backend.db import interactions
from backend.db.connection import get_db
from backend.services.auth import require_user

router = APIRouter()


class ViewsRequest(BaseModel):
    card_ids: list[str]


@router.post("/api/v1/views")
def log_views(body: ViewsRequest, user=Depends(require_user), conn=Depends(get_db)):
    interactions.log_views(conn, user["id"], body.card_ids)
    conn.commit()
    return {"logged": len(body.card_ids)}
```

- [ ] **Step 7: Update `backend/routers/tests/test_cards_router.py`**

Replace the `_client` helper:
```python
from unittest.mock import MagicMock
from fastapi.testclient import TestClient
from fastapi import FastAPI
from backend.db.connection import get_db
from backend.routers.cards_router import router


def _client(monkeypatch):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: MagicMock()
    return TestClient(app)
```
Every other line in the file (the `monkeypatch.setattr("backend.routers.cards_router.cards...."` calls) is unchanged — those patch the `cards` module functions, not the connection.

- [ ] **Step 8: Update `backend/routers/tests/test_recommendations_router.py`**

Replace the `_client` helper:
```python
from unittest.mock import MagicMock
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware
from backend.db.connection import get_db
from backend.routers.recommendations_router import router


def _client(monkeypatch, user):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: MagicMock()
    from backend.services.auth import require_user
    app.dependency_overrides[require_user] = lambda: user
    return TestClient(app)
```
Rest of the file unchanged.

- [ ] **Step 9: Update `backend/routers/tests/test_saves_router.py`**

Replace the `_client` helper:
```python
from unittest.mock import MagicMock
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware
from backend.db.connection import get_db
from backend.routers.saves_router import router


def _client(monkeypatch, user=None):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: MagicMock()
    if user is not None:
        from backend.services.auth import require_user
        app.dependency_overrides[require_user] = lambda: user
    return TestClient(app)
```
Rest of the file unchanged (the `test_list_saves_requires_auth` test builds its own bare `app`/`client` without overrides, which is correct — it's testing the 401 path).

- [ ] **Step 10: Update `backend/routers/tests/test_search_router.py`**

Replace the `_client` helper:
```python
from unittest.mock import MagicMock
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.db.connection import get_db
from backend.routers.search_router import router


def _client(monkeypatch):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: MagicMock()
    return TestClient(app)
```
Rest of the file unchanged.

- [ ] **Step 11: Update `backend/routers/tests/test_views_router.py`**

Replace `test_log_views_calls_interactions_log_views`:
```python
def test_log_views_calls_interactions_log_views(monkeypatch):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: MagicMock()
    from backend.services.auth import require_user
    app.dependency_overrides[require_user] = lambda: {"id": 1}
    client = TestClient(app)
    calls = []
    monkeypatch.setattr("backend.routers.views_router.interactions.log_views", lambda conn, uid, cids: calls.append((uid, cids)))

    response = client.post("/api/v1/views", json={"card_ids": ["c1", "c2"]})

    assert response.status_code == 200
    assert calls == [(1, ["c1", "c2"])]
```
Add the import at the top:
```python
from backend.db.connection import get_db
```
`test_log_views_requires_auth` is unchanged (no overrides — testing the 401 path).

- [ ] **Step 12: Run the full suite**

Run: `pytest backend/ -q`
Expected: `85 passed`

- [ ] **Step 13: Commit**

```bash
git add -A
git commit -m "refactor: dedupe DB connection handling with a FastAPI Depends generator"
```

---

## Task 5: Dedupe frontend fetch/masonry/save-toggle patterns into `src/api.js`

**Files:**
- Create: `src/api.js`
- Modify: `src/main.js`, `src/favorites.js`, `src/recommendations.js`, `src/cardRender.js`

Every one of these 4 files gets touched — `favorites.js` for `apiFetch` only (its Packery config and lack of a saved-ids prefetch mean the other two helpers don't apply there).

**Interfaces:**
- Produces: `apiFetch(apiBase, path, options) -> Promise<Response>` — thin `fetch` wrapper; on a 401 response, redirects to `${apiBase}/auth/login/google` and still returns the Response (callers that need to short-circuit check `response.status === 401` themselves, same as today — this wrapper only centralizes the redirect side-effect, not the control flow, since callers currently do different things after a 401: `favorites.js`/`recommendations.js` `return` immediately, `createSaveToggler` returns `false`).
- Produces: `fetchSavedCardIds(apiBase) -> Promise<Set<string>>` — always resolves (never rejects); returns an empty `Set` on any fetch failure or non-OK response.
- Produces: `createMasonry(gallery) -> Packery` — `new Packery(gallery, {itemSelector: '.image-wrapper', columnWidth: '.image-wrapper', gutter: 15})`. `favorites.js` keeps constructing its own `Packery` inline since its config differs (`percentPosition`/`.grid-sizer`/`.gutter-sizer`).
- Consumes: `Packery` (from the `packery` package, already a dependency)

- [ ] **Step 1: Create `src/api.js`**

```javascript
import Packery from 'packery';

export async function apiFetch(apiBase, path, options) {
  const response = await fetch(`${apiBase}${path}`, options);
  if (response.status === 401) {
    window.location.href = `${apiBase}/auth/login/google`;
  }
  return response;
}

export async function fetchSavedCardIds(apiBase) {
  try {
    const response = await fetch(`${apiBase}/api/v1/saves`, { credentials: 'include' });
    if (!response.ok) return new Set();
    const saves = await response.json();
    return new Set(saves.map((c) => c.id));
  } catch (error) {
    return new Set();
  }
}

export function createMasonry(gallery) {
  return new Packery(gallery, {
    itemSelector: '.image-wrapper',
    columnWidth: '.image-wrapper',
    gutter: 15,
  });
}
```

- [ ] **Step 2: Wire `fetchSavedCardIds`/`createMasonry` into `src/main.js`**

Change the import line:
```javascript
import Packery from 'packery';
import imagesLoaded from 'imagesloaded';
import { cardArtUrl, createCardWrapper, createSaveToggler } from './cardRender.js';
import { initSidebarToggle } from './sidebar.js';
import { initSignInLink } from './authStatus.js';
```
to:
```javascript
import imagesLoaded from 'imagesloaded';
import { cardArtUrl, createCardWrapper, createSaveToggler } from './cardRender.js';
import { initSidebarToggle } from './sidebar.js';
import { initSignInLink } from './authStatus.js';
import { fetchSavedCardIds, createMasonry } from './api.js';
```
(`Packery` import drops — no longer constructed directly in this file)

Replace the saved-ids fetch block:
```javascript
  let savedCardIds = new Set();
  try {
    const savesResponse = await fetch(`${API_BASE}/api/v1/saves`, { credentials: 'include' });
    if (savesResponse.ok) {
      const saves = await savesResponse.json();
      savedCardIds = new Set(saves.map((c) => c.id));
    }
  } catch (error) {
    // Not logged in or backend unreachable — treat as no saves; the feed itself still works.
  }
```
with:
```javascript
  const savedCardIds = await fetchSavedCardIds(API_BASE);
```

Replace both `new Packery(gallery, { itemSelector: '.image-wrapper', columnWidth: '.image-wrapper', gutter: 15 })` call sites (one in `loadMoreCards`, one in the search-input handler) with `createMasonry(gallery)`.

`main.js` has no direct 401-check call sites of its own (the only auth-gated calls go through `createSaveToggler`, fixed in Step 6) — no `apiFetch` usage needed here.

- [ ] **Step 3: Wire `fetchSavedCardIds`/`createMasonry` into `src/recommendations.js`**

Change the import line:
```javascript
import Packery from 'packery';
import imagesLoaded from 'imagesloaded';
import { cardArtUrl, createCardWrapper, createSaveToggler } from './cardRender.js';
import { initSidebarToggle } from './sidebar.js';
import { initSignInLink } from './authStatus.js';
```
to:
```javascript
import imagesLoaded from 'imagesloaded';
import { cardArtUrl, createCardWrapper, createSaveToggler } from './cardRender.js';
import { initSidebarToggle } from './sidebar.js';
import { initSignInLink } from './authStatus.js';
import { apiFetch, fetchSavedCardIds, createMasonry } from './api.js';
```

Replace:
```javascript
  let savedCardIds = new Set();
  try {
    const savesResponse = await fetch(`${API_BASE}/api/v1/saves`, { credentials: 'include' });
    if (savesResponse.ok) {
      const saves = await savesResponse.json();
      savedCardIds = new Set(saves.map((c) => c.id));
    }
  } catch (error) {
    // Saved-state fetch failing shouldn't block showing recommendations.
  }
```
with:
```javascript
  const savedCardIds = await fetchSavedCardIds(API_BASE);
```

Replace:
```javascript
  const msnry = new Packery(gallery, {
    itemSelector: '.image-wrapper',
    columnWidth: '.image-wrapper',
    gutter: 15,
  });
```
with:
```javascript
  const msnry = createMasonry(gallery);
```

Replace the initial recommendations fetch:
```javascript
  let body;
  try {
    const response = await fetch(`${API_BASE}/api/v1/recommendations`, { credentials: 'include' });
    if (response.status === 401) {
      window.location.href = `${API_BASE}/auth/login/google`;
      return;
    }
    body = await response.json();
  } catch (error) {
    messageEl.textContent = 'Could not load recommendations.';
    return;
  }
```
with:
```javascript
  let body;
  try {
    const response = await apiFetch(API_BASE, '/api/v1/recommendations', { credentials: 'include' });
    if (response.status === 401) return;
    body = await response.json();
  } catch (error) {
    messageEl.textContent = 'Could not load recommendations.';
    return;
  }
```

- [ ] **Step 4: Wire `apiFetch` into `src/favorites.js`**

Change the import line:
```javascript
import Packery from 'packery';
import imagesLoaded from 'imagesloaded';
import { cardArtUrl, createCardWrapper } from './cardRender.js';
import { initSidebarToggle } from './sidebar.js';
import { initSignInLink } from './authStatus.js';
```
to:
```javascript
import Packery from 'packery';
import imagesLoaded from 'imagesloaded';
import { cardArtUrl, createCardWrapper } from './cardRender.js';
import { initSidebarToggle } from './sidebar.js';
import { initSignInLink } from './authStatus.js';
import { apiFetch } from './api.js';
```
(`Packery` stays imported here — this file's masonry config genuinely differs, per the Interfaces note above, so it keeps constructing its own instance)

Replace the initial saves fetch:
```javascript
  let saved;
  try {
    const response = await fetch(`${API_BASE}/api/v1/saves`, { credentials: 'include' });
    if (response.status === 401) {
      window.location.href = `${API_BASE}/auth/login/google`;
      return;
    }
    saved = await response.json();
  } catch (error) {
    gallery.innerHTML = `<p class="error-message">Could not load your saves.</p>`;
    return;
  }
```
with:
```javascript
  let saved;
  try {
    const response = await apiFetch(API_BASE, '/api/v1/saves', { credentials: 'include' });
    if (response.status === 401) return;
    saved = await response.json();
  } catch (error) {
    gallery.innerHTML = `<p class="error-message">Could not load your saves.</p>`;
    return;
  }
```

Replace the remove-button delete fetch:
```javascript
        const response = await fetch(`${API_BASE}/api/v1/saves/${card.id}`, {
          method: 'DELETE',
          credentials: 'include',
        });

        if (response.status === 401) {
          window.location.href = `${API_BASE}/auth/login/google`;
          return;
        }

        if (!response.ok) {
          console.error('Failed to remove save:', response.status);
          return;
        }
```
with:
```javascript
        const response = await apiFetch(API_BASE, `/api/v1/saves/${card.id}`, {
          method: 'DELETE',
          credentials: 'include',
        });

        if (response.status === 401) return;

        if (!response.ok) {
          console.error('Failed to remove save:', response.status);
          return;
        }
```

- [ ] **Step 5: Wire `apiFetch` into `src/cardRender.js`'s `createSaveToggler`**

Add the import at the top of the file:
```javascript
import { apiFetch } from './api.js';
```

Replace `createSaveToggler`:
```javascript
export function createSaveToggler(apiBase, savedCardIds) {
  return async function toggleSave(cardId, shouldSave) {
    const method = shouldSave ? 'POST' : 'DELETE';
    const path = shouldSave ? '/api/v1/saves' : `/api/v1/saves/${cardId}`;
    const response = await apiFetch(apiBase, path, {
      method,
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: shouldSave ? JSON.stringify({ card_id: cardId }) : undefined,
    });

    if (response.status === 401) return false;
    if (!response.ok) return false;

    if (shouldSave) savedCardIds.add(cardId);
    else savedCardIds.delete(cardId);
    return true;
  };
}
```

- [ ] **Step 6: Run the build**

Run: `npx vite build`
Expected: clean build, same module count as before this task (check the "modules transformed" line — 1 new module (`api.js`) added, so expect 39 instead of the 38 baseline noted in `.claude/handoff.md`; if it differs from that, investigate before continuing).

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "refactor: extract src/api.js to dedupe saved-ids fetch and Packery init"
```

---

## Task 6: Docs pass and sweep close-out

**Files:**
- Modify: `docs/notes/polish-backlog.md`

**Interfaces:** none (docs only)

- [ ] **Step 1: Final full verification**

Run: `pytest backend/ -q`
Expected: `85 passed`

Run: `npx vite build`
Expected: clean build

- [ ] **Step 2: Confirm no stale `backend.pipeline`/flat-router references remain anywhere live**

```bash
grep -rn "backend\.pipeline\|backend/pipeline" backend/ src/ .github/ README.md TRICKS.md --include="*.py" --include="*.js" --include="*.md" --include="*.yml"
```
Expected: no output. (Historical entries in `docs/notes/polish-backlog.md`'s "Done" log and `docs/superpowers/specs/*.md` are expected to still mention the old paths — those are point-in-time records, not live references, and are excluded from this grep by path.)

- [ ] **Step 3: Move the sweep from "not started" to "done" in `docs/notes/polish-backlog.md`**

In the `### Sweep: codebase cleanup` section, change the `Status:` line from:
```
Status: not started — brainstormed 2026-08-07, design approved, plan not yet written
```
to:
```
Status: done
```
Add one closing sentence after the existing item list, above `Depends on:`:
```
Landed via `docs/superpowers/plans/2026-08-07-codebase-cleanup-implementation.md` across 5 commits (backend/pipeline → backend/db + backend/ingest, backend/{routers,services} split, Depends-based connection dedup, src/api.js frontend dedup). `pytest backend/` 85 passed, `npx vite build` clean throughout. No live-browser pass done (no browser automation tool in this environment, per this doc's established note) — frontend changes are refactor-only (no DOM/behavior change), but worth a manual eyeball per the project's usual caution with `[fe]` work.
```

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "docs: close out codebase cleanup sweep"
```
