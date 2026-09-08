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


def create(db: Session, email_account_id: int, parsed: EmailMessage) -> Email:
    """Insert a new Email row from an already-normalized EmailMessage.
    Caller is responsible for having already checked
    get_by_provider_message_id to avoid duplicates.
    """
    row = Email(
        email_account_id=email_account_id,
        provider_message_id=parsed.message_id,
        sender_name=parsed.sender_name,
        sender_email=parsed.sender_email,
        recipients=", ".join(parsed.recipients) or None,
        in_reply_to=parsed.in_reply_to,
        references_header=parsed.references_header,
        subject=parsed.subject,
        body=parsed.body,
        received_at=parsed.received_at,
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
