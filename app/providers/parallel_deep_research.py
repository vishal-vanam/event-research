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

            prompt = (
                f"Deep research on notable events, concerts, festivals, nightlife and high-signal "
                f"gatherings in {city} over the next {days_ahead} days. "
                f"Focus on: specific dates, venues, expected scale, typical audience, price ranges, "
                f"and any unique local context. "
                f"Return a structured markdown report with clear sections (Overview, Major Events, "
                f"Music, Sports, Family-Friendly, Nightlife) and bullet points. Include inline "
                f"citations for key claims."
            )

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

                # 2) Block until result, with a timeout in seconds
                run_result = self.client.task_run.result(
                    task_run.run_id,
                    api_timeout=120,  # adjust as you like
                )

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