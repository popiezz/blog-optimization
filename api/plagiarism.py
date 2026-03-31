import httpx
from typing import Dict, Any, List
from config.settings import settings
import logging

logger = logging.getLogger(__name__)

async def check_plagiarism(html_content: str) -> Dict[str, Any]:
    """
    Runs a similarity check against the web using Copyscape API.
    """
    url = "https://www.copyscape.com/api/"
    params = {
        "u": settings.COPYSCAPE_USERNAME,
        "k": settings.COPYSCAPE_API_KEY,
        "o": "csearch",
        "t": html_content,
        "f": "json"
    }
    
    async with httpx.AsyncClient() as client:
        # Copyscape uses POST with params in body for csearch
        response = await client.post(url, data=params)
        response.raise_for_status()
        
        data = response.json()
        
        # Parse the results
        matches = data.get("result", [])
        max_similarity = 0.0
        
        if matches:
            # Simple max similarity calculation if provided by API, 
            # or based on count of matching words.
            # This is a simplification of the actual API response processing.
            max_similarity = max([float(m.get("minper", 0)) for m in matches]) if matches else 0
            
        return {
            "plagiarism_flagged": max_similarity > settings.PLAGIARISM_THRESHOLD,
            "max_similarity": max_similarity,
            "matches": matches
        }
