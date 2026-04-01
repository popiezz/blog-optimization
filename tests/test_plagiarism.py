"""
Tests for api/plagiarism.py — Copyscape similarity check.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# check_plagiarism
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_check_plagiarism_empty_html_returns_safe_default():
    from api.plagiarism import check_plagiarism
    result = await check_plagiarism("")
    assert result == {"plagiarism_flagged": False, "max_similarity": 0.0, "matches": []}


@pytest.mark.asyncio
async def test_check_plagiarism_whitespace_only_returns_safe_default():
    from api.plagiarism import check_plagiarism
    result = await check_plagiarism("   ")
    assert result == {"plagiarism_flagged": False, "max_similarity": 0.0, "matches": []}


@pytest.mark.asyncio
async def test_check_plagiarism_not_flagged_below_threshold():
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "result": [{"percentmatched": "10"}]
    }

    with patch("api.plagiarism.settings") as s:
        s.COPYSCAPE_USERNAME = "user"
        s.COPYSCAPE_API_KEY = "key"
        s.PLAGIARISM_THRESHOLD = 15.0
        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_cls.return_value = mock_client

            from api.plagiarism import check_plagiarism
            result = await check_plagiarism("<p>Some original content here.</p>")

    assert result["plagiarism_flagged"] is False
    assert result["max_similarity"] == 10.0


@pytest.mark.asyncio
async def test_check_plagiarism_flagged_above_threshold():
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "result": [{"percentmatched": "20"}, {"percentmatched": "8"}]
    }

    with patch("api.plagiarism.settings") as s:
        s.COPYSCAPE_USERNAME = "user"
        s.COPYSCAPE_API_KEY = "key"
        s.PLAGIARISM_THRESHOLD = 15.0
        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_cls.return_value = mock_client

            from api.plagiarism import check_plagiarism
            result = await check_plagiarism("<p>Copied content.</p>")

    assert result["plagiarism_flagged"] is True
    assert result["max_similarity"] == 20.0


@pytest.mark.asyncio
async def test_check_plagiarism_uses_minper_fallback():
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "result": [{"minper": "25"}]  # no percentmatched key
    }

    with patch("api.plagiarism.settings") as s:
        s.COPYSCAPE_USERNAME = "user"
        s.COPYSCAPE_API_KEY = "key"
        s.PLAGIARISM_THRESHOLD = 15.0
        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_cls.return_value = mock_client

            from api.plagiarism import check_plagiarism
            result = await check_plagiarism("<p>Content.</p>")

    assert result["max_similarity"] == 25.0
    assert result["plagiarism_flagged"] is True


@pytest.mark.asyncio
async def test_check_plagiarism_no_matches_returns_safe():
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"result": []}

    with patch("api.plagiarism.settings") as s:
        s.COPYSCAPE_USERNAME = "user"
        s.COPYSCAPE_API_KEY = "key"
        s.PLAGIARISM_THRESHOLD = 15.0
        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_cls.return_value = mock_client

            from api.plagiarism import check_plagiarism
            result = await check_plagiarism("<p>Original content.</p>")

    assert result["plagiarism_flagged"] is False
    assert result["max_similarity"] == 0.0


@pytest.mark.asyncio
async def test_check_plagiarism_api_failure_returns_safe_default():
    with patch("api.plagiarism.settings") as s:
        s.COPYSCAPE_USERNAME = "user"
        s.COPYSCAPE_API_KEY = "key"
        s.PLAGIARISM_THRESHOLD = 15.0
        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(side_effect=Exception("Connection timeout"))
            mock_cls.return_value = mock_client

            from api.plagiarism import check_plagiarism
            result = await check_plagiarism("<p>Content.</p>")

    assert result["plagiarism_flagged"] is False
    assert result["max_similarity"] == 0.0
    assert result["matches"] == []


@pytest.mark.asyncio
async def test_check_plagiarism_truncates_to_1000_words():
    long_html = "<p>" + " ".join(["word"] * 1500) + "</p>"

    captured_data = {}

    async def mock_post(url, data=None, **kwargs):
        captured_data["text"] = data.get("t", "")
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"result": []}
        return mock_resp

    with patch("api.plagiarism.settings") as s:
        s.COPYSCAPE_USERNAME = "user"
        s.COPYSCAPE_API_KEY = "key"
        s.PLAGIARISM_THRESHOLD = 15.0
        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(side_effect=mock_post)
            mock_cls.return_value = mock_client

            from api.plagiarism import check_plagiarism
            await check_plagiarism(long_html)

    submitted_words = captured_data["text"].split()
    assert len(submitted_words) <= 1000
