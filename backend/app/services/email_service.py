"""IMAP email ingestion and rule-based triage.

Ported and corrected from the two divergent prototype implementations
found in legacy/backend-fastapi-broken/email_utils.py and
legacy/mailease-flask/app/email_utils.py, consolidated into one
implementation with a fixed MIME-walking bug (see get_email_body) and
a single categorization keyword list (the two legacy versions disagreed).

Categorization and deadline extraction here are intentionally simple
keyword/regex heuristics, not AI. Replacing them with a real LLM-backed
pipeline is a later phase — this phase only needs a correct, testable
ingestion path.
"""

import email
import imaplib
import logging
import re
from email.header import decode_header
from email.message import Message

from bs4 import BeautifulSoup

from app.config import Settings
from app.schemas.email import EmailMessage, UrgencyLevel

logger = logging.getLogger(__name__)

_ABSOLUTE_DATE_PATTERN = re.compile(
    r"\b(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}[/-]\d{1,2}[/-]\d{1,2})\b"
)

_HIGH_PRIORITY_KEYWORDS = (
    "urgent",
    "asap",
    "immediate",
    "deadline",
    "final call",
    "submission",
    "action required",
    "critical",
    "emergency",
)
_MEDIUM_PRIORITY_KEYWORDS = (
    "reminder",
    "follow up",
    "today",
    "tomorrow",
    "meeting",
    "schedule",
    "update",
)


class EmailFetchError(RuntimeError):
    """Raised when IMAP login/fetch fails. Never includes credentials."""


def _clean_whitespace(text: str) -> str:
    return re.sub(r"[\r\t]+", " ", text).strip()


def _decode_subject(raw_subject: str | None) -> str:
    if not raw_subject:
        return "(no subject)"
    decoded_parts = decode_header(raw_subject)
    parts: list[str] = []
    for part, encoding in decoded_parts:
        if isinstance(part, bytes):
            parts.append(part.decode(encoding or "utf-8", errors="ignore"))
        else:
            parts.append(part)
    return _clean_whitespace("".join(parts))


def get_email_body(msg: Message) -> str:
    """Extract readable text from a possibly-multipart email message.

    Walks every MIME part (fixing the legacy bug where only the first
    part of a multipart message was inspected, which broke on
    multipart/mixed messages with an attachment listed first). Prefers
    text/plain; falls back to HTML with tags stripped.
    """
    plain_text: str | None = None
    html_text: str | None = None

    parts = msg.walk() if msg.is_multipart() else [msg]

    for part in parts:
        if part.get_content_maintype() == "multipart":
            continue
        if part.get_content_disposition() == "attachment":
            continue

        content_type = part.get_content_type()
        charset = part.get_content_charset() or "utf-8"

        try:
            payload = part.get_payload(decode=True)
        except Exception:
            continue
        if not payload:
            continue

        try:
            decoded = payload.decode(charset, errors="ignore")
        except (LookupError, UnicodeDecodeError):
            decoded = payload.decode("utf-8", errors="ignore")

        if content_type == "text/plain" and plain_text is None:
            plain_text = decoded.strip()
        elif content_type == "text/html" and html_text is None:
            html_text = BeautifulSoup(decoded, "html.parser").get_text(separator="\n").strip()

    body = plain_text or html_text or ""
    return _clean_whitespace(body) if body else "(no readable content)"


def categorize_email(subject: str, body: str) -> UrgencyLevel:
    text = f"{subject} {body}".lower()
    if any(keyword in text for keyword in _HIGH_PRIORITY_KEYWORDS):
        return UrgencyLevel.high
    if any(keyword in text for keyword in _MEDIUM_PRIORITY_KEYWORDS):
        return UrgencyLevel.medium
    return UrgencyLevel.low


def extract_deadlines(body: str) -> list[str]:
    """Find absolute date-like substrings.

    Deliberately limited to absolute numeric dates for now. Relative
    dates ("by Friday", "next week", "EOD") require timestamp-anchored
    parsing and are planned for a dedicated deadline-extraction phase
    rather than being bolted on here.
    """
    return _ABSOLUTE_DATE_PATTERN.findall(body)


def _parse_message(raw_email: bytes) -> EmailMessage:
    msg = email.message_from_bytes(raw_email)

    subject = _decode_subject(msg.get("Subject"))
    sender = msg.get("From")
    date = msg.get("Date")
    message_id = msg.get("Message-ID")
    body = get_email_body(msg)

    return EmailMessage(
        message_id=message_id,
        subject=subject,
        sender=sender,
        date=date,
        body=body,
        category=categorize_email(subject, body),
        deadlines=extract_deadlines(body),
    )


def fetch_emails(settings: Settings, mailbox: str = "INBOX") -> list[EmailMessage]:
    """Log into IMAP and return the most recent emails as EmailMessage objects.

    Raises EmailFetchError on any IMAP failure. Never logs the password;
    logs the configured address only at debug level.
    """
    if not settings.imap_is_configured():
        raise EmailFetchError("Email account is not configured (missing address/app password).")

    mail: imaplib.IMAP4_SSL | None = None
    try:
        mail = imaplib.IMAP4_SSL(settings.imap_server, settings.imap_port)
        mail.login(settings.email_address, settings.email_app_password)
        mail.select(mailbox)

        status, data = mail.search(None, "ALL")
        if status != "OK":
            raise EmailFetchError(f"IMAP search failed with status: {status}")

        message_ids = data[0].split()
        message_ids = message_ids[-settings.max_emails_per_fetch :]

        emails: list[EmailMessage] = []
        for message_id in message_ids:
            status, msg_data = mail.fetch(message_id, "(RFC822)")
            if status != "OK" or not msg_data or not msg_data[0]:
                continue
            raw_email = msg_data[0][1]
            emails.append(_parse_message(raw_email))

        return emails

    except imaplib.IMAP4.error as exc:
        logger.warning("IMAP error while fetching from %s", settings.imap_server)
        raise EmailFetchError("IMAP login or fetch failed. Check credentials and server settings.") from exc
    finally:
        if mail is not None:
            try:
                mail.logout()
            except Exception:
                pass
