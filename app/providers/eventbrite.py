from datetime import datetime
from typing import List
import logging

import httpx

from app.models import Event
from app.providers.base import EventProvider
from app.config import settings

logger = logging.getLogger(__name__)


class EventbriteProvider:
    name = "eventbrite"

    def __init__(self) -> None:
        self.token = settings.eventbrite_token
        if not self.token:
            logger.warning("Eventbrite token not set; provider will return no events.")

    def get_events(
        self,
        city: str,
        latitude: float,
        longitude: float,
        start: datetime,
        end: datetime,
        radius_km: int,
    ) -> List[Event]:
        if not self.token:
            return []

        url = "https://www.eventbriteapi.com/v3/events/search/"

        params = {
            "location.latitude": latitude,
            "location.longitude": longitude,
            "location.within": f"{radius_km}km",
            "expand": "venue",
        }

        headers = {
            "Authorization": f"Bearer {self.token}",
        }

        logger.info(
            "EventbriteProvider.get_events: token_set=%s lat=%s lon=%s radius=%s",
            bool(self.token),
            latitude,
            longitude,
            radius_km,
        )

        try:
            resp = httpx.get(url, params=params, headers=headers, timeout=10)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            logger.error("Eventbrite API request failed: %s", exc)
            return []

        data = resp.json()
        raw_events = data.get("events", [])

        events: List[Event] = []

        for item in raw_events:
            try:
                start_dt_raw = item.get("start", {}).get("utc")
                if not start_dt_raw:
                    continue
                start_dt = datetime.fromisoformat(start_dt_raw.replace("Z", "+00:00"))

                venue = item.get("venue", {}) or {}
                lat = venue.get("latitude")
                lon = venue.get("longitude")

                events.append(
                    Event(
                        id=f"eventbrite-{item['id']}",
                        source="eventbrite",
                        name=item.get("name", {}).get("text", "Unknown event"),
                        start_time=start_dt,
                        end_time=None,
                        venue_name=venue.get("name"),
                        city=venue.get("address", {}).get("city"),
                        country=venue.get("address", {}).get("country"),
                        lat=float(lat) if lat else None,
                        lon=float(lon) if lon else None,
                        category=None,
                        url=item.get("url"),
                        price_min=None,
                        price_max=None,
                    )
                )
            except Exception as exc:
                logger.warning(
                    "Failed to parse Eventbrite event %s: %s",
                    item.get("id"),
                    exc,
                )

        logger.info("EventbriteProvider: parsed %d events", len(events))
        return events
