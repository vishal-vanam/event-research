import logging
from fastapi import FastAPI, Query, HTTPException
from app.models import WebResult 
from pydantic import BaseModel

from app.aggregator import get_city_events
from app.config import settings
from app.providers.ticketmaster import TicketmasterProvider
from app.providers.seatgeek import SeatGeekProvider
from app.providers.eventbrite import EventbriteProvider
from app.providers.you_search import YouSearchProvider

logger = logging.getLogger(__name__)

import httpx

def geocode_city(city: str):
    url = "https://nominatim.openstreetmap.org/search"
    params = {"q": city, "format": "json", "limit": 1}
    headers = {
        "User-Agent": "event-research/0.1 (personal project; contact: vishal@example.com)"
    }
    try:
        resp = httpx.get(url, params=params, headers=headers, timeout=10)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        print(f"Geocoding error for {city}: {exc}")
        return None, None

    try:
        data = resp.json()
    except ValueError:
        return None, None

    if not data:
        return None, None

    return float(data[0]["lat"]), float(data[0]["lon"])

class WebResultOut(BaseModel):
    source: str
    title: str
    url: str
    snippet: str | None = None
    page_age: str | None = None

class EventOut(BaseModel):
    id: str
    source: str
    name: str
    start_time: str
    end_time: str | None = None
    venue_name: str | None = None
    city: str | None = None
    country: str | None = None
    lat: float | None = None
    lon: float | None = None
    category: str | None = None
    url: str | None = None
    price_min: float | None = None
    price_max: float | None = None


app = FastAPI(title="City Events API", version="0.1.0")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/events", response_model=list[EventOut])
def list_events(
    city: str = Query(..., description="City name, e.g. 'New York'"),
    days_ahead: int = Query(settings.default_days_ahead, ge=1, le=30),
    radius_km: int = Query(settings.default_radius_km, ge=1, le=100),
):
    latitude, longitude = geocode_city(city)

    if latitude is None or longitude is None:
        # OPTION 1: fail explicitly with a clean error
        # raise HTTPException(
        #     status_code=502,
        #     detail=f"Failed to geocode city '{city}'",
        # )

        # OPTION 2: TEMP fallback – keep things working even if geocoding is blocked
        print(f"Geocoding failed for {city}, using default NYC coords")
        latitude, longitude = 40.7128, -74.0060

    providers = [
        TicketmasterProvider(),
        SeatGeekProvider(),
        EventbriteProvider(),
    ]

    events = get_city_events(
        city=city,
        latitude=latitude,
        longitude=longitude,
        providers=providers,
        days_ahead=days_ahead,
        radius_km=radius_km,
    )

    return [
        EventOut(
            id=e.id,
            source=e.source,
            name=e.name,
            start_time=e.start_time.isoformat(),
            end_time=e.end_time.isoformat() if e.end_time else None,
            venue_name=e.venue_name,
            city=e.city,
            country=e.country,
            lat=e.lat,
            lon=e.lon,
            category=e.category,
            url=e.url,
            price_min=e.price_min,
            price_max=e.price_max,
        )
        for e in events
    ]

@app.get("/events/research", response_model=list[WebResultOut])
def research_events(
    city: str = Query(..., description="City name, e.g. 'New York'"),
    days_ahead: int = Query(settings.default_days_ahead, ge=1, le=30),
    limit: int = Query(10, ge=1, le=20),
):
    """
    Deep research endpoint: returns You.com web results about events in the given city.
    This complements the structured /events data from Ticketmaster/SeatGeek.
    """
    provider = YouSearchProvider()
    results = provider.search_city_events(city=city, days_ahead=days_ahead, limit=limit)

    return [
        WebResultOut(
            source=r.source,
            title=r.title,
            url=r.url,
            snippet=r.snippet,
            page_age=r.page_age,
        )
        for r in results
    ]
