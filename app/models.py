from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Dict, Any


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
    # NEW: PWS headcount enrichment
    headcount_bucket: Optional[str] = None            # "small", "medium", "large", "stadium"
    headcount_confidence: Optional[float] = None      # 0.0–1.0

@dataclass
class WebResult:
    source: str          # e.g. "you-search"
    title: str
    url: str
    snippet: Optional[str] = None
    page_age: Optional[str] = None

@dataclass
class DeepResearchReport:
    provider: str
    city: str
    days_ahead: int
    report: str  # raw text / repr for debugging
    structured: Optional[Dict[str, Any]] = None  # e.g. {"events": [...]}

@dataclass
class CombinedResult:
    city: str
    days_ahead: int
    events: List[Event]
    web_results: List[WebResult]
    parallel_report: Optional[str] = None