# Archie Backend — Developer & API Reference

FastAPI + SQLAlchemy + PostgreSQL backend for **Archie**, the AI interview
platform. This module owns **session handling, the interview engine, the
problem catalog, rankings, history/analytics and feedback persistence**.


---

## 1. Architecture

```
Frontend (React) ──► POST /chat ──► Archie Backend ──► AI Engine (AI_ENGINE_URL)
                          │                │   SSE stream proxied back
                          │                └──► PostgreSQL (history persisted)
Frontend ────────► /api/v1/* REST ──► Routers ──► Services ──► SQLAlchemy ──► PostgreSQL
                                        │
                                        ├─ session_engine  (lifecycle, tokens, timers)
                                        ├─ ranking         (evaluations, leaderboards)
                                        ├─ analytics       (history, dashboard)
                                        ├─ achievements    (rules + notifications)
                                        └─ cache           (in-memory TTL, Redis-ready)
```

### Folder structure

```
app/
├── main.py               # app factory, /chat SSE proxy, health, router mounting
├── config.py             # pydantic-settings (all env vars)
├── database.py           # engine, pooling, get_db, schema_sync
├── models.py             # 14 SQLAlchemy models
├── schemas.py            # Pydantic schemas + pagination envelope
├── crud.py               # catalog/user/session CRUD + seed data
├── security.py           # X-API-Key / X-Admin-API-Key dependencies
├── errors.py             # ApiError + global handlers (consistent error shape)
├── rate_limit.py         # sliding-window rate limiter middleware
├── routes/
│   ├── problems.py       # catalog, filters, ratings, bookmarks, daily challenge…
│   ├── lifecycle.py      # interview engine endpoints
│   ├── sessions.py       # legacy session CRUD + C2 feedback endpoints
│   ├── rankings.py       # leaderboards + user rank
│   ├── history.py        # history, replay, dashboard
│   ├── notifications.py  # notifications + achievements
│   └── users.py
└── services/
    ├── session_engine.py # lifecycle state machine + concurrency control
    ├── ranking.py        # composite scoring formula + leaderboard queries
    ├── analytics.py      # aggregations
    ├── achievements.py   # award rules
    ├── cache.py          # thread-safe in-memory TTL cache
    └── interviewer.py    # canned Socratic streamer (offline fallback)
migrations/               # Alembic environment (see DEPLOYMENT.md)
```

### API versioning

Every router is mounted twice:

| Prefix | Purpose |
|---|---|
| `/api/v1/*` | **Canonical.** All new frontend work targets this. |
| `/api/*` | Backward-compatible alias for existing clients. Same handlers. |

`POST /chat`, `/`, `/health`, `/health/db` are unversioned.

---

## 2. Database

### ER diagram (text)

```
users 1───* sessions *───1 problems
              │ 1                │
              │                  ├──* problem_ratings  (UQ user+problem)
              ├──1 feedback      ├──* bookmarks        (UQ user+problem)
              ├──* session_events├──* recently_viewed  (UQ user+problem)
              └──1 evaluations   └──* daily_challenges
users 1───* notifications
users 1───* user_achievements *───1 achievements
audit_logs (standalone — survives deletes)
```

### Tables

