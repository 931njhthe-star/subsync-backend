# SubSync Backend

YouTube 이중 자막 학습 서비스 SubSync의 FastAPI 백엔드입니다.
Chrome Extension에 사전·단어장·Video Tutor API를 제공하고, Streamlit 운영 화면에서
LLM 사용량과 API 호출 지표를 조회할 수 있도록 Supabase 및 외부 provider를 연결합니다.

이 저장소의 애플리케이션 진입점은 app/main.py이며, 모든 버전 API는 /api/v1 아래에
등록됩니다. 서버 상태 확인용 /health만 버전 경로 밖에 있습니다.

## 구현된 기능

- 사전: Hover 빠른 조회와 Click 상세 조회를 제공합니다. Redis 캐시를 먼저 확인한 뒤
  Free Dictionary와 Wiktionary를 사용하고, 설정된 경우 DeepL 번역을 적용합니다.
- 저장 단어: 단어 저장·목록·삭제 API를 제공합니다.
- Video Tutor: 자막 문맥을 이용한 질문, 선제 질문, 피드백, 사용량 조회 API를 제공합니다.
  LLM provider는 Gemini, Groq, stub을 지원하며 provider 장애·한도 초과 시 fallback합니다.
- 운영 지표: LLM 사용량(llm_usage)과 API 호출 로그(api_logs)를 집계하는 Dashboard API를
  제공합니다. 현재 관리자 인증은 연결 전인 개발용 계약입니다.
- 관측성: API 응답에 X-Request-ID를 넣고, 요청 본문·응답 본문을 저장하지 않는 최소
  API 로그를 Supabase에 비동기로 기록합니다.

## 시스템 구성

```
Chrome Extension / Streamlit Dashboard
                │
                │ HTTP REST API (JSON)
                ▼
           FastAPI Backend
                ├── Supabase Auth/PostgreSQL: 인증·사용자·저장 단어·운영 지표
                ├── Redis: 사전 조회 결과 캐시
                ├── Dictionary APIs + DeepL: 단어 정의·한국어 번역
                └── Gemini / Groq / stub: Video Tutor 응답
```

콘텐츠/API 라우터는 app/api/v1에, 요청·응답 DTO는 app/schemas에, 도메인 서비스는
app/services 및 app/ai에 둡니다. app/main.py에는 애플리케이션·middleware·라우터 등록만 둡니다.

## 프로젝트 구조

```
subsync-backend/
├── app/
│   ├── api/
│   │   ├── deps.py                 # 공통 인증·개발 사용자 dependency
│   │   └── v1/                     # /api/v1 HTTP 라우터
│   │       ├── auth.py             # Supabase 사용자 확인·로그아웃
│   │       ├── dashboard.py        # 운영 지표 조회
│   │       ├── dictionary.py       # 사전 Hover·Detail 및 레거시 alias
│   │       ├── tutor.py            # Video Tutor API
│   │       └── words.py             # 저장 단어 API
│   ├── ai/
│   │   ├── context_builder.py      # Tutor 문맥 구성
│   │   ├── learner_profile.py      # 학습자 프로필 구성
│   │   ├── llm_client.py           # Gemini·Groq·stub 호출
│   │   ├── prompts.py              # Tutor 프롬프트
│   │   ├── provider_router.py      # provider fallback·한도 처리
│   │   ├── tutor_service.py        # Tutor 도메인 로직
│   │   ├── tutor_state.py          # 대화·선제 질문 상태
│   │   └── usage_tracker.py         # 사용량·호출 제한
│   ├── cache/
│   │   └── redis_client.py          # Redis JSON 캐시
│   ├── core/
│   │   ├── config.py               # 환경변수 기반 설정
│   │   └── security.py             # Supabase Access Token 검증
│   ├── db/
│   │   ├── api_logs.py             # API 로그 repository
│   │   ├── llm_usage.py             # LLM 사용량 repository
│   │   ├── login_history.py         # 로그인 이력 repository
│   │   ├── saved_words.py           # 저장 단어 repository
│   │   └── users.py                 # 사용자 동기화·directory repository
│   ├── schemas/                     # Pydantic 요청·응답 DTO
│   │   ├── auth.py · dashboard.py · dictionary.py
│   │   ├── tutor.py · words.py
│   ├── services/
│   │   ├── dashboard.py             # 지표 집계·필터링
│   │   ├── dict_service.py          # 사전 provider·번역·캐시 fallback
│   │   └── word_service.py          # 저장 단어 비즈니스 로직
│   └── main.py                      # FastAPI app·CORS·로그 middleware
├── docs/
│   ├── database/                    # DB 기준 문서·테이블 SQL
│   ├── migrations/                  # 적용 순서를 보존하는 migration SQL
│   ├── auth-login.md                # Supabase 로그인 연동 문서
│   ├── onboarding.md                # 초보자 온보딩
│   └── README.md                    # 문서 인덱스
├── postman/                         # JSON Collection·환경·Quick Start 리소스
├── tests/                            # pytest 단위·API 통합 테스트
├── .env.example                     # 환경변수 이름과 예시 기본값
├── .python-version                  # Python 버전 기준
├── pyproject.toml                   # 프로젝트·의존성 정의
├── uv.lock                          # uv dependency lock
└── AGENTS.md                        # 저장소 협업 지침
```

