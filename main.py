import logging
import secrets
from contextlib import asynccontextmanager
from typing import Any, Dict, List

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy.future import select

from config.settings import settings
from models.blog_run import AsyncSessionLocal, BlogRun, RunStatus, init_db
from webhooks.asana_handler import handle_asana_webhook
from webhooks.shopify_handler import handle_shopify_webhook

logging.basicConfig(level=settings.LOG_LEVEL)
logger = logging.getLogger(__name__)

http_basic = HTTPBasic()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    logger.info("Database initialised.")
    yield


app = FastAPI(
    title="SEO Blog Automation Pipeline",
    description="Automated SEO optimization for Shopify blog content",
    version="1.0.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Auth helper
# ---------------------------------------------------------------------------

def verify_admin(credentials: HTTPBasicCredentials = Depends(http_basic)) -> str:
    correct_username = secrets.compare_digest(
        credentials.username.encode(), settings.ADMIN_USERNAME.encode()
    )
    correct_password = secrets.compare_digest(
        credentials.password.encode(), settings.ADMIN_PASSWORD.encode()
    )
    if not (correct_username and correct_password):
        raise HTTPException(
            status_code=401,
            detail="Incorrect credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/health")
async def health_check() -> Dict[str, str]:
    """Simple health check for Railway monitoring."""
    return {"status": "healthy"}


# ---------------------------------------------------------------------------
# Shopify webhook
# ---------------------------------------------------------------------------

@app.post("/webhooks/shopify")
async def shopify_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_shopify_hmac_sha256: str = Header(None),
) -> Dict[str, str]:
    """
    Receives Shopify `articles/create` webhooks.
    Validates HMAC and delegates processing to a background task so Shopify
    receives a fast 200 OK.
    """
    if not x_shopify_hmac_sha256:
        logger.warning("Shopify webhook received without HMAC header.")
        raise HTTPException(status_code=401, detail="Missing HMAC header")

    payload = await request.body()
    background_tasks.add_task(handle_shopify_webhook, payload, x_shopify_hmac_sha256)
    return {"status": "received"}


# ---------------------------------------------------------------------------
# Asana webhook
# ---------------------------------------------------------------------------

@app.post("/webhooks/asana")
async def asana_webhook(
    request: Request,
    response: Response,
    background_tasks: BackgroundTasks,
    x_hook_signature: str = Header(None),
    x_hook_secret: str = Header(None),
) -> Dict[str, str]:
    """
    Receives Asana webhook events (story.added — comment added to a task).
    Handles the initial handshake and then delegates event processing.
    """
    # Asana initial handshake: echo the secret back in the response header
    if x_hook_secret:
        logger.info("Asana webhook handshake received.")
        response.headers["X-Hook-Secret"] = x_hook_secret
        return {"status": "handshake complete"}

    if not x_hook_signature:
        logger.warning("Asana webhook received without signature header.")
        raise HTTPException(status_code=401, detail="Missing signature header")

    payload = await request.body()
    background_tasks.add_task(handle_asana_webhook, payload, x_hook_signature)
    return {"status": "received"}


# ---------------------------------------------------------------------------
# Admin — run history
# ---------------------------------------------------------------------------

@app.get("/runs")
async def list_runs(
    _: str = Depends(verify_admin),
) -> List[Dict[str, Any]]:
    """
    Returns the last 50 pipeline runs. Protected by HTTP Basic Auth.
    """
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(BlogRun).order_by(BlogRun.created_at.desc()).limit(50)
        )
        runs = result.scalars().all()

    return [
        {
            "id": run.id,
            "article_id": run.article_id,
            "blog_id": run.blog_id,
            "title": run.title,
            "language": run.language,
            "status": run.status,
            "main_keyword": run.main_keyword,
            "target_keyword_input": run.target_keyword_input,
            "initial_surfer_score": run.initial_surfer_score,
            "final_surfer_score": run.final_surfer_score,
            "score_delta": run.score_delta,
            "score_delta_pct": run.score_delta_pct,
            "plagiarism_flagged": run.plagiarism_flagged,
            "plagiarism_max_similarity": run.plagiarism_max_similarity,
            "failure_reason": run.failure_reason,
            "asana_task_gid": run.asana_task_gid,
            "surfer_doc_id": run.surfer_doc_id,
            "created_at": run.created_at.isoformat() if run.created_at else None,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
            "duration_seconds": run.duration_seconds,
        }
        for run in runs
    ]


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
