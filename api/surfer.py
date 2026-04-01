import asyncio
import logging
from typing import Any, Dict

import httpx

from config.settings import settings

logger = logging.getLogger(__name__)


def _headers() -> Dict[str, str]:
    return {"Authorization": f"Bearer {settings.SURFER_API_KEY}"}


def _json_headers() -> Dict[str, str]:
    return {**_headers(), "Content-Type": "application/json"}


# ---------------------------------------------------------------------------
# Low-level API calls
# ---------------------------------------------------------------------------

async def create_surfer_document(keyword: str, language: str) -> Dict[str, Any]:
    """Creates a new SurferSEO content editor document."""
    url = f"{settings.SURFER_BASE_URL}/content-editor"
    payload = {"keyword": keyword, "language": language}

    async with httpx.AsyncClient() as client:
        response = await client.post(url, headers=_json_headers(), json=payload)
        response.raise_for_status()
        return response.json()


async def update_surfer_content(doc_id: str, html_content: str) -> Dict[str, Any]:
    """Updates the HTML content of a Surfer document."""
    url = f"{settings.SURFER_BASE_URL}/content-editor/{doc_id}"
    async with httpx.AsyncClient() as client:
        response = await client.patch(
            url, headers=_json_headers(), json={"body_html": html_content}
        )
        response.raise_for_status()
        return response.json()


async def trigger_surfer_optimization(doc_id: str) -> Dict[str, Any]:
    """Triggers the async auto-optimize process for a document."""
    url = f"{settings.SURFER_BASE_URL}/content-editor/{doc_id}/optimize"
    async with httpx.AsyncClient() as client:
        response = await client.post(url, headers=_headers())
        response.raise_for_status()
        return response.json()


async def poll_surfer_score(doc_id: str) -> Dict[str, Any]:
    """
    Polls the Surfer API until optimization completes or 60s timeout is reached.
    Returns content_score, lsi_keywords, and suggested_headings.
    """
    url = f"{settings.SURFER_BASE_URL}/content-editor/{doc_id}"

    async with httpx.AsyncClient() as client:
        for attempt in range(settings.SURFER_POLL_MAX_ATTEMPTS):
            response = await client.get(url, headers=_headers())
            response.raise_for_status()
            data = response.json()

            if data.get("status") == "done":
                logger.info(
                    "SurferSEO doc %s optimized (attempt %d).", doc_id, attempt + 1
                )
                return {
                    "content_score": data.get("content_score", 0),
                    "lsi_keywords": data.get("lsi_keywords", []),
                    "suggested_headings": data.get("suggested_headings", []),
                }

            logger.debug(
                "SurferSEO doc %s status='%s' — waiting %ds (attempt %d/%d).",
                doc_id,
                data.get("status"),
                settings.SURFER_POLL_INTERVAL_SECONDS,
                attempt + 1,
                settings.SURFER_POLL_MAX_ATTEMPTS,
            )
            await asyncio.sleep(settings.SURFER_POLL_INTERVAL_SECONDS)

    raise TimeoutError(
        f"SurferSEO auto-optimize timed out after "
        f"{settings.SURFER_POLL_MAX_ATTEMPTS * settings.SURFER_POLL_INTERVAL_SECONDS}s "
        f"for document {doc_id}"
    )


# ---------------------------------------------------------------------------
# High-level helpers used by the pipeline
# ---------------------------------------------------------------------------

async def get_initial_surfer_score(
    keyword: str, language: str, body_html: str
) -> Dict[str, Any]:
    """
    Creates a Surfer document, uploads content, triggers optimize, and polls.

    Returns:
        {
            "surfer_doc_id": str,
            "initial_score": float,
            "lsi_keywords": list[str],
            "suggested_headings": list[str],
        }
    """
    doc = await create_surfer_document(keyword, language)
    doc_id: str = doc.get("id") or doc.get("data", {}).get("id", "")

    if not doc_id:
        raise ValueError(f"SurferSEO did not return a document ID. Response: {doc}")

    await update_surfer_content(doc_id, body_html)
    await trigger_surfer_optimization(doc_id)
    result = await poll_surfer_score(doc_id)

    return {
        "surfer_doc_id": doc_id,
        "initial_score": result["content_score"],
        "lsi_keywords": result["lsi_keywords"],
        "suggested_headings": result["suggested_headings"],
    }


async def get_final_surfer_score(
    doc_id: str, optimized_html: str, initial_score: float
) -> Dict[str, Any]:
    """
    Updates an existing Surfer document with optimized content, re-triggers
    optimize, polls, and returns the score delta.

    Returns:
        {
            "initial_score": float,
            "final_score": float,
            "score_delta": float,
            "score_delta_pct": float,
        }
    """
    await update_surfer_content(doc_id, optimized_html)
    await trigger_surfer_optimization(doc_id)
    result = await poll_surfer_score(doc_id)

    final_score: float = result["content_score"]
    score_delta = final_score - initial_score
    score_delta_pct = (score_delta / initial_score * 100) if initial_score else 0.0

    return {
        "initial_score": initial_score,
        "final_score": final_score,
        "score_delta": score_delta,
        "score_delta_pct": score_delta_pct,
    }
