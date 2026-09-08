import imaplib
import email
from email.header import decode_header
from bs4 import BeautifulSoup
import re

# Email credentials
EMAIL = "sujalranjan02@gmail.com"
APP_PASSWORD = "ouwdeblwgmkqstus"

# IMAP settings
IMAP_SERVER = "imap.gmail.com"
IMAP_PORT = 993

# Regex pattern for dates (deadlines)
date_pattern = r"\b(?:\d{1,2}[/-]\d{1,2}[/-]\d{4}|\d{4}[/-]\d{1,2}[/-]\d{1,2})\b"


def fetch_emails():
    mail = imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT)
    emails_data = []

    try:
        mail.login(EMAIL, APP_PASSWORD)
        mail.select("inbox")
        status, messages = mail.search(None, "ALL")
        email_ids = messages[0].split()

        for email_id in email_ids[-100:]:  # Latest 100 emails
            status, msg_data = mail.fetch(email_id, "(RFC822)")

            for response_part in msg_data:
                if isinstance(response_part, tuple):
                    msg = email.message_from_bytes(response_part[1])

                    # Decode subject
                    subject, encoding = decode_header(msg["Subject"])[0]
                    if isinstance(subject, bytes):
                        subject = subject.decode(encoding or "utf-8", errors="ignore")

                    from_ = msg.get("From")
                    date = msg.get("Date")
                    body = get_email_body(msg)

                    category = categorize_email(subject, body)
                    deadlines = extract_deadlines(body)

                    print("Fetched email - Subject:", subject)
                    print("Category:", category)
                    print("Body:", body[:100])  # Preview only

                    emails_data.append({
                        "subject": subject,
                        "from": from_,
                        "body": body,
                        "category": category,
                        "deadlines": deadlines,
                        "timestamp": date
                    })

    except Exception as e:
        print(f"Error: {e}")
    finally:
        print(f"Fetched {len(emails_data)} emails.")
        mail.logout()

    return emails_data


def get_email_body(msg):
    body_text = None
    html_text = None

    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            charset = part.get_content_charset() or "utf-8"

            try:
                content = part.get_payload(decode=True)
                if content:
                    decoded = content.decode(charset, errors="ignore")

                    if content_type == "text/plain" and not body_text:
                        body_text = decoded.strip()
                    elif content_type == "text/html" and not html_text:
                        soup = BeautifulSoup(decoded, "html.parser")
                        html_text = soup.get_text(separator="\n").strip()
            except:
                continue
    else:
        content_type = msg.get_content_type()
        charset = msg.get_content_charset() or "utf-8"

        try:
            payload = msg.get_payload(decode=True)
            if payload:
                decoded = payload.decode(charset, errors="ignore")
                if content_type == "text/plain":
                    body_text = decoded.strip()
                elif content_type == "text/html":
                    soup = BeautifulSoup(decoded, "html.parser")
                    html_text = soup.get_text(separator="\n").strip()
        except:
            pass

    return body_text or html_text or "No readable content found."


def categorize_email(subject, body):
    text = (subject + " " + body).lower()
    if any(keyword in text for keyword in ['urgent', 'asap', 'immediate', 'deadline']):
        return "High"
    elif any(keyword in text for keyword in ['reminder', 'follow up', 'today', 'tomorrow']):
        return "Medium"
    return "Low"


def extract_deadlines(body):
    return re.findall(date_pattern, body)
