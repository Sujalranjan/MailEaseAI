import imaplib
from unittest.mock import MagicMock, patch

import pytest

from app.config import Settings
from app.integrations.base import EmailFetchError
from app.integrations.imap_provider import IMAPProvider


def make_settings():
    return Settings(email_address="me@gmail.com", email_app_password="secret")


def make_mock_conn(uidvalidity: str, search_uids: list[int], fetch_ok_uids: set[int] | None = None):
    """A mock IMAP4_SSL connection: reports the given UIDVALIDITY, returns
    search_uids from UID SEARCH, and succeeds fetching only fetch_ok_uids
    (default: all of them) — lets tests simulate a fetch failing partway.
    """
    if fetch_ok_uids is None:
        fetch_ok_uids = set(search_uids)

    conn = MagicMock()
    conn.response.return_value = ("UIDVALIDITY", [uidvalidity.encode()])

    def uid_side_effect(command, *args):
        if command == "search":
            data = " ".join(str(u) for u in search_uids).encode()
            return "OK", [data]
        if command == "fetch":
            requested_uid = int(args[0])
            if requested_uid not in fetch_ok_uids:
                return "NO", [None]
            raw = f"Subject: msg {requested_uid}\n\nBody".encode()
            return "OK", [(f"{requested_uid} (RFC822 {{n}}".encode(), raw)]
        raise AssertionError(f"unexpected uid command: {command}")

    conn.uid.side_effect = uid_side_effect
    return conn


class TestFetchNewMessages:
    @patch("app.integrations.imap_provider.imaplib.IMAP4_SSL")
    def test_first_sync_with_no_cursor_searches_from_uid_1(self, mock_cls):
        conn = make_mock_conn(uidvalidity="1000", search_uids=[1, 2])
        mock_cls.return_value = conn

        result = IMAPProvider(make_settings()).fetch_new_messages(cursor=None, batch_size=50)

        search_call = [c for c in conn.uid.call_args_list if c.args[0] == "search"][0]
        assert search_call.args[2] == "1:*"
        assert len(result.messages) == 2
        assert result.new_cursor == "1000:2"

    @patch("app.integrations.imap_provider.imaplib.IMAP4_SSL")
    def test_incremental_sync_searches_from_last_uid_plus_one(self, mock_cls):
        conn = make_mock_conn(uidvalidity="1000", search_uids=[3])
        mock_cls.return_value = conn

        result = IMAPProvider(make_settings()).fetch_new_messages(cursor="1000:2", batch_size=50)

        search_call = [c for c in conn.uid.call_args_list if c.args[0] == "search"][0]
        assert search_call.args[2] == "3:*"
        assert len(result.messages) == 1
        assert result.new_cursor == "1000:3"

    @patch("app.integrations.imap_provider.imaplib.IMAP4_SSL")
    def test_uidvalidity_change_forces_resync_from_scratch(self, mock_cls):
        conn = make_mock_conn(uidvalidity="2000", search_uids=[1, 2, 3])
        mock_cls.return_value = conn

        result = IMAPProvider(make_settings()).fetch_new_messages(cursor="1000:50", batch_size=50)

        search_call = [c for c in conn.uid.call_args_list if c.args[0] == "search"][0]
        assert search_call.args[2] == "1:*"
        assert result.new_cursor == "2000:3"

    @patch("app.integrations.imap_provider.imaplib.IMAP4_SSL")
    def test_batch_size_caps_and_advances_cursor_to_capped_max(self, mock_cls):
        conn = make_mock_conn(uidvalidity="1000", search_uids=[1, 2, 3, 4, 5])
        mock_cls.return_value = conn

        result = IMAPProvider(make_settings()).fetch_new_messages(cursor=None, batch_size=2)

        assert len(result.messages) == 2
        assert result.new_cursor == "1000:2"

    @patch("app.integrations.imap_provider.imaplib.IMAP4_SSL")
    def test_no_new_messages_returns_none_cursor(self, mock_cls):
        conn = make_mock_conn(uidvalidity="1000", search_uids=[])
        mock_cls.return_value = conn

        result = IMAPProvider(make_settings()).fetch_new_messages(cursor="1000:5", batch_size=50)

        assert result.messages == []
        assert result.new_cursor is None

    @patch("app.integrations.imap_provider.imaplib.IMAP4_SSL")
    def test_malformed_cursor_treated_as_first_sync(self, mock_cls):
        conn = make_mock_conn(uidvalidity="1000", search_uids=[1])
        mock_cls.return_value = conn

        IMAPProvider(make_settings()).fetch_new_messages(cursor="not-a-valid-cursor", batch_size=50)

        search_call = [c for c in conn.uid.call_args_list if c.args[0] == "search"][0]
        assert search_call.args[2] == "1:*"

    @patch("app.integrations.imap_provider.imaplib.IMAP4_SSL")
    def test_partial_fetch_failure_raises_all_or_nothing(self, mock_cls):
        conn = make_mock_conn(uidvalidity="1000", search_uids=[1, 2], fetch_ok_uids={1})
        mock_cls.return_value = conn

        with pytest.raises(EmailFetchError):
            IMAPProvider(make_settings()).fetch_new_messages(cursor=None, batch_size=50)

    @patch("app.integrations.imap_provider.imaplib.IMAP4_SSL")
    def test_search_failure_raises_fetch_error(self, mock_cls):
        conn = MagicMock()
        conn.response.return_value = ("UIDVALIDITY", [b"1000"])
        conn.uid.return_value = ("NO", [None])
        mock_cls.return_value = conn

        with pytest.raises(EmailFetchError):
            IMAPProvider(make_settings()).fetch_new_messages(cursor=None, batch_size=50)

    @patch("app.integrations.imap_provider.imaplib.IMAP4_SSL")
    def test_missing_uidvalidity_raises_fetch_error(self, mock_cls):
        conn = MagicMock()
        conn.response.return_value = ("UIDVALIDITY", [None])
        mock_cls.return_value = conn

        with pytest.raises(EmailFetchError):
            IMAPProvider(make_settings()).fetch_new_messages(cursor=None, batch_size=50)

    @patch("app.integrations.imap_provider.imaplib.IMAP4_SSL")
    def test_imap_login_error_raises_fetch_error_without_leaking_password(self, mock_cls):
        conn = MagicMock()
        conn.login.side_effect = imaplib.IMAP4.error("bad credentials")
        mock_cls.return_value = conn

        with pytest.raises(EmailFetchError) as exc_info:
            IMAPProvider(make_settings()).fetch_new_messages(cursor=None, batch_size=50)
        assert "secret" not in str(exc_info.value)

    @patch("app.integrations.imap_provider.imaplib.IMAP4_SSL")
    def test_network_error_raises_fetch_error(self, mock_cls):
        mock_cls.side_effect = OSError("DNS resolution failed")

        with pytest.raises(EmailFetchError):
            IMAPProvider(make_settings()).fetch_new_messages(cursor=None, batch_size=50)

    @patch("app.integrations.imap_provider.imaplib.IMAP4_SSL")
    def test_logout_called_even_when_search_fails(self, mock_cls):
        conn = MagicMock()
        conn.response.return_value = ("UIDVALIDITY", [b"1000"])
        conn.uid.return_value = ("NO", [None])
        mock_cls.return_value = conn

        with pytest.raises(EmailFetchError):
            IMAPProvider(make_settings()).fetch_new_messages(cursor=None, batch_size=50)
        conn.logout.assert_called_once()

    def test_constructor_raises_when_not_configured(self):
        with pytest.raises(EmailFetchError):
            IMAPProvider(Settings(email_address=None, email_app_password=None))
