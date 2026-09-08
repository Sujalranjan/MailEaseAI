from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.db.session import get_db
from app.main import create_app
from app.schemas.email import EmailMessage, UrgencyLevel


def make_client(settings: Settings, db_session=None) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    if db_session is not None:
        app.dependency_overrides[get_db] = lambda: (yield db_session)
    return TestClient(app)


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


def test_list_emails_returns_502_on_fetch_error(monkeypatch, db_session):
    client = make_client(Settings(email_address="a@b.com", email_app_password="x"), db_session)

    def raise_error(settings):
        from app.services.email_service import EmailFetchError

        raise EmailFetchError("IMAP login failed")

    monkeypatch.setattr("app.services.email_sync_service.fetch_emails", raise_error)
    response = client.get("/emails/")
    assert response.status_code == 502
    assert "IMAP login failed" in response.json()["detail"]


def test_list_emails_persists_and_returns_stored_emails(monkeypatch, db_session):
    client = make_client(Settings(email_address="a@b.com", email_app_password="x"), db_session)

    fake_email = EmailMessage(
        message_id="<api-test-1@example.com>",
        subject="Test",
        sender="a@b.com",
        recipients="a@b.com",
        date="Mon, 1 Sep 2026 00:00:00 +0000",
        body="Hello",
        category=UrgencyLevel.low,
        deadlines=[],
    )
    monkeypatch.setattr("app.services.email_sync_service.fetch_emails", lambda settings: [fake_email])

    response = client.get("/emails/")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["subject"] == "Test"
    assert body[0]["urgency"] == "Low"
    assert "id" in body[0]  # confirms this is the persisted DB row, not the raw IMAP shape


def test_list_emails_does_not_duplicate_across_requests(monkeypatch, db_session):
    client = make_client(Settings(email_address="a@b.com", email_app_password="x"), db_session)

    fake_email = EmailMessage(
        message_id="<api-test-2@example.com>",
        subject="Test",
        sender="a@b.com",
        recipients="a@b.com",
        date="Mon, 1 Sep 2026 00:00:00 +0000",
        body="Hello",
        category=UrgencyLevel.low,
        deadlines=[],
    )
    monkeypatch.setattr("app.services.email_sync_service.fetch_emails", lambda settings: [fake_email])

    first = client.get("/emails/")
    second = client.get("/emails/")

    assert len(first.json()) == 1
    assert len(second.json()) == 1
    assert first.json()[0]["id"] == second.json()[0]["id"]
