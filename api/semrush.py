import httpx
from typing import Dict, List, Any
from config.settings import settings
import logging

logger = logging.getLogger(__name__)

async def semrush_keyword_overview(keyword: str, database: str = "us") -> Dict[str, Any]:
    """
    Fetches volume, KD, and CPC for a seed keyword.
    """
    params = {
        "key": settings.SEMRUSH_API_KEY,
        "type": "phrase_this",
        "phrase": keyword,
        "database": database,
        "export_columns": "Ph,Vi,Kd,Cp"
    }
    
    async with httpx.AsyncClient() as client:
        response = await client.get("https://api.semrush.com/", params=params)
        response.raise_for_status()
        # Parse SEMrush CSV-like response
        # Row 1: Ph;Vi;Kd;Cp
        # Row 2: keyword;volume;kd;cpc
        data = response.text.splitlines()
        if len(data) < 2:
            return {}
        
        values = data[1].split(";")
        return {
            "keyword": values[0],
            "volume": int(values[1]),
            "difficulty": float(values[2]),
            "cpc": float(values[3])
        }

async def semrush_related_keywords(keyword: str, database: str = "us", limit: int = 10) -> List[Dict[str, Any]]:
    """
    Fetches related keywords by volume/KD ratio.
    """
    params = {
        "key": settings.SEMRUSH_API_KEY,
        "type": "phrase_related",
        "phrase": keyword,
        "database": database,
        "export_columns": "Ph,Vi,Kd",
        "display_limit": limit
    }
    
    async with httpx.AsyncClient() as client:
        response = await client.get("https://api.semrush.com/", params=params)
        response.raise_for_status()
        
        lines = response.text.splitlines()
        results = []
        for line in lines[1:]: # Skip header
            values = line.split(";")
            results.append({
                "keyword": values[0],
                "volume": int(values[1]),
                "difficulty": float(values[2])
            })
        return results

async def semrush_question_keywords(keyword: str, database: str = "us", limit: int = 5) -> List[str]:
    """
    Fetches question-format keywords for H2 suggestions.
    """
    params = {
        "key": settings.SEMRUSH_API_KEY,
        "type": "phrase_questions",
        "phrase": keyword,
        "database": database,
        "export_columns": "Ph",
        "display_limit": limit
    }
    
    async with httpx.AsyncClient() as client:
        response = await client.get("https://api.semrush.com/", params=params)
        response.raise_for_status()
        
        lines = response.text.splitlines()
        return [line.strip() for line in lines[1:]]
