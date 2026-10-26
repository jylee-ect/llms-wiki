"""OpenAI Responses API 래퍼."""
import json
from dataclasses import dataclass

from openai import OpenAI, OpenAIError

from .config import MODELS, settings
from .errors import InputError, LLMError


@dataclass(frozen=True)
class LLMOptions:
    model: str
    effort: str

    def describe(self) -> str:
        return f"{self.model} (effort: {self.effort})"


def resolve_options(model: str | None = None, effort: str | None = None) -> LLMOptions:
    """요청에서 받은 모델/effort를 검증한다. 비어 있으면 서버 기본값을 쓴다."""
    model = model or settings.model
    effort = effort or settings.reasoning_effort
    if model not in MODELS:
        raise InputError(f"지원하지 않는 모델입니다: {model} (지원: {', '.join(MODELS)})")
    efforts = MODELS[model]["efforts"]
    if effort not in efforts:
        raise InputError(f"{model}은(는) effort '{effort}'를 지원하지 않습니다 (지원: {', '.join(efforts)})")
    return LLMOptions(model, effort)


_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        if not settings.api_key:
            raise LLMError("GPT_API 환경변수가 설정되어 있지 않습니다.")
        _client = OpenAI(api_key=settings.api_key, timeout=settings.llm_timeout)
    return _client


def _create(opts: LLMOptions, instructions: str, input: str, **kwargs):
    try:
        response = _get_client().responses.create(
            model=opts.model,
            instructions=instructions,
            input=input,
            reasoning={"effort": opts.effort},
            **kwargs,
        )
    except OpenAIError as e:
        raise LLMError(f"LLM 호출 실패: {e}") from e
    if response.status == "incomplete":
        reason = getattr(response.incomplete_details, "reason", "unknown")
        raise LLMError(f"LLM 응답이 중간에 끊겼습니다 (reason: {reason}). 입력 크기를 줄여 보세요.")
    return response


def complete_text(opts: LLMOptions, instructions: str, input: str) -> str:
    return _create(opts, instructions, input).output_text.strip()


def complete_json(opts: LLMOptions, instructions: str, input: str, schema: dict, name: str) -> dict:
    response = _create(
        opts,
        instructions,
        input,
        text={"format": {"type": "json_schema", "name": name, "schema": schema, "strict": True}},
    )
    try:
        return json.loads(response.output_text)
    except json.JSONDecodeError as e:
        raise LLMError("LLM이 올바른 JSON을 반환하지 않았습니다.") from e
