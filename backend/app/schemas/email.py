from datetime import datetime
from enum import Enum

from pydantic import BaseModel

from app.schemas.task import TaskOut


class UrgencyLevel(str, Enum):
    """Rule-based urgency tag.

    This is a keyword heuristic, not an AI/ML classification — kept
    deliberately simple in this phase. Real classification (LLM-backed,
    with confidence scores) is planned for a later AI pipeline phase and
    will replace or augment this.
    """

    high = "High"
    medium = "Medium"
    low = "Low"


class EmailMessage(BaseModel):
    """Shape produced by normalization — a freshly parsed, not-yet-persisted
    message with normalized (not raw-header) sender/recipients. See EmailOut
    for the persisted/API shape.
    """

    message_id: str | None = None
    subject: str
    sender_name: str | None = None
    sender_email: str | None = None
    recipients: list[str] = []
    in_reply_to: str | None = None
    references_header: str | None = None
    received_at: datetime | None = None
    body: str
    category: UrgencyLevel


class EmailOut(BaseModel):
    """API-facing shape of a persisted Email row (see models/email.py)."""

    model_config = {"from_attributes": True}

    id: int
    thread_id: int | None
    provider_message_id: str
    sender_name: str | None
    sender_email: str | None
    recipients: str | None
    in_reply_to: str | None
    references_header: str | None
    subject: str
    body: str
    received_at: datetime | None
    is_read: bool
    urgency: str | None
    category: str | None
    organization: str | None
    processing_status: str
    tasks: list[TaskOut] = []


class EmailThreadOut(BaseModel):
    """API-facing shape of an EmailThread with its member emails."""

    model_config = {"from_attributes": True}

    id: int
    subject: str | None
    provider_thread_id: str | None
    emails: list[EmailOut]
