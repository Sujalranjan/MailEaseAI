import imaplib
import email
from email.header import decode_header
from typing import List, Dict

def clean(text: str) -> str:
    """Clean text by removing unwanted characters."""
    import re
    return re.sub(r'[\n\r\t]', ' ', str(text))

def get_text(msg: email.message.Message) -> str:
    """Get the text content of an email message, handling different content types."""
    if msg.is_multipart():
        for part in msg.get_payload():
            return get_text(part)
    else:
        return msg.get_payload(decode=True).decode()

def fetch_emails(mail_server: str, email_user: str, email_pass: str, mailbox: str = "INBOX") -> List[Dict]:
    """
    Fetches emails from the specified mailbox.

    Args:
        mail_server: The IMAP server address (e.g., 'imap.gmail.com').
        email_user: The email address to log in with.
        email_pass: The email password.
        mailbox: The mailbox to fetch emails from (default: 'INBOX').

    Returns:
        A list of dictionaries, where each dictionary represents an email.
    """

    try:
        mail = imaplib.IMAP4_SSL(mail_server)
        mail.login(email_user, email_pass)
        mail.select(mailbox)

        _, data = mail.search(None, "ALL")
        mail_ids = data[0]

        emails = []
        for mail_id in mail_ids.split():
            _, data = mail.fetch(mail_id, '(RFC822)')
            raw_email = data[0][1]

            try:
                msg = email.message_from_bytes(raw_email)
            except TypeError:
                msg = email.message_from_string(raw_email)

            subject = decode_header(msg['Subject'])[0][0]
            if isinstance(subject, bytes):
                subject = subject.decode()
            from_ = msg.get("From")
            date_ = msg.get("Date")
            body = get_text(msg)

            emails.append({
                "subject": clean(subject),
                "from": from_,
                "date": date_,
                "body": clean(body)
            })

        mail.close()
        mail.logout()
        return emails

    except Exception as e:
        print(f"Error fetching emails: {e}")
        return []  # Return an empty list in case of an error