from datetime import datetime, timezone
from sqlalchemy import text
from sqlalchemy.orm import Session
from app import models, schemas


def _get_or_create_lookup(db: Session, table: str, name: str) -> int:
    """Return the integer id for a lookup-table row, inserting if absent.

    Works with any simple (id SERIAL PK, name TEXT UNIQUE) lookup table
    used by the normalized Neon schema (categories, companies, interview_rounds).
    Using raw SQL keeps this independent of SQLAlchemy model definitions for
    those tables.
    """
    row = db.execute(
        text(f"SELECT id FROM {table} WHERE name = :n"), {"n": name}
    ).fetchone()
    if row:
        return row[0]
    # Insert if not present (ON CONFLICT to handle races)
    result = db.execute(
        text(
            f"INSERT INTO {table} (name) VALUES (:n) "
            f"ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name "
            f"RETURNING id"
        ),
        {"n": name},
    ).fetchone()
    db.flush()  # make the ID visible within this transaction
    return result[0]


def get_problem(db: Session, problem_id: str):
    return db.query(models.Problem).filter(models.Problem.id == problem_id).first()


def create_problem(db: Session, problem: schemas.ProblemCreate, creator: str = "admin"):
    # Resolve normalized FK IDs required by the live Neon DB schema.
    # get-or-create so the caller doesn't need to know the lookup table contents.
    category_id       = _get_or_create_lookup(db, "categories",      problem.category)
    company_name      = problem.company or "Practice"
    company_id        = _get_or_create_lookup(db, "companies",        company_name)
    round_name        = problem.meta.interview_round or "Backend Round"
    interview_round_id = _get_or_create_lookup(db, "interview_rounds", round_name)

    db_problem = models.Problem(
        id=problem.id,
        title=problem.title,
        description=problem.description,
        requirements=problem.requirements,
        constraints=problem.constraints,
        difficulty=problem.difficulty.lower(),   # live DB: CHECK IN ('easy','medium','hard')
        category=problem.category,
        subcategory=problem.subcategory,
        estimated_time=problem.estimated_time,
        company=problem.company or "Practice",
        status=problem.status.lower(),           # normalise for consistency
        interview_round=problem.meta.interview_round,
        key_concepts=problem.meta.key_concepts,
        similar_problems=problem.meta.similar_problems,
        why_this_problem=problem.meta.why_this_problem,
        what_youll_learn=problem.meta.what_youll_learn,
        next_level_problems=problem.meta.next_level_problems,
        sources=problem.meta.sources,
        version=1,
        created_by=creator,
        updated_by=creator,
        # Normalized FK columns required by live Neon DB (NOT NULL).
        # Kept in sync with the text columns above.
        category_id=category_id,
        company_id=company_id,
        interview_round_id=interview_round_id,
        estimated_time_minutes=problem.estimated_time,
    )
    db.add(db_problem)

    # Write to audit log
    db_log = models.AuditLog(
        action="CREATE",
        target_id=problem.id,
        target_title=problem.title,
        performed_by=creator,
        details={
            "title": problem.title,
            "difficulty": problem.difficulty,
            "category": problem.category,
            "subcategory": problem.subcategory,
            "estimated_time": problem.estimated_time,
            "status": problem.status
        }
    )
    db.add(db_log)
    db.commit()
    db.refresh(db_problem)
    return db_problem

def update_problem(db: Session, problem_id: str, problem_update: schemas.ProblemUpdate, updater: str = "admin"):
    db_problem = db.query(models.Problem).filter(models.Problem.id == problem_id).first()
    if not db_problem:
        return None
    
    update_data = problem_update.model_dump(exclude_unset=True)
    old_values = {}
    new_values = {}
    
    for key, value in update_data.items():
        old_val = getattr(db_problem, key)
        if old_val != value:
            old_values[key] = old_val
            new_values[key] = value
            setattr(db_problem, key, value)
            
    if old_values:
        db_problem.version += 1
        db_problem.updated_by = updater
        db_problem.updated_at = datetime.now(timezone.utc)
        
        # Write to audit log
        db_log = models.AuditLog(
            action="UPDATE",
            target_id=problem_id,
            target_title=db_problem.title,
            performed_by=updater,
            details={
                "old": old_values,
                "new": new_values,
                "version_incremented_to": db_problem.version
            }
        )
        db.add(db_log)
        
    db.commit()
    db.refresh(db_problem)
    return db_problem

