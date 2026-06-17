# Archie Backend API & Database Documentation

Python backend built using FastAPI, SQLAlchemy, and PostgreSQL.

## Database Schema & Tables Info

### 1. `users` Table
Stores user accounts.
* `id` (VARCHAR, Primary Key): Unique identifier (e.g. username or auth provider sub).
* `name` (VARCHAR, Nullable): Display name.
* `email` (VARCHAR, Unique, Nullable): Email address.
* `created_at` (TIMESTAMP): Time of registration.

### 2. `problems` Table
Stores the system design problems catalog.
* `id` (VARCHAR, Primary Key): Unique slug (e.g., `design-url-shortener`).
* `title` (VARCHAR): Title of the system design question.
* `description` (TEXT): Description of the question.
* `requirements` (JSON): List of functional/non-functional requirements.
* `constraints` (JSON): Scale constraints.
* `difficulty` (VARCHAR): Difficulty level (e.g., `Easy`, `Medium`, `Hard`).
* `category` (VARCHAR): Classification category (e.g., `System Design`).
* `estimated_time` (INTEGER): Estimated time to complete in minutes.
* `status` (VARCHAR): Catalog status (e.g., `published`, `draft`, or `archived`).
* `version` (INTEGER): Incrementing schema version of the problem description.
* `created_by` / `updated_by` (VARCHAR): Admin author tags tracking updates.
* `created_at` / `updated_at` (TIMESTAMP): Creation and update timestamps.

### 3. `sessions` Table
Stores practice sessions.
* `id` (VARCHAR, Primary Key): Unique UUID string.
* `problem_id` (VARCHAR, Foreign Key -> `problems.id`): The problem associated with this session.
* `user_id` (VARCHAR, Foreign Key -> `users.id`, Nullable): The user who owns this session.
* `status` (VARCHAR): Status (`active` or `completed`).
* `chat_history` (JSON): List of chat turns.
* `canvas_history` (JSON): List of whiteboard canvas snapshots.
* `created_at` (TIMESTAMP): Time of session creation.

### 4. `feedback` Table
Stores practice session feedback reports.
* `id` (VARCHAR, Primary Key): Unique UUID string.
* `session_id` (VARCHAR, Foreign Key -> `sessions.id`, Unique): The session associated with this feedback report.
* `scores` (JSON): Dictionary containing rating values for the 5 dimensions (`requirements`, `scalability`, `reliability`, `communication`, `tradeoffs`).
* `strengths` (JSON): List of strengths.
* `improvements` (JSON): List of improvement areas.
* `summary` (TEXT): Overall recommendation summary text.
* `created_at` (TIMESTAMP): Time of feedback report generation.

### 5. `audit_logs` Table
Tracks all administrative updates, modifications, or deletions made to the problems catalog.
* `id` (VARCHAR, Primary Key): Unique UUID string.
* `action` (VARCHAR): The CRUD action performed (`CREATE`, `UPDATE`, `DELETE`).
* `target_id` (VARCHAR): The ID/slug of the affected problem. Decoupled from foreign keys so logs persist even after a hard delete.
* `target_title` (VARCHAR, Nullable): The title of the problem.
* `performed_by` (VARCHAR): Admin username who performed the action.
* `details` (JSON, Nullable): Complete payload snapshot of the resource state.
* `created_at` (TIMESTAMP): Timestamp of the logged event.

#### Use Case: Administrative Audit Trails
In an enterprise architecture, content curation needs a durable audit trail. If an administrator edits metadata or hard-deletes a scenario, the `audit_logs` table preserves a permanent log of who changed what, when they changed it, and what the old contents were, without being impacted by cascades.

---


## API Retrieval Endpoints

All endpoints require the HTTP Header `X-API-Key: JDIDJDNK_EKJEKEN_DDCEEDD` for authorization.

### Problems Catalog
* **GET `/api/problems/`**
  * Lists all available system design problems.
* **GET `/api/problems/{problem_id}`**
  * Retrieves details for a specific problem.

### Administrative Catalog Control (Admin API)
All administrative routes require the header `X-Admin-API-Key: WERNIDF-DSDFLEINC-DAKDLE` for authorization. Default author names are set to `admin` (or configured via `ADMIN_USERNAME`).

