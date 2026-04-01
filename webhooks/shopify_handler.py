import base64
import hashlib
import hmac
import json
import logging
from typing import Any, Dict

from config.settings import settings
from models.blog_run import AsyncSessionLocal, BlogRun, RunStatus
from pipeline.seo_pipeline import start_optimization_pipeline
from api.shopify import get_article_metafields
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
    4. Checks for the seo.target_keyword metafield.
    5. Triggers the SEO optimization pipeline with idempotency.
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

    logger.info(f"[Article {article_id}] Received Shopify webhook: '{title}' (status: {status})")

    # Only process articles that are in 'draft' status
    if status != "draft":
        logger.info(f"[Article {article_id}] is not in 'draft' status (status: {status}). Skipping.")
        return

    # Check for the seo.target_keyword metafield
    try:
        metafields = await get_article_metafields(article_id)
        target_keyword = None
        # metafields is expected to be a List[Dict[str, Any]] as returned by get_article_metafields
        if isinstance(metafields, list):
            for mf in metafields:
                if isinstance(mf, dict) and mf.get("namespace") == "seo" and mf.get("key") == "target_keyword":
                    target_keyword = mf.get("value")
                    break
        else:
            logger.warning(f"[Article {article_id}] Unexpected metafields format received from Shopify API: {type(metafields)}")

        if not target_keyword:
            logger.warning(f"[Article {article_id}] Missing 'seo.target_keyword' metafield. Rejecting pipeline execution.")
            return

        # Add target_keyword to data so it's available in pipeline
        data["seo.target_keyword"] = target_keyword
        logger.info(f"[Article {article_id}] Found target keyword: '{target_keyword}'")
    except Exception as e:
        logger.error(f"[Article {article_id}] Failed to fetch metafields: {e}")
        return

    # Check idempotency: Have we already processed this article_id?
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(BlogRun).where(BlogRun.article_id == article_id))
        existing_run = result.scalars().first()
        
        if existing_run:
            logger.info(f"[Article {article_id}] already exists in database (status: {existing_run.status}). Skipping.")
            return

        # Create a new record to track this run
        new_run = BlogRun(
            article_id=article_id,
            blog_id=blog_id,
            title=title,
            target_keyword_input=target_keyword,
            status=RunStatus.PENDING,
            original_content=data.get("body_html", "")
        )
        session.add(new_run)
        await session.commit()
    
    logger.info(f"[Article {article_id}] Triggering SEO pipeline")
    await start_optimization_pipeline(article_id, blog_id, data)
