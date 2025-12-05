import json
import os
import re
import time
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from app.config import settings
from app.api.http import geocode_location  # reuse your helper
from app.models import Event, WebResult
from app.providers.ticketmaster import TicketmasterProvider
from app.providers.you_search import YouSearchProvider
from app.providers.parallel_deep_research import ParallelDeepResearchProvider
from app.providers.agentql import AgentQLEventsProvider
from math import radians, sin, cos, atan2, sqrt
import logging

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
)

# You can change this before running, or later wire it to CLI args.
LOCATION_QUERY = "Philadelphia, PA"

def parse_iso_or_none(val: Any) -> Optional[datetime]:
    if not isinstance(val, str) or not val.strip():
        return None
    try:
        return datetime.fromisoformat(val.replace("Z", "+00:00"))
    except Exception:
        return None

def time_score(e, now, end):
    if e.start_time <= now:
        return 0.0
    total = (end - now).total_seconds()
    if total <= 0:
        return 0.0
    remaining = (e.start_time - now).total_seconds()
    # invert so sooner -> higher
    s = 1.0 - (remaining / total)
    return max(0.0, min(1.0, s))

def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    phi1, phi2 = radians(lat1), radians(lat2)
    dphi = radians(lat2 - lat1)
    dlambda = radians(lon2 - lon1)

    a = sin(dphi/2)**2 + cos(phi1)*cos(phi2)*sin(dlambda/2)**2
    c = 2 * atan2(sqrt(a), sqrt(1-a))
    return R * c

def distance_score(e, center_lat, center_lon, radius_km):
    if e.lat is None or e.lon is None:
        # If we don't know where it is, treat as neutral/low
        return 0.3
    d = haversine_km(center_lat, center_lon, e.lat, e.lon)
    if d >= radius_km:
        return 0.0
    # Closer = higher; 0km → 1.0, radius → 0.0
    s = 1.0 - (d / radius_km)
    return max(0.0, min(1.0, s))

HEADCOUNT_BUCKET_SCORE = {
    "small": 0.2,
    "medium": 0.5,
    "large": 0.8,
    "stadium": 1.0,
}

def headcount_score(e):
    if not e.headcount_bucket:
        return 0.0
    base = HEADCOUNT_BUCKET_SCORE.get(e.headcount_bucket, 0.0)
    if e.headcount_confidence is not None:
        return base * max(0.0, min(1.0, e.headcount_confidence))
    return base

def compute_event_rank(
    e,
    now,
    end,
    center_lat,
    center_lon,
    radius_km,
    w_time=0.5,
    w_dist=0.3,
    w_pop=0.2,
):
    t = time_score(e, now, end)
    d = distance_score(e, center_lat, center_lon, radius_km)
    p = headcount_score(e)
    return w_time * t + w_dist * d + w_pop * p



def pws_json_to_event(item: Dict[str, Any], fallback_city: str | None = None) -> Event:
    """
    Convert one JSON event from pws_enriched_events into an Event object.
    Unknown fields stay as None.
    """
    name = item.get("name") or "Unnamed event"

    start = parse_iso_or_none(item.get("start_time")) or datetime.min.replace(tzinfo=timezone.utc)
    end = parse_iso_or_none(item.get("end_time"))

    venue_name = item.get("venue_name") or None
    city = item.get("city") or fallback_city
    country = item.get("country") or None
    lat = item.get("lat")
    lon = item.get("lon")
    category = item.get("category") or None
    url = item.get("url") or None
    price_min = item.get("price_min")
    price_max = item.get("price_max")

    headcount_bucket = item.get("headcount_bucket")
    headcount_confidence = item.get("headcount_confidence")

    # Build a synthetic ID based on name + start time
    start_key = (
        start.isoformat()
        if start != datetime.min.replace(tzinfo=timezone.utc)
        else "nostart"
    )
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "event"
    event_id = f"pws-{slug}-{start_key}"

    return Event(
        id=event_id,
        source="pws",
        name=name,
        start_time=start,
        end_time=end,
        venue_name=venue_name,
        city=city,
        country=country,
        lat=lat,
        lon=lon,
        category=category,
        url=url,
        price_min=price_min,
        price_max=price_max,
        headcount_bucket=headcount_bucket,
        headcount_confidence=headcount_confidence,
    )

def normalize_text(s: Optional[str]) -> str:
    if not s:
        return ""
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(s.split())


def make_dedupe_key(e: Event) -> tuple:
    date_key = e.start_time.date().isoformat() if isinstance(e.start_time, datetime) else None
    return (
        date_key,
        normalize_text(e.name),
        normalize_text(e.venue_name),
    )


