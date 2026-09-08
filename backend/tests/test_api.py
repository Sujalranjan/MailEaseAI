from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import create_app
from app.schemas.email import EmailMessage, UrgencyLevel
from app.services.email_service import EmailFetchError


def make_client(settings: Settings) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
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


def test_list_emails_returns_503_when_unconfigured():
    client = make_client(Settings(email_address=None, email_app_password=None))
    response = client.get("/emails/")
    assert response.status_code == 503


def test_list_emails_returns_502_on_fetch_error(monkeypatch):
    client = make_client(Settings(email_address="a@b.com", email_app_password="x"))

    def raise_error(settings):
        raise EmailFetchError("IMAP login failed")

    monkeypatch.setattr("app.api.emails.fetch_emails", raise_error)
    response = client.get("/emails/")
    assert response.status_code == 502
    assert "IMAP login failed" in response.json()["detail"]


def test_list_emails_returns_parsed_emails(monkeypatch):
    client = make_client(Settings(email_address="a@b.com", email_app_password="x"))

    fake_email = EmailMessage(
        subject="Test",
        sender="a@b.com",
        date="Mon, 1 Sep 2026",
        body="Hello",
        category=UrgencyLevel.low,
        deadlines=[],
    )
    monkeypatch.setattr("app.api.emails.fetch_emails", lambda settings: [fake_email])

    response = client.get("/emails/")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["subject"] == "Test"
