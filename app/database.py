import logging
from sqlalchemy import create_engine, text, inspect
from sqlalchemy.orm import declarative_base, sessionmaker
from app.config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("backend.database")

DATABASE_URL = settings.DATABASE_URL

connect_args = {}
engine_kwargs = dict(pool_pre_ping=True, pool_recycle=300)
if DATABASE_URL.startswith("postgresql"):
    connect_args["connect_timeout"] = 15
    engine_kwargs.update(pool_size=settings.DB_POOL_SIZE,
                         max_overflow=settings.DB_MAX_OVERFLOW)
elif DATABASE_URL.startswith("sqlite"):
    # Needed for FastAPI's threaded test client / dev usage
    connect_args["check_same_thread"] = False

engine = create_engine(DATABASE_URL, connect_args=connect_args, **engine_kwargs)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def verify_db_connection():
    logger.info("Verifying database connection...")
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        logger.info("Successfully connected to the database.")
    except Exception as e:
        logger.error(
            "\n"
            "========================================================================\n"
            "DATABASE CONNECTION ERROR:\n"
            "Failed to connect to the database.\n"
            f"Error details: {str(e)}\n"
            "Please verify that your database server is running and the credentials\n"
            "in .env / Railway variables are correct.\n"
            "========================================================================"
        )
        # Re-raise to crash application startup: a backend without a DB is useless
        raise e


def schema_sync():
    """Additive schema safety net for dev/preview environments.

    Creates missing tables and adds missing columns (with type + nullability,
    no data migration). Production releases should run `alembic upgrade head`;
    this exists so a fresh clone or preview deploy works with zero ops.
    """
    Base.metadata.create_all(bind=engine)

    inspector = inspect(engine)
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            existing_cols = {c["name"] for c in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing_cols:
                    continue
                col_type = column.type.compile(engine.dialect)
                ddl = f'ALTER TABLE {table.name} ADD COLUMN "{column.name}" {col_type}'
                # New columns must be nullable or defaulted for existing rows;
                # server-side defaults for simple scalar python defaults.
                if column.default is not None and getattr(column.default, "arg", None) is not None \
                        and isinstance(column.default.arg, (int, float, str, bool)):
                    default_val = column.default.arg
                    if isinstance(default_val, bool):
                        default_val = "TRUE" if default_val else "FALSE"
                    elif isinstance(default_val, str):
                        default_val = f"'{default_val}'"
                    ddl += f" DEFAULT {default_val}"
                logger.info("schema_sync: %s", ddl)
                conn.execute(text(ddl))
