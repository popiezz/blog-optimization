import hashlib
import hmac
import json
import logging
from typing import Any, Dict, List

from config.settings import settings
from pipeline.seo_pipeline import approve_optimization_run, reject_optimization_run
from api.asana import get_asana_story

logger = logging.getLogger(__name__)


def validate_asana_signature(payload: bytes, signature: str) -> bool:
    """
    Validates the Asana webhook signature using HMAC-SHA256.
    """
    if not settings.ASANA_WEBHOOK_SECRET:
        # If secret is not configured, we might be in initial setup or missing config
        logger.warning("ASANA_WEBHOOK_SECRET not set. Skipping signature validation.")
        return True

    computed_signature = hmac.new(
        settings.ASANA_WEBHOOK_SECRET.encode("utf-8"),
        payload,
        hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(computed_signature, signature)


async def handle_asana_webhook(payload: bytes, signature: str):
    """
    Processes incoming Asana webhook events.
    1. Validates the signature for authenticity.
    2. Iterates through events to find task comment added signals.
    3. Parses the comment text for "APPROVE" or "REJECT: [reason]".
    4. Triggers the appropriate approval or rejection phase of the SEO pipeline.
    """
    if not validate_asana_signature(payload, signature):
        logger.warning("Invalid Asana signature received. Rejecting event.")
        return

    try:
        data = json.loads(payload.decode("utf-8"))
    except json.JSONDecodeError as e:
        logger.error(f"Failed to decode Asana webhook payload: {e}")
        return

    events = data.get("events", [])
    logger.info(f"Received {len(events)} events from Asana.")

    for event in events:
        resource = event.get("resource", {})
        resource_type = resource.get("resource_type")
        action = event.get("action")
        change = event.get("change", {})

        parent = event.get("parent", {})
        task_gid = parent.get("gid") if parent.get("resource_type") == "task" else None

        # Log identifying info for each event
        logger.debug(f"Event: resource_type={resource_type}, action={action}, task_gid={task_gid}")

        # Check for task.comment_added
        if (
            resource_type == "story" and
            action == "added" and
            resource.get("resource_subtype") == "comment_added" and
            task_gid is not None
        ):
            story_gid = resource.get("gid")
            if not story_gid:
                logger.warning(f"Asana webhook event for story on task {task_gid} missing story gid.")
                continue

            # Fetch the story details to get the text
            try:
                story_data = await get_asana_story(story_gid)
                comment_text = story_data.get("text", "")
            except Exception as e:
                logger.error(f"Failed to fetch Asana story {story_gid}: {e}")
                continue

            logger.info(f"Asana comment added on task {task_gid}. Parsing content.")

            if comment_text.strip() == "APPROVE" or comment_text.strip().startswith("APPROVE"):
                logger.info(f"APPROVAL received for task {task_gid}. Triggering pipeline approval.")
                await approve_optimization_run(task_gid)
            elif comment_text.strip().startswith("REJECT:"):
                # Extract reason
                reason = comment_text.strip()[len("REJECT:"):].strip()
                logger.info(f"REJECTION received for task {task_gid} with reason: '{reason}'. Triggering pipeline rejection.")
                await reject_optimization_run(task_gid, reason)
            else:
                logger.debug(f"Comment on task {task_gid} ignored as it does not match APPROVE or REJECT: format.")
