from datetime import datetime, timezone
from unittest.mock import patch

from app.models import Email, EmailAccount, EmailThread, Task, User
from app.services.email_threading_service import assign_thread
from app.services.task_extraction_service import extract_and_persist_tasks
from app.services.task_extractor_base import TaskExtractionError


def make_account(db_session, email="user@example.com"):
    user = User(email=email)
    db_session.add(user)
    db_session.flush()
    account = EmailAccount(user_id=user.id, email_address=email, provider="imap")
    db_session.add(account)
    db_session.flush()
    return account


def make_email(db_session, account, message_id, body="Please submit the report by Friday.", **kwargs):
    email = Email(
        email_account_id=account.id,
        provider_message_id=message_id,
        subject=kwargs.pop("subject", "Hi"),
        body=body,
        received_at=kwargs.pop("received_at", datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc)),
        urgency=kwargs.pop("urgency", "Low"),
        **kwargs,
    )
    db_session.add(email)
    db_session.flush()
    return email


class TestBasicExtraction:
    def test_persists_extracted_tasks_linked_to_source_email(self, db_session):
        account = make_account(db_session)
        email = make_email(db_session, account, "<1@example.com>")

        tasks = extract_and_persist_tasks(db_session, email)

        assert len(tasks) == 1
        assert tasks[0].email_id == email.id
        assert db_session.query(Task).count() == 1

    def test_no_actionable_content_persists_nothing(self, db_session):
        account = make_account(db_session)
        email = make_email(db_session, account, "<2@example.com>", body="Just a quick FYI, nothing needed.")

        tasks = extract_and_persist_tasks(db_session, email)

        assert tasks == []
        assert db_session.query(Task).count() == 0


class TestIdempotency:
    def test_calling_twice_on_same_email_does_not_duplicate(self, db_session):
        account = make_account(db_session)
        email = make_email(db_session, account, "<3@example.com>")

        first = extract_and_persist_tasks(db_session, email)
        second = extract_and_persist_tasks(db_session, email)

        assert [t.id for t in first] == [t.id for t in second]
        assert db_session.query(Task).count() == 1

    def test_same_task_across_repeated_sync_style_calls(self, db_session):
        # Simulates re-running extraction as part of a repeated sync,
        # the way email_sync_service would if it were ever called again
        # for the same already-persisted email.
        account = make_account(db_session)
        email = make_email(
            db_session, account, "<4@example.com>", body="Please submit A by Friday. Please submit B by Monday."
        )

        extract_and_persist_tasks(db_session, email)
        extract_and_persist_tasks(db_session, email)
        extract_and_persist_tasks(db_session, email)

        assert db_session.query(Task).count() == 2


class TestExtractionFailureHandling:
    def test_extractor_exception_is_caught_and_returns_empty_list(self, db_session):
        account = make_account(db_session)
        email = make_email(db_session, account, "<5@example.com>")

        with patch(
            "app.services.task_extraction_service.get_task_extractor"
        ) as mock_factory:
            mock_factory.return_value.extract.side_effect = TaskExtractionError("boom")
            tasks = extract_and_persist_tasks(db_session, email)

        assert tasks == []
        assert db_session.query(Task).count() == 0

    def test_unexpected_extractor_exception_is_also_caught(self, db_session):
        account = make_account(db_session)
        email = make_email(db_session, account, "<6@example.com>")

        with patch(
            "app.services.task_extraction_service.get_task_extractor"
        ) as mock_factory:
            mock_factory.return_value.extract.side_effect = RuntimeError("unexpected bug")
            tasks = extract_and_persist_tasks(db_session, email)

        assert tasks == []


class TestThreadAssociation:
    def test_task_reachable_from_correct_thread_via_source_email(self, db_session):
        account = make_account(db_session)
        root = make_email(db_session, account, "<root@example.com>", body="Please submit the report by Friday.")
        thread = assign_thread(db_session, account.id, root)

        tasks = extract_and_persist_tasks(db_session, root)

        assert tasks[0].email.thread_id == thread.id
        assert tasks[0] in [t for e in thread.emails for t in e.tasks]

    def test_out_of_order_threaded_emails_each_keep_correct_task_and_thread(self, db_session):
        # Reply arrives (and is task-extracted) before its parent, then
        # the parent arrives later and the threads merge -- tasks from
        # both messages must still resolve to the single merged thread.
        account = make_account(db_session)
        reply = make_email(
            db_session,
            account,
            "<reply@example.com>",
            body="Please confirm by Monday.",
            in_reply_to="<root2@example.com>",
        )
        assign_thread(db_session, account.id, reply)
        extract_and_persist_tasks(db_session, reply)

        root = make_email(db_session, account, "<root2@example.com>", body="Please submit the draft by Friday.")
        merged_thread = assign_thread(db_session, account.id, root)
        extract_and_persist_tasks(db_session, root)

        all_tasks_in_thread = [t for e in merged_thread.emails for t in e.tasks]
        assert len(all_tasks_in_thread) == 2
        assert db_session.query(EmailThread).count() == 1


class TestCrossAccountIsolation:
    def test_tasks_from_different_accounts_do_not_mix(self, db_session):
        account_a = make_account(db_session, email="a@example.com")
        account_b = make_account(db_session, email="b@example.com")
        email_a = make_email(db_session, account_a, "<a1@example.com>")
        email_b = make_email(db_session, account_b, "<b1@example.com>")

        tasks_a = extract_and_persist_tasks(db_session, email_a)
        tasks_b = extract_and_persist_tasks(db_session, email_b)

        assert tasks_a[0].email.email_account_id == account_a.id
        assert tasks_b[0].email.email_account_id == account_b.id
        assert tasks_a[0].id != tasks_b[0].id
