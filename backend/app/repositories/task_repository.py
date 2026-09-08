from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Email, Task
from app.schemas.task import ExtractedTask


def list_by_email(db: Session, email_id: int) -> list[Task]:
    return list(db.execute(select(Task).where(Task.email_id == email_id)).scalars().all())


def create(db: Session, email_id: int, item: ExtractedTask) -> Task:
    row = Task(
        email_id=email_id,
        title=item.title,
        description=item.description,
        deadline=item.deadline,
        deadline_confidence=item.deadline_confidence,
        priority=item.priority,
    )
    db.add(row)
    db.flush()
    return row


def list_by_account(db: Session, email_account_id: int, limit: int = 200) -> list[Task]:
    stmt = (
        select(Task)
        .join(Email, Task.email_id == Email.id)
        .where(Email.email_account_id == email_account_id)
        .order_by(Task.deadline.is_(None), Task.deadline.asc(), Task.id.desc())
        .limit(limit)
    )
    return list(db.execute(stmt).scalars().all())


def get_by_id(db: Session, task_id: int) -> Task | None:
    return db.get(Task, task_id)