| Table | Purpose |
|---|---|
| `users` | User accounts (`id` PK, `name`, `email` UQ, `created_at`). |
| `problems` | Problem catalog. Base fields (`title`, `description`, `difficulty`, `status`, `version`, `created_by/updated_by`, `created_at`, `updated_at`) plus normalized metadata and lookups: `category_id`, `company_id`, `interview_round_id`, `estimated_time_minutes`, `requirements_functional` JSON, `requirements_deliverables` JSON, `constraints_non_functional` JSON, `why_this_problem` TEXT, `what_youll_learn` TEXT, and denormalized engine stats (`attempts`, `completions`, `success_rate`, `avg_rating`, `rating_count`, `bookmark_count`, `avg_attempts_to_solve`). |
| `categories` | Problem category/topic lookup table. | 
| `companies` | Problem company/domain lookup table. | 
| `interview_rounds` | Interview round lookup table. | 
| `concepts` | Canonical concept lookup table for problem metadata. | 
| `problem_concepts` | Many-to-many junction between problems and concepts. | 
| `problem_similar_problems` | Problem similarity relationships. | 
| `problem_next_level_problems` | Follow-on problem recommendations. | 
| `problem_sources` | Problem source/reference table. | 
| `sessions` | Interview sessions. C2-locked JSON columns `history` & `canvas_snapshots`; engine columns: `session_token`, `browser_id`, `device_id`, `ip_address`, `lock_version`, `started_at`, `paused_at`, `completed_at`, `last_heartbeat_at`, `last_activity_at`, `total_paused_seconds`, `idle_seconds`, `time_limit_minutes`, `attempt_number`, `autosave_state` JSON. Status: `active`, `paused`, `completed`, `cancelled`, `abandoned`, `expired`. Indexes: `(user_id, status)`, `(problem_id)`. |
| `session_events` | Activity log per session (started/paused/resumed/recovered/finished/cancelled/abandoned + details). Powers replay & audit. |
| `feedback` | C2 feedback reports, 1:1 with sessions. `scores` JSON (5 locked keys), `strengths`, `improvements`, `summary` + superset columns `architecture_feedback`, `communication_feedback`, `metadata`. |
| `evaluations` | Ranking engine output, 1:1 with sessions: 5 dimension scores (0–100), `time_taken_seconds`, `retry_count`, `difficulty_multiplier`, `composite_score`. Indexes: `(problem_id, composite_score)`, `(user_id, created_at)`. |
| `problem_ratings` | 1–5 star ratings, unique per (user, problem); aggregates denormalized onto `problems`. |
| `bookmarks` | Unique per (user, problem); count denormalized onto `problems`. |
| `recently_viewed` | Last-viewed timestamps, unique per (user, problem). |
| `notifications` | Per-user notifications (`type`: info/achievement/ranking/reminder, `read` flag). |
| `achievements` / `user_achievements` | Achievement definitions (seeded) and earned records (unique per user+achievement). |
| `daily_challenges` | One problem per date (deterministic pick, persisted). |
| `audit_logs` | Admin catalog change trail (who/what/when + old/new diff). |

### Design notes

- `sessions.history` stays a JSON array — its element shape
  (`{role, content, timestamp}`) is **locked by the C2 contract** (signal
  source for the FeedbackGenerator). Normalization to a messages table is
  post-C2 work.
- Problem stats are **denormalized** and updated transactionally by the
  engine (start → `attempts`, finish → `completions`/`success_rate`/
  `avg_attempts_to_solve`, rate → `avg_rating`/`rating_count`, bookmark →
  `bookmark_count`). Cheap catalog reads; reconcile nightly if drift matters.
- Optimistic locking: `sessions.lock_version` increments on every lifecycle
  transition.
- Migrations: Alembic (`alembic upgrade head`); `schema_sync()` at startup is
  an additive dev-environment safety net only. For manual Neon migration use
  [docs/neon_migration.sql](docs/neon_migration.sql) (re-runnable; verified
  against the live database via a rolled-back dry run).
- The live Neon schema normalizes problem metadata into lookup tables and flattened columns. Legacy `problems.meta` / `problems.stats` JSONB blobs have been replaced by canonical fields and junction tables; new code should use the normalized schema.

---

## 3. Authentication

| Header | Used by | Notes |
|---|---|---|
| `X-API-Key` | All `/api/*` endpoints | Client key; compared constant-time. |
| `X-Admin-API-Key` | Problem create/update/delete, audit logs | Admin key. |
| `X-Admin-User` | Admin endpoints (optional) | Blame label recorded in `created_by`/`updated_by`/audit logs. |
| `X-Session-Token` | Interview engine mutations | Issued by `/start`, `/resume`, rotated on resume/takeover. **Required** for `/heartbeat`; validated when present elsewhere (legacy clients without it are tolerated). |

