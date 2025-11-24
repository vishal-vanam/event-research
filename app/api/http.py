import logging
from fastapi import FastAPI, Query, HTTPException
from app.models import WebResult 
from app.models import CombinedResult
from app.cache import combined_cache
from pydantic import BaseModel

from app.aggregator import get_city_events
from app.config import settings
from app.providers.ticketmaster import TicketmasterProvider
from app.providers.seatgeek import SeatGeekProvider
from app.providers.eventbrite import EventbriteProvider
from app.providers.you_search import YouSearchProvider

from app.models import DeepResearchReport
from app.providers.parallel_deep_research import ParallelDeepResearchProvider

from datetime import datetime, timedelta, timezone

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

@app.get("/events/deep_research/parallel", response_model=DeepResearchReport)
async def deep_research_parallel(
    city: str,
    days_ahead: int = Query(7, ge=1, le=30),
) -> DeepResearchReport:
    """
    v1.2: Deep research via Parallel Web Systems Task API.

    This is intentionally separate from the /events/research (You.com) endpoint
    so you can control when you incur Deep Research cost.
    """
    provider = ParallelDeepResearchProvider()
    if not provider.is_configured:
        raise HTTPException(
            status_code=503,
            detail="Parallel API key (PARALLEL_API_KEY) not configured on server.",
        )

    report = provider.research_city_events(city=city, days_ahead=days_ahead)
    if report is None:
        raise HTTPException(
            status_code=502,
            detail="Parallel Deep Research failed or returned no output.",
        )

    return report

@app.get("/events/combined", response_model=CombinedResult)
async def combined_events(
    city: str,
    days_ahead: int = Query(settings.default_days_ahead, ge=1, le=30),
    radius_km: int = Query(settings.default_radius_km, ge=1, le=100),
    force_refresh: bool = Query(False, description="Bypass cache if true"),
):
    # Normalize city for cache key
    city_norm = city.strip().lower()
    cache_key = f"combined:{city_norm}:{days_ahead}:{radius_km}"

    # ─────────────────────────────────────────────
    # 1) Try cache unless force_refresh
    # ─────────────────────────────────────────────
    if not force_refresh:
        cached = combined_cache.get(cache_key)
        if cached is not None:
            return cached

    # ─────────────────────────────────────────────
    # 2) Geocode or fallback
    # ─────────────────────────────────────────────
    from app.api.http import geocode_city  # reuse your function
    lat, lon = geocode_city(city)
    if lat is None or lon is None:
        # fallback to NYC coords
        lat, lon = 40.7128, -74.006

    start = datetime.now(timezone.utc)
    end = start + timedelta(days=days_ahead)

    # ─────────────────────────────────────────────
    # 3) Structured events (v1)
    # ─────────────────────────────────────────────
    events = []
    from app.providers.ticketmaster import TicketmasterProvider
    tm = TicketmasterProvider()
    if tm.api_key:
        events.extend(
            tm.get_events(
                city=city,
                latitude=lat,
                longitude=lon,
                start=start,
                end=end,
                radius_km=radius_km,
            )
        )

    # (Optional: add SeatGeek / Eventbrite here)

    # ─────────────────────────────────────────────
    # 4) You.com deep research (v1.1)
    # ─────────────────────────────────────────────
    from app.providers.you_search import YouSearchProvider
    you = YouSearchProvider()
    if you.api_key:
        web_results = you.search_city_events(city=city, days_ahead=days_ahead, limit=10)
    else:
        web_results = []

    # ─────────────────────────────────────────────
    # 5) Parallel deep research (v1.2)
    # ─────────────────────────────────────────────
    from app.providers.parallel_deep_research import ParallelDeepResearchProvider
    parallel_provider = ParallelDeepResearchProvider()
    parallel_report = None
    if parallel_provider.is_configured:
        try:
            report_obj = parallel_provider.research_city_events(city=city, days_ahead=days_ahead)
            if report_obj:
                parallel_report = report_obj.report
        except Exception:
            parallel_report = None

    combined = CombinedResult(
        city=city,
        days_ahead=days_ahead,
        events=events,
        web_results=web_results,
        parallel_report=parallel_report,
    )

    # ─────────────────────────────────────────────
    # 6) Store in cache and return
    # ─────────────────────────────────────────────
    combined_cache.set(cache_key, combined)
    return combined