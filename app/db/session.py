"""DB 연결. DATABASE_URL 환경변수로 교체 가능 (기본: SQLite, 이후 PostgreSQL)."""
import os
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.db.models import Base

ROOT = Path(__file__).resolve().parents[2]
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{ROOT / 'data' / 'pokemon.db'}")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)


@event.listens_for(engine, "connect")
def _sqlite_foreign_keys(dbapi_conn, _):
    # SQLite는 기본적으로 외래키 검사를 하지 않으므로 켜준다
    if engine.dialect.name == "sqlite":
        dbapi_conn.execute("PRAGMA foreign_keys=ON")


def init_db() -> None:
    Base.metadata.create_all(engine)
