import logging
import traceback
from datetime import datetime
from typing import Any, Dict

from models.blog_run import AsyncSessionLocal, BlogRun, RunStatus
from sqlalchemy.future import select

from api.semrush import semrush_keyword_overview, semrush_related_keywords, semrush_question_keywords
from api.competitor_research import fetch_competitor_content
from api.surfer import create_surfer_document, trigger_surfer_optimization, poll_surfer_score, update_surfer_content
from api.claude_ai import generate_seo_content
from api.plagiarism import check_plagiarism
from api.asana import create_asana_task
from api.shopify import update_shopify_article

# For missing imports we define placeholders or use ones we assume exist
import pipeline.restructure as restructure

logger = logging.getLogger(__name__)


async def start_optimization_pipeline(article_id: str, blog_id: str, data: Dict[str, Any]):
    """
    Entry point for the SEO optimization pipeline.
    Orchestrates the research, rewriting, and task creation.
    """
    logger.info(f"[Article {article_id}] Starting SEO pipeline")
    
    try:
        async with AsyncSessionLocal() as session:
            # Update status to PROCESSING
            result = await session.execute(select(BlogRun).where(BlogRun.article_id == article_id))
            run = result.scalars().first()
            if not run:
                logger.error(f"[Article {article_id}] BlogRun not found in DB.")
                return

            run.status = RunStatus.PROCESSING
            await session.commit()

            target_keyword = data.get("seo.target_keyword", "")
            title = data.get("title", "")
            body_html = data.get("body_html", "")
            language = "fr" if "fr" in data.get("body_html", "").lower() else "en" # Mock language detection if langdetect isn't directly usable here

            # Step 2: SEMrush
            logger.info(f"[Article {article_id}] Fetching SEMrush data for keyword: {target_keyword}")
            semrush_db = "ca" if language == "fr" else "us"
            kw_overview = await semrush_keyword_overview(target_keyword, database=semrush_db)
            related_kws = await semrush_related_keywords(target_keyword, database=semrush_db)
            question_kws = await semrush_question_keywords(target_keyword, database=semrush_db)

            main_keyword = kw_overview.get("keyword", target_keyword)

            # Step 3: Competitor Research
            logger.info(f"[Article {article_id}] Fetching competitor research")
            competitor_data = await fetch_competitor_content(main_keyword, language)

            # Step 4: Restructure
            logger.info(f"[Article {article_id}] Restructuring content")
            # Assuming restructure.restructure_html exists or we just use original for now
            restructured_html = getattr(restructure, "restructure_html", lambda x, y: x)(body_html, title)

            # Step 5: Surfer Initial Score
            logger.info(f"[Article {article_id}] Fetching initial SurferSEO score")
            surfer_doc = await create_surfer_document(main_keyword, language)
            doc_id = surfer_doc.get("id", "mock_id") # Adjust according to actual response
            await update_surfer_content(doc_id, restructured_html)
            await trigger_surfer_optimization(doc_id)
            initial_surfer_data = await poll_surfer_score(doc_id)
            run.initial_surfer_score = initial_surfer_data.get("content_score", 0.0)

            # Step 6: Claude Rewrite
            logger.info(f"[Article {article_id}] Generating optimized content with Claude")
            prompt_context = {
                "title": title,
                "body_html": restructured_html,
                "language": language,
                "main_keyword": main_keyword,
                "secondary_keywords": [kw.get("keyword") for kw in related_kws],
                "lsi_keywords": initial_surfer_data.get("lsi_keywords", []),
                "question_keywords": question_kws,
                "suggested_headings": initial_surfer_data.get("suggested_headings", []),
                "competitor_heading_structure": competitor_data.get("dominant_heading_structure", {})
            }
            # Load system prompt (mocking this as a simple string for now, in reality loaded from file)
            system_prompt = f"Optimize this {language} blog post for SEO."

            # We will handle retry logic inside generate_seo_content
            claude_response = await generate_seo_content(prompt_context, system_prompt, article_id=article_id)
            optimized_html = claude_response.get("optimized_html", "")

            # Step 7: Plagiarism
            logger.info(f"[Article {article_id}] Checking plagiarism")
            plagiarism_data = await check_plagiarism(optimized_html)
            run.plagiarism_flagged = plagiarism_data.get("plagiarism_flagged", False)
            run.plagiarism_max_similarity = plagiarism_data.get("max_similarity", 0.0)

            # Step 8: Surfer Final Score
            logger.info(f"[Article {article_id}] Fetching final SurferSEO score")
            await update_surfer_content(doc_id, optimized_html)
            await trigger_surfer_optimization(doc_id)
            final_surfer_data = await poll_surfer_score(doc_id)
            run.final_surfer_score = final_surfer_data.get("content_score", 0.0)

            if run.initial_surfer_score is not None and run.final_surfer_score is not None:
                run.score_delta = run.final_surfer_score - run.initial_surfer_score
                if run.initial_surfer_score > 0:
                    run.score_delta_pct = (run.score_delta / run.initial_surfer_score) * 100
                else:
                    run.score_delta_pct = 0.0

            run.optimized_content = optimized_html

            # Save Claude response metadata for step 10 to DB or file if needed, here we just keep it in memory
            # For simplicity, we could serialize it into optimized_content or a new column, but let's assume it's passed via Asana for now.

            # Step 9: Asana task
            logger.info(f"[Article {article_id}] Creating Asana task for approval")
            notes = f"✅ SEO Pipeline Complete — Awaiting Approval\n\n"
            notes += f"📄 Article: {title}\n"
            notes += f"🔑 Main Keyword: {main_keyword}\n"
            notes += f"📊 SurferSEO Score: {run.initial_surfer_score} → {run.final_surfer_score} (+{run.score_delta_pct:.2f}%)\n"
            notes += f"🌐 Competitors analyzed: {', '.join(competitor_data.get('competitor_urls', []))}\n"
            notes += f"⚠️ Plagiarism flag: {'YES' if run.plagiarism_flagged else 'NO'} ({run.plagiarism_max_similarity}% max similarity)\n\n"
            notes += f"Changes made:\n{claude_response.get('changes_summary', 'N/A')}\n\n"
            notes += f"👉 Reply 'APPROVE' to write optimized content to Shopify draft\n"
            notes += f"👉 Reply 'REJECT: [reason]' to discard"

            asana_task = await create_asana_task(title, notes, article_id)
            run.asana_task_gid = asana_task.get("gid")
            run.status = RunStatus.AWAITING_APPROVAL

            await session.commit()
            logger.info(f"[Article {article_id}] Pipeline paused, awaiting approval on task {run.asana_task_gid}")

    except Exception as e:
        logger.error(f"[Article {article_id}] Unhandled error in pipeline: {e}\n{traceback.format_exc()}")
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(BlogRun).where(BlogRun.article_id == article_id))
            run = result.scalars().first()
            if run:
                run.status = RunStatus.FAILED
                run.failure_reason = str(e)
                if run.created_at:
                    run.duration_seconds = (datetime.utcnow() - run.created_at).total_seconds()
                await session.commit()


