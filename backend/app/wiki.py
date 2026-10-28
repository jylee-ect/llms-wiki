"""LLM Wiki의 세 가지 동작: ingest, query, lint."""
import time

from . import llm, store
from .config import settings
from .errors import InputError
from .extract import extract_text
from .llm import LLMOptions
from .store import PAGE_TYPES, Page

PICK_SCHEMA = {
    "type": "object",
    "properties": {"slugs": {"type": "array", "items": {"type": "string"}}},
    "required": ["slugs"],
    "additionalProperties": False,
}

INGEST_SCHEMA = {
    "type": "object",
    "properties": {
        "source_title": {"type": "string"},
        "pages": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "slug": {"type": "string"},
                    "title": {"type": "string"},
                    "type": {"type": "string", "enum": PAGE_TYPES},
                    "summary": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["slug", "title", "type", "summary", "content"],
                "additionalProperties": False,
            },
        },
        "log": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["source_title", "pages", "log"],
    "additionalProperties": False,
}

LINT_SCHEMA = {
    "type": "object",
    "properties": {
        "issues": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {
                        "type": "string",
                        "enum": ["contradiction", "stale", "missing_page", "missing_link", "duplicate", "other"],
                    },
                    "pages": {"type": "array", "items": {"type": "string"}},
                    "description": {"type": "string"},
                    "suggestion": {"type": "string"},
                },
                "required": ["kind", "pages", "description", "suggestion"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["issues"],
    "additionalProperties": False,
}

INGEST_PICK_INSTR = """너는 위키 관리자다. 새 원본 문서가 들어왔다.
위키 목차를 보고, 이 문서의 내용으로 보강하거나 수정해야 할 기존 페이지의 slug를 골라라.
관련성이 높은 순서로 최대 {limit}개. 관련 페이지가 없으면 빈 배열."""

INGEST_INSTR = """너는 위키 관리자다. 새 원본 문서를 읽고 위키에 통합한다.
아래 규칙(스키마)을 반드시 따른다.

<schema>
{schema}
</schema>

작업:
1. 이 원본에 대한 `source` 유형 페이지를 하나 만든다. slug는 `source-`로 시작한다.
2. 원본에 등장하는 중요한 개체·개념·주제에 대해 페이지를 새로 만들거나, 제공된 기존 페이지를 갱신한다.
   - 기존 페이지를 갱신할 때는 같은 slug를 쓰고, 기존 내용을 보존하면서 새 정보를 통합한 **본문 전체**를 반환한다.
   - 목차에는 있지만 본문이 제공되지 않은 페이지는 같은 slug로 반환하지 말고 링크만 건다.
3. 페이지끼리 `[[slug]]`로 적극적으로 연결한다. 목차에 있는 기존 페이지로의 링크도 좋다.
4. `summary`는 목차에 들어갈 한 줄 요약(80자 이내)이다.
5. `content`는 본문 마크다운이다. frontmatter와 `#` 제목은 넣지 않는다.
6. `log`에는 이번 작업에서 한 일을 짧은 문장 몇 개로 적는다.

원본 파일명: {source}
오늘 날짜: {today}"""

QUERY_PICK_INSTR = """너는 위키 검색기다. 위키 목차를 보고 질문에 답하는 데 필요한 페이지의 slug를 골라라.
관련성이 높은 순서로 최대 {limit}개. 관련 페이지가 없으면 빈 배열."""

QUERY_INSTR = """너는 사내 지식 위키를 기반으로 답하는 어시스턴트다.
제공된 위키 페이지만 근거로 질문에 답한다.

- 답변의 각 주장 뒤에 근거 페이지를 `[[slug]]` 형식으로 표시한다.
- 위키에 근거가 없거나 부족하면 그렇다고 분명히 말하고, 어떤 자료를 추가하면 좋을지 제안한다.
- 마크다운으로 간결하게 쓴다. 필요하면 표를 사용한다.
- 답변 언어는 질문의 언어를 따른다."""

LINT_INSTR = """너는 위키 품질 점검자다. 아래 위키 페이지들을 읽고 문제를 찾아라.

점검 항목:
- contradiction: 페이지 간 서로 모순되는 사실
- stale: 더 새로운 원본에 의해 대체되었을 가능성이 있는 오래된 주장
- missing_page: 여러 곳에서 언급되지만 자체 페이지가 없는 중요한 개념·개체
- missing_link: 서로 연결되어야 하는데 링크가 없는 페이지
- duplicate: 같은 대상을 다루는 중복 페이지
- other: 그 밖에 출처 누락 등 품질 문제

`pages`에는 관련 페이지 slug를 넣는다. 설명과 제안은 한국어로 구체적으로 쓴다.
문제가 없으면 빈 배열을 반환한다."""


def _pages_context(slugs: list[str]) -> str:
    blocks = []
    for slug in slugs:
        page = store.get_page(slug)
        if page:
            blocks.append(f'<page slug="{slug}">\n{page.to_markdown()}</page>')
    return "\n\n".join(blocks)


def _pick_pages(opts: LLMOptions, instructions: str, context: str, limit: int) -> list[str]:
    if not store.list_pages():
        return []
    result = llm.complete_json(
        opts,
        instructions.format(limit=limit),
        f"# 위키 목차\n{store.read_index()}\n\n{context}",
        PICK_SCHEMA,
        "pick_pages",
    )
    picked: list[str] = []
    for raw in result["slugs"]:
        slug = store.normalize_slug(raw)
        if slug not in picked and store.page_exists(slug):
            picked.append(slug)
    return picked[:limit]


# ---------- ingest ----------

def ingest_file(opts: LLMOptions, filename: str, data: bytes) -> dict:
    text = extract_text(filename, data)
    with store.lock:
        source_name = store.save_raw(filename, data)
        return _ingest(opts, source_name, text)


def ingest_text(opts: LLMOptions, title: str, text: str) -> dict:
    if not text.strip():
        raise InputError("내용이 비어 있습니다.")
    with store.lock:
        source_name = store.save_raw(f"{store.slugify(title)}.md", text.encode("utf-8"))
        return _ingest(opts, source_name, text)


def _ingest(opts: LLMOptions, source_name: str, text: str) -> dict:
    truncated = len(text) > settings.max_source_chars
    text = text[: settings.max_source_chars]

    related = _pick_pages(
        opts,
        INGEST_PICK_INSTR,
        f"# 새 원본 문서: {source_name}\n{text[:20000]}",
        settings.max_related_pages,
    )
    result = llm.complete_json(
        opts,
        INGEST_INSTR.format(schema=store.read_schema(), source=source_name, today=store.today()),
        f"# 위키 목차\n{store.read_index()}\n\n"
        f"# 갱신 대상 기존 페이지\n{_pages_context(related) or '(없음)'}\n\n"
        f"# 새 원본 문서: {source_name}\n{text}",
        INGEST_SCHEMA,
        "ingest",
    )

    created, updated = [], []
    for item in result["pages"]:
        slug = store.normalize_slug(item["slug"] or item["title"])
        if slug in created or slug in updated:
            continue
        old = store.get_page(slug)
        page = Page(
            slug=slug,
            title=item["title"].strip() or slug,
            type=item["type"],
            summary=item["summary"].strip(),
            body=item["content"].strip(),
            sources=sorted(set((old.sources if old else []) + [source_name])),
            updated=store.today(),
        )
        if old and slug not in related:
            # LLM이 본문을 보지 못한 기존 페이지 — 덮어쓰지 않고 뒤에 덧붙인다.
            page.title, page.type, page.summary = old.title, old.type, old.summary
            page.body = f"{old.body}\n\n## 추가 내용 ({source_name})\n\n{page.body}"
        store.write_page(page)
        (updated if old else created).append(slug)

    store.rebuild_index()
    details = list(result["log"])
    if created:
        details.append("생성: " + ", ".join(f"[[{s}]]" for s in created))
    if updated:
        details.append("수정: " + ", ".join(f"[[{s}]]" for s in updated))
    if truncated:
        details.append(f"원본이 길어 앞부분 {settings.max_source_chars:,}자만 반영함")
    details.append(f"모델: {opts.describe()}")
    store.append_log("ingest", f"{result['source_title']} ({source_name})", details)

    return {
        "source": source_name,
        "source_title": result["source_title"],
        "created": created,
        "updated": updated,
        "truncated": truncated,
        "log": result["log"],
        "model": opts.model,
        "effort": opts.effort,
    }


# ---------- query ----------

def query(opts: LLMOptions, question: str) -> dict:
    if not store.list_pages():
        return {
            "answer": "위키가 비어 있습니다. 먼저 문서를 추가해 주세요.",
            "pages": [],
            "model": opts.model,
            "effort": opts.effort,
        }
    slugs = _pick_pages(opts, QUERY_PICK_INSTR, f"# 질문\n{question}", settings.max_query_pages)
    answer = llm.complete_text(
        opts,
        QUERY_INSTR,
        f"# 참고 위키 페이지\n{_pages_context(slugs) or '(관련 페이지 없음)'}\n\n# 질문\n{question}",
    )
    store.append_log(
        "query",
        question,
        ["참고: " + (", ".join(f"[[{s}]]" for s in slugs) or "없음"), f"모델: {opts.describe()}"],
    )
    return {"answer": answer, "pages": slugs, "model": opts.model, "effort": opts.effort}


def save_answer(question: str, answer: str, title: str | None = None) -> dict:
    title = (title or question).strip()
    with store.lock:
        slug = store.unique_slug(store.normalize_slug(f"analysis-{title}"))
        page = Page(
            slug=slug,
            title=title,
            type="analysis",
            summary=question.strip()[:80],
            body=f"> 질문: {question.strip()}\n\n{answer.strip()}",
            updated=store.today(),
        )
        store.write_page(page)
        store.rebuild_index()
        store.append_log("save", title, [f"질의 결과를 [[{slug}]]로 저장"])
    return page.meta()


# ---------- lint ----------

def lint(opts: LLMOptions) -> dict:
    """점검 후 결과를 data/lint/<id>.json에 저장하고 그 레코드를 반환한다."""
    run_id, created_at = store.new_lint_run_id()
    started = time.monotonic()
    pages = store.list_pages()
    existing = {p.slug for p in pages}
    broken = [{"page": p.slug, "target": t} for p in pages for t in p.links if t not in existing]
    linked = {t for p in pages for t in p.links}
    orphans = [p.slug for p in pages if p.slug not in linked]

    issues, checked = [], 0
    if pages:
        blocks, size = [], 0
        for page in pages:
            block = f'<page slug="{page.slug}">\n{page.to_markdown()}</page>'
            if blocks and size + len(block) > settings.max_lint_chars:
                break
            blocks.append(block)
            size += len(block)
        checked = len(blocks)
        issues = llm.complete_json(opts, LINT_INSTR, "\n\n".join(blocks), LINT_SCHEMA, "lint")["issues"]

    record = {
        "schema_version": store.LINT_SCHEMA_VERSION,
        "id": run_id,
        "created_at": created_at,
        "duration_seconds": round(time.monotonic() - started, 1),
        "model": opts.model,
        "effort": opts.effort,
        "checked_pages": checked,
        "total_pages": len(pages),
        "counts": {"issues": len(issues), "broken_links": len(broken), "orphans": len(orphans)},
        "issues": [{"id": f"{run_id}-{n:03d}", **issue} for n, issue in enumerate(issues, 1)],
        "broken_links": broken,
        "orphans": orphans,
    }
    store.save_lint_run(record)
    store.append_log(
        "lint",
        f"페이지 {checked}/{len(pages)}개 점검",
        [
            f"LLM 지적 {len(issues)}건",
            f"깨진 링크 {len(broken)}건",
            f"고아 페이지 {len(orphans)}개",
            f"모델: {opts.describe()}",
            f"결과: lint/{run_id}.json",
        ],
    )
    return record
