"""Orchestrates: IMAP fetch -> dedupe by provider message ID -> persist -> read back.

Keeps app/services/email_service.py (pure IMAP + parsing, no DB) separate
from persistence (app/repositories/*), per the requirement not to put
database logic directly in the provider-fetch layer or in API routes.
"""

import logging

from sqlalchemy.orm import Session

from app.config import Settings
from app.models import Email
from app.repositories.account_repository import get_or_create_default_account
from app.repositories.email_repository import create, get_by_provider_message_id, list_by_account
from app.services.email_service import fetch_emails

logger = logging.getLogger(__name__)


def sync_emails(db: Session, settings: Settings) -> list[Email]:
    """Fetch from IMAP, persist anything new, and return the account's
    stored emails from the database (not the raw IMAP fetch result).

    Idempotent: calling this repeatedly with the same mailbox contents
    does not create duplicate rows, because each message is looked up
    by (email_account_id, provider_message_id) before insert.
    """
    account = get_or_create_default_account(db, settings)
    fetched = fetch_emails(settings)

    new_count = 0
    for parsed in fetched:
        if not parsed.message_id:
            # Can't dedupe reliably without a stable ID; skip rather than
            # risk either duplicate rows or false-duplicate merges.
            logger.warning("Skipping email with no Message-ID (subject=%r)", parsed.subject)
            continue

        existing = get_by_provider_message_id(db, account.id, parsed.message_id)
        if existing is not None:
            continue

        create(db, account.id, parsed)
        new_count += 1

    db.commit()
    logger.info("Sync complete: %d new email(s) stored", new_count)
    return list_by_account(db, account.id)
