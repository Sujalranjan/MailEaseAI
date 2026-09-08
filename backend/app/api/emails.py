from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db.session import get_db
from app.schemas.email import EmailOut
from app.services.email_service import EmailFetchError
from app.services.email_sync_service import sync_emails

router = APIRouter(prefix="/emails", tags=["emails"])


@router.get("/", response_model=list[EmailOut])
def list_emails(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> list[EmailOut]:
    if not settings.imap_is_configured():
        raise HTTPException(
            status_code=503,
            detail="Email account is not configured. Set EMAIL_ADDRESS and EMAIL_APP_PASSWORD.",
        )
    try:
        return sync_emails(db, settings)
    except EmailFetchError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
