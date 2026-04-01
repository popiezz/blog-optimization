"""
Tests for api/semrush.py — keyword research.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from api.semrush import (
    _database_for_language,
    _parse_value,
    run_keyword_research,
    semrush_keyword_overview,
    semrush_question_keywords,
    semrush_related_keywords,
)


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def test_database_for_language_fr():
    with patch("api.semrush.settings") as s:
        s.SEMRUSH_DATABASE_FR = "ca"
        s.SEMRUSH_DATABASE_EN = "us"
        assert _database_for_language("fr") == "ca"


def test_database_for_language_en():
    with patch("api.semrush.settings") as s:
        s.SEMRUSH_DATABASE_FR = "ca"
        s.SEMRUSH_DATABASE_EN = "us"
        assert _database_for_language("en") == "us"


def test_parse_value_int_success():
    assert _parse_value("1200", int) == 1200


def test_parse_value_float_success():
    assert _parse_value("45.5", float) == 45.5


def test_parse_value_returns_zero_on_invalid_int():
    assert _parse_value("N/A", int) == 0


def test_parse_value_returns_zero_on_invalid_float():
    assert _parse_value("--", float) == 0.0


def test_parse_value_handles_whitespace():
    assert _parse_value("  500  ", int) == 500


# ---------------------------------------------------------------------------
# semrush_keyword_overview
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_keyword_overview_parses_valid_response():
    csv_response = "Keyword;Search Volume;Keyword Difficulty;CPC\nrunning shoes;12000;45.5;1.20"
    mock_response = MagicMock()
    mock_response.text = csv_response
    mock_response.raise_for_status = MagicMock()

    with patch("api.semrush.settings") as s:
        s.SEMRUSH_API_KEY = "key"
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            result = await semrush_keyword_overview("running shoes", "us")

    assert result["keyword"] == "running shoes"
    assert result["volume"] == 12000
    assert result["difficulty"] == 45.5
    assert result["cpc"] == 1.20


@pytest.mark.asyncio
async def test_keyword_overview_returns_zeros_on_empty_response():
    mock_response = MagicMock()
    mock_response.text = "Keyword;Search Volume;Keyword Difficulty;CPC"  # header only
    mock_response.raise_for_status = MagicMock()

    with patch("api.semrush.settings") as s:
        s.SEMRUSH_API_KEY = "key"
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            result = await semrush_keyword_overview("unknown", "us")

    assert result["volume"] == 0
    assert result["difficulty"] == 0.0


@pytest.mark.asyncio
async def test_keyword_overview_returns_zeros_on_malformed_row():
    mock_response = MagicMock()
    mock_response.text = "Keyword;Volume\nrunning shoes;12000"  # only 2 columns
    mock_response.raise_for_status = MagicMock()

    with patch("api.semrush.settings") as s:
        s.SEMRUSH_API_KEY = "key"
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            result = await semrush_keyword_overview("running shoes", "us")

    assert result["volume"] == 0


# ---------------------------------------------------------------------------
# semrush_related_keywords
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_related_keywords_parses_multiple_rows():
    csv = (
        "Keyword;Volume;KD\n"
        "best running shoes;8000;50.0\n"
        "trail running shoes;3000;35.0\n"
        "women running shoes;5000;40.0\n"
    )
    mock_response = MagicMock()
    mock_response.text = csv
    mock_response.raise_for_status = MagicMock()

    with patch("api.semrush.settings") as s:
        s.SEMRUSH_API_KEY = "key"
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            result = await semrush_related_keywords("running shoes", "us")

    assert len(result) == 3
    assert result[0]["keyword"] == "best running shoes"
    assert result[0]["volume"] == 8000


@pytest.mark.asyncio
async def test_related_keywords_skips_malformed_rows():
    csv = "Keyword;Volume;KD\nbad row\ngood row;1000;20.0"
    mock_response = MagicMock()
    mock_response.text = csv
    mock_response.raise_for_status = MagicMock()

    with patch("api.semrush.settings") as s:
        s.SEMRUSH_API_KEY = "key"
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            result = await semrush_related_keywords("kw", "us")

    assert len(result) == 1
    assert result[0]["keyword"] == "good row"


# ---------------------------------------------------------------------------
# semrush_question_keywords
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_question_keywords_returns_list_of_strings():
    csv = "Keyword\nhow to choose running shoes\nwhat are the best running shoes\n"
    mock_response = MagicMock()
    mock_response.text = csv
    mock_response.raise_for_status = MagicMock()

    with patch("api.semrush.settings") as s:
        s.SEMRUSH_API_KEY = "key"
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            result = await semrush_question_keywords("running shoes", "us")

    assert result == [
        "how to choose running shoes",
        "what are the best running shoes",
    ]


# ---------------------------------------------------------------------------
# run_keyword_research — high-level orchestrator
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_keyword_research_returns_top_5_secondary_sorted_by_ratio():
    overview = {"keyword": "running shoes", "volume": 10000, "difficulty": 50.0, "cpc": 1.0}
    # volume/KD ratios: a=200, b=80, c=500, d=150, e=400, f=100
    related = [
        {"keyword": "a", "volume": 2000, "difficulty": 10},  # 200
        {"keyword": "b", "volume": 800, "difficulty": 10},   # 80
        {"keyword": "c", "volume": 5000, "difficulty": 10},  # 500
        {"keyword": "d", "volume": 1500, "difficulty": 10},  # 150
        {"keyword": "e", "volume": 4000, "difficulty": 10},  # 400
        {"keyword": "f", "volume": 1000, "difficulty": 10},  # 100
    ]
    questions = ["how to choose", "what are", "which is best", "why", "when"]

    with patch("api.semrush.settings") as s:
        s.SEMRUSH_DATABASE_FR = "ca"
        s.SEMRUSH_DATABASE_EN = "us"
        with patch("api.semrush._gather_semrush", new_callable=AsyncMock) as mock_gather:
            mock_gather.return_value = (overview, related, questions)
            result = await run_keyword_research("running shoes", "en")

    assert result["main_keyword"] == "running shoes"
    assert result["main_kw_volume"] == 10000
    assert result["main_kw_difficulty"] == 50.0
    assert len(result["secondary_keywords"]) == 5
    # Top 5 by volume/KD ratio: c(500), e(400), a(200), d(150), f(100)
    assert result["secondary_keywords"] == ["c", "e", "a", "d", "f"]
    # Only top 3 question keywords
    assert result["question_keywords"] == ["how to choose", "what are", "which is best"]


@pytest.mark.asyncio
async def test_run_keyword_research_handles_zero_difficulty():
    overview = {"keyword": "kw", "volume": 100, "difficulty": 0.0, "cpc": 0.0}
    related = [{"keyword": "x", "volume": 1000, "difficulty": 0}]
    questions = []

    with patch("api.semrush.settings") as s:
        s.SEMRUSH_DATABASE_FR = "ca"
        s.SEMRUSH_DATABASE_EN = "us"
        with patch("api.semrush._gather_semrush", new_callable=AsyncMock) as mock_gather:
            mock_gather.return_value = (overview, related, questions)
            result = await run_keyword_research("kw", "en")

    # Should not raise ZeroDivisionError (uses max(difficulty, 1))
    assert result["secondary_keywords"] == ["x"]
