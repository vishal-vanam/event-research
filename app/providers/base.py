from typing import Protocol, List
from datetime import datetime
from app.models import Event


class EventProvider(Protocol):
    name: str

    def get_events(
        self,
        city: str,
        latitude: float,
        longitude: float,
        start: datetime,
        end: datetime,
        radius_km: int,
    ) -> List[Event]:
        ...
