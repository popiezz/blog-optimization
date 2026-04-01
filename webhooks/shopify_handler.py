import base64
import hashlib
import hmac
import json
import logging
from typing import Any, Dict

from config.settings import settings
from models.blog_run import AsyncSessionLocal, BlogRun, RunStatus
from pipeline.seo_pipeline import start_optimization_pipeline
from sqlalchemy.future import select

logger = logging.getLogger(__name__)


def validate_shopify_hmac(payload: bytes, hmac_header: str) -> bool:
    """
    Validates the Shopify HMAC signature to ensure the request is authentic.
    """
    if not settings.SHOPIFY_WEBHOOK_SECRET:
        logger.error("SHOPIFY_WEBHOOK_SECRET is not configured.")
        return False

    digest = hmac.new(
        settings.SHOPIFY_WEBHOOK_SECRET.encode("utf-8"),
        payload,
        hashlib.sha256
    ).digest()
    computed_hmac = base64.b64encode(digest).decode("utf-8")
    
    return hmac.compare_digest(computed_hmac, hmac_header)


async def handle_shopify_webhook(payload: bytes, hmac_header: str):
    """
    Processes the incoming Shopify article/create webhook.
    1. Validates the HMAC signature.
    2. Parses the article payload.
    3. Checks if the article is in 'draft' status.
    4. Triggers the SEO optimization pipeline with idempotency.
    """
    if not validate_shopify_hmac(payload, hmac_header):
        logger.warning("Invalid Shopify HMAC signature. Rejecting webhook.")
        return

    try:
        data = json.loads(payload.decode("utf-8"))
    except json.JSONDecodeError as e:
        logger.error(f"Failed to decode Shopify webhook payload: {e}")
        return

    article_id = str(data.get("id"))
    title = data.get("title")
    status = data.get("status")
    blog_id = str(data.get("blog_id"))

    logger.info(f"Received Shopify webhook for article {article_id}: '{title}' (status: {status})")

    # Only process articles that are in 'draft' status
    if status != "draft":
        logger.info(f"Article {article_id} is not in 'draft' status (status: {status}). Skipping.")
        return

    # Optional blog ID filter — ignore articles from other blog sections
    if settings.SHOPIFY_BLOG_ID and blog_id != settings.SHOPIFY_BLOG_ID:
        logger.info(
            f"Article {article_id} belongs to blog {blog_id}, "
            f"not the configured blog {settings.SHOPIFY_BLOG_ID}. Skipping."
        )
        return

    # Check idempotency: Have we already processed this article_id?
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(BlogRun).where(BlogRun.article_id == article_id))
        existing_run = result.scalars().first()
        
        if existing_run:
            logger.info(f"Article {article_id} already exists in database (status: {existing_run.status}). Skipping.")
            return

        # Create a new record to track this run
        new_run = BlogRun(
            article_id=article_id,
            blog_id=blog_id,
            title=title,
            status=RunStatus.PENDING,
            original_content=data.get("body_html", "")
        )
        session.add(new_run)
        await session.commit()
    
    logger.info(f"Triggering SEO pipeline for article {article_id}")
    await start_optimization_pipeline(article_id, blog_id, data)
