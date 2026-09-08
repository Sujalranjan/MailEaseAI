from app.services.task_extractor_base import TaskExtractor
from app.services.task_extractor_rule_based import RuleBasedTaskExtractor


def get_task_extractor() -> TaskExtractor:
    """Only a deterministic extractor is wired in this phase. See
    task_extractor_llm.py for the validated-structured-output pattern
    that would plug in here once a real LLM provider/key exists — it is
    a real, tested implementation, just not selectable yet, since there
    is nothing configured for it to call.
    """
    return RuleBasedTaskExtractor()
