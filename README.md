# Event Intelligence Platform

A FastAPI service that aggregates events from multiple providers (Ticketmaster, SeatGeek, Eventbrite) and enriches them with AI-powered web research (You.com, Parallel Web Systems, AgentQL). Search by city or free-form location query to get structured event data with venue info, pricing, and coordinates.

## Features

- **Multi-source aggregation** — Ticketmaster, SeatGeek, Eventbrite
- **AI-enriched research** — You.com search, Parallel deep research, AgentQL web scraping
- **Geocoding** — Free-form location queries via OpenStreetMap Nominatim
- **Caching** — In-memory TTL cache for combined results
- **Fault-tolerant** — Per-provider error handling; failures don't block other sources

## API Endpoints

| Endpoint | Description |
|---|---|
| `GET /health` | Health check |
| `GET /events` | Structured events from Ticketmaster, SeatGeek, Eventbrite |
| `GET /events/research` | Web search results via You.com |
| `GET /events/deep_research/parallel` | Parallel deep research reports |
| `GET /events/deep_research/agentql` | AgentQL web scraping results |
| `GET /events/combined` | Unified response combining all sources |
| `GET /events/mined` | Pre-mined/cached location data |

All endpoints accept `location` or `city` query parameters.

## Setup

```bash
# Clone and install
git clone https://github.com/vishal-vanam/event-intelligence-platform.git
cd event-intelligence-platform
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your API keys

# Run
python main.py
```

## Environment Variables

See [.env.example](.env.example) for the full list. Key variables:

| Variable | Description |
|---|---|
| `TICKETMASTER_API_KEY` | Ticketmaster API key |
| `SEATGEEK_CLIENT_ID` | SeatGeek client ID |
| `EVENTBRITE_TOKEN` | Eventbrite OAuth token |
| `YDC_API_KEY` | You.com search API key |
| `PARALLEL_API_KEY` | Parallel Web Systems API key |
| `AGENTQL_API_KEY` | AgentQL API key |
| `DEFAULT_RADIUS_KM` | Search radius in km (default: 25) |
| `DEFAULT_DAYS_AHEAD` | Event lookahead days (default: 7) |

## Tech Stack

- **FastAPI** + **Uvicorn**
- **httpx** for async HTTP
- **Pydantic** for data validation
- **Docker** support included

## License

MIT
