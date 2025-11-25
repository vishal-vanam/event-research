import json
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
import os

from app.config import settings
from app.api.http import geocode_location  # reuse your helper
from app.models import Event, WebResult
from app.providers.ticketmaster import TicketmasterProvider
from app.providers.you_search import YouSearchProvider
from app.providers.parallel_deep_research import ParallelDeepResearchProvider


# You can change this before running, or later wire it to CLI args.
LOCATION_QUERY = "Jersey City, NJ"


def event_to_dict(e: Event) -> Dict[str, Any]:
    d = asdict(e)
    # Convert datetimes to ISO strings for JSON
    if isinstance(e.start_time, datetime):
        d["start_time"] = e.start_time.isoformat()
    if e.end_time and isinstance(e.end_time, datetime):
        d["end_time"] = e.end_time.isoformat()
    return d

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

def webresult_to_dict(w: WebResult) -> Dict[str, Any]:
    return asdict(w)


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

    # 3) Structured events (Ticketmaster for now)
    tm = TicketmasterProvider()
    events: List[Event] = []
    if tm.api_key:
        print("[mine_location] Fetching Ticketmaster events...")
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
    else:
        print("[mine_location] Ticketmaster API key not configured; skipping.")

    # TODO: add SeatGeek/Eventbrite here later if desired

    # 4) You.com deep research
    you = YouSearchProvider()
    web_results: List[WebResult] = []
    if you.api_key:
        print("[mine_location] Fetching You.com web results...")
        web_results = you.search_city_events(
            city=query,
            days_ahead=days_ahead,
            limit=15,  # bump limit a bit for mining
        )
    else:
        print("[mine_location] You.com API key not configured; skipping.")

    # 5) Parallel deep research
    parallel = ParallelDeepResearchProvider()
    parallel_report: Optional[str] = None
    if parallel.is_configured:
        print("[mine_location] Running Parallel deep research (this may take a while)...")
        report_obj = parallel.research_city_events(city=query, days_ahead=days_ahead)
        if report_obj:
            parallel_report = report_obj.report
        else:
            print("[mine_location] Parallel returned no report.")
    else:
        print("[mine_location] Parallel API key not configured; skipping.")

    # 6) Build output payload
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
        "events": [event_to_dict(e) for e in events],
        "web_results": [webresult_to_dict(w) for w in web_results],
        "parallel_report": parallel_report,
        "meta": {
            "ticketmaster_events_count": len(events),
            "you_web_results_count": len(web_results),
            "parallel_enabled": parallel.is_configured,
        },
    }

    # 7) Write to data/ folder with timestamp
    out_dir = get_data_dir()
    ts = now.strftime("%Y%m%dT%H%M%SZ")
    safe_loc = query.lower().replace(" ", "_").replace(",", "")
    out_path = out_dir / f"{safe_loc}_{ts}.json"

    out_path.write_text(json.dumps(payload, indent=2))
    print(f"[mine_location] Wrote {out_path}")

if __name__ == "__main__":
    main()
