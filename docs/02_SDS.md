# LLM Wiki — 소프트웨어 설계 명세서 (SDS)

| 항목 | 내용 |
|---|---|
| 문서 버전 | 1.1 (2026-10-28) — 점검 결과 JSON 저장 (5.9, 7.4, 9.2, 10.3) |
| 요구사항 | [01_SRS.md](01_SRS.md) |
| 원칙 | 이 문서만 보고 같은 동작의 코드를 다시 만들 수 있어야 한다. 프롬프트·스키마·파일 형식은 **원문 그대로** 싣는다 |

---

## 1. 아키텍처

```
┌──────────────────────────┐   HTTP/JSON    ┌───────────────────────────────────────────┐
│ frontend/app.py          │ ─────────────▶ │ backend/app/main.py  (FastAPI, :8000)      │
│ Streamlit (:8501)        │  requests      │   │                                        │
│ - 사이드바: 모델·effort  │  timeout 900s  │   ├─ wiki.py    ingest / query / lint      │
│ - 6개 탭                 │                │   │    ├─ llm.py      OpenAI Responses API ─┼──▶ OpenAI
└──────────────────────────┘                │   │    ├─ extract.py  파일 → 텍스트         │
                                            │   │    └─ store.py    파일 저장소           │
                                            │   ├─ config.py  설정·모델 카탈로그         │
                                            │   └─ errors.py  InputError / LLMError      │
                                            └──────────────────────┬────────────────────┘
                                                                   ▼
                                            data/ (AGENTS.md, raw/, lint/*.json, wiki/index.md, wiki/log.md, wiki/*.md)
```

계층별 책임:
- **main.py**: HTTP 경계만 담당한다. 요청 검증, `model`/`effort` 해석(`resolve_options`), 예외를 HTTP 상태 코드로 변환.
- **wiki.py**: 업무 로직. LLM 호출 순서와 결과를 위키에 반영하는 규칙.
- **store.py**: 파일 형식과 입출력. LLM을 모른다.
- **llm.py**: OpenAI 호출과 응답 검증. 위키를 모른다.

---

## 2. 기술 스택

개발·검증에 쓴 버전 (Python 3.12.10, Windows 11):

| 패키지 | 버전 | 용도 |
|---|---|---|
| fastapi | 0.162.0 | 백엔드 |
| uvicorn[standard] | 0.54.0 | ASGI 서버 |
| python-multipart | 0.0.32 | 파일 업로드 |
| openai | 3.37.0 | Responses API (`client.responses.create`, `response.output_text`) |
| pydantic | 2.14.1 | 요청 모델 |
| pypdf | 6.21.2 | PDF 텍스트 추출 |
| python-docx | 1.2.0 | DOCX 텍스트 추출 |
| streamlit | 1.66.1 | 프론트엔드 (`width="stretch"` 사용, `use_container_width`는 deprecated) |
| requests | 2.34.2 | 프론트엔드 → 백엔드 호출 |

`backend/requirements.txt`:
```
fastapi>=0.115
uvicorn[standard]>=0.30
openai>=3.0
python-multipart>=0.0.9
pypdf>=5.0
python-docx>=1.1
```

`frontend/requirements.txt`:
```
streamlit>=1.40
requests>=2.32
```

---

## 3. 디렉토리 구조

```
llm_wiki/
├─ backend/
│  ├─ requirements.txt
│  └─ app/
│     ├─ __init__.py            (빈 파일)
│     ├─ config.py              설정, MODELS 카탈로그
│     ├─ errors.py              InputError, LLMError
│     ├─ llm.py                 LLMOptions, resolve_options, complete_text, complete_json
│     ├─ extract.py             extract_text, SUPPORTED_EXTENSIONS
│     ├─ store.py               Page, slug 규칙, 페이지/목차/로그/규칙/원본 입출력, lock
│     ├─ wiki.py                프롬프트, JSON 스키마, ingest/query/save_answer/lint
│     ├─ main.py                FastAPI 앱, 엔드포인트
│     └─ default_schema.md      첫 실행 시 data/AGENTS.md로 복사되는 기본 작성 규칙
├─ frontend/
│  ├─ requirements.txt
│  └─ app.py                    Streamlit 앱 (단일 파일)
├─ data/                        실행 시 자동 생성 (git 제외)
├─ samples/                     시연용 샘플 문서 7개 + README
├─ docs/                        이 문서들
├─ run_backend.ps1, run_frontend.ps1
├─ .gitignore                   .venv/, __pycache__/, *.tmp, data/
└─ README.md
```

---

## 4. 설정 (config.py)

모든 값은 **모듈 import 시점**에 환경변수에서 읽는다. `ROOT = Path(__file__).resolve().parents[2]` (프로젝트 루트).

| 속성 | 환경변수 | 기본값 |
|---|---|---|
| `api_key` | `GPT_API` | 없음 (None) |
| `model` | `LLM_MODEL` | `gpt-6-luna` |
| `reasoning_effort` | `LLM_REASONING_EFFORT` | `medium` |
| `llm_timeout` | `LLM_TIMEOUT` | `600` (초, float) |
| `data_dir` | `WIKI_DATA_DIR` | `ROOT / "data"` |
| `max_source_chars` | `MAX_SOURCE_CHARS` | `150000` |
| `max_lint_chars` | `MAX_LINT_CHARS` | `200000` |
| `max_related_pages` | `MAX_RELATED_PAGES` | `8` |
| `max_query_pages` | `MAX_QUERY_PAGES` | `8` |
| `max_upload_bytes` | `MAX_UPLOAD_MB` | `20` → ×1024×1024 |

