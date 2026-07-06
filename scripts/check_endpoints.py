#!/usr/bin/env python3
"""
check_endpoints.py
==================
Smoke-tests every API endpoint of the Archie Backend against the live
Railway deployment and shows EXACTLY which ones pass and which fail.

Usage:
    python scripts/check_endpoints.py
    python scripts/check_endpoints.py --base-url https://web-production-3b743.up.railway.app --api-key YOUR_KEY --admin-key YOUR_ADMIN_KEY
    python scripts/check_endpoints.py --report endpoint_status_report.md

Exit code: 0 = all pass, 1 = one or more genuine failures
"""

import argparse
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Dict, Any

try:
    import requests
except ImportError:
    print("[ERROR] 'requests' library not installed. Run: pip install requests")
    sys.exit(1)

# ──────────────────────────────── Config ──────────────────────────────────────

DEFAULT_BASE_URL  = "https://web-production-3b743.up.railway.app"
DEFAULT_API_KEY   = os.getenv("API_KEY",       "JDIDJDNK_EKJEKEN_DDCEEDD")
DEFAULT_ADMIN_KEY = os.getenv("ADMIN_API_KEY", "WERNIDF-DSDFLEINC-DAKDLE")
TIMEOUT           = 15  # seconds

# Dummy IDs — these exist only to test error paths
# IMPORTANT: DUMMY_SESSION_ID is auto-created by PATCH (legacy behaviour),
# so lifecycle tests use DUMMY_SESSION_ID_LIFECYCLE which is always pristine.
DUMMY_USER_ID              = "smoke-test-user-000"
DUMMY_PROBLEM_ID           = "smoke-test-problem-000"
DUMMY_SESSION_ID           = "smoke-test-session-00000000"      # may auto-exist after PATCH
DUMMY_SESSION_ID_LIFECYCLE = "smoke-lifecycle-session-99999"    # never touched — always 404
DUMMY_NOTIFICATION_ID      = "smoke-test-notif-000"
DUMMY_PROBLEM_ADMIN_ID     = "smoke-admin-problem-create-999"

# ──────────────────────────────── Result ──────────────────────────────────────

@dataclass
class TestResult:
    method:         str
    path:           str
    category:       str        # health | user | admin
    status_code:    Optional[int]
    expected_codes: List[int]
    response_ms:    float
    error:          Optional[str] = None
    note:           str = ""

    @property
    def passed(self) -> bool:
        if self.error:
            return False
        return self.status_code in self.expected_codes


# ──────────────────────────────── Checker ─────────────────────────────────────

