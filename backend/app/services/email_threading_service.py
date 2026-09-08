"""Groups Email rows into EmailThread conversations using Message-ID
evidence only (In-Reply-To / References) — never subject text, which
two unrelated conversations can share coincidentally.

Algorithm, run once per newly-persisted Email M (see assign_thread):

  1. Backward: parse M's References + In-Reply-To into a list of
     referenced Message-IDs. Any already-stored email (same account)
     whose provider_message_id is in that list is a proven ancestor —
     take its thread.
  2. Forward: any already-stored email (same account) whose In-Reply-To
     equals M's own Message-ID, or whose References mentions it, is a
     proven descendant that arrived before M (out-of-order case) — take
     its thread too.
  3. No candidates -> M starts a new thread. One candidate -> M joins it.
     Multiple distinct candidates -> they are provably one conversation
     (each linked to M by an explicit header), so merge them into the
     oldest thread and re-parent every email off the others.

The forward References check is a per-account substring scan in Python,
not a SQL index lookup — References is free-text and SQL LIKE can't use
a normal index for a "contains" match anyway. Fine at personal-mailbox
scale (this account's own emails only); a real mail-server-scale system
would maintain a normalized (message_id -> referenced_message_id) join
table instead.
"""

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Email, EmailThread

_MESSAGE_ID_TOKEN = re.compile(r"<[^<>\s]+>")


def _extract_referenced_ids(references_header: str | None, in_reply_to: str | None) -> list[str]:
    ids: list[str] = []
    seen: set[str] = set()
    for header in (references_header, in_reply_to):
        if not header:
            continue
        cleaned = re.sub(r"[\r\n\t]+", " ", header)
        for token in _MESSAGE_ID_TOKEN.findall(cleaned):
            if token not in seen:
                seen.add(token)
                ids.append(token)
    return ids


def _find_ancestor_thread_ids(db: Session, email_account_id: int, email: Email, referenced_ids: list[str]) -> set[int]:
    if not referenced_ids:
        return set()
    rows = db.execute(
        select(Email.thread_id).where(
            Email.email_account_id == email_account_id,
            Email.id != email.id,
            Email.provider_message_id.in_(referenced_ids),
            Email.thread_id.isnot(None),
        )
    ).scalars().all()
    return {t for t in rows if t is not None}


def _find_descendant_thread_ids(db: Session, email_account_id: int, email: Email) -> set[int]:
    msgid = email.provider_message_id
    if not msgid:
        return set()

    thread_ids: set[int] = set()

    exact_matches = db.execute(
        select(Email.thread_id).where(
            Email.email_account_id == email_account_id,
            Email.id != email.id,
            Email.thread_id.isnot(None),
            Email.in_reply_to == msgid,
        )
    ).scalars().all()
    thread_ids.update(t for t in exact_matches if t is not None)

    candidates_with_refs = db.execute(
        select(Email).where(
            Email.email_account_id == email_account_id,
            Email.id != email.id,
            Email.thread_id.isnot(None),
            Email.references_header.isnot(None),
        )
    ).scalars().all()
    for candidate in candidates_with_refs:
        if msgid in candidate.references_header:
            thread_ids.add(candidate.thread_id)

    return thread_ids


def _merge_threads(db: Session, thread_ids: set[int]) -> EmailThread:
    """Merge multiple threads proven-by-evidence to be one conversation.

    Keeps the lowest-id (oldest/first-created) thread as canonical, for
    deterministic behavior regardless of which order threads are
    discovered in. Every email on the other thread(s) is re-parented
    before those thread rows are deleted, so no email is ever orphaned.
    """
    threads = db.execute(
        select(EmailThread).where(EmailThread.id.in_(thread_ids)).order_by(EmailThread.id)
    ).scalars().all()
    canonical = threads[0]

    for other in threads[1:]:
        members = db.execute(select(Email).where(Email.thread_id == other.id)).scalars().all()
        for member in members:
            member.thread_id = canonical.id
        # Flush the reassignment before deleting `other`. Without this,
        # SQLAlchemy's delete-cascade resolution re-queries for children
        # still pointing at `other.id` (since the UPDATE hasn't hit the
        # DB yet) and nulls their thread_id out from under the reassignment
        # above -- silently orphaning the merged messages. Confirmed via a
        # standalone repro during development, not a hypothetical risk.
        db.flush()
        db.delete(other)

    db.flush()
    return canonical


def assign_thread(db: Session, email_account_id: int, email: Email) -> EmailThread:
    """Assign `email` to a thread, creating or merging as needed, and
    return that thread. `email` must already be flushed (have an id) and
    have provider_message_id set — email_sync_service guarantees both
    before calling this, since messages without a Message-ID are never
    persisted in the first place.

    Idempotent even if called more than once for the same already-
    threaded email (email_sync_service never does this in practice —
    it's only called once per newly-inserted row — but the function
    stays correct in isolation rather than relying on that discipline):
    an email that already has a thread_id is left untouched rather than
    being re-evaluated from scratch, which would otherwise spuriously
    create a brand new thread for it (it has no *other* email to be
    found by, now that itself is excluded from its own search).
    """
    if email.thread_id is not None:
        return db.get(EmailThread, email.thread_id)

    referenced_ids = _extract_referenced_ids(email.references_header, email.in_reply_to)

    candidate_thread_ids = _find_ancestor_thread_ids(db, email_account_id, email, referenced_ids)
    candidate_thread_ids |= _find_descendant_thread_ids(db, email_account_id, email)

    if not candidate_thread_ids:
        thread = EmailThread(email_account_id=email_account_id, subject=email.subject)
        db.add(thread)
        db.flush()
    elif len(candidate_thread_ids) == 1:
        thread_id = next(iter(candidate_thread_ids))
        thread = db.get(EmailThread, thread_id)
    else:
        thread = _merge_threads(db, candidate_thread_ids)

    email.thread_id = thread.id
    db.flush()
    return thread