def merge_events(tm_events: List[Event], pws_events: List[Event]) -> List[Event]:
    """
    Combine Ticketmaster + PWS events.

    - Keep Ticketmaster as the canonical base.
    - If a PWS event matches an existing TM event:
      - enrich TM headcount_* if PWS has it.
      - do NOT add a duplicate event.
    - If a PWS event does not match, append it as its own event (source="pws").
    """
    merged: List[Event] = []
    index: Dict[tuple, Event] = {}

    # Seed with Ticketmaster events
    for e in tm_events:
        key = make_dedupe_key(e)
        index[key] = e
        merged.append(e)

    # Fold in PWS events
    for p in pws_events:
        key = make_dedupe_key(p)
        if key in index:
            base = index[key]
            # Enrich headcount if TM doesn't have it
            if base.headcount_bucket is None and p.headcount_bucket:
                base.headcount_bucket = p.headcount_bucket
                base.headcount_confidence = p.headcount_confidence
            # (You could also fill category/price if TM is missing; optional.)
            continue

        merged.append(p)

    return merged


def event_to_dict(e: Event) -> Dict[str, Any]:
    d = asdict(e)
    # Convert datetimes to ISO strings for JSON
    if isinstance(e.start_time, datetime):
        d["start_time"] = e.start_time.isoformat()
    if e.end_time and isinstance(e.end_time, datetime):
        d["end_time"] = e.end_time.isoformat()
    return d


def webresult_to_dict(w: WebResult) -> Dict[str, Any]:
    return asdict(w)


def get_data_dir() -> Path:
    """
    Returns the correct data directory depending on environment:
    - Locally: ./data
    - Azure App Service: /home/data
    """
    if os.getenv("WEBSITE_SITE_NAME"):
        # Azure App Service persistent, writable area
        base = Path("/home/data")
    else:
        # Local dev
        base = Path("data")

    base.mkdir(parents=True, exist_ok=True)
    return base


def extract_pws_events_from_markdown(markdown: str) -> Optional[Dict[str, Any]]:
    """
    For mining: assume Parallel returns ONLY raw JSON now.
    Try to parse it; on failure, return None.
    """
    text = markdown.strip()
    if not text:
        print("[mine_location] Parallel report is empty when extracting PWS JSON.")
        return None

    try:
        obj = json.loads(text)
    except json.JSONDecodeError as e:
        print("[mine_location] Failed to decode PWS JSON:", e)
        print("[mine_location] Snippet:", text[:500])
        return None

    if not isinstance(obj, dict):
        print("[mine_location] PWS JSON is not an object, got:", type(obj))
        return None

    if "events" not in obj or not isinstance(obj["events"], list):
        obj["events"] = []

    return obj


