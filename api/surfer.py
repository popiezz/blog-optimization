import httpx
import asyncio
from typing import Dict, Any, List
from config.settings import settings
import logging

logger = logging.getLogger(__name__)

async def create_surfer_document(keyword: str, language: str) -> Dict[str, Any]:
    """
    Creates a new SurferSEO document for a keyword and language.
    """
    url = f"{settings.SURFER_BASE_URL}/content-editor"
    headers = {"Authorization": f"Bearer {settings.SURFER_API_KEY}", "Content-Type": "application/json"}
    payload = {"keyword": keyword, "language": language}
    
    async with httpx.AsyncClient() as client:
        response = await client.post(url, headers=headers, json=payload)
        response.raise_for_status()
        return response.json()

async def update_surfer_content(doc_id: str, html_content: str) -> Dict[str, Any]:
    """
    Updates the HTML content of a Surfer document.
    """
    url = f"{settings.SURFER_BASE_URL}/content-editor/{doc_id}"
    headers = {"Authorization": f"Bearer {settings.SURFER_API_KEY}", "Content-Type": "application/json"}
    payload = {"body_html": html_content}
    
    async with httpx.AsyncClient() as client:
        response = await client.patch(url, headers=headers, json=payload)
        response.raise_for_status()
        return response.json()

async def trigger_surfer_optimization(doc_id: str) -> Dict[str, Any]:
    """
    Triggers the auto-optimize process for a document.
    """
    url = f"{settings.SURFER_BASE_URL}/content-editor/{doc_id}/optimize"
    headers = {"Authorization": f"Bearer {settings.SURFER_API_KEY}"}
    
    async with httpx.AsyncClient() as client:
        response = await client.post(url, headers=headers)
        response.raise_for_status()
        return response.json()

async def poll_surfer_score(doc_id: str) -> Dict[str, Any]:
    """
    Polls the Surfer API until the optimization is complete or timeout is reached.
    """
    url = f"{settings.SURFER_BASE_URL}/content-editor/{doc_id}"
    headers = {"Authorization": f"Bearer {settings.SURFER_API_KEY}"}
    
    async with httpx.AsyncClient() as client:
        for _ in range(settings.SURFER_POLL_MAX_ATTEMPTS):
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            data = response.json()
            
            # Assuming 'status' field exists and is "done" when complete
            if data.get("status") == "done":
                return {
                    "content_score": data.get("content_score", 0),
                    "lsi_keywords": data.get("lsi_keywords", []),
                    "suggested_headings": data.get("suggested_headings", [])
                }
            
            await asyncio.sleep(settings.SURFER_POLL_INTERVAL_SECONDS)
            
    raise TimeoutError(f"SurferSEO poll timed out for document {doc_id}")
