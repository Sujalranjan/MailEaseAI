from unittest.mock import patch

from app.config import Settings
from app.models import Email
from app.schemas.email import EmailMessage, UrgencyLevel
from app.services.email_sync_service import sync_emails


def make_settings():
    return Settings(email_address="me@gmail.com", email_app_password="secret")


def fake_message(message_id="<1@example.com>", subject="Test", category=UrgencyLevel.low):
    return EmailMessage(
        message_id=message_id,
        subject=subject,
        sender="a@b.com",
        recipients="me@gmail.com",
        date="Mon, 1 Sep 2026 00:00:00 +0000",
        body="Body text",
        category=category,
        deadlines=[],
    )


class TestSyncEmails:
    @patch("app.services.email_sync_service.fetch_emails")
    def test_first_sync_persists_all_fetched_emails(self, mock_fetch, db_session):
        mock_fetch.return_value = [fake_message("<1@example.com>"), fake_message("<2@example.com>")]

        result = sync_emails(db_session, make_settings())

        assert len(result) == 2
        assert db_session.query(Email).count() == 2

    @patch("app.services.email_sync_service.fetch_emails")
    def test_repeated_sync_does_not_duplicate(self, mock_fetch, db_session):
        mock_fetch.return_value = [fake_message("<1@example.com>"), fake_message("<2@example.com>")]

        sync_emails(db_session, make_settings())
        result = sync_emails(db_session, make_settings())

        assert len(result) == 2
        assert db_session.query(Email).count() == 2

    @patch("app.services.email_sync_service.fetch_emails")
    def test_sync_persists_newly_arrived_email_on_second_call(self, mock_fetch, db_session):
        mock_fetch.return_value = [fake_message("<1@example.com>")]
        sync_emails(db_session, make_settings())

        mock_fetch.return_value = [fake_message("<1@example.com>"), fake_message("<2@example.com>")]
        result = sync_emails(db_session, make_settings())

        assert len(result) == 2
        assert db_session.query(Email).count() == 2

    @patch("app.services.email_sync_service.fetch_emails")
    def test_email_without_message_id_is_skipped_not_crashed(self, mock_fetch, db_session):
        mock_fetch.return_value = [fake_message(message_id=None)]

        result = sync_emails(db_session, make_settings())

        assert result == []
        assert db_session.query(Email).count() == 0

    @patch("app.services.email_sync_service.fetch_emails")
    def test_urgency_is_persisted_from_categorization(self, mock_fetch, db_session):
        mock_fetch.return_value = [fake_message("<1@example.com>", category=UrgencyLevel.high)]

        result = sync_emails(db_session, make_settings())

        assert result[0].urgency == "High"
        assert result[0].category is None  # not populated until real classification exists

    @patch("app.services.email_sync_service.fetch_emails")
    def test_bootstrap_account_reused_across_calls(self, mock_fetch, db_session):
        from app.models import EmailAccount

        mock_fetch.return_value = [fake_message("<1@example.com>")]
        sync_emails(db_session, make_settings())
        sync_emails(db_session, make_settings())

        assert db_session.query(EmailAccount).count() == 1
