"""
Tests for api/surfer.py — SurferSEO content scoring.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call


# ---------------------------------------------------------------------------
# poll_surfer_score
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_poll_surfer_score_returns_on_done_status():
    done_response = MagicMock()
    done_response.raise_for_status = MagicMock()
    done_response.json.return_value = {
        "status": "done",
        "content_score": 72,
        "lsi_keywords": ["keyword1", "keyword2"],
        "suggested_headings": ["How to X", "Why Y"],
    }

    with patch("api.surfer.settings") as s:
        s.SURFER_BASE_URL = "https://api.surferseo.com/v1"
        s.SURFER_API_KEY = "test_key"
        s.SURFER_POLL_INTERVAL_SECONDS = 0
        s.SURFER_POLL_MAX_ATTEMPTS = 3
        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=done_response)
            mock_cls.return_value = mock_client

            from api.surfer import poll_surfer_score
            result = await poll_surfer_score("doc123")

    assert result["content_score"] == 72
    assert result["lsi_keywords"] == ["keyword1", "keyword2"]
    assert result["suggested_headings"] == ["How to X", "Why Y"]


@pytest.mark.asyncio
async def test_poll_surfer_score_retries_until_done():
    pending = MagicMock()
    pending.raise_for_status = MagicMock()
    pending.json.return_value = {"status": "pending"}

    done = MagicMock()
    done.raise_for_status = MagicMock()
    done.json.return_value = {
        "status": "done",
        "content_score": 60,
        "lsi_keywords": [],
        "suggested_headings": [],
    }

    with patch("api.surfer.settings") as s:
        s.SURFER_BASE_URL = "https://api.surferseo.com/v1"
        s.SURFER_API_KEY = "test_key"
        s.SURFER_POLL_INTERVAL_SECONDS = 0
        s.SURFER_POLL_MAX_ATTEMPTS = 3
        with patch("asyncio.sleep", new_callable=AsyncMock):
            with patch("httpx.AsyncClient") as mock_cls:
                mock_client = AsyncMock()
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=False)
                mock_client.get = AsyncMock(side_effect=[pending, pending, done])
                mock_cls.return_value = mock_client

                from api.surfer import poll_surfer_score
                result = await poll_surfer_score("doc123")

    assert result["content_score"] == 60
    assert mock_client.get.call_count == 3


@pytest.mark.asyncio
async def test_poll_surfer_score_raises_timeout_after_max_attempts():
    pending = MagicMock()
    pending.raise_for_status = MagicMock()
    pending.json.return_value = {"status": "pending"}

    with patch("api.surfer.settings") as s:
        s.SURFER_BASE_URL = "https://api.surferseo.com/v1"
        s.SURFER_API_KEY = "test_key"
        s.SURFER_POLL_INTERVAL_SECONDS = 0
        s.SURFER_POLL_MAX_ATTEMPTS = 3
        with patch("asyncio.sleep", new_callable=AsyncMock):
            with patch("httpx.AsyncClient") as mock_cls:
                mock_client = AsyncMock()
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=False)
                mock_client.get = AsyncMock(return_value=pending)
                mock_cls.return_value = mock_client

                from api.surfer import poll_surfer_score
                with pytest.raises(TimeoutError):
                    await poll_surfer_score("doc123")


# ---------------------------------------------------------------------------
# get_final_surfer_score — score delta calculation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_final_surfer_score_calculates_delta_correctly():
    with patch("api.surfer.update_surfer_content", new_callable=AsyncMock) as mock_update, \
         patch("api.surfer.trigger_surfer_optimization", new_callable=AsyncMock), \
         patch("api.surfer.poll_surfer_score", new_callable=AsyncMock) as mock_poll:

        mock_poll.return_value = {
            "content_score": 75,
            "lsi_keywords": [],
            "suggested_headings": [],
        }

        from api.surfer import get_final_surfer_score
        result = await get_final_surfer_score("doc123", "<p>content</p>", 50.0)

    assert result["initial_score"] == 50.0
    assert result["final_score"] == 75
    assert result["score_delta"] == 25.0
    assert abs(result["score_delta_pct"] - 50.0) < 0.01  # 25/50 * 100 = 50%


@pytest.mark.asyncio
async def test_get_final_surfer_score_zero_initial_no_division_error():
    with patch("api.surfer.update_surfer_content", new_callable=AsyncMock), \
         patch("api.surfer.trigger_surfer_optimization", new_callable=AsyncMock), \
         patch("api.surfer.poll_surfer_score", new_callable=AsyncMock) as mock_poll:

        mock_poll.return_value = {
            "content_score": 40,
            "lsi_keywords": [],
            "suggested_headings": [],
        }

        from api.surfer import get_final_surfer_score
        result = await get_final_surfer_score("doc123", "<p>content</p>", 0.0)

    assert result["score_delta_pct"] == 0.0  # no division by zero


# ---------------------------------------------------------------------------
# get_initial_surfer_score — doc ID extraction
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_initial_surfer_score_raises_on_missing_doc_id():
    with patch("api.surfer.create_surfer_document", new_callable=AsyncMock) as mock_create:
        mock_create.return_value = {}  # no "id" key

        from api.surfer import get_initial_surfer_score
        with pytest.raises(ValueError, match="document ID"):
            await get_initial_surfer_score("keyword", "en", "<p>html</p>")


@pytest.mark.asyncio
async def test_get_initial_surfer_score_reads_nested_data_id():
    with patch("api.surfer.create_surfer_document", new_callable=AsyncMock) as mock_create, \
         patch("api.surfer.update_surfer_content", new_callable=AsyncMock), \
         patch("api.surfer.trigger_surfer_optimization", new_callable=AsyncMock), \
         patch("api.surfer.poll_surfer_score", new_callable=AsyncMock) as mock_poll:

        mock_create.return_value = {"data": {"id": "nested_doc_id"}}
        mock_poll.return_value = {
            "content_score": 55,
            "lsi_keywords": ["lsi1"],
            "suggested_headings": ["h2 suggestion"],
        }

        from api.surfer import get_initial_surfer_score
        result = await get_initial_surfer_score("keyword", "en", "<p>html</p>")

    assert result["surfer_doc_id"] == "nested_doc_id"
    assert result["initial_score"] == 55
