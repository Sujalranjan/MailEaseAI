from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin


class GeneratedReply(Base, TimestampMixin):
    """An AI-drafted reply to an email, reviewable/editable before sending.

    Not yet populated — LLM-backed reply generation is a later phase.
    `generated_text` (model output) and `edited_text` (user's edit) are
    kept separate so the original generation is never silently lost,
    which matters both for the "edit before send" UX requirement and
    for any future reply-quality evaluation.
    """

    __tablename__ = "generated_replies"

    id: Mapped[int] = mapped_column(primary_key=True)
    email_id: Mapped[int] = mapped_column(ForeignKey("emails.id"), index=True)

    prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    generated_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    edited_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="draft")

    email: Mapped["Email"] = relationship(back_populates="generated_replies")
