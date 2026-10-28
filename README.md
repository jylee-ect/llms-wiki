# LLM Wiki (프로토타입)

Andrej Karpathy의 LLM Wiki 패턴을 구현한 프로토타입입니다. LLM(`gpt-6-luna`)이 원본 문서를 읽고 마크다운 위키를 직접 작성·갱신하며, 사람은 위키에 질문하거나 위키를 읽습니다.

- **backend/**: FastAPI. ingest / query / lint 로직과 파일 저장소
- **frontend/**: Streamlit. 질문, 문서 추가, 위키 탐색, 점검, 로그, 규칙 편집 화면
- **data/**: 위키 데이터 (첫 실행 시 자동 생성)

## 실행

백엔드와 프론트엔드를 **터미널 2개**에서 각각 실행합니다. 모든 명령은 프로젝트 루트(`llm_wiki/`)에서 실행합니다.
OpenAI API 키는 `GPT_API` 환경변수에서 읽습니다.

### 1. 최초 1회: 가상환경과 패키지 설치

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r backend\requirements.txt -r frontend\requirements.txt
```

### 2. 터미널 1 — 백엔드 (FastAPI)

```powershell
.\.venv\Scripts\activate
cd backend
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

- 서버 주소: http://127.0.0.1:8000
- API 문서(Swagger): http://127.0.0.1:8000/docs
- `--reload`: 코드를 수정하면 자동으로 재시작 (개발용)

### 3. 터미널 2 — 프론트엔드 (Streamlit)

```powershell
.\.venv\Scripts\activate
streamlit run frontend\app.py
```

- 브라우저에서 http://localhost:8501 이 자동으로 열립니다.
- 포트를 바꾸려면 `streamlit run frontend\app.py --server.port 8502`

### 참고

- **가상환경 활성화 없이** 실행하려면 `python` 대신 `.\.venv\Scripts\python.exe`를 쓰면 됩니다.
  ```powershell
  .\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --port 8000 --reload
  .\.venv\Scripts\python.exe -m streamlit run frontend\app.py
  ```
- PowerShell에서 `activate` 시 "스크립트를 실행할 수 없습니다" 오류가 나면 한 번만 실행:
  `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`
- **Git Bash / macOS / Linux**에서는 `source .venv/Scripts/activate` (macOS·Linux는 `source .venv/bin/activate`)로 활성화하고, 경로 구분자를 `/`로 바꿉니다.
- 서버 기본 모델을 바꿔서 실행하는 예 (PowerShell, `backend` 폴더에서):
  ```powershell
  $env:LLM_MODEL = "gpt-6-sol"; $env:LLM_REASONING_EFFORT = "low"
  uvicorn app.main:app --port 8000
  ```
- 프론트엔드가 다른 주소의 백엔드를 쓰게 하려면: `$env:BACKEND_URL = "http://서버주소:8000"; streamlit run frontend\app.py`
- 종료: 각 터미널에서 `Ctrl + C`
- `run_backend.ps1`, `run_frontend.ps1`은 위 명령을 묶어 둔 스크립트입니다.

## 모델 선택

Streamlit **사이드바**에서 모델과 reasoning effort를 고를 수 있습니다. 선택값은 질문, 문서 추가, 점검 요청에 함께 전달되고, 사용한 모델은 `log.md`에 기록됩니다.

| 모델 | 특징 | 지원 effort |
|---|---|---|
| `gpt-6-luna` (기본) | 가장 빠르고 저렴 | none, low, medium, high, xhigh, max |
| `gpt-6-sol` | 속도·비용·성능 균형 | none, low, medium, high, xhigh, max |
| `gpt-6.1-sol` | Sol 최신 버전 | low, medium, high, xhigh, max |

- effort가 높을수록 깊게 추론하지만 느리고 비쌉니다. 일상적인 작업은 `low`~`medium`, 길고 복잡한 문서를 수집하거나 점검할 때는 `high` 이상을 권장합니다.
- 실측 예시 (같은 질문): Sol·none 4.4초 / 6.1 Sol·high 9.1초 / Luna·max 27.3초
- 모델 목록은 `backend/app/config.py`의 `MODELS`에서 추가·수정합니다.
- API에서는 요청 본문에 `"model"`, `"effort"`를 넣습니다(파일 업로드는 form 필드). 생략하면 서버 기본값(`LLM_MODEL`, `LLM_REASONING_EFFORT`)을 씁니다.

## 데이터 구조 (DB 없음)

```
data/
├─ AGENTS.md        위키 작성 규칙(스키마). 사람이 편집 → LLM이 따름
├─ raw/             원본 문서. 수정하지 않음
├─ lint/<id>.json   점검 결과. 실행할 때마다 1파일 (추후 DB 이관 전제, docs/02_SDS.md 5.9)
└─ wiki/
   ├─ index.md      목차. 페이지 메타데이터로 자동 생성
   ├─ log.md        작업 이력 (append-only)
   └─ <slug>.md     위키 페이지 (frontmatter + 본문, [[slug]] 링크)
```

위키 자체가 저장소이므로 DB를 쓰지 않습니다. `data/` 폴더를 Obsidian으로 열어 보거나 git으로 버전 관리할 수 있습니다.

## 동작

| 동작 | API | 설명 |
|---|---|---|
| Ingest | `POST /ingest/file`, `POST /ingest/text` | ① 목차를 보고 갱신할 기존 페이지 선택 → ② 원본 + 기존 페이지를 주고 페이지 생성·갱신 (JSON 구조화 출력) → ③ index 재생성, log 기록 |
| Query | `POST /query` | ① 목차에서 관련 페이지 선택 → ② 그 페이지를 근거로 `[[slug]]` 인용과 함께 답변 |
| Save | `POST /query/save` | 좋은 답변을 `analysis` 페이지로 위키에 저장 |
| Lint | `POST /lint` | LLM: 모순·오래된 정보·빠진 페이지/링크·중복 / 코드: 깨진 링크·고아 페이지. 결과는 `data/lint/<id>.json`에 저장 |

조회용: `GET /health`, `/models`, `/pages`, `/pages/{slug}`, `/index`, `/log`, `/sources`, `/lint/runs`, `/lint/runs/{id}`, `GET·PUT /schema`

지원 형식: pdf, docx, txt, md, csv, json, html, xml, log (스캔 PDF는 OCR 미지원)

## 설정 (환경변수)

| 변수 | 기본값 | 설명 |
|---|---|---|
| `GPT_API` | — | OpenAI API 키 |
| `LLM_MODEL` | `gpt-6-luna` | 사용할 모델 |
| `LLM_REASONING_EFFORT` | `medium` | 추론 강도 (`low` / `medium` / `high`) |
| `WIKI_DATA_DIR` | `./data` | 데이터 폴더 |
| `MAX_SOURCE_CHARS` | `150000` | ingest 시 원본 반영 최대 글자 수 |
| `MAX_LINT_CHARS` | `200000` | lint 시 점검할 최대 분량 |
| `BACKEND_URL` | `http://localhost:8000` | (frontend) 백엔드 주소 |

## 한계 (프로토타입)

- 단일 프로세스·단일 사용자 전제입니다. 쓰기 작업은 프로세스 내 lock으로 직렬화합니다.
- 페이지가 수백 개를 넘으면 index.md만으로 페이지를 고르기 어려워집니다. 이때 임베딩 검색(벡터 DB)을 추가하는 것이 다음 단계입니다.
- 업로드한 문서 내용은 OpenAI API로 전송됩니다. 사내 문서를 넣기 전에 보안 정책을 확인하세요.
