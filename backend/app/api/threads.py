from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.repositories.thread_repository import get_by_id
from app.schemas.email import EmailThreadOut

router = APIRouter(prefix="/threads", tags=["threads"])


@router.get("/{thread_id}", response_model=EmailThreadOut)
def get_thread(thread_id: int, db: Session = Depends(get_db)) -> EmailThreadOut:
    thread = get_by_id(db, thread_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="Thread not found.")
    return thread