def delete_problem(db: Session, problem_id: str, performed_by: str = "admin"):
    db_problem = db.query(models.Problem).filter(models.Problem.id == problem_id).first()
    if not db_problem:
        return None
    
    title = db_problem.title
    db.delete(db_problem)
    
    # Write to audit log
    db_log = models.AuditLog(
        action="DELETE",
        target_id=problem_id,
        target_title=title,
        performed_by=performed_by,
        details={"message": f"Problem '{title}' (ID: {problem_id}) deleted permanently."}
    )
    db.add(db_log)
    db.commit()
    return db_problem

def get_audit_logs(db: Session, limit: int = 50, offset: int = 0):
    return db.query(models.AuditLog).order_by(models.AuditLog.created_at.desc()).offset(offset).limit(limit).all()

def get_user(db: Session, user_id: str):
    return db.query(models.User).filter(models.User.id == user_id).first()

def get_users(db: Session):
    return db.query(models.User).all()

def get_user_by_email(db: Session, email: str):
    return db.query(models.User).filter(models.User.email == email).first()

def get_user_by_google_id(db: Session, google_id: str):
    return db.query(models.User).filter(models.User.google_id == google_id).first()

def create_user(db: Session, user: schemas.UserCreate):
    db_user = models.User(
        id=user.id,
        name=user.name,
        email=user.email
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user

def create_session(db: Session, session_create: schemas.SessionCreate):
    # Check if a session already exists for this user and problem
    if session_create.user_id:
        # Auto-create the user if they don't exist yet to prevent foreign key errors
        user_exists = db.query(models.User).filter(models.User.id == session_create.user_id).first()
        if not user_exists:
            db_user = models.User(id=session_create.user_id)
            db.add(db_user)
            db.commit()

        existing = db.query(models.Session).filter(
            models.Session.user_id == session_create.user_id,
            models.Session.problem_id == session_create.problem_id
        ).first()
        if existing:
            return existing

    db_session = models.Session(
        problem_id=session_create.problem_id,
        user_id=session_create.user_id,
        status="active",
        history=[],
        canvas_snapshots=[]
    )
    db.add(db_session)
    db.commit()
    db.refresh(db_session)
    return db_session

def get_session(db: Session, session_id: str):
    return db.query(models.Session).filter(models.Session.id == session_id).first()

def get_sessions(db: Session, user_id: str = None, limit: int = None, offset: int = None):
    query = db.query(models.Session)
    if user_id:
        query = query.filter(models.Session.user_id == user_id)
    query = query.order_by(models.Session.created_at.desc())
    if offset is not None:
        query = query.offset(offset)
    if limit is not None:
        query = query.limit(limit)
    return query.all()

# --- Library features: ratings / bookmarks / recently viewed ---

def upsert_rating(db: Session, user_id: str, problem_id: str, rating: int):
    if not db.query(models.User).filter(models.User.id == user_id).first():
        db.add(models.User(id=user_id))
        db.flush()
    record = db.query(models.ProblemRating).filter_by(user_id=user_id, problem_id=problem_id).first()
    if record:
        record.rating = rating
    else:
        record = models.ProblemRating(user_id=user_id, problem_id=problem_id, rating=rating)
        db.add(record)
    db.flush()

    # Recompute denormalized aggregates on the problem
    from sqlalchemy import func
    avg, count = db.query(func.avg(models.ProblemRating.rating),
                          func.count(models.ProblemRating.id)) \
        .filter(models.ProblemRating.problem_id == problem_id).one()
    problem = db.query(models.Problem).filter(models.Problem.id == problem_id).first()
    problem.avg_rating = round(float(avg or 0), 2)
    problem.rating_count = int(count or 0)
    db.commit()
    return record

def toggle_bookmark(db: Session, user_id: str, problem_id: str) -> bool:
    if not db.query(models.User).filter(models.User.id == user_id).first():
        db.add(models.User(id=user_id))
        db.flush()
    problem = db.query(models.Problem).filter(models.Problem.id == problem_id).first()
    existing = db.query(models.Bookmark).filter_by(user_id=user_id, problem_id=problem_id).first()
    if existing:
        db.delete(existing)
        problem.bookmark_count = max(0, (problem.bookmark_count or 0) - 1)
        db.commit()
        return False
    db.add(models.Bookmark(user_id=user_id, problem_id=problem_id))
    problem.bookmark_count = (problem.bookmark_count or 0) + 1
    db.commit()
    return True

def touch_recently_viewed(db: Session, user_id: str, problem_id: str):
    if not db.query(models.User).filter(models.User.id == user_id).first():
        db.add(models.User(id=user_id))
        db.flush()
    record = db.query(models.RecentlyViewed).filter_by(user_id=user_id, problem_id=problem_id).first()
    if record:
        record.viewed_at = datetime.now(timezone.utc)
    else:
        db.add(models.RecentlyViewed(user_id=user_id, problem_id=problem_id))
    db.commit()

def seed_problems(db: Session):
    # Only seed if no problems exist in catalog
    if db.query(models.Problem).count() > 0:
        return

    sample_problems = [
        models.Problem(
            id="design-url-shortener",
            title="Design a URL Shortener",
            description="Design a system like TinyURL that takes a long URL and generates a short link.",
            requirements=[
                "Generate a unique short code for a given long URL.",
                "Redirect users to the original URL when they access the short code.",
                "Highly available and low latency redirection.",
                "Custom short links should be supported."
            ],
            constraints=[
                "100 million new URLs generated per month.",
                "10 billion URL redirections per month.",
                "Read-to-Write ratio is 100:1."
            ]
        ),
        models.Problem(
            id="design-parking-lot",
            title="Design a Parking Lot",
            description="Design an Object-Oriented/System architecture for a multi-level parking lot.",
            requirements=[
                "Support multiple sizes of parking spots (small, medium, large).",
                "Support multiple levels/floors.",
                "Track spot availability in real-time.",
                "Accept payments at exit gates or automated kiosks."
            ],
            constraints=[
                "10,000 parking spots capacity.",
                "Peak traffic of 500 arrivals/departures per hour.",
                "Support automated ticket generation."
            ]
        ),
        models.Problem(
            id="design-twitter",
            title="Design Twitter / Social Feed",
            description="Design a social network service where users can publish posts, follow others, and view feeds.",
            requirements=[
                "Publish new tweets to followers.",
                "Display a timeline/news feed of followed users.",
                "Support likes, retweets, and comments.",
                "High availability and low latency feed generation."
            ],
            constraints=[
                "300 daily active users daily.",
                "600 million tweets published per day.",
                "Average follower count: 200 users."
            ]
        ),
        models.Problem(
            id="design-youtube",
            title="Design YouTube / Video Streaming",
            description="Design a scalable video-sharing service like YouTube or Netflix.",
            requirements=[
                "Upload and convert videos into multiple resolutions.",
                "Stream videos seamlessly with variable bandwidth.",
                "Support likes, comments, and views count.",
                "Highly available CDN integration."
            ],
            constraints=[
                "50 million active users daily.",
                "10 million videos uploaded per day.",
                "High download bandwidth (petabytes of data daily)."
            ]
        ),
        models.Problem(
            id="design-uber",
            title="Design Uber / Ride-Hailing",
            description="Design a location-aware matching service like Uber or Lyft.",
            requirements=[
                "Real-time driver tracking.",
                "Match riders with nearby available drivers.",
                "Calculate ETA and route coordinates.",
                "Handle fare calculations and payments."
            ],
            constraints=[
                "10 million daily active riders.",
                "1 million active drivers.",
                "Location updates from drivers every 3 seconds."
            ]
        ),
        models.Problem(
            id="design-dropbox",
            title="Design Dropbox / Cloud Storage",
            description="Design a file storage and syncing service like Dropbox or Google Drive.",
            requirements=[
                "Upload, download, and delete files.",
                "Sync files across multiple devices.",
                "Support file versioning and history.",
                "Offline file edits and automatic syncing."
            ],
            constraints=[
                "500 million registered users.",
                "100 million active users daily.",
                "Average file size: 10 MB."
            ]
        ),
        models.Problem(
            id="design-whatsapp",
            title="Design WhatsApp / Chat Messenger",
            description="Design a secure, real-time instant messaging service like WhatsApp.",
            requirements=[
                "One-on-one and group messaging.",
                "Message delivery receipts (sent, delivered, read).",
                "Send media files (images, audio, videos).",
                "Support offline delivery and end-to-end encryption."
            ],
            constraints=[
                "2 billion monthly active users.",
                "100 billion messages sent daily.",
                "Low latency connection persistence."
            ]
        ),
        models.Problem(
            id="design-yelp",
            title="Design Yelp / Proximity Search",
            description="Design a location-based local search service like Yelp or Google Maps.",
            requirements=[
                "Add, update, and retrieve businesses profiles.",
                "Search for nearby businesses within a given radius.",
                "Support ratings, reviews, and photos.",
                "Highly responsive geo-searching."
            ],
            constraints=[
                "100 million daily active users.",
                "1 million businesses.",
                "Average search queries: 50,000 per second."
            ]
        ),
        models.Problem(
            id="design-ticketmaster",
            title="Design Ticketmaster / Ticket Booking",
            description="Design a high-concurrency ticket purchasing platform like Ticketmaster.",
            requirements=[
                "Browse events and search by city/date.",
                "Reserve seats temporarily for checkout.",
                "Purchase tickets securely.",
                "Handle high-concurrency booking for popular events."
            ],
            constraints=[
                "10 million daily active users.",
                "High peak demand (100,000 bookings/minute during pre-sales).",
                "Strict double-booking prevention."
            ]
        ),
        models.Problem(
            id="design-rate-limiter",
            title="Design a Rate Limiter",
            description="Design an API rate limiter to throttle incoming traffic and prevent abuse.",
            requirements=[
                "Limit requests based on IP or User ID.",
                "Support configurable rules (e.g. 100 req/min).",
                "Low latency check (< 2ms per API call).",
                "Highly available and scalable across distributed nodes."
            ],
            constraints=[
                "1 billion total API calls per day.",
                "Peak traffic: 50,000 queries per second.",
                "Minimum memory consumption per user rule."
            ]
        ),
        models.Problem(
            id="design-web-crawler",
            title="Design a Web Crawler",
            description="Design a scalable system that crawls the web, parses HTML, and indexes links.",
            requirements=[
                "Fetch web pages from a seed list of URLs.",
                "Parse page content to extract outbound links.",
                "Avoid duplicate crawls and circular loops.",
                "Politeness compliance (robot.txt checks)."
            ],
            constraints=[
                "Crawling budget: 1 billion pages per month.",
                "Raw HTML storage: petabytes of data.",
                "Distinguish dynamic and static pages."
            ]
        ),
        models.Problem(
            id="design-key-value-store",
            title="Design a Key-Value Store",
            description="Design a distributed, highly available Key-Value store similar to Cassandra or Dynamo.",
            requirements=[
                "Support put(key, value) and get(key) operations.",
                "High write throughput and low latency.",
                "Configurable consistency model (eventual vs strong).",
                "Scalable data partitioning."
            ],
            constraints=[
                "10 million operations per second.",
                "Data size: hundreds of terabytes.",
                "Zero single point of failure."
            ]
        ),
        models.Problem(
            id="design-notification-system",
            title="Design a Notification System",
            description="Design a highly available notification service supporting SMS, email, and mobile push notifications.",
            requirements=[
                "Support multi-channel notifications (Email, SMS, Mobile Push).",
                "Ensure at-least-once message delivery.",
                "Support user preferences (opt-outs, quiet hours).",
                "Scale to millions of events per hour."
            ],
            constraints=[
                "100 million active users.",
                "500 million notifications sent daily.",
                "SMS/Email delivery latency < 10 seconds."
            ]
        ),
        models.Problem(
            id="design-distributed-cache",
            title="Design a Distributed Cache",
            description="Design a distributed in-memory cache system similar to Redis or Memcached.",
            requirements=[
                "Support read/write caching operations.",
                "Provide configurable eviction policies (LRU, LFU, TTL).",
                "Consistent hashing to distribute cache keys.",
                "High throughput with sub-millisecond response."
            ],
            constraints=[
                "10 million queries per second.",
                "99.99% cache availability.",
                "Scale storage memory dynamically."
            ]
        ),
        models.Problem(
            id="design-api-gateway",
            title="Design an API Gateway",
            description="Design a centralized entry point proxy for routing, authentication, and logging.",
            requirements=[
                "Centralized endpoint routing to microservices.",
                "Validate user authentication and authorization token header.",
                "Log requests, metrics, and trace IDs.",
                "Perform request modification and header forwarding."
            ],
            constraints=[
                "500 million API calls daily.",
                "Sub-millisecond routing latency overhead.",
                "Handle dynamic service discovery changes."
            ]
        ),
        models.Problem(
            id="design-tinder",
            title="Design Tinder / Proximity Matchmaking",
            description="Design a matchmaking system supporting card swiping, profiles, and instant chat matches.",
            requirements=[
                "Show recommendation cards based on location, age, gender.",
                "Process swipes (likes/dislikes) in real-time.",
                "Create instant match when both users like each other.",
                "Support low latency push matches notifications."
            ],
            constraints=[
                "50 million active users daily.",
                "1 billion swiping interactions daily.",
                "Instant matcher latency < 100 milliseconds."
            ]
        ),
        models.Problem(
            id="design-e-commerce",
            title="Design Amazon Checkout / E-commerce",
            description="Design a reliable and scalable e-commerce inventory and checkout system.",
            requirements=[
                "Maintain accurate stock levels.",
                "Process shopping cart checkout transactions.",
                "Integrate secure payment transactions.",
                "Handle flash-sale peak booking spikes."
            ],
            constraints=[
                "100 million registered users.",
                "Peak checkout requests: 20,000 per second.",
                "No overselling of limited inventory."
            ]
        )
    ]

    # Sample meta enrichment for a few seeded problems (new catalog schema)
    seed_meta = {
        "design-url-shortener": {
            "company": "Google", "interview_round": "phone-screen",
            "key_concepts": ["Hashing", "Caching", "Database Sharding"],
            "similar_problems": ["design-rate-limiter"],
            "why_this_problem": "A classic warm-up that tests estimation, key generation and read-heavy scaling.",
            "what_youll_learn": ["Short-code generation strategies", "Read-heavy caching", "Redirect latency budgets"],
            "next_level_problems": ["design-twitter"],
            "sources": ["https://github.com/donnemartin/system-design-primer"],
        },
        "design-whatsapp": {
            "company": "Meta", "interview_round": "onsite",
            "key_concepts": ["WebSockets", "Message Queues", "Fan-out"],
            "similar_problems": ["design-notification-system"],
            "why_this_problem": "Tests real-time delivery, connection persistence and write-optimized storage.",
            "what_youll_learn": ["Delivery receipts", "Fan-out-on-write vs read", "E2E encryption basics"],
            "next_level_problems": ["design-youtube"],
            "sources": ["https://github.com/donnemartin/system-design-primer"],
        },
        "design-rate-limiter": {
            "company": "Stripe", "interview_round": "phone-screen",
            "key_concepts": ["Token Bucket", "Sliding Window", "Redis"],
            "similar_problems": ["design-api-gateway"],
            "why_this_problem": "Small surface area but deep tradeoffs — ideal for algorithmic system design.",
            "what_youll_learn": ["Rate limiting algorithms", "Distributed counters", "Low-latency checks"],
            "next_level_problems": ["design-distributed-cache"],
            "sources": ["https://github.com/donnemartin/system-design-primer"],
        },
    }

    for p in sample_problems:
        p.difficulty = "Medium"
        p.category = "System Design"
        p.estimated_time = 45
        p.status = "published"
        p.version = 1
        p.created_by = "system"
        p.updated_by = "system"
        for key, value in seed_meta.get(p.id, {}).items():
            setattr(p, key, value)
        db.add(p)
    db.commit()
