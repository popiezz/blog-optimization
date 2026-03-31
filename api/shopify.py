import logging
from typing import Any, Dict, Optional

import httpx
from config.settings import settings

logger = logging.getLogger(__name__)


async def get_shopify_article(article_id: str) -> Dict[str, Any]:
    """
    Fetches a single article from Shopify by ID.
    """
    url = f"https://{settings.SHOPIFY_STORE_URL}/admin/api/2024-01/articles/{article_id}.json"
    headers = {"X-Shopify-Access-Token": settings.SHOPIFY_ACCESS_TOKEN}

    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers)
        response.raise_for_status()
        return response.json().get("article", {})


async def get_article_metafields(article_id: str) -> Dict[str, Any]:
    """
    Fetches all metafields for a given article.
    """
    url = f"https://{settings.SHOPIFY_STORE_URL}/admin/api/2024-01/articles/{article_id}/metafields.json"
    headers = {"X-Shopify-Access-Token": settings.SHOPIFY_ACCESS_TOKEN}

    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers)
        response.raise_for_status()
        return response.json().get("metafields", [])


async def update_shopify_article(
    article_id: str, data: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Updates an article's content and metadata in Shopify.
    """
    url = f"https://{settings.SHOPIFY_STORE_URL}/admin/api/2024-01/articles/{article_id}.json"
    headers = {
        "X-Shopify-Access-Token": settings.SHOPIFY_ACCESS_TOKEN,
        "Content-Type": "application/json",
    }

    payload = {"article": data}

    async with httpx.AsyncClient() as client:
        response = await client.put(url, headers=headers, json=payload)
        response.raise_for_status()
        return response.json().get("article", {})


async def update_article_metafield(
    article_id: str,
    namespace: str,
    key: str,
    value: str,
    value_type: str = "single_line_text_field",
) -> Dict[str, Any]:
    """
    Updates or creates a metafield for a specific article.
    """
    url = f"https://{settings.SHOPIFY_STORE_URL}/admin/api/2024-01/articles/{article_id}/metafields.json"
    headers = {
        "X-Shopify-Access-Token": settings.SHOPIFY_ACCESS_TOKEN,
        "Content-Type": "application/json",
    }

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