파생 속성(property): `raw_dir = data_dir/"raw"`, `wiki_dir = data_dir/"wiki"`, `lint_dir = data_dir/"lint"`, `schema_path = data_dir/"AGENTS.md"`.
모듈 끝에서 `settings = Settings()` 싱글턴을 만든다.

모델 카탈로그 (`MODELS`, 순서 유지):

```python
_ALL_EFFORTS = ["none", "low", "medium", "high", "xhigh", "max"]

MODELS = {
    "gpt-6-luna":  {"label": "GPT-6 Luna",  "description": "가장 빠르고 저렴. 일상적인 수집·질의에 적합", "efforts": _ALL_EFFORTS},
    "gpt-6-sol":   {"label": "GPT-6 Sol",   "description": "속도·비용·성능 균형",                     "efforts": _ALL_EFFORTS},
    "gpt-6.1-sol": {"label": "GPT-6.1 Sol", "description": "Sol 최신 버전. effort 'none' 미지원",      "efforts": _ALL_EFFORTS[1:]},
}
```

> `minimal`은 세 모델 모두 지원하지 않는다 (API가 400 반환). 지원 범위는 API에 직접 요청해서 확인했다.

---

## 5. 데이터 설계

### 5.1 파일 배치

```
data/
├─ AGENTS.md          작성 규칙. 없으면 default_schema.md를 복사해서 만든다
├─ raw/<원본파일명>   업로드 원본 (바이트 그대로)
├─ lint/<id>.json     점검 결과. 실행 1회당 1파일 (5.9)
└─ wiki/
   ├─ index.md        목차 (자동 생성, 직접 수정 금지)
   ├─ log.md          작업 로그 (append-only). 초기 내용: "# 작업 로그\n"
   └─ <slug>.md       위키 페이지
```

`index`, `log`는 예약 slug다. 페이지 목록에서 빼고, LLM이 이 slug를 쓰면 `page-` 접두어를 붙인다.

### 5.2 slug 규칙

```python
def slugify(text):
    s = re.sub(r"[^\w\s-]", "", text.strip().lower())   # \w는 유니코드 → 한글 유지
    s = re.sub(r"[\s_]+", "-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s[:80].strip("-") or "untitled"

def normalize_slug(text):
    s = slugify(text)
    return f"page-{s}" if s in {"index", "log"} else s
```

- 예: `"가디언 AC-100"` → `가디언-ac-100`, `"index"` → `page-index`
- 경로 구분자와 `.`이 모두 제거되므로 경로 조작이 불가능하다.
- API의 `GET /pages/{slug}`는 `slug == normalize_slug(slug)`일 때만 조회하고, 아니면 404를 반환한다.

### 5.3 위키 링크

```python
LINK_RE = re.compile(r"\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]")
```

- `[[slug]]`, `[[slug|표시명]]`, `[[slug#섹션]]`을 인식하고, 대상은 첫 그룹이다.
- `Page.links` = 본문에서 찾은 대상을 `normalize_slug`한 집합에서 자기 자신을 뺀 뒤 정렬한 것.
- 역링크 = 전체 페이지 중 `slug in p.links`인 페이지.

### 5.4 페이지 파일 형식

frontmatter의 **값은 JSON으로 인코딩**한다 (`json.dumps(v, ensure_ascii=False)`). JSON은 YAML의 부분집합이라 Obsidian 등에서도 읽힌다. 따로 YAML 파서가 필요 없다.

```markdown
---
title: "가디언 AC-100"
type: "entity"
summary: "한빛시큐어의 기업용 출입통제 시스템. 리더기·컨트롤러·GMS로 구성"
sources: ["01_출입통제시스템_개요.md", "07_물리보안_제로트러스트_백서.pdf"]
updated: "2026-10-26"
---

가디언 AC-100은 ... (출처: [[source-가디언-ac-100-개요]])

## 구성 요소
...
```

- 키 순서: `title, type, summary, sources, updated`. slug는 파일명이므로 frontmatter에 넣지 않는다.
- `type` ∈ `["source", "entity", "concept", "topic", "analysis"]`. 이 밖의 값은 읽을 때 `topic`으로 처리한다.
- 파싱: 텍스트가 `"---\n"`로 시작하면 다음 `"\n---\n"`까지를 frontmatter로 본다. 각 줄을 첫 `:`에서 나눠 값을 `json.loads`하고, 실패하면 문자열 그대로 둔다. 나머지를 `strip()`한 것이 본문이다.
- 직렬화: `f"---\n{front}\n---\n\n{body.strip()}\n"`
- 날짜는 `YYYY-MM-DD`, 시각은 `YYYY-MM-DD HH:MM` (로컬 시간).

`Page` dataclass:

```python
@dataclass
class Page:
    slug: str; title: str; type: str; summary: str; body: str
    sources: list[str] = field(default_factory=list)
    updated: str = ""
    links (property)        # 5.3
    meta() -> dict          # slug, title, type, summary, sources, updated
    to_markdown() -> str    # 위 형식
```

### 5.5 목차 (index.md) 형식

`rebuild_index()`는 모든 페이지 메타데이터로 목차를 **매번 처음부터** 다시 만든다. LLM이 목차를 직접 쓰지 않는다.

