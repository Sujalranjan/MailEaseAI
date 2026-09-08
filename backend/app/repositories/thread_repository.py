from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import EmailThread


def get_by_id(db: Session, thread_id: int) -> EmailThread | None:
    return db.get(EmailThread, thread_id)
