import logging

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request, Response

from config.settings import settings
from webhooks.asana_handler import handle_asana_webhook
from webhooks.shopify_handler import handle_shopify_webhook

# Configure logging
logging.basicConfig(level=settings.LOG_LEVEL)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="SEO Blog Automation Pipeline",
    description="Automated SEO optimization for Shopify blog content",
    version="0.1.0",
)


@app.get("/health")
async def health_check():
    """Simple health check endpoint for Railway monitoring."""
    return {"status": "healthy"}


@app.post("/webhooks/shopify")
async def shopify_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_shopify_hmac_sha256: str = Header(None),
):
    """
    Receives Shopify 'articles/create' webhooks.
    Validates HMAC and delegates processing to a background task.
    """
    if not x_shopify_hmac_sha256:
        logger.warning("Shopify webhook received without HMAC header.")
        raise HTTPException(status_code=401, detail="Missing HMAC header")

    payload = await request.body()

    # Process the webhook in the background to return 200 OK to Shopify quickly
    background_tasks.add_task(handle_shopify_webhook, payload, x_shopify_hmac_sha256)

    return {"status": "received"}


@app.post("/webhooks/asana")
async def asana_webhook(
    request: Request,
    response: Response,
    background_tasks: BackgroundTasks,
    x_hook_signature: str = Header(None),
    x_hook_secret: str = Header(None),
):
    """
    Receives Asana webhook events.
    Handles the handshake secret and delegates comment processing to a background task.
    """
    # Handle the initial handshake secret required by Asana
    if x_hook_secret:
        logger.info("Asana handshake secret received.")
        response.headers["X-Hook-Secret"] = x_hook_secret
        return {"status": "handshake complete"}

    if not x_hook_signature:
        logger.warning("Asana webhook received without signature header.")
        raise HTTPException(status_code=401, detail="Missing signature header")

    payload = await request.body()

    # Process the Asana event in the background
    background_tasks.add_task(handle_asana_webhook, payload, x_hook_signature)

    return {"status": "received"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
