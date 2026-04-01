"""
SEO Pipeline Orchestrator.

Wires all modules in sequence for the 10-step pipeline:

  1. Fetch draft from Shopify
  2. Keyword research via SEMrush
  3. Competitor research via web search
  4. Template restructure (heading normalisation only)
  5. SurferSEO — initial content score
  6. Claude — full SEO rewrite + metadata generation
  7. Plagiarism check via Copyscape
  8. SurferSEO — final content score
  9. Human approval gate via Asana
 10. Write optimised draft back to Shopify + notify Asana
"""

import json
import logging
from datetime import datetime
from typing import Any, Dict, List

from sqlalchemy.future import select

from api.asana import add_comment_to_task, complete_task, create_approval_task, create_failure_task
from api.claude_ai import run_seo_rewrite
from api.competitor_research import fetch_competitor_content
from api.plagiarism import check_plagiarism
from api.semrush import run_keyword_research
from api.shopify import fetch_article_data, update_article_metafield, update_shopify_article
from api.surfer import get_final_surfer_score, get_initial_surfer_score
from models.blog_run import AsyncSessionLocal, BlogRun, RunStatus
from pipeline.restructure import normalize_html_structure

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_run_by_article(session, article_id: str) -> BlogRun | None:
    result = await session.execute(
        select(BlogRun).where(BlogRun.article_id == article_id)
    )
    return result.scalars().first()


async def _get_run_by_task(session, task_gid: str) -> BlogRun | None:
    result = await session.execute(
        select(BlogRun).where(BlogRun.asana_task_gid == task_gid)
    )
    return result.scalars().first()


async def _fail_run(
    session,
    run: BlogRun,
    reason: str,
    notify_asana: bool = True,
) -> None:
    """Marks a run as FAILED in the DB and optionally creates an Asana alert."""
    run.status = RunStatus.FAILED
    run.failure_reason = reason
    await session.commit()
    logger.error("Pipeline FAILED for article %s: %s", run.article_id, reason)

    if notify_asana:
        try:
            await create_failure_task(
                title=run.title or "",
                article_id=run.article_id,
                reason=reason,
            )
        except Exception as exc:
            logger.error("Could not create Asana failure task: %s", exc)


# ---------------------------------------------------------------------------
# Step 10 helpers — Shopify write-back
# ---------------------------------------------------------------------------

async def _write_back_to_shopify(
    article_id: str,
    optimized_html: str,
    metadata: Dict[str, Any],
) -> None:
    """
    Updates the Shopify article with optimised content and all metadata.
    Status remains 'draft' — colleague publishes manually after final review.
    """
    # Core article fields
    article_data: Dict[str, Any] = {
        "body_html": optimized_html,
        "title": metadata.get("title_tag", ""),
        "handle": metadata.get("slug", ""),
    }
    await update_shopify_article(article_id, article_data)

    # Metafields — separate calls
    metafield_map = {
        ("seo", "meta_description"): metadata.get("meta_description", ""),
        ("seo", "og_title"): metadata.get("og_title", ""),
        ("seo", "og_description"): metadata.get("og_description", ""),
    }
    for (namespace, key), value in metafield_map.items():
        if value:
            try:
                await update_article_metafield(article_id, namespace, key, value)
            except Exception as exc:
                logger.warning(
                    "Failed to update metafield %s.%s: %s", namespace, key, exc
                )

    # Schema markup as JSON string metafield
    schema = metadata.get("schema_markup")
    if schema:
        try:
            await update_article_metafield(
                article_id,
                "seo",
                "schema_markup",
                json.dumps(schema, ensure_ascii=False),
                value_type="json",
            )
        except Exception as exc:
            logger.warning("Failed to write schema_markup metafield: %s", exc)


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

