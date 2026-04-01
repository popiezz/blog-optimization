from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Shopify
    SHOPIFY_STORE_URL: str
    SHOPIFY_ACCESS_TOKEN: str
    SHOPIFY_WEBHOOK_SECRET: str

    # SEMrush
    SEMRUSH_API_KEY: str
    SEMRUSH_DATABASE_FR: str = "ca"
    SEMRUSH_DATABASE_EN: str = "us"

    # SurferSEO
    SURFER_API_KEY: str
    SURFER_BASE_URL: str = "https://api.surferseo.com/v1"

    # Anthropic
    ANTHROPIC_API_KEY: str

    # Copyscape
    COPYSCAPE_USERNAME: str
    COPYSCAPE_API_KEY: str
    PLAGIARISM_THRESHOLD: float = 15.0

    # Asana
    ASANA_ACCESS_TOKEN: str
    ASANA_PROJECT_GID: str
    ASANA_WEBHOOK_SECRET: Optional[str] = None
    ASANA_ASSIGNEE_GID: str

    # Serper (Google Search API for competitor research)
    SERPER_API_KEY: Optional[str] = None

    # Optional: only process articles from this specific Shopify blog ID
    # If unset, all draft article creates will be processed.
    SHOPIFY_BLOG_ID: Optional[str] = None

    # App
    APP_BASE_URL: str
    SECRET_KEY: str
    LOG_LEVEL: str = "INFO"

    # Admin endpoint
    ADMIN_USERNAME: str = "admin"
    ADMIN_PASSWORD: str

    # Pipeline config
    MAX_PIPELINE_RETRIES: int = 1
    SURFER_POLL_INTERVAL_SECONDS: int = 5
    SURFER_POLL_MAX_ATTEMPTS: int = 12


settings = Settings()