DB 접근은 app/db repository와 app/schemas DTO로 분리되어 있습니다. Dashboard 화면 자체가
아니라 Dashboard 조회 API가 app/api/v1/dashboard.py와 app/services/dashboard.py에 구현되어
있습니다.

## API 요약

대부분의 API 응답은 JSON이며, 입력 검증 실패는 FastAPI 기본 형식의 422를 사용합니다.
저장 단어 삭제 성공처럼 본문이 없는 응답은 204를 사용합니다.

| 영역 | Method | 경로 | 인증·비고 |
| --- | --- | --- | --- |
| Health | GET | /health | 공개. 서버 프로세스 상태 확인 |
| Auth | GET | /api/v1/auth/me | Supabase Bearer Access Token 필요 |
| Auth | POST | /api/v1/auth/logout | Supabase Bearer Access Token 필요 |
| Dictionary | GET | /api/v1/dictionary/hover?word=honest | 공개. context를 추가하면 문맥 뜻 사용 |
| Dictionary | GET | /api/v1/dictionary/detail?word=honest | 공개. 상세 정의·예문·문맥 뜻 |
| Dictionary | GET | /api/v1/dict/hover, /detail | 이전 Extension 호환 alias. 공개 |
| Saved Words | POST, GET | /api/v1/words | 개발 환경에서 X-Dev-User-ID 필요 |
| Saved Words | DELETE | /api/v1/words/{word_id} | 개발 환경에서 X-Dev-User-ID 필요 |
| Tutor | POST | /api/v1/tutor/ask | 현재 개발용 actor·상태 저장소 사용 |
| Tutor | GET | /api/v1/tutor/usage | 개발용 전체 LLM 사용량 조회 |
| Tutor | POST | /api/v1/tutor/proactive | 영상 시점 기반 선제 질문 판단 |
| Tutor | POST | /api/v1/tutor/feedback | 개발용 메모리 상태에 피드백 기록 |
| Dashboard | GET | /api/v1/dashboard/overview | 관리자 인증 연결 전 개발용 API |
| Dashboard | GET | /api/v1/dashboard/usage | 최근 1~90일 또는 날짜 범위 조회 |
| Dashboard | GET | /api/v1/dashboard/api-calls | endpoint별 호출·성공률·응답시간 조회 |

사전 API의 word는 1~100자, context는 선택적 1,000자까지 허용합니다.
사전 provider를 찾지 못하면 404, 외부 사전과 번역 fallback을 모두 사용할 수 없으면
503을 반환합니다. 따라서 /health가 200이어도 사전 provider 장애 시 Hover 요청만 503이 될 수 있습니다.
상세 응답의 is_saved는 현재 인증·saved_words 연동 전이므로 null입니다.

## 로컬 실행

### 요구 사항

- Python 3.11
- uv
- Supabase, Redis, 외부 provider는 기능에 따라 선택 사항입니다. LLM_PROVIDER=stub이면
  LLM API 키 없이 Tutor 계약을 확인할 수 있습니다.

### 설치 및 서버 실행

```
uv sync
Copy-Item .env.example .env
# macOS/Linux: cp .env.example .env
uv run uvicorn app.main:app --reload --port 8000 --env-file .env
```

실행 후 다음 주소를 사용할 수 있습니다.

- Health: http://127.0.0.1:8000/health
- Swagger UI: http://127.0.0.1:8000/docs
- OpenAPI JSON: http://127.0.0.1:8000/openapi.json

### 테스트 및 기본 검증

```
uv run pytest
uv run python -m compileall -q app tests
git diff --check
```

