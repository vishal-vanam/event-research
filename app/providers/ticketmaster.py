from datetime import datetime
from typing import List
import logging

import httpx

from app.models import Event
from app.providers.base import EventProvider
from app.config import settings

logger = logging.getLogger(__name__)


class TicketmasterProvider:
    name = "ticketmaster"

    def __init__(self) -> None:
        self.api_key = settings.ticketmaster_api_key
        if not self.api_key:
            logger.warning("Ticketmaster API key not set; provider will return no events.")

    def get_events(
        self,
        city: str,
        latitude: float,
        longitude: float,
        start: datetime,
        end: datetime,
        radius_km: int,
    ) -> List[Event]:
        if not self.api_key:
            return []

        url = "https://app.ticketmaster.com/discovery/v2/events.json"

        params = {
            "apikey": self.api_key,
            "latlong": f"{latitude},{longitude}",
            "radius": radius_km,
            "unit": "km",
            # For now we let Ticketmaster default to "upcoming" without explicit dates
        }

        logger.info(
            "TicketmasterProvider.get_events: api_key_set=%s lat=%s lon=%s radius=%s",
            bool(self.api_key),
            latitude,
            longitude,
            radius_km,
        )

        try:
            resp = httpx.get(url, params=params, timeout=10)
        except httpx.HTTPError as exc:
            logger.error("Ticketmaster API request failed (network): %s", exc)
            return []

        if resp.status_code != 200:
            logger.error(
                "Ticketmaster API returned %s: %s",
                resp.status_code,
                resp.text[:500],
            )
            return []

        data = resp.json()
        embedded = data.get("_embedded", {})
        raw_events = embedded.get("events", [])

        events: List[Event] = []

        for item in raw_events:
            try:
                start_dt_raw = item["dates"]["start"]["dateTime"]
                start_dt = datetime.fromisoformat(start_dt_raw.replace("Z", "+00:00"))

                venues = item.get("_embedded", {}).get("venues", [])
                venue = venues[0] if venues else {}
                location = venue.get("location", {}) or {}

                price_ranges = item.get("priceRanges", [])
                price_min = price_ranges[0].get("min") if price_ranges else None
                price_max = price_ranges[0].get("max") if price_ranges else None

                classifications = item.get("classifications", [])
                category = None
                if classifications:
                    category = (
                        classifications[0]
                        .get("segment", {})
                        .get("name")
                    )

                events.append(
                    Event(
                        id=f"ticketmaster-{item['id']}",
                        source="ticketmaster",
                        name=item.get("name", "Unknown event"),
                        start_time=start_dt,
                        end_time=None,
                        venue_name=venue.get("name"),
                        city=venue.get("city", {}).get("name"),
                        country=venue.get("country", {}).get("name"),
                        lat=float(location["latitude"]) if "latitude" in location else None,
                        lon=float(location["longitude"]) if "longitude" in location else None,
                        category=category,
                        url=item.get("url"),
                        price_min=price_min,
                        price_max=price_max,
                    )
                )
            except Exception as exc:
                logger.warning(
                    "Failed to parse Ticketmaster event %s: %s",
                    item.get("id"),
                    exc,
                )

        logger.info("TicketmasterProvider: parsed %d events", len(events))
        return events
