import os
import re

import requests
import streamlit as st

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000").rstrip("/")
LLM_TIMEOUT = 900  # ingest/query/lint는 추론 모델 호출이라 오래 걸릴 수 있다
TYPE_LABELS = {
    "source": "원본 요약",
    "entity": "개체",
    "concept": "개념",
    "topic": "주제",
    "analysis": "분석",
}
LINK_RE = re.compile(r"\[\[([^\]|#]+)(?:\|([^\]]*))?\]\]")
EFFORT_HELP = {
    "none": "추론 없음 · 가장 빠르고 저렴",
    "low": "가벼운 추론 · 빠름",
    "medium": "기본값 · 속도와 품질 균형",
    "high": "깊은 추론 · 복잡한 문서에 적합",
    "xhigh": "매우 깊은 추론 · 느림",
    "max": "최대 추론 · 가장 느리고 비쌈",
}

st.set_page_config(page_title="LLM Wiki", page_icon="📚", layout="wide")


def api(method: str, path: str, timeout: float = 30, **kwargs):
    """백엔드 호출. 실패하면 화면에 오류를 표시하고 None을 반환한다."""
    try:
        response = requests.request(method, f"{BACKEND_URL}{path}", timeout=timeout, **kwargs)
    except requests.RequestException as e:
        st.error(f"백엔드에 연결할 수 없습니다 ({BACKEND_URL}): {e}")
        return None
    if not response.ok:
        try:
            detail = response.json().get("detail", response.text)
        except ValueError:
            detail = response.text
        st.error(f"오류 {response.status_code}: {detail}")
        return None
    return response.json()


def render_links(markdown: str) -> str:
    """[[slug]] 위키 링크를 읽기 좋은 표시로 바꾼다."""
    return LINK_RE.sub(lambda m: f"`📄 {m.group(2) or m.group(1)}`", markdown)


def open_page(slug: str):
    st.session_state["selected_page"] = slug
    st.session_state["jump_to_wiki"] = True


# ---------- 사이드바 ----------

health = api("GET", "/health", timeout=5)
catalog = api("GET", "/models", timeout=5) if health else None
if health is None or catalog is None:
    st.info("백엔드를 먼저 실행하세요 (README.md의 '실행' 참고)")
    st.stop()
models = {m["id"]: m for m in catalog["models"]}

