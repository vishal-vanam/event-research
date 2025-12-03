import logging
from typing import Optional

from parallel import Parallel as ParallelClient
from parallel.types import TaskSpecParam, TextSchemaParam

from app.config import settings
from app.models import DeepResearchReport

logger = logging.getLogger(__name__)


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
        if not self.client:
            return None

        prompt = f"""
            You are an AI assistant that performs deep research about events.

            Your task: research upcoming public events in **{city}** happening in the next **{days_ahead} days**.

            You MUST produce **two outputs** in a single response, in this exact order:

            ---

            ## 1. Markdown Report (Human-Readable)

            Write a well-structured **Markdown report** with headings and bullet points covering:

            ### Summary
            - 2–4 bullet points summarizing the overall event scene in {city} for the next {days_ahead} days.

            ### Notable Upcoming Events
            For each important event, include:
            - **Event name**
            - Venue & neighborhood
            - Date/time
            - Type (music, sports, comedy, arts, etc.)
            - Short 1-sentence description

            ### Notable Venues
            List any major venues with short notes.

            ### Sources
            List the URLs you used.

            ---

            ## 2. Structured JSON Block (Machine-Readable)

            At the VERY END of the message, output **one fenced JSON code block**
            containing a single JSON object matching this schema *exactly*:

            ```json
            {{
            "events": [
                {{
                "name": "string or null",
                "start_time": "ISO-8601 string or null",
                "end_time": "ISO-8601 string or null",

                "venue_name": "string or null",
                "city": "string or null",
                "country": "string or null",
                "lat": "number or null",
                "lon": "number or null",

                "category": "string or null",
                "url": "string or null",

                "price_min": "number or null",
                "price_max": "number or null",

                "headcount_bucket": "small | medium | large | stadium | null",
                "headcount_confidence": "number between 0.0 and 1.0 or null"
                }}
            ]
            }}
            """
        logger.info(
            "ParallelDeepResearchProvider.research_city_events: city=%s days_ahead=%s processor=%s",
            city,
            days_ahead,
            self.processor,
        )

        try:
            # 1) Create the task run (returns immediately)
            task_run = self.client.task_run.create(
                input=prompt,
                processor=self.processor,
                task_spec=TaskSpecParam(
                    output_schema=TextSchemaParam()  # text / markdown output
                ),
            )

            # 2) Block until result
            run_result = self.client.task_run.result(task_run.run_id)

        except Exception as exc:
            logger.error("Parallel Deep Research API request failed: %s", exc)
            return None

        # Extract text output
        output = getattr(run_result, "output", None)
        if output is None:
            logger.error("Parallel Deep Research result had no 'output' field: %r", run_result)
            return None

        report_text: Optional[str] = None
        for attr in ("content", "report", "text"):
            if hasattr(output, attr):
                val = getattr(output, attr)
                if isinstance(val, str) and val.strip():
                    report_text = val
                    break

        if not report_text:
            report_text = str(output).strip()

        if not report_text:
            logger.error("Parallel Deep Research returned empty output object: %r", output)
            return None

        return DeepResearchReport(
            provider=self.name,
            city=city,
            days_ahead=days_ahead,
            report=report_text,
        )

