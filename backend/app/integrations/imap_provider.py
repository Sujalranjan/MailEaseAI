"""IMAP implementation of EmailProvider, using UID-based incremental sync.

Cursor format: "<uidvalidity>:<last_uid>", entirely internal to this
module — nothing outside app/integrations ever parses it.

IMAP UIDs are unique within a mailbox only as long as UIDVALIDITY stays
the same; a server is allowed to renumber them (rare, but real — e.g.
after certain mailbox migrations), in which case old UIDs are meaningless.
This provider detects a UIDVALIDITY change and treats it as a first sync
rather than trusting a stale last_uid. The DB's (email_account_id,
provider_message_id) unique constraint is a second, independent safety
net: even if UID bookkeeping here were ever wrong, it cannot cause
duplicate rows, only (at worst) a redundant re-fetch.

Fetching is all-or-nothing per call: if the connection drops partway
through a batch, this raises rather than returning a partial result, and
the cursor is not advanced — the next sync call retries the same range.
"""

import imaplib
import logging

from app.config import Settings
from app.integrations.base import EmailFetchError, EmailProvider, FetchResult, RawEmail

logger = logging.getLogger(__name__)


def _parse_cursor(cursor: str | None) -> tuple[str | None, int | None]:
    if not cursor:
        return None, None
    try:
        uidvalidity, last_uid = cursor.split(":", 1)
        return uidvalidity, int(last_uid)
    except (ValueError, TypeError):
        logger.warning("Ignoring malformed sync cursor: %r", cursor)
        return None, None


def _make_cursor(uidvalidity: str, last_uid: int) -> str:
    return f"{uidvalidity}:{last_uid}"


class IMAPProvider(EmailProvider):
    def __init__(self, settings: Settings, mailbox: str = "INBOX"):
        if not settings.imap_is_configured():
            raise EmailFetchError("Email account is not configured (missing address/app password).")
        self._server = settings.imap_server
        self._port = settings.imap_port
        self._user = settings.email_address
        self._password = settings.email_app_password
        self._mailbox = mailbox

    def fetch_new_messages(self, cursor: str | None, batch_size: int) -> FetchResult:
        known_uidvalidity, last_uid = _parse_cursor(cursor)

        mail: imaplib.IMAP4_SSL | None = None
        try:
            mail = imaplib.IMAP4_SSL(self._server, self._port)
            mail.login(self._user, self._password)
            mail.select(self._mailbox)

            current_uidvalidity = self._get_uidvalidity(mail)
            if known_uidvalidity is not None and known_uidvalidity != current_uidvalidity:
                logger.warning(
                    "IMAP UIDVALIDITY changed (%s -> %s); resyncing from scratch",
                    known_uidvalidity,
                    current_uidvalidity,
                )
                last_uid = None

            search_range = f"{last_uid + 1}:*" if last_uid is not None else "1:*"
            status, data = mail.uid("search", None, search_range)
            if status != "OK":
                raise EmailFetchError(f"IMAP UID search failed with status: {status}")

            uids = [int(u) for u in data[0].split()] if data and data[0] else []
            if last_uid is not None:
                # "N:*" can include N itself as an IMAP quirk when N is
                # past the mailbox's current max UID; filter defensively.
                uids = [u for u in uids if u > last_uid]
            uids.sort()
            uids = uids[:batch_size]

            if not uids:
                return FetchResult(messages=[], new_cursor=None)

            messages: list[RawEmail] = []
            for uid in uids:
                status, msg_data = mail.uid("fetch", str(uid), "(RFC822)")
                if status != "OK" or not msg_data or not msg_data[0]:
                    raise EmailFetchError(f"IMAP UID fetch failed for uid={uid}")
                messages.append(RawEmail(provider_uid=str(uid), raw_bytes=msg_data[0][1]))

            new_cursor = _make_cursor(current_uidvalidity, uids[-1])
            return FetchResult(messages=messages, new_cursor=new_cursor)

        except imaplib.IMAP4.error as exc:
            logger.warning("IMAP error while syncing %s", self._server)
            raise EmailFetchError("IMAP login or fetch failed. Check credentials and server settings.") from exc
        except OSError as exc:
            logger.warning("Network error connecting to %s", self._server)
            raise EmailFetchError("Could not connect to the mail server.") from exc
        finally:
            if mail is not None:
                try:
                    mail.logout()
                except Exception:
                    pass

    @staticmethod
    def _get_uidvalidity(mail: imaplib.IMAP4_SSL) -> str:
        _, data = mail.response("UIDVALIDITY")
        if data and data[0]:
            return data[0].decode()
        raise EmailFetchError("Mail server did not report UIDVALIDITY; cannot sync incrementally.")
