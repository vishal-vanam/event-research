# app/providers/parallel_deep_research.py
from __future__ import annotations

import logging
from typing import Optional, Dict, Any, List

from parallel import Parallel as ParallelClient
from parallel.types import TaskSpecParam, JsonSchemaParam  # keep your actual schema import here

from app.config import settings
from app.models import DeepResearchReport

logger = logging.getLogger(__name__)

EVENTS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "events": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": ["string", "null"]},
                    "start_time": {"type": ["string", "null"]},
                    "end_time": {"type": ["string", "null"]},
                    "venue_name": {"type": ["string", "null"]},
                    "city": {"type": ["string", "null"]},
                    "country": {"type": ["string", "null"]},
                    "lat": {"type": ["number", "null"]},
                    "lon": {"type": ["number", "null"]},
                    "category": {"type": ["string", "null"]},
                    "url": {"type": ["string", "null"]},
                    "price_min": {"type": ["number", "null"]},
                    "price_max": {"type": ["number", "null"]},
                    "headcount_bucket": {
                        "type": ["string", "null"],
                        "enum": ["small", "medium", "large", "stadium", None],
                    },
                    "headcount_confidence": {
                        "type": ["number", "null"],
                        "minimum": 0.0,
                        "maximum": 1.0,
                    },
                },
                "required": ["name"],
                "additionalProperties": True,
            },
        }
    },
    "required": ["events"],
    "additionalProperties": False,
}


class ParallelDeepResearchProvider:
    name = "parallel-deep-research"

    def __init__(self) -> None:
        self.api_key: Optional[str] = settings.parallel_api_key
        self.processor: str = settings.parallel_processor or "ultra"

        if not self.api_key:
            logger.warning(
                "Parallel PARALLEL_API_KEY not set; ParallelDeepResearchProvider will be disabled."
            )
            self.client = None
        else:
            self.client = ParallelClient(api_key=self.api_key)

    @property
    def is_configured(self) -> bool:
        return self.client is not None

    def research_city_events(self, city: str, days_ahead: int = 7) -> Optional[DeepResearchReport]:
        """
        Call Parallel Task Run API and try to extract a structured events list
        from the SDK's TaskRunJsonOutput / FieldBasis objects.

        We do NOT do json.loads here; we work directly with the Python objects.
        """
        if not self.client:
            return None

        prompt = f"""
        You are an event data extractor.

        Goal: Populate the "events" list in the JSON schema with real, upcoming in-person events in "{city}" over the next {days_ahead} days.

        You MUST:
        - Include as many real events as you can find.
        - For each event, fill fields like name, start_time, venue_name, city, and url as accurately as possible.
        - If you cannot find a specific field, leave it null.
        - Do NOT leave the "events" list empty unless there are truly no relevant events.

        Focus on concerts, sports, festivals, cultural events, and significant community events.
        """


        logger.info(
            "ParallelDeepResearchProvider.research_city_events: city=%s days_ahead=%s processor=%s",
            city,
            days_ahead,
            self.processor,
        )

        try:
            task_run = self.client.task_run.create(
                input=prompt,
                processor=self.processor,
                task_spec=TaskSpecParam(
                    output_schema=JsonSchemaParam(
                        json_schema=EVENTS_SCHEMA  # or 'schema=' depending on SDK version
                    )
                ),
            )

            run_result = self.client.task_run.result(task_run.run_id)
        except Exception as exc:
            logger.error("Parallel Deep Research API request failed: %s", exc)
            return None

        # This is whatever the SDK exposes as "output"
        output = getattr(run_result, "output", None)
        if output is None:
            logger.error("Parallel Deep Research result had no 'output' field: %r", run_result)
            return None

        # HARD DEBUG: always visible even if logging misconfigures
        print("[pws-debug] output type:", type(output))
        print("[pws-debug] output repr snippet:", repr(output)[:600])
        # ------------------------------------------------------------------
        # 1) Try to extract structured JSON-like data from the SDK objects
        # ------------------------------------------------------------------
        structured: Dict[str, Any] = {"events": []}

        def _find_events_in_dict(obj: Any) -> Optional[List[Any]]:
            """
            Recursively search for a key named 'events' whose value is a list.
            Return that list if found, else None.
            """
            if isinstance(obj, dict):
                if "events" in obj and isinstance(obj["events"], list):
                    return obj["events"]
                for v in obj.values():
                    found = _find_events_in_dict(v)
                    if found is not None:
                        return found
            elif isinstance(obj, list):
                for v in obj:
                    found = _find_events_in_dict(v)
                    if found is not None:
                        return found
            return None

        try:
            raw: Optional[Dict[str, Any]] = None

            if isinstance(output, dict):
                raw = output
            elif hasattr(output, "model_dump"):
                # pydantic v2 style
                raw = output.model_dump()  # type: ignore[attr-defined]
            elif hasattr(output, "dict"):
                # pydantic v1 style
                raw = output.dict()  # type: ignore[attr-defined]
            elif hasattr(output, "data"):
                maybe = output.data  # type: ignore[attr-defined]
                if isinstance(maybe, dict):
                    raw = maybe

            if raw is not None:
                events_list = _find_events_in_dict(raw) or []
                normalized: List[Dict[str, Any]] = []

                for item in events_list:
                    if isinstance(item, dict):
                        normalized.append(item)
                    elif hasattr(item, "model_dump"):
                        normalized.append(item.model_dump())  # type: ignore[attr-defined]
                    elif hasattr(item, "dict"):
                        normalized.append(item.dict())  # type: ignore[attr-defined]
                    else:
                        try:
                            normalized.append(vars(item))
                        except Exception:
                            continue

                structured = {"events": normalized}
            else:
                logger.warning(
                    "ParallelDeepResearchProvider: could not derive raw dict from output type %r",
                    type(output),
                )

        except Exception as exc:
            logger.error("Failed to interpret Parallel structured output: %s", exc)


        # ------------------------------------------------------------------
        # 2) Keep a string version around for debugging / inspection
        # ------------------------------------------------------------------
        report_text = str(output)

        logger.info(
            "ParallelDeepResearchProvider: extracted %d events from structured output",
            len(structured.get("events", [])),
        )
        logger.info("ParallelDeepResearchProvider raw output repr: %r", output)
        logger.info("ParallelDeepResearchProvider structured keys: %s", list(structured.keys()))
        logger.info("ParallelDeepResearchProvider structured events length: %d", len(structured.get("events", [])))

        return DeepResearchReport(
            provider=self.name,
            city=city,
            days_ahead=days_ahead,
            report=report_text,
            structured=structured,
        )
