# database.py
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
import os

"""
Database config: supports local SQLite during dev and DATABASE_URL (Postgres) in production.

"""

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./financial_app.db")

# For postgres, SQLAlchemy expects the new style: postgresql://....
# Render's managed Postgres will already provide a proper URL.
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()
