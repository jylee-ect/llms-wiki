# FastAPI 백엔드 실행 (http://127.0.0.1:8000, API 문서: /docs)
$root = $PSScriptRoot
& "$root\.venv\Scripts\python.exe" -m uvicorn app.main:app --app-dir "$root\backend" --host 127.0.0.1 --port 8000 --reload --reload-dir "$root\backend"
