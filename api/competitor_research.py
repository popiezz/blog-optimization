import asyncio
import logging
from typing import Any, Dict, List, Optional

import httpx
from bs4 import BeautifulSoup

from config.settings import settings

logger = logging.getLogger(__name__)

_SERPER_URL = "https://google.serper.dev/search"
_SKIP_DOMAINS = {"wikipedia.org", "reddit.com", "quora.com", "amazon.com", "youtube.com"}
_FETCH_TIMEOUT = 10.0  # seconds per competitor page


# ---------------------------------------------------------------------------
# Serper search
# ---------------------------------------------------------------------------

async def _serper_search(keyword: str, language: str, num: int = 5) -> List[str]:
    """
    Searches Google via Serper.dev and returns the top organic result URLs,
    filtering out ads, featured snippets, and low-quality domains.
    """
    if not settings.SERPER_API_KEY:
        raise RuntimeError("SERPER_API_KEY not configured")

    gl = "ca" if language == "fr" else "us"
    hl = language

    payload = {"q": keyword, "gl": gl, "hl": hl, "num": num + 2}
    headers = {"X-API-KEY": settings.SERPER_API_KEY, "Content-Type": "application/json"}

    async with httpx.AsyncClient() as client:
        response = await client.post(_SERPER_URL, headers=headers, json=payload)
        response.raise_for_status()

    data = response.json()
    urls = []
    for item in data.get("organic", []):
        url: str = item.get("link", "")
        domain = url.split("/")[2] if url.startswith("http") else ""
        if any(skip in domain for skip in _SKIP_DOMAINS):
            continue
        urls.append(url)
        if len(urls) >= 3:
            break

    return urls


# ---------------------------------------------------------------------------
# Page heading extraction
# ---------------------------------------------------------------------------

async def _extract_headings(url: str) -> Optional[Dict[str, Any]]:
    """
    Fetches a page and extracts its heading structure and word count.
    Returns None if the page cannot be fetched.
    """
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=_FETCH_TIMEOUT) as client:
            response = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            response.raise_for_status()
            html = response.text
    except Exception as exc:
        logger.warning("Could not fetch competitor page %s: %s", url, exc)
        return None

    soup = BeautifulSoup(html, "lxml")

    # Remove nav, footer, sidebar elements to focus on main content
    for tag in soup.find_all(["nav", "footer", "aside", "header"]):
        tag.decompose()

    h1 = soup.find("h1")
    h2s = [h.get_text(strip=True) for h in soup.find_all("h2")]
    h3s = [h.get_text(strip=True) for h in soup.find_all("h3")]
    word_count = len(soup.get_text(separator=" ", strip=True).split())

    return {
        "url": url,
        "h1": h1.get_text(strip=True) if h1 else "",
        "h2s": h2s,
        "h3s": h3s,
        "word_count": word_count,
    }


# ---------------------------------------------------------------------------
# Structural analysis
# ---------------------------------------------------------------------------

def _dominant_structure(pages: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Derives the dominant heading structure signal from multiple competitor pages.
    """
    all_h2s: List[str] = []
    word_counts: List[int] = []
    h2_counts: List[int] = []

    for page in pages:
        all_h2s.extend(page.get("h2s", []))
        word_counts.append(page.get("word_count", 0))
        h2_counts.append(len(page.get("h2s", [])))

    # De-duplicate H2 topics while preserving frequency order
    seen = set()
    unique_h2s = []
    for h2 in all_h2s:
        key = h2.lower()
        if key not in seen:
            seen.add(key)
            unique_h2s.append(h2)

    return {
        "h2_topics": unique_h2s[:8],  # top 8 H2 topics
        "avg_word_count": int(sum(word_counts) / max(len(word_counts), 1)),
        "avg_h2_count": int(sum(h2_counts) / max(len(h2_counts), 1)),
    }


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

async def fetch_competitor_content(keyword: str, language: str) -> Dict[str, Any]:
    """
    Searches for `keyword`, fetches the top 3 organic results, and extracts
    the dominant heading structure for use as a structural signal in Claude.

    Returns:
        {
            "competitor_urls": list[str],
            "dominant_heading_structure": {
                "h2_topics": list[str],
                "avg_word_count": int,
                "avg_h2_count": int,
            },
        }

    Falls back to a minimal stub if SERPER_API_KEY is not configured or all
    fetches fail, so the pipeline continues without blocking.
    """
    logger.info("Competitor research for '%s' (%s)", keyword, language)

    if not settings.SERPER_API_KEY:
        logger.warning("SERPER_API_KEY not set — using stub competitor data.")
        return _stub_response(keyword)

    try:
        urls = await _serper_search(keyword, language)
        if not urls:
            logger.warning("No competitor URLs found for '%s'", keyword)
            return _stub_response(keyword)

        # Fetch pages concurrently
        results = await asyncio.gather(*[_extract_headings(url) for url in urls])
        pages = [r for r in results if r is not None]

        if not pages:
            logger.warning("All competitor page fetches failed for '%s'", keyword)
            return {"competitor_urls": urls, "dominant_heading_structure": _stub_structure(keyword)}

        return {
            "competitor_urls": [p["url"] for p in pages],
            "dominant_heading_structure": _dominant_structure(pages),
        }

    except Exception as exc:
        logger.error("Competitor research failed: %s", exc, exc_info=True)
        return _stub_response(keyword)


def _stub_response(keyword: str) -> Dict[str, Any]:
    return {
        "competitor_urls": [],
        "dominant_heading_structure": _stub_structure(keyword),
    }


def _stub_structure(keyword: str) -> Dict[str, Any]:
    return {
        "h2_topics": [
            f"What is {keyword}",
            f"Benefits of {keyword}",
            f"How to choose {keyword}",
            f"Tips for {keyword}",
        ],
        "avg_word_count": 1200,
        "avg_h2_count": 5,
    }
