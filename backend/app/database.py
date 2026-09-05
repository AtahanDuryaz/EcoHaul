import os
from typing import Generator

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

load_dotenv()

DATABASE_URL = os.getenv( #env den okuyor ki data leak olmasın
    "DATABASE_URL",
    "postgresql+psycopg://postgres:postgres@localhost:5432/ecohaul",
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True) #kopuk bağlantıyı belirlemek için ping atıyor
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db() -> Generator[Session, None, None]: #session end pointe yield ile ulaşıyoruz
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
