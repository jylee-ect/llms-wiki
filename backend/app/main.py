from contextlib import asynccontextmanager

from fastapi import FastAPI, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from . import store, wiki
from .config import MODELS, settings
from .errors import InputError, LLMError
from .extract import SUPPORTED_EXTENSIONS
from .llm import resolve_options


@asynccontextmanager
async def lifespan(app: FastAPI):
    store.init()
    yield


app = FastAPI(title="LLM Wiki API", version="0.1.0", lifespan=lifespan)


@app.exception_handler(LLMError)
async def llm_error_handler(request: Request, exc: LLMError):
    return JSONResponse(status_code=502, content={"detail": str(exc)})


@app.exception_handler(InputError)
async def input_error_handler(request: Request, exc: InputError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


class LLMChoice(BaseModel):
    """요청별 모델/effort. 생략하면 서버 기본값."""

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


@app.get("/health")
def health():
    return {
        "status": "ok",
        "model": settings.model,
        "effort": settings.reasoning_effort,
        "api_key_configured": bool(settings.api_key),
        "pages": len(store.list_pages()),
        "sources": len(store.list_sources()),
        "supported_extensions": sorted(SUPPORTED_EXTENSIONS),
    }


@app.get("/models")
def list_models():
    return {
        "default_model": settings.model,
        "default_effort": settings.reasoning_effort,
        "models": [{"id": model_id, **info} for model_id, info in MODELS.items()],
    }


@app.get("/pages")
def list_pages():
    return [p.meta() for p in store.list_pages()]


@app.get("/pages/{slug}")
def get_page(slug: str):
    page = store.get_page(slug) if slug == store.normalize_slug(slug) else None
    if page is None:
        raise HTTPException(status_code=404, detail=f"페이지가 없습니다: {slug}")
    return {**page.meta(), "body": page.body, "links": page.links, "backlinks": store.backlinks(slug)}


@app.get("/index")
def get_index():
    return {"content": store.read_index()}


@app.get("/log")
def get_log():
    return {"content": store.read_log()}


@app.get("/sources")
def list_sources():
    return store.list_sources()


@app.get("/schema")
def get_schema():
    return {"content": store.read_schema()}


@app.put("/schema")
def put_schema(body: SchemaUpdate):
    store.write_schema(body.content)
    store.append_log("schema", "위키 작성 규칙 수정")
    return {"content": store.read_schema()}


@app.post("/ingest/file")
def ingest_file(file: UploadFile, model: str | None = Form(None), effort: str | None = Form(None)):
    opts = resolve_options(model, effort)
    data = file.file.read(settings.max_upload_bytes + 1)
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(status_code=413, detail="파일이 너무 큽니다.")
    return wiki.ingest_file(opts, file.filename or "upload.txt", data)


@app.post("/ingest/text")
def ingest_text(body: TextIngest):
    return wiki.ingest_text(resolve_options(body.model, body.effort), body.title, body.text)


@app.post("/query")
def query(body: QueryRequest):
    return wiki.query(resolve_options(body.model, body.effort), body.question)


@app.post("/query/save")
def save_answer(body: SaveAnswerRequest):
    return wiki.save_answer(body.question, body.answer, body.title)


@app.post("/lint")
def lint(body: LLMChoice | None = None):
    body = body or LLMChoice()
    return wiki.lint(resolve_options(body.model, body.effort))


@app.get("/lint/runs")
def list_lint_runs():
    return store.list_lint_runs()


@app.get("/lint/runs/{run_id}")
def get_lint_run(run_id: str):
    record = store.get_lint_run(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"점검 기록이 없습니다: {run_id}")
    return record
