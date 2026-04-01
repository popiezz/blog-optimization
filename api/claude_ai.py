import httpx
import json
from typing import Dict, Any, Optional
from config.settings import settings
import logging

logger = logging.getLogger(__name__)

async def generate_seo_content(prompt_context: Dict[str, Any], system_prompt: str, article_id: str = "Unknown") -> Dict[str, Any]:
    """
    Sends the SEO context and system prompt to Claude and expects a JSON response.
    Includes retry logic if the response is not valid JSON.
    """
    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": settings.ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json"
    }
    
    user_message = json.dumps(prompt_context)
    
    messages = [
        {"role": "user", "content": user_message}
    ]

    payload = {
        "model": "claude-3-5-sonnet-20241022", # Production target model as per README
        "max_tokens": 4000,
        "system": system_prompt,
        "messages": messages
    }
    
    async with httpx.AsyncClient() as client:
        for attempt in range(settings.MAX_PIPELINE_RETRIES + 1):
            logger.info(f"[Article {article_id}] Calling Claude API (attempt {attempt + 1}/{settings.MAX_PIPELINE_RETRIES + 1})")
            response = await client.post(url, headers=headers, json=payload, timeout=60.0)
            response.raise_for_status()

            data = response.json()
            raw_text = data["content"][0]["text"]

            # Parse the JSON from the text response
            try:
                # Strip out any markdown formatting that Claude might have added around the JSON block
                clean_text = raw_text.strip()
                if clean_text.startswith("```json"):
                    clean_text = clean_text[7:]
                if clean_text.endswith("```"):
                    clean_text = clean_text[:-3]
                clean_text = clean_text.strip()

                return json.loads(clean_text)
            except json.JSONDecodeError:
                logger.warning(f"[Article {article_id}] Failed to parse Claude response as JSON. Raw text preview: {raw_text[:200]}...")

                if attempt < settings.MAX_PIPELINE_RETRIES:
                    logger.info(f"[Article {article_id}] Retrying Claude API with JSON correction prompt...")
                    # Append the assistant's previous invalid response and a new user prompt explicitly requesting valid JSON
                    payload["messages"].append({"role": "assistant", "content": raw_text})
                    payload["messages"].append({
                        "role": "user",
                        "content": "Your previous response was not valid JSON. Please rewrite your response and ensure it is strictly valid JSON format, with no markdown formatting, no backticks, no preamble, and no trailing text."
                    })
                else:
                    logger.error(f"[Article {article_id}] Max retries reached. Failing sequence.")
                    raise ValueError("Failed to obtain valid JSON from Claude after max retries")
