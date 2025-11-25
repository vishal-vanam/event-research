# app/providers/agentql_events.py
from __future__ import annotations

import logging
from typing import List

import httpx

from app.config import settings
from app.models import WebResult

logger = logging.getLogger(__name__)


class AgentQLEventsProvider:
    """
    Tiny Fish / AgentQL-based deep research provider.

    Uses AgentQL REST API (query-data) to scrape an events page
    (right now we use Eventbrite's city page as a simple default).
    """

    name = "agentql"

    def __init__(self) -> None:
        self.api_key = settings.agentql_api_key
        if not self.api_key:
            logger.warning(
                "AgentQL API key (AGENTQL_API_KEY) not set; AgentQLEventsProvider will return no results."
            )

    def _build_city_events_url(self, city: str) -> str:
        """
        Simple heuristic: map 'Jersey City' -> 'jersey-city' and hit Eventbrite city page.
        You can tweak this later if you prefer another site.
        """
        slug = city.strip().lower().replace(",", "").replace(" ", "-")
        # US-centered for now; adjust if needed
        return f"https://www.eventbrite.com/d/united-states--{slug}/events/"

    def search_city_events(self, city: str, days_ahead: int = 7, limit: int = 20) -> List[WebResult]:
        """
        Use AgentQL REST API to extract 'events' from an Eventbrite city page.

        This is best-effort and meant as a deep-research complement to Ticketmaster.
        """
        if not self.api_key:
            return []

        url = self._build_city_events_url(city)

        # AgentQL query: define a structured output.
        # AgentQL will try to find matching data on the page.
        aql_query = """
        {
          events[] {
            title
            date
            location
            url
          }
        }
        """

        payload = {
            "query": aql_query,
            "url": url,
            "params": {
                "wait_for": 2,
                "is_scroll_to_bottom_enabled": True,
                "mode": "fast",
                "is_screenshot_enabled": False,
            },
        }

        headers = {
            "X-API-Key": self.api_key,
            "Content-Type": "application/json",
        }

        logger.info(
            "AgentQLEventsProvider.search_city_events: city=%r url=%r days_ahead=%d limit=%d",
            city,
            url,
            days_ahead,
            limit,
        )

        try:
            resp = httpx.post(
                "https://api.agentql.com/v1/query-data",
                headers=headers,
                json=payload,
                timeout=60,
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            logger.error("AgentQL query-data request failed: %s", exc)
            return []

        data = resp.json().get("data", {})
        raw_events = data.get("events", []) or []

        results: List[WebResult] = []
        for item in raw_events[:limit]:
            title = item.get("title") or "Untitled event"
            event_url = item.get("url") or url
            date = item.get("date")
            location = item.get("location")

            snippet_parts = []
            if date:
                snippet_parts.append(f"Date: {date}")
            if location:
                snippet_parts.append(f"Location: {location}")
            snippet = " | ".join(snippet_parts) if snippet_parts else None

            results.append(
                WebResult(
                    source=self.name,
                    title=title,
                    url=event_url,
                    snippet=snippet,
                    page_age=None,
                )
            )

        logger.info("AgentQLEventsProvider: parsed %d web results", len(results))
        return results
