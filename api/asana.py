import logging
from typing import Any, Dict, Optional

import httpx
from config.settings import settings

logger = logging.getLogger(__name__)


async def create_asana_task(
    title: str, notes: str, article_id: str
) -> Dict[str, Any]:
    """
    Creates an Asana task for manual content approval.
    """
    url = "https://app.asana.com/api/1.0/tasks"
    headers = {
        "Authorization": f"Bearer {settings.ASANA_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }

    payload = {
        "data": {
            "name": f"APPROVAL: {title}",
            "notes": notes,
            "projects": [settings.ASANA_PROJECT_GID],
            "assignee": settings.ASANA_ASSIGNEE_GID,
            "custom_fields": {
                # Add article_id to custom field if exists
                # settings.ASANA_ARTICLE_ID_GID: article_id
            }
        }
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(url, headers=headers, json=payload)
        response.raise_for_status()
        return response.json().get("data", {})


async def get_asana_task(task_gid: str) -> Dict[str, Any]:
    """
    Fetches a single Asana task's details.
    """
    url = f"https://app.asana.com/api/1.0/tasks/{task_gid}"
    headers = {"Authorization": f"Bearer {settings.ASANA_ACCESS_TOKEN}"}

    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers)
        response.raise_for_status()
        return response.json().get("data", {})


async def update_asana_task(task_gid: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Updates an existing Asana task.
    """
    url = f"https://app.asana.com/api/1.0/tasks/{task_gid}"
    headers = {
        "Authorization": f"Bearer {settings.ASANA_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }

    payload = {"data": data}

    async with httpx.AsyncClient() as client:
        response = await client.put(url, headers=headers, json=payload)
        response.raise_for_status()
        return response.json().get("data", {})
