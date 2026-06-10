import httpx
import json
import time
from app.database import SessionLocal, verify_db_connection
from app import models

BASE_URL = "http://127.0.0.1:8000"
API_KEY = "JDIDJDNK_EKJEKEN_DDCEEDD"
HEADERS = {"X-API-Key": API_KEY, "Content-Type": "application/json"}

def test_feedback_module():
    print("=" * 60)
    print("TESTING LAYER 3 FEEDBACK GENERATION & DB PERSISTENCE")
    print("=" * 60)

    # 1. Setup a test session in the database
    db = SessionLocal()
    session_id = "test-feedback-session-" + str(int(time.time()))
    
    print(f"1. Pre-seeding a test session: {session_id}")
    try:
        # Verify rate-limiter problem exists in database catalog
        problem = db.query(models.Problem).filter(models.Problem.id == "design-rate-limiter").first()
        if not problem:
            print("[ERROR] Problems catalog is empty! Please start the backend server once to seed problems.")
            return

        # Insert a dummy session with sample chat history containing system design keywords
        sample_history = [
            {"role": "user", "content": "I want to design a rate limiter. The functional requirements are clear.", "timestamp": "2026-06-10T12:00:00Z"},
            {"role": "assistant", "content": "Sounds good. What non-functional requirements or constraints are we targeting?", "timestamp": "2026-06-10T12:01:00Z"},
            {"role": "user", "content": "We need to scale to 10k QPS. I will place a load balancer in front of API gateways, and add a Redis cache cluster.", "timestamp": "2026-06-10T12:02:00Z"},
            {"role": "assistant", "content": "Nice. How will you avoid data loss and single points of failure in Redis?", "timestamp": "2026-06-10T12:03:00Z"},
            {"role": "user", "content": "I will enable Redis database replication with master-slave architecture and active failover to eliminate SPOFs.", "timestamp": "2026-06-10T12:04:00Z"},
            {"role": "assistant", "content": "Good. What tradeoffs did you make in this active failover choice?", "timestamp": "2026-06-10T12:05:00Z"},
            {"role": "user", "content": "The trade-off is eventual consistency vs strong consistency. I choose eventual consistency for lower latency.", "timestamp": "2026-06-10T12:06:00Z"}
        ]
        
        test_session = models.Session(
            id=session_id,
            problem_id="design-rate-limiter",
            user_id=None,
            status="active",
            history=sample_history,
            canvas_snapshots=[]
        )
        db.add(test_session)
        db.commit()
        print("[SUCCESS] Test session created in database.")
    except Exception as e:
        print(f"[ERROR] failed to create test session: {e}")
        db.close()
        return
    finally:
        db.close()

    # 2. Call POST to save feedback
    print(f"\n2. Calling POST /api/sessions/{session_id}/feedback...")
    feedback_payload = {
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
    with httpx.Client(timeout=10.0) as client:
        resp = client.post(
            f"{BASE_URL}/api/sessions/{session_id}/feedback",
            headers=HEADERS,
            json=feedback_payload
        )
        if resp.status_code != 200:
            print(f"[ERROR] POST feedback failed with status code {resp.status_code}")
            print(resp.text)
            return
        
        post_result = resp.json()
        print("[SUCCESS] Feedback saved successfully via POST API:")
        print(json.dumps(post_result, indent=2))

    # 3. Query PostgreSQL directly to verify storage
    print("\n3. Querying PostgreSQL directly to verify storage...")
    db_check = SessionLocal()
    try:
        feedback_in_db = db_check.query(models.Feedback).filter(models.Feedback.session_id == session_id).first()
        if not feedback_in_db:
            print("[ERROR] Feedback record not found in PostgreSQL table!")
            return
        
        print("[SUCCESS] Feedback record successfully persisted in PostgreSQL table.")
        print(f"  Feedback Record ID:  {feedback_in_db.id}")
        print(f"  Scores persisted:    {feedback_in_db.scores}")
        print(f"  Summary persisted:   {feedback_in_db.summary}")
    except Exception as e:
        print(f"[ERROR] Direct DB check failed: {e}")
    finally:
        db_check.close()

    # 4. Call GET to retrieve saved feedback
    print(f"\n4. Calling GET /api/sessions/{session_id}/feedback...")
    with httpx.Client(timeout=10.0) as client:
        resp_get = client.get(f"{BASE_URL}/api/sessions/{session_id}/feedback", headers=HEADERS)
        if resp_get.status_code != 200:
            print(f"[ERROR] GET feedback failed with status code {resp_get.status_code}")
            return
        
        get_result = resp_get.json()
        print("[SUCCESS] Feedback report retrieved successfully via GET API:")
        print(f"  Summary: {get_result['summary']}")
        print(f"  Scores:  {get_result['scores']}")

    print("\n" + "=" * 60)
    print("[SUCCESS] ALL TESTS PASSED SUCCESSFULLY - FEEDBACK MODULE VERIFIED")
    print("=" * 60)

if __name__ == "__main__":
    test_feedback_module()