async def approve_optimization_run(task_gid: str):
    """
    Final step of the pipeline, triggered by Asana approval.
    Writes the optimized content back to Shopify.
    """
    logger.info(f"Approving SEO run for Asana task {task_gid}")
    
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(BlogRun).where(BlogRun.asana_task_gid == task_gid))
            run = result.scalars().first()
            if not run:
                logger.error(f"BlogRun not found for Asana task {task_gid}")
                return

            article_id = run.article_id
            logger.info(f"[Article {article_id}] Approving SEO run for Asana task {task_gid}")

            run.status = RunStatus.APPROVED
            await session.commit()

            # Write back to Shopify
            logger.info(f"[Article {article_id}] Writing optimized content to Shopify")
            update_data = {
                "body_html": run.optimized_content
                # In a full implementation, we would extract title, handle, metafields from stored Claude JSON output
                # and pass them here as well.
            }
            await update_shopify_article(article_id, update_data)

            run.status = RunStatus.COMPLETED
            if run.created_at:
                run.duration_seconds = (datetime.utcnow() - run.created_at).total_seconds()
            await session.commit()
            logger.info(f"[Article {article_id}] SEO pipeline successfully completed")
    except Exception as e:
        logger.error(f"Unhandled error in approve_optimization_run: {e}\n{traceback.format_exc()}")
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(BlogRun).where(BlogRun.asana_task_gid == task_gid))
            run = result.scalars().first()
            if run:
                run.status = RunStatus.FAILED
                run.failure_reason = str(e)
                if run.created_at:
                    run.duration_seconds = (datetime.utcnow() - run.created_at).total_seconds()
                await session.commit()


async def reject_optimization_run(task_gid: str, reason: str):
    """
    Final step of the pipeline when rejected.
    Records the reason and closes the run.
    """
    logger.info(f"Rejecting SEO run for Asana task {task_gid}. Reason: {reason}")
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(BlogRun).where(BlogRun.asana_task_gid == task_gid))
            run = result.scalars().first()
            if not run:
                logger.error(f"BlogRun not found for Asana task {task_gid}")
                return

            article_id = run.article_id
            logger.info(f"[Article {article_id}] Rejecting SEO run for Asana task {task_gid}")

            run.status = RunStatus.REJECTED
            run.failure_reason = f"Rejected via Asana: {reason}"
            if run.created_at:
                run.duration_seconds = (datetime.utcnow() - run.created_at).total_seconds()
            await session.commit()
            logger.info(f"[Article {article_id}] SEO pipeline rejected")
    except Exception as e:
        logger.error(f"Unhandled error in reject_optimization_run: {e}\n{traceback.format_exc()}")