#### 1. Create a System Design Problem (POST `/api/problems/`)
Adds a new scenario/problem to the database catalog. Default status will be set to `"published"` unless otherwise specified.
* **CURL Example:**
  ```bash
  curl -X POST -H "X-Admin-API-Key: WERNIDF-DSDFLEINC-DAKDLE" \
       -H "Content-Type: application/json" \
       -d '{
         "id": "design-tiktok-live",
         "title": "Design TikTok Live Stream",
         "description": "Design a system that allows users to stream live video to thousands of concurrent viewers.",
         "requirements": ["Real-time video ingest", "Dynamic playback resolution", "Live chat chatrooms"],
         "constraints": ["10 million active users daily", "Average streaming latency < 2s"],
         "difficulty": "Hard",
         "category": "Streaming Systems",
         "estimated_time": 45,
         "status": "published"
       }' "https://sesson-handling.onrender.com/api/problems/"
  ```

#### 2. Update/Edit a Problem (PATCH `/api/problems/{problem_id}`)
Modifies selected columns of an existing problem. 
* **Key Behavior:** Increments the problem's schema `version` counter by 1, logs the admin user in `updated_by`, and updates timestamps.
* **CURL Example:**
  ```bash
  curl -X PATCH -H "X-Admin-API-Key: WERNIDF-DSDFLEINC-DAKDLE" \
       -H "Content-Type: application/json" \
       -d '{
         "difficulty": "Medium",
         "estimated_time": 30
       }' "https://sesson-handling.onrender.com/api/problems/design-tiktok-live"
  ```

#### 3. Soft Delete / Archive a Problem (PATCH status="archived")
To hide a problem from standard candidate listings without breaking existing practice sessions or analytic trails:
* **CURL Example:**
  ```bash
  curl -X PATCH -H "X-Admin-API-Key: WERNIDF-DSDFLEINC-DAKDLE" \
       -H "Content-Type: application/json" \
       -d '{"status": "archived"}' \
       "https://sesson-handling.onrender.com/api/problems/design-tiktok-live"
  ```

#### 4. Hard Delete a Problem (DELETE `/api/problems/{problem_id}`)
Permanently purges the problem record from the system. 
* **Caution:** This action cascade-deletes all practice sessions and candidate states associated with the problem.
* **CURL Example:**
  ```bash
  curl -X DELETE -H "X-Admin-API-Key: WERNIDF-DSDFLEINC-DAKDLE" \
       "https://sesson-handling.onrender.com/api/problems/design-tiktok-live"
  ```

#### 5. Retrieve Admin Audit Logs (GET `/api/problems/admin/audit-logs`)
Lists chronological transaction logs of all administrative changes (creation, updates, deletions). The logged `target_id` is plain text, meaning logs survive hard deletions.
* **CURL Example:**
  ```bash
  curl -H "X-Admin-API-Key: WERNIDF-DSDFLEINC-DAKDLE" \
       "https://sesson-handling.onrender.com/api/problems/admin/audit-logs?limit=50&offset=0"
  ```

---

### How to use the Scenario Content API (Dynamic Catalog)
Standard candidate listings are accessed using the client header `X-API-Key: JDIDJDNK_EKJEKEN_DDCEEDD`. 

* **List Published Scenarios:** `GET /api/problems/` (only returns problems with `status="published"`).
* **Retrieve Specific Problem:** `GET /api/problems/{problem_id}` (fetches details of the specific system design question).
* **Text Search:** Filter problems by slug or title using the `search` query parameter:
  `GET /api/problems/?search=uber`
* **Admin Full Listing:** To list problems under all statuses (including `archived` or `draft` states), pass `status=all`:
  `GET /api/problems/?status=all`


### User Profiles
* **POST `/api/users/`**
  * Registers a new user.
  * Request Body: `{"id": "username", "name": "Name", "email": "email@example.com"}`
* **GET `/api/users/`**
  * Lists all users.
* **GET `/api/users/{user_id}`**
  * Retrieves details for a specific user.

