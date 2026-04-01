import logging
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

import httpx
from config.settings import settings

logger = logging.getLogger(__name__)

_ASANA_BASE = "https://app.asana.com/api/1.0"


def _headers() -> Dict[str, str]:
    return {"Authorization": f"Bearer {settings.ASANA_ACCESS_TOKEN}"}


def _json_headers() -> Dict[str, str]:
    return {**_headers(), "Content-Type": "application/json"}


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------


async def create_asana_task(
    title: str,
    notes: str,
    due_on: Optional[str] = None,
) -> Dict[str, Any]:
    """Creates an Asana task in the configured blog project."""
    payload: Dict[str, Any] = {
        "data": {
            "name": title,
            "notes": notes,
            "projects": [settings.ASANA_PROJECT_GID],
            "assignee": settings.ASANA_ASSIGNEE_GID,
        }
    }
    if due_on:
        payload["data"]["due_on"] = due_on

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{_ASANA_BASE}/tasks", headers=_json_headers(), json=payload
        )
        response.raise_for_status()
        return response.json().get("data", {})


async def get_asana_task(task_gid: str) -> Dict[str, Any]:
    """Fetches a single Asana task."""
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{_ASANA_BASE}/tasks/{task_gid}", headers=_headers()
        )
        response.raise_for_status()
        return response.json().get("data", {})


async def update_asana_task(task_gid: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """Updates an existing Asana task."""
    async with httpx.AsyncClient() as client:
        response = await client.put(
            f"{_ASANA_BASE}/tasks/{task_gid}",
            headers=_json_headers(),
            json={"data": data},
        )
        response.raise_for_status()
        return response.json().get("data", {})


async def add_comment_to_task(task_gid: str, comment_text: str) -> Dict[str, Any]:
    """Adds a comment (story) to an Asana task."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{_ASANA_BASE}/tasks/{task_gid}/stories",
            headers=_json_headers(),
            json={"data": {"text": comment_text}},
        )
        response.raise_for_status()
        return response.json().get("data", {})


async def complete_task(task_gid: str) -> Dict[str, Any]:
    """Marks an Asana task as completed."""
    return await update_asana_task(task_gid, {"completed": True})


async def get_asana_story(story_gid: str) -> Dict[str, Any]:
    """Fetches a story (comment) by GID to read its text."""
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{_ASANA_BASE}/stories/{story_gid}", headers=_headers()
        )
        response.raise_for_status()
        return response.json().get("data", {})


# ---------------------------------------------------------------------------
# High-level helper used by the pipeline
# ---------------------------------------------------------------------------


def _next_business_day() -> str:
    """Returns the next business day (Mon–Fri) in ISO format."""
    d = date.today() + timedelta(days=1)
    while d.weekday() >= 5:  # 5=Sat, 6=Sun
        d += timedelta(days=1)
    return d.isoformat()


def _format_internal_links(suggestions: List[Dict[str, Any]]) -> str:
    if not suggestions:
        return "  None suggested."
    lines = []
    for s in suggestions:
        location = s.get("location", "")
        topic = s.get("suggested_topic", "")
        lines.append(f"  • Near '{location}': link to '{topic}'")
    return "\n".join(lines)


async def create_failure_task(
    title: str, article_id: str, reason: str
) -> Dict[str, Any]:
    """Creates an Asana task to alert the colleague of a pipeline failure."""
    notes = (
        f"The SEO pipeline failed for article '{title}' (ID: {article_id}).\n\n"
        f"Reason:\n{reason}\n\n"
        "Please investigate and re-trigger if needed."
    )
    return await create_asana_task(
        title=f"❌ SEO Pipeline Error — {title or article_id}",
        notes=notes,
    )


async def create_approval_task(
    *,
    article_id: str,
    title: str,
    main_keyword: str,
    main_kw_volume: int,
    main_kw_difficulty: float,
    initial_score: float,
    final_score: float,
    score_delta_pct: float,
    competitor_urls: List[str],
    plagiarism_flagged: bool,
    plagiarism_max_similarity: float,
    changes_summary: str,
    internal_link_suggestions: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Creates the Asana approval task with the full optimization report as the
    task description.  Returns the created task data (including its GID).
    """
    plagiarism_line = (
        f"⚠️  Plagiarism flag: YES ({plagiarism_max_similarity:.1f}% max similarity)"
        if plagiarism_flagged
        else f"✅ Plagiarism flag: NO ({plagiarism_max_similarity:.1f}% max similarity)"
    )

    competitor_line = ", ".join(competitor_urls) if competitor_urls else "N/A"
    delta_sign = "+" if score_delta_pct >= 0 else ""
    internal_links_formatted = _format_internal_links(internal_link_suggestions)

    notes = f"""\
✅ SEO Pipeline Complete — Awaiting Approval

📄 Article: {title}
🔑 Main Keyword: {main_keyword} (Vol: {main_kw_volume:,}, KD: {main_kw_difficulty:.0f})
📊 SurferSEO Score: {initial_score:.0f} → {final_score:.0f} ({delta_sign}{score_delta_pct:.1f}%)
🌐 Competitors analysed: {competitor_line}
{plagiarism_line}

Changes made:
{changes_summary}

Internal link suggestions:
{internal_links_formatted}

👉 Reply "APPROVE" to write optimised content to the Shopify draft
👉 Reply "REJECT: [reason]" to discard and notify the original author
"""

    task_title = f"SEO APPROVAL: {title}"
    return await create_asana_task(
        title=task_title,
        notes=notes,
        due_on=_next_business_day(),
    )
