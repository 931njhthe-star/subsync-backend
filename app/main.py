"""FastAPI 애플리케이션 진입점.

개발환경: uvicorn app.main:app --reload --port 8000
API 라우터는 app/api/ 에서 등록한다. (3단계~)
"""

from fastapi import FastAPI

app = FastAPI(title="YouTube Language Teach Agent API")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