### Practice Sessions
* **POST `/api/sessions/`**
  * Creates or resumes a session.
  * Request Body: `{"problem_id": "design-url-shortener", "user_id": "user_5"}`
  * Note: Enforces one session per user per problem. If a session already exists for the user and problem, it is returned.
* **GET `/api/sessions/`**
  * Lists/filters sessions.
  * Optional Query Parameters:
    * `user_id` (str): Filter by user.
    * `limit` (int): Limit returned sessions (for pagination).
* **GET `/api/sessions/{session_id}`**
  * Retrieves a session's history and canvas snapshots.
  * Optional Query Parameters:
    * `limit` (int): Return only the last N conversation turns/messages.
* **POST `/api/sessions/{session_id}/turns`**
  * Sends a message and canvas state, streams back the interviewer's reply.
  * Request Body: `{"text": "User text", "c1Snapshot": { "nodes": [], "edges": [] }}` (Note: The API schema expects `text` for the message and `c1Snapshot` for the canvas state).
* **PATCH `/api/sessions/{session_id}`**
  * Updates the status of a session (e.g., setting it to `"completed"` or `"active"`).
  * Request Body: `{"status": "completed"}`
* **POST `/api/sessions/{session_id}/send`**
  * Slices the database history to extract exactly the latest 9 chat messages and latest 9 canvas snapshots.
  * Forwards this payload to the Socratic AI Interface Adapter (the controller interface connecting to the AI).
  * Returns a success message containing the exact payload that was forwarded.

### Combined Chat Proxy
* **POST `/chat`**
  * Primary entry point connecting the React frontend with the AI interviewer engine.
  * Request Body: `{"session_id": "uuid", "problem": "Problem Title", "message": "Candidate message", "canvas_snapshot": {"nodes": [], "edges": []}}`
  * Action: Saves the candidate's turn and canvas snapshots, proxies the prompt to the AI Engine on port 8001, streams back the SSE responses, and saves the final AI response to PostgreSQL.

### Layer 3: Assessment & Feedback
* **POST `/api/sessions/{session_id}/feedback`**
  * Receives raw assessment scores and summary, saves the report to the `feedback` table, and returns it.
  * **Note**: To use or modify the scoring/evaluation logic, clone the team's branch **`feature/feedback-module`** which contains the evaluation engine.
  * **Request Body**:
    ```json
    {
      "scores": {
        "requirements": 8,
        "scalability": 9,
        "reliability": 8,
        "communication": 9,
        "tradeoffs": 7
      },
      "strengths": [
        "Good understanding of replication",
        "Clear explanation of consistency tradeoffs"
      ],
      "improvements": [
        "Could elaborate more on Redis partition handling"
      ],
      "summary": "The candidate has demonstrated strong technical knowledge of scaling and database replication."
    }
    ```
  * **Response**:
    ```json
    {
      "id": "uuid",
      "session_id": "uuid",
      "scores": {
        "requirements": 8,
        "scalability": 9,
        "reliability": 8,
        "communication": 9,
        "tradeoffs": 7
      },
      "strengths": [...],
      "improvements": [...],
      "summary": "...",
      "created_at": "2026-06-10T12:30:39.999553"
    }
    ```
* **GET `/api/sessions/{session_id}/feedback`**
  * Retrieves the saved feedback report for the session from the database.

---




## Testing Guide (How to inspect, retrieve, and test sessions)

Since the Neon database has been pre-seeded with dummy data, you can retrieve, slice, and inspect sessions easily using the **Render Hosted URL** (`https://sesson-handling.onrender.com`).

### 1. Retrieve Active Sessions for a User
To inspect the seeded sessions and retrieve active `session_id`s for a test user (e.g., `user_1`):
* **API Request (curl):**
  ```bash
  curl -H "X-API-Key: JDIDJDNK_EKJEKEN_DDCEEDD" "https://sesson-handling.onrender.com/api/sessions/?user_id=user_1"
  ```
* **PowerShell:**
  ```powershell
  (Invoke-RestMethod -Uri "https://sesson-handling.onrender.com/api/sessions/?user_id=user_1" -Headers @{"X-API-Key"="JDIDJDNK_EKJEKEN_DDCEEDD"} -Method Get) | ConvertTo-Json -Depth 5
  ```

