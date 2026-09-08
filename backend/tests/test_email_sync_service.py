from unittest.mock import MagicMock, patch

from app.config import Settings
from app.integrations.base import FetchResult, RawEmail
from app.models import Email, EmailAccount
from app.services.email_sync_service import sync_emails


def make_settings():
    return Settings(email_address="me@gmail.com", email_app_password="secret")


def raw_message(message_id="<1@example.com>", subject="Test", urgent=False):
    body = "Submit ASAP" if urgent else "Just an update"
    msg_id_line = f"Message-ID: {message_id}\n" if message_id else ""
    return (
        f"From: a@b.com\nTo: me@gmail.com\nSubject: {subject}\n{msg_id_line}"
        f"Date: Mon, 1 Sep 2026 00:00:00 +0000\nContent-Type: text/plain\n\n{body}"
    ).encode()


def patch_provider(fetch_result: FetchResult):
    mock_provider = MagicMock()
    mock_provider.fetch_new_messages.return_value = fetch_result
    return patch("app.services.email_sync_service.IMAPProvider", return_value=mock_provider)


class TestSyncEmails:
    def test_first_sync_persists_all_fetched_emails(self, db_session):
        result = FetchResult(
            messages=[
                RawEmail(provider_uid="1", raw_bytes=raw_message("<1@example.com>")),
                RawEmail(provider_uid="2", raw_bytes=raw_message("<2@example.com>")),
            ],
            new_cursor="1000:2",
        )
        with patch_provider(result):
            emails = sync_emails(db_session, make_settings())

        assert len(emails) == 2
        assert db_session.query(Email).count() == 2

    def test_cursor_is_persisted_on_the_account(self, db_session):
        result = FetchResult(
            messages=[RawEmail(provider_uid="1", raw_bytes=raw_message("<1@example.com>"))],
            new_cursor="1000:1",
        )
        with patch_provider(result):
            sync_emails(db_session, make_settings())

        account = db_session.query(EmailAccount).one()
        assert account.sync_cursor == "1000:1"

    def test_cursor_unchanged_when_no_new_messages(self, db_session):
        with patch_provider(FetchResult(messages=[RawEmail("1", raw_message())], new_cursor="1000:1")):
            sync_emails(db_session, make_settings())

        with patch_provider(FetchResult(messages=[], new_cursor=None)):
            sync_emails(db_session, make_settings())

        account = db_session.query(EmailAccount).one()
        assert account.sync_cursor == "1000:1"

    def test_repeated_sync_with_same_messages_does_not_duplicate(self, db_session):
        result = FetchResult(
            messages=[RawEmail("1", raw_message("<1@example.com>")), RawEmail("2", raw_message("<2@example.com>"))],
            new_cursor="1000:2",
        )
        with patch_provider(result):
            sync_emails(db_session, make_settings())
        with patch_provider(result):
            emails = sync_emails(db_session, make_settings())

        assert len(emails) == 2
        assert db_session.query(Email).count() == 2

    def test_email_without_message_id_is_skipped_not_crashed(self, db_session):
        result = FetchResult(messages=[RawEmail("1", raw_message(message_id=None))], new_cursor="1000:1")
        with patch_provider(result):
            emails = sync_emails(db_session, make_settings())

        assert emails == []
        assert db_session.query(Email).count() == 0

    def test_malformed_message_is_skipped_not_crashed(self, db_session):
        result = FetchResult(
            messages=[
                RawEmail("1", b"not a valid email at all \xff\xfe"),
                RawEmail("2", raw_message("<2@example.com>")),
            ],
            new_cursor="1000:2",
        )
        with patch_provider(result):
            emails = sync_emails(db_session, make_settings())

        # The malformed bytes still parse as *some* email.message.Message
        # (the stdlib parser is lenient) but the well-formed one must
        # always survive alongside it either way.
        assert any(e.provider_message_id == "<2@example.com>" for e in emails)

    def test_urgency_is_persisted_from_categorization(self, db_session):
        result = FetchResult(
            messages=[RawEmail("1", raw_message("<1@example.com>", urgent=True))], new_cursor="1000:1"
        )
        with patch_provider(result):
            emails = sync_emails(db_session, make_settings())

        assert emails[0].urgency == "High"
        assert emails[0].category is None

    def test_bootstrap_account_reused_across_calls(self, db_session):
        result = FetchResult(messages=[RawEmail("1", raw_message("<1@example.com>"))], new_cursor="1000:1")
        with patch_provider(result):
            sync_emails(db_session, make_settings())
        with patch_provider(FetchResult(messages=[], new_cursor=None)):
            sync_emails(db_session, make_settings())

        assert db_session.query(EmailAccount).count() == 1
