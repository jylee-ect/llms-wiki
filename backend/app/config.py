import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

_ALL_EFFORTS = ["none", "low", "medium", "high", "xhigh", "max"]

# 선택 가능한 모델과 지원 reasoning effort (2026-10 OpenAI API 기준, 실제 호출로 확인)
MODELS: dict[str, dict] = {
    "gpt-6-luna": {
        "label": "GPT-6 Luna",
        "description": "가장 빠르고 저렴. 일상적인 수집·질의에 적합",
        "efforts": _ALL_EFFORTS,
    },
    "gpt-6-sol": {
        "label": "GPT-6 Sol",
        "description": "속도·비용·성능 균형",
        "efforts": _ALL_EFFORTS,
    },
    "gpt-6.1-sol": {
        "label": "GPT-6.1 Sol",
        "description": "Sol 최신 버전. effort 'none' 미지원",
        "efforts": _ALL_EFFORTS[1:],
    },
}


class Settings:
    api_key: str | None = os.getenv("GPT_API")
    model: str = os.getenv("LLM_MODEL", "gpt-6-luna")
    reasoning_effort: str = os.getenv("LLM_REASONING_EFFORT", "medium")
    llm_timeout: float = float(os.getenv("LLM_TIMEOUT", "600"))

    data_dir: Path = Path(os.getenv("WIKI_DATA_DIR", str(ROOT / "data")))

    # 한 번에 LLM에 넘기는 양의 상한 (문자 수)
    max_source_chars: int = int(os.getenv("MAX_SOURCE_CHARS", "150000"))
    max_lint_chars: int = int(os.getenv("MAX_LINT_CHARS", "200000"))
    max_related_pages: int = int(os.getenv("MAX_RELATED_PAGES", "8"))
    max_query_pages: int = int(os.getenv("MAX_QUERY_PAGES", "8"))
    max_upload_bytes: int = int(os.getenv("MAX_UPLOAD_MB", "20")) * 1024 * 1024

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def wiki_dir(self) -> Path:
        return self.data_dir / "wiki"

    @property
    def schema_path(self) -> Path:
        return self.data_dir / "AGENTS.md"


settings = Settings()
