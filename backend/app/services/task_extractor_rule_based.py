"""Deterministic, keyword/regex task extraction — no ML/LLM.

Same class of heuristic as email_normalizer.categorize_email: real
limitations (imperfect actionability detection, a fixed vocabulary of
relative date phrases), but fully deterministic and unit-testable, which
an LLM-backed extractor fundamentally cannot promise on its own. This is
the only extractor actually wired into the sync pipeline in this phase —
see task_extractor_llm.py for why an LLM-backed alternative exists but
isn't active.

No third-party date-parsing library is used. The set of formats this
phase must support is small and explicit (ISO, DD/MM or MM/DD numeric,
month-name, and five specific relative phrases), and hand-rolling it
keeps every ambiguity-handling decision visible and testable rather than
delegating to a general-purpose parser's own (often surprising, locale-
dependent) guessing behavior — which would work against the requirement
to be conservative about ambiguous dates.

Deadline resolution is always anchored to the email's own `received_at`
timestamp, never `datetime.now()` — a relative phrase like "tomorrow"
means the day after the email was sent, not the day after we happen to
process it. This is also what makes extraction deterministic: reprocessing
the same email later must produce the same deadline every time.
"""

import re
from datetime import date, datetime, timedelta, timezone

from app.models import Email
from app.schemas.task import ExtractedTask
from app.services.task_extractor_base import TaskExtractor

_ACTION_CUES = (
    "please ",
    "kindly ",
    "can you",
    "could you",
    "would you",
    "need you to",
    "make sure",
    "don't forget",
    "do not forget",
    "remember to",
    "action required",
    "reply by",
    "respond by",
    "confirm by",
    "send me",
    "send the",
    "complete the",
    "finish the",
    "review and",
    "let me know by",
    "get back to me by",
    "required to",
    "must submit",
    "need to submit",
    "should submit",
)

_IMPERATIVE_VERBS = (
    "submit",
    "send",
    "complete",
    "finish",
    "review",
    "confirm",
    "provide",
    "attach",
    "upload",
    "schedule",
    "prepare",
    "update",
    "reply",
    "respond",
    "sign",
    "return",
    "pay",
    "register",
    "call",
)

_INFORMATIONAL_OVERRIDES = (
    "fyi",
    "for your information",
    "just to let you know",
    "no action needed",
    "no action required",
    "was held",
    "took place",
    "happened on",
    "for reference only",
)

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")
_FIRST_WORD = re.compile(r"[a-zA-Z']+")

_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}
_MONTH_NAMES_ALT = "|".join(sorted(_MONTHS, key=len, reverse=True))
_MONTH_DAY_PATTERN = re.compile(
    rf"\b({_MONTH_NAMES_ALT})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s*(\d{{4}}))?\b", re.IGNORECASE
)
_DAY_MONTH_PATTERN = re.compile(
    rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MONTH_NAMES_ALT})\.?(?:,?\s*(\d{{4}}))?\b", re.IGNORECASE
)
_ISO_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_NUMERIC_DATE = re.compile(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})\b")

_WEEKDAYS = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6}
_WEEKDAY_ALT = "|".join(_WEEKDAYS)
_NEXT_WEEKDAY_PATTERN = re.compile(rf"\bnext ({_WEEKDAY_ALT})\b", re.IGNORECASE)
_BY_WEEKDAY_PATTERN = re.compile(rf"\b(?:by|on) ({_WEEKDAY_ALT})\b", re.IGNORECASE)
_IN_N_DAYS_PATTERN = re.compile(r"\bin (\d+) days?\b", re.IGNORECASE)
_TOMORROW_PATTERN = re.compile(r"\btomorrow\b", re.IGNORECASE)
_NEXT_WEEK_PATTERN = re.compile(r"\bnext week\b", re.IGNORECASE)


def _split_sentences(body: str) -> list[str]:
    if not body or not body.strip():
        return []
    return [p.strip() for p in _SENTENCE_SPLIT.split(body) if p.strip()]


def _is_actionable(sentence: str) -> bool:
    text = sentence.lower()
    if any(phrase in text for phrase in _INFORMATIONAL_OVERRIDES):
        return False
    if any(phrase in text for phrase in _ACTION_CUES):
        return True
    first = _FIRST_WORD.match(text)
    return bool(first and first.group(0) in _IMPERATIVE_VERBS)


def _make_title(sentence: str) -> str:
    cleaned = re.sub(r"\s+", " ", sentence).strip()
    return cleaned[:297] + "..." if len(cleaned) > 300 else cleaned


