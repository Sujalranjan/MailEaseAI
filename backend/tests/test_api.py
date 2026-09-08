from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.db.session import get_db
from app.integrations.base import FetchResult, RawEmail
from app.main import create_app


def make_client(settings: Settings, db_session=None) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    if db_session is not None:
        app.dependency_overrides[get_db] = lambda: (yield db_session)
    return TestClient(app)


def raw_message(message_id="<api-test@example.com>", subject="Test", in_reply_to=None, body="Hello"):
    reply_line = f"In-Reply-To: {in_reply_to}\n" if in_reply_to else ""
    return (
        f"From: a@b.com\nTo: a@b.com\nSubject: {subject}\nMessage-ID: {message_id}\n{reply_line}"
        f"Date: Mon, 1 Sep 2026 00:00:00 +0000\nContent-Type: text/plain\n\n{body}"
    ).encode()


def patch_provider(fetch_result: FetchResult):
    mock_provider = MagicMock()
    mock_provider.fetch_new_messages.return_value = fetch_result
    return patch("app.services.email_sync_service.IMAPProvider", return_value=mock_provider)


def test_root():
    client = make_client(Settings())
    response = client.get("/")
    assert response.status_code == 200
    assert "Mail-Ease" in response.json()["message"]


def test_health_reports_unconfigured_email():
    client = make_client(Settings(email_address=None, email_app_password=None))
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "email_configured": False}


def test_health_reports_configured_email():
    client = make_client(Settings(email_address="a@b.com", email_app_password="x"))
    assert client.get("/health").json()["email_configured"] is True


def test_list_emails_returns_503_when_unconfigured(db_session):
    client = make_client(Settings(email_address=None, email_app_password=None), db_session)
    response = client.get("/emails/")
    assert response.status_code == 503


def test_list_emails_returns_502_on_fetch_error(db_session):
    from app.integrations.base import EmailFetchError

    client = make_client(Settings(email_address="a@b.com", email_app_password="x"), db_session)
    mock_provider = MagicMock()
    mock_provider.fetch_new_messages.side_effect = EmailFetchError("IMAP login failed")

    with patch("app.services.email_sync_service.IMAPProvider", return_value=mock_provider):
        response = client.get("/emails/")

    assert response.status_code == 502
    assert "IMAP login failed" in response.json()["detail"]


def test_list_emails_persists_and_returns_stored_emails(db_session):
    client = make_client(Settings(email_address="a@b.com", email_app_password="x"), db_session)
    result = FetchResult(messages=[RawEmail("1", raw_message("<api-test-1@example.com>"))], new_cursor="1000:1")

    with patch_provider(result):
        response = client.get("/emails/")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["subject"] == "Test"
    assert body[0]["urgency"] == "Low"
    assert body[0]["sender_email"] == "a@b.com"
    assert "id" in body[0]  # confirms this is the persisted DB row, not the raw IMAP shape
    assert body[0]["thread_id"] is not None


def test_list_emails_does_not_duplicate_across_requests(db_session):
    client = make_client(Settings(email_address="a@b.com", email_app_password="x"), db_session)
    result = FetchResult(messages=[RawEmail("1", raw_message("<api-test-2@example.com>"))], new_cursor="1000:1")
    empty_result = FetchResult(messages=[], new_cursor=None)

    with patch_provider(result):
        first = client.get("/emails/")
    with patch_provider(empty_result):
        second = client.get("/emails/")

    assert len(first.json()) == 1
    assert len(second.json()) == 1
    assert first.json()[0]["id"] == second.json()[0]["id"]


def test_get_thread_returns_404_when_not_found(db_session):
    client = make_client(Settings(), db_session)
    response = client.get("/threads/999")
    assert response.status_code == 404


def test_get_thread_returns_thread_with_its_emails(db_session):
    client = make_client(Settings(email_address="a@b.com", email_app_password="x"), db_session)
    result = FetchResult(
        messages=[
            RawEmail("1", raw_message("<thread-root@example.com>")),
            RawEmail("2", raw_message("<thread-reply@example.com>", in_reply_to="<thread-root@example.com>")),
        ],
        new_cursor="1000:2",
    )
    with patch_provider(result):
        emails_response = client.get("/emails/")

    thread_id = emails_response.json()[0]["thread_id"]
    response = client.get(f"/threads/{thread_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == thread_id
    assert len(body["emails"]) == 2
    assert {e["provider_message_id"] for e in body["emails"]} == {
        "<thread-root@example.com>",
        "<thread-reply@example.com>",
    }


def test_list_tasks_returns_empty_before_any_sync(db_session):
    client = make_client(Settings(email_address="a@b.com", email_app_password="x"), db_session)
    response = client.get("/tasks/")
    assert response.status_code == 200
    assert response.json() == []


def test_list_tasks_returns_503_when_unconfigured(db_session):
    client = make_client(Settings(email_address=None, email_app_password=None), db_session)
    response = client.get("/tasks/")
    assert response.status_code == 503


def test_sync_then_list_tasks_returns_extracted_task(db_session):
    client = make_client(Settings(email_address="a@b.com", email_app_password="x"), db_session)
    result = FetchResult(
        messages=[
            RawEmail(
                "1", raw_message("<task-api@example.com>", body="Please submit the report by 2026-09-20.")
            )
        ],
        new_cursor="1000:1",
    )
    with patch_provider(result):
        emails_response = client.get("/emails/")

    tasks_response = client.get("/tasks/")
    assert tasks_response.status_code == 200
    tasks_body = tasks_response.json()
    assert len(tasks_body) == 1
    assert tasks_body[0]["email_id"] == emails_response.json()[0]["id"]
    assert tasks_body[0]["deadline_confidence"] == "confirmed"

    # Also exposed nested under the email itself.
    assert len(emails_response.json()[0]["tasks"]) == 1


def test_get_task_returns_404_when_not_found(db_session):
    client = make_client(Settings(), db_session)
    response = client.get("/tasks/999")
    assert response.status_code == 404


def test_get_task_returns_task_detail(db_session):
    client = make_client(Settings(email_address="a@b.com", email_app_password="x"), db_session)
    result = FetchResult(
        messages=[RawEmail("1", raw_message("<task-detail@example.com>", body="Please submit the report."))],
        new_cursor="1000:1",
    )
    with patch_provider(result):
        client.get("/emails/")

    task_id = client.get("/tasks/").json()[0]["id"]
    response = client.get(f"/tasks/{task_id}")
    assert response.status_code == 200
    assert response.json()["id"] == task_id


def test_repeated_email_sync_does_not_duplicate_tasks_via_api(db_session):
    client = make_client(Settings(email_address="a@b.com", email_app_password="x"), db_session)
    result = FetchResult(
        messages=[RawEmail("1", raw_message("<task-nodupe@example.com>", body="Please submit the report."))],
        new_cursor="1000:1",
    )
    with patch_provider(result):
        client.get("/emails/")
    with patch_provider(FetchResult(messages=[], new_cursor=None)):
        client.get("/emails/")

    assert len(client.get("/tasks/").json()) == 1
