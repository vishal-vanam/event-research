from datetime import datetime, timedelta
from app.aggregator import get_city_events
from app.models import Event


class DummyProvider:
    name = "dummy"

    def get_events(self, city, latitude, longitude, start, end, radius_km):
        return [
            Event(
                id="dummy-1",
                source=self.name,
                name=f"Test event in {city}",
                start_time=start + timedelta(hours=1),
            )
        ]


def test_aggregator_returns_events():
    events = get_city_events(
        city="TestCity",
        latitude=0.0,
        longitude=0.0,
        providers=[DummyProvider()],
        days_ahead=1,
        radius_km=10,
    )
    assert len(events) == 1
    assert events[0].name.startswith("Test event in")
