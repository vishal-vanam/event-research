# app/snapshot.py
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.utils.paths import get_data_dir

logger = logging.getLogger(__name__)


def _normalize_loc(query: str) -> str:
    """
    Match the naming used in mine_location.py:
    query.lower().replace(" ", "_").replace(",", "")
    """
    return query.lower().replace(" ", "_").replace(",", "")


def list_snapshots_for_location(query: str) -> List[Path]:
    """
    Return all snapshot files for a given location query,
    sorted by filename (timestamp is in the name).
    """
    data_dir = get_data_dir()
    safe_loc = _normalize_loc(query)
    pattern = f"{safe_loc}_*.json"

    files = sorted(data_dir.glob(pattern), key=lambda p: p.name)
    logger.info(
        "Snapshots for %r -> %d files (pattern=%s)",
        query,
        len(files),
        pattern,
    )
    return files


def load_latest_snapshot(query: str) -> Optional[Dict[str, Any]]:
    """
    Load the latest snapshot JSON for this location, or None if none exist.
    """
    snapshots = list_snapshots_for_location(query)
    if not snapshots:
        logger.info("No snapshots found for location query=%r", query)
        return None

    latest = snapshots[-1]
    logger.info("Loading latest snapshot for %r from %s", query, latest)

    try:
        return json.loads(latest.read_text())
    except Exception as exc:
        logger.error("Failed to read snapshot %s: %s", latest, exc)
        return None
