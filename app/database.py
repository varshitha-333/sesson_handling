import sys
import logging
from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker
from app.config import settings

# Setup logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("backend.database")

DATABASE_URL = settings.DATABASE_URL

# Create the SQLAlchemy engine for PostgreSQL
connect_args = {}
if "postgresql" in DATABASE_URL:
    connect_args["connect_timeout"] = 15

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=300,
    connect_args=connect_args
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def verify_db_connection():
    logger.info("Verifying PostgreSQL database connection...")
    try:
        # Try to connect and run a simple query
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        logger.info("Successfully connected to the PostgreSQL database.")
    except Exception as e:
        logger.error(
            "\n"
            "========================================================================\n"
            "DATABASE CONNECTION ERROR:\n"
            f"Failed to connect to the PostgreSQL database at: {DATABASE_URL}\n"
            f"Error details: {str(e)}\n"
            "Please verify that your database server is running and the credentials in .env are correct.\n"
            "========================================================================"
        )
        # Re-raise to crash application startup as strictly required by user
        raise e
