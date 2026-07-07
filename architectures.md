# Archie — Architecture

AI-powered system design interview platform.
**Stack:** React 18 + TypeScript + React Flow (Vite) · FastAPI + Python 3.11 · SQLAlchemy 2.0 · PostgreSQL + pgvector · Claude via OpenRouter

---

## 1. High-Level System Overview

```mermaid
flowchart TB
    U["👤 Candidate<br/>(Browser)"]

    subgraph FE["Frontend — React + Vite (port 5176)"]
        UI["Pages: Catalog · Interview · History · Dashboard"]
        CV["Canvas (React Flow)"]
        API_L["API Layer<br/>archieApi.ts · feedbackApi.ts"]
    end

    subgraph BE["Backend — FastAPI (port 8000)"]
        SEC["CORS + X-API-Key Security"]
        RT["Routers<br/>/chat · /api/problems · /api/sessions<br/>/api/history · /api/analytics"]
        SVC["Services<br/>TurnLoop · InterviewEngine · FeedbackGenerator<br/>RAG Retriever · SessionCache"]
    end

    subgraph DATA["Data Layer"]
        PG[("PostgreSQL<br/>+ pgvector")]
    end

    LLM["🤖 Claude<br/>(via OpenRouter API)"]

    U --> UI
    UI --> CV
    UI --> API_L
    API_L -- "JSON / REST<br/>X-API-Key header" --> SEC
    SEC --> RT
    RT --> SVC
    SVC -- "SQLAlchemy ORM" --> PG
    SVC -- "HTTPS" --> LLM
```

**Talking points**

- Classic three-tier architecture with an AI service layer embedded in the backend.
- The frontend never talks to the LLM directly — the API key stays server-side; all traffic goes through the FastAPI gateway.
- Every request carries an `X-API-Key` header validated by a FastAPI security dependency.
- All state lives in PostgreSQL — the HTTP API itself is stateless, so a server restart never loses an interview.

---

## 2. Frontend Architecture

```mermaid
flowchart LR
    subgraph VIEWS["Views (App.tsx state machine)"]
        CAT["ProblemSelector<br/><i>catalog</i>"]
        INT["Interview View<br/><i>ChatPanel + Canvas + FeedbackPanel</i>"]
        HIS["HistoryPage"]
        HISD["HistoryDetailPage"]
        DASH["DashboardPage"]
    end

    subgraph CANVAS["Canvas Module"]
        CW["CanvasWorkspace<br/>(React Flow)"]
        PAL["Palette<br/>Client · Service · Database<br/>Cache · Queue · Load Balancer"]
        EXP["canvasExporter<br/>C1 contract snapshot"]
        ELK["elkLayout<br/>auto-layout"]
    end

    subgraph APIL["API Layer"]
        A1["archieApi.ts<br/>problems · sessions · chat"]
        A2["feedbackApi.ts<br/>generate · fetch feedback"]
    end

    CAT -->|"select problem<br/>→ create session"| INT
    CAT --> HIS
    CAT --> DASH
    HIS --> HISD
    DASH --> HISD
    INT --- CW
    CW --- PAL
    CW --- EXP
    CW --- ELK
    VIEWS --> APIL
    APIL -->|"fetch + X-API-Key"| BE["FastAPI :8000"]
```

**Talking points**

- `App.tsx` is a small state machine: `catalog → interview → history → history-detail → dashboard`.
- The interview view is a split layout: chat/feedback tabs on the left, the React Flow canvas on the right.
- The canvas exports a **C1 contract** snapshot (`{id, type, label, position}` nodes, `{from, to}` edges) — a locked schema shared between the frontend and AI engine teams.
- Configuration (`config.ts`) reads `VITE_API_BASE_URL` / `VITE_X_API_KEY` from env at build time.

---

## 3. Backend Layered Architecture

