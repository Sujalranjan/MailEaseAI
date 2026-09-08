from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db.session import get_db
from app.models import EmailAccount
from app.repositories import task_repository
from app.schemas.task import TaskOut

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get("/", response_model=list[TaskOut])
def list_tasks(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> list[TaskOut]:
    if not settings.imap_is_configured():
        raise HTTPException(status_code=503, detail="Email account is not configured.")

    # Read-only lookup (no get-or-create): a GET request should never
    # have the side effect of provisioning an account. If no account has
    # been created yet (i.e. /emails/ has never been synced), there are
    # by definition no tasks yet either.
    account = db.query(EmailAccount).filter_by(email_address=settings.email_address).one_or_none()
    if account is None:
        return []
    return task_repository.list_by_account(db, account.id)


@router.get("/{task_id}", response_model=TaskOut)
def get_task(task_id: int, db: Session = Depends(get_db)) -> TaskOut:
    task = task_repository.get_by_id(db, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found.")
    return task