async def start_optimization_pipeline(
    article_id: str, blog_id: str, raw_data: Dict[str, Any]
) -> None:
    """
    Entry point called by the Shopify webhook handler.
    Runs all 10 steps; marks the run FAILED on any unhandled exception.
    """
    start_time = datetime.utcnow()
    logger.info("=== SEO pipeline starting for article %s ===", article_id)

    async with AsyncSessionLocal() as session:
        run = await _get_run_by_article(session, article_id)
        if run is None:
            logger.error("No BlogRun record found for article %s — aborting.", article_id)
            return

        try:
            # -------------------------------------------------------------------
            # Step 1 — Fetch article + language + target_keyword
            # -------------------------------------------------------------------
            run.status = RunStatus.PROCESSING
            await session.commit()

            article_data = await fetch_article_data(article_id)
            language: str = article_data["language"]
            target_keyword: str | None = article_data["target_keyword"]
            title: str = article_data["title"]
            body_html: str = article_data["body_html"]

            run.language = language
            run.target_keyword_input = target_keyword
            run.title = title  # refresh in case it was empty at webhook time
            await session.commit()

            if not target_keyword:
                await _fail_run(
                    session,
                    run,
                    "Missing seo.target_keyword metafield. "
                    "Please add it to the Shopify draft and re-save.",
                )
                return

            # -------------------------------------------------------------------
            # Step 2 — Keyword research via SEMrush
            # -------------------------------------------------------------------
            keyword_data = await run_keyword_research(target_keyword, language)
            run.main_keyword = keyword_data["main_keyword"]
            await session.commit()

            # -------------------------------------------------------------------
            # Step 3 — Competitor research via web search
            # -------------------------------------------------------------------
            competitor_data = await fetch_competitor_content(
                keyword_data["main_keyword"], language
            )

            # -------------------------------------------------------------------
            # Step 4 — Heading normalisation (no content rewrite)
            # -------------------------------------------------------------------
            restructured_html = normalize_html_structure(body_html, title)

            # -------------------------------------------------------------------
            # Step 5 — SurferSEO initial score
            # -------------------------------------------------------------------
            surfer_initial = await get_initial_surfer_score(
                keyword_data["main_keyword"], language, restructured_html
            )
            run.surfer_doc_id = surfer_initial["surfer_doc_id"]
            run.initial_surfer_score = surfer_initial["initial_score"]
            await session.commit()

            # -------------------------------------------------------------------
            # Step 6 — Claude full SEO rewrite
            # -------------------------------------------------------------------
            claude_output = await run_seo_rewrite(
                title=title,
                body_html=restructured_html,
                language=language,
                main_keyword=keyword_data["main_keyword"],
                secondary_keywords=keyword_data["secondary_keywords"],
                question_keywords=keyword_data["question_keywords"],
                lsi_keywords=surfer_initial["lsi_keywords"],
                suggested_headings=surfer_initial["suggested_headings"],
                competitor_heading_structure=competitor_data["dominant_heading_structure"],
            )

            optimized_html: str = claude_output.get("optimized_html", "")
            run.optimized_content = optimized_html
            run.optimized_metadata = json.dumps(claude_output, ensure_ascii=False)
            await session.commit()

            # -------------------------------------------------------------------
            # Step 7 — Plagiarism check
            # -------------------------------------------------------------------
            plagiarism_result = await check_plagiarism(optimized_html)
            run.plagiarism_flagged = plagiarism_result["plagiarism_flagged"]
            run.plagiarism_max_similarity = plagiarism_result["max_similarity"]
            await session.commit()

            # -------------------------------------------------------------------
            # Step 8 — SurferSEO final score
            # -------------------------------------------------------------------
            surfer_final = await get_final_surfer_score(
                run.surfer_doc_id, optimized_html, run.initial_surfer_score or 0
            )
            run.final_surfer_score = surfer_final["final_score"]
            run.score_delta = surfer_final["score_delta"]
            run.score_delta_pct = surfer_final["score_delta_pct"]
            await session.commit()

            # -------------------------------------------------------------------
            # Step 9 — Create Asana approval task
            # -------------------------------------------------------------------
            internal_links: List[Dict[str, Any]] = claude_output.get(
                "internal_link_suggestions", []
            )
            changes_summary: str = claude_output.get("changes_summary", "")

            asana_task = await create_approval_task(
                article_id=article_id,
                title=title,
                main_keyword=keyword_data["main_keyword"],
                main_kw_volume=keyword_data["main_kw_volume"],
                main_kw_difficulty=keyword_data["main_kw_difficulty"],
                initial_score=surfer_initial["initial_score"],
                final_score=surfer_final["final_score"],
                score_delta_pct=surfer_final["score_delta_pct"],
                competitor_urls=competitor_data["competitor_urls"],
                plagiarism_flagged=run.plagiarism_flagged or False,
                plagiarism_max_similarity=run.plagiarism_max_similarity or 0.0,
                changes_summary=changes_summary,
                internal_link_suggestions=internal_links,
            )

            run.asana_task_gid = asana_task.get("gid", "")
            run.status = RunStatus.AWAITING_APPROVAL
            run.duration_seconds = (datetime.utcnow() - start_time).total_seconds()
            await session.commit()

            logger.info(
                "=== SEO pipeline complete for article %s. "
                "Awaiting approval on Asana task %s ===",
                article_id,
                run.asana_task_gid,
            )

        except Exception as exc:
            logger.error(
                "Unhandled exception in pipeline for article %s: %s",
                article_id,
                exc,
                exc_info=True,
            )
            await _fail_run(session, run, str(exc))