```mermaid
flowchart TB
    subgraph L1["HTTP Layer"]
        MW["CORS Middleware → API-Key Dependency → Rate Limiter"]
    end

    subgraph L2["Routers (controllers — HTTP concerns only)"]
        R1["chat.py<br/>POST /chat"]
        R2["sessions.py · lifecycle.py<br/>/api/sessions"]
        R3["problems.py<br/>/api/problems"]
        R4["history.py<br/>/api/history · /api/analytics"]
        R5["users.py · rankings.py<br/>notifications.py"]
    end

    subgraph L3["Service Layer (business logic)"]
        TL["TurnLoop<br/>orchestrates one interview turn"]
        IE["InterviewEngine<br/>prompt assembly + LLM call"]
        PF["ProviderFactory<br/>OpenRouter | Gemini | NVIDIA"]
        FG["FeedbackGenerator<br/>scores 5 dimensions"]
        RAG["RAG Retriever<br/>pgvector similarity search"]
        CP["CanvasParser<br/>C1 canvas → text summary"]
        SC["SessionCache<br/>in-process TTL cache"]
    end

    subgraph L4["Data Layer"]
        ORM["SQLAlchemy 2.0 ORM + connection pool"]
        DB[("PostgreSQL + pgvector")]
    end

    MW --> L2
    R1 --> TL
    TL --> CP
    TL --> RAG
    TL --> IE
    IE --> PF
    R2 --> SC
    R4 --> FG
    L3 --> ORM
    ORM --> DB
    PF --> EXT["OpenRouter API"]
```

**Talking points**

- Strict layering: routers handle HTTP only; all business logic lives in services; services are the only layer touching the ORM.
- `ProviderFactory` abstracts the LLM behind a common interface — swapping Claude for Gemini or NVIDIA is a one-line `.env` change (`LLM_PROVIDER`).
- Hot session reads come from an in-process TTL cache (`SessionCache`) instead of hitting PostgreSQL on every poll.
- Routers are mounted twice: `/api` (backward-compatible) and `/api/v1` (canonical) for painless versioning.

---

## 4. One Interview Turn — Request Lifecycle

```mermaid
sequenceDiagram
    actor C as Candidate
    participant FE as React Frontend
    participant CH as POST /chat
    participant RAG as RAG Retriever
    participant TL as TurnLoop
    participant LLM as Claude (OpenRouter)
    participant DB as PostgreSQL

    C->>FE: types message
    FE->>FE: snapshot canvas (C1 contract)
    FE->>CH: message + chat_history + canvas + problem
    CH->>CH: summarize canvas → text
    CH->>RAG: query = problem + message + canvas summary
    RAG->>DB: pgvector cosine similarity (top-k chunks)
    DB-->>RAG: reference knowledge chunks
    CH->>TL: TurnPayload (+ rag_context)
    TL->>TL: assemble interviewer prompt
    TL->>LLM: chat completion
    LLM-->>TL: Socratic follow-up question
    CH->>DB: persist user msg + reply to session history
    CH-->>FE: ChatResponse (reply + RAG metadata)
    FE-->>C: Archie's next question
```

**Talking points**

- The canvas snapshot travels with **every** message — the AI interviewer literally sees the architecture diagram and can challenge it.
- RAG grounds the interviewer in real system design knowledge; retrieval failure degrades gracefully (turn continues without context).
- Persistence is isolated in its own DB session — a write failure never breaks the HTTP response.
- TurnLoop is stateless; all state travels in the request, so the backend scales horizontally.

---

## 5. RAG Pipeline

```mermaid
flowchart LR
    subgraph INGEST["Ingestion (offline)"]
        DOCS["System design<br/>reference docs"]
        CHK["Chunker<br/>~1500 chars, 150 overlap"]
        EMB1["Embedder<br/>sentence-transformers (local)"]
        VDB[("pgvector<br/>embeddings table")]
        DOCS --> CHK --> EMB1 --> VDB
    end

    subgraph QUERY["Retrieval (per chat turn)"]
        Q["problem + message<br/>+ canvas summary"]
        EMB2["embed query"]
        SIM["cosine similarity<br/>top-k = 5, min score 0.3"]
        CTX["formatted context<br/>→ injected into prompt"]
        Q --> EMB2 --> SIM --> CTX
    end

    VDB -.-> SIM
```

**Talking points**

- Two phases: offline ingestion (chunk → embed → store) and online retrieval on every chat turn.
- Embeddings live in PostgreSQL via **pgvector** — no separate vector database to operate.
- A minimum similarity score filters out irrelevant chunks; the response reports which topics were used (`rag` metadata).

