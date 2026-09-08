from datetime import datetime, timezone

from app.models import Email
from app.services.task_extractor_rule_based import RuleBasedTaskExtractor


_DEFAULT_ANCHOR = datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc)  # a Tuesday
_UNSET = object()


def make_email(body, subject="Test", urgency="Low", received_at=_UNSET):
    return Email(
        email_account_id=1,
        provider_message_id="<x@example.com>",
        subject=subject,
        body=body,
        urgency=urgency,
        received_at=_DEFAULT_ANCHOR if received_at is _UNSET else received_at,
    )


extractor = RuleBasedTaskExtractor()


class TestSingleAndMultipleTasks:
    def test_email_with_one_task(self):
        email = make_email("Please submit the report by Friday.")
        tasks = extractor.extract(email)
        assert len(tasks) == 1
        assert "submit the report" in tasks[0].title.lower()

    def test_email_with_no_task(self):
        email = make_email("Thanks for the update, the meeting went well yesterday.")
        assert extractor.extract(email) == []

    def test_email_with_multiple_independent_tasks(self):
        email = make_email(
            "Please submit the report by Friday. Also, kindly send the invoice by 2026-09-20. "
            "The weather was nice today."
        )
        tasks = extractor.extract(email)
        assert len(tasks) == 2
        titles = " ".join(t.title.lower() for t in tasks)
        assert "report" in titles
        assert "invoice" in titles


class TestActionableVsInformational:
    def test_informational_statement_is_not_actionable(self):
        email = make_email("The meeting was held on 2026-09-15 and went well.")
        assert extractor.extract(email) == []

    def test_fyi_override_suppresses_action_cue(self):
        email = make_email("FYI, please note the office will submit reports differently from now on.")
        assert extractor.extract(email) == []

    def test_imperative_verb_start_is_actionable(self):
        email = make_email("Submit the form before the end of day.")
        tasks = extractor.extract(email)
        assert len(tasks) == 1


class TestExplicitDates:
    def test_iso_date(self):
        email = make_email("Please submit the report by 2026-09-15.")
        tasks = extractor.extract(email)
        assert tasks[0].deadline == datetime(2026, 9, 15, 23, 59, tzinfo=timezone.utc)
        assert tasks[0].deadline_confidence == "confirmed"

    def test_month_name_date_with_year(self):
        email = make_email("Please submit the report by September 15, 2026.")
        tasks = extractor.extract(email)
        assert tasks[0].deadline == datetime(2026, 9, 15, 23, 59, tzinfo=timezone.utc)

    def test_day_then_month_name(self):
        email = make_email("Please submit the report by 15 September 2026.")
        tasks = extractor.extract(email)
        assert tasks[0].deadline == datetime(2026, 9, 15, 23, 59, tzinfo=timezone.utc)

    def test_month_name_without_year_infers_current_year_when_future(self):
        # Anchor is 2026-09-08; "December 1" without a year is still ahead.
        email = make_email("Please submit the report by December 1.")
        tasks = extractor.extract(email)
        assert tasks[0].deadline.year == 2026
        assert tasks[0].deadline.month == 12

    def test_month_name_without_year_rolls_forward_when_in_the_past(self):
        # Anchor is 2026-09-08; "March 1" without a year has already
        # passed this year, so it must roll forward to next year.
        email = make_email("Please submit the report by March 1.")
        tasks = extractor.extract(email)
        assert tasks[0].deadline.year == 2027
        assert tasks[0].deadline.month == 3

    def test_unambiguous_numeric_date_day_over_twelve(self):
        email = make_email("Please submit the report by 25/09/2026.")
        tasks = extractor.extract(email)
        assert tasks[0].deadline == datetime(2026, 9, 25, 23, 59, tzinfo=timezone.utc)
        assert tasks[0].deadline_confidence == "confirmed"


