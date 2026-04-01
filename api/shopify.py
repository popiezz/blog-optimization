import logging
from typing import Any, Dict, List, Optional

import httpx
from bs4 import BeautifulSoup

from config.settings import settings

logger = logging.getLogger(__name__)

_SHOPIFY_API_VERSION = "2024-01"


def _base_url() -> str:
    return f"https://{settings.SHOPIFY_STORE_URL}/admin/api/{_SHOPIFY_API_VERSION}"


def _headers() -> Dict[str, str]:
    return {"X-Shopify-Access-Token": settings.SHOPIFY_ACCESS_TOKEN}


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------

async def get_shopify_article(article_id: str) -> Dict[str, Any]:
    """Fetches a single article from Shopify by ID."""
    url = f"{_base_url()}/articles/{article_id}.json"
    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=_headers())
        response.raise_for_status()
        return response.json().get("article", {})


async def get_article_metafields(article_id: str) -> List[Dict[str, Any]]:
    """Fetches all metafields for a given article."""
    url = f"{_base_url()}/articles/{article_id}/metafields.json"
    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=_headers())
        response.raise_for_status()
        return response.json().get("metafields", [])


async def update_shopify_article(
    article_id: str, data: Dict[str, Any]
) -> Dict[str, Any]:
    """Updates an article's content and metadata in Shopify."""
    url = f"{_base_url()}/articles/{article_id}.json"
    headers = {**_headers(), "Content-Type": "application/json"}
    async with httpx.AsyncClient() as client:
        response = await client.put(url, headers=headers, json={"article": data})
        response.raise_for_status()
        return response.json().get("article", {})


async def update_article_metafield(
    article_id: str,
    namespace: str,
    key: str,
    value: str,
    value_type: str = "single_line_text_field",
) -> Dict[str, Any]:
    """Creates or updates a single metafield on an article."""
    url = f"{_base_url()}/articles/{article_id}/metafields.json"
    headers = {**_headers(), "Content-Type": "application/json"}
    payload = {
        "metafield": {
            "namespace": namespace,
            "key": key,
            "value": value,
            "type": value_type,
        }
    }
    async with httpx.AsyncClient() as client:
        response = await client.post(url, headers=headers, json=payload)
        response.raise_for_status()
        return response.json().get("metafield", {})


# ---------------------------------------------------------------------------
# High-level helper used by the pipeline
# ---------------------------------------------------------------------------

async def fetch_article_data(article_id: str) -> Dict[str, Any]:
    """
    Fetches article content + metafields and enriches with language detection.

    Returns:
        {
            "article_id": str,
            "blog_id": str,
            "title": str,
            "body_html": str,
            "language": "fr" | "en",
            "target_keyword": str | None,
        }
    """
    article = await get_shopify_article(article_id)
    metafields = await get_article_metafields(article_id)

    # Extract the seo.target_keyword metafield
    target_keyword: Optional[str] = None
    for mf in metafields:
        if mf.get("namespace") == "seo" and mf.get("key") == "target_keyword":
            target_keyword = mf.get("value") or None
            break

    # Detect language from plain text of body
    body_html = article.get("body_html") or ""
    language = _detect_language(body_html)

    return {
        "article_id": str(article.get("id", article_id)),
        "blog_id": str(article.get("blog_id", "")),
        "title": article.get("title", ""),
        "body_html": body_html,
        "language": language,
        "target_keyword": target_keyword,
    }


def _detect_language(body_html: str) -> str:
    """Returns 'fr' or 'en'; defaults to 'fr' on failure."""
    if not body_html:
        return "fr"
    try:
        from langdetect import DetectorFactory, detect

        DetectorFactory.seed = 0  # deterministic
        text = BeautifulSoup(body_html, "lxml").get_text(separator=" ", strip=True)
        detected = detect(text[:2000])  # limit to avoid slow detection on huge docs
        return detected if detected in ("fr", "en") else "fr"
    except Exception as exc:
        logger.warning("Language detection failed (%s). Defaulting to 'fr'.", exc)
        return "fr"