This will return a list of sessions. Copy any `session_id` from the response (e.g., `b18f0c3d-df78-4db5-b461-12f716618be2`).

### 2. Retrieve Sliced History (e.g., Last 9 Turns)
Using the copied `session_id`, you can fetch the conversation history and canvas snapshots, sliced to the latest `N` turns (using the `limit=9` query parameter):
* **API Request (curl):**
  ```bash
  curl -H "X-API-Key: JDIDJDNK_EKJEKEN_DDCEEDD" "https://sesson-handling.onrender.com/api/sessions/{session_id}?limit=9"
  ```
* **PowerShell:**
  ```powershell
  (Invoke-RestMethod -Uri "https://sesson-handling.onrender.com/api/sessions/{session_id}?limit=9" -Headers @{"X-API-Key"="JDIDJDNK_EKJEKEN_DDCEEDD"} -Method Get) | ConvertTo-Json -Depth 5
  ```

### 3. Forward the Latest 9 Turns to Socratic AI Interface Adapter
To test the controller proxy forwarding data to the AI interface adapter, post to the `/send` endpoint. It will slice history/canvas configurations to the last 9 turns and return the forwarded JSON payload:
* **API Request (curl):**
  ```bash
  curl -X POST -H "X-API-Key: JDIDJDNK_EKJEKEN_DDCEEDD" "https://sesson-handling.onrender.com/api/sessions/{session_id}/send"
  ```
* **PowerShell:**
  ```powershell
  (Invoke-RestMethod -Uri "https://sesson-handling.onrender.com/api/sessions/{session_id}/send" -Headers @{"X-API-Key"="JDIDJDNK_EKJEKEN_DDCEEDD"} -Method Post) | ConvertTo-Json -Depth 5
  ```

### 4. Update Session Status
To mark a session as completed or toggle its status:
* **API Request (curl):**
  ```bash
  curl -X PATCH -H "X-API-Key: JDIDJDNK_EKJEKEN_DDCEEDD" -H "Content-Type: application/json" -d '{"status": "completed"}' "https://sesson-handling.onrender.com/api/sessions/{session_id}"
  ```
* **PowerShell:**
  ```powershell
  (Invoke-RestMethod -Uri "https://sesson-handling.onrender.com/api/sessions/{session_id}" -Headers @{"X-API-Key"="JDIDJDNK_EKJEKEN_DDCEEDD"} -Method Patch -Body '{"status": "completed"}' -ContentType "application/json") | ConvertTo-Json -Depth 5
  ```

### 6. Frontend JavaScript Fetch Example (Any Domain)
Since CORS is configured using a dynamic regex pattern to support all web origins and allow credentials, you can safely query the API from any frontend domain (e.g., React, Vue, or local development servers) using standard `fetch`:

```javascript
// Example: Retrieve a user's sessions from any domain
const API_URL = "https://sesson-handling.onrender.com/api/sessions/?user_id=user_1";
const API_KEY = "JDIDJDNK_EKJEKEN_DDCEEDD";

fetch(API_URL, {
  method: "GET",
  headers: {
    "X-API-Key": API_KEY,
    "Content-Type": "application/json"
  }
})
  .then(response => {
    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }
    return response.json();
  })
  .then(data => {
    console.log("Seeded User Sessions JSON:", data);
  })
  .catch(error => {
    console.error("CORS / Network Request Failed:", error);
  });
```

## Performance Optimization: Asynchronous Database Logging
To maximize throughput and concurrency under heavy user loads, the backend implements **Asynchronous Database Writes** for long-running stream connections:

* **The Problem:** SSE streaming endpoints (`POST /chat` and `POST /api/sessions/{session_id}/turns`) hold HTTP connections open while generating replies. Synchronously writing assistant messages to PostgreSQL at the end of the stream blocks Uvicorn worker threads, creating queue lag for other concurrent users.
* **The Solution:** The backend delegates all post-stream database writes to FastAPI's native `BackgroundTasks` pool. Once the final tokens are yielded and the stream terminates, the worker writes the logs asynchronously, releasing the main ASGI thread immediately to serve incoming traffic.



