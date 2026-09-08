from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin


class Task(Base, TimestampMixin):
    """An actionable item extracted from an email.

    Not yet populated automatically — real task/deadline extraction
    (turning "please submit the report by Friday" into a structured
    Task) is a later phase. The schema exists now so that phase is
    purely a service that inserts rows, not a migration.
    """

    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    email_id: Mapped[int] = mapped_column(ForeignKey("emails.id"), index=True)

    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True, nullable=True)
    priority: Mapped[str | None] = mapped_column(String(20), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)

    email: Mapped["Email"] = relationship(back_populates="tasks")
    calendar_event: Mapped["CalendarEvent | None"] = relationship(
        back_populates="task", cascade="all, delete-orphan", uselist=False
    )


class CalendarEvent(Base, TimestampMixin):
    """A Google Calendar event created from a Task.

    Not yet populated — Calendar OAuth/event creation is a later phase.
    `task_id` is unique so a Task can have at most one CalendarEvent,
    which is how duplicate-event creation will be prevented once that
    phase exists: check for an existing row before calling the API.
    """

    __tablename__ = "calendar_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), unique=True, index=True)

    google_event_id: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    calendar_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    start_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")

    task: Mapped["Task"] = relationship(back_populates="calendar_event")
