from email.utils import parsedate_to_datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Email
from app.schemas.email import EmailMessage


def get_by_provider_message_id(db: Session, email_account_id: int, provider_message_id: str) -> Email | None:
    stmt = select(Email).where(
        Email.email_account_id == email_account_id,
        Email.provider_message_id == provider_message_id,
    )
    return db.execute(stmt).scalar_one_or_none()


def _parse_received_at(raw_date: str | None):
    if not raw_date:
        return None
    try:
        return parsedate_to_datetime(raw_date)
    except (TypeError, ValueError):
        return None


def create(db: Session, email_account_id: int, parsed: EmailMessage) -> Email:
    """Insert a new Email row from a freshly-fetched, not-yet-persisted
    EmailMessage. Caller is responsible for having already checked
    get_by_provider_message_id to avoid duplicates.
    """
    row = Email(
        email_account_id=email_account_id,
        provider_message_id=parsed.message_id,
        sender=parsed.sender,
        recipients=parsed.recipients,
        subject=parsed.subject,
        body=parsed.body,
        received_at=_parse_received_at(parsed.date),
        urgency=parsed.category.value,
    )
    db.add(row)
    db.flush()
    return row


def list_by_account(db: Session, email_account_id: int, limit: int = 100) -> list[Email]:
    stmt = (
        select(Email)
        .where(Email.email_account_id == email_account_id)
        .order_by(Email.received_at.desc().nulls_last(), Email.id.desc())
        .limit(limit)
    )
    return list(db.execute(stmt).scalars().all())
