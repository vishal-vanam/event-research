from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional


@dataclass
class Event:
    id: str
    source: str            # "ticketmaster", "seatgeek", etc.
    name: str
    start_time: datetime
    end_time: Optional[datetime] = None
    venue_name: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    category: Optional[str] = None
    url: Optional[str] = None
    price_min: Optional[float] = None
    price_max: Optional[float] = None

@dataclass
class WebResult:
    source: str          # e.g. "you-search"
    title: str
    url: str
    snippet: Optional[str] = None
    page_age: Optional[str] = None

@dataclass
class DeepResearchReport:
    provider: str      # e.g. "parallel-deep-research"
    city: str
    days_ahead: int
    report: str        # markdown / rich text from Parallel

@dataclass
class CombinedResult:
    city: str
    days_ahead: int
    events: List[Event]
    web_results: List[WebResult]
    parallel_report: Optional[str] = None