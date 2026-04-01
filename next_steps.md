# Next Steps — SEO Blog Optimization Pipeline

## What Has Been Done

### Infrastructure & Deployment
- FastAPI application with lifespan database initialization
- Railway deployment configuration (`railway.toml`) with `uvicorn` entry point
- Health check endpoint (`GET /health`) for Railway monitoring
- SQLite database with `aiosqlite` for async I/O; `BlogRun` ORM model tracking every pipeline run end-to-end
- HTTP Basic Auth (constant-time comparison via `secrets.compare_digest`) on the admin `GET /runs` endpoint
- Environment variable management via `pydantic-settings` with all secrets externalized — nothing committed to the repo

### Webhook Layer
- **Shopify handler** (`webhooks/shopify_handler.py`): HMAC-SHA256 validation, `status=draft` filter, optional `SHOPIFY_BLOG_ID` filter, idempotency check (skips duplicate `article_id`)
- **Asana handler** (`webhooks/asana_handler.py`): HMAC-SHA256 signature validation, Asana handshake echo, `story.added` event filtering, APPROVE / REJECT comment routing
- Both handlers run as FastAPI `BackgroundTasks` so webhooks receive an immediate `200 OK`

### 10-Step Pipeline Orchestrator (`pipeline/seo_pipeline.py`)
1. Fetch article, detect language (`langdetect`), extract `seo.target_keyword` metafield
2. SEMrush keyword research (main keyword, 5 secondary, 3 question keywords)
3. Competitor research via Serper.dev + BeautifulSoup heading extraction
4. HTML heading normalization (structure only, no content change)
5. SurferSEO initial content score
6. Claude full SEO rewrite + metadata generation
7. Copyscape plagiarism check (non-blocking — surfaces as flag in approval task)
8. SurferSEO final score + delta calculation
9. Create Asana approval task with full optimization report
10. On APPROVE: write-back to Shopify (body, title, handle, metafields); on REJECT: mark run REJECTED

### API Integrations
| Module | Status |
|---|---|
| `api/shopify.py` | Article fetch, metafield read/write, article update |
| `api/semrush.py` | Keyword overview, related keywords, question keywords — all concurrent via `asyncio.gather` |
| `api/surfer.py` | Create doc, upload content, trigger optimize, poll with timeout, score delta |
| `api/claude_ai.py` | System prompt + brand voice loading, JSON extraction with fence stripping, retry logic |
| `api/competitor_research.py` | Serper search, page fetch + heading extraction, dominant structure aggregation |
| `api/plagiarism.py` | HTML-to-text strip, Copyscape similarity check, threshold comparison |
| `api/asana.py` | Task creation, comment posting, task completion, approval task formatting |

### Content Pipeline Logic
- **`pipeline/restructure.py`**: Ensures exactly one H1 (inserts from title if missing, demotes extras to H2); corrects skipped heading levels (e.g. H2 → H4); inserts `<!-- INTRODUCTION START/END -->` and `<!-- CONCLUSION START/END -->` HTML comments as Claude context markers
- **Prompt system**: Language-specific SEO system prompts (`prompts/seo_optimizer_{en,fr}.txt`) merged with brand voice files (`prompts/brand_voice_{en,fr}.txt`) at runtime — marketing can update tone without a redeploy
- **Keyword ranking**: Secondary keywords sorted by `volume / max(difficulty, 1)` ratio to maximize traffic while avoiding high-competition terms

### Run Tracking
`BlogRun` model captures: language, target keyword, main keyword, initial/final Surfer scores, delta, plagiarism flag, original and optimized content, Claude metadata blob, Asana task GID, failure reason, and timestamps.

Status lifecycle: `PENDING → PROCESSING → AWAITING_APPROVAL → APPROVED → COMPLETED` (or `REJECTED` / `FAILED`)

---

## What Remains To Be Done

### Before First Real Run
1. **Register Shopify webhook** — via Shopify Admin → Notifications → Webhooks, set URL to `{APP_BASE_URL}/webhooks/shopify`, topic `articles/create`
2. **Register Asana webhook** — one-time `POST` to Asana API targeting the approval project; capture the `X-Hook-Secret` echoed back and store it as `ASANA_WEBHOOK_SECRET` in Railway env vars
3. **Confirm SurferSEO API access** — the Content Editor API endpoint is not included on all plans; verify with SurferSEO support before going live
4. **Set `SHOPIFY_BLOG_ID`** — strongly recommended to avoid processing articles from unintended blog sections
5. **Validate all API keys in Railway** — do a dry run with a test draft article

### Short-Term Improvements
- **Structured logging** — replace `logging.basicConfig` with JSON-structured logs (e.g. `python-json-logger`) for better Railway log querying
- **Webhook retry handling** — Shopify retries failed webhook deliveries; the current idempotency check handles this for the DB record creation, but a failed background task leaves the run stuck at `PENDING`. Add a recovery mechanism (e.g. a `/runs/{id}/retry` endpoint)
- **Rate limiting** — add request-rate limiting on both webhook endpoints to prevent abuse
- **Prompt tuning** — after 3–5 real runs, review Claude output quality and adjust `seo_optimizer_{en,fr}.txt` and brand voice files as needed
- **Cost monitoring** — track SEMrush API unit consumption and Claude API token usage; set budget alerts in Railway/Anthropic dashboards

