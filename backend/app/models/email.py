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
    (services/email_normalizer.categorize_email), applied at ingestion
    time. `category` (Work/Personal/Finance/...) is a separate,
    currently-NULL field — real classification is a later AI-pipeline
    phase. These were previously conflated under one field called
    "category" in the Phase 1 response schema; that was a naming mistake
    corrected in Phase 2.

    `organization` is likewise NULL until entity/sender extraction exists.

    `sender_name`/`sender_email` and `recipients` are normalized (parsed
    address components, not raw "Name <addr>" header text) — see
    services/email_normalizer.py. `in_reply_to`/`references_header`
    capture the standard MIME threading headers as raw values; grouping
    them into EmailThread rows is not implemented yet (a later phase).

    `received_at` is always stored normalized to UTC. SQLite (unlike
    Postgres) silently drops timezone info on any datetime it stores —
    confirmed by a round-trip check during Phase 3 — so a timezone-aware
    value written here would come back naive and wrong for any sender
    not in UTC. Normalizing to UTC before storing, and treating every
    stored value as naive-UTC by convention, sidesteps that and behaves
    identically if this ever moves to Postgres.
    """

    __tablename__ = "emails"
    __table_args__ = (
        UniqueConstraint("email_account_id", "provider_message_id", name="uq_account_message_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    email_account_id: Mapped[int] = mapped_column(ForeignKey("email_accounts.id"), index=True)
    thread_id: Mapped[int | None] = mapped_column(ForeignKey("email_threads.id"), index=True, nullable=True)

    provider_message_id: Mapped[str] = mapped_column(String(998), index=True)
    sender_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sender_email: Mapped[str | None] = mapped_column(String(320), index=True, nullable=True)
    recipients: Mapped[str | None] = mapped_column(String(998), nullable=True)
    in_reply_to: Mapped[str | None] = mapped_column(String(998), nullable=True)
    references_header: Mapped[str | None] = mapped_column(String(998), nullable=True)
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