Keys are set via environment variables (`API_KEY`, `ADMIN_API_KEY`).
**Never commit real keys.** The previously published keys must be rotated.
### API key usage examples

#### Regular user requests

Use `X-API-Key` for all standard user-facing endpoints.

```bash
curl -H "X-API-Key: $API_KEY" \
  "https://<your-service>.up.railway.app/api/v1/problems/?limit=3"
```

```bash
curl -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"problem_id":"design-whatsapp","user_id":"user-123","browser_id":"tab1"}' \
  https://<your-service>.up.railway.app/api/v1/sessions/start
```

Expected behavior:
- `GET /api/v1/problems/` returns a paginated problem list.
- `POST /api/v1/sessions/start` returns `201` with `session_id`, `session_token`, and session state.

#### Admin requests

Use `X-Admin-API-Key` for protected admin endpoints.

```bash
curl -H "X-API-Key: $API_KEY" \
  -H "X-Admin-API-Key: $ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"id":"design-new-system","title":"New Problem","difficulty":"easy","category":"System Design","status":"draft","description":"Design a scalable system.","requirements":{"functional":"..."},"constraints":["...."],"estimated_time":45,"company":"Acme","meta":{"interview_round":"Backend Round","key_concepts":["APIs"],"similar_problems":[],"why_this_problem":"","what_youll_learn":[],"next_level_problems":[],"sources":[]}}' \
  https://<your-service>.up.railway.app/api/v1/problems/
```

Expected behavior:
- `POST /api/v1/problems/` creates a new problem and returns the created record.
- If the admin key is missing or invalid, the endpoint returns `401` or `403`.

#### Endpoints that do not require API keys

The following endpoints can be called directly without `X-API-Key` or `X-Admin-API-Key`:

```bash
curl https://<your-service>.up.railway.app/health
curl https://<your-service>.up.railway.app/health/db
```

The `/chat` endpoint is also open to direct client use without an API key:

```bash
curl -H "Content-Type: application/json" \
  -d '{"session_id":"session-123","problem":{"title":"Design WhatsApp"},"message":"Start interview","browser_id":"tab1"}' \
  https://<your-service>.up.railway.app/chat
```

This is useful for legacy clients or direct AI chat proxy access. All other `/api/*` or `/api/v1/*` endpoints require a valid API key.

#### How to test locally

1. Copy `.env.example` to `.env`.
2. Set `API_KEY` and `ADMIN_API_KEY` to strong values.
3. Run the app locally:

```bash
uvicorn app.main:app --reload --port 8000
```

4. Test the user endpoint:

```bash
API_KEY=your_key curl -H "X-API-Key: $API_KEY" http://localhost:8000/api/v1/problems/?limit=1
```

5. Test the admin endpoint:

```bash
API_KEY=your_key ADMIN_API_KEY=your_admin_key curl -H "X-API-Key: $API_KEY" -H "X-Admin-API-Key: $ADMIN_API_KEY" http://localhost:8000/api/v1/problems/
```

If you want to test admin creation, add `-H "Content-Type: application/json"` and a JSON body.

### Production base URL

The production backend is hosted at: `https://web-production-3b743.up.railway.app`

Use this as the base URL for all API requests in production. Example curl calls using the production URL:

```bash
# Health
curl https://web-production-3b743.up.railway.app/health

# Problems list (user)
curl -H "X-API-Key: $API_KEY" \
  "https://web-production-3b743.up.railway.app/api/v1/problems/?limit=3"

# Start session (user)
curl -X POST -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  -d '{"problem_id":"design-whatsapp","user_id":"user-123","browser_id":"tab1"}' \
  https://web-production-3b743.up.railway.app/api/v1/sessions/start

# Admin create problem (admin)
curl -X POST \
  -H "X-API-Key: $API_KEY" \
  -H "X-Admin-API-Key: $ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"title":"New Problem","slug":"design-new-system","difficulty":"Medium","category":"System Design","status":"published","requirements":{"functional":"..."} }' \
  https://web-production-3b743.up.railway.app/api/v1/problems/
```

