"""LLM-backed task extraction — demonstrates the pluggable interface and
the required safety properties (structured, validated output; never
write arbitrary model output to the database) but is NOT wired into the
active sync pipeline and has NOT been verified against a real provider,
since no LLM API key/provider is configured in this environment.
RuleBasedTaskExtractor is what actually runs today.

This class exists so a real provider can be plugged in later by
supplying a concrete LLMClient (e.g. wrapping the Anthropic or OpenAI
SDK), without touching the extraction interface, the sync pipeline, or
the persistence layer — the same EmailProvider-style abstraction used
for IMAP/Gmail in app/integrations/.
"""

import json
import logging
from datetime import datetime
from typing import Protocol

from pydantic import BaseModel, ValidationError, field_validator

from app.models import Email
from app.schemas.task import ExtractedTask
from app.services.task_extractor_base import TaskExtractionError, TaskExtractor

logger = logging.getLogger(__name__)


class LLMClient(Protocol):
    """Minimal interface a real provider client must satisfy. Deliberately
    provider-agnostic (no Anthropic/OpenAI-specific types) so swapping
    providers never touches this extractor. Tests inject a fake
    implementation; no concrete network-calling implementation exists in
    this codebase yet.
    """

    def complete(self, prompt: str) -> str: ...


class _LLMTaskItem(BaseModel):
    title: str
    description: str | None = None
    deadline_iso: str | None = None
    priority: str | None = None

    @field_validator("title")
    @classmethod
    def title_not_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("title must not be empty")
        return value


class _LLMTaskList(BaseModel):
    tasks: list[_LLMTaskItem]


_PROMPT_TEMPLATE = """Extract actionable tasks from the email below. Return ONLY a JSON object matching exactly this shape, with no prose before or after it:
{{"tasks": [{{"title": "...", "description": "...", "deadline_iso": "YYYY-MM-DDTHH:MM:SS or null", "priority": "High, Medium, Low, or null"}}]}}
If there are no actionable tasks, return {{"tasks": []}}. Do not invent a deadline that isn't stated or clearly implied in the email.

Subject: {subject}
Body:
{body}
"""


class LLMTaskExtractor(TaskExtractor):
    def __init__(self, client: LLMClient):
        self._client = client

    def extract(self, email: Email) -> list[ExtractedTask]:
        prompt = _PROMPT_TEMPLATE.format(subject=email.subject, body=email.body)

        try:
            raw_response = self._client.complete(prompt)
        except Exception as exc:
            raise TaskExtractionError("LLM call failed") from exc

        try:
            payload = json.loads(raw_response)
            validated = _LLMTaskList.model_validate(payload)
        except (json.JSONDecodeError, ValidationError) as exc:
            # Never write arbitrary/malformed model output to the database.
            raise TaskExtractionError("LLM returned invalid structured output") from exc

        tasks: list[ExtractedTask] = []
        for item in validated.tasks:
            deadline, confidence = None, None
            if item.deadline_iso:
                try:
                    deadline = datetime.fromisoformat(item.deadline_iso)
                    confidence = "confirmed"
                except ValueError:
                    logger.warning(
                        "LLM returned unparseable deadline_iso=%r; dropping deadline, keeping task",
                        item.deadline_iso,
                    )
            tasks.append(
                ExtractedTask(
                    title=item.title,
                    description=item.description,
                    deadline=deadline,
                    deadline_confidence=confidence,
                    priority=item.priority,
                )
            )
        return tasks