```markdown
# 위키 목차

> 자동 생성 — 직접 수정하지 마세요. 페이지 12개 · 원본 7개 · 갱신 2026-10-26 22:10

## 원본 요약 (source)

- [[source-가디언-ac-100-개요]] **가디언 AC-100 출입통제 시스템 개요** — 구성 요소, 인증 방식, ...

## 개체 (사람·조직·제품·시스템) (entity)

- [[가디언-ac-100]] **가디언 AC-100** — ...
```

- 그룹 순서는 `PAGE_TYPES` 순서를 따르고, 빈 그룹은 생략한다. 그룹 안에서는 제목순으로 정렬한다.
- 그룹 제목 라벨(`TYPE_LABELS`): source=`원본 요약`, entity=`개체 (사람·조직·제품·시스템)`, concept=`개념`, topic=`주제 종합`, analysis=`분석·질의 결과`

### 5.6 로그 (log.md) 형식

```markdown
# 작업 로그

## [2026-10-26 22:01] ingest | 가디언 AC-100 출입통제 시스템 개요 (01_출입통제시스템_개요.md)

- (LLM이 반환한 log 문장들)
- 생성: [[a]], [[b]]
- 수정: [[c]]
- 원본이 길어 앞부분 150,000자만 반영함      ← 잘렸을 때만
- 모델: gpt-6-luna (effort: medium)
```

- `append_log(operation, title, details)`는 `"\n## [{now}] {operation} | {title}\n"`을 쓰고, details가 있으면 `"\n" + "\n".join("- " + d) + "\n"`을 덧붙인다.
- operation 값: `ingest`, `query`, `save`, `lint`, `schema`

### 5.7 원본 파일명 규칙

```python
name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", Path(filename).name).strip(" .") or "source.txt"
# 같은 이름이 있으면 stem-2.ext, stem-3.ext ...
```

텍스트 직접 입력은 `f"{slugify(title)}.md"`라는 이름으로 UTF-8 저장한다.

### 5.8 기본 작성 규칙 (default_schema.md 원문)

```markdown
# 위키 작성 규칙 (Schema)

이 파일은 LLM이 위키를 작성·관리할 때 따르는 규칙입니다. 사람이 자유롭게 고쳐서 위키의 방향을 조정합니다.

## 목적

여러 원본 문서에서 얻은 지식을 주제별 위키 페이지로 축적한다.
새 문서가 들어올 때마다 기존 페이지를 보강하고, 페이지 간 연결을 늘려 간다.

## 페이지 유형

- `source`: 원본 문서 1개당 1페이지. 문서의 핵심 내용, 주요 주장, 수치, 결론을 요약한다.
- `entity`: 사람, 조직, 제품, 시스템 등 고유한 대상.
- `concept`: 용어, 기술, 방법론 등 개념.
- `topic`: 여러 원본·개념을 가로지르는 주제 종합.
- `analysis`: 질의 응답 결과를 위키에 보관한 페이지.

## 작성 규칙

- 언어: 한국어. 고유명사·전문 용어는 원어를 병기할 수 있다.
- 본문은 짧은 요약 문단으로 시작하고, `##` 소제목으로 구분한다. 제목(`#`)과 frontmatter는 시스템이 관리하므로 쓰지 않는다.
- 다른 페이지는 `[[slug]]` 형식으로 링크한다. slug는 소문자·하이픈 형식 (예: `access-control`, `에스원-보안시스템`).
- 사실 문장에는 근거가 된 원본 요약 페이지를 `(출처: [[source-...]])` 형식으로 붙인다.
- 원본에 없는 내용을 지어내지 않는다. 추정은 "추정"이라고 명시한다.
- 새 정보가 기존 내용과 충돌하면 덮어쓰지 말고 `## 상충되는 정보` 섹션에 양쪽을 출처와 함께 기록한다.
- 한 페이지는 한 대상/개념에 집중한다. 길어지면 하위 주제를 별도 페이지로 분리하고 링크한다.
```

### 5.9 점검 결과 (lint/<id>.json) 형식

추후 DB로 옮길 것을 전제로 한 형식이다. 실행 1회가 파일 1개(레코드 1건)다.

- **id**: `YYYYMMDD-HHMMSS-<6자리 hex>`. 앞부분이 실행 시작 시각(로컬 시간)이라 파일명순 정렬이 곧 시간순이다. 뒤의 hex는 `secrets.token_hex(3)`로, 같은 초에 두 번 실행해도 충돌하지 않게 한다. 검증 정규식: `^\d{8}-\d{6}-[0-9a-f]{6}$`
- **created_at**: 실행 **시작** 시각. `datetime.now().astimezone().isoformat(timespec="seconds")` (예: `2026-10-28T22:45:11+09:00`)
- **duration_seconds**: 시작부터 레코드를 만들 때까지 걸린 시간 (`time.monotonic()` 차이, 소수 1자리)
- **issues[].id**: `f"{run_id}-{n:03d}"` (n은 1부터). 지적 사항 원래 필드 앞에 붙인다
- 직렬화: `json.dumps(record, ensure_ascii=False, indent=2) + "\n"`, UTF-8, atomic write

```json
{
  "schema_version": 1,
  "id": "20261028-224511-078905",
  "created_at": "2026-10-28T22:45:11+09:00",
  "duration_seconds": 10.1,
  "model": "gpt-6-sol",
  "effort": "low",
  "checked_pages": 29,
  "total_pages": 29,
  "counts": {"issues": 4, "broken_links": 4, "orphans": 1},
  "issues": [
    {
      "id": "20261028-224511-078905-001",
      "kind": "contradiction",
      "pages": ["security-incident-response", "vision-video-retention-and-export"],
      "description": "보안사고 대응 페이지는 영상을 90일 안에 보존 처리해야 한다고 단정한다. 그러나 ...",
      "suggestion": "..."
    }
  ],
  "broken_links": [{"page": "gms", "target": "source-pangyo-research-lab-equipment"}],
  "orphans": ["hanbit-secure"]
}
```

키 순서는 위와 같다. 요약 목록(`list_lint_runs`)은 레코드에서 `LINT_SUMMARY_KEYS = ("id", "created_at", "model", "effort", "checked_pages", "total_pages", "counts")`만 뽑는다.

DB 이관 시 테이블 대응 (참고):

| 테이블 | 키 | 컬럼 출처 |
|---|---|---|
| `lint_runs` | `id` (PK) | schema_version, created_at, duration_seconds, model, effort, checked_pages, total_pages, counts.* |
| `lint_issues` | `id` (PK), `run_id` (FK) | kind, description, suggestion. 이후 해결 상태(status, resolved_at 등) 컬럼 추가 |
| `lint_issue_pages` | (`issue_id`, `slug`) | issues[].pages |
| `lint_broken_links` | (`run_id`, `page`, `target`) | broken_links[] |
| `lint_orphans` | (`run_id`, `slug`) | orphans[] |

형식을 바꾸면 `LINT_SCHEMA_VERSION`을 올린다. 이관 스크립트는 버전별로 분기한다.

---

## 6. 모듈 설계

### 6.1 errors.py

```python
class InputError(ValueError):   # 사용자 입력 문제 → HTTP 400
class LLMError(RuntimeError):   # LLM 호출 실패 → HTTP 502
```

### 6.2 llm.py

```python
@dataclass(frozen=True)
class LLMOptions:
    model: str
    effort: str
    def describe(self) -> str: return f"{self.model} (effort: {self.effort})"

