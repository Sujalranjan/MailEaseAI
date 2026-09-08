from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin


class User(Base, TimestampMixin):
    """A Mail-Ease account holder.

    Minimal by design: there is no authentication system yet (planned
    for a later phase alongside Gmail OAuth). Until then, exactly one
    User/EmailAccount pair is bootstrapped from the configured mailbox
    address — see repositories/account_repository.py.
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)

    email_accounts: Mapped[list["EmailAccount"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class EmailAccount(Base, TimestampMixin):
    """A connected mailbox. One user can eventually connect multiple
    accounts (e.g. work + personal Gmail); today only IMAP is supported,
    with Gmail API as a planned addition behind the same EmailProvider
    interface (see app/integrations/base.py).

    `sync_cursor` is a deliberately opaque, provider-defined string used
    to resume incremental sync (see app/integrations/imap_provider.py for
    what IMAP packs into it). Keeping it opaque here — rather than typed
    IMAP-specific columns like "last_uid" — is what lets a future Gmail
    provider (which would use a historyId, not a UID) reuse this same
    column without a schema change.
    """

    __tablename__ = "email_accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    email_address: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    provider: Mapped[str] = mapped_column(String(20), default="imap")
    imap_server: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sync_cursor: Mapped[str | None] = mapped_column(String(255), nullable=True)

    user: Mapped["User"] = relationship(back_populates="email_accounts")
    threads: Mapped[list["EmailThread"]] = relationship(
        back_populates="email_account", cascade="all, delete-orphan"
    )
    emails: Mapped[list["Email"]] = relationship(
        back_populates="email_account", cascade="all, delete-orphan"
    )
