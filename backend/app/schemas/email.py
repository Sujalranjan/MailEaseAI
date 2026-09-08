from datetime import datetime
from enum import Enum

from pydantic import BaseModel


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
    """Shape returned by the IMAP fetch layer — a freshly parsed,
    not-yet-persisted message. See EmailOut for the persisted/API shape.
    """

    message_id: str | None = None
    subject: str
    sender: str | None = None
    recipients: str | None = None
    date: str | None = None
    body: str
    category: UrgencyLevel
    deadlines: list[str] = []


class EmailOut(BaseModel):
    """API-facing shape of a persisted Email row (see models/email.py)."""

    model_config = {"from_attributes": True}

    id: int
    provider_message_id: str
    sender: str | None
    recipients: str | None
    subject: str
    body: str
    received_at: datetime | None
    is_read: bool
    urgency: str | None
    category: str | None
    organization: str | None
    processing_status: str
