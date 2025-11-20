# app/config.py
import os
from dataclasses import dataclass

from dotenv import load_dotenv

# Load .env file into environment variables
load_dotenv()


@dataclass
class Settings:
    ticketmaster_api_key: str | None = os.getenv("TICKETMASTER_API_KEY")
    seatgeek_client_id: str | None = os.getenv("SEATGEEK_CLIENT_ID")
    seatgeek_client_secret: str | None = os.getenv("SEATGEEK_CLIENT_SECRET")
    eventbrite_token: str | None = os.getenv("EVENTBRITE_TOKEN")

    you_api_key: str | None = os.getenv("YDC_API_KEY") or os.getenv("YOU_API_KEY")
    
    default_radius_km: int = int(os.getenv("DEFAULT_RADIUS_KM", "25"))
    default_days_ahead: int = int(os.getenv("DEFAULT_DAYS_AHEAD", "7"))


settings = Settings()
