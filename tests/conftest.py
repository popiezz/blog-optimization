"""
Shared test configuration and fixtures.

Environment variables must be set at module level (before any application
imports) because config/settings.py instantiates Settings() at import time.
"""
import os

# Must be set before any application module is imported
os.environ.update(
    {
        "SHOPIFY_STORE_URL": "https://test-store.myshopify.com",
        "SHOPIFY_ACCESS_TOKEN": "test_shopify_token",
        "SHOPIFY_WEBHOOK_SECRET": "test_shopify_secret",
        "SEMRUSH_API_KEY": "test_semrush_key",
        "SURFER_API_KEY": "test_surfer_key",
        "ANTHROPIC_API_KEY": "sk-ant-test",
        "COPYSCAPE_USERNAME": "test_user",
        "COPYSCAPE_API_KEY": "test_copyscape_key",
        "ASANA_ACCESS_TOKEN": "test_asana_token",
        "ASANA_PROJECT_GID": "1234567890",
        "ASANA_ASSIGNEE_GID": "9876543210",
        "APP_BASE_URL": "https://test.example.com",
        "SECRET_KEY": "test_secret_key_32bytes_padding!!",
        "ADMIN_PASSWORD": "test_admin_pass",
    }
)

import pytest
from unittest.mock import MagicMock


@pytest.fixture
def mock_settings(monkeypatch):
    """Provides a MagicMock settings object patched into all modules."""
    mock = MagicMock()
    mock.SHOPIFY_STORE_URL = "https://test-store.myshopify.com"
    mock.SHOPIFY_ACCESS_TOKEN = "test_shopify_token"
    mock.SHOPIFY_WEBHOOK_SECRET = "test_shopify_secret"
    mock.SHOPIFY_BLOG_ID = None
    mock.SEMRUSH_API_KEY = "test_semrush_key"
    mock.SEMRUSH_DATABASE_FR = "ca"
    mock.SEMRUSH_DATABASE_EN = "us"
    mock.SURFER_API_KEY = "test_surfer_key"
    mock.SURFER_BASE_URL = "https://api.surferseo.com/v1"
    mock.SURFER_POLL_INTERVAL_SECONDS = 0  # no sleep in tests
    mock.SURFER_POLL_MAX_ATTEMPTS = 3
    mock.ANTHROPIC_API_KEY = "sk-ant-test"
    mock.COPYSCAPE_USERNAME = "test_user"
    mock.COPYSCAPE_API_KEY = "test_copyscape_key"
    mock.PLAGIARISM_THRESHOLD = 15.0
    mock.ASANA_ACCESS_TOKEN = "test_asana_token"
    mock.ASANA_PROJECT_GID = "1234567890"
    mock.ASANA_ASSIGNEE_GID = "9876543210"
    mock.ASANA_WEBHOOK_SECRET = "test_asana_secret"
    mock.MAX_PIPELINE_RETRIES = 1
    mock.ADMIN_USERNAME = "admin"
    mock.ADMIN_PASSWORD = "test_admin_pass"

    for module_path in [
        "api.shopify.settings",
        "api.semrush.settings",
        "api.surfer.settings",
        "api.claude_ai.settings",
        "api.plagiarism.settings",
        "api.asana.settings",
        "api.competitor_research.settings",
        "webhooks.shopify_handler.settings",
        "webhooks.asana_handler.settings",
        "pipeline.seo_pipeline.settings",
    ]:
        monkeypatch.setattr(module_path, mock, raising=False)

    return mock
