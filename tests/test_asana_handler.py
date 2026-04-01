"""
Tests for webhooks/asana_handler.py — signature validation and comment routing.
"""
import hashlib
import hmac
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _make_asana_hmac(payload: bytes, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def _make_story_event(story_gid: str, task_gid: str) -> dict:
    return {
        "events": [
            {
                "action": "added",
                "resource": {"resource_type": "story", "gid": story_gid},
                "parent": {"gid": task_gid},
            }
        ]
    }


# ---------------------------------------------------------------------------
# validate_asana_signature
# ---------------------------------------------------------------------------

def test_validate_asana_signature_valid():
    payload = b'{"events": []}'
    secret = "asana_secret"
    valid_sig = _make_asana_hmac(payload, secret)

    with patch("webhooks.asana_handler.settings") as s:
        s.ASANA_WEBHOOK_SECRET = secret
        from webhooks.asana_handler import validate_asana_signature
        assert validate_asana_signature(payload, valid_sig) is True


def test_validate_asana_signature_invalid():
    payload = b'{"events": []}'
    with patch("webhooks.asana_handler.settings") as s:
        s.ASANA_WEBHOOK_SECRET = "correct_secret"
        from webhooks.asana_handler import validate_asana_signature
        assert validate_asana_signature(payload, "wrong_signature") is False


def test_validate_asana_signature_no_secret_allows_through():
    """When ASANA_WEBHOOK_SECRET is not set, validation passes with a warning."""
    with patch("webhooks.asana_handler.settings") as s:
        s.ASANA_WEBHOOK_SECRET = None
        from webhooks.asana_handler import validate_asana_signature
        assert validate_asana_signature(b"any payload", "any sig") is True


# ---------------------------------------------------------------------------
# _route_comment
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_route_comment_approve_calls_approve_run():
    with patch("webhooks.asana_handler.approve_optimization_run", new_callable=AsyncMock) as mock_approve, \
         patch("webhooks.asana_handler.reject_optimization_run", new_callable=AsyncMock) as mock_reject:

        from webhooks.asana_handler import _route_comment
        await _route_comment("task_gid_001", "APPROVE")

    mock_approve.assert_called_once_with("task_gid_001")
    mock_reject.assert_not_called()


@pytest.mark.asyncio
async def test_route_comment_approve_case_insensitive():
    with patch("webhooks.asana_handler.approve_optimization_run", new_callable=AsyncMock) as mock_approve:
        from webhooks.asana_handler import _route_comment
        await _route_comment("task_001", "approve")

    mock_approve.assert_called_once_with("task_001")


@pytest.mark.asyncio
async def test_route_comment_reject_with_reason():
    with patch("webhooks.asana_handler.reject_optimization_run", new_callable=AsyncMock) as mock_reject, \
         patch("webhooks.asana_handler.approve_optimization_run", new_callable=AsyncMock) as mock_approve:

        from webhooks.asana_handler import _route_comment
        await _route_comment("task_002", "REJECT: The tone is off-brand")

    mock_reject.assert_called_once_with("task_002", "The tone is off-brand")
    mock_approve.assert_not_called()


@pytest.mark.asyncio
async def test_route_comment_reject_without_reason_uses_default():
    with patch("webhooks.asana_handler.reject_optimization_run", new_callable=AsyncMock) as mock_reject:
        from webhooks.asana_handler import _route_comment
        await _route_comment("task_003", "REJECT")

    mock_reject.assert_called_once_with("task_003", "No reason provided.")


@pytest.mark.asyncio
async def test_route_comment_ignores_unrecognized_comments():
    with patch("webhooks.asana_handler.approve_optimization_run", new_callable=AsyncMock) as mock_approve, \
         patch("webhooks.asana_handler.reject_optimization_run", new_callable=AsyncMock) as mock_reject:

        from webhooks.asana_handler import _route_comment
        await _route_comment("task_004", "Looks good to me, but let me check with Sarah first.")

    mock_approve.assert_not_called()
    mock_reject.assert_not_called()


# ---------------------------------------------------------------------------
# handle_asana_webhook — full flow
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_handle_webhook_rejects_invalid_signature():
    payload = json.dumps(_make_story_event("story1", "task1")).encode()

    with patch("webhooks.asana_handler.validate_asana_signature", return_value=False), \
         patch("webhooks.asana_handler.approve_optimization_run", new_callable=AsyncMock) as mock_approve:

        from webhooks.asana_handler import handle_asana_webhook
        await handle_asana_webhook(payload, "bad_sig")

    mock_approve.assert_not_called()


@pytest.mark.asyncio
async def test_handle_webhook_skips_non_story_events():
    data = {
        "events": [
            {
                "action": "added",
                "resource": {"resource_type": "task", "gid": "task1"},
                "parent": {"gid": "project1"},
            }
        ]
    }
    payload = json.dumps(data).encode()

    with patch("webhooks.asana_handler.validate_asana_signature", return_value=True), \
         patch("webhooks.asana_handler.get_asana_story", new_callable=AsyncMock) as mock_story:

        from webhooks.asana_handler import handle_asana_webhook
        await handle_asana_webhook(payload, "sig")

    mock_story.assert_not_called()


@pytest.mark.asyncio
async def test_handle_webhook_skips_non_added_actions():
    data = {
        "events": [
            {
                "action": "changed",  # not "added"
                "resource": {"resource_type": "story", "gid": "story1"},
                "parent": {"gid": "task1"},
            }
        ]
    }
    payload = json.dumps(data).encode()

    with patch("webhooks.asana_handler.validate_asana_signature", return_value=True), \
         patch("webhooks.asana_handler.get_asana_story", new_callable=AsyncMock) as mock_story:

        from webhooks.asana_handler import handle_asana_webhook
        await handle_asana_webhook(payload, "sig")

    mock_story.assert_not_called()


@pytest.mark.asyncio
async def test_handle_webhook_routes_approve_comment():
    data = _make_story_event("story_abc", "task_xyz")
    payload = json.dumps(data).encode()

    with patch("webhooks.asana_handler.validate_asana_signature", return_value=True), \
         patch("webhooks.asana_handler.get_asana_story", new_callable=AsyncMock) as mock_story, \
         patch("webhooks.asana_handler.approve_optimization_run", new_callable=AsyncMock) as mock_approve:

        mock_story.return_value = {"text": "APPROVE"}
        from webhooks.asana_handler import handle_asana_webhook
        await handle_asana_webhook(payload, "valid_sig")

    mock_story.assert_called_once_with("story_abc")
    mock_approve.assert_called_once_with("task_xyz")


@pytest.mark.asyncio
async def test_handle_webhook_skips_empty_comment():
    data = _make_story_event("story_empty", "task_x")
    payload = json.dumps(data).encode()

    with patch("webhooks.asana_handler.validate_asana_signature", return_value=True), \
         patch("webhooks.asana_handler.get_asana_story", new_callable=AsyncMock) as mock_story, \
         patch("webhooks.asana_handler.approve_optimization_run", new_callable=AsyncMock) as mock_approve, \
         patch("webhooks.asana_handler.reject_optimization_run", new_callable=AsyncMock) as mock_reject:

        mock_story.return_value = {"text": "  "}
        from webhooks.asana_handler import handle_asana_webhook
        await handle_asana_webhook(payload, "sig")

    mock_approve.assert_not_called()
    mock_reject.assert_not_called()


@pytest.mark.asyncio
async def test_handle_webhook_continues_on_story_fetch_error():
    data = {"events": [
        {"action": "added", "resource": {"resource_type": "story", "gid": "s1"}, "parent": {"gid": "t1"}},
        {"action": "added", "resource": {"resource_type": "story", "gid": "s2"}, "parent": {"gid": "t2"}},
    ]}
    payload = json.dumps(data).encode()

    with patch("webhooks.asana_handler.validate_asana_signature", return_value=True), \
         patch("webhooks.asana_handler.get_asana_story", new_callable=AsyncMock) as mock_story, \
         patch("webhooks.asana_handler.approve_optimization_run", new_callable=AsyncMock) as mock_approve:

        # First fetch fails, second succeeds with APPROVE
        mock_story.side_effect = [Exception("Asana API error"), {"text": "APPROVE"}]
        from webhooks.asana_handler import handle_asana_webhook
        await handle_asana_webhook(payload, "sig")

    # Should still process the second event
    mock_approve.assert_called_once_with("t2")
