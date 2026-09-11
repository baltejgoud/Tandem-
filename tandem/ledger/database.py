"""SQLite database engine and session factory with Write-Ahead Logging (WAL)."""

from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from tandem.ledger.models import Base


def get_engine(db_path: str = "tandem_ledger.db"):
    """Create SQLite engine configured with crash-safe WAL mode."""
    # Ensure directory exists if path includes subdirectories
    path_obj = Path(db_path)
    if path_obj.parent and str(path_obj.parent) != ".":
        path_obj.parent.mkdir(parents=True, exist_ok=True)

    engine = create_engine(
        f"sqlite:///{db_path}",
        echo=False,
        connect_args={"timeout": 30.0},
    )

    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()

    return engine


def init_db(engine) -> None:
    """Create all ledger tables if they do not already exist."""
    Base.metadata.create_all(bind=engine)


def get_session_factory(engine) -> sessionmaker[Session]:
    """Return configured session factory."""
    return sessionmaker(bind=engine, expire_on_commit=False)


# Default application-wide engine and sessionmaker
from tandem.config import settings

_default_engine = get_engine(settings.tandem_db_path)
init_db(_default_engine)
SessionLocal = get_session_factory(_default_engine)


def get_db():
    """FastAPI dependency yielding database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