def main() -> None:
    # 1) Resolve location to lat/lon
    query = LOCATION_QUERY.strip()
    if not query:
        raise ValueError("LOCATION_QUERY is empty")

    print(f"[mine_location] Geocoding: {query!r}")
    lat, lon = geocode_location(query)
    if lat is None or lon is None:
        print(f"[mine_location] Geocoding failed for {query}, using default NYC coords")
        lat, lon = 40.7128, -74.006

    # 2) Time window: from 1 hour ago to N days ahead
    days_ahead = settings.default_days_ahead
    now = datetime.now(timezone.utc)
    start = now - timedelta(hours=1)
    end = now + timedelta(days=days_ahead)

    print(
        f"[mine_location] Time window: {start.isoformat()} → {end.isoformat()} "
        f"({days_ahead} days ahead, with 1h lookback)"
    )
    print(f"[mine_location] Radius: {settings.default_radius_km} km")

    # 3) Structured events (Ticketmaster for now)
    tm = TicketmasterProvider()
    events: List[Event] = []
    if tm.api_key:
        print("[mine_location] Fetching Ticketmaster events (paginated)...")
        t0 = time.perf_counter()
        events.extend(
            tm.get_events(
                city=query,
                latitude=lat,
                longitude=lon,
                start=start,
                end=end,
                radius_km=settings.default_radius_km,
            )
        )
        dt = time.perf_counter() - t0
        print(
            f"[mine_location] Ticketmaster returned {len(events)} events in {dt:.2f}s."
        )
    else:
        print("[mine_location] Ticketmaster API key not configured; skipping.")

    # 4) You.com deep research
    you = YouSearchProvider()
    web_results: List[WebResult] = []
    if you.api_key:
        print("[mine_location] Fetching You.com web results...")
        t0 = time.perf_counter()
        web_results = you.search_city_events(
            city=query,
            days_ahead=days_ahead,
            limit=15,  # bump limit a bit for mining
        )
        dt = time.perf_counter() - t0
        print(
            f"[mine_location] You.com returned {len(web_results)} web results in {dt:.2f}s."
        )
    else:
        print("[mine_location] You.com API key not configured; skipping.")

    # 5) AgentQL (Tiny Fish) deep-ish snippets (experimental)
    agentql = AgentQLEventsProvider()
    agentql_results: List[WebResult] = []
    if agentql.api_key:
        print("[mine_location] Fetching AgentQL (Tiny Fish) event snippets...")
        t0 = time.perf_counter()
        agentql_results = agentql.search_city_events(
            city=query,
            days_ahead=days_ahead,
            limit=15,
        )
        agentql_results = agentql_results if agentql_results else []
        dt = time.perf_counter() - t0
        print(
            f"[mine_location] AgentQL returned {len(agentql_results)} web results "
            f"in {dt:.2f}s."
        )
    else:
        print("[mine_location] AgentQL API key not configured; skipping.")

    # Merge You.com + AgentQL into one web_results list (if you want to keep them together)
    all_web_results = web_results + agentql_results

    # 6) Parallel deep research (narrative + structured JSON events)
    parallel = ParallelDeepResearchProvider()
    parallel_report: Optional[Dict[str, Any]] = None
    pws_enriched_events: Dict[str, Any] = {"events": []}

    if parallel.is_configured:
        print("[mine_location] Running Parallel deep research (this may take a while)...")
        report_obj = parallel.research_city_events(city=query, days_ahead=days_ahead)

        if report_obj:
            # Use the structured field directly
            if isinstance(report_obj.structured, dict):
                pws_enriched_events = report_obj.structured
            else:
                pws_enriched_events = {"events": []}

            # Optional: keep raw string for debugging
            parallel_report = {
                "provider": report_obj.provider,
                "city": report_obj.city,
                "days_ahead": report_obj.days_ahead,
                "raw": report_obj.report,
            }

            print(
                f"[mine_location] Parallel structured events: "
                f"{len(pws_enriched_events.get('events', []))}"
            )
        else:
            print("[mine_location] Parallel returned no report.")
    else:
        print("[mine_location] Parallel API key not configured; skipping.")


    # 6b) Convert PWS enriched events into Event objects
    pws_event_objects: List[Event] = []
    for item in pws_enriched_events.get("events", []):
        if not isinstance(item, dict):
            continue
        try:
            pws_event_objects.append(
                pws_json_to_event(item, fallback_city=query)
            )
        except Exception as exc:
            print(f"[mine_location] Failed to convert PWS event JSON to Event: {exc}")


    # 6c) Merge Ticketmaster + PWS
    combined_events = merge_events(events, pws_event_objects)
    ranked_events = []
    for e in combined_events:
        score = compute_event_rank(
            e,
            now=now,
            end=end,
            center_lat=lat,
            center_lon=lon,
            radius_km=settings.default_radius_km,
        )
        ranked_events.append((score, e))

    ranked_events.sort(key=lambda x: x[0], reverse=True)

    # 7) Build output payload
    payload: Dict[str, Any] = {
        "location_query": query,
        "generated_at_utc": now.isoformat(),
        "time_window": {
            "start_utc": start.isoformat(),
            "end_utc": end.isoformat(),
            "days_ahead": days_ahead,
            "lookback_hours": 1,
        },
        "coords": {"lat": lat, "lon": lon},

        # Ticketmaster only (as before)
        "events": [event_to_dict(e) for e in events],

        # All web results (You.com + AgentQL if any)
        "web_results": [webresult_to_dict(w) for w in all_web_results],

        # Raw PWS JSON events
        "pws_enriched_events": pws_enriched_events,

        # NEW: merged Event list (Ticketmaster + PWS)
        "combined_events": [event_to_dict(e) for e in combined_events],
        "ranked_events": [
            {
                **event_to_dict(e),
                "score": score,
            }
            for score, e in ranked_events
        ],


        "meta": {
            "ticketmaster_events_count": len(events),
            "you_web_results_count": len(web_results),
            "agentql_web_results_count": len(agentql_results),
            "parallel_enabled": parallel.is_configured,
            "pws_enriched_events_count": len(
                pws_enriched_events.get("events", [])
            ),
            "pws_events_as_objects_count": len(pws_event_objects),
            "combined_events_count": len(combined_events),
            "top_ranked_first_event_name": ranked_events[0][1].name if ranked_events else None
        },
    }


    # 8) Write to data/ folder with timestamp
    out_dir = get_data_dir()
    ts = now.strftime("%Y%m%dT%H%M%SZ")
    safe_loc = query.lower().replace(" ", "_").replace(",", "")
    out_path = out_dir / f"{safe_loc}_{ts}.json"

    out_path.write_text(json.dumps(payload, indent=2))
    print(f"[mine_location] Wrote {out_path}")


if __name__ == "__main__":
    main()