# ---------------------------------------------------------------------------
# Approval
# ---------------------------------------------------------------------------

async def approve_optimization_run(task_gid: str) -> None:
    """
    Triggered by Asana APPROVE comment.
    Writes optimised content back to Shopify and marks the run COMPLETED.
    """
    logger.info("Approval received for Asana task %s", task_gid)

    async with AsyncSessionLocal() as session:
        run = await _get_run_by_task(session, task_gid)

        if run is None:
            logger.error(
                "No BlogRun found for Asana task %s — cannot approve.", task_gid
            )
            return

        if run.status != RunStatus.AWAITING_APPROVAL:
            logger.warning(
                "Task %s is in status '%s', not awaiting_approval — skipping.",
                task_gid,
                run.status,
            )
            return

        try:
            run.status = RunStatus.APPROVED
            await session.commit()

            # Deserialise stored metadata
            metadata: Dict[str, Any] = {}
            if run.optimized_metadata:
                try:
                    metadata = json.loads(run.optimized_metadata)
                except json.JSONDecodeError:
                    logger.warning("Could not parse optimized_metadata for run %s", run.id)

            # Step 10a — Write back to Shopify
            await _write_back_to_shopify(
                article_id=run.article_id,
                optimized_html=run.optimized_content or "",
                metadata=metadata,
            )

            # Step 10b — Update Asana
            await add_comment_to_task(
                task_gid,
                "✅ Shopify draft updated — ready for final review and publish.",
            )
            await complete_task(task_gid)

            # Mark run as COMPLETED
            run.status = RunStatus.COMPLETED
            run.completed_at = datetime.utcnow()
            await session.commit()

            logger.info("Run %s COMPLETED — Shopify draft updated.", run.id)

        except Exception as exc:
            logger.error(
                "Approval failed for task %s: %s", task_gid, exc, exc_info=True
            )
            await _fail_run(session, run, f"Approval step failed: {exc}", notify_asana=False)
            try:
                await add_comment_to_task(
                    task_gid,
                    f"❌ Shopify write-back failed: {exc}\n\nPlease contact the developer.",
                )
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Rejection
# ---------------------------------------------------------------------------

async def reject_optimization_run(task_gid: str, reason: str) -> None:
    """
    Triggered by Asana REJECT comment.
    Logs the rejection, marks the run REJECTED, and acknowledges on Asana.
    """
    logger.info("Rejection received for Asana task %s. Reason: %s", task_gid, reason)

    async with AsyncSessionLocal() as session:
        run = await _get_run_by_task(session, task_gid)

        if run is None:
            logger.error("No BlogRun found for Asana task %s — cannot reject.", task_gid)
            return

        run.status = RunStatus.REJECTED
        run.failure_reason = f"Rejected: {reason}"
        await session.commit()
        logger.info("Run %s marked REJECTED. Reason: %s", run.id, reason)

        try:
            await add_comment_to_task(
                task_gid,
                f"❌ Run rejected.\n\nReason: {reason}\n\n"
                "The original draft has not been modified. "
                "The original author has been notified.",
            )
        except Exception as exc:
            logger.warning("Could not post rejection comment to Asana: %s", exc)
