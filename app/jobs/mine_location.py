import json
import os
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


# You can change this before running, or later wire it to CLI args.
LOCATION_QUERY = "Philadelphia, PA"


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
    Look for a ```json ... ``` block at the end of the Parallel report
    and parse it as JSON.

    Expects something like:

    ```json
    { "events": [ ... ] }
    ```

    Returns a dict like {"events": [...]} or None if parsing fails.
    """
    start_token = "```json"
    end_token = "```"

    start_idx = markdown.rfind(start_token)
    if start_idx == -1:
        return None

    # Find the end fence after start_idx
    content_start = start_idx + len(start_token)
    end_idx = markdown.find(end_token, content_start)
    if end_idx == -1:
        return None

    json_str = markdown[content_start:end_idx].strip()

    if not json_str:
        return None

    try:
        obj = json.loads(json_str)
    except json.JSONDecodeError:
        return None

    if not isinstance(obj, dict):
        return None

    # Ensure 'events' key exists (even if empty)
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
    parallel_report_obj: Optional[Dict[str, Any]] = None
    pws_enriched_events: Dict[str, Any] = {"events": []}

    if parallel.is_configured:
        print("[mine_location] Running Parallel deep research (this may take a while)...")
        t0 = time.perf_counter()
        report_obj = parallel.research_city_events(city=query, days_ahead=days_ahead)
        dt = time.perf_counter() - t0

        if report_obj and report_obj.report:
            markdown = report_obj.report
            lines = markdown.splitlines()

            parallel_report_obj = {
                "city": query,
                "days_ahead": days_ahead,
                "elapsed_seconds": round(dt, 2),
                "raw_markdown": markdown,
                "markdown_lines": lines,
            }
            print(
                f"[mine_location] Parallel returned a report in {dt:.2f}s "
                f"with {len(lines)} markdown lines."
            )

            # Try to extract structured events JSON from the markdown
            parsed = extract_pws_events_from_markdown(markdown)
            if parsed is not None:
                pws_enriched_events = parsed
                print(
                    f"[mine_location] PWS enriched events parsed: "
                    f"{len(pws_enriched_events.get('events', []))} events."
                )
            else:
                print("[mine_location] No valid PWS events JSON block found in report.")
        else:
            print(f"[mine_location] Parallel returned no report after {dt:.2f}s.")
    else:
        print("[mine_location] Parallel API key not configured; skipping.")

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
        "events": [event_to_dict(e) for e in events],
        "web_results": [webresult_to_dict(w) for w in all_web_results],
        "parallel_report": parallel_report_obj,
        "pws_enriched_events": pws_enriched_events,
        "meta": {
            "ticketmaster_events_count": len(events),
            "you_web_results_count": len(web_results),
            "agentql_web_results_count": len(agentql_results),
            "parallel_enabled": parallel.is_configured,
            "pws_enriched_events_count": len(
                pws_enriched_events.get("events", [])
            ),
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