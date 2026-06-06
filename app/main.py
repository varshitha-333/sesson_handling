from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.database import engine, Base, verify_db_connection, SessionLocal
from app import crud, models
from app.config import settings
from app.routes import problems, sessions, users

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Skip database initialization if we are running in testing mode
    if not settings.TESTING:
        # 1. Verify connection to PostgreSQL on startup
        # This will fail and crash the application if connection cannot be established
        verify_db_connection()
        
        # 2. Create tables in PostgreSQL database
        Base.metadata.create_all(bind=engine)
        
        # 3. Seed initial problems into catalog
        db = SessionLocal()
        try:
            crud.seed_problems(db)
        finally:
            db.close()
        
    yield

app = FastAPI(
    title="Archie Backend",
    description="Python FastAPI backend for Archie",
    version="1.0.0",
    lifespan=lifespan
)

# CORS configuration to allow local/web clients to connect securely
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex="https?://.*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Root endpoint for health checking
@app.get("/")
def read_root():
    return {"status": "running", "service": "Archie Backend"}

# Mount the routes
app.include_router(problems.router)
app.include_router(sessions.router)
app.include_router(users.router)
