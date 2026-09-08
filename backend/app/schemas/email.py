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
    message_id: str | None = None
    subject: str
    sender: str | None = None
    date: str | None = None
    body: str
    category: UrgencyLevel
    deadlines: list[str] = []
