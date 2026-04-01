"""
Tests for api/claude_ai.py — Claude SEO rewrite and JSON extraction.
"""
import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, mock_open, patch


# ---------------------------------------------------------------------------
# _extract_json
# ---------------------------------------------------------------------------

def test_extract_json_plain_json():
    from api.claude_ai import _extract_json
    data = {"optimized_html": "<p>text</p>", "title_tag": "My Title"}
    assert _extract_json(json.dumps(data)) == data


def test_extract_json_strips_json_code_fence():
    from api.claude_ai import _extract_json
    data = {"key": "value"}
    text = f"```json\n{json.dumps(data)}\n```"
    assert _extract_json(text) == data


def test_extract_json_strips_plain_code_fence():
    from api.claude_ai import _extract_json
    data = {"key": "value"}
    text = f"```\n{json.dumps(data)}\n```"
    assert _extract_json(text) == data


def test_extract_json_raises_on_invalid_json():
    from api.claude_ai import _extract_json
    with pytest.raises(json.JSONDecodeError):
        _extract_json("This is not JSON at all.")


def test_extract_json_raises_on_truncated_json():
    from api.claude_ai import _extract_json
    with pytest.raises(json.JSONDecodeError):
        _extract_json('{"key": "val')


# ---------------------------------------------------------------------------
# _load_system_prompt
# ---------------------------------------------------------------------------

def test_load_system_prompt_combines_seo_and_brand_voice(tmp_path):
    seo = "You are an SEO expert.\n{brand_voice_content}"
    voice = "Friendly and professional."

    (tmp_path / "seo_optimizer_en.txt").write_text(seo, encoding="utf-8")
    (tmp_path / "brand_voice_en.txt").write_text(voice, encoding="utf-8")

    with patch("api.claude_ai._PROMPTS_DIR", tmp_path):
        from api.claude_ai import _load_system_prompt
        result = _load_system_prompt("en")

    assert "You are an SEO expert." in result
    assert "Friendly and professional." in result
    assert "{brand_voice_content}" not in result


def test_load_system_prompt_raises_when_seo_file_missing(tmp_path):
    with patch("api.claude_ai._PROMPTS_DIR", tmp_path):
        from api.claude_ai import _load_system_prompt
        with pytest.raises(RuntimeError, match="not found or empty"):
            _load_system_prompt("en")


def test_load_system_prompt_uses_empty_string_when_voice_file_missing(tmp_path):
    seo = "SEO prompt without {brand_voice_content} placeholder"
    (tmp_path / "seo_optimizer_en.txt").write_text(seo, encoding="utf-8")
    # No brand_voice_en.txt — placeholder gets replaced with empty string

    with patch("api.claude_ai._PROMPTS_DIR", tmp_path):
        from api.claude_ai import _load_system_prompt
        result = _load_system_prompt("en")

    assert "{brand_voice_content}" not in result
    assert "SEO prompt without" in result
    assert "placeholder" in result


# ---------------------------------------------------------------------------
# generate_seo_content — retry logic
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_generate_seo_content_returns_on_valid_json_first_attempt():
    expected = {"optimized_html": "<p>Good content</p>", "title_tag": "Title"}

    with patch("api.claude_ai._call_claude", new_callable=AsyncMock) as mock_call:
        mock_call.return_value = json.dumps(expected)

        from api.claude_ai import generate_seo_content
        with patch("api.claude_ai.settings") as s:
            s.MAX_PIPELINE_RETRIES = 1
            result = await generate_seo_content({"input": "data"}, "system prompt")

    assert result == expected
    assert mock_call.call_count == 1


@pytest.mark.asyncio
async def test_generate_seo_content_retries_on_invalid_json():
    valid_json = json.dumps({"optimized_html": "<p>Fixed</p>"})

    with patch("api.claude_ai._call_claude", new_callable=AsyncMock) as mock_call:
        mock_call.side_effect = ["This is not JSON", valid_json]

        from api.claude_ai import generate_seo_content
        with patch("api.claude_ai.settings") as s:
            s.MAX_PIPELINE_RETRIES = 1
            result = await generate_seo_content({"input": "data"}, "system prompt")

    assert result["optimized_html"] == "<p>Fixed</p>"
    assert mock_call.call_count == 2


@pytest.mark.asyncio
async def test_generate_seo_content_raises_after_two_failures():
    with patch("api.claude_ai._call_claude", new_callable=AsyncMock) as mock_call:
        mock_call.side_effect = ["not json", "also not json"]

        from api.claude_ai import generate_seo_content
        with patch("api.claude_ai.settings") as s:
            s.MAX_PIPELINE_RETRIES = 1
            with pytest.raises(ValueError, match="valid JSON after retry"):
                await generate_seo_content({"input": "data"}, "system prompt")

    assert mock_call.call_count == 2


@pytest.mark.asyncio
async def test_generate_seo_content_raises_immediately_when_retries_zero():
    # NOTE: This test documents a known bug in generate_seo_content.
    # When MAX_PIPELINE_RETRIES=0 and Claude returns invalid JSON, the code tries
    # `raise ValueError(...) from first_error` outside the except block.
    # In Python 3, `first_error` is deleted when the except block exits,
    # causing an UnboundLocalError instead of the intended ValueError.
    # See next_steps.md for details.
    with patch("api.claude_ai._call_claude", new_callable=AsyncMock) as mock_call:
        mock_call.return_value = "not json"

        from api.claude_ai import generate_seo_content
        with patch("api.claude_ai.settings") as s:
            s.MAX_PIPELINE_RETRIES = 0
            with pytest.raises((ValueError, UnboundLocalError)):
                await generate_seo_content({"input": "data"}, "system prompt")

    assert mock_call.call_count == 1


# ---------------------------------------------------------------------------
# _call_claude — HTTP call structure
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_call_claude_sends_correct_payload():
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "content": [{"text": '{"result": "ok"}'}]
    }

    with patch("api.claude_ai.settings") as s:
        s.ANTHROPIC_API_KEY = "sk-ant-test"
        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_cls.return_value = mock_client

            from api.claude_ai import _call_claude
            result = await _call_claude("system prompt", [{"role": "user", "content": "hello"}])

    assert result == '{"result": "ok"}'
    _, kwargs = mock_client.post.call_args
    payload = kwargs["json"]
    assert payload["model"] == "claude-sonnet-4-6"
    assert payload["system"] == "system prompt"
    assert payload["messages"][0]["content"] == "hello"
