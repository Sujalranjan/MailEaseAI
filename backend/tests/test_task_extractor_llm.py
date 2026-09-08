"""Tests the LLM-backed extractor's structured-output validation using a
fake LLMClient — never a real network call, since no provider/API key is
configured in this environment. These prove the safety mechanics
(requirement: never write arbitrary/invalid model output to the
database), not that any specific provider integration works.
"""

import pytest

from app.models import Email
from app.services.task_extractor_base import TaskExtractionError
from app.services.task_extractor_llm import LLMTaskExtractor


class FakeLLMClient:
    def __init__(self, response: str):
        self._response = response

    def complete(self, prompt: str) -> str:
        return self._response


class RaisingLLMClient:
    def complete(self, prompt: str) -> str:
        raise TimeoutError("simulated provider timeout")


def make_email():
    return Email(email_account_id=1, provider_message_id="<x@example.com>", subject="Hi", body="Please submit it.")


class TestValidStructuredOutput:
    def test_valid_response_produces_tasks(self):
        response = '{"tasks": [{"title": "Submit the report", "description": null, "deadline_iso": "2026-09-15T17:00:00", "priority": "High"}]}'
        extractor = LLMTaskExtractor(FakeLLMClient(response))
        tasks = extractor.extract(make_email())

        assert len(tasks) == 1
        assert tasks[0].title == "Submit the report"
        assert tasks[0].deadline.isoformat() == "2026-09-15T17:00:00"
        assert tasks[0].deadline_confidence == "confirmed"
        assert tasks[0].priority == "High"

    def test_empty_tasks_list_is_valid(self):
        extractor = LLMTaskExtractor(FakeLLMClient('{"tasks": []}'))
        assert extractor.extract(make_email()) == []

    def test_null_deadline_is_valid(self):
        response = '{"tasks": [{"title": "Call back", "deadline_iso": null}]}'
        extractor = LLMTaskExtractor(FakeLLMClient(response))
        tasks = extractor.extract(make_email())
        assert tasks[0].deadline is None
        assert tasks[0].deadline_confidence is None


class TestInvalidStructuredOutput:
    def test_malformed_json_raises_extraction_error(self):
        extractor = LLMTaskExtractor(FakeLLMClient("this is not json at all"))
        with pytest.raises(TaskExtractionError):
            extractor.extract(make_email())

    def test_json_missing_required_field_raises_extraction_error(self):
        # "tasks" key is required by the schema.
        extractor = LLMTaskExtractor(FakeLLMClient('{"items": []}'))
        with pytest.raises(TaskExtractionError):
            extractor.extract(make_email())

    def test_task_with_empty_title_raises_extraction_error(self):
        response = '{"tasks": [{"title": "   "}]}'
        extractor = LLMTaskExtractor(FakeLLMClient(response))
        with pytest.raises(TaskExtractionError):
            extractor.extract(make_email())

    def test_prose_wrapped_around_json_raises_extraction_error(self):
        # A real model occasionally ignores "return ONLY JSON" -- this
        # must be rejected, not string-scraped or partially trusted.
        response = 'Sure! Here is the JSON: {"tasks": []}'
        extractor = LLMTaskExtractor(FakeLLMClient(response))
        with pytest.raises(TaskExtractionError):
            extractor.extract(make_email())

    def test_unparseable_deadline_drops_deadline_but_keeps_task(self):
        response = '{"tasks": [{"title": "Call back", "deadline_iso": "not-a-real-date"}]}'
        extractor = LLMTaskExtractor(FakeLLMClient(response))
        tasks = extractor.extract(make_email())
        assert len(tasks) == 1
        assert tasks[0].deadline is None


class TestClientFailure:
    def test_client_exception_raises_extraction_error_not_the_original(self):
        extractor = LLMTaskExtractor(RaisingLLMClient())
        with pytest.raises(TaskExtractionError):
            extractor.extract(make_email())
