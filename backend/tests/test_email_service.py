import email
from unittest.mock import MagicMock, patch

import pytest

from app.config import Settings
from app.services.email_service import (
    EmailFetchError,
    categorize_email,
    extract_deadlines,
    fetch_emails,
    get_email_body,
)


class TestCategorizeEmail:
    def test_high_priority_keyword_in_subject(self):
        assert categorize_email("URGENT: server down", "please look now") == "High"

    def test_medium_priority_keyword(self):
        assert categorize_email("Reminder", "don't forget the call tomorrow") == "Medium"

    def test_low_priority_default(self):
        assert categorize_email("Newsletter", "here's what's new this month") == "Low"

    def test_case_insensitive(self):
        assert categorize_email("Deadline Approaching", "") == "High"


class TestExtractDeadlines:
    def test_finds_slash_date(self):
        assert extract_deadlines("Please submit by 15/09/2026.") == ["15/09/2026"]

    def test_finds_iso_date(self):
        assert extract_deadlines("Due 2026-09-15 at noon.") == ["2026-09-15"]

    def test_no_date_returns_empty(self):
        assert extract_deadlines("Please submit by Friday.") == []

    def test_multiple_dates(self):
        result = extract_deadlines("First draft 01/09/2026, final 15/09/2026.")
        assert result == ["01/09/2026", "15/09/2026"]


class TestGetEmailBody:
    def test_plain_text_message(self):
        msg = email.message_from_string(
            "Content-Type: text/plain\n\nHello world"
        )
        assert get_email_body(msg) == "Hello world"

    def test_multipart_mixed_with_attachment_first(self):
        raw = (
            "Content-Type: multipart/mixed; boundary=BOUND\n\n"
            "--BOUND\n"
            "Content-Type: application/pdf\n"
            "Content-Disposition: attachment; filename=report.pdf\n\n"
            "%PDF-fake-binary\n"
            "--BOUND\n"
            "Content-Type: text/plain\n\n"
            "The actual message body\n"
            "--BOUND--"
        )
        msg = email.message_from_string(raw)
        assert get_email_body(msg) == "The actual message body"

    def test_falls_back_to_html_when_no_plain_text(self):
        raw = (
            "Content-Type: multipart/alternative; boundary=BOUND\n\n"
            "--BOUND\n"
            "Content-Type: text/html\n\n"
            "<p>Hello <b>HTML</b> world</p>\n"
            "--BOUND--"
        )
        msg = email.message_from_string(raw)
        assert "Hello" in get_email_body(msg)
        assert "HTML" in get_email_body(msg)

    def test_empty_message_has_placeholder(self):
        msg = email.message_from_string("Content-Type: text/plain\n\n")
        assert get_email_body(msg) == "(no readable content)"


class TestFetchEmails:
    def test_raises_when_not_configured(self):
        settings = Settings(email_address=None, email_app_password=None)
        with pytest.raises(EmailFetchError):
            fetch_emails(settings)

    @patch("app.services.email_service.imaplib.IMAP4_SSL")
    def test_fetches_and_parses_one_email(self, mock_imap_cls):
        mock_conn = MagicMock()
        mock_imap_cls.return_value = mock_conn
        mock_conn.search.return_value = ("OK", [b"1"])
        raw_email = b"Subject: Test\nFrom: a@b.com\nDate: Mon, 1 Sep 2026 00:00:00 +0000\nContent-Type: text/plain\n\nUrgent: please respond ASAP"
        mock_conn.fetch.return_value = ("OK", [(b"1 (RFC822 {123}", raw_email)])

        settings = Settings(email_address="me@gmail.com", email_app_password="secret")
        results = fetch_emails(settings)

        assert len(results) == 1
        assert results[0].subject == "Test"
        assert results[0].category == "High"
        mock_conn.login.assert_called_once_with("me@gmail.com", "secret")
        mock_conn.logout.assert_called_once()

    @patch("app.services.email_service.imaplib.IMAP4_SSL")
    def test_login_failure_raises_email_fetch_error_without_leaking_password(self, mock_imap_cls):
        import imaplib as real_imaplib

        mock_conn = MagicMock()
        mock_imap_cls.return_value = mock_conn
        mock_conn.login.side_effect = real_imaplib.IMAP4.error("Invalid credentials")

        settings = Settings(email_address="me@gmail.com", email_app_password="wrong")
        with pytest.raises(EmailFetchError) as exc_info:
            fetch_emails(settings)

        assert "wrong" not in str(exc_info.value)
