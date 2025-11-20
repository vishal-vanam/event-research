from datetime import datetime, timedelta
from typing import List
import logging

from app.models import Event
from app.providers.base import EventProvider

logger = logging.getLogger(__name__)


def get_city_events(
    city: str,
    latitude: float,
    longitude: float,
    providers: list[EventProvider],
    days_ahead: int = 7,
    radius_km: int = 25,
) -> List[Event]:
    start = datetime.utcnow()
    end = start + timedelta(days=days_ahead)

    events: list[Event] = []

    for provider in providers:
        try:
            provider_events = provider.get_events(
                city=city,
                latitude=latitude,
                longitude=longitude,
                start=start,
                end=end,
                radius_km=radius_km,
            )
            logger.info("Provider %s returned %d events", provider.name, len(provider_events))
            events.extend(provider_events)
        except Exception as exc:
            logger.exception("Provider %s failed: %s", provider.name, exc)

    # TODO: dedupe by (name, start_time, venue) or better ID logic
    events.sort(key=lambda e: e.start_time)
    return events
