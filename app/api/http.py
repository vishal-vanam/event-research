import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import httpx
from fastapi import FastAPI, Query, HTTPException
from pydantic import BaseModel

from app.aggregator import get_city_events
from app.cache import combined_cache
from app.config import settings
from app.models import WebResult, CombinedResult, DeepResearchReport
from app.providers.eventbrite import EventbriteProvider
from app.providers.seatgeek import SeatGeekProvider
from app.providers.ticketmaster import TicketmasterProvider
from app.providers.you_search import YouSearchProvider
from app.providers.parallel_deep_research import ParallelDeepResearchProvider

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# Geocoding helper (generic: city / address / neighborhood)
# ─────────────────────────────────────────────

def geocode_location(query: str):
    """
    Geocode ANY free-form location string: street, neighborhood, city, etc.
    Currently uses Nominatim (OSM). Later you can swap this out for
    Google/Mapbox/Geoapify by only changing this function.
    """
    url = "https://nominatim.openstreetmap.org/search"
    params = {"q": query, "format": "json", "limit": 1}
    headers = {
        # Nominatim requires a custom User-Agent
        "User-Agent": "event-research-app/1.0 (contact: you@example.com)"
    }

    try:
        resp = httpx.get(url, params=params, headers=headers, timeout=10)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        logger.error("Geocoding error for %r: %s", query, exc)
        return None, None

    data = resp.json()
    if not data:
        logger.warning("Geocoding returned no results for %r", query)
        return None, None

    return float(data[0]["lat"]), float(data[0]["lon"])


# ─────────────────────────────────────────────
# API models (Pydantic output wrappers)
# ─────────────────────────────────────────────

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


app = FastAPI(title="City Events API", version="0.2.0")


# ─────────────────────────────────────────────
# Health
# ─────────────────────────────────────────────

@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


# ─────────────────────────────────────────────
# /events – structured events (v1)
# supports city OR free-form location
# ─────────────────────────────────────────────

@app.get("/events", response_model=list[EventOut])
def list_events(
    city: str | None = Query(
        None,
        description="City name, e.g. 'New York'. Optional if 'location' is provided.",
    ),
    location: str | None = Query(
        None,
        description="Free-form location: '123 Main St, Jersey City', neighborhood, etc.",
    ),
    days_ahead: int = Query(settings.default_days_ahead, ge=1, le=30),
    radius_km: int = Query(settings.default_radius_km, ge=1, le=100),
):
    # Choose which string to use as the location query
    query = (location or city or "").strip()
    if not query:
        raise HTTPException(
            status_code=400,
            detail="Either 'city' or 'location' query parameter is required.",
        )

    latitude, longitude = geocode_location(query)

    if latitude is None or longitude is None:
        logger.warning("Geocoding failed for %s, using default NYC coords", query)
        latitude, longitude = 40.7128, -74.0060

    providers = [
        TicketmasterProvider(),
        SeatGeekProvider(),
        EventbriteProvider(),
    ]

    events = get_city_events(
        city=query,  # can be city name or full address
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


# ─────────────────────────────────────────────
# /events/research – You.com web search (v1.1)
# supports city OR free-form location
# ─────────────────────────────────────────────

@app.get("/events/research", response_model=list[WebResultOut])
def research_events(
    city: str | None = Query(
        None,
        description="City name, e.g. 'New York'. Optional if 'location' is provided.",
    ),
    location: str | None = Query(
        None,
        description="Free-form location string to base research on.",
    ),
    days_ahead: int = Query(settings.default_days_ahead, ge=1, le=30),
    limit: int = Query(10, ge=1, le=20),
):
    """
    Deep research endpoint: returns You.com web results about events
    near the given location (city or free-form address).
    """
    query = (location or city or "").strip()
    if not query:
        raise HTTPException(
            status_code=400,
            detail="Either 'city' or 'location' query parameter is required.",
        )

    provider = YouSearchProvider()
    if not provider.api_key:
        raise HTTPException(
            status_code=503,
            detail="You.com API key (YDC_API_KEY) not configured on server.",
        )

    results = provider.search_city_events(city=query, days_ahead=days_ahead, limit=limit)

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


# ─────────────────────────────────────────────
# /events/deep_research/parallel – Parallel (v1.2)
# still uses 'city' param for now, can be extended similarly
# ─────────────────────────────────────────────

@app.get("/events/deep_research/parallel", response_model=DeepResearchReport)
async def deep_research_parallel(
    city: str = Query(..., description="Location string (city or address) for deep research."),
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


# ─────────────────────────────────────────────
# /events/combined – v1 + v1.1 + v1.2
# supports city OR free-form location + in-memory cache
# ─────────────────────────────────────────────

@app.get("/events/combined", response_model=CombinedResult)
async def combined_events(
    city: str | None = Query(
        None,
        description="City name, e.g. 'New York'. Optional if 'location' is provided.",
    ),
    location: str | None = Query(
        None,
        description="Free-form location: street, neighborhood, full address, etc.",
    ),
    days_ahead: int = Query(settings.default_days_ahead, ge=1, le=30),
    radius_km: int = Query(settings.default_radius_km, ge=1, le=100),
    force_refresh: bool = Query(False, description="Bypass cache if true"),
):
    # 1) Select the query string
    query = (location or city or "").strip()
    if not query:
        raise HTTPException(
            status_code=400,
            detail="Either 'city' or 'location' query parameter is required.",
        )

    # 2) Build cache key
    query_norm = query.lower()
    cache_key = f"combined:{query_norm}:{days_ahead}:{radius_km}"

    if not force_refresh:
        cached = combined_cache.get(cache_key)
        if cached is not None:
            return cached

    # 3) Geocode
    lat, lon = geocode_location(query)
    if lat is None or lon is None:
        logger.warning("Geocoding failed for %s, using default NYC coords", query)
        lat, lon = 40.7128, -74.006

    start = datetime.now(timezone.utc)
    end = start + timedelta(days=days_ahead)

    # 4) Structured events (Ticketmaster etc.)
    events = []
    tm = TicketmasterProvider()
    if tm.api_key:
        events.extend(
            tm.get_events(
                city=query,
                latitude=lat,
                longitude=lon,
                start=start,
                end=end,
                radius_km=radius_km,
            )
        )

    # (Optional: add SeatGeek / Eventbrite via aggregator or direct providers)

    # 5) You.com deep research
    you = YouSearchProvider()
    if you.api_key:
        web_results = you.search_city_events(city=query, days_ahead=days_ahead, limit=10)
    else:
        web_results = []

    # 6) Parallel deep research
    parallel_provider = ParallelDeepResearchProvider()
    parallel_report: Optional[str] = None
    if parallel_provider.is_configured:
        try:
            report_obj = parallel_provider.research_city_events(city=query, days_ahead=days_ahead)
            if report_obj:
                parallel_report = report_obj.report
        except Exception as exc:
            logger.error("Parallel deep research failed: %s", exc)
            parallel_report = None

    combined = CombinedResult(
        city=query,  # now represents generic location query string
        days_ahead=days_ahead,
        events=events,
        web_results=web_results,
        parallel_report=parallel_report,
    )

    combined_cache.set(cache_key, combined)
    return combined
