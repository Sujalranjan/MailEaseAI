from fastapi import APIRouter, Depends, HTTPException

from app.config import Settings, get_settings
from app.schemas.email import EmailMessage
from app.services.email_service import EmailFetchError, fetch_emails

router = APIRouter(prefix="/emails", tags=["emails"])


@router.get("/", response_model=list[EmailMessage])
def list_emails(settings: Settings = Depends(get_settings)) -> list[EmailMessage]:
    if not settings.imap_is_configured():
        raise HTTPException(
            status_code=503,
            detail="Email account is not configured. Set EMAIL_ADDRESS and EMAIL_APP_PASSWORD.",
        )
    try:
        return fetch_emails(settings)
    except EmailFetchError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
