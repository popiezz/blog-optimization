"""
Asana webhook handler.

Listens for `story.added` events (comments added to tasks).
Validates the HMAC-SHA256 signature, fetches the comment text, and routes
APPROVE / REJECT decisions to the pipeline orchestrator.
"""

import hashlib
import hmac
import json
import logging
from typing import Any, Dict

from api.asana import get_asana_story
from config.settings import settings
from pipeline.seo_pipeline import approve_optimization_run, reject_optimization_run

logger = logging.getLogger(__name__)


def validate_asana_signature(payload: bytes, signature: str) -> bool:
    """Validates the Asana HMAC-SHA256 webhook signature."""
    if not settings.ASANA_WEBHOOK_SECRET:
        # Secret is not set — allow through but log a warning.
        # This can happen during initial setup before the secret is captured.
        logger.warning(
            "ASANA_WEBHOOK_SECRET not configured; skipping signature validation. "
            "Set it to the secret echoed back during the handshake."
        )
        return True

    computed = hmac.new(
        settings.ASANA_WEBHOOK_SECRET.encode("utf-8"),
        payload,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(computed, signature)


async def handle_asana_webhook(payload: bytes, signature: str) -> None:
    """
    Processes incoming Asana webhook events.

    Only acts on `story` resources with action `added` (i.e. new comments).
    Fetches the comment text and checks for APPROVE or REJECT: <reason>.
    """
    if not validate_asana_signature(payload, signature):
        logger.warning("Invalid Asana webhook signature — rejecting event.")
        return

    try:
        data = json.loads(payload.decode("utf-8"))
    except json.JSONDecodeError as exc:
        logger.error("Failed to decode Asana webhook payload: %s", exc)
        return

    events: list = data.get("events", [])
    logger.info("Asana webhook: %d event(s) received.", len(events))

    for event in events:
        resource: Dict[str, Any] = event.get("resource", {})
        resource_type: str = resource.get("resource_type", "")
        action: str = event.get("action", "")

        # Only care about new comments (stories)
        if resource_type != "story" or action != "added":
            logger.debug(
                "Skipping event: resource_type=%s, action=%s", resource_type, action
            )
            continue

        story_gid: str = resource.get("gid", "")
        parent: Dict[str, Any] = event.get("parent", {})
        task_gid: str = parent.get("gid", "")

        if not story_gid or not task_gid:
            logger.warning("Story/task GID missing in Asana event; skipping.")
            continue

        logger.info("Processing comment story %s on task %s", story_gid, task_gid)

        # Fetch the comment text
        try:
            story = await get_asana_story(story_gid)
        except Exception as exc:
            logger.error("Failed to fetch Asana story %s: %s", story_gid, exc)
            continue

        comment_text: str = (story.get("text") or "").strip()

        if not comment_text:
            logger.debug("Empty comment on task %s — skipping.", task_gid)
            continue

        await _route_comment(task_gid, comment_text)


async def _route_comment(task_gid: str, comment_text: str) -> None:
    """Routes APPROVE / REJECT comment to the pipeline."""
    upper = comment_text.upper()

    if upper.startswith("APPROVE"):
        logger.info("APPROVE received for task %s — triggering approval.", task_gid)
        await approve_optimization_run(task_gid)

    elif upper.startswith("REJECT"):
        # Extract reason after "REJECT:" or "REJECT :"
        reason = comment_text[6:].lstrip(": ").strip() or "No reason provided."
        logger.info("REJECT received for task %s: %s", task_gid, reason)
        await reject_optimization_run(task_gid, reason)

    else:
        logger.debug(
            "Comment on task %s does not start with APPROVE/REJECT — ignoring: '%s'",
            task_gid,
            comment_text[:80],
        )
