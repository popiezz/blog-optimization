# SEO Blog Automation Pipeline

Automated SEO optimization pipeline for company blog content. Triggered when a CRM manager creates a blog draft in Shopify — the pipeline runs end-to-end keyword research, competitor analysis, content restructuring, AI rewriting, and scoring before routing to the colleague for a single human approval gate.

**Volume:** 1–3 blogs/week  
**Languages:** FR + EN  
**Hosting:** Railway (always-on)  
**Status:** Active development

---

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [Full Pipeline Flow](#full-pipeline-flow)
- [Tech Stack](#tech-stack)
- [Repository Structure](#repository-structure)
- [API Integrations](#api-integrations)
- [Environment Variables](#environment-variables)
- [Claude Prompt Design](#claude-prompt-design)
- [Database Schema](#database-schema)
- [Setup & Deployment](#setup--deployment)
- [Development Phases](#development-phases)
- [Cost Estimates](#cost-estimates)
- [Known Risks & Mitigations](#known-risks--mitigations)
- [Conventions](#conventions)

---

## Architecture Overview

```
CRM Manager
    │
    │  Creates blog draft in Shopify
    │  (sets seo.target_keyword metafield)
    ▼
Shopify Webhook (articles/create, status=draft)
    │
    ▼
FastAPI App (Railway)
    │
    ▼
SEO Pipeline Orchestrator
    │
    ├─► [1]  Fetch draft from Shopify
    ├─► [2]  Keyword research via SEMrush
    ├─► [3]  Competitor research via Web Search
    ├─► [4]  Template restructure (structure only, no rewrite)
    ├─► [5]  SurferSEO — initial content score
    ├─► [6]  Claude — full SEO rewrite + metadata generation
    ├─► [7]  Plagiarism check
    ├─► [8]  SurferSEO — final content score
    ├─► [9]  Human approval gate via Asana  ◄── colleague acts here
    └─► [10] Write optimized draft back to Shopify + notify Asana
```

The pipeline fires automatically on draft creation. The colleague's only required action is approving or rejecting at step 9 — everything else is automated.

---

## Full Pipeline Flow

### Trigger — Shopify Webhook

**Event:** `articles/create`  
**Filter:** `status = draft`  
**Required custom metafield on article:** `seo.target_keyword` (string) — the primary keyword the CRM manager wants to target. This must be filled before saving the draft.

> The Shopify webhook is the sole trigger. Asana is used only for the approval gate (step 9) and the final notification (step 10). This removes the fragile title-matching dependency that would exist if Asana were used as the trigger.

---

### Step 1 — Fetch Blog Draft from Shopify

**Module:** `api/shopify.py`

- Receive `article_id` and `blog_id` from the webhook payload
- `GET /admin/api/2024-01/articles/{article_id}.json`
- Extract: `title`, `body_html`, `handle`, `blog_id`
- Detect language from content using `langdetect` — outputs `fr` or `en`
- Extract `target_keyword` from metafield `seo.target_keyword`
- Idempotency check: query DB — if `article_id` already has a completed run, skip and log

**Output:**

```json
{
  "article_id": "...",
  "blog_id": "...",
  "title": "...",
  "body_html": "...",
  "language": "fr|en",
  "target_keyword": "..."
}
```

---

### Step 2 — Keyword Research via SEMrush

**Module:** `api/semrush.py`

Using `target_keyword` as the seed (explicit human input — not inferred from title):

- `phrase_this` → volume, keyword difficulty, CPC for the seed keyword
- `phrase_related` → top 10 related keywords by volume/KD ratio
- `phrase_questions` → question-format keywords (strong H2 candidates)
- Select `main_keyword` = seed keyword validated against volume/KD data
- Select `secondary_keywords[]` = top 5 related by `(volume / KD)` score
- Select `question_keywords[]` = top 3 questions (for H2 suggestions)

**Output:**

```json
{
  "main_keyword": "...",
  "secondary_keywords": ["...", "..."],
  "question_keywords": ["...", "..."],
  "main_kw_volume": 0,
  "main_kw_difficulty": 0
}
```

> SEMrush runs **once**, outside any optimization loop. Its output is passed as static context to Claude and does not change between iterations.

---

### Step 3 — Competitor Research via Web Search

**Module:** `api/competitor_research.py`

- Search Google for `main_keyword` (language-aware: add locale signal for FR searches)
- Fetch top 3 organic results — skip ads, featured snippets, Wikipedia, Reddit, Quora
- For each result, extract: H1, all H2s, all H3s, word count, estimated keyword density
- Identify the dominant heading structure pattern across the 3 articles
- Extract top recurring H2 topics — these become structural signals passed to Claude

**Output:**

```json
{
  "competitor_urls": ["...", "...", "..."],
  "dominant_heading_structure": {
    "h2_topics": ["...", "..."],
    "avg_word_count": 0,
    "avg_h2_count": 0
  }
}
```

> This context informs Claude's restructuring decisions. Claude is explicitly instructed not to reproduce competitor phrasing — only their structural approach.

---

### Step 4 — Template Restructure (Structure Only, No Rewrite)

**Module:** `pipeline/restructure.py`

Apply the stored blog structure template to the raw draft **without modifying any text content**. This step corrects structural issues before scoring:

- Multiple H1s → collapse to single H1
- Missing H1 → generate from article title
- Skipped heading levels (e.g. H2 → H4 with no H3) → normalize hierarchy
- Enforce strict H1 → H2 → H3 nesting, no exceptions
- Tag introduction and conclusion sections for Claude's awareness

**Template file:** `prompts/structure_template.json` — editable by the colleague without developer involvement.

**Output:** Restructured `body_html` with corrected heading hierarchy, original text content unchanged.

---

### Step 5 — SurferSEO Initial Score

**Module:** `api/surfer.py`

- `POST /content-editor` — create new document with `main_keyword` and language
- Insert restructured `body_html`
- `POST /content-editor/{id}/optimize` — trigger auto-optimize (async)
- Poll `GET /content-editor/{id}` every 5s, max 60s timeout
- Extract: `content_score` (initial), `lsi_keywords[]`, `suggested_headings[]`

**Polling pattern:**

```python
for _ in range(12):  # max 60 seconds
    result = await get_surfer_document(doc_id)
    if result["status"] == "done":
        return result
    await asyncio.sleep(5)
raise TimeoutError("SurferSEO auto-optimize timeout after 60s")
```

**Output:**

```json
{
  "surfer_doc_id": "...",
  "initial_score": 0,
  "lsi_keywords": ["...", "..."],
  "suggested_headings": ["...", "..."]
}
```

---

### Step 6 — Claude Rewrite + Metadata Generation

**Module:** `api/claude_ai.py`  
**Model:** `claude-sonnet-4-20250514`  
**Max tokens:** 4000

Claude receives all upstream context in a single structured prompt and produces the fully optimized blog plus all metadata in one JSON response.

**Input to Claude:**

```json
{
  "title": "...",
  "body_html": "...",
  "language": "fr|en",
  "main_keyword": "...",
  "secondary_keywords": ["..."],
  "lsi_keywords": ["..."],
  "question_keywords": ["..."],
  "suggested_headings": ["..."],
  "competitor_heading_structure": {
    "h2_topics": ["..."],
    "avg_word_count": 0
  }
}
```

**Expected JSON output:**

```json
{
  "optimized_html": "...",
  "title_tag": "...",
  "meta_description": "...",
  "slug": "...",
  "og_title": "...",
  "og_description": "...",
  "schema_markup": {},
  "alt_texts": { "image_src": "alt text" },
  "internal_link_suggestions": [
    { "location": "paragraph about X", "suggested_topic": "..." }
  ],
  "changes_summary": "..."
}
```

**Error handling:** Wrap JSON parse in `try/except`. If invalid JSON is returned, retry once with an explicit correction prompt. If the second attempt fails, mark the run as `failed` in DB and notify the colleague via Asana.

---

### Step 7 — Plagiarism Check

**Module:** `api/plagiarism.py`

Before writing anything to Shopify, run a similarity check against the competitor URLs identified in step 3.

- Use Copyscape API (`POST https://www.copyscape.com/api/`)
- Acceptable similarity threshold: **< 15%** against any single source
- If threshold exceeded: flag in the run log, add a warning to the Asana approval comment
- Does **not** block the pipeline — routes to approval gate with a warning flag visible to the colleague

---

### Step 8 — SurferSEO Final Score

**Module:** `api/surfer.py` (reused)

- Update the existing SurferSEO document (`surfer_doc_id` from step 5) with `optimized_html`
- Re-trigger auto-optimize and poll
- Extract final `content_score`
- Calculate `score_delta = final_score - initial_score`
- Calculate `score_delta_pct = (score_delta / initial_score) * 100`

**Output:**

```json
{
  "initial_score": 0,
  "final_score": 0,
  "score_delta": 0,
  "score_delta_pct": 0.0
}
```

> v1 does not include an automated re-optimization loop. A single Claude pass is used to validate the pipeline and establish score delta baselines. If deltas are consistently below expectations after 10+ real runs, a loop with a configurable iteration cap and cost ceiling will be introduced in v2.

---

### Step 9 — Human Approval Gate via Asana

**Module:** `api/asana.py`

Create a task in the Asana blog project and post the full optimization report as a comment:

```
✅ SEO Pipeline Complete — Awaiting Approval

📄 Article: {title}
🔑 Main Keyword: {main_keyword} (Vol: {volume}, KD: {kd})
📊 SurferSEO Score: {initial_score} → {final_score} (+{delta_pct}%)
🌐 Competitors analyzed: {urls}
⚠️  Plagiarism flag: YES / NO ({max_similarity}% max similarity)

Changes made:
{changes_summary}

Internal link suggestions:
{internal_link_suggestions}

👉 Reply "APPROVE" to write optimized content to Shopify draft
👉 Reply "REJECT: [reason]" to discard and notify original author
```

- Assign task to colleague
- Set due date = today + 1 business day
- Pipeline pauses here and waits for the Asana comment webhook

**Webhook listener:** `webhooks/asana_handler.py`

- Listens for `task.comment_added` on the blog project
- Validates HMAC-SHA256 signature on `X-Hook-Signature` header
- Parses comment text:
  - `APPROVE` → proceed to step 10
  - `REJECT: [reason]` → notify original author, log rejection reason, close run

---

### Step 10 — Write Back to Shopify + Final Asana Notification

**Module:** `api/shopify.py` + `api/asana.py`

**Shopify write-back** (`PUT /admin/api/2024-01/articles/{article_id}.json`):

- `body_html` → optimized content
- `title` → `title_tag` value from Claude output
- `handle` → `slug` value from Claude output
- Metafields: `meta_description`, `og_title`, `og_description`, `schema_markup`, `alt_texts`
- Status remains `draft` — colleague publishes manually after final review

**Asana final notification:**

- Add comment: "✅ Shopify draft updated — ready for final review and publish"
- Mark task complete or move to "Ready to Publish" section

**DB write:**

- `INSERT blog_run` with all scores, keywords, timestamps, `status = completed`

---

## Tech Stack

| Layer              | Choice                    | Reason                                                             |
| ------------------ | ------------------------- | ------------------------------------------------------------------ |
| Language           | Python 3.11               | Rich async ecosystem, all required API clients available           |
| Web framework      | FastAPI                   | Async-native, auto Swagger docs, clean webhook handling            |
| Hosting            | Railway.app               | GitHub push deploy, env vars UI, persistent process, built-in logs |
| Database           | SQLite + SQLAlchemy       | Sufficient for 1–3 blogs/week; zero ops overhead                   |
| Task queue         | asyncio + BackgroundTasks | No Redis/Celery needed at this volume                              |
| HTTP client        | httpx (async)             | Consistent async HTTP across all API modules                       |
| Language detection | langdetect                | Lightweight, accurate for FR/EN                                    |
| Testing            | pytest + pytest-asyncio   | Standard Python async test stack                                   |

---

## Repository Structure

```
seo-blog-automation/
│
├── README.md
├── .env.example
├── .gitignore
├── requirements.txt
├── railway.toml
├── main.py                        # FastAPI entry point + webhook routes
│
├── config/
│   └── settings.py                # Pydantic BaseSettings — loads all env vars
│
├── api/
│   ├── shopify.py                 # GET draft / PUT optimized article
│   ├── semrush.py                 # Keyword research
│   ├── surfer.py                  # Content editor create / optimize / poll / score
│   ├── claude_ai.py               # Structured prompt → JSON output
│   ├── competitor_research.py     # Web search → heading structure extraction
│   └── plagiarism.py              # Copyscape similarity check
│
├── webhooks/
│   ├── shopify_handler.py         # Validate Shopify HMAC + extract article payload
│   └── asana_handler.py           # Validate Asana HMAC + parse APPROVE/REJECT
│
├── pipeline/
│   ├── seo_pipeline.py            # Main orchestrator — calls all modules in sequence
│   └── restructure.py             # Template-based heading hierarchy normalization
│
├── models/
│   └── blog_run.py                # SQLAlchemy model for run history
│
├── prompts/
│   ├── seo_optimizer_fr.txt       # Claude system prompt — French
│   ├── seo_optimizer_en.txt       # Claude system prompt — English
│   ├── brand_voice_fr.txt         # Brand voice + tone guide — French
│   ├── brand_voice_en.txt         # Brand voice + tone guide — English
│   └── structure_template.json    # Blog heading structure template
│
└── logs/
    └── .gitkeep
```

---

## API Integrations

### Shopify Admin API

|                    |                                                                              |
| ------------------ | ---------------------------------------------------------------------------- |
| Auth               | `X-Shopify-Access-Token` header                                              |
| Base URL           | `https://{store}.myshopify.com/admin/api/2024-01`                            |
| Webhook trigger    | `articles/create` filtered by `status=draft`                                 |
| Endpoints used     | `GET /articles/{id}.json` · `PUT /articles/{id}.json`                        |
| Webhook validation | HMAC-SHA256 on `X-Shopify-Hmac-Sha256` header using `SHOPIFY_WEBHOOK_SECRET` |

**Required custom metafield on all blog drafts:**

- Namespace: `seo`
- Key: `target_keyword`
- Type: `single_line_text_field`
- Set by: CRM manager before saving the draft

---

### SEMrush API

|                |                                                       |
| -------------- | ----------------------------------------------------- |
| Auth           | `?key={api_key}` query param                          |
| Base URL       | `https://api.semrush.com`                             |
| SDK            | None — use `httpx` directly                           |
| Endpoints used | `phrase_this` · `phrase_related` · `phrase_questions` |
| Database param | `ca` for French content · `us` for English content    |

---

### SurferSEO API

|                |                                                                                            |
| -------------- | ------------------------------------------------------------------------------------------ |
| Auth           | `Authorization: Bearer {token}`                                                            |
| Base URL       | `https://api.surferseo.com/v1`                                                             |
| Endpoints used | `POST /content-editor` · `POST /content-editor/{id}/optimize` · `GET /content-editor/{id}` |
| Notes          | `optimize` endpoint is async — requires polling loop with 60s timeout                      |

> ⚠️ **Confirm API access before starting development.** SurferSEO API access is not included on standard plans. If unavailable, evaluate Clearscope or Frase as drop-in alternatives — both have accessible APIs and equivalent content scoring.

---

### Anthropic Claude API

|                |                                                                            |
| -------------- | -------------------------------------------------------------------------- |
| Auth           | `x-api-key` header                                                         |
| Model          | `claude-sonnet-4-20250514`                                                 |
| Max tokens     | 4000                                                                       |
| Prompt pattern | System prompt (SEO rules + brand voice) + User message (blog data as JSON) |
| Output format  | JSON only — no markdown, no preamble, no trailing text                     |

---

### Copyscape API

|           |                                          |
| --------- | ---------------------------------------- |
| Auth      | Username + API key in request body       |
| Base URL  | `https://www.copyscape.com/api/`         |
| Endpoint  | `POST /` with `o=csearch`                |
| Threshold | Flag run if any source match exceeds 15% |

---

### Asana API

|                    |                                                                |
| ------------------ | -------------------------------------------------------------- |
| Auth               | `Authorization: Bearer {PAT}`                                  |
| Role in pipeline   | Approval gate (step 9) and final notification (step 10) only   |
| Webhook event      | `task.comment_added` on blog project                           |
| Webhook validation | HMAC-SHA256 on `X-Hook-Signature` header                       |
| Endpoints used     | `POST /tasks` · `POST /tasks/{id}/stories` · `PUT /tasks/{id}` |

---

## Environment Variables

```bash
# Shopify
SHOPIFY_STORE_URL=your-store.myshopify.com
SHOPIFY_ACCESS_TOKEN=shpat_xxx
SHOPIFY_WEBHOOK_SECRET=xxx              # From Shopify webhook settings

# SEMrush
SEMRUSH_API_KEY=xxx
SEMRUSH_DATABASE_FR=ca                  # Keyword database for French content
SEMRUSH_DATABASE_EN=us                  # Keyword database for English content

# SurferSEO
SURFER_API_KEY=xxx
SURFER_BASE_URL=https://api.surferseo.com/v1

# Anthropic
ANTHROPIC_API_KEY=sk-ant-xxx

# Copyscape
COPYSCAPE_USERNAME=xxx
COPYSCAPE_API_KEY=xxx
PLAGIARISM_THRESHOLD=15                 # Max acceptable similarity % before flagging

# Asana
ASANA_ACCESS_TOKEN=xxx
ASANA_PROJECT_GID=xxx                   # GID of the blog project
ASANA_WEBHOOK_SECRET=xxx                # Set when registering the Asana webhook
ASANA_ASSIGNEE_GID=xxx                  # GID of the colleague who approves

# App
APP_BASE_URL=https://your-app.railway.app
SECRET_KEY=xxx                          # For securing internal endpoints
LOG_LEVEL=INFO

# Pipeline config
MAX_PIPELINE_RETRIES=1                  # Claude JSON parse retry count before failing
SURFER_POLL_INTERVAL_SECONDS=5
SURFER_POLL_MAX_ATTEMPTS=12             # 12 × 5s = 60s timeout
```

---

## Claude Prompt Design

### System Prompt Structure

The system prompt is loaded at runtime from `prompts/seo_optimizer_fr.txt` or `prompts/seo_optimizer_en.txt` depending on detected language, with `prompts/brand_voice_fr.txt` or `prompts/brand_voice_en.txt` appended.

```
Tu es un expert SEO on-page et rédacteur de contenu de marque. Tu reçois un blog
en [LANGUE] avec des données SEO complètes et des directives de voix de marque.
Tu retournes UNIQUEMENT un objet JSON valide, sans markdown, sans backticks,
sans commentaires, sans aucun texte avant ou après l'objet JSON.

=== RÈGLES DE STRUCTURE ===
- H1 unique contenant le mot-clé principal exact
- Mot-clé principal dans les 100 premiers mots
- Hiérarchie stricte : H1 → H2 → H3 (jamais de saut de niveau)
- Les H2 doivent couvrir les sujets identifiés dans competitor_heading_structure
  sans copier leur formulation exacte
- Minimum 1 H2 basé sur un question_keyword (format question)

=== RÈGLES DE CONTENU ===
- Densité mot-clé principal : 1–2% (ne pas dépasser)
- Intégrer les LSI keywords naturellement — jamais de bourrage
- Intégrer les secondary_keywords dans au moins 2 H2 ou sous-sections
- Paragraphes max 3–4 lignes
- Ne jamais inventer des faits — travailler uniquement avec le contenu fourni
- Marquer [INTERNAL LINK NEEDED: sujet] là où un lien interne serait pertinent
- Préserver la voix et le ton décrits dans les directives de marque ci-dessous
- NE PAS reproduire la formulation des concurrents

=== RÈGLES METADATA ===
- title_tag : 50–60 caractères, mot-clé principal en début
- meta_description : 150–160 caractères, incitative, mot-clé présent, appel à l'action
- slug : 3–5 mots en kebab-case, mot-clé inclus, sans stop words
- og_title : accrocheur pour le partage social, peut différer du title_tag
- schema_markup : BlogPosting JSON-LD complet
- alt_texts : descriptifs, mot-clé présent si naturel et pertinent

=== DIRECTIVES DE VOIX DE MARQUE ===
{brand_voice_content}
```

### User Message Structure

Assembled by `api/claude_ai.py` at runtime:

```json
{
  "title": "...",
  "body_html": "...",
  "language": "fr|en",
  "main_keyword": "...",
  "secondary_keywords": ["..."],
  "lsi_keywords": ["..."],
  "question_keywords": ["..."],
  "suggested_headings": ["..."],
  "competitor_heading_structure": {
    "h2_topics": ["..."],
    "avg_word_count": 0,
    "avg_h2_count": 0
  }
}
```

### Brand Voice Files

`prompts/brand_voice_fr.txt` and `prompts/brand_voice_en.txt` should include:

- Tone adjectives (e.g., "expert mais accessible, jamais condescendant")
- Words and phrases to always use
- Words and phrases to never use
- Target audience description
- 2–3 example sentences that represent the brand voice at its best

**Maintainer:** Marketing colleague — these files can be updated directly in the GitHub repo without any code changes. They are loaded fresh on every pipeline run.

---

## Database Schema

**Table: `blog_runs`**

| Column                      | Type       | Description                                                          |
| --------------------------- | ---------- | -------------------------------------------------------------------- |
| `id`                        | INTEGER PK | Auto-increment                                                       |
| `article_id`                | VARCHAR    | Shopify article ID                                                   |
| `blog_id`                   | VARCHAR    | Shopify blog ID                                                      |
| `title`                     | VARCHAR    | Blog title at time of run                                            |
| `language`                  | VARCHAR(2) | `fr` or `en`                                                         |
| `main_keyword`              | VARCHAR    | SEMrush-validated primary keyword                                    |
| `target_keyword_input`      | VARCHAR    | Raw keyword from Shopify metafield                                   |
| `initial_surfer_score`      | FLOAT      | Score before Claude rewrite                                          |
| `final_surfer_score`        | FLOAT      | Score after Claude rewrite                                           |
| `score_delta`               | FLOAT      | Absolute score change                                                |
| `score_delta_pct`           | FLOAT      | Percentage improvement                                               |
| `plagiarism_flagged`        | BOOLEAN    | True if similarity exceeded threshold                                |
| `plagiarism_max_similarity` | FLOAT      | Highest similarity percentage found                                  |
| `status`                    | VARCHAR    | `pending` · `awaiting_approval` · `approved` · `rejected` · `failed` |
| `failure_reason`            | TEXT       | Populated if status = `failed`                                       |
| `asana_task_gid`            | VARCHAR    | Links back to the Asana approval task                                |
| `surfer_doc_id`             | VARCHAR    | Links back to the SurferSEO document                                 |
| `created_at`                | DATETIME   | Pipeline start timestamp                                             |
| `completed_at`              | DATETIME   | Shopify write-back timestamp                                         |
| `duration_seconds`          | FLOAT      | Total pipeline wall-clock duration                                   |

**Admin endpoint:** `GET /runs` — basic auth protected, returns last 50 runs as JSON.

---

## Setup & Deployment

### Prerequisites

- Python 3.11+
- Railway account connected to this GitHub repo
- API keys for: Shopify, SEMrush, SurferSEO, Anthropic, Copyscape, Asana

### Local Development

```bash
# Clone and install
git clone git@github.com:your-org/seo-blog-automation.git
cd seo-blog-automation
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Fill in all values in .env

# Run locally
uvicorn main:app --reload --port 8000

# Verify
curl http://localhost:8000/health
```

### Register Shopify Webhook

Run once after first deploy:

```bash
curl -X POST https://your-store.myshopify.com/admin/api/2024-01/webhooks.json \
  -H "X-Shopify-Access-Token: {token}" \
  -H "Content-Type: application/json" \
  -d '{
    "webhook": {
      "topic": "articles/create",
      "address": "https://your-app.railway.app/webhooks/shopify",
      "format": "json"
    }
  }'
```

### Register Asana Webhook

Run once after first deploy:

```bash
curl -X POST https://app.asana.com/api/1.0/webhooks \
  -H "Authorization: Bearer {token}" \
  -H "Content-Type: application/json" \
  -d '{
    "data": {
      "resource": "{ASANA_PROJECT_GID}",
      "target": "https://your-app.railway.app/webhooks/asana",
      "filters": [{"resource_type": "story", "action": "added"}]
    }
  }'
```

### Railway Deployment

Push to `main` branch → Railway auto-deploys via the connected GitHub integration. All environment variables are managed in Railway's dashboard under Variables — never committed to the repo.

---

## Development Phases

### Phase 1 — Foundation (0.5 day)

- [ ] Repo structure + `.gitignore` + `.env.example` + `requirements.txt`
- [ ] FastAPI skeleton with `/health` endpoint
- [ ] `config/settings.py` with Pydantic BaseSettings
- [ ] Deploy to Railway, verify `/health` responds in prod

### Phase 2 — API Modules in Isolation (2 days)

Test each module independently with unit test scripts before wiring into the pipeline:

- [ ] `api/shopify.py` — fetch a real draft, test a PUT with dummy data
- [ ] `api/semrush.py` — keyword research on a real blog title
- [ ] `api/surfer.py` — create doc, trigger optimize, poll, extract LSI and score
- [ ] `api/claude_ai.py` — send a test blog, validate JSON output schema
- [ ] `api/competitor_research.py` — web search + heading extraction for a test keyword
- [ ] `api/plagiarism.py` — Copyscape test with a known-similar text pair

### Phase 3 — Webhook Handlers (0.5 day)

- [ ] `webhooks/shopify_handler.py` — HMAC validation + payload extraction
- [ ] Register Shopify webhook, create a test draft, confirm handler receives it
- [ ] `webhooks/asana_handler.py` — HMAC validation + APPROVE/REJECT parsing
- [ ] Register Asana webhook, test comment trigger end-to-end

### Phase 4 — Pipeline Orchestrator (1 day)

- [ ] `pipeline/restructure.py` — heading normalization against structure template
- [ ] `pipeline/seo_pipeline.py` — wire all modules in sequence
- [ ] Error handling: any step failure → log to DB + notify Asana + mark run `failed`
- [ ] End-to-end test with a real blog draft

### Phase 5 — Database + Admin (0.5 day)

- [ ] `models/blog_run.py` — SQLAlchemy model
- [ ] DB write at end of each run with all fields
- [ ] Idempotency check at pipeline start (skip if `article_id` already processed)
- [ ] `GET /runs` endpoint with basic auth

### Phase 6 — Validation & Prompt Tuning (1 day)

- [ ] Run 3 real blog drafts end-to-end
- [ ] Review Claude output quality — adjust system prompt and brand voice files as needed
- [ ] Verify all Shopify fields write correctly: `title_tag`, `meta_description`, `slug`, `og_*`, `schema_markup`
- [ ] Verify Asana approval flow works with real APPROVE/REJECT comment replies
- [ ] Document baseline score deltas across the 3 test runs

**Total estimated development time: ~5.5 days**

---

## Cost Estimates

Monthly estimates at 1–3 blogs/week (~10 blogs/month):

| Service             | Estimated Cost   | Notes                                            |
| ------------------- | ---------------- | ------------------------------------------------ |
| Railway.app         | ~$5/month        | Hobby plan, always-on                            |
| Claude API          | ~$3–6/month      | Sonnet, ~4k tokens/blog                          |
| SEMrush API         | Included in plan | Confirm API unit consumption against plan limits |
| SurferSEO API       | TBD              | Requires enterprise API access confirmation      |
| Copyscape API       | ~$0.30/month     | ~$0.03 per search × 10 blogs                     |
| Asana               | Included in plan | Standard webhooks                                |
| **Total app infra** | **~$8–12/month** | Excluding SurferSEO/SEMrush plan costs           |

---

## Known Risks & Mitigations

| Risk                                                  | Severity  | Mitigation                                                                                                                                 |
| ----------------------------------------------------- | --------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| SurferSEO API not available on current plan           | 🔴 High   | Confirm with SurferSEO before dev starts. Fallback: Clearscope or Frase API                                                                |
| Claude returns invalid JSON                           | 🟡 Medium | One automatic retry with a correction prompt; if still fails, mark run `failed` and notify Asana                                           |
| SurferSEO polling timeout                             | 🟡 Medium | 60s hard timeout with `TimeoutError`; log and continue with partial data                                                                   |
| Asana webhook fires duplicate events                  | 🟡 Medium | Idempotency check on `article_id` at pipeline start                                                                                        |
| CRM manager forgets to set `target_keyword` metafield | 🟡 Medium | Shopify handler checks for metafield presence; if missing, reject webhook with Asana notification instructing author to add it and re-save |
| Plagiarism similarity exceeds threshold               | 🟢 Low    | Does not block pipeline; visible as warning flag in Asana approval comment                                                                 |
| Shopify webhook fires on non-blog article create      | 🟢 Low    | Filter by `blog_id` — only process articles belonging to the designated blog section                                                       |

---

## Conventions

### CRM Manager Checklist (before saving a Shopify draft)

Every blog draft submitted for optimization must have:

1. **Status:** Draft
2. **Custom metafield `seo.target_keyword`:** The primary keyword to target (e.g., `chaussures de course femme`)
3. **Body content:** The complete, un-optimized text — the pipeline handles all SEO work

The blog title does not need to be SEO-optimized at submission time. The pipeline generates the final `title_tag` and `slug`.

### Colleague Approval Workflow

1. Receive Asana task assignment when pipeline completes
2. Review the optimization report in the task comment (scores, changes made, competitor URLs analyzed, plagiarism flag if any)
3. Optionally open the Shopify draft directly to review the output
4. Reply to the Asana task comment:
   - `APPROVE` → pipeline writes optimized content to the Shopify draft
   - `REJECT: [reason]` → run is discarded, original author is notified with the rejection reason
5. After approval, review the Shopify draft and publish manually

### Updating Prompt and Voice Files

The following files can be edited directly in GitHub without any code changes or redeployment — they are loaded at runtime:

| File                              | Purpose                            | Maintainer |
| --------------------------------- | ---------------------------------- | ---------- |
| `prompts/brand_voice_fr.txt`      | French brand tone and voice rules  | Marketing  |
| `prompts/brand_voice_en.txt`      | English brand tone and voice rules | Marketing  |
| `prompts/structure_template.json` | Blog heading structure template    | Marketing  |
| `prompts/seo_optimizer_fr.txt`    | Claude SEO rules — French          | Developer  |
| `prompts/seo_optimizer_en.txt`    | Claude SEO rules — English         | Developer  |

### Branch Strategy

- `main` → production (Railway auto-deploys on push)
- `dev` → active development
- `feature/{module-name}` → individual feature branches

Never push directly to `main`. Open a PR from `dev` → `main` for each release.