with st.sidebar:
    st.title("📚 LLM Wiki")
    st.caption("LLM이 원본 문서를 읽고 위키를 직접 쓰고 관리합니다.")
    col1, col2 = st.columns(2)
    col1.metric("위키 페이지", health["pages"])
    col2.metric("원본 문서", health["sources"])
    if not health["api_key_configured"]:
        st.warning("GPT_API 환경변수가 설정되지 않았습니다.")

    st.markdown("##### 모델 설정")
    if st.session_state.get("model") not in models:
        default_model = catalog["default_model"]
        st.session_state["model"] = default_model if default_model in models else next(iter(models))
    model = st.selectbox("모델", list(models), format_func=lambda m: models[m]["label"], key="model")
    st.caption(models[model]["description"])
    efforts = models[model]["efforts"]
    if st.session_state.get("effort") not in efforts:
        default_effort = catalog["default_effort"]
        st.session_state["effort"] = default_effort if default_effort in efforts else efforts[len(efforts) // 2]
    effort = st.select_slider("Reasoning effort", efforts, key="effort")
    st.caption(EFFORT_HELP.get(effort, ""))
    llm_choice = {"model": model, "effort": effort}

    st.divider()
    if st.button("새로고침", width="stretch"):
        st.rerun()
    st.caption(f"Backend: {BACKEND_URL}")

if st.session_state.pop("jump_to_wiki", False):
    st.toast(f"'위키' 탭에서 `{st.session_state['selected_page']}` 페이지를 열었습니다.")

tab_query, tab_ingest, tab_wiki, tab_lint, tab_log, tab_schema = st.tabs(
    ["💬 질문", "📥 문서 추가", "📖 위키", "🩺 점검", "📜 로그", "⚙️ 규칙"]
)

# ---------- 질문 ----------

with tab_query:
    st.subheader("위키에 질문하기")
    st.caption("LLM이 목차(index.md)에서 관련 페이지를 고른 뒤, 그 페이지를 근거로 답합니다.")
    messages = st.session_state.setdefault("messages", [])

    for i, msg in enumerate(messages):
        with st.chat_message(msg["role"]):
            st.markdown(render_links(msg["content"]) if msg["role"] == "assistant" else msg["content"])
            if msg["role"] != "assistant":
                continue
            if msg.get("model"):
                st.caption(f"🤖 {models.get(msg['model'], {}).get('label', msg['model'])} · effort {msg['effort']}")
            if msg.get("pages"):
                with st.expander(f"참고한 페이지 {len(msg['pages'])}개"):
                    for slug in msg["pages"]:
                        st.button(f"📄 {slug}", key=f"ref-{i}-{slug}", on_click=open_page, args=(slug,))
            if msg.get("saved"):
                st.caption(f"✅ 위키에 저장됨: `{msg['saved']}`")
            elif msg.get("question") and st.button("이 답변을 위키에 저장", key=f"save-{i}"):
                saved = api(
                    "POST", "/query/save", json={"question": msg["question"], "answer": msg["content"]}
                )
                if saved:
                    msg["saved"] = saved["slug"]
                    st.rerun()

    question = st.chat_input("예: 출입통제 시스템의 주요 구성 요소는?")
    if question:
        messages.append({"role": "user", "content": question})
        with st.spinner("위키를 찾아보는 중..."):
            result = api("POST", "/query", timeout=LLM_TIMEOUT, json={"question": question, **llm_choice})
        if result:
            messages.append(
                {
                    "role": "assistant",
                    "content": result["answer"],
                    "pages": result["pages"],
                    "question": question,
                    "model": result["model"],
                    "effort": result["effort"],
                }
            )
        st.rerun()

    if messages and st.button("대화 지우기"):
        messages.clear()
        st.rerun()

# ---------- 문서 추가 ----------

with tab_ingest:
    st.subheader("원본 문서 추가 (Ingest)")
    st.caption("문서를 추가하면 LLM이 원본 요약 페이지를 만들고, 관련 개체·개념 페이지를 새로 쓰거나 갱신합니다.")
    st.caption(f"사용 모델: **{models[model]['label']}** · effort **{effort}** (사이드바에서 변경)")

    extensions = [e.lstrip(".") for e in health["supported_extensions"]]
    files = st.file_uploader("파일 선택", type=extensions, accept_multiple_files=True)
    if st.button("위키에 반영", type="primary", disabled=not files):
        for f in files:
            with st.status(f"{f.name} 처리 중...", expanded=True) as status:
                result = api(
                    "POST",
                    "/ingest/file",
                    timeout=LLM_TIMEOUT,
                    files={"file": (f.name, f.getvalue())},
                    data=llm_choice,
                )
                if result is None:
                    status.update(label=f"{f.name} 실패", state="error")
                    continue
                st.markdown(f"**{result['source_title']}** (`{result['source']}`)")
                for line in result["log"]:
                    st.markdown(f"- {render_links(line)}")
                st.markdown(f"생성 {len(result['created'])}개 · 수정 {len(result['updated'])}개")
                if result["truncated"]:
                    st.warning("문서가 길어 앞부분만 반영했습니다.")
                status.update(label=f"{f.name} 완료", state="complete")

    with st.expander("텍스트 직접 입력"):
        with st.form("text_ingest", clear_on_submit=True):
            title = st.text_input("제목")
            text = st.text_area("내용", height=250)
            if st.form_submit_button("위키에 반영") and title and text:
                with st.spinner("위키에 반영하는 중..."):
                    result = api(
                        "POST",
                        "/ingest/text",
                        timeout=LLM_TIMEOUT,
                        json={"title": title, "text": text, **llm_choice},
                    )
                if result:
                    st.success(
                        f"완료: 생성 {len(result['created'])}개 · 수정 {len(result['updated'])}개"
                    )

    sources = api("GET", "/sources") or []
    if sources:
        st.markdown("##### 추가된 원본")
        st.dataframe(sources, width="stretch", hide_index=True)

# ---------- 위키 ----------

with tab_wiki:
    pages = api("GET", "/pages") or []
    if not pages:
        st.info("아직 위키 페이지가 없습니다. '문서 추가' 탭에서 문서를 넣어 보세요.")
    else:
        left, right = st.columns([1, 3])
        with left:
            keyword = st.text_input("검색", placeholder="제목·요약")
            type_filter = st.multiselect("유형", list(TYPE_LABELS), format_func=TYPE_LABELS.get)
            filtered = [
                p
                for p in pages
                if (not type_filter or p["type"] in type_filter)
                and (not keyword or keyword.lower() in (p["title"] + p["summary"]).lower())
            ]
            titles = {p["slug"]: f"[{TYPE_LABELS.get(p['type'], p['type'])}] {p['title']}" for p in pages}
            options = [p["slug"] for p in filtered]
            selected = st.session_state.get("selected_page")
            if selected in titles and selected not in options:
                options.insert(0, selected)
            if options:
                if selected not in options:
                    st.session_state["selected_page"] = options[0]
                st.radio("페이지", options, format_func=titles.get, key="selected_page", label_visibility="collapsed")
            else:
                st.caption("조건에 맞는 페이지가 없습니다.")

        with right:
            slug = st.session_state.get("selected_page")
            page = api("GET", f"/pages/{slug}") if slug in titles else None
            if page:
                st.markdown(f"## {page['title']}")
                st.caption(
                    f"`{page['slug']}` · {TYPE_LABELS.get(page['type'], page['type'])} · 갱신 {page['updated']}"
                    + (f" · 원본: {', '.join(page['sources'])}" if page["sources"] else "")
                )
                st.markdown(render_links(page["body"]))
                st.divider()
                for label, slugs in (("연결된 페이지", page["links"]), ("이 페이지를 참조하는 페이지", page["backlinks"])):
                    st.markdown(f"**{label}**")
                    if not slugs:
                        st.caption("없음")
                        continue
                    cols = st.columns(4)
                    for j, target in enumerate(slugs):
                        cols[j % 4].button(
                            titles.get(target, f"⚠️ {target} (없음)"),
                            key=f"nav-{label}-{target}",
                            on_click=open_page,
                            args=(target,),
                            disabled=target not in titles,
                            width="stretch",
                        )

        with st.expander("목차 원문 (index.md)"):
            index = api("GET", "/index")
            if index:
                st.code(index["content"], language="markdown")

# ---------- 점검 ----------

with tab_lint:
    st.subheader("위키 점검 (Lint)")
    st.caption("페이지 간 모순, 오래된 내용, 빠진 페이지·링크를 LLM이 찾고, 깨진 링크와 고아 페이지는 코드로 검사합니다.")
    st.caption(f"사용 모델: **{models[model]['label']}** · effort **{effort}** (사이드바에서 변경)")
    if st.button("점검 실행", type="primary"):
        with st.spinner("위키 전체를 읽는 중..."):
            st.session_state["lint"] = api("POST", "/lint", timeout=LLM_TIMEOUT, json=llm_choice)

    report = st.session_state.get("lint")
    if report:
        c1, c2, c3 = st.columns(3)
        c1.metric("LLM 지적 사항", len(report["issues"]))
        c2.metric("깨진 링크", len(report["broken_links"]))
        c3.metric("고아 페이지", len(report["orphans"]))
        if report["checked_pages"] < report["total_pages"]:
            st.warning(f"분량 제한으로 {report['total_pages']}개 중 {report['checked_pages']}개만 LLM이 점검했습니다.")
        for issue in report["issues"]:
            with st.container(border=True):
                st.markdown(f"**`{issue['kind']}`** — {issue['description']}")
                st.markdown(f"💡 {issue['suggestion']}")
                if issue["pages"]:
                    st.caption("관련: " + ", ".join(issue["pages"]))
        if report["broken_links"]:
            st.markdown("##### 깨진 링크")
            st.dataframe(report["broken_links"], width="stretch", hide_index=True)
        if report["orphans"]:
            st.markdown("##### 고아 페이지 (다른 페이지에서 링크되지 않음)")
            st.write(", ".join(f"`{s}`" for s in report["orphans"]))

# ---------- 로그 ----------

with tab_log:
    log = api("GET", "/log")
    if log:
        st.markdown(render_links(log["content"]))

# ---------- 규칙 ----------

with tab_schema:
    st.subheader("위키 작성 규칙 (AGENTS.md)")
    st.caption("LLM이 페이지를 쓸 때 따르는 규칙입니다. 수정하면 다음 문서 추가부터 반영됩니다.")
    schema = api("GET", "/schema")
    if schema:
        with st.form("schema"):
            content = st.text_area("규칙", schema["content"], height=500, label_visibility="collapsed")
            if st.form_submit_button("저장"):
                if api("PUT", "/schema", json={"content": content}):
                    st.success("저장했습니다.")
