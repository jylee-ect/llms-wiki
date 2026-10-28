"""파일 기반 위키 저장소.

data/
  AGENTS.md      위키 작성 규칙(스키마) — 사람이 편집
  raw/           원본 문서 — 수정하지 않음
  lint/<id>.json 점검 결과 — 실행 1회당 1파일
  wiki/
    index.md     목차 — 페이지 메타데이터로 자동 생성
    log.md       작업 이력 — append-only
    <slug>.md    LLM이 작성하는 페이지 (frontmatter + 본문)
"""
import json
import re
import secrets
import shutil
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .config import settings

PAGE_TYPES = ["source", "entity", "concept", "topic", "analysis"]
TYPE_LABELS = {
    "source": "원본 요약",
    "entity": "개체 (사람·조직·제품·시스템)",
    "concept": "개념",
    "topic": "주제 종합",
    "analysis": "분석·질의 결과",
}
RESERVED_SLUGS = {"index", "log"}
LINK_RE = re.compile(r"\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]")
DEFAULT_SCHEMA = Path(__file__).with_name("default_schema.md")

LINT_SCHEMA_VERSION = 1
LINT_RUN_ID_RE = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{6}$")
LINT_SUMMARY_KEYS = ("id", "created_at", "model", "effort", "checked_pages", "total_pages", "counts")

