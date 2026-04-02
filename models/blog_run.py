from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String, Text
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

from config.settings import settings

Base = declarative_base()


class RunStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    COMPLETED = "completed"
    REJECTED = "rejected"
    FAILED = "failed"


class BlogRun(Base):
    __tablename__ = "blog_runs"

    id = Column(Integer, primary_key=True, index=True)
    article_id = Column(String, index=True, unique=True, nullable=False)
    blog_id = Column(String, nullable=True)
    title = Column(String, nullable=True)
    language = Column(String(2), nullable=True)
    status = Column(SQLEnum(RunStatus), default=RunStatus.PENDING, nullable=False)

    # Keyword data
    target_keyword_input = Column(String, nullable=True)   # Raw value from metafield
    main_keyword = Column(String, nullable=True)           # SEMrush-validated keyword

    # Surfer scores
    initial_surfer_score = Column(Float, nullable=True)
    final_surfer_score = Column(Float, nullable=True)
    score_delta = Column(Float, nullable=True)
    score_delta_pct = Column(Float, nullable=True)

    # Plagiarism
    plagiarism_flagged = Column(Boolean, nullable=True)
    plagiarism_max_similarity = Column(Float, nullable=True)

    # Content storage
    original_content = Column(Text, nullable=True)
    optimized_content = Column(Text, nullable=True)         # Optimized body_html
    optimized_metadata = Column(Text, nullable=True)        # JSON blob of Claude output metadata

    # Failure
    failure_reason = Column(Text, nullable=True)

    # External references
    asana_task_gid = Column(String, index=True, nullable=True)
    surfer_doc_id = Column(String, nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime, nullable=True)
    duration_seconds = Column(Float, nullable=True)

    def __repr__(self) -> str:
        return f"<BlogRun(article_id='{self.article_id}', status='{self.status}')>"


# Normalize Railway's postgres:// scheme to the asyncpg async driver scheme
def _resolve_db_url(url: str) -> str:
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    if url.startswith("postgresql://") and "+asyncpg" not in url:
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


DATABASE_URL = _resolve_db_url(settings.DATABASE_URL)
engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
