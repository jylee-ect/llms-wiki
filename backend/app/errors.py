class InputError(ValueError):
    """사용자 입력 문제 (HTTP 400)."""


class LLMError(RuntimeError):
    """LLM 호출 실패 (HTTP 502)."""