외부 provider에 연결되는 테스트는 기본 테스트에 의존하지 않도록 fake·stub fixture를
사용합니다. 실제 사전 provider 또는 LLM 장애 동작은 설정과 로그를 별도로 확인합니다.

## 환경 변수

환경변수 이름과 주석이 있는 기준 파일은 [.env.example](.env.example)입니다.
실제 키와 secret은 로컬 .env 또는 Render 환경변수에만 저장하고 Git, 브라우저, Postman
공유 환경 파일에 넣지 않습니다.

| 그룹 | 주요 변수 | 용도 |
| --- | --- | --- |
| 공통 | ENV | development 또는 production 실행 모드 |
| Supabase | SUPABASE_URL, SUPABASE_SECRET_KEY | Auth 검증, users/login_history 동기화, 운영 로그 저장 |
| Redis | REDIS_URL | 사전 조회 캐시. 비어 있거나 장애가 나면 캐시 miss로 원본 provider를 조회 |
| Dictionary | DICTIONARY_API_URL, DICTIONARY_FALLBACK_API_URL | 기본 Free Dictionary와 Wiktionary fallback 주소 |
| 번역 | DEEPL_API_KEY, DEEPL_API_BASE_URL | 영어 정의·문맥 뜻의 한국어 번역 및 provider 장애 fallback |
| Tutor | LLM_PROVIDER, GEMINI_*, GROQ_* | LLM provider, 모델, timeout, API key 설정 |
| Tutor 제한 | GEMINI_*_TOKEN_LIMIT, GROQ_*_TOKEN_LIMIT, TUTOR_REQUESTS_PER_MINUTE | provider별 token quota와 사용자 호출 제한 |
| 선제 질문 | TUTOR_PROACTIVE_COOLDOWN_SECONDS, TUTOR_PROACTIVE_MAX_QUESTIONS_PER_VIDEO | 영상 시점 간격과 영상별 최대 표시 횟수 |

LLM_PROVIDER는 기본적으로 stub으로 두고, 실제 provider를 사용할 때 gemini·groq·auto와
각 provider의 키·모델·timeout을 함께 설정합니다. 로컬 quota 또는 provider 응답 오류가
발생하면 설정된 다음 provider로 전환한 뒤 stub fallback을 사용할 수 있습니다.

## 데이터베이스와 문서

- [문서 인덱스](docs/README.md)
- [온보딩 안내](docs/onboarding.md)
- [Supabase 로그인 연동](docs/auth-login.md)
- [데이터베이스 문서](docs/database/README.md)
- [현재 기준 스키마](docs/database/db_schema.sql)
- [DB migration 디렉터리](docs/migrations/)
- [Postman 사용 안내](postman/README.md)

사용자 소유 데이터는 Supabase RLS와 서버 측 소유권 검사를 기준으로 관리합니다.
DB 테이블·컬럼·RLS를 변경할 때는 기존 migration을 수정하지 말고 docs/migrations에 새 SQL을
추가한 뒤 db_schema.sql, repository, schema, 테스트를 함께 갱신합니다.

## 배포 확인

현재 Render 배포 주소는 [subsync-backend-4bmh.onrender.com](https://subsync-backend-4bmh.onrender.com/)입니다.

```
GET https://subsync-backend-4bmh.onrender.com/health
GET https://subsync-backend-4bmh.onrender.com/api/v1/dictionary/hover?word=honest
```

운영에서는 ENV=production과 필요한 Supabase·Redis·Dictionary·DeepL·LLM 환경변수를
Render에 설정합니다. 요청 문제가 재현되면 응답의 X-Request-ID와 Render 로그의
상관관계를 사용해 확인합니다. /health는 프로세스 상태만 확인하므로 외부 사전·번역
provider의 정상 여부까지 보장하지 않습니다.

## 변경 시 체크리스트

- API 변경: app/schemas, app/api/v1, OpenAPI, Postman Collection, tests를 함께 갱신합니다.
- DB 변경: docs/migrations에 새 SQL을 만들고 docs/database/db_schema.sql과 관련 코드를 갱신합니다.
- Tutor 변경: provider fallback, prompt 입력 분리, 대화 이력·사용량 제한을 확인합니다.
- 의존성 변경: uv add 또는 uv add --dev를 사용하고 uv.lock을 함께 갱신합니다.
- 커밋 전 git status, git diff, git diff --check로 의도하지 않은 변경과 secret을 확인합니다.
- 세부 협업 규칙은 [AGENTS.md](AGENTS.md)를 따릅니다.
