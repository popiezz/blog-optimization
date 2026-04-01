from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import Column, DateTime, Float, Boolean, Integer, String, Text, Enum as SQLEnum
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

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
    article_id = Column(String, index=True, unique=True)
    blog_id = Column(String)
    title = Column(String)
    status = Column(SQLEnum(RunStatus), default=RunStatus.PENDING)
    
    # Asana tracking
    asana_task_gid = Column(String, index=True, nullable=True)
    
    # SEO data
    target_keyword_input = Column(String, nullable=True)
    initial_surfer_score = Column(Float, nullable=True)
    final_surfer_score = Column(Float, nullable=True)
    score_delta = Column(Float, nullable=True)
    score_delta_pct = Column(Float, nullable=True)
    plagiarism_flagged = Column(Boolean, nullable=True)
    plagiarism_max_similarity = Column(Float, nullable=True)

    # Content storage
    original_content = Column(Text, nullable=True)
    optimized_content = Column(Text, nullable=True)
    
    # Run info
    failure_reason = Column(Text, nullable=True)
    duration_seconds = Column(Float, nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<BlogRun(article_id='{self.article_id}', status='{self.status}')>"

# Database setup (using SQLite for now as per GEMINI.md)
DATABASE_URL = "sqlite+aiosqlite:///./seo_blog.db"
engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
