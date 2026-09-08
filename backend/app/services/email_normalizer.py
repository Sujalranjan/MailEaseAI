"""Turns raw RFC822 bytes (from any EmailProvider) into a normalized,
provider-agnostic EmailMessage.

Kept separate from app/integrations/*  (which only knows how to talk to
a specific provider) and from persistence (app/repositories/*) — this
module's only job is: raw bytes in, structured+normalized data out.

Categorization and deadline extraction here are intentionally simple
keyword/regex heuristics, not AI. Replacing them with a real LLM-backed
pipeline is a later phase — this phase only needs a correct, testable
normalization path.
"""

import logging
import re
from datetime import timezone
from email import message_from_bytes
from email.header import decode_header
from email.message import Message
from email.utils import getaddresses, parseaddr, parsedate_to_datetime

from bs4 import BeautifulSoup

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

    Walks every MIME part, including nested ones (Message.walk() is a
    full preorder traversal, so multipart/alternative nested inside
    multipart/mixed is handled without special-casing). Prefers
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


def _parse_received_at(raw_date: str | None):
    """Parse the Date header to a UTC-normalized datetime.

    SQLite (unlike Postgres) drops timezone info on any datetime it
    stores — confirmed by a round-trip check — so two emails sent at the
    same instant from different sender timezones would otherwise be
    stored as different, incomparable naive values. Converting to UTC
    here, at the normalization boundary, means every downstream
    consumer can treat `received_at` as naive-UTC and get correct
    ordering regardless of sender timezone.
    """
    if not raw_date:
        return None
    try:
        parsed = parsedate_to_datetime(raw_date)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        # Some malformed/legacy Date headers omit a timezone; treat as
        # UTC rather than silently dropping the timestamp.
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _normalize_sender(raw_from: str | None) -> tuple[str | None, str | None]:
    if not raw_from:
        return None, None
    name, addr = parseaddr(raw_from)
    return (name or None), (addr or None)


def _normalize_recipients(msg: Message) -> list[str]:
    header_values = msg.get_all("To", []) + msg.get_all("Cc", [])
    addresses = getaddresses(header_values)
    return [addr for _, addr in addresses if addr]


def normalize_message(raw_bytes: bytes) -> EmailMessage:
    """Parse raw RFC822 bytes into a normalized EmailMessage.

    Raises on genuinely unparseable input; callers (email_sync_service)
    are responsible for catching that per-message so one malformed email
    doesn't abort an entire sync batch.
    """
    msg = message_from_bytes(raw_bytes)

    subject = _decode_subject(msg.get("Subject"))
    sender_name, sender_email = _normalize_sender(msg.get("From"))
    body = get_email_body(msg)

    return EmailMessage(
        message_id=msg.get("Message-ID"),
        subject=subject,
        sender_name=sender_name,
        sender_email=sender_email,
        recipients=_normalize_recipients(msg),
        in_reply_to=msg.get("In-Reply-To"),
        references_header=msg.get("References"),
        received_at=_parse_received_at(msg.get("Date")),
        body=body,
        category=categorize_email(subject, body),
        deadlines=extract_deadlines(body),
    )
