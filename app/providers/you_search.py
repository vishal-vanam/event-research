from typing import List
import logging

import httpx

from app.models import WebResult
from app.config import settings

logger = logging.getLogger(__name__)


class YouSearchProvider:
    name = "you-search"

    def __init__(self) -> None:
        self.api_key = settings.you_api_key
        if not self.api_key:
            logger.warning("You.com API key (YDC_API_KEY) not set; YouSearchProvider will return no results.")

    def search_city_events(self, city: str, days_ahead: int = 7, limit: int = 10) -> List[WebResult]:
        if not self.api_key:
            return []

        query = f"events in {city} in the next {days_ahead} days"

        # ✅ Use documented host + path
        url = "https://ydc-index.io/v1/search"
        params = {
            "query": query,
            "count": limit,   # ✅ matches docs instead of num_web_results
        }
        headers = {
            "X-API-Key": self.api_key,
        }

        logger.info("YouSearchProvider.search_city_events: query=%r", query)

        try:
            resp = httpx.get(url, params=params, headers=headers, timeout=10)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            logger.error("You.com Search API request failed: %s", exc)
            return []

        data = resp.json()
        results_block = data.get("results", {})
        web_hits = results_block.get("web", [])  # per docs: results.web[...] 

        results: List[WebResult] = []
        for item in web_hits:
            try:
                results.append(
                    WebResult(
                        source="you-search",
                        title=item.get("title") or item.get("url", "Untitled"),
                        url=item.get("url", ""),
                        snippet=(item.get("description") or
                                 (item.get("snippets") or [None])[0]),
                        page_age=item.get("page_age"),
                    )
                )
            except Exception as exc:
                logger.warning("Failed to parse You.com hit: %s", exc)

        logger.info("YouSearchProvider: parsed %d web results", len(results))
        return results
