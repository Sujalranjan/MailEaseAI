"""Import every model module so Base.metadata is fully populated before
Alembic autogenerate or test create_all() run, and so relationship()
string forward-references resolve regardless of import order elsewhere.
"""

from app.db.base import Base
from app.models.email import Email, EmailThread
from app.models.reply import GeneratedReply
from app.models.task import CalendarEvent, Task
from app.models.user import EmailAccount, User

__all__ = [
    "Base",
    "User",
    "EmailAccount",
    "EmailThread",
    "Email",
    "Task",
    "CalendarEvent",
    "GeneratedReply",
]
