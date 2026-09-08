"""Orchestrates: source Email -> TaskExtractor -> persisted Task rows.

Kept separate from app/api/* (never called directly from a route) and
from app/services/task_extractor_*.py (which only know how to produce
ExtractedTask candidates, not how to persist them) — same layering
discipline as email_sync_service.py / email_threading_service.py.
"""

import logging

from sqlalchemy.orm import Session

from app.models import Email, Task
from app.repositories import task_repository
from app.services.task_extractor_base import TaskExtractionError
from app.services.task_extractor_factory import get_task_extractor

logger = logging.getLogger(__name__)


def extract_and_persist_tasks(db: Session, email: Email) -> list[Task]:
    """Idempotent: if `email` already has Task rows, they are returned
    unchanged rather than re-extracted. In the normal sync pipeline this
    never actually happens twice for the same email anyway — Phase 2/3
    dedup means email_repository.create() only ever runs once per
    message — but this guard keeps the function correct in isolation
    rather than relying on caller discipline (the same pattern
    email_threading_service.assign_thread uses).

    Extraction failures (a bug in the extractor, or — for an eventual
    LLM-backed extractor — a call failure or invalid structured output)
    are caught and logged, never raised: one email's extraction failing
    must not corrupt the database or abort the surrounding sync batch.
    """
    existing = task_repository.list_by_email(db, email.id)
    if existing:
        return existing

    extractor = get_task_extractor()
    try:
        extracted = extractor.extract(email)
    except TaskExtractionError:
        logger.warning("Task extraction failed for email_id=%s", email.id, exc_info=True)
        return []
    except Exception:
        logger.warning("Unexpected task extraction failure for email_id=%s", email.id, exc_info=True)
        return []

    return [task_repository.create(db, email.id, item) for item in extracted]
