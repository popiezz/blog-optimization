"""
Tests for api/asana.py — task creation, formatting helpers, and business day logic.
"""
import pytest
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# _next_business_day
# ---------------------------------------------------------------------------

def test_next_business_day_returns_tomorrow_on_weekday():
    from api.asana import _next_business_day
    # Thursday → Friday
    with patch("api.asana.date") as mock_date:
        mock_date.today.return_value = date(2026, 4, 2)  # Thursday
        mock_date.side_effect = lambda *args, **kwargs: date(*args, **kwargs)
        result = _next_business_day()
    assert result == "2026-04-03"


def test_next_business_day_skips_saturday_and_sunday():
    from api.asana import _next_business_day
    # Friday → skip Sat/Sun → Monday
    with patch("api.asana.date") as mock_date:
        mock_date.today.return_value = date(2026, 4, 3)  # Friday
        mock_date.side_effect = lambda *args, **kwargs: date(*args, **kwargs)
        result = _next_business_day()
    assert result == "2026-04-06"  # Monday


def test_next_business_day_skips_sunday():
    from api.asana import _next_business_day
    # Saturday → skip → Monday
    with patch("api.asana.date") as mock_date:
        mock_date.today.return_value = date(2026, 4, 4)  # Saturday
        mock_date.side_effect = lambda *args, **kwargs: date(*args, **kwargs)
        result = _next_business_day()
    assert result == "2026-04-06"  # Monday


# ---------------------------------------------------------------------------
# _format_internal_links
# ---------------------------------------------------------------------------

def test_format_internal_links_empty_list():
    from api.asana import _format_internal_links
    result = _format_internal_links([])
    assert result == "  None suggested."


def test_format_internal_links_single_suggestion():
    from api.asana import _format_internal_links
    suggestions = [{"location": "intro section", "suggested_topic": "shoe sizing guide"}]
    result = _format_internal_links(suggestions)
    assert "intro section" in result
    assert "shoe sizing guide" in result
    assert "•" in result


def test_format_internal_links_multiple_suggestions():
    from api.asana import _format_internal_links
    suggestions = [
        {"location": "section A", "suggested_topic": "topic 1"},
        {"location": "section B", "suggested_topic": "topic 2"},
    ]
    result = _format_internal_links(suggestions)
    lines = result.strip().split("\n")
    assert len(lines) == 2
    assert "topic 1" in lines[0]
    assert "topic 2" in lines[1]


def test_format_internal_links_handles_missing_keys():
    from api.asana import _format_internal_links
    suggestions = [{}]  # no location or suggested_topic keys
    result = _format_internal_links(suggestions)
    assert "•" in result  # should still format without crashing


# ---------------------------------------------------------------------------
# create_approval_task — notes content
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_approval_task_includes_all_key_fields():
    with patch("api.asana.create_asana_task", new_callable=AsyncMock) as mock_create, \
         patch("api.asana._next_business_day", return_value="2026-04-03"):

        mock_create.return_value = {"gid": "task123"}

        from api.asana import create_approval_task
        await create_approval_task(
            article_id="art_001",
            title="How to Choose Running Shoes",
            main_keyword="running shoes",
            main_kw_volume=12000,
            main_kw_difficulty=45.0,
            initial_score=42.0,
            final_score=68.0,
            score_delta_pct=61.9,
            competitor_urls=["https://example.com/article"],
            plagiarism_flagged=False,
            plagiarism_max_similarity=8.3,
            changes_summary="Added keyword to H1, restructured sections.",
            internal_link_suggestions=[],
        )

    _, kwargs = mock_create.call_args
    notes = kwargs.get("notes") or mock_create.call_args[0][1]
    title_arg = kwargs.get("title") or mock_create.call_args[0][0]

    assert "How to Choose Running Shoes" in notes
    assert "running shoes" in notes
    assert "12,000" in notes
    assert "42" in notes and "68" in notes
    assert "+61.9%" in notes
    assert "example.com" in notes
    assert "8.3%" in notes
    assert "APPROVE" in notes
    assert "REJECT" in notes
    assert "SEO APPROVAL:" in title_arg


@pytest.mark.asyncio
async def test_create_approval_task_shows_plagiarism_warning_when_flagged():
    with patch("api.asana.create_asana_task", new_callable=AsyncMock) as mock_create, \
         patch("api.asana._next_business_day", return_value="2026-04-03"):

        mock_create.return_value = {"gid": "task123"}

        from api.asana import create_approval_task
        await create_approval_task(
            article_id="art_002",
            title="Test Article",
            main_keyword="test",
            main_kw_volume=1000,
            main_kw_difficulty=30.0,
            initial_score=30.0,
            final_score=50.0,
            score_delta_pct=66.7,
            competitor_urls=[],
            plagiarism_flagged=True,
            plagiarism_max_similarity=22.5,
            changes_summary="Some changes.",
            internal_link_suggestions=[],
        )

    notes = mock_create.call_args[1].get("notes") or mock_create.call_args[0][1]
    assert "⚠️" in notes
    assert "22.5%" in notes


# ---------------------------------------------------------------------------
# create_failure_task — notes content
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_failure_task_includes_article_info():
    with patch("api.asana.create_asana_task", new_callable=AsyncMock) as mock_create:
        mock_create.return_value = {"gid": "task_fail"}

        from api.asana import create_failure_task
        await create_failure_task(
            title="My Blog Article",
            article_id="art_fail_001",
            reason="SurferSEO API returned 403 Forbidden",
        )

    call_kwargs = mock_create.call_args
    title_arg = call_kwargs[1].get("title") or call_kwargs[0][0]
    notes_arg = call_kwargs[1].get("notes") or call_kwargs[0][1]

    assert "My Blog Article" in title_arg
    assert "❌" in title_arg
    assert "art_fail_001" in notes_arg
    assert "SurferSEO API returned 403 Forbidden" in notes_arg
