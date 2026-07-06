# Archie Backend — Endpoint Smoke Test Report

| Field | Value |
|---|---|
| **Base URL** | `https://web-production-3b743.up.railway.app` |
| **Generated** | 2026-07-06 12:57:52 UTC |
| **Overall** | 1 FAILED (47/48 checks) |

---

## Health & Root  —  3/3 passed

| Result | Method | Endpoint | HTTP Got | Expected | Time | Note |
|--------|--------|----------|----------|----------|------|------|
| PASS | `GET` | `/` | 200 | 200 or 307 | 704ms | root |
| PASS | `GET` | `/health` | 200 | 200 | 281ms |  |
| PASS | `GET` | `/health/db` | 200 | 200 or 503 | 562ms | 503 if DB down |

## User Endpoints  —  40/40 passed

| Result | Method | Endpoint | HTTP Got | Expected | Time | Note |
|--------|--------|----------|----------|----------|------|------|
| PASS | `GET` | `/api/v1/problems/` | 401 | 401 or 403 | 282ms | no key -> 401/403 |
| PASS | `GET` | `/api/v1/sessions/` | 401 | 401 or 403 | 281ms | no key -> 401/403 |
| PASS | `GET` | `/api/v1/users/` | 200 | 200 | 500ms | list all users |
| PASS | `GET` | `/api/v1/users/smoke-test-user-000` | 200 | 200 or 404 | 484ms | 200 if persists, 404 if first run |
| PASS | `POST` | `/api/v1/users/` | 400 | 201 or 400 | 563ms | 201 first run, 400 if already exists |
| PASS | `GET` | `/api/v1/problems/` | 200 | 200 | 578ms |  |
| PASS | `GET` | `/api/v1/problems/trending` | 200 | 200 | 844ms |  |
| PASS | `GET` | `/api/v1/problems/daily-challenge` | 200 | 200 or 404 | 546ms | 404 if no published problems |
| PASS | `GET` | `/api/v1/problems/recommended` | 200 | 200 | 860ms |  |
| PASS | `GET` | `/api/v1/problems/bookmarks` | 200 | 200 | 562ms |  |
| PASS | `GET` | `/api/v1/problems/recently-viewed` | 200 | 200 | 563ms |  |
| PASS | `GET` | `/api/v1/problems/smoke-test-problem-000` | 404 | 404 | 547ms | 404 - unknown problem |
| PASS | `GET` | `/api/v1/problems/smoke-test-problem-000/stats` | 404 | 404 | 609ms | 404 - unknown problem |
| PASS | `POST` | `/api/v1/problems/smoke-test-problem-000/rate` | 404 | 404 | 547ms | 404 - unknown problem |
| PASS | `POST` | `/api/v1/problems/smoke-test-problem-000/bookmark` | 404 | 404 | 562ms | 404 - unknown problem |
| PASS | `GET` | `/api/v1/sessions/` | 200 | 200 | 500ms |  |
| PASS | `GET` | `/api/v1/sessions/smoke-test-session-00000000` | 200 | 200 or 404 | 266ms | 200 if persists from prev run |
| PASS | `PATCH` | `/api/v1/sessions/smoke-test-session-00000000` | 200 | 200 | 766ms | auto-creates if not found (legacy) |
| PASS | `POST` | `/api/v1/sessions/smoke-test-session-00000000/send` | 200 | 200 | 500ms | returns payload |
| PASS | `GET` | `/api/v1/sessions/smoke-test-session-00000000/feedback` | 404 | 404 | 609ms | no feedback yet |
| PASS | `POST` | `/api/v1/sessions/smoke-test-session-00000000/feedback` | 422 | 200 or 404 or 422 | 281ms | 200 if session valid, 422 if validation fails |
| PASS | `GET` | `/api/v1/sessions/active` | 200 | 200 | 641ms | null when no live session |
| PASS | `POST` | `/api/v1/sessions/start` | 404 | 201 or 404 or 409 | 547ms | 404=problem not found, 409=session conflict |
| PASS | `POST` | `/api/v1/sessions/smoke-lifecycle-session-99999/heartbeat` | 404 | 404 | 562ms | 404 - session doesn't exist |
| PASS | `POST` | `/api/v1/sessions/smoke-lifecycle-session-99999/pause` | 404 | 404 | 563ms |  |
| PASS | `POST` | `/api/v1/sessions/smoke-lifecycle-session-99999/resume` | 404 | 404 | 578ms |  |
| PASS | `POST` | `/api/v1/sessions/smoke-lifecycle-session-99999/autosave` | 404 | 404 | 562ms |  |
| PASS | `POST` | `/api/v1/sessions/smoke-lifecycle-session-99999/finish` | 404 | 404 | 563ms |  |
| PASS | `POST` | `/api/v1/sessions/smoke-lifecycle-session-99999/cancel` | 404 | 404 | 547ms |  |
| PASS | `GET` | `/api/v1/sessions/smoke-lifecycle-session-99999/timer` | 404 | 404 | 578ms |  |
| PASS | `GET` | `/api/v1/sessions/smoke-lifecycle-session-99999/state` | 404 | 404 | 547ms |  |
| PASS | `GET` | `/api/v1/rankings/leaderboard` | 200 | 200 | 562ms |  |
| PASS | `GET` | `/api/v1/rankings/me` | 200 | 200 | 485ms |  |
| PASS | `GET` | `/api/v1/history/` | 200 | 200 | 578ms |  |
| PASS | `GET` | `/api/v1/history/smoke-lifecycle-session-99999` | 404 | 404 | 578ms | 404 - unknown session |
| PASS | `GET` | `/api/v1/analytics/dashboard` | 200 | 200 | 781ms |  |
| PASS | `GET` | `/api/v1/notifications/` | 200 | 200 | 547ms |  |
| PASS | `POST` | `/api/v1/notifications/smoke-test-notif-000/read` | 404 | 404 | 578ms |  |
| PASS | `POST` | `/api/v1/notifications/read-all` | 200 | 200 | 625ms |  |
| PASS | `GET` | `/api/v1/achievements/` | 200 | 200 | 563ms |  |

## Admin Endpoints  —  4/5 passed

| Result | Method | Endpoint | HTTP Got | Expected | Time | Note |
|--------|--------|----------|----------|----------|------|------|
| PASS | `GET` | `/api/v1/problems/admin/audit-logs` | 200 | 200 | 563ms | valid admin key |
| PASS | `GET` | `/api/v1/problems/admin/audit-logs` | 403 | 401 or 403 | 297ms | invalid key -> 401/403 |
| **FAIL** | `POST` | `/api/v1/problems/` | 422 | 201 or 400 | 687ms | 201=created, 400=already exists |
| PASS | `PATCH` | `/api/v1/problems/smoke-admin-problem-create-999` | 404 | 200 or 404 | 563ms | 200 if just created, 404 if create failed |
| PASS | `DELETE` | `/api/v1/problems/smoke-admin-problem-create-999` | 404 | 204 or 404 | 562ms | 204 if exists, 404 if already deleted |

---

## Known Issues / Failed Endpoints

### `POST /api/v1/problems/`
- **Got**: `422`
- **Expected**: `201, 400`
- **Note**: 201=created, 400=already exists

---

## Summary

| Metric | Count |
|---|---|
| Total checks run | 48 |
| Passed | 47 |
| Failed | 1 |
