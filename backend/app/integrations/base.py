"""Provider-agnostic interface for fetching raw mail.

The goal is that swapping IMAP for the Gmail API later means writing a
new class that satisfies EmailProvider, not touching the sync/normalize/
persist pipeline built on top of it. Everything provider-specific (IMAP
UIDs and UIDVALIDITY today; a Gmail historyId if/when that provider is
added) stays behind the opaque `cursor` string — callers never interpret
it, only store and pass it back.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass


class EmailFetchError(RuntimeError):
    """Raised when a provider fails to connect or fetch. Never includes
    credentials — messages are written to be safe to return in an API
    error response.
    """


@dataclass(frozen=True)
class RawEmail:
    """One not-yet-parsed message as retrieved from the provider."""

    provider_uid: str
    raw_bytes: bytes


@dataclass(frozen=True)
class FetchResult:
    messages: list[RawEmail]
    # The cursor to persist for next time. None means "no new messages
    # were found — leave the stored cursor unchanged" (as opposed to an
    # empty-but-valid cursor, which would be a real, if unlikely, value).
    new_cursor: str | None


class EmailProvider(ABC):
    @abstractmethod
    def fetch_new_messages(self, cursor: str | None, batch_size: int) -> FetchResult:
        """Return up to `batch_size` messages newer than `cursor`.

        All-or-nothing: if the provider fails partway through retrieving
        a batch, it must raise rather than return a partial FetchResult,
        so the caller never persists an inconsistent subset or advances
        the cursor past messages it didn't actually retrieve. Raises
        EmailFetchError on any provider/network failure.
        """
        raise NotImplementedError