def resolve_options(model=None, effort=None) -> LLMOptions
    # 빈 값이면 settings 기본값을 쓴다
    # model ∉ MODELS             → InputError("지원하지 않는 모델입니다: {model} (지원: a, b, c)")
    # effort ∉ MODELS[model]     → InputError("{model}은(는) effort '{effort}'를 지원하지 않습니다 (지원: ...)")

def complete_text(opts, instructions, input) -> str     # response.output_text.strip()
def complete_json(opts, instructions, input, schema, name) -> dict
```

공통 호출 `_create(opts, instructions, input, **kwargs)`:

```python
client.responses.create(
    model=opts.model,
    instructions=instructions,     # 시스템 지시문
    input=input,                   # 사용자 입력 (문자열)
    reasoning={"effort": opts.effort},
    **kwargs,                      # complete_json은 text=... 를 넘긴다
)
```

- 클라이언트는 처음 호출할 때 한 번만 만든다: `OpenAI(api_key=settings.api_key, timeout=settings.llm_timeout)`. 키가 없으면 `LLMError("GPT_API 환경변수가 설정되어 있지 않습니다.")`.
- `OpenAIError`가 나면 `LLMError(f"LLM 호출 실패: {e}")`로 바꾼다.
- `response.status == "incomplete"`이면 `LLMError("LLM 응답이 중간에 끊겼습니다 (reason: {incomplete_details.reason}). 입력 크기를 줄여 보세요.")`.
- `complete_json`은 `text={"format": {"type": "json_schema", "name": name, "schema": schema, "strict": True}}`로 호출하고 `json.loads(output_text)`한다. 실패하면 `LLMError("LLM이 올바른 JSON을 반환하지 않았습니다.")`.
- temperature 등 샘플링 파라미터는 쓰지 않는다 (추론 모델에서 effort가 none이 아니면 지원하지 않음).

### 6.3 extract.py

| 확장자 | 처리 |
|---|---|
| `.pdf` | `pypdf.PdfReader`. 페이지마다 `f"[p.{i}]\n{page.extract_text() or ''}"`를 만들어 `"\n\n"`으로 연결 |
| `.docx` | `docx.Document`. 비어 있지 않은 문단 텍스트 + 표의 각 행을 `" \| "`로 이어 붙인 줄 → `"\n"` 연결 |
| `TEXT_EXTENSIONS` = `.txt .md .markdown .csv .json .html .htm .xml .log` | `utf-8-sig` → `cp949` 순서로 디코딩하고, 둘 다 실패하면 `utf-8 errors="replace"` |
| 그 밖 | `InputError("지원하지 않는 파일 형식입니다: {ext} (지원: ...)")` |

추출 결과가 공백뿐이면 `InputError("문서에서 텍스트를 추출하지 못했습니다. (스캔 PDF는 OCR이 필요합니다)")`.
`SUPPORTED_EXTENSIONS = TEXT_EXTENSIONS | {".pdf", ".docx"}`. pypdf와 docx는 함수 안에서 import한다.

### 6.4 store.py

| 함수 | 설명 |
|---|---|
| `init()` | raw/, wiki/, lint/ 생성. AGENTS.md, log.md, index.md가 없으면 만든다 |
| `page_exists(slug)` | 예약 slug가 아니고 파일이 있으면 True |
| `get_page(slug)` → `Page \| None` | |
| `list_pages()` → `list[Page]` | `wiki/*.md`를 파일명순으로 읽는다. 예약 slug는 뺀다 |
| `write_page(page)` | lock을 잡고 atomic write |
| `unique_slug(base)` | `base`, `base-2`, `base-3` ... 중 없는 것 |
| `backlinks(slug, pages=None)` | |
| `rebuild_index()` | 5.5 |
| `read_index()`, `read_log()` | 파일이 없으면 `""` |
| `append_log(operation, title, details=None)` | 5.6, lock |
| `read_schema()`, `write_schema(content)` | |
| `save_raw(filename, data)` → 저장된 파일명 | 5.7 |
| `list_sources()` → `[{name, size, added}]` | raw/ 파일 목록, `added`는 mtime |
| `new_lint_run_id()` → `(id, created_at)` | 5.9의 id와 시작 시각 |
| `save_lint_run(record)` | lock, lint/ 생성 후 `<id>.json` atomic write |
| `get_lint_run(run_id)` → `dict \| None` | id 정규식이 안 맞거나 파일이 없으면 None |
| `list_lint_runs()` → `list[dict]` | `lint/*.json`을 파일명 역순(최신순)으로 읽어 요약 키만 반환. JSON이 깨진 파일은 건너뜀 |
| `now()`, `today()` | |

- `lock = threading.RLock()`. 재진입 가능해야 한다 (ingest가 lock을 잡은 상태에서 write_page, append_log가 다시 잡는다).
- atomic write: `path.with_suffix(path.suffix + ".tmp")`에 UTF-8로 쓴 뒤 `tmp.replace(path)`.
- 모든 파일 입출력은 `encoding="utf-8"`로 한다 (Windows 기본 인코딩 cp949 회피).

### 6.5 wiki.py

공개 함수 (모두 첫 인자가 `opts: LLMOptions`, `save_answer`만 예외):

```python
ingest_file(opts, filename, data: bytes) -> dict
ingest_text(opts, title, text) -> dict
query(opts, question) -> dict
save_answer(question, answer, title=None) -> dict    # LLM 호출 없음
lint(opts) -> dict
```

내부 함수:

```python
_pages_context(slugs) -> str
    # 각 페이지를 '<page slug="{slug}">\n{page.to_markdown()}</page>'로 감싸 "\n\n"으로 연결

_pick_pages(opts, instructions, context, limit) -> list[str]
    # 페이지가 없으면 [] (LLM 호출 안 함)
    # input = f"# 위키 목차\n{read_index()}\n\n{context}"
    # instructions.format(limit=limit), PICK_SCHEMA
    # 결과 slug를 normalize하고, 존재하는 것만 중복 없이 순서대로 남긴 뒤 limit개로 자른다
```

---

## 7. 처리 흐름

### 7.1 Ingest

```
ingest_file(opts, filename, data)
  text = extract_text(filename, data)              ← lock 밖에서 (실패하면 원본을 저장하지 않음)
  with lock:
    source_name = save_raw(filename, data)
    _ingest(opts, source_name, text)

_ingest(opts, source_name, text)
  1. truncated = len(text) > MAX_SOURCE_CHARS;  text = text[:MAX_SOURCE_CHARS]
  2. related = _pick_pages(opts, INGEST_PICK_INSTR,
                 f"# 새 원본 문서: {source_name}\n{text[:20000]}", MAX_RELATED_PAGES)
  3. result = complete_json(opts,
                 INGEST_INSTR.format(schema=read_schema(), source=source_name, today=today()),
                 f"# 위키 목차\n{read_index()}\n\n"
                 f"# 갱신 대상 기존 페이지\n{_pages_context(related) or '(없음)'}\n\n"
                 f"# 새 원본 문서: {source_name}\n{text}",
                 INGEST_SCHEMA, "ingest")
  4. for item in result.pages:
       slug = normalize_slug(item.slug or item.title)
       이미 이번 작업에서 처리한 slug면 건너뜀
       old = get_page(slug)
       page = Page(slug, title=item.title.strip() or slug, type=item.type,
                   summary=item.summary.strip(), body=item.content.strip(),
                   sources=sorted(set(old.sources + [source_name])), updated=today())
       if old and slug not in related:          ← LLM이 본문을 못 본 기존 페이지
           page.title/type/summary = old 값 유지
           page.body = f"{old.body}\n\n## 추가 내용 ({source_name})\n\n{새 본문}"
       write_page(page);  old 있으면 updated, 없으면 created에 추가
  5. rebuild_index()
  6. append_log("ingest", f"{source_title} ({source_name})",
                result.log + [생성..., 수정..., 잘림..., f"모델: {opts.describe()}"])
  7. return {source, source_title, created, updated, truncated, log, model, effort}
```

설계 포인트:
- **두 단계 호출**: 1단계에서 목차만 보고 관련 페이지를 고르고, 2단계에서 그 페이지 본문만 넘긴다. 위키 전체를 넣지 않으므로 페이지가 늘어도 입력 크기가 제한된다.
- **덮어쓰기 방지**: 2단계에서 본문을 넘기지 않은 페이지가 반환되면 덧붙인다 (FR-ING-07).
- **목차는 코드가 만든다**: LLM 출력의 summary로 재생성하므로 목차 형식이 항상 일정하다.
- ingest 전체를 lock으로 감싸므로 동시에 들어온 ingest는 순서대로 처리된다.

### 7.2 Query

```
query(opts, question)
  페이지가 없으면 → {"answer": "위키가 비어 있습니다. 먼저 문서를 추가해 주세요.", "pages": [], model, effort}
  slugs = _pick_pages(opts, QUERY_PICK_INSTR, f"# 질문\n{question}", MAX_QUERY_PAGES)
  answer = complete_text(opts, QUERY_INSTR,
             f"# 참고 위키 페이지\n{_pages_context(slugs) or '(관련 페이지 없음)'}\n\n# 질문\n{question}")
  append_log("query", question, ["참고: [[a]], [[b]]" 또는 "참고: 없음", f"모델: {opts.describe()}"])
  return {answer, pages: slugs, model, effort}
```

### 7.3 Save answer

```
save_answer(question, answer, title=None)
  title = (title or question).strip()
  with lock:
    slug = unique_slug(normalize_slug(f"analysis-{title}"))
    Page(slug, title, "analysis", summary=question.strip()[:80],
         body=f"> 질문: {question.strip()}\n\n{answer.strip()}", sources=[], updated=today())
    write_page → rebuild_index → append_log("save", title, [f"질의 결과를 [[{slug}]]로 저장"])
  return page.meta()
```

### 7.4 Lint

```
lint(opts)
  run_id, created_at = new_lint_run_id();  started = time.monotonic()
  pages = list_pages();  existing = {slug}
  broken  = [{"page": p.slug, "target": t} for p in pages for t in p.links if t not in existing]
  orphans = [p.slug for p in pages if p.slug not in (모든 페이지 links의 합집합)]
  페이지가 있으면:
    블록 = '<page slug="..">\n{to_markdown()}</page>'를 순서대로 쌓다가
           (이미 블록이 하나 이상 있고) 누적 길이가 MAX_LINT_CHARS를 넘으면 중단
    issues = complete_json(opts, LINT_INSTR, "\n\n".join(블록), LINT_SCHEMA, "lint")["issues"]
  record = 5.9 형식 (issues마다 id 부여, duration_seconds = monotonic 차이)
  save_lint_run(record)
  append_log("lint", f"페이지 {checked}/{total}개 점검",
             [f"LLM 지적 {n}건", f"깨진 링크 {n}건", f"고아 페이지 {n}개", f"모델: ...",
              f"결과: lint/{run_id}.json"])
  return record
```

LLM 호출이 실패하면 예외가 그대로 올라가므로 레코드는 저장되지 않는다.

---

## 8. 프롬프트와 JSON 스키마 (원문)

`{...}`는 `str.format`으로 채우는 자리다. 작성 규칙 본문은 `format`의 **값**으로 들어가므로 그 안에 `{}`가 있어도 문제없다.

### 8.1 INGEST_PICK_INSTR

```
너는 위키 관리자다. 새 원본 문서가 들어왔다.
위키 목차를 보고, 이 문서의 내용으로 보강하거나 수정해야 할 기존 페이지의 slug를 골라라.
관련성이 높은 순서로 최대 {limit}개. 관련 페이지가 없으면 빈 배열.
```

### 8.2 INGEST_INSTR

```
너는 위키 관리자다. 새 원본 문서를 읽고 위키에 통합한다.
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
오늘 날짜: {today}
```

### 8.3 QUERY_PICK_INSTR

```
너는 위키 검색기다. 위키 목차를 보고 질문에 답하는 데 필요한 페이지의 slug를 골라라.
관련성이 높은 순서로 최대 {limit}개. 관련 페이지가 없으면 빈 배열.
```

### 8.4 QUERY_INSTR (format 없음)

```
너는 사내 지식 위키를 기반으로 답하는 어시스턴트다.
제공된 위키 페이지만 근거로 질문에 답한다.

- 답변의 각 주장 뒤에 근거 페이지를 `[[slug]]` 형식으로 표시한다.
- 위키에 근거가 없거나 부족하면 그렇다고 분명히 말하고, 어떤 자료를 추가하면 좋을지 제안한다.
- 마크다운으로 간결하게 쓴다. 필요하면 표를 사용한다.
- 답변 언어는 질문의 언어를 따른다.
```

### 8.5 LINT_INSTR (format 없음)

```
너는 위키 품질 점검자다. 아래 위키 페이지들을 읽고 문제를 찾아라.

점검 항목:
- contradiction: 페이지 간 서로 모순되는 사실
- stale: 더 새로운 원본에 의해 대체되었을 가능성이 있는 오래된 주장
- missing_page: 여러 곳에서 언급되지만 자체 페이지가 없는 중요한 개념·개체
- missing_link: 서로 연결되어야 하는데 링크가 없는 페이지
- duplicate: 같은 대상을 다루는 중복 페이지
- other: 그 밖에 출처 누락 등 품질 문제

`pages`에는 관련 페이지 slug를 넣는다. 설명과 제안은 한국어로 구체적으로 쓴다.
문제가 없으면 빈 배열을 반환한다.
```

### 8.6 JSON 스키마

strict 모드이므로 **모든 속성을 `required`에 넣고 `additionalProperties: false`** 로 둔다.

```python
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
                    "kind": {"type": "string",
                             "enum": ["contradiction", "stale", "missing_page", "missing_link", "duplicate", "other"]},
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
```

---

## 9. API 명세

- 앱: `FastAPI(title="LLM Wiki API", version="0.1.0", lifespan=lifespan)`. lifespan 시작 시 `store.init()`을 호출한다.
- LLM을 호출하는 엔드포인트는 **동기 `def`** 로 정의한다. FastAPI가 스레드풀에서 실행하므로 오래 걸리는 LLM 호출이 이벤트 루프를 막지 않는다.
- 오류 응답 형식: `{"detail": "메시지"}`

### 9.1 요청 모델 (pydantic)

```python
class LLMChoice(BaseModel):        # 요청별 모델/effort. 생략하면 서버 기본값
    model: str | None = None
    effort: str | None = None

class TextIngest(LLMChoice):
    title: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1)

class QueryRequest(LLMChoice):
    question: str = Field(min_length=1, max_length=4000)

class SaveAnswerRequest(BaseModel):
    question: str = Field(min_length=1)
    answer: str = Field(min_length=1)
    title: str | None = None

class SchemaUpdate(BaseModel):
    content: str = Field(min_length=1)
```

### 9.2 엔드포인트

| 메서드·경로 | 요청 | 응답 (200) |
|---|---|---|
| `GET /health` | — | `{status:"ok", model, effort, api_key_configured: bool, pages: int, sources: int, supported_extensions: [".csv", ...]}` |
| `GET /models` | — | `{default_model, default_effort, models: [{id, label, description, efforts}]}` |
| `GET /pages` | — | `[Page.meta()]` |
| `GET /pages/{slug}` | — | `{...meta, body, links: [slug], backlinks: [slug]}` · 404 |
| `GET /index` | — | `{content}` |
| `GET /log` | — | `{content}` |
| `GET /sources` | — | `[{name, size, added}]` |
| `GET /schema` | — | `{content}` |
| `PUT /schema` | `SchemaUpdate` | `{content}` + 로그 `schema \| 위키 작성 규칙 수정` |
| `POST /ingest/file` | multipart: `file` (UploadFile), form `model`, `effort` (선택) | ingest 결과 (7.1의 7번) · 400 / 413 / 502 |
| `POST /ingest/text` | `TextIngest` | ingest 결과 |
| `POST /query` | `QueryRequest` | `{answer, pages, model, effort}` |
| `POST /query/save` | `SaveAnswerRequest` | `Page.meta()` |
| `POST /lint` | `LLMChoice` (본문 생략 가능) | 5.9 레코드 (저장된 것과 동일) |
| `GET /lint/runs` | — | `[{id, created_at, model, effort, checked_pages, total_pages, counts}]` 최신순. 기록이 없으면 `[]` |
| `GET /lint/runs/{run_id}` | — | 5.9 레코드 · 404 `"점검 기록이 없습니다: {run_id}"` |

`/ingest/file` 처리 순서: `resolve_options` → `file.file.read(max_upload_bytes + 1)` → 크기 초과 시 413 → `wiki.ingest_file(opts, file.filename or "upload.txt", data)`.

### 9.3 오류 매핑

| 예외 | 상태 코드 | 처리 |
|---|---|---|
| `InputError` | 400 | `@app.exception_handler(InputError)` |
| `LLMError` | 502 | `@app.exception_handler(LLMError)` |
| 페이지 없음 | 404 | `HTTPException` |
| 업로드 크기 초과 | 413 | `HTTPException("파일이 너무 큽니다.")` |
| pydantic 검증 실패 | 422 | FastAPI 기본 |

---

## 10. 프론트엔드 설계 (frontend/app.py)

### 10.1 상수와 헬퍼

```python
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000").rstrip("/")
LLM_TIMEOUT = 900
TYPE_LABELS = {"source": "원본 요약", "entity": "개체", "concept": "개념", "topic": "주제", "analysis": "분석"}
LINK_RE = re.compile(r"\[\[([^\]|#]+)(?:\|([^\]]*))?\]\]")
EFFORT_HELP = {
    "none": "추론 없음 · 가장 빠르고 저렴", "low": "가벼운 추론 · 빠름",
    "medium": "기본값 · 속도와 품질 균형", "high": "깊은 추론 · 복잡한 문서에 적합",
    "xhigh": "매우 깊은 추론 · 느림", "max": "최대 추론 · 가장 느리고 비쌈",
}
st.set_page_config(page_title="LLM Wiki", page_icon="📚", layout="wide")
```

- `api(method, path, timeout=30, **kwargs)`: `requests.request`로 호출한다. 연결 실패나 `not response.ok`이면 `st.error`로 보여주고 `None`을 반환한다. 오류 메시지는 응답 JSON의 `detail`을 쓰고, JSON이 아니면 본문 텍스트를 쓴다.
- `render_links(md)`: `[[slug|표시명]]` → `` `📄 표시명` ``, `[[slug]]` → `` `📄 slug` ``
- `open_page(slug)`: 버튼 `on_click` 콜백. `session_state["selected_page"] = slug`, `session_state["jump_to_wiki"] = True`. Streamlit은 탭을 코드로 바꿀 수 없으므로, 다음 렌더링에서 `st.toast("'위키' 탭에서 `slug` 페이지를 열었습니다.")`로 알린다.

### 10.2 화면 흐름

1. `GET /health`(timeout 5)와 `GET /models`를 호출한다. 하나라도 실패하면 `st.info("백엔드를 먼저 실행하세요 (README.md의 '실행' 참고)")`를 보여주고 `st.stop()`.
2. **사이드바**: 제목·설명, `st.metric` 2개(위키 페이지, 원본 문서), 키 미설정 경고, `##### 모델 설정`, 모델 `selectbox(key="model", format_func=label)`, 설명 caption, effort `select_slider(key="effort")`, `EFFORT_HELP` caption, divider, 새로고침 버튼, 백엔드 주소.
   - 위젯을 그리기 **전에** `session_state["model"]`이 목록에 없으면 기본 모델(없으면 첫 모델)로, `session_state["effort"]`가 현재 모델의 efforts에 없으면 기본 effort(없으면 `efforts[len//2]`)로 설정한다.
   - `llm_choice = {"model": model, "effort": effort}`를 모든 LLM 요청에 넣는다.
3. `st.tabs(["💬 질문", "📥 문서 추가", "📖 위키", "🩺 점검", "📜 로그", "⚙️ 규칙"])`

### 10.3 탭별 동작

| 탭 | 동작 |
|---|---|
| 질문 | `session_state["messages"]` 목록 `{role, content, pages?, question?, model?, effort?, saved?}`을 `st.chat_message`로 그린다. 어시스턴트 메시지에는 `🤖 {label} · effort {effort}` caption, "참고한 페이지 N개" expander(slug 버튼 → `open_page`), 저장 버튼(`POST /query/save` 후 `saved=slug`, rerun) 또는 "✅ 위키에 저장됨". `st.chat_input` → 사용자 메시지 추가 → spinner와 함께 `POST /query {question, **llm_choice}` → 어시스턴트 메시지 추가 → `st.rerun()`. 메시지가 있으면 "대화 지우기" 버튼 |
| 문서 추가 | 사용 모델 caption. `st.file_uploader(type=health 확장자에서 '.' 제거, accept_multiple_files=True)`. "위키에 반영" 버튼을 누르면 파일마다 `st.status`를 띄우고 `POST /ingest/file`(files + `data=llm_choice`)을 호출해 제목, log 목록, 생성·수정 수, 잘림 경고를 보여준다. expander 안의 `st.form(clear_on_submit=True)`에 제목·내용을 입력하면 `POST /ingest/text`. 아래에 `GET /sources`를 `st.dataframe`으로 표시 |
| 위키 | 페이지가 없으면 안내. 있으면 `columns([1, 3])`. 왼쪽: 검색어, 유형 multiselect, 필터 결과 `st.radio(key="selected_page", format_func="[유형] 제목")`. 선택된 페이지가 필터 결과에 없으면 목록 맨 앞에 넣고, 선택이 없거나 잘못됐으면 첫 항목으로. 오른쪽: `## 제목`, caption(slug · 유형 · 갱신일 · 원본), `render_links(body)`, divider, "연결된 페이지"/"이 페이지를 참조하는 페이지" 버튼(4열, 없는 slug는 `⚠️ slug (없음)` 비활성). 아래에 "목차 원문 (index.md)" expander(`st.code(language="markdown")`) |
| 점검 | 사용 모델 caption. "점검 실행" → `POST /lint json=llm_choice`가 성공하면 `session_state["lint_run_id"] = result["id"]`. 이어서 `GET /lint/runs`를 호출하고, 비어 있으면 `st.info("아직 점검 기록이 없습니다.")`. 있으면 `session_state["lint_run_id"]`가 목록에 없을 때 최신 id로 설정한 뒤 `st.selectbox("점검 기록 (최신순)", key="lint_run_id")`를 그린다. 라벨은 `"YYYY-MM-DD HH:MM · {모델 label}({effort}) · 지적 n · 깨진 링크 n · 고아 n"`. 선택한 id로 `GET /lint/runs/{id}`. 결과 위에 `columns([4, 1])`: caption `` 저장 위치: `data/lint/{id}.json` · 소요 {duration_seconds}초 `` + `st.download_button("JSON 다운로드", file_name=f"lint-{id}.json", mime="application/json")`. 그 아래 metric 3개, 부분 점검 경고, 문제마다 `st.container(border=True)`(`` **`kind`** — 설명 ``, `💡 제안`, 관련 페이지), 깨진 링크 dataframe, 고아 페이지 목록 |
| 로그 | `GET /log`를 `render_links` 후 `st.markdown` |
| 규칙 | `GET /schema`를 `st.form` 안의 `text_area(height=500)`에 넣고, 저장하면 `PUT /schema` |

- 버튼 key는 화면 안에서 겹치지 않게 만든다: `ref-{i}-{slug}`, `save-{i}`, `nav-{label}-{target}`
- 너비는 `width="stretch"`를 쓴다.

---

## 11. 보안·운영 고려

- 업로드 문서는 OpenAI로 전송된다. 사내 문서를 넣기 전에 보안 정책을 확인해야 한다.
- 인증이 없으므로 `127.0.0.1`에만 바인딩한다. 외부에 공개하면 안 된다.
- lock은 프로세스 안에서만 동작한다. uvicorn worker를 여러 개 띄우면 안 된다.
- 다음 단계 후보: 페이지가 수백 개를 넘으면 벡터 검색 추가, 다중 사용자를 지원하려면 DB와 작업 큐, lint 결과 자동 수정, OCR.

---

## 12. 실행

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r backend\requirements.txt -r frontend\requirements.txt

# 터미널 1
cd backend
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

# 터미널 2 (프로젝트 루트)
streamlit run frontend\app.py
```
