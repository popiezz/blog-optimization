"""
Step 6 — Claude rewrite + metadata generation.

Loads language-specific SEO system prompt + brand voice, sends all upstream
context in a single structured prompt, and returns a validated JSON object.

On invalid JSON, retries once with an explicit correction prompt before
propagating the failure to the pipeline orchestrator.
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict

import httpx

from config.settings import settings

logger = logging.getLogger(__name__)

_CLAUDE_API_URL = "https://api.anthropic.com/v1/messages"
_MODEL = "claude-sonnet-4-6"
_MAX_TOKENS = 4096
_TIMEOUT = 120.0  # seconds — full blog rewrite can be slow

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"

_CORRECTION_PROMPT = (
    "Your previous response was not valid JSON. "
    "Return ONLY a valid JSON object with no markdown, no backticks, no comments, "
    "and no text before or after the object. "
    "Here is what you returned:\n\n{previous_response}"
)


# ---------------------------------------------------------------------------
# Prompt loading
# ---------------------------------------------------------------------------

def _load_system_prompt(language: str) -> str:
    """
    Combines the SEO system prompt with the brand voice file for the given language.
    Files are read fresh on every call so the colleague can update them without
    redeploying the application.
    """
    seo_file = _PROMPTS_DIR / f"seo_optimizer_{language}.txt"
    voice_file = _PROMPTS_DIR / f"brand_voice_{language}.txt"

    seo_prompt = _read_prompt_file(seo_file, f"SEO optimizer ({language})")
    brand_voice = _read_prompt_file(voice_file, f"brand voice ({language})")

    if not seo_prompt:
        raise RuntimeError(
            f"SEO system prompt file not found or empty: {seo_file}. "
            "Please ensure prompts/seo_optimizer_fr.txt and prompts/seo_optimizer_en.txt exist."
        )

    return seo_prompt.replace("{brand_voice_content}", brand_voice)


def _read_prompt_file(path: Path, label: str) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        logger.warning("Prompt file not found: %s (%s)", path, label)
        return ""
    except Exception as exc:
        logger.error("Failed to read prompt file %s: %s", path, exc)
        return ""


# ---------------------------------------------------------------------------
# Raw API call
# ---------------------------------------------------------------------------

def _build_headers() -> Dict[str, str]:
    return {
        "x-api-key": settings.ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }


async def _call_claude(
    system_prompt: str,
    messages: list,
) -> str:
    """Calls the Claude API and returns the raw text response."""
    payload = {
        "model": _MODEL,
        "max_tokens": _MAX_TOKENS,
        "system": system_prompt,
        "messages": messages,
    }
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        response = await client.post(_CLAUDE_API_URL, headers=_build_headers(), json=payload)
        response.raise_for_status()

    data = response.json()
    return data["content"][0]["text"]


# ---------------------------------------------------------------------------
# JSON extraction (handles accidental markdown wrapping)
# ---------------------------------------------------------------------------

def _extract_json(text: str) -> Dict[str, Any]:
    """
    Parses JSON from a Claude response.  Strips leading/trailing markdown
    code fences if present before parsing.
    """
    stripped = text.strip()
    # Remove ```json ... ``` or ``` ... ``` wrappers
    if stripped.startswith("```"):
        lines = stripped.split("\n")
        # Remove first line (```json or ```) and last line (```)
        inner = "\n".join(lines[1:-1]) if lines[-1].strip() == "```" else "\n".join(lines[1:])
        stripped = inner.strip()
    return json.loads(stripped)


# ---------------------------------------------------------------------------
# Low-level call with retry
# ---------------------------------------------------------------------------

async def generate_seo_content(
    prompt_context: Dict[str, Any],
    system_prompt: str,
) -> Dict[str, Any]:
    """
    Sends the SEO context JSON to Claude.  Retries once with a correction
    prompt if the first response is not valid JSON.
    """
    user_message = json.dumps(prompt_context, ensure_ascii=False)
    messages = [{"role": "user", "content": user_message}]

    raw_response = await _call_claude(system_prompt, messages)

    try:
        return _extract_json(raw_response)
    except (json.JSONDecodeError, ValueError) as first_error:
        logger.warning(
            "Claude returned invalid JSON on attempt 1: %s. Retrying with correction prompt.",
            first_error,
        )

    # Retry: include the bad response and ask Claude to fix it
    if settings.MAX_PIPELINE_RETRIES < 1:
        raise ValueError(f"Claude returned invalid JSON and MAX_PIPELINE_RETRIES=0.") from first_error

    correction = _CORRECTION_PROMPT.format(previous_response=raw_response[:2000])
    messages = [
        {"role": "user", "content": user_message},
        {"role": "assistant", "content": raw_response},
        {"role": "user", "content": correction},
    ]

    raw_response2 = await _call_claude(system_prompt, messages)

    try:
        return _extract_json(raw_response2)
    except (json.JSONDecodeError, ValueError) as second_error:
        logger.error(
            "Claude returned invalid JSON on attempt 2 as well. Raw response: %s",
            raw_response2[:500],
        )
        raise ValueError("Claude failed to produce valid JSON after retry.") from second_error


# ---------------------------------------------------------------------------
# High-level helper used by the pipeline
# ---------------------------------------------------------------------------

async def run_seo_rewrite(
    *,
    title: str,
    body_html: str,
    language: str,
    main_keyword: str,
    secondary_keywords: list,
    question_keywords: list,
    lsi_keywords: list,
    suggested_headings: list,
    competitor_heading_structure: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Assembles all SEO context, loads the appropriate system prompt, calls
    Claude, and returns the validated JSON output.

    Expected output keys:
        optimized_html, title_tag, meta_description, slug, og_title,
        og_description, schema_markup, alt_texts,
        internal_link_suggestions, changes_summary
    """
    system_prompt = _load_system_prompt(language)

    prompt_context = {
        "title": title,
        "body_html": body_html,
        "language": language,
        "main_keyword": main_keyword,
        "secondary_keywords": secondary_keywords,
        "lsi_keywords": lsi_keywords,
        "question_keywords": question_keywords,
        "suggested_headings": suggested_headings,
        "competitor_heading_structure": competitor_heading_structure,
    }

    return await generate_seo_content(prompt_context, system_prompt)