class EndpointChecker:
    def __init__(self, base_url: str, api_key: str, admin_key: str):
        self.base_url  = base_url.rstrip("/")
        self.api_key   = api_key
        self.admin_key = admin_key
        self.results: List[TestResult] = []
        self.sess      = requests.Session()

    # ── auth headers ─────────────────────────────────────────────────────────

    def _user(self)  -> Dict[str, str]:
        return {"X-API-Key": self.api_key, "Content-Type": "application/json"}

    def _admin(self) -> Dict[str, str]:
        return {"X-API-Key": self.api_key, "X-Admin-API-Key": self.admin_key,
                "Content-Type": "application/json"}

    def _none(self)  -> Dict[str, str]:
        return {"Content-Type": "application/json"}

    # ── single request ────────────────────────────────────────────────────────

    def _req(self, method: str, path: str, category: str,
             expected: List[int], headers: Dict = None,
             json: Dict = None, params: Dict = None, note: str = "") -> TestResult:
        url = self.base_url + path
        if headers is None:
            headers = self._user()
        t0 = time.monotonic()
        code, err = None, None
        try:
            r = self.sess.request(method, url, headers=headers,
                                  json=json, params=params,
                                  timeout=TIMEOUT, allow_redirects=False)
            code = r.status_code
        except requests.exceptions.Timeout:
            err = f"Timeout after {TIMEOUT}s"
        except Exception as exc:
            err = str(exc)
        ms = (time.monotonic() - t0) * 1000
        result = TestResult(method.upper(), path, category, code, expected, ms, err, note)
        self.results.append(result)
        return result

    # ── test groups ──────────────────────────────────────────────────────────

    def test_health(self):
        print("\n[HEALTH] Health & root endpoints")
        self._req("GET", "/",          "health", [200, 307], self._none(), note="root")
        self._req("GET", "/health",    "health", [200],      self._none())
        self._req("GET", "/health/db", "health", [200, 503], self._none(), note="503 if DB down")

    def test_auth_boundaries(self):
        print("\n[AUTH BOUNDARY] No-key requests must be rejected")
        self._req("GET", "/api/v1/problems/", "user", [401, 403], self._none(), note="no key -> 401/403")
        self._req("GET", "/api/v1/sessions/", "user", [401, 403], self._none(), note="no key -> 401/403")

    def test_users(self):
        print("\n[USERS] User management endpoints")
        self._req("GET",  "/api/v1/users/",                 "user", [200],       note="list all users")
        self._req("GET",  f"/api/v1/users/{DUMMY_USER_ID}", "user", [200, 404],  note="200 if persists, 404 if first run")
        self._req("POST", "/api/v1/users/",                 "user", [201, 400],
                  json={"id": DUMMY_USER_ID, "name": "Smoke Tester", "email": "smoke@example.com"},
                  note="201 first run, 400 if already exists")

    def test_problems_user(self):
        print("\n[PROBLEMS - USER] Problem catalog - user endpoints")
        self._req("GET", "/api/v1/problems/",                              "user", [200], params={"limit": 5})
        self._req("GET", "/api/v1/problems/trending",                      "user", [200], params={"days": 7, "limit": 5})
        self._req("GET", "/api/v1/problems/daily-challenge",               "user", [200, 404], note="404 if no published problems")
        self._req("GET", "/api/v1/problems/recommended",                   "user", [200], params={"user_id": DUMMY_USER_ID, "limit": 5})
        self._req("GET", "/api/v1/problems/bookmarks",                     "user", [200], params={"user_id": DUMMY_USER_ID})
        self._req("GET", "/api/v1/problems/recently-viewed",               "user", [200], params={"user_id": DUMMY_USER_ID})
        self._req("GET", f"/api/v1/problems/{DUMMY_PROBLEM_ID}",           "user", [404], note="404 - unknown problem")
        self._req("GET", f"/api/v1/problems/{DUMMY_PROBLEM_ID}/stats",     "user", [404], note="404 - unknown problem")
        self._req("POST",f"/api/v1/problems/{DUMMY_PROBLEM_ID}/rate",      "user", [404],
                  json={"user_id": DUMMY_USER_ID, "rating": 4},            note="404 - unknown problem")
        self._req("POST",f"/api/v1/problems/{DUMMY_PROBLEM_ID}/bookmark",  "user", [404],
                  json={"user_id": DUMMY_USER_ID},                         note="404 - unknown problem")

    def test_problems_admin(self):
        print("\n[PROBLEMS - ADMIN] Problem catalog - admin endpoints")
        # Audit logs - valid admin key
        self._req("GET", "/api/v1/problems/admin/audit-logs", "admin", [200], self._admin(), note="valid admin key")
        # Audit logs - wrong admin key must fail
        self._req("GET", "/api/v1/problems/admin/audit-logs", "admin", [401, 403],
                  headers={**self._user(), "X-Admin-API-Key": "wrong-key"}, note="invalid key -> 401/403")
        # Create problem (admin only)
        # Expected codes:
        #   201 = created successfully
        #   400 = already exists from a previous test run
        self._req("POST", "/api/v1/problems/", "admin", [201, 400], self._admin(),
                  json={
                      "id": DUMMY_PROBLEM_ADMIN_ID,
                      "title": "Smoke Test Problem (Admin)",
                      "description": "Created by smoke test. Safe to delete.",
                      "requirements": {"functional": "None"},
                      "constraints": ["none"],
                      "difficulty": "easy",
                      "category": "Smoke Test",
                      "status": "draft",
                      "estimated_time": 30,
                      "company": "Acme",
                      "meta": {
                          "interview_round": "phone",
                          "key_concepts": ["testing"],
                          "similar_problems": [],
                          "why_this_problem": "smoke test",
                          "what_youll_learn": ["nothing"],
                          "next_level_problems": [],
                          "sources": [],
                      },
                  },
                  note="201=created, 400=already exists")
        # Update problem (admin only)
        self._req("PATCH",  f"/api/v1/problems/{DUMMY_PROBLEM_ADMIN_ID}", "admin", [200, 404], self._admin(),
                  json={"status": "draft"}, note="200 if just created, 404 if create failed")
        # Delete problem (admin only)
        self._req("DELETE", f"/api/v1/problems/{DUMMY_PROBLEM_ADMIN_ID}", "admin", [204, 404], self._admin(),
                  note="204 if exists, 404 if already deleted")

    def test_sessions_crud(self):
        print("\n[SESSIONS - CRUD] Session management endpoints")
        self._req("GET",   "/api/v1/sessions/",                             "user", [200])
        self._req("GET",   f"/api/v1/sessions/{DUMMY_SESSION_ID}",          "user", [200, 404], note="200 if persists from prev run")
        self._req("PATCH", f"/api/v1/sessions/{DUMMY_SESSION_ID}",          "user", [200],
                  json={"status": "active"}, note="auto-creates if not found (legacy)")
        self._req("POST",  f"/api/v1/sessions/{DUMMY_SESSION_ID}/send",     "user", [200], note="returns payload")
        self._req("GET",   f"/api/v1/sessions/{DUMMY_SESSION_ID}/feedback", "user", [404], note="no feedback yet")
        self._req("POST",  f"/api/v1/sessions/{DUMMY_SESSION_ID}/feedback", "user", [200, 404, 422],
                  json={
                      "scores": {"technical_depth": 3, "solution_correctness": 3,
                                 "communication": 3, "optimization_awareness": 3,
                                 "problem_solving_confidence": 3},
                      "strengths": ["Good attempt"],
                      "improvements": ["Practice more"],
                      "summary": "Smoke test feedback.",
                  }, note="200 if session valid, 422 if validation fails")

    def test_lifecycle(self):
        print("\n[LIFECYCLE] Interview engine endpoints (use pristine session ID)")
        sid = DUMMY_SESSION_ID_LIFECYCLE  # never auto-created
        self._req("GET",  "/api/v1/sessions/active",    "user", [200],
                  params={"user_id": DUMMY_USER_ID}, note="null when no live session")
        self._req("POST", "/api/v1/sessions/start",     "user", [201, 404, 409],
                  json={"problem_id": DUMMY_PROBLEM_ID, "user_id": DUMMY_USER_ID, "browser_id": "smoke-tab"},
                  note="404=problem not found, 409=session conflict")
        self._req("POST", f"/api/v1/sessions/{sid}/heartbeat", "user", [404],
                  json={"is_idle": False}, note="404 - session doesn't exist")
        self._req("POST", f"/api/v1/sessions/{sid}/pause",     "user", [404])
        self._req("POST", f"/api/v1/sessions/{sid}/resume",    "user", [404],
                  json={"browser_id": "smoke-tab"})
        self._req("POST", f"/api/v1/sessions/{sid}/autosave",  "user", [404], json={})
        self._req("POST", f"/api/v1/sessions/{sid}/finish",    "user", [404], json={})
        self._req("POST", f"/api/v1/sessions/{sid}/cancel",    "user", [404], json={})
        self._req("GET",  f"/api/v1/sessions/{sid}/timer",     "user", [404])
        self._req("GET",  f"/api/v1/sessions/{sid}/state",     "user", [404])

    def test_rankings(self):
        print("\n[RANKINGS] Leaderboard endpoints")
        self._req("GET", "/api/v1/rankings/leaderboard", "user", [200], params={"scope": "global", "limit": 5})
        self._req("GET", "/api/v1/rankings/me",          "user", [200], params={"user_id": DUMMY_USER_ID})

    def test_history(self):
        print("\n[HISTORY & ANALYTICS] History and dashboard endpoints")
        self._req("GET", "/api/v1/history/",                              "user", [200], params={"user_id": DUMMY_USER_ID})
        self._req("GET", f"/api/v1/history/{DUMMY_SESSION_ID_LIFECYCLE}", "user", [404], note="404 - unknown session")
        self._req("GET", "/api/v1/analytics/dashboard",                   "user", [200], params={"user_id": DUMMY_USER_ID})

    def test_notifications(self):
        print("\n[NOTIFICATIONS & ACHIEVEMENTS] Notification endpoints")
        self._req("GET",  "/api/v1/notifications/",                            "user", [200], params={"user_id": DUMMY_USER_ID})
        self._req("POST", f"/api/v1/notifications/{DUMMY_NOTIFICATION_ID}/read","user", [404])
        self._req("POST", "/api/v1/notifications/read-all",                    "user", [200], params={"user_id": DUMMY_USER_ID})
        self._req("GET",  "/api/v1/achievements/",                             "user", [200], params={"user_id": DUMMY_USER_ID})

    # ── run all ───────────────────────────────────────────────────────────────

    def run_all(self):
        print("\n" + "=" * 70)
        print("  Archie Backend - Full Endpoint Smoke Test")
        print(f"  Base URL  : {self.base_url}")
        print(f"  Timestamp : {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC")
        print("=" * 70)
        self.test_health()
        self.test_auth_boundaries()
        self.test_users()
        self.test_problems_user()
        self.test_problems_admin()
        self.test_sessions_crud()
        self.test_lifecycle()
        self.test_rankings()
        self.test_history()
        self.test_notifications()

    # ── print results ─────────────────────────────────────────────────────────

    def print_summary(self) -> bool:
        total   = len(self.results)
        passed  = sum(1 for r in self.results if r.passed)
        failed  = total - passed
        failures = [r for r in self.results if not r.passed]

        print("\n" + "=" * 70)
        print(f"  RESULTS: {passed}/{total} checks passed   |   {failed} FAILED")
        print("=" * 70)

        groups = [
            ("health", "HEALTH"),
            ("user",   "USER ENDPOINTS"),
            ("admin",  "ADMIN ENDPOINTS"),
        ]

        for cat_key, cat_label in groups:
            cat_results = [r for r in self.results if r.category == cat_key]
            if not cat_results:
                continue
            cat_pass = sum(1 for r in cat_results if r.passed)
            print(f"\n  [{cat_label}]  {cat_pass}/{len(cat_results)} passed")
            for r in cat_results:
                status = "PASS" if r.passed else "FAIL"
                code   = str(r.status_code) if r.status_code else "ERR"
                ms     = f"{r.response_ms:.0f}ms"
                note   = f"  ({r.note})" if r.note else ""
                err    = f"  ERROR: {r.error}" if r.error else ""
                print(f"    [{status}]  {r.method:<7} {r.path:<58} {code:<5} {ms:>7}{note}{err}")

        if failures:
            print("\n" + "-" * 70)
            print(f"  FAILED ENDPOINTS ({len(failures)})")
            print("-" * 70)
            for r in failures:
                code = str(r.status_code) if r.status_code else "NO_RESPONSE"
                expected = "/".join(str(c) for c in r.expected_codes)
                print(f"  >> {r.method} {r.path}")
                print(f"     Got: {code}   Expected one of: [{expected}]")
                if r.error:
                    print(f"     Error: {r.error}")
                if r.note:
                    print(f"     Note: {r.note}")
        else:
            print("\n  ALL ENDPOINTS WORKING PERFECTLY!")

        print("\n" + "=" * 70 + "\n")
        return failed == 0

    # ── markdown report ───────────────────────────────────────────────────────

    def write_report(self, path: str):
        total  = len(self.results)
        passed = sum(1 for r in self.results if r.passed)
        failed = total - passed
        ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

        lines = [
            "# Archie Backend — Endpoint Smoke Test Report",
            "",
            f"| Field | Value |",
            f"|---|---|",
            f"| **Base URL** | `{self.base_url}` |",
            f"| **Generated** | {ts} |",
            f"| **Overall** | {'ALL PASSED' if failed == 0 else f'{failed} FAILED'} ({passed}/{total} checks) |",
            "",
            "---",
            "",
        ]

        groups = [
            ("health", "Health & Root"),
            ("user",   "User Endpoints"),
            ("admin",  "Admin Endpoints"),
        ]

        for cat_key, cat_label in groups:
            cat_res = [r for r in self.results if r.category == cat_key]
            if not cat_res:
                continue
            cat_pass = sum(1 for r in cat_res if r.passed)
            lines.append(f"## {cat_label}  —  {cat_pass}/{len(cat_res)} passed")
            lines.append("")
            lines.append("| Result | Method | Endpoint | HTTP Got | Expected | Time | Note |")
            lines.append("|--------|--------|----------|----------|----------|------|------|")
            for r in cat_res:
                icon     = "PASS" if r.passed else "**FAIL**"
                code     = str(r.status_code) if r.status_code else "---"
                expected = " or ".join(str(c) for c in r.expected_codes)
                ms       = f"{r.response_ms:.0f}ms"
                note     = (r.note or "") + (" " + r.error if r.error else "")
                lines.append(f"| {icon} | `{r.method}` | `{r.path}` | {code} | {expected} | {ms} | {note.strip()} |")
            lines.append("")

        # Known issues section
        failures = [r for r in self.results if not r.passed]
        if failures:
            lines.append("---")
            lines.append("")
            lines.append("## Known Issues / Failed Endpoints")
            lines.append("")
            for r in failures:
                code = str(r.status_code) if r.status_code else "NO_RESPONSE"
                expected = ", ".join(str(c) for c in r.expected_codes)
                lines.append(f"### `{r.method} {r.path}`")
                lines.append(f"- **Got**: `{code}`")
                lines.append(f"- **Expected**: `{expected}`")
                if r.note:
                    lines.append(f"- **Note**: {r.note}")
                if r.error:
                    lines.append(f"- **Error**: {r.error}")
                lines.append("")

        lines += [
            "---", "",
            "## Summary",
            "",
            "| Metric | Count |",
            "|---|---|",
            f"| Total checks run | {total} |",
            f"| Passed | {passed} |",
            f"| Failed | {failed} |",
            "",
        ]

        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        print(f"  Report saved -> {path}")


# ──────────────────────────────── CLI ─────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Archie Backend endpoint smoke-tester")
    parser.add_argument("--base-url",  default=DEFAULT_BASE_URL)
    parser.add_argument("--api-key",   default=DEFAULT_API_KEY)
    parser.add_argument("--admin-key", default=DEFAULT_ADMIN_KEY)
    parser.add_argument("--report",    default="endpoint_status_report.md")
    args = parser.parse_args()

    checker = EndpointChecker(args.base_url, args.api_key, args.admin_key)
    checker.run_all()
    all_ok = checker.print_summary()
    checker.write_report(args.report)
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
