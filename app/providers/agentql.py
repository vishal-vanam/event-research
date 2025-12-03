from __future__ import annotations

import json
import logging
from typing import List

import httpx

from app.config import settings
from app.models import WebResult

logger = logging.getLogger(__name__)


class AgentQLEventsProvider:
    """
    Tiny Fish / AgentQL-based deep research provider.

    Uses AgentQL REST API (query-data) to scrape an events page.
    Right now we target Eventbrite's city listings as a simple default.
    """

    name = "agentql"

    def __init__(self) -> None:
        self.api_key = settings.agentql_api_key
        if not self.api_key:
            logger.warning(
                "AgentQL API key (AGENTQL_API_KEY) not set; AgentQLEventsProvider will return no results."
            )

    @staticmethod
    def _build_city_events_url(city: str) -> str:
        """
        Map "Philadelphia, PA" -> "philadelphia" slug and build Eventbrite URL:
        https://www.eventbrite.com/d/united-states--philadelphia/events/
        """
        city_only = city.split(",")[0].strip().lower()
        slug = city_only.replace(" ", "-")
        return f"https://www.eventbrite.com/d/united-states--{slug}/events/"

    def search_city_events(
        self,
        city: str,
        days_ahead: int = 7,
        limit: int = 20,
    ) -> List[WebResult]:
        """
        Use AgentQL REST API (prompt mode) to extract events (title + url)
        from an Eventbrite city listing page.

        This is best-effort and meant as a deep-research complement.
        """
        if not self.api_key:
            return []

        url = self._build_city_events_url(city)

        # Prompt-based extraction: let AgentQL infer the structure.
        # IMPORTANT: no { } braces in this string, so it's safe as a normal str.
        prompt = (
            "You are extracting upcoming public events from this Eventbrite city listing page.\n"
            "Return a JSON object with a top-level key 'events'.\n"
            "The 'events' value must be a list (array) of objects.\n"
            "Each object must have:\n"
            "- 'title': the event name as a string\n"
            "- 'url': the event detail URL as a string\n"
            "Only include real events that link to an event detail page.\n"
            "If you cannot find any events, return {\"events\": []}."
        )

        payload = {
            "prompt": prompt,
            "url": url,
            "params": {
                # Give the page a little time to load; tweak if needed
                "wait_for": 3,
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
        except httpx.HTTPStatusError as exc:
            # This will catch 4xx/5xx, incl. 422
            text_preview = exc.response.text[:500] if exc.response is not None else ""
            logger.error(
                "AgentQL query-data HTTP error: %s, response snippet=%r",
                exc,
                text_preview,
            )
            return []
        except httpx.HTTPError as exc:
            logger.error("AgentQL query-data request failed (network): %s", exc)
            return []

        body = resp.json()
        data = body.get("data")

        if not isinstance(data, dict):
            logger.warning(
                "AgentQL response 'data' is not a dict. Top-level keys: %r",
                list(body.keys()),
            )
            return []

        raw_events = data.get("events") or []
        if not isinstance(raw_events, list):
            logger.warning(
                "AgentQL 'events' is not a list. Type: %s, value: %r",
                type(raw_events),
                raw_events,
            )
            return []

        results: List[WebResult] = []
        for item in raw_events[:limit]:
            if not isinstance(item, dict):
                continue
            title = item.get("title") or "Untitled event"
            event_url = item.get("url") or url

            results.append(
                WebResult(
                    source=self.name,
                    title=title,
                    url=event_url,
                    snippet=None,
                    page_age=None,
                )
            )

        logger.info(
            "AgentQLEventsProvider: parsed %d web results (city=%r)",
            len(results),
            city,
        )

        # Extra debug: if we got 0 results, log a small sample of data for debugging
        if not results:
            logger.warning(
                "AgentQLEventsProvider: 0 events parsed for city=%r. "
                "Sample of 'data' key: %s",
                city,
                json.dumps(data, indent=2)[:1000],
            )
