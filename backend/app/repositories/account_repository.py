from sqlalchemy.orm import Session

from app.config import Settings
from app.models import EmailAccount, User


def get_or_create_default_account(db: Session, settings: Settings) -> EmailAccount:
    """Return the single bootstrap EmailAccount for the configured mailbox,
    creating its User and EmailAccount rows on first use.

    This is a deliberate placeholder for real multi-user auth + Gmail
    OAuth account linking (a later phase). Callers must have already
    verified settings.imap_is_configured().
    """
    assert settings.email_address is not None

    account = db.query(EmailAccount).filter_by(email_address=settings.email_address).one_or_none()
    if account is not None:
        return account

    user = db.query(User).filter_by(email=settings.email_address).one_or_none()
    if user is None:
        user = User(email=settings.email_address)
        db.add(user)
        db.flush()

    account = EmailAccount(
        user_id=user.id,
        email_address=settings.email_address,
        provider="imap",
        imap_server=settings.imap_server,
    )
    db.add(account)
    db.flush()
    return account
