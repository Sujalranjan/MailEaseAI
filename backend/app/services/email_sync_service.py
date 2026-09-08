"""Orchestrates: provider fetch -> normalize -> dedupe -> persist -> thread -> extract tasks -> read back.

Keeps app/integrations/* (provider connectivity), app/services/
email_normalizer.py (raw bytes -> structured data), app/services/
email_threading_service.py (conversation grouping), app/services/
task_extraction_service.py (actionable-task extraction), and
app/repositories/* (persistence) each responsible for one concern, per
the requirement not to put database or provider logic directly in the
other layers or in API routes.
"""

import logging

from sqlalchemy.orm import Session

from app.config import Settings
from app.integrations.imap_provider import IMAPProvider
from app.models import Email
from app.repositories.account_repository import get_or_create_default_account
from app.repositories.email_repository import create, get_by_provider_message_id, list_by_account
from app.services.email_normalizer import normalize_message
from app.services.email_threading_service import assign_thread
from app.services.task_extraction_service import extract_and_persist_tasks

logger = logging.getLogger(__name__)


def sync_emails(db: Session, settings: Settings) -> list[Email]:
    """Fetch new messages since the account's last sync, persist anything
    new, and return the account's stored emails from the database.

    Idempotent: (email_account_id, provider_message_id) is checked before
    every insert, so even a re-fetched or overlapping message never
    creates a duplicate row. The sync cursor (see IMAPProvider) is only
    advanced after a successful fetch, and the cursor update, inserts,
    and account creation all land in one commit — a crash or exception
    partway through never leaves the cursor ahead of what was actually
    persisted.

    Thread assignment (email_threading_service.assign_thread) runs once
    per newly-inserted email, inside this same transaction, so it is
    naturally idempotent too: an already-persisted email is never
    re-processed on a later sync call, and its thread_id is only ever
    revisited by an explicit evidence-based merge triggered by a later
    email in the same conversation.

    Task extraction (task_extraction_service.extract_and_persist_tasks)
    likewise runs once per newly-inserted email in this same transaction,
    and never raises — an extraction failure for one email is logged and
    treated as zero tasks found, never allowed to abort the batch.
    """
    account = get_or_create_default_account(db, settings)
    provider = IMAPProvider(settings)
    result = provider.fetch_new_messages(account.sync_cursor, settings.sync_batch_size)

    new_count = 0
    skipped_malformed = 0
    skipped_no_id = 0

    for raw in result.messages:
        try:
            parsed = normalize_message(raw.raw_bytes)
        except Exception:
            logger.warning("Skipping malformed message (provider_uid=%s)", raw.provider_uid, exc_info=True)
            skipped_malformed += 1
            continue

        if not parsed.message_id:
            # Can't dedupe reliably without a stable ID; skip rather than
            # risk either duplicate rows or false-duplicate merges.
            logger.warning("Skipping email with no Message-ID (subject=%r)", parsed.subject)
            skipped_no_id += 1
            continue

        if get_by_provider_message_id(db, account.id, parsed.message_id) is not None:
            continue

        row = create(db, account.id, parsed)
        assign_thread(db, account.id, row)
        extract_and_persist_tasks(db, row)
        new_count += 1

    if result.new_cursor is not None:
        account.sync_cursor = result.new_cursor

    db.commit()
    logger.info(
        "Sync complete: %d new, %d malformed skipped, %d missing-id skipped",
        new_count,
        skipped_malformed,
        skipped_no_id,
    )
    return list_by_account(db, account.id)