### Medium-Term
- **Admin UI** — the `GET /runs` endpoint returns raw JSON; a minimal HTML table view (even just a Jinja2 template) would be more useful for day-to-day monitoring
- **Re-run support** — currently a rejected or failed article can never be re-processed because the idempotency check blocks it on `article_id`. Add a reset/retry path
- **v2 optimization loop** — if Surfer score delta is below a threshold (e.g. < 10 points), flag the run for manual review rather than auto-creating the approval task
- **Schema markup metafield** — currently written as `value_type="json"` to a standard metafield; verify Shopify theme reads it correctly for structured data rendering

---

## Issues to Fix Before Using Real API Keys

### 🔴 Bug: `NameError` in `claude_ai.py` when `MAX_PIPELINE_RETRIES=0`

**File:** `api/claude_ai.py`, line 150

**Problem:** In Python 3, the `as` variable in an `except` clause is deleted when the block exits (to break reference cycles). The variable `first_error` is bound inside the `except` block but then referenced outside it:

```python
try:
    return _extract_json(raw_response)
except (json.JSONDecodeError, ValueError) as first_error:
    logger.warning(...)
# first_error is now deleted by Python 3

if settings.MAX_PIPELINE_RETRIES < 1:
    raise ValueError("...") from first_error  # ← NameError
```

**Condition:** Only triggers when `MAX_PIPELINE_RETRIES=0` AND Claude returns invalid JSON. The default is `MAX_PIPELINE_RETRIES=1` so it does not trigger on the happy path, but it is a latent crash.

**Fix:** Store the exception in a separate variable before the `except` block exits, or remove the `from first_error` chaining.

---

### 🟡 Security: Asana webhook accepts unauthenticated events if `ASANA_WEBHOOK_SECRET` is unset

**File:** `webhooks/asana_handler.py`, lines 24–31

**Problem:** If `ASANA_WEBHOOK_SECRET` is not configured, `validate_asana_signature` logs a warning and returns `True`, effectively accepting all incoming requests without validation. An attacker who can POST to `/webhooks/asana` could trigger spurious approval or rejection of runs.

**Fix:** Before switching to real API keys, ensure `ASANA_WEBHOOK_SECRET` is captured during webhook registration and set in Railway. Optionally, change the behavior to `return False` (reject) if the secret is unset.

---

### 🟡 Security: Missing HMAC header on Shopify webhook returns 401 in `main.py` but handler also logs rather than errors

The missing-header check is in `main.py` (raises `HTTPException 401`), which is correct. No change needed, but ensure this path is tested before going live.

---

### 🟡 Pipeline stuck at `PENDING` on background task failure

**File:** `webhooks/shopify_handler.py`, line 94

**Problem:** The `BlogRun` DB record is created (status=`PENDING`) in one session, then the session is closed, and `start_optimization_pipeline` is called. If `start_optimization_pipeline` crashes before it updates the status to `PROCESSING`, the run stays at `PENDING` indefinitely. The idempotency check then prevents any retry because `article_id` already exists.

**Fix:** Add a startup check or admin endpoint to detect and reset stale `PENDING` runs older than N minutes.

---

### 🟡 `SHOPIFY_BLOG_ID` unset = all blogs processed

If `SHOPIFY_BLOG_ID` is not set in production, every draft article across every Shopify blog (news, product updates, etc.) will trigger the pipeline, consuming SEMrush/SurferSEO/Claude API credits unnecessarily.

**Fix:** Set `SHOPIFY_BLOG_ID` in Railway environment variables before enabling the webhook.

---

### 🟡 SurferSEO plan access unconfirmed

The Content Editor API used in `api/surfer.py` may not be available on standard SurferSEO plans. If `create_surfer_document` returns a non-200 response, the pipeline fails at step 5 and creates an Asana failure alert. This will not cause data loss, but it will leave every run in `FAILED` status until the plan is upgraded or the integration is swapped out.

**Fix:** Confirm API access with SurferSEO before going live. The code is structured so the integration can be swapped (e.g. for Frase or Clearscope) by replacing `api/surfer.py` and the two calls in `seo_pipeline.py`.

---

### 🔴 Bug: `TypeError` in `restructure.py` when article HTML has no H1

**File:** `pipeline/restructure.py`, line 56

**Problem:** `_fix_h1s` calls `body.new_tag("h1")` to create a new H1 element when the article has none. However, `body` is the result of `soup.find("body")`, which returns a BeautifulSoup `Tag` object (lxml always wraps content in `<html><body>`). The `new_tag()` factory method only exists on the `BeautifulSoup` root object, not on `Tag` objects. When called on a `Tag`, BS4 interprets it as a child-element lookup, finds nothing, and returns `None`. Calling `None("h1")` raises `TypeError`.

This means Step 4 of the pipeline (heading normalization) will crash for any article that has no H1 heading.

**Fix:** Pass a reference to the root `soup` object into `_fix_h1s` so it can call `soup.new_tag("h1")`, or store the soup reference separately before narrowing to `body`.

---

### 🟢 Low severity: Claude model hardcoded in `claude_ai.py`

`_MODEL = "claude-sonnet-4-6"` is hardcoded. This is not a blocking issue but means upgrading to a new model requires a code change rather than an env var update. Consider moving it to `config/settings.py`.

---

### 🟢 Low severity: SQLite not suitable if volume increases

SQLite is sufficient for 1–3 articles/week. If usage grows to 10+/week or concurrent runs occur, SQLite's write-lock behavior may cause issues. Plan a migration to PostgreSQL (Railway supports it natively) if volume increases.
