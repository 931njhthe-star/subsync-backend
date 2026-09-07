# SubSync Backend

YouTube 이중 자막과 AI Video Tutor를 결합한 영어 학습 서비스 **SubSync**의 백엔드입니다.
Chrome Extension과 Streamlit 대시보드에 REST API를 제공하며, 사용자 학습 기록·단어장·AI 대화·행동 로그를 관리합니다.

## 주요 기능

- **인증 및 사용자 관리**: 회원가입, 로그인, JWT 기반 인증, 학습 프로필 관리
- **영어 단어 학습**: 자막 단어 Hover 빠른 조회, Click 상세 조회, 단어장 저장 및 목록 조회
- **Video Tutor**: 영상 자막과 재생 시점을 문맥으로 활용하는 Gemini/Groq 기반 질의응답 및 피드백 수집
- **학습 기록**: 시청 이력, 저장 단어, 단어 클릭, Tutor 대화 이력 기록
- **운영 및 분석**: Streamlit 기반 KPI·행동 로그·AI 응답 품질 분석

## 아키텍처

```text
Chrome Extension / Streamlit Dashboard
                │
                │ HTTP REST API (JSON)
                ▼
           FastAPI Backend
          ├── Supabase (PostgreSQL): 사용자·학습 데이터
          ├── Redis: 세션·단어 조회 캐시
          ├── Google Gemini: Video Tutor 기본 응답 생성
          ├── Groq: Gemini quota/rate limit 시 fallback 응답 생성
          └── YouTube: 영상·자막 데이터
```

## 현재 폴더 구조

현재 저장소에 생성된 구조입니다. 빈 `__init__.py` 패키지는 이후 기능별 구현을 위한 경계를 미리 잡아 둔 것입니다.

```text
subsync-backend/
├── app/
│   ├── api/                 # HTTP API 라우터
│   ├── cache/               # Redis 등 캐시 연동
│   ├── core/
│   │   └── config.py        # 환경별 설정 로드
│   ├── db/                  # DB 연결 및 저장소 계층
│   ├── models/              # DB 모델
│   ├── schemas/             # Pydantic 요청·응답 모델
│   ├── services/            # 비즈니스 로직
│   └── main.py              # FastAPI 애플리케이션 진입점
├── dashboard/               # Streamlit 운영·분석 대시보드
│   ├── analytics/
│   ├── components/
│   └── app.py
├── docs/
│   ├── onboarding.md       # 처음 참여하는 팀원의 실행·작업 안내
│   ├── prompts/            # AI 작업 요청 템플릿
│   ├── architecture/       # 시스템 구조·레포지토리 설계
│   ├── api/                # 공통 API·도메인 API 계약
│   ├── ai/                 # AI Tutor 요구사항·설계
│   ├── database/           # Supabase 스키마·DB 문서
│   └── README.md           # 문서 분류 및 읽는 순서
├── tests/
│   ├── fixtures/             # 담당자 간 공유 테스트 데이터
│   ├── test_health.py        # 헬스체크 테스트
│   └── test_tutor.py         # Tutor 테스트
├── .github/
│   ├── pull_request_template.md
│   └── workflows/ci.yml      # PR 자동 테스트
├── .python-version          # uv가 사용할 Python 버전
├── pyproject.toml           # uv 프로젝트·의존성 설정
└── uv.lock                  # uv가 생성·관리하는 고정 의존성 잠금 파일
```

## 확장 예정 구조

기획서의 기능을 구현하면서 아래와 같이 세분화합니다. API 경로와 요청·응답 형식은 [API 명세](docs/api/api_spec.md)를 기준으로 관리합니다.

```text
app/
├── api/
│   ├── deps.py              # 인증·DB 공통 의존성
│   └── v1/
│       ├── auth.py          # /auth
│       ├── dictionary.py    # /dict/hover, /dict/detail
│       ├── words.py         # /words
│       ├── tutor.py         # /tutor
│       └── logs.py          # /logs
├── ai/
│   ├── llm_client.py        # Gemini/Groq API 호출 래퍼
│   ├── provider_router.py   # provider fallback 및 quota guard
│   ├── usage_tracker.py     # provider별 토큰 사용량 기록
│   ├── context_builder.py   # 자막·시점 문맥 구성
│   ├── prompts.py           # Tutor 프롬프트
│   └── tutor_service.py     # AI 응답·피드백 처리
├── cache/
│   └── redis_client.py
├── core/
│   ├── config.py
│   └── security.py          # JWT·비밀번호 해싱
├── data/
│   └── base_dictionary.json # 빠른 단어 조회용 정적 사전
├── db/
│   └── database.py          # Supabase 클라이언트
├── models/
├── schemas/
└── services/
    ├── auth_service.py
    ├── dict_service.py      # Redis → 정적 사전 → 외부 사전 조회
    ├── word_service.py
    └── log_service.py
```

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

비밀값은 로컬 `.env` 파일 또는 배포 환경의 시크릿 관리 도구에만 보관하고 Git에 커밋하지 않습니다. 도입 예정 값은 다음과 같습니다.

```dotenv
ENV=development
SUPABASE_URL=
SUPABASE_KEY=
REDIS_URL=
LLM_PROVIDER=stub
GEMINI_API_KEY=
GEMINI_MODEL=gemini-3.6-flash
GEMINI_TIMEOUT_SECONDS=20
GEMINI_DAILY_TOKEN_LIMIT=0
GEMINI_MINUTE_TOKEN_LIMIT=0
GROQ_API_KEY=
GROQ_MODEL=openai/gpt-oss-20b
GROQ_TIMEOUT_SECONDS=20
GROQ_DAILY_TOKEN_LIMIT=180000
GROQ_MINUTE_TOKEN_LIMIT=7000
TUTOR_PROACTIVE_COOLDOWN_SECONDS=45
TUTOR_REQUESTS_PER_MINUTE=30
JWT_SECRET_KEY=
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
`429` 응답 또는 로컬 quota 도달 시 다음 provider로 전환합니다. 상세한 프로필 추론 및
fallback 규칙은
[AI Tutor 기초 설계](docs/ai/ai-tutor.md)를 참고하세요.

## 문서

- [문서 인덱스](docs/README.md)
- [온보딩 안내](docs/onboarding.md)
- [AI 작업 프롬프트](docs/prompts/feature-task.md)
- [시스템 아키텍처](docs/architecture/architecture.md)
- [API 명세](docs/api/api_spec.md)
- [Video Tutor API 명세](docs/api/tutor_api_spec.md)
- [AI Tutor 요구사항](docs/ai/ai_tutor_requirements.md)
- [Supabase DB 스키마](docs/database/db_schema.sql)
- [레포지토리·폴더 구조 설계](docs/architecture/subsync-architecture-guide.md)

## 개발 원칙

- API 변경은 구현 전에 `docs/api/api_spec.md`를 먼저 갱신합니다.
- 요청·응답 검증은 `schemas/`, 도메인 로직은 `services/`, 외부 연동은 `ai/`, `db/`, `cache/`에 둡니다.
- 의존성 추가·갱신은 `uv add` 또는 `uv add --dev`로 수행하고, 생성된 `uv.lock`은 함께 커밋합니다.
- 민감 정보와 로컬 데이터는 `.gitignore`로 제외합니다.
