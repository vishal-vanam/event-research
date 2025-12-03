import os
from pathlib import Path


def get_data_dir() -> Path:
    """
    Returns the correct data directory depending on environment:
    - Locally: ./data
    - Azure App Service: /home/data
    """
    if os.getenv("WEBSITE_SITE_NAME"):
        base = Path("/home/data")
    else:
        base = Path("data")

    base.mkdir(parents=True, exist_ok=True)
    return base