def _extract_time_of_day(text: str) -> tuple[int, int] | None:
    lowered = text.lower()
    if re.search(r"\bnoon\b", lowered):
        return (12, 0)
    if re.search(r"\bmidnight\b", lowered):
        return (0, 0)

    m = re.search(r"\b(1[0-2]|0?[1-9]):([0-5][0-9])\s*(am|pm)\b", lowered)
    if m:
        hour, minute, meridiem = int(m.group(1)), int(m.group(2)), m.group(3)
        return (_to_24h(hour, meridiem), minute)

    m = re.search(r"\b(1[0-2]|0?[1-9])\s*(am|pm)\b", lowered)
    if m:
        return (_to_24h(int(m.group(1)), m.group(2)), 0)

    m = re.search(r"\b([01]?[0-9]|2[0-3]):([0-5][0-9])\b", text)
    if m:
        return (int(m.group(1)), int(m.group(2)))
    return None


def _to_24h(hour: int, meridiem: str) -> int:
    if meridiem == "pm" and hour != 12:
        return hour + 12
    if meridiem == "am" and hour == 12:
        return 0
    return hour


def _combine(d: date, sentence: str) -> datetime:
    hour, minute = _extract_time_of_day(sentence) or (23, 59)
    return datetime(d.year, d.month, d.day, hour, minute, tzinfo=timezone.utc)


def _match_month_name_date(sentence: str, anchor_date: date) -> date | None:
    m = _MONTH_DAY_PATTERN.search(sentence)
    if m:
        month, day, year_str = _MONTHS[m.group(1).lower()], int(m.group(2)), m.group(3)
    else:
        m = _DAY_MONTH_PATTERN.search(sentence)
        if not m:
            return None
        day, month, year_str = int(m.group(1)), _MONTHS[m.group(2).lower()], m.group(3)

    year = int(year_str) if year_str else anchor_date.year
    try:
        d = date(year, month, day)
    except ValueError:
        return None

    if not year_str and d < anchor_date:
        try:
            d = date(year + 1, month, day)
        except ValueError:
            return None
    return d


def _match_numeric_date(sentence: str) -> tuple[date | None, bool]:
    """Returns (date_or_None, was_ambiguous)."""
    m = _NUMERIC_DATE.search(sentence)
    if not m:
        return None, False

    first, second, year_str = int(m.group(1)), int(m.group(2)), m.group(3)
    year = int(year_str) if len(year_str) == 4 else 2000 + int(year_str)

    if first > 12:
        day, month = first, second
    elif second > 12:
        day, month = second, first
    elif first == second:
        day, month = first, second
    else:
        return None, True  # genuinely ambiguous: could be DD/MM or MM/DD

    try:
        return date(year, month, day), False
    except ValueError:
        return None, False  # unambiguous order, but not a real calendar date


def _next_weekday(anchor: date, target: int, include_today: bool) -> date:
    days_ahead = target - anchor.weekday()
    if days_ahead < 0 or (days_ahead == 0 and not include_today):
        days_ahead += 7
    return anchor + timedelta(days=days_ahead)


def _match_relative_date(sentence: str, anchor_date: date) -> date | None:
    if _TOMORROW_PATTERN.search(sentence):
        return anchor_date + timedelta(days=1)
    if _NEXT_WEEK_PATTERN.search(sentence):
        return anchor_date + timedelta(days=7)
    m = _IN_N_DAYS_PATTERN.search(sentence)
    if m:
        return anchor_date + timedelta(days=int(m.group(1)))
    m = _NEXT_WEEKDAY_PATTERN.search(sentence)
    if m:
        return _next_weekday(anchor_date, _WEEKDAYS[m.group(1).lower()], include_today=False)
    m = _BY_WEEKDAY_PATTERN.search(sentence)
    if m:
        return _next_weekday(anchor_date, _WEEKDAYS[m.group(1).lower()], include_today=True)
    return None


def _resolve_deadline(sentence: str, anchor: datetime) -> tuple[datetime | None, str | None]:
    anchor_date = anchor.date()

    m = _ISO_DATE.search(sentence)
    if m:
        try:
            d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            return _combine(d, sentence), "confirmed"
        except ValueError:
            pass  # fall through to other patterns rather than give up entirely

    d = _match_month_name_date(sentence, anchor_date)
    if d is not None:
        return _combine(d, sentence), "confirmed"

    d, ambiguous = _match_numeric_date(sentence)
    if ambiguous:
        return None, "ambiguous"
    if d is not None:
        return _combine(d, sentence), "confirmed"

    d = _match_relative_date(sentence, anchor_date)
    if d is not None:
        return _combine(d, sentence), "confirmed"

    return None, None


class RuleBasedTaskExtractor(TaskExtractor):
    def extract(self, email: Email) -> list[ExtractedTask]:
        anchor = email.received_at
        tasks: list[ExtractedTask] = []

        for sentence in _split_sentences(email.body):
            if not _is_actionable(sentence):
                continue

            deadline, confidence = (None, None)
            if anchor is not None:
                deadline, confidence = _resolve_deadline(sentence, anchor)

            tasks.append(
                ExtractedTask(
                    title=_make_title(sentence),
                    description=None,
                    deadline=deadline,
                    deadline_confidence=confidence,
                    priority=email.urgency,
                )
            )

        return tasks
