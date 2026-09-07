# SubSync Backend

YouTube 자막 문맥을 활용하는 AI Video Tutor의 FastAPI 백엔드입니다.

## 현재 구현

- `GET /health`
- `POST /api/v1/tutor/ask`
- `POST /api/v1/tutor/proactive`
- `POST /api/v1/tutor/feedback`
- Gemini/Groq provider와 네트워크 없이 동작하는 `stub` fallback

Tutor 대화·피드백·사용량 제한은 현재 개발용 프로세스 메모리에 저장된다. Supabase Auth,
영구 DB 저장, Redis 캐시는 아직 API에 연결되어 있지 않다.

## 기준

- API 계약: FastAPI `/docs`, Postman Collection, `tests/`
- 환경변수: `.env.example`
- DB 생성 기준과 점검 결과: `docs/database/README.md`

## 시작하기

### 요구 사항

- Python 3.11 이상
- [uv](https://docs.astral.sh/uv/)

### 설치 및 실행

```bash
uv sync
uv run uvicorn app.main:app --reload --port 8000
```

서버 실행 후 `http://127.0.0.1:8000/health`에서 상태를 확인할 수 있습니다. FastAPI 자동 문서는 `http://127.0.0.1:8000/docs`에서 확인합니다.

### 테스트

```bash
uv run pytest
```

## 환경 변수

비밀값은 로컬 `.env` 파일 또는 배포 환경의 시크릿 관리 도구에만 보관하고 Git에 커밋하지 않습니다. 환경변수 목록과 설명의 기준 파일은 `.env.example`입니다.

```bash
cp .env.example .env
```

Video Tutor는 기본적으로 `LLM_PROVIDER=stub`으로 실행되며, API 키 없이도 문맥/프로필/API
계약을 확인할 수 있습니다. 실제 provider를 사용하려면 서버 환경변수에 다음 중 하나를
설정합니다.

- `LLM_PROVIDER=gemini`: Gemini 우선, 한도 초과/장애 시 Groq → stub
- `LLM_PROVIDER=groq`: Groq 우선, 한도 초과/장애 시 Gemini → stub
- `LLM_PROVIDER=auto`: Gemini 우선 fallback 체인

`GEMINI_DAILY_TOKEN_LIMIT`/`GEMINI_MINUTE_TOKEN_LIMIT`는 AI Studio에서 확인한 프로젝트
한도로 설정합니다. Gemini의 활성 한도는 프로젝트·모델·계정에 따라 달라질 수 있으므로
기본값은 로컬 guard를 끄는 `0`입니다. Groq 값은 무료 플랜을 가정한 보수적 기본값이며,
사용 중인 plan에 맞게 조정할 수 있습니다. 실제 provider 응답의 usage도 기록하고,
`429` 응답 또는 로컬 quota 도달 시 다음 provider로 전환합니다. 세부 동작은
`app/ai/`의 docstring과 `tests/test_tutor.py`에서 확인합니다.

## 문서

- [문서 인덱스](docs/README.md)
- [온보딩 안내](docs/onboarding.md)
- [DB 기준과 스키마](docs/database/README.md)

## 개발 원칙

- API 변경은 Pydantic DTO, Postman Collection, 테스트를 함께 갱신하고 `/docs`에서 확인합니다.
- 요청·응답 검증은 `schemas/`, 도메인 로직은 `services/`, 외부 연동은 `ai/`, `db/`, `cache/`에 둡니다.
- 의존성 추가·갱신은 `uv add` 또는 `uv add --dev`로 수행하고, 생성된 `uv.lock`은 함께 커밋합니다.
- 민감 정보와 로컬 데이터는 `.gitignore`로 제외합니다.