Placeholders:
- `API_KEY` — your client API key (set in Railway variables)
- `ADMIN_API_KEY` — your admin API key (set in Railway variables)

Ensure the `CORS_ORIGINS` setting in the service variables includes the frontend origin if calling from a browser.
### Error shape (all endpoints)

```json
{ "error": { "code": "SESSION_CONFLICT", "message": "…", "details": { } } }
```

Codes include `UNAUTHORIZED`, `FORBIDDEN`, `NOT_FOUND`, `VALIDATION_ERROR`,
`SESSION_CONFLICT`, `INVALID_SESSION_STATE`, `SESSION_TOKEN_REQUIRED`,
`RATE_LIMITED`, `INTERNAL_ERROR`.

### Rate limiting

Sliding window per API key (fallback: client IP): `RATE_LIMIT_PER_MINUTE`
(default 120). Responses carry `X-RateLimit-Limit` / `X-RateLimit-Remaining`;
429 includes `Retry-After`. Health endpoints and docs are exempt.

---

## 4. Pagination, sorting, filtering

List endpoints return an envelope:

```json
{ "data": [ … ],
  "meta": { "total": 42, "limit": 20, "offset": 0, "returned": 20, "has_more": true } }
```

`GET /api/v1/problems/` supports:

| Param | Meaning |
|---|---|
| `search` | Case-insensitive match on title/description/slug |
| `status` | `published` (default) / `draft` / `archived` / `all` |
| `difficulty`, `company`, `category`, `subcategory`, `interview_round` | Exact (case-insensitive) |
| `key_concept` | Problem's `key_concepts` array contains value |
| `max_estimated_time` | Minutes ceiling |
| `user_id` | Enables per-user `bookmarked`/`completed` flags |
| `completed=true/false`, `bookmarked=true/false` | Per-user filters (require `user_id`) |
| `sort_by` | `created_at`, `updated_at`, `title`, `difficulty`, `estimated_time`, `attempts`, `completions`, `success_rate`, `avg_rating`, `bookmark_count` |
| `order` | `asc` / `desc` (default) |
| `limit` (1–100, default 20), `offset` | Pagination |

---

## 5. API Reference

All examples assume header `X-API-Key: <API_KEY>` (admin endpoints:
`X-Admin-API-Key: <ADMIN_API_KEY>`). Interactive docs: `GET /docs`.

### 5.1 Health

| Endpoint | Purpose |
|---|---|
| `GET /` | Legacy root status |
| `GET /health` | Liveness (Railway healthcheck target) |
| `GET /health/db` | Readiness — checks DB, 503 when degraded |

### 5.2 Problems catalog

| Endpoint | Description |
|---|---|
| `GET /api/v1/problems/` | List/filter/sort/search (see §4) |
| `GET /api/v1/problems/{id}?user_id=` | Problem detail (+per-user flags; records recently-viewed) |
| `GET /api/v1/problems/{id}/stats` | Full stats + average candidate stats (avg/best time, avg score) |
| `GET /api/v1/problems/trending?days=7` | Most-attempted problems in window |
| `GET /api/v1/problems/recommended?user_id=` | Personalized recommendations (next-level > category affinity > popularity) |
| `GET /api/v1/problems/daily-challenge?user_id=` | Deterministic daily problem (same for everyone) |
| `GET /api/v1/problems/bookmarks?user_id=` | User's bookmarked problems |
| `GET /api/v1/problems/recently-viewed?user_id=` | User's recently viewed problems |
| `POST /api/v1/problems/{id}/rate` | `{"user_id": "u", "rating": 1..5}` — upsert; updates `avg_rating` |
| `POST /api/v1/problems/{id}/bookmark` | `{"user_id": "u"}` — toggles; returns `{"bookmarked": bool}` |
| `POST /api/v1/problems/` (admin) | Create — body is `ProblemBase` + `"meta": {…}` |
| `PATCH /api/v1/problems/{id}` (admin) | Partial update (base and/or flat meta fields); bumps `version`, audit-logged |
| `DELETE /api/v1/problems/{id}` (admin) | Hard delete (cascades sessions!) — prefer `PATCH {"status": "archived"}` |
| `GET /api/v1/problems/admin/audit-logs` (admin) | Catalog change trail |