# 쓰기 작업(ingest/저장/로그)을 직렬화한다. 단일 프로세스 전제.
lock = threading.RLock()


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def slugify(text: str) -> str:
    s = re.sub(r"[^\w\s-]", "", text.strip().lower())
    s = re.sub(r"[\s_]+", "-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s[:80].strip("-") or "untitled"


def normalize_slug(text: str) -> str:
    s = slugify(text)
    return f"page-{s}" if s in RESERVED_SLUGS else s


@dataclass
class Page:
    slug: str
    title: str
    type: str
    summary: str
    body: str
    sources: list[str] = field(default_factory=list)
    updated: str = ""

    @property
    def links(self) -> list[str]:
        return sorted({normalize_slug(m) for m in LINK_RE.findall(self.body)} - {self.slug})

    def meta(self) -> dict:
        return {
            "slug": self.slug,
            "title": self.title,
            "type": self.type,
            "summary": self.summary,
            "sources": self.sources,
            "updated": self.updated,
        }

    def to_markdown(self) -> str:
        meta = self.meta()
        meta.pop("slug")
        front = "\n".join(f"{k}: {json.dumps(v, ensure_ascii=False)}" for k, v in meta.items())
        return f"---\n{front}\n---\n\n{self.body.strip()}\n"


def _parse_page(slug: str, text: str) -> Page:
    meta: dict = {}
    body = text
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end != -1:
            for line in text[4:end].splitlines():
                key, sep, value = line.partition(":")
                if not sep:
                    continue
                try:
                    meta[key.strip()] = json.loads(value.strip())
                except json.JSONDecodeError:
                    meta[key.strip()] = value.strip()
            body = text[end + 5 :]
    page_type = meta.get("type", "topic")
    return Page(
        slug=slug,
        title=str(meta.get("title") or slug),
        type=page_type if page_type in PAGE_TYPES else "topic",
        summary=str(meta.get("summary", "")),
        body=body.strip(),
        sources=list(meta.get("sources") or []),
        updated=str(meta.get("updated", "")),
    )


def _write_atomic(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _page_path(slug: str) -> Path:
    return settings.wiki_dir / f"{slug}.md"


# ---------- 초기화 ----------

def init() -> None:
    settings.raw_dir.mkdir(parents=True, exist_ok=True)
    settings.wiki_dir.mkdir(parents=True, exist_ok=True)
    settings.lint_dir.mkdir(parents=True, exist_ok=True)
    if not settings.schema_path.exists():
        shutil.copyfile(DEFAULT_SCHEMA, settings.schema_path)
    if not (settings.wiki_dir / "log.md").exists():
        _write_atomic(settings.wiki_dir / "log.md", "# 작업 로그\n")
    if not (settings.wiki_dir / "index.md").exists():
        rebuild_index()


# ---------- 페이지 ----------

def page_exists(slug: str) -> bool:
    return slug not in RESERVED_SLUGS and _page_path(slug).is_file()


def get_page(slug: str) -> Page | None:
    if not page_exists(slug):
        return None
    return _parse_page(slug, _page_path(slug).read_text(encoding="utf-8"))


def list_pages() -> list[Page]:
    pages = []
    for path in sorted(settings.wiki_dir.glob("*.md")):
        if path.stem in RESERVED_SLUGS:
            continue
        pages.append(_parse_page(path.stem, path.read_text(encoding="utf-8")))
    return pages


def write_page(page: Page) -> None:
    with lock:
        _write_atomic(_page_path(page.slug), page.to_markdown())


def unique_slug(base: str) -> str:
    slug, i = base, 2
    while page_exists(slug):
        slug = f"{base}-{i}"
        i += 1
    return slug


def backlinks(slug: str, pages: list[Page] | None = None) -> list[str]:
    pages = pages if pages is not None else list_pages()
    return [p.slug for p in pages if slug in p.links]


# ---------- index / log / schema ----------

def rebuild_index() -> None:
    pages = list_pages()
    lines = [
        "# 위키 목차",
        "",
        f"> 자동 생성 — 직접 수정하지 마세요. 페이지 {len(pages)}개 · 원본 {len(list_sources())}개 · 갱신 {now()}",
    ]
    for page_type in PAGE_TYPES:
        group = [p for p in pages if p.type == page_type]
        if not group:
            continue
        lines += ["", f"## {TYPE_LABELS[page_type]} ({page_type})", ""]
        lines += [f"- [[{p.slug}]] **{p.title}** — {p.summary}" for p in sorted(group, key=lambda p: p.title)]
    with lock:
        _write_atomic(settings.wiki_dir / "index.md", "\n".join(lines) + "\n")


def read_index() -> str:
    path = settings.wiki_dir / "index.md"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def append_log(operation: str, title: str, details: list[str] | None = None) -> None:
    entry = f"\n## [{now()}] {operation} | {title}\n"
    if details:
        entry += "\n" + "\n".join(f"- {d}" for d in details) + "\n"
    with lock:
        with open(settings.wiki_dir / "log.md", "a", encoding="utf-8") as f:
            f.write(entry)


def read_log() -> str:
    path = settings.wiki_dir / "log.md"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def read_schema() -> str:
    return settings.schema_path.read_text(encoding="utf-8")


def write_schema(content: str) -> None:
    with lock:
        _write_atomic(settings.schema_path, content)


# ---------- 점검 결과 ----------

def new_lint_run_id() -> tuple[str, str]:
    """(id, created_at) — id는 시각순 정렬이 되도록 타임스탬프로 시작한다."""
    at = datetime.now().astimezone()
    return f"{at:%Y%m%d-%H%M%S}-{secrets.token_hex(3)}", at.isoformat(timespec="seconds")


def save_lint_run(record: dict) -> None:
    with lock:
        settings.lint_dir.mkdir(parents=True, exist_ok=True)
        text = json.dumps(record, ensure_ascii=False, indent=2) + "\n"
        _write_atomic(settings.lint_dir / f"{record['id']}.json", text)


def get_lint_run(run_id: str) -> dict | None:
    if not LINT_RUN_ID_RE.match(run_id):
        return None
    path = settings.lint_dir / f"{run_id}.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def list_lint_runs() -> list[dict]:
    """최신순 요약 목록. 읽을 수 없는 파일은 건너뛴다."""
    runs = []
    for path in sorted(settings.lint_dir.glob("*.json"), reverse=True):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        runs.append({key: record.get(key) for key in LINT_SUMMARY_KEYS})
    return runs


# ---------- 원본 ----------

def save_raw(filename: str, data: bytes) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", Path(filename).name).strip(" .") or "source.txt"
    path = settings.raw_dir / name
    i = 2
    while path.exists():
        path = settings.raw_dir / f"{Path(name).stem}-{i}{Path(name).suffix}"
        i += 1
    path.write_bytes(data)
    return path.name


def list_sources() -> list[dict]:
    if not settings.raw_dir.exists():
        return []
    return [
        {
            "name": p.name,
            "size": p.stat().st_size,
            "added": datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
        }
        for p in sorted(settings.raw_dir.iterdir())
        if p.is_file()
    ]
