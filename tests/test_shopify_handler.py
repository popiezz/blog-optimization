"""
Tests for webhooks/shopify_handler.py — HMAC validation and webhook routing.
"""
import base64
import hashlib
import hmac
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Helper: build a valid HMAC for a given payload and secret
# ---------------------------------------------------------------------------

def _make_hmac(payload: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


# ---------------------------------------------------------------------------
# validate_shopify_hmac
# ---------------------------------------------------------------------------

def test_validate_shopify_hmac_returns_true_for_valid_signature():
    payload = b'{"id": 12345, "title": "Test"}'
    secret = "my_webhook_secret"
    valid_hmac = _make_hmac(payload, secret)

    with patch("webhooks.shopify_handler.settings") as s:
        s.SHOPIFY_WEBHOOK_SECRET = secret
        from webhooks.shopify_handler import validate_shopify_hmac
        assert validate_shopify_hmac(payload, valid_hmac) is True


def test_validate_shopify_hmac_returns_false_for_invalid_signature():
    payload = b'{"id": 12345}'
    with patch("webhooks.shopify_handler.settings") as s:
        s.SHOPIFY_WEBHOOK_SECRET = "correct_secret"
        from webhooks.shopify_handler import validate_shopify_hmac
        assert validate_shopify_hmac(payload, "wrong_hmac_value") is False


def test_validate_shopify_hmac_returns_false_when_secret_not_configured():
    with patch("webhooks.shopify_handler.settings") as s:
        s.SHOPIFY_WEBHOOK_SECRET = ""
        from webhooks.shopify_handler import validate_shopify_hmac
        assert validate_shopify_hmac(b"payload", "any_hmac") is False


def test_validate_shopify_hmac_returns_false_for_tampered_payload():
    original_payload = b'{"id": 12345}'
    tampered_payload = b'{"id": 99999}'
    secret = "webhook_secret"
    # HMAC computed for original, but we validate tampered
    valid_hmac = _make_hmac(original_payload, secret)

    with patch("webhooks.shopify_handler.settings") as s:
        s.SHOPIFY_WEBHOOK_SECRET = secret
        from webhooks.shopify_handler import validate_shopify_hmac
        assert validate_shopify_hmac(tampered_payload, valid_hmac) is False


# ---------------------------------------------------------------------------
# handle_shopify_webhook
# ---------------------------------------------------------------------------

def _make_payload(article_id=111, status="draft", blog_id=222, title="Test Article"):
    data = {
        "id": article_id,
        "title": title,
        "status": status,
        "blog_id": blog_id,
        "body_html": "<p>Content</p>",
    }
    payload_bytes = json.dumps(data).encode()
    return payload_bytes, data


@pytest.mark.asyncio
async def test_handle_webhook_rejects_invalid_hmac():
    payload, _ = _make_payload()

    with patch("webhooks.shopify_handler.validate_shopify_hmac", return_value=False), \
         patch("webhooks.shopify_handler.start_optimization_pipeline") as mock_pipeline:

        from webhooks.shopify_handler import handle_shopify_webhook
        await handle_shopify_webhook(payload, "bad_hmac")

    mock_pipeline.assert_not_called()


@pytest.mark.asyncio
async def test_handle_webhook_skips_non_draft_articles():
    payload, _ = _make_payload(status="published")

    with patch("webhooks.shopify_handler.validate_shopify_hmac", return_value=True), \
         patch("webhooks.shopify_handler.start_optimization_pipeline") as mock_pipeline:

        from webhooks.shopify_handler import handle_shopify_webhook
        await handle_shopify_webhook(payload, "valid_hmac")

    mock_pipeline.assert_not_called()


@pytest.mark.asyncio
async def test_handle_webhook_skips_wrong_blog_id():
    payload, _ = _make_payload(blog_id=222)

    with patch("webhooks.shopify_handler.validate_shopify_hmac", return_value=True), \
         patch("webhooks.shopify_handler.settings") as s, \
         patch("webhooks.shopify_handler.start_optimization_pipeline") as mock_pipeline:

        s.SHOPIFY_BLOG_ID = "999"  # different blog
        from webhooks.shopify_handler import handle_shopify_webhook
        await handle_shopify_webhook(payload, "valid_hmac")

    mock_pipeline.assert_not_called()


@pytest.mark.asyncio
async def test_handle_webhook_skips_duplicate_article_id():
    payload, _ = _make_payload(article_id=111)

    existing_run = MagicMock()
    existing_run.status = "awaiting_approval"

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = existing_run
    mock_session.execute = AsyncMock(return_value=mock_result)

    with patch("webhooks.shopify_handler.validate_shopify_hmac", return_value=True), \
         patch("webhooks.shopify_handler.settings") as s, \
         patch("webhooks.shopify_handler.AsyncSessionLocal", return_value=mock_session), \
         patch("webhooks.shopify_handler.start_optimization_pipeline") as mock_pipeline:

        s.SHOPIFY_BLOG_ID = None
        from webhooks.shopify_handler import handle_shopify_webhook
        await handle_shopify_webhook(payload, "valid_hmac")

    mock_pipeline.assert_not_called()


@pytest.mark.asyncio
async def test_handle_webhook_creates_blog_run_and_triggers_pipeline():
    payload, data = _make_payload(article_id=555, status="draft", blog_id=333)

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()

    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = None  # no existing run
    mock_session.execute = AsyncMock(return_value=mock_result)

    with patch("webhooks.shopify_handler.validate_shopify_hmac", return_value=True), \
         patch("webhooks.shopify_handler.settings") as s, \
         patch("webhooks.shopify_handler.AsyncSessionLocal", return_value=mock_session), \
         patch("webhooks.shopify_handler.start_optimization_pipeline", new_callable=AsyncMock) as mock_pipeline:

        s.SHOPIFY_BLOG_ID = None
        from webhooks.shopify_handler import handle_shopify_webhook
        await handle_shopify_webhook(payload, "valid_hmac")

    mock_session.add.assert_called_once()
    mock_session.commit.assert_called_once()
    mock_pipeline.assert_called_once_with("555", "333", data)


@pytest.mark.asyncio
async def test_handle_webhook_rejects_malformed_json():
    bad_payload = b"this is not json {"
    secret = "secret"
    valid_hmac = _make_hmac(bad_payload, secret)

    with patch("webhooks.shopify_handler.validate_shopify_hmac", return_value=True), \
         patch("webhooks.shopify_handler.start_optimization_pipeline") as mock_pipeline:

        from webhooks.shopify_handler import handle_shopify_webhook
        await handle_shopify_webhook(bad_payload, valid_hmac)

    mock_pipeline.assert_not_called()
