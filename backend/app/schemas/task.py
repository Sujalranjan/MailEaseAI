from datetime import datetime

from pydantic import BaseModel


class ExtractedTask(BaseModel):
    """Output of a TaskExtractor — validated, structured, not-yet-persisted.
    Every extractor implementation (rule-based or LLM-backed) must
    produce this shape; nothing downstream ever writes raw extractor
    output straight into the database.
    """

    title: str
    description: str | None = None
    deadline: datetime | None = None
    deadline_confidence: str | None = None  # "confirmed" | "ambiguous" | None
    priority: str | None = None


class TaskOut(BaseModel):
    """API-facing shape of a persisted Task row (see models/task.py)."""

    model_config = {"from_attributes": True}

    id: int
    email_id: int
    title: str
    description: str | None
    deadline: datetime | None
    deadline_confidence: str | None
    priority: str | None
    status: str
