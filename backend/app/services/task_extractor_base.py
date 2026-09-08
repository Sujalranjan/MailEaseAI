from abc import ABC, abstractmethod

from app.models import Email
from app.schemas.task import ExtractedTask


class TaskExtractionError(RuntimeError):
    """Raised when an extractor fails outright (LLM call failure, invalid
    structured output, etc). Callers treat this identically to "zero
    tasks found" — extraction failure must never corrupt the database or
    abort the surrounding sync batch.
    """


class TaskExtractor(ABC):
    """Provider-agnostic task-extraction interface. RuleBasedTaskExtractor
    (deterministic, active by default) and LLMTaskExtractor (structured-
    output-validated, not wired into the pipeline — see its module
    docstring) both implement this, so the orchestrator
    (task_extraction_service.py) never depends on which one is in use.
    """

    @abstractmethod
    def extract(self, email: Email) -> list[ExtractedTask]:
        """Return zero or more candidate tasks found in `email`. May
        raise TaskExtractionError; must never return anything other than
        validated ExtractedTask instances.
        """
        raise NotImplementedError
