import hashlib
import hmac
import json
import logging
from typing import Any, Dict, List

from config.settings import settings
from pipeline.seo_pipeline import approve_optimization_run

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
    2. Iterates through events to find task completion signals.
    3. Triggers the final 'approval' phase of the SEO pipeline.
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

        # Log identifying info for each event
        logger.debug(f"Event: resource_type={resource_type}, action={action}, task_gid={resource.get('gid')}")

        # Check for task completion: 'changed' action on the 'completed' field.
        # Note: Depending on the specific workflow, we might also look for a tag or a custom field.
        # Here we assume completing the task signifies approval.
        if (
            resource_type == "task" and
            action == "changed" and
            change.get("field") == "completed"
        ):
            task_gid = resource.get("gid")
            logger.info(f"Asana task {task_gid} marked as completed. Triggering pipeline approval.")

            # Trigger the pipeline to write back to Shopify
            await approve_optimization_run(task_gid)
