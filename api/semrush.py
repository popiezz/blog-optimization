import logging
from typing import Any, Dict, List

import httpx

from config.settings import settings

logger = logging.getLogger(__name__)

_SEMRUSH_BASE = "https://api.semrush.com/"


def _database_for_language(language: str) -> str:
    return settings.SEMRUSH_DATABASE_FR if language == "fr" else settings.SEMRUSH_DATABASE_EN


def _parse_value(raw: str, cast):
    """Safely cast a raw string value; returns 0 (or 0.0) on failure."""
    try:
        return cast(raw.strip())
    except (ValueError, AttributeError):
        return cast(0)


# ---------------------------------------------------------------------------
# Low-level API calls
# ---------------------------------------------------------------------------

async def semrush_keyword_overview(keyword: str, database: str = "us") -> Dict[str, Any]:
    """
    Returns volume, KD, and CPC for the seed keyword.
    SEMrush response is CSV-like: header row + data row, semicolon-separated.
    """
    params = {
        "key": settings.SEMRUSH_API_KEY,
        "type": "phrase_this",
        "phrase": keyword,
        "database": database,
        "export_columns": "Ph,Vi,Kd,Cp",
    }
    async with httpx.AsyncClient() as client:
        response = await client.get(_SEMRUSH_BASE, params=params)
        response.raise_for_status()

    lines = [l for l in response.text.splitlines() if l.strip()]
    if len(lines) < 2:
        logger.warning("SEMrush phrase_this returned no data for '%s'", keyword)
        return {"keyword": keyword, "volume": 0, "difficulty": 0.0, "cpc": 0.0}

    values = lines[1].split(";")
    if len(values) < 4:
        return {"keyword": keyword, "volume": 0, "difficulty": 0.0, "cpc": 0.0}

    return {
        "keyword": values[0].strip(),
        "volume": _parse_value(values[1], int),
        "difficulty": _parse_value(values[2], float),
        "cpc": _parse_value(values[3], float),
    }


async def semrush_related_keywords(
    keyword: str, database: str = "us", limit: int = 20
) -> List[Dict[str, Any]]:
    """Returns related keywords sorted by the SEMrush default ranking."""
    params = {
        "key": settings.SEMRUSH_API_KEY,
        "type": "phrase_related",
        "phrase": keyword,
        "database": database,
        "export_columns": "Ph,Vi,Kd",
        "display_limit": limit,
    }
    async with httpx.AsyncClient() as client:
        response = await client.get(_SEMRUSH_BASE, params=params)
        response.raise_for_status()

    results = []
    lines = [l for l in response.text.splitlines() if l.strip()]
    for line in lines[1:]:  # skip header
        values = line.split(";")
        if len(values) < 3:
            continue
        results.append(
            {
                "keyword": values[0].strip(),
                "volume": _parse_value(values[1], int),
                "difficulty": _parse_value(values[2], float),
            }
        )
    return results


async def semrush_question_keywords(
    keyword: str, database: str = "us", limit: int = 5
) -> List[str]:
    """Returns question-format keywords (strong H2 candidates)."""
    params = {
        "key": settings.SEMRUSH_API_KEY,
        "type": "phrase_questions",
        "phrase": keyword,
        "database": database,
        "export_columns": "Ph",
        "display_limit": limit,
    }
    async with httpx.AsyncClient() as client:
        response = await client.get(_SEMRUSH_BASE, params=params)
        response.raise_for_status()

    lines = [l for l in response.text.splitlines() if l.strip()]
    return [line.strip() for line in lines[1:]]  # skip header


# ---------------------------------------------------------------------------
# High-level helper used by the pipeline
# ---------------------------------------------------------------------------

async def run_keyword_research(target_keyword: str, language: str) -> Dict[str, Any]:
    """
    Runs all three SEMrush calls and returns the full keyword research output.

    Returns:
        {
            "main_keyword": str,
            "secondary_keywords": list[str],   # top 5 by volume/KD score
            "question_keywords": list[str],     # top 3
            "main_kw_volume": int,
            "main_kw_difficulty": float,
        }
    """
    database = _database_for_language(language)

    overview, related, questions = await _gather_semrush(target_keyword, database)

    main_keyword = overview.get("keyword") or target_keyword
    main_kw_volume = overview.get("volume", 0)
    main_kw_difficulty = overview.get("difficulty", 0.0)

    # Rank related keywords by volume / max(KD, 1) — higher is better
    scored = sorted(
        related,
        key=lambda kw: kw["volume"] / max(kw["difficulty"], 1),
        reverse=True,
    )
    secondary_keywords = [kw["keyword"] for kw in scored[:5]]

    return {
        "main_keyword": main_keyword,
        "secondary_keywords": secondary_keywords,
        "question_keywords": questions[:3],
        "main_kw_volume": main_kw_volume,
        "main_kw_difficulty": main_kw_difficulty,
    }


async def _gather_semrush(keyword: str, database: str):
    """Runs the three SEMrush calls concurrently."""
    import asyncio

    overview_task = asyncio.create_task(semrush_keyword_overview(keyword, database))
    related_task = asyncio.create_task(semrush_related_keywords(keyword, database, limit=20))
    questions_task = asyncio.create_task(semrush_question_keywords(keyword, database, limit=5))
    return await asyncio.gather(overview_task, related_task, questions_task)
