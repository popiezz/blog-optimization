import httpx
import json
from typing import Dict, Any, Optional
from config.settings import settings
import logging

logger = logging.getLogger(__name__)

async def generate_seo_content(prompt_context: Dict[str, Any], system_prompt: str) -> Dict[str, Any]:
    """
    Sends the SEO context and system prompt to Claude and expects a JSON response.
    """
    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": settings.ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json"
    }
    
    user_message = json.dumps(prompt_context)
    
    payload = {
        "model": "claude-3-5-sonnet-20240620", # Updated from README's dated version to a current one
        "max_tokens": 4000,
        "system": system_prompt,
        "messages": [
            {"role": "user", "content": user_message}
        ]
    }
    
    async with httpx.AsyncClient() as client:
        response = await client.post(url, headers=headers, json=payload, timeout=60.0)
        response.raise_for_status()
        
        data = response.json()
        raw_text = data["content"][0]["text"]
        
        # Parse the JSON from the text response
        try:
            return json.loads(raw_text)
        except json.JSONDecodeError:
            logger.error("Failed to parse Claude response as JSON.")
            # In a real scenario, you would implement the retry logic here
            raise