---

## 6. Feedback Generation

```mermaid
sequenceDiagram
    actor C as Candidate
    participant FE as FeedbackPanel
    participant BE as FastAPI
    participant FG as FeedbackGenerator
    participant LLM as Claude
    participant DB as PostgreSQL

    C->>FE: ends interview
    FE->>BE: POST /api/sessions/{id}/feedback
    BE->>DB: load full session (transcript + final canvas)
    BE->>FG: generate feedback
    FG->>LLM: evaluate against rubric (C2 contract)
    LLM-->>FG: scores + strengths + improvements
    FG->>DB: persist feedback report
    BE-->>FE: FeedbackData
    FE->>FE: render radar chart (5 scores /5)
```

**Talking points**

- Scored on five dimensions: **Requirements · Scalability · Reliability · Communication · Tradeoffs** (each 1–5).
- The evaluation sees the *entire* session — full transcript plus the final canvas — not just the last message.
- The **C2 feedback contract** locks the JSON shape so frontend, feedback generator, and dashboard were built in parallel.
- Stored reports power the History detail view and all Dashboard aggregates.

---

## 7. Data Model (core tables)

```mermaid
erDiagram
    USERS ||--o{ SESSIONS : owns
    PROBLEMS ||--o{ SESSIONS : "attempted in"
    SESSIONS ||--o{ SESSION_EVENTS : logs
    SESSIONS ||--o| FEEDBACK : receives
    SESSIONS ||--o{ EVALUATIONS : scored_by
    USERS ||--o{ BOOKMARKS : saves
    USERS ||--o{ NOTIFICATIONS : gets
    USERS ||--o{ USER_ACHIEVEMENTS : earns
    ACHIEVEMENTS ||--o{ USER_ACHIEVEMENTS : defines

    SESSIONS {
        string id PK
        string problem_id FK
        string status "active | completed | abandoned"
        json history "chat transcript"
        json canvas_state "P1 canvas w/ positions"
        datetime created_at
    }
    FEEDBACK {
        string session_id FK
        json scores "5 dimensions"
        json strengths
        json improvements
    }
    PROBLEMS {
        string id PK
        string title
        json requirements
        json constraints
    }
```

**Talking points**

- `sessions` is the heart: the full chat transcript and the positioned canvas are stored as JSON on the session row — one read restores an entire interview.
- Two canvas shapes by design: **C1** (no positions, sent to the LLM) vs **P1** (with positions, persisted for pixel-perfect restore).
- `session_events` is an append-only audit trail of lifecycle transitions.
- Supporting tables (bookmarks, notifications, achievements, daily challenges) are built but headless-ready for future UI.

---

## 8. Session Lifecycle

```mermaid
stateDiagram-v2
    [*] --> active : problem selected (POST /api/sessions)
    active --> active : chat turns + canvas autosave + heartbeat
    active --> completed : candidate ends interview → feedback generated
    active --> abandoned : idle timeout (15 min) / heartbeat lost (3 min)
    abandoned --> active : resume within 24h recovery window
    completed --> [*]
```

**Talking points**

- Heartbeats detect dropped clients; idle sessions are reaped automatically.
- An abandoned interview can be resumed within a 24-hour recovery window — canvas and transcript restore exactly as left.
- Status drives the UI: History filters on it, and the Dashboard splits completed vs in-progress.

---

## 9. Tech Stack Summary

| Layer | Technology | Why |
|---|---|---|
| UI | React 18 + TypeScript (Vite) | Fast dev loop, type-safe API contracts |
| Diagramming | React Flow + ELK auto-layout | Interactive canvas with programmatic layout |
| API | FastAPI + Pydantic v2 | Async, auto-validated JSON, OpenAPI docs for free |
| AI | Claude via OpenRouter (provider-pluggable) | Quality Socratic questioning; swappable via `.env` |
| Retrieval | pgvector + sentence-transformers | Vector search inside the existing database |
| Persistence | PostgreSQL + SQLAlchemy 2.0 | Durable sessions, JSON columns for transcript/canvas |
| Security | X-API-Key dependency + CORS + rate limiting | Simple, constant-time key comparison |