<details><summary>Problem response example</summary>

```json
{
  "id": "design-whatsapp", "title": "Design WhatsApp / Chat Messenger",
  "description": "…", "requirements": {"functional": "…"}, "constraints": ["…"],
  "difficulty": "medium", "category": "System Design", "subcategory": null,
  "estimated_time": 45, "company": "Meta", "status": "published",
  "meta": {
    "interview_round": "onsite",
    "key_concepts": ["WebSockets", "Message Queues", "Fan-out"],
    "similar_problems": ["design-notification-system"],
    "why_this_problem": "Tests real-time delivery…",
    "what_youll_learn": ["Delivery receipts", "…"],
    "next_level_problems": ["design-youtube"],
    "sources": ["https://github.com/donnemartin/system-design-primer"]
  },
  "stats": {
    "attempts": 12, "completions": 9, "success_rate": 0.75,
    "avg_rating": 4.5, "rating_count": 6, "bookmark_count": 3,
    "avg_attempts_to_solve": 1.4
  },
  "version": 1, "created_by": "system", "updated_by": "system",
  "created_at": "2026-07-06T10:00:00", "updated_at": "2026-07-06T10:00:00",
  "bookmarked": true, "completed": false
}
```
</details>

### 5.3 Interview engine (session lifecycle)

| Endpoint | Description |
|---|---|
| `POST /api/v1/sessions/start` | Start an interview. Body: `{"problem_id", "user_id", "browser_id?", "device_id?", "time_limit_minutes?", "takeover?"}`. **201** with state incl. `session_token`. **409 SESSION_CONFLICT** if the user already has a live interview and `takeover=false`; `takeover=true` cancels the old one. Increments `problems.attempts`; `attempt_number` counts retries per problem. |
| `GET /api/v1/sessions/active?user_id=` | Resume-after-refresh/crash discovery: the user's live session or `null` (token withheld — call `/resume`). |
| `POST /api/v1/sessions/{id}/heartbeat` | Body `{"is_idle?": bool}`. Requires `X-Session-Token` (401 without, **409** with a stale one → show takeover dialog). Updates liveness, accumulates idle time, auto-expires the countdown. Returns timer + `idle_timeout_in`. Send every ≤60 s. |
| `POST /api/v1/sessions/{id}/pause` | active → paused (pause clock stops the timer). |
| `POST /api/v1/sessions/{id}/resume` | Body `{"browser_id?", "device_id?", "takeover?"}`. Resumes paused/stale/abandoned-within-window sessions. Proof of ownership = valid token or same `browser_id`; otherwise requires `takeover=true`. **Rotates and returns** the session token (invalidates other tabs). |
| `POST /api/v1/sessions/{id}/autosave` | Body `{"autosave_state?": {...}, "canvas_state?": {...}}` — crash-recovery scratch state + canvas snapshot. |
| `POST /api/v1/sessions/{id}/finish` | → `completed`; updates problem stats, checks achievements. |
| `POST /api/v1/sessions/{id}/cancel` | → `cancelled`. |
| `GET /api/v1/sessions/{id}/timer` | Timer state (below). |
| `GET /api/v1/sessions/{id}/state` | Full engine state (token withheld). |