class TestRelativeDates:
    def test_tomorrow(self):
        email = make_email("Please send the file tomorrow.")
        tasks = extractor.extract(email)
        assert tasks[0].deadline.date().isoformat() == "2026-09-09"

    def test_next_week(self):
        email = make_email("Please send the file next week.")
        tasks = extractor.extract(email)
        assert tasks[0].deadline.date().isoformat() == "2026-09-15"

    def test_in_n_days(self):
        email = make_email("Please send the file in 3 days.")
        tasks = extractor.extract(email)
        assert tasks[0].deadline.date().isoformat() == "2026-09-11"

    def test_by_friday(self):
        # Anchor Tuesday 2026-09-08; next Friday is 2026-09-11.
        email = make_email("Please send the file by Friday.")
        tasks = extractor.extract(email)
        assert tasks[0].deadline.date().isoformat() == "2026-09-11"

    def test_next_monday(self):
        # "next Monday" explicitly skips the coming Monday-adjacent week
        # boundary semantics tested here: anchor is Tuesday, so the very
        # next Monday is only 6 days away and "next" should still mean
        # that one (not skip an extra week) since it hasn't occurred yet.
        email = make_email("Please send the file next Monday.")
        tasks = extractor.extract(email)
        assert tasks[0].deadline.date().isoformat() == "2026-09-14"

    def test_bare_weekday_without_by_or_on_is_not_treated_as_deadline(self):
        email = make_email("Please review the notes, Friday's session was useful.")
        tasks = extractor.extract(email)
        assert len(tasks) == 1
        assert tasks[0].deadline is None


class TestDatesWithTimes:
    def test_explicit_time_pm(self):
        email = make_email("Please submit the report by 2026-09-15 5pm.")
        tasks = extractor.extract(email)
        assert tasks[0].deadline == datetime(2026, 9, 15, 17, 0, tzinfo=timezone.utc)

    def test_explicit_time_24h(self):
        email = make_email("Please submit the report by 2026-09-15 17:30.")
        tasks = extractor.extract(email)
        assert tasks[0].deadline == datetime(2026, 9, 15, 17, 30, tzinfo=timezone.utc)

    def test_noon(self):
        email = make_email("Please submit the report by 2026-09-15 noon.")
        tasks = extractor.extract(email)
        assert tasks[0].deadline == datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)

    def test_no_time_defaults_to_end_of_day(self):
        email = make_email("Please submit the report by 2026-09-15.")
        tasks = extractor.extract(email)
        assert tasks[0].deadline.hour == 23
        assert tasks[0].deadline.minute == 59


class TestAmbiguousAndMalformedDates:
    def test_ambiguous_numeric_date_yields_no_deadline_but_still_a_task(self):
        # Both 05 and 06 are valid day-or-month values -> genuinely ambiguous.
        email = make_email("Please submit the report by 05/06/2026.")
        tasks = extractor.extract(email)
        assert len(tasks) == 1
        assert tasks[0].deadline is None
        assert tasks[0].deadline_confidence == "ambiguous"

    def test_invalid_calendar_date_is_dropped_not_crashed(self):
        # Unambiguous order (31 can't be a month) but Feb 31 doesn't exist.
        email = make_email("Please submit the report by 31/02/2026.")
        tasks = extractor.extract(email)
        assert len(tasks) == 1
        assert tasks[0].deadline is None

    def test_no_date_at_all_task_has_none_deadline(self):
        email = make_email("Please submit the report soon.")
        tasks = extractor.extract(email)
        assert len(tasks) == 1
        assert tasks[0].deadline is None
        assert tasks[0].deadline_confidence is None

    def test_missing_anchor_timestamp_never_invents_a_deadline(self):
        email = make_email("Please submit the report by Friday.", received_at=None)
        tasks = extractor.extract(email)
        assert len(tasks) == 1
        assert tasks[0].deadline is None


class TestMultipleDeadlinesInOneEmail:
    def test_two_tasks_with_different_deadlines_each_keep_their_own(self):
        email = make_email(
            "Please submit the draft by 2026-09-10. Please submit the final version by 2026-09-20."
        )
        tasks = extractor.extract(email)
        assert len(tasks) == 2
        deadlines = sorted(t.deadline for t in tasks)
        assert deadlines[0].day == 10
        assert deadlines[1].day == 20


class TestPriorityInheritance:
    def test_priority_inherited_from_email_urgency(self):
        email = make_email("Please submit the report by Friday.", urgency="High")
        tasks = extractor.extract(email)
        assert tasks[0].priority == "High"


class TestMalformedOrEmptyContent:
    def test_empty_body_returns_no_tasks(self):
        email = make_email("")
        assert extractor.extract(email) == []

    def test_placeholder_body_returns_no_tasks(self):
        email = make_email("(no readable content)")
        assert extractor.extract(email) == []
