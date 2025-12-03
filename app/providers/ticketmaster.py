from datetime import datetime, timezone
from typing import List
import logging

import httpx

from app.models import Event
from app.providers.base import EventProvider
from app.config import settings

logger = logging.getLogger(__name__)


class TicketmasterProvider(EventProvider):
    name = "ticketmaster"

    def __init__(self) -> None:
        self.api_key = settings.ticketmaster_api_key
        if not self.api_key:
            logger.warning("Ticketmaster API key not set; provider will return no events.")

    @staticmethod
    def _format_tm_datetime(dt: datetime) -> str:
        """
        Ticketmaster expects ISO-8601 UTC with 'Z', e.g. 2025-11-25T18:00:00Z
        """
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

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

        base_url = "https://app.ticketmaster.com/discovery/v2/events.json"

        # Ticketmaster docs: size * page < 1000, so we cap total events and pages. 
        size = 200          # page size (max-ish)
        max_events = 1000   # hard cap per query
        page = 0

        start_str = self._format_tm_datetime(start)
        end_str = self._format_tm_datetime(end)

        logger.info(
            "TicketmasterProvider.get_events: api_key_set=%s lat=%s lon=%s radius=%s "
            "start=%s end=%s",
            bool(self.api_key),
            latitude,
            longitude,
            radius_km,
            start_str,
            end_str,
        )

        events: List[Event] = []

        while True:
            params = {
                "apikey": self.api_key,
                "latlong": f"{latitude},{longitude}",
                "radius": radius_km,
                "unit": "km",
                "size": size,
                "page": page,
                "sort": "date,asc",
                "startDateTime": start_str,
                "endDateTime": end_str,
                "city": city,
            }

            try:
                resp = httpx.get(base_url, params=params, timeout=15)
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                logger.error("Ticketmaster API request failed on page %s: %s", page, exc)
                break

            data = resp.json()
            embedded = data.get("_embedded", {})
            raw_events = embedded.get("events", [])

            if not raw_events:
                logger.info("TicketmasterProvider: no events on page %s, stopping pagination", page)
                break

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
                        category = classifications[0].get("segment", {}).get("name")

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
                        "Failed to parse Ticketmaster event %s on page %s: %s",
                        item.get("id"),
                        page,
                        exc,
                    )

            logger.info(
                "TicketmasterProvider: accumulated %d events after page %s",
                len(events),
                page,
            )

            # Stopping conditions
            if len(raw_events) < size:
                # Last page
                break

            if len(events) >= max_events:
                logger.info(
                    "TicketmasterProvider: reached max_events=%d, stopping pagination",
                    max_events,
                )
                events = events[:max_events]
                break

            # Ticketmaster constraint: size * page < 1000 → avoid going beyond that. 
            if size * (page + 1) >= 1000:
                logger.info("TicketmasterProvider: size*page constraint hit, stopping pagination")
                break

            page += 1

        logger.info("TicketmasterProvider: parsed %d events total", len(events))
        return events