**Timer state:** `mode` (`countdown` when `time_limit_minutes` set — defaults
to the problem's `estimated_time` — else `stopwatch`), `elapsed_seconds`
(excludes pauses), `remaining_seconds`, `paused_seconds`, `idle_seconds`,
`thinking_seconds` (assistant-question → user-reply gaps), `speaking_seconds`
(word-count heuristic), `is_paused`, `is_expired`. Average candidate time and
best time per problem: `GET /problems/{id}/stats`.

**Liveness model:** heartbeat gap > `SESSION_HEARTBEAT_TIMEOUT_SECONDS` (180)
⇒ client considered crashed but session stays recoverable; gap >
`SESSION_RECOVERY_WINDOW_SECONDS` (24 h) ⇒ swept to `abandoned`. Idle >
`SESSION_IDLE_TIMEOUT_SECONDS` (900) ⇒ frontend should warn/auto-pause
(`idle_timeout_in` counts down in heartbeat responses).

### 5.4 Sessions (legacy CRUD — kept for compatibility)

| Endpoint | Description |
|---|---|
| `POST /api/v1/sessions/` | Create session. Body: `{"problem_id", "user_id?"}`. Returns **404** if the referenced problem does not exist. |
| `GET /api/v1/sessions/?user_id=&limit=&offset=` | List sessions (newest first). |
| `GET /api/v1/sessions/{id}?limit=N` | Session with history/canvas (optionally last N). |
| `POST /api/v1/sessions/{id}/turns` | `{"text", "c1Snapshot?"}` — persists turn, streams interviewer reply (SSE). |
| `PATCH /api/v1/sessions/{id}` | `{"status?", "canvas_state?"}`. |
| `POST /api/v1/sessions/{id}/send` | Forwards last 9 turns/snapshots to the Socratic AI adapter. |

### 5.5 Feedback (C2 contract — locked)

| Endpoint | Description |
|---|---|
| `POST /api/v1/sessions/{id}/feedback` | Persists the C2 feedback report (upsert). Accepts the **full C2 JSON** or the minimal subset `{scores, strengths, improvements, summary}`. Scores validated as integers 1–5 with exactly the 5 locked keys. **Side effect:** for non-anonymous sessions, computes/refreshes the `evaluations` row (ranking) and re-checks achievements. |
| `GET /api/v1/sessions/{id}/feedback` | Returns the stored report (404 with guidance if not yet generated). |

### 5.6 Rankings

| Endpoint | Description |
|---|---|
| `GET /api/v1/rankings/leaderboard?scope=global|weekly|monthly&problem_id=&company=&limit=&offset=` | Paginated leaderboard: rank, user, avg composite score, interviews completed, best score. |
| `GET /api/v1/rankings/me?user_id=&scope=&problem_id=&company=` | User's rank, percentile, avg score, and `rank_change` vs the previous period (weekly/monthly). |

**Composite score formula** (full derivation in
[`app/services/ranking.py`](app/services/ranking.py)): dimension scores from
C2 feedback (technical 30%, correctness 20%, communication 20%, optimization
15%, confidence 15%) × time multiplier (0.70–1.05) × retry multiplier
(−5%/retry, floor 0.85) × difficulty multiplier (Easy 0.90 / Medium 1.00 /
Hard 1.15), clamped 0–100.

### 5.7 History & analytics

| Endpoint | Description |
|---|---|
| `GET /api/v1/history/?user_id=&status=&limit=&offset=` | Interview history (problem, status, attempt #, duration, score, summary). |
| `GET /api/v1/history/{session_id}` | **Replay payload**: transcript, canvas snapshots, lifecycle events, feedback, evaluation. |
| `GET /api/v1/analytics/dashboard?user_id=` | Problems solved/attempted, completion & success rate, avg score/time, personal best, weak/strong topics, current & longest streak, interview readiness (0–100), per-company readiness, learning curve. |

### 5.8 Notifications & achievements

| Endpoint | Description |
|---|---|
| `GET /api/v1/notifications/?user_id=&unread_only=` | Paginated notifications. |
| `POST /api/v1/notifications/{id}/read` · `POST /api/v1/notifications/read-all?user_id=` | Mark read. |
| `GET /api/v1/achievements/?user_id=&earned_only=` | Achievement definitions with `earned_at` for earned ones. |

### 5.9 Users

`POST /api/v1/users/` · `GET /api/v1/users/` · `GET /api/v1/users/{id}` — unchanged.

### 5.10 Chat proxy

`POST /chat` — persists the candidate turn + canvas snapshot, proxies to the
AI engine (`AI_ENGINE_URL`), streams SSE back, persists the assistant reply
post-stream via `BackgroundTasks`.

---

## 6. Environment variables

See [.env.example](.env.example). Summary:

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | local PG | PostgreSQL URL (Railway: reference the PG plugin) |
| `API_KEY` / `ADMIN_API_KEY` | placeholders | Auth keys — set strong values |
| `ADMIN_USERNAME` | `admin` | Fallback blame label |
| `CORS_ORIGINS` | `*` | Comma-separated origins; pin in production |
| `AI_ENGINE_URL` | `http://127.0.0.1:8001/chat` | Chat proxy upstream |
| `SESSION_HEARTBEAT_TIMEOUT_SECONDS` | 180 | Stale-client threshold |
| `SESSION_IDLE_TIMEOUT_SECONDS` | 900 | Idle warning window |
| `SESSION_RECOVERY_WINDOW_SECONDS` | 86400 | Crash-recovery window |
| `RATE_LIMIT_PER_MINUTE` | 120 | 0 disables |
| `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` | 5 / 10 | PG connection pool |
| `TESTING` | false | Skips DB init at startup (unit tests) |
| `PORT` | — | Provided by Railway; consumed by the uvicorn start command |

---

## 7. Endpoint Smoke-Test Script

A ready-to-run smoke-test script is included at [`scripts/check_endpoints.py`](scripts/check_endpoints.py).
It tests **all 46 endpoints** across **48 checks** (user + admin + health) against the live Railway deployment and prints a
summary table. An optional Markdown report can also be generated.

> **Note:** `difficulty` must be lowercase (`easy` / `medium` / `hard`) — enforced by a CHECK constraint on the live database.

### Prerequisites

```bash
pip install requests
```

(`requests>=2.31.0` is also listed in `requirements.txt`.)

### Usage

```bash
# Quick check against production (reads API keys from env)
export API_KEY=YOUR_API_KEY
export ADMIN_API_KEY=YOUR_ADMIN_API_KEY
python scripts/check_endpoints.py

# Pass keys directly and save a Markdown report
python scripts/check_endpoints.py \
    --base-url https://web-production-3b743.up.railway.app \
    --api-key  YOUR_API_KEY \
    --admin-key YOUR_ADMIN_API_KEY \
    --report endpoint_status_report.md
```

### What it tests

| Category | Endpoints tested | Auth used |
|---|---|---|
| Health | `GET /`, `/health`, `/health/db` | None |
| Auth boundary | Rejects requests with no key | None (expect 401/403) |
| Users | Create, list, get by ID | `X-API-Key` |
| Problems (user) | List, trending, daily-challenge, recommended, bookmarks, recently-viewed, get, stats, rate, bookmark | `X-API-Key` |
| Problems (admin) | Audit-logs, create, update, delete; invalid-key rejection | `X-Admin-API-Key` |
| Sessions (CRUD) | Create, list, get, patch, send, feedback POST/GET | `X-API-Key` |
| Interview lifecycle | start, active, heartbeat, pause, resume, autosave, finish, cancel, timer, state | `X-API-Key` |
| Rankings | Leaderboard, my rank | `X-API-Key` |
| History & analytics | History list, history detail, dashboard | `X-API-Key` |
| Notifications | List, mark-read, mark-all-read, achievements | `X-API-Key` |

### Exit codes

| Code | Meaning |
|---|---|
| `0` | All checks passed |
| `1` | One or more checks failed |

---

## 8. Future expansion notes

- **Normalize `history` → `conversation_messages`** after C2 (locked contract
  currently reads the JSON array).
- **Redis** for cache + rate limiting when scaling beyond one instance
  (both sit behind small interfaces).
- **JWT end-user auth** — platform-level decision; session tokens already
  bind interviews to clients, so JWT slots in as a `get_current_user`
  dependency without schema changes.
- **Background jobs** (nightly stats reconciliation, leaderboard snapshots,
  reminder notifications) — Railway cron or APScheduler.
- **Observability** — structured JSON logs, request IDs, Prometheus
  `/metrics`, Sentry.
- Materialized leaderboards once `evaluations` outgrows in-request
  aggregation (current implementation aggregates per request, fine to ~10⁵
  rows).

