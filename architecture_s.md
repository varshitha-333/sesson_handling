# Archie — Architecture

AI-powered system design interview platform.
**Stack:** React 18 + TypeScript + React Flow (Vite) · FastAPI + Python 3.11 · SQLAlchemy 2.0 · PostgreSQL + pgvector · Claude via OpenRouter

---

## 1. High-Level System Architecture

```mermaid
flowchart TB
    U["👤 Candidate (Browser)"]

    subgraph FE["Frontend — React + TypeScript + Vite"]
        VIEWS["Views: Problems Catalog · Interview · History · Dashboard"]
        CV["Canvas — React Flow<br/>Client · Service · Database · Cache · Queue"]
        APIL["API Layer — archieApi.ts · feedbackApi.ts"]
        VIEWS --- CV
        VIEWS --> APIL
    end

    subgraph BE["Backend — FastAPI"]
        SEC["CORS → X-API-Key auth → Rate limiter"]
        RT["Routers (HTTP only)<br/>/chat · /api/problems · /api/sessions · /api/history"]
        SVC["Services (business logic)<br/>TurnLoop · InterviewEngine · FeedbackGenerator<br/>RAG Retriever · SessionCache"]
        PF["ProviderFactory<br/>OpenRouter | Gemini | NVIDIA"]
        SEC --> RT --> SVC --> PF
    end

    subgraph DATA["Data Layer"]
        ORM["SQLAlchemy 2.0 ORM"]
        PG[("PostgreSQL + pgvector<br/>sessions · problems · feedback · embeddings")]
        ORM --> PG
    end

    LLM["🤖 Claude (OpenRouter API)"]

    U --> VIEWS
    APIL -- "JSON / REST + X-API-Key" --> SEC
    SVC --> ORM
    PF -- HTTPS --> LLM
```


## 2. One Interview Turn — Request Lifecycle (with RAG)

```mermaid
sequenceDiagram
    actor C as Candidate
    participant FE as React Frontend
    participant CH as POST /chat
    participant RAG as RAG Retriever
    participant TL as TurnLoop
    participant LLM as Claude (OpenRouter)
    participant DB as PostgreSQL (pgvector)

    C->>FE: types message
    FE->>FE: snapshot canvas (C1 contract)
    FE->>CH: message + chat_history + canvas + problem
    CH->>CH: summarize canvas → text
    CH->>RAG: query = problem + message + canvas summary
    RAG->>DB: embed query → cosine similarity (top-5 chunks)
    DB-->>RAG: reference knowledge chunks
    CH->>TL: TurnPayload (+ rag_context)
    TL->>TL: assemble interviewer prompt
    TL->>LLM: chat completion
    LLM-->>TL: Socratic follow-up question
    CH->>DB: persist user msg + reply to session history
    CH-->>FE: reply + RAG metadata
    FE-->>C: Archie's next question
```


---

## 3. Feedback & Progress Analytics

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
    LLM-->>FG: 5 scores + strengths + improvements
    FG->>DB: persist feedback report
    BE-->>FE: FeedbackData
    FE->>FE: render radar chart

    Note over FE,DB: Stored reports then power History & Dashboard
    FE->>BE: GET /api/sessions + feedback (History / Dashboard)
    BE-->>FE: aggregates: avg score, per-category strengths,<br/>completed vs in-progress
```


---

## 4. Data Model & Session Lifecycle

```mermaid
erDiagram
    USERS ||--o{ SESSIONS : owns
    PROBLEMS ||--o{ SESSIONS : "attempted in"
    SESSIONS ||--o{ SESSION_EVENTS : "audit log"
    SESSIONS ||--o| FEEDBACK : receives

    SESSIONS {
        string id PK
        string problem_id FK
        string status "active | completed | abandoned"
        json history "full chat transcript"
        json canvas_state "canvas with positions"
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

```mermaid
stateDiagram-v2
    [*] --> active : problem selected (POST /api/sessions)
    active --> active : chat turns + canvas autosave + heartbeat
    active --> completed : candidate ends interview → feedback generated
    active --> abandoned : idle timeout (15 min) / heartbeat lost (3 min)
    abandoned --> active : resume within 24h recovery window
    completed --> [*]
```
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
