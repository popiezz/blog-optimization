"""
Step 7 — Plagiarism check via Copyscape.

Strips HTML to plain text before submitting (Copyscape accepts text, not HTML).
Does NOT block the pipeline — returns a flag that is surfaced in the Asana
approval comment so the colleague can make an informed decision.
"""

import logging
from typing import Any, Dict

import httpx
from bs4 import BeautifulSoup

from config.settings import settings

logger = logging.getLogger(__name__)

_COPYSCAPE_URL = "https://www.copyscape.com/api/"


async def check_plagiarism(html_content: str) -> Dict[str, Any]:
    """
    Submits the optimised content to Copyscape for a similarity check.

    Returns:
        {
            "plagiarism_flagged": bool,   # True if any source exceeds threshold
            "max_similarity": float,      # Highest similarity % found (0–100)
            "matches": list,              # Raw Copyscape result items
        }

    If the Copyscape API call fails, returns a safe default (not flagged) and
    logs the error so the pipeline can continue.
    """
    if not html_content or not html_content.strip():
        return {"plagiarism_flagged": False, "max_similarity": 0.0, "matches": []}

    # Strip HTML to plain text
    plain_text = BeautifulSoup(html_content, "lxml").get_text(separator=" ", strip=True)
    # Copyscape recommends ≤ 1,000 words for a single query
    words = plain_text.split()
    if len(words) > 1000:
        plain_text = " ".join(words[:1000])

    params = {
        "u": settings.COPYSCAPE_USERNAME,
        "k": settings.COPYSCAPE_API_KEY,
        "o": "csearch",
        "t": plain_text,
        "f": "json",
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(_COPYSCAPE_URL, data=params)
            response.raise_for_status()
            data = response.json()
    except Exception as exc:
        logger.error("Copyscape API call failed: %s — skipping plagiarism check.", exc)
        return {"plagiarism_flagged": False, "max_similarity": 0.0, "matches": []}

    matches = data.get("result", [])
    if not matches:
        return {"plagiarism_flagged": False, "max_similarity": 0.0, "matches": []}

    # Copyscape returns `minper` (minimum % of matching words in the source)
    # and `percentmatched` (% of our text matched).  We use percentmatched when
    # available, falling back to minper.
    def _similarity(match: Dict) -> float:
        for key in ("percentmatched", "minper", "percent"):
            val = match.get(key)
            if val is not None:
                try:
                    return float(val)
                except (ValueError, TypeError):
                    pass
        return 0.0

    max_similarity = max(_similarity(m) for m in matches)
    flagged = max_similarity > settings.PLAGIARISM_THRESHOLD

    if flagged:
        logger.warning(
            "Plagiarism threshold exceeded: %.1f%% > %.1f%%",
            max_similarity,
            settings.PLAGIARISM_THRESHOLD,
        )

    return {
        "plagiarism_flagged": flagged,
        "max_similarity": max_similarity,
        "matches": matches,
    }
