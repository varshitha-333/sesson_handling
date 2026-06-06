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
* `system_prompt` (TEXT): Prompt guiding the interviewer.

### 3. `sessions` Table
Stores practice sessions.
* `id` (VARCHAR, Primary Key): Unique UUID string.
* `problem_id` (VARCHAR, Foreign Key -> `problems.id`): The problem associated with this session.
* `user_id` (VARCHAR, Foreign Key -> `users.id`, Nullable): The user who owns this session.
* `status` (VARCHAR): Status (`active` or `completed`).
* `chat_history` (JSON): List of chat turns.
* `canvas_history` (JSON): List of whiteboard canvas snapshots.
* `created_at` (TIMESTAMP): Time of session creation.

---

## API Retrieval Endpoints

All endpoints require the HTTP Header `X-API-Key: JDIDJDNK_EKJEKEN_DDCEEDD` for authorization.

### Problems Catalog
* **GET `/api/problems/`**
  * Lists all available system design problems.
* **GET `/api/problems/{problem_id}`**
  * Retrieves details for a specific problem.

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
  * Request Body: `{"message": "User text", "canvas_json": { "nodes": [], "edges": [] }}`
* **PATCH `/api/sessions/{session_id}`**
  * Updates the status of a session (e.g., setting it to `"completed"` or `"active"`).
  * Request Body: `{"status": "completed"}`
* **POST `/api/sessions/{session_id}/send`**
  * Slices the database history to extract exactly the latest 9 chat messages and latest 9 canvas snapshots.
  * Forwards this payload to the Socratic AI Interface Adapter (the controller interface connecting to the AI).
  * Returns a success message containing the exact payload that was forwarded.

---



## Testing Guide (How to inspect, retrieve, and test sessions)

Since the Neon database has been pre-seeded with dummy data, you can retrieve, slice, and inspect sessions easily using either the **Local URL** (`http://127.0.0.1:8000`) or the **Render Hosted URL** (`https://sesson-handling.onrender.com`).

### 1. Retrieve Active Sessions for a User
To inspect the seeded sessions and retrieve active `session_id`s for a test user (e.g., `user_1`):
* **Local API Request (curl):**
  ```bash
  curl -H "X-API-Key: JDIDJDNK_EKJEKEN_DDCEEDD" "http://127.0.0.1:8000/api/sessions/?user_id=user_1"
  ```
* **Render Hosted API Request (curl):**
  ```bash
  curl -H "X-API-Key: JDIDJDNK_EKJEKEN_DDCEEDD" "https://sesson-handling.onrender.com/api/sessions/?user_id=user_1"
  ```
* **PowerShell (Render):**
  ```powershell
  (Invoke-RestMethod -Uri "https://sesson-handling.onrender.com/api/sessions/?user_id=user_1" -Headers @{"X-API-Key"="JDIDJDNK_EKJEKEN_DDCEEDD"} -Method Get) | ConvertTo-Json -Depth 5
  ```

This will return a list of sessions. Copy any `session_id` from the response (e.g., `b18f0c3d-df78-4db5-b461-12f716618be2`).

### 2. Retrieve Sliced History (e.g., Last 9 Turns)
Using the copied `session_id`, you can fetch the conversation history and canvas snapshots, sliced to the latest `N` turns (using the `limit=9` query parameter):
* **Local API Request (curl):**
  ```bash
  curl -H "X-API-Key: JDIDJDNK_EKJEKEN_DDCEEDD" "http://127.0.0.1:8000/api/sessions/{session_id}?limit=9"
  ```
* **Render Hosted API Request (curl):**
  ```bash
  curl -H "X-API-Key: JDIDJDNK_EKJEKEN_DDCEEDD" "https://sesson-handling.onrender.com/api/sessions/{session_id}?limit=9"
  ```
* **PowerShell (Render):**
  ```powershell
  (Invoke-RestMethod -Uri "https://sesson-handling.onrender.com/api/sessions/{session_id}?limit=9" -Headers @{"X-API-Key"="JDIDJDNK_EKJEKEN_DDCEEDD"} -Method Get) | ConvertTo-Json -Depth 5
  ```

### 3. Forward the Latest 9 Turns to Socratic AI Interface Adapter
To test the controller proxy forwarding data to the AI interface adapter, post to the `/send` endpoint. It will slice history/canvas configurations to the last 9 turns and return the forwarded JSON payload:
* **Local API Request (curl):**
  ```bash
  curl -X POST -H "X-API-Key: JDIDJDNK_EKJEKEN_DDCEEDD" "http://127.0.0.1:8000/api/sessions/{session_id}/send"
  ```
* **Render Hosted API Request (curl):**
  ```bash
  curl -X POST -H "X-API-Key: JDIDJDNK_EKJEKEN_DDCEEDD" "https://sesson-handling.onrender.com/api/sessions/{session_id}/send"
  ```
* **PowerShell (Render):**
  ```powershell
  (Invoke-RestMethod -Uri "https://sesson-handling.onrender.com/api/sessions/{session_id}/send" -Headers @{"X-API-Key"="JDIDJDNK_EKJEKEN_DDCEEDD"} -Method Post) | ConvertTo-Json -Depth 5
  ```

### 4. Update Session Status
To mark a session as completed or toggle its status:
* **Local API Request (curl):**
  ```bash
  curl -X PATCH -H "X-API-Key: JDIDJDNK_EKJEKEN_DDCEEDD" -H "Content-Type: application/json" -d '{"status": "completed"}' "http://127.0.0.1:8000/api/sessions/{session_id}"
  ```
* **Render Hosted API Request (curl):**
  ```bash
  curl -X PATCH -H "X-API-Key: JDIDJDNK_EKJEKEN_DDCEEDD" -H "Content-Type: application/json" -d '{"status": "completed"}' "https://sesson-handling.onrender.com/api/sessions/{session_id}"
  ```
* **PowerShell (Render):**
  ```powershell
  (Invoke-RestMethod -Uri "https://sesson-handling.onrender.com/api/sessions/{session_id}" -Headers @{"X-API-Key"="JDIDJDNK_EKJEKEN_DDCEEDD"} -Method Patch -Body '{"status": "completed"}' -ContentType "application/json") | ConvertTo-Json -Depth 5
  ```

### 5. View All Pre-seeded Session IDs offline
For offline inspection of all 5 seeded dummy users (`user_1` to `user_5`), their 25 total sessions, and associated chat/canvas history data, you can open:
* [database_dump.json](file:///d:/internship/Archie/backend/database_dump.json) located in this directory.

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


