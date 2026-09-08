from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin


class EmailThread(Base, TimestampMixin):
    """A conversation grouping of related emails.

    Not yet populated by the ingestion pipeline — real threading
    (Message-ID / In-Reply-To / References, or provider thread IDs)
    is a dedicated later phase. The table and the Email.thread_id FK
    exist now so that phase only has to add population logic, not a
    schema migration.
    """

    __tablename__ = "email_threads"

    id: Mapped[int] = mapped_column(primary_key=True)
    email_account_id: Mapped[int] = mapped_column(ForeignKey("email_accounts.id"), index=True)
    provider_thread_id: Mapped[str | None] = mapped_column(String(255), index=True, nullable=True)
    subject: Mapped[str | None] = mapped_column(String(998), nullable=True)

    email_account: Mapped["EmailAccount"] = relationship(back_populates="threads")
    emails: Mapped[list["Email"]] = relationship(back_populates="thread")


class Email(Base, TimestampMixin):
    """A single ingested email, normalized from the provider (IMAP today).

    `urgency` is the existing rule-based High/Medium/Low heuristic
    (services/email_service.categorize_email), applied at ingestion time.
    `category` (Work/Personal/Finance/...) is a separate, currently-NULL
    field — real classification is a later AI-pipeline phase. These were
    previously conflated under one field called "category" in the
    Phase 1 response schema; that was a naming mistake corrected here.

    `organization` is likewise NULL until entity/sender extraction exists.
    """

    __tablename__ = "emails"
    __table_args__ = (
        UniqueConstraint("email_account_id", "provider_message_id", name="uq_account_message_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    email_account_id: Mapped[int] = mapped_column(ForeignKey("email_accounts.id"), index=True)
    thread_id: Mapped[int | None] = mapped_column(ForeignKey("email_threads.id"), index=True, nullable=True)

    provider_message_id: Mapped[str] = mapped_column(String(998), index=True)
    sender: Mapped[str | None] = mapped_column(String(998), nullable=True)
    recipients: Mapped[str | None] = mapped_column(String(998), nullable=True)
    subject: Mapped[str] = mapped_column(String(998), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True, nullable=True)

    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    urgency: Mapped[str | None] = mapped_column(String(20), nullable=True)
    category: Mapped[str | None] = mapped_column(String(50), nullable=True)
    organization: Mapped[str | None] = mapped_column(String(255), nullable=True)
    processing_status: Mapped[str] = mapped_column(String(20), default="ingested")

    email_account: Mapped["EmailAccount"] = relationship(back_populates="emails")
    thread: Mapped["EmailThread | None"] = relationship(back_populates="emails")
    tasks: Mapped[list["Task"]] = relationship(back_populates="email", cascade="all, delete-orphan")
    generated_replies: Mapped[list["GeneratedReply"]] = relationship(
        back_populates="email", cascade="all, delete-orphan"
    )
