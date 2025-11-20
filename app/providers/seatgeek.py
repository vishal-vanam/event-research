from datetime import datetime
from typing import List
import logging

import httpx

from app.models import Event
from app.providers.base import EventProvider
from app.config import settings

logger = logging.getLogger(__name__)


class SeatGeekProvider:
    name = "seatgeek"

    def __init__(self) -> None:
        self.client_id = settings.seatgeek_client_id
        if not self.client_id:
            logger.warning("SeatGeek client ID not set; provider will return no events.")

    def get_events(
        self,
        city: str,
        latitude: float,
        longitude: float,
        start: datetime,
        end: datetime,
        radius_km: int,
    ) -> List[Event]:
        if not self.client_id:
            return []

        url = "https://api.seatgeek.com/2/events"

        # SeatGeek uses miles with a "mi" suffix like "25mi"
        miles = max(1, int(radius_km * 0.621371))
        params = {
            "client_id": self.client_id,
            "lat": latitude,
            "lon": longitude,
            "range": f"{miles}mi",
            "per_page": 50,
        }

        logger.info(
            "SeatGeekProvider.get_events: client_id_set=%s lat=%s lon=%s range=%s",
            bool(self.client_id),
            latitude,
            longitude,
            params["range"],
        )

        try:
            resp = httpx.get(url, params=params, timeout=10)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            logger.error("SeatGeek API request failed: %s", exc)
            return []

        data = resp.json()
        raw_events = data.get("events", [])

        events: List[Event] = []

        for item in raw_events:
            try:
                start_dt_raw = item.get("datetime_local") or item.get("datetime_utc")
                if not start_dt_raw:
                    continue
                start_dt = datetime.fromisoformat(start_dt_raw.replace("Z", "+00:00"))

                venue = item.get("venue", {}) or {}
                location = venue.get("location", {}) or {}

                events.append(
                    Event(
                        id=f"seatgeek-{item['id']}",
                        source="seatgeek",
                        name=item.get("short_title") or item.get("title", "Unknown event"),
                        start_time=start_dt,
                        end_time=None,
                        venue_name=venue.get("name"),
                        city=venue.get("city"),
                        country=venue.get("country"),
                        lat=float(location["lat"]) if "lat" in location else None,
                        lon=float(location["lon"]) if "lon" in location else None,
                        category=(item.get("type") or None),
                        url=item.get("url"),
                        price_min=None,
                        price_max=None,
                    )
                )
            except Exception as exc:
                logger.warning(
                    "Failed to parse SeatGeek event %s: %s",
                    item.get("id"),
                    exc,
                )

        logger.info("SeatGeekProvider: parsed %d events", len(events))
        return events
