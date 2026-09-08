import pytest
from sqlalchemy.exc import IntegrityError

from app.models import CalendarEvent, Email, EmailAccount, EmailThread, GeneratedReply, Task, User


def make_account(db_session, email="user@example.com"):
    user = User(email=email)
    db_session.add(user)
    db_session.flush()
    account = EmailAccount(user_id=user.id, email_address=email, provider="imap")
    db_session.add(account)
    db_session.flush()
    return account


def test_user_to_email_account_relationship(db_session):
    account = make_account(db_session)
    db_session.commit()

    fetched_user = db_session.get(User, account.user_id)
    assert len(fetched_user.email_accounts) == 1
    assert fetched_user.email_accounts[0].email_address == "user@example.com"


def test_email_account_to_email_relationship(db_session):
    account = make_account(db_session)
    email = Email(
        email_account_id=account.id,
        provider_message_id="<abc@example.com>",
        subject="Hello",
        body="World",
        urgency="Low",
    )
    db_session.add(email)
    db_session.commit()

    assert len(account.emails) == 1
    assert email.email_account.email_address == "user@example.com"


def test_email_thread_relationship(db_session):
    account = make_account(db_session)
    thread = EmailThread(email_account_id=account.id, subject="Project X")
    db_session.add(thread)
    db_session.flush()

    email = Email(
        email_account_id=account.id,
        thread_id=thread.id,
        provider_message_id="<abc@example.com>",
        subject="Re: Project X",
        body="...",
    )
    db_session.add(email)
    db_session.commit()

    assert thread.emails[0].id == email.id
    assert email.thread.subject == "Project X"


def test_duplicate_provider_message_id_within_account_rejected(db_session):
    account = make_account(db_session)
    db_session.add(
        Email(email_account_id=account.id, provider_message_id="<dup@example.com>", subject="A", body="")
    )
    db_session.commit()

    db_session.add(
        Email(email_account_id=account.id, provider_message_id="<dup@example.com>", subject="B", body="")
    )
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_same_message_id_allowed_across_different_accounts(db_session):
    account_a = make_account(db_session, email="a@example.com")
    account_b = make_account(db_session, email="b@example.com")

    db_session.add(
        Email(email_account_id=account_a.id, provider_message_id="<shared@example.com>", subject="A", body="")
    )
    db_session.add(
        Email(email_account_id=account_b.id, provider_message_id="<shared@example.com>", subject="B", body="")
    )
    db_session.commit()  # should not raise

    assert db_session.query(Email).count() == 2


def test_task_and_calendar_event_relationship(db_session):
    account = make_account(db_session)
    email = Email(email_account_id=account.id, provider_message_id="<t1@example.com>", subject="", body="")
    db_session.add(email)
    db_session.flush()

    task = Task(email_id=email.id, title="Submit report", priority="High")
    db_session.add(task)
    db_session.flush()

    event = CalendarEvent(task_id=task.id, status="pending")
    db_session.add(event)
    db_session.commit()

    assert task.calendar_event.id == event.id
    assert task.email.id == email.id


def test_calendar_event_task_id_is_unique(db_session):
    account = make_account(db_session)
    email = Email(email_account_id=account.id, provider_message_id="<t2@example.com>", subject="", body="")
    db_session.add(email)
    db_session.flush()
    task = Task(email_id=email.id, title="Do a thing")
    db_session.add(task)
    db_session.flush()

    db_session.add(CalendarEvent(task_id=task.id))
    db_session.commit()

    db_session.add(CalendarEvent(task_id=task.id))
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_generated_reply_relationship(db_session):
    account = make_account(db_session)
    email = Email(email_account_id=account.id, provider_message_id="<r1@example.com>", subject="", body="")
    db_session.add(email)
    db_session.flush()

    reply = GeneratedReply(email_id=email.id, prompt="Tell them yes", generated_text="Sure, count me in.")
    db_session.add(reply)
    db_session.commit()

    assert email.generated_replies[0].generated_text == "Sure, count me in."


def test_deleting_email_cascades_to_tasks_and_replies(db_session):
    account = make_account(db_session)
    email = Email(email_account_id=account.id, provider_message_id="<c1@example.com>", subject="", body="")
    db_session.add(email)
    db_session.flush()
    db_session.add(Task(email_id=email.id, title="X"))
    db_session.add(GeneratedReply(email_id=email.id))
    db_session.commit()

    db_session.delete(email)
    db_session.commit()

    assert db_session.query(Task).count() == 0
    assert db_session.query(GeneratedReply).count() == 0


def test_email_defaults(db_session):
    account = make_account(db_session)
    email = Email(email_account_id=account.id, provider_message_id="<d1@example.com>", subject="", body="")
    db_session.add(email)
    db_session.commit()

    assert email.is_read is False
    assert email.processing_status == "ingested"
    assert email.category is None
    assert email.organization is None
    assert email.thread_id is None
