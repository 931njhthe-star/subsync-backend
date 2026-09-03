# SubSync Backend 협업 지침

> 최종 수정: 2026-09-03 (v1.1 — 에이전트 행동 원칙, Git 워크플로우, 관측성,
> AI 보안, DB 롤백 규칙 보강)
> 이 문서를 수정하면 상단의 날짜와 버전을 함께 갱신한다.

이 문서는 SubSync 백엔드를 작업하는 모든 사람과 에이전트의 공통 작업 계약이다.
목표는 담당자가 달라도 동일한 API 계약, 데이터 모델, 보안 수준, 검증 결과를
만드는 것이다. 구현 전에는 관련 문서를 읽고, 구현 후에는 이 문서의 완료 조건을
충족한다.

## 1. 프로젝트 기준

- 런타임: Python 3.11, FastAPI, `uv`
- 의존성 기준 파일: `pyproject.toml`, `uv.lock`
- API 기본 경로: `/api/v1` (`/health` 제외)
- 인증: Supabase Auth가 Google OAuth 및 세션을 관리한다. 보호 API는 Supabase Access
  Token(JWT)을 검증한 뒤 JWT의 `sub`를 사용자 ID로 사용한다.
- 데이터: Supabase PostgreSQL, 사용자별 데이터에는 RLS를 적용한다.
- AI Tutor: `app/ai/`에서 Gemini/Groq/stub provider를 다루며, 외부 provider가
  실패해도 안전한 fallback 동작을 유지한다.

다음 문서는 구현의 기준이다.

| 변경 영역 | 반드시 먼저 확인할 문서 |
| --- | --- |
| 모든 API 공통 규칙·인증·오류 | `docs/api/api_spec.md` |
| Video Tutor API | `docs/api/tutor_api_spec.md`, `docs/ai/ai-tutor.md` |
| DB 테이블·인덱스 | `docs/database/db_schema.sql` |
| 시스템/폴더 구조 | `docs/architecture/architecture.md`, `docs/architecture/subsync-architecture-guide.md` |
| 초보자 온보딩·AI 작업 요청 | `docs/onboarding.md`, `docs/prompts/feature-task.md` |
| Postman 사용 방법 | `postman/README.md` |

문서의 `IMPLEMENTED`, `PROPOSED`, `DEPENDENCY` 상태 표기를 실제 라우터 및 테스트와
일치시킨다. 아직 존재하지 않는 API를 `IMPLEMENTED`로 표시하지 않는다.

## 2. 폴더 책임 경계

```text
app/
├── api/v1/       HTTP 라우터: 입력 수신, dependency 주입, HTTP 상태 코드 반환
├── schemas/      Pydantic 요청·응답 DTO 및 유효성 검증
├── services/     인증·사전·단어장·로그 등 일반 도메인 비즈니스 로직
├── ai/           Tutor 문맥, 프로필, 프롬프트, provider, fallback, 사용량 처리
├── db/           Supabase 연결 및 repository/storage 구현
├── cache/        Redis 연결·캐시 정책
├── core/         환경 설정, 보안, 공통 인프라
└── main.py       앱 생성, 미들웨어, router 등록만 담당

tests/            pytest 단위·API 통합 테스트
docs/             팀이 합의한 계약 및 설계 문서
├── architecture/ 시스템 구조·레포지토리 설계
├── api/          공통 API·도메인 API 계약
├── ai/           AI Tutor 요구사항·설계
├── database/     Supabase 스키마·DB 문서
└── migrations/  적용 순서가 보존되는 DB 변경 SQL (DB 변경 시 생성)
docs/onboarding.md 온보딩 및 로컬 실행 절차
docs/prompts/     AI 코딩 작업 프롬프트 템플릿
postman/          공유 가능한 Collection·Environment JSON
dashboard/        Streamlit 운영·분석 화면
```

라우터에 DB/LLM 세부 로직을 넣지 않는다. 요청/응답 스키마는 `schemas/`에 두고,
외부 서비스 호출은 `ai/`, `db/`, `cache/` 또는 해당 service를 통해 수행한다.

## 3. 팀 담당 영역과 인수인계 계약

세 명의 기본 담당은 다음과 같다. 담당 영역의 코드를 우선 책임지되, 공통 계약을
바꾸거나 다른 담당 영역에 영향을 주는 변경은 구현 전에 해당 담당자와 공유한다.
에이전트가 담당 경계가 애매한 작업을 만났을 때의 처리 방법은 10절을 따른다.

| 담당자 | 주 담당 영역 | 기본 작업 폴더 | 책임 산출물 |
| --- | --- | --- | --- |
| **소예** | 사용자/DB 중심: Auth, User, Word Save, History, Feedback, Supabase | `app/core/`, `app/db/`, `app/models/`, `app/services/` 중 사용자·저장 영역 | Supabase Auth/JWT dependency, DB migration·RLS, 사용자 데이터 repository, 저장·조회 API |
| **서윤** | 콘텐츠/API 중심: Video, Subtitle, Script, Dictionary, Hover, Redis | `app/api/v1/`, `app/schemas/`, `app/services/` 중 콘텐츠·사전 영역, `app/cache/` | 콘텐츠/사전 API, 표준 자막 DTO, Redis cache 정책 및 fallback |
| **경락** | LLM + AI Tutor | `app/ai/`, `app/api/v1/tutor.py`, `app/schemas/tutor.py` | Tutor 문맥·프롬프트·provider/fallback, 대화 응답 계약, AI 사용량·품질 처리 |

### 담당 영역별 작업 규칙

- 소예는 사용자 비밀번호를 별도 저장하지 않고 Supabase `auth.users`를 기준으로
  사용자와 앱 데이터를 연결한다. 사용자 데이터의 소유권, RLS, migration SQL을 함께
  검토한다.
- 서윤은 자막과 콘텐츠의 원천 형식을 하나의 Pydantic DTO로 고정한다. Redis를 사용할
  때 cache key, TTL, miss 시 동작을 문서와 테스트에 남긴다.
- 경락은 외부 LLM을 기본 테스트에 직접 연결하지 않는다. `stub/fake` provider로
  Tutor 요청·응답·fallback을 재현할 수 있게 만들고, provider별 설정은 환경변수로
  분리한다.
- `app/main.py`, `app/core/config.py`, 공통 `app/schemas/`, `docs/`의 계약 문서,
  `pyproject.toml`, Postman 파일은 공유 영역이다. 담당자 단독으로 호환성을 깨는
  변경을 하지 않는다.

### 세 담당자 사이의 공통 데이터 계약

다음 값의 이름과 의미를 임의로 바꾸지 않는다. 변경이 필요하면 API 명세와 관련
테스트를 먼저 갱신하고 세 담당자에게 알린다.

```text
인증 → 모든 보호 API: Authorization: Bearer <Supabase access token>
사용자 식별 → 검증된 JWT의 sub (요청 body의 user_id 사용 금지)
자막 한 줄 → { video_id, time, en, ko }
Tutor 입력 → { user_id, video_id, timestamp, current_subtitle,
               nearby_subtitles, saved_words, learner_profile,
               conversation_history, user_message }
Tutor 출력 → { conversation_id, message_id, reply,
               suggested_questions, provider, model, usage }
Tutor 피드백 → 경락이 반환한 message_id를 기준으로 소예가 저장
```

서윤의 자막·사전 데이터는 경락의 Tutor 문맥 입력으로 전달되고, 소예의 저장 단어·
학습 이력은 경락의 학습자 프로필 입력으로 전달된다. 어느 한 영역이 아직 구현되지
않았으면 위 계약을 지키는 fixture/mock으로 먼저 연결하고, 임시 동작임을 문서와
테스트에 표시한다.

## 4. 공통 구현 규칙

### Python·FastAPI

- 타입 힌트를 작성하고, 외부 입력은 Pydantic 모델로 검증한다.
- **초심자도 처음 읽고 흐름을 따라갈 수 있도록 주석과 docstring을 작성한다.**
  - 공개 함수·클래스·라우터 함수에는 한 줄 이상의 docstring을 작성하고, 역할과
    입력/반환값, DB·캐시·외부 API 호출 같은 중요한 부작용을 설명한다.
  - 복잡한 조건문, 인증·권한 처리, 캐시 순서, 데이터 변환, fallback처럼 의도가 바로
    드러나지 않는 코드에는 코드 바로 위에 한국어 주석으로 **왜** 필요한지 적는다.
  - `# i를 1 증가`처럼 코드를 그대로 읽어 주는 주석은 피하고, 이름·구조만으로도
    의도가 명확한 짧은 코드에는 불필요한 주석을 추가하지 않는다.
  - 환경변수, API 필드, DB 컬럼, 외부 서비스의 의미가 처음 등장하는 위치에는
    용도와 예시를 함께 적는다. 비밀값 자체는 예시와 주석에도 넣지 않는다.
  - 기능을 수정할 때 기존 주석·docstring이 실제 동작과 다르면 반드시 함께 고친다.
- 비동기 외부 I/O에는 `async` API를 사용한다. 동기식·오래 걸리는 작업을 async
  라우터에서 직접 실행하지 않는다.
- 오류를 숨기거나 임의의 성공 응답으로 바꾸지 않는다. `HTTPException`과 API 명세의
  상태 코드/오류 형식을 따른다.
- 설정값과 비밀값은 `app/core/config.py` 및 환경변수에서만 읽는다. API 키, 토큰,
  서비스 키를 코드·테스트 fixture·문서 예시에 넣지 않는다.
- `main.py` 변경 시 새 라우터 등록, CORS, middleware 영향과 `/docs` OpenAPI 노출을
  확인한다.

### 인증·권한

- 보호 API는 공통 `get_current_user` dependency를 사용해 Bearer JWT를 검증한다.
- 사용자 ID는 요청 body/query의 `user_id`가 아니라 검증된 JWT의 `sub`만 사용한다.
- Refresh Token 및 `service_role` 키를 브라우저, Postman 컬렉션, 로그, 응답에 넣지
  않는다.
- Supabase `auth.users`와 연결되는 앱 테이블은 사용자 비밀번호를 중복 저장하지 않는다.
- 사용자 소유 데이터에는 RLS 정책과 서버 측 소유권 검사를 모두 고려한다.

### 로깅·관측성

- 로그는 구조화된 형식(JSON 또는 key=value)으로 남기고, 요청 단위로 상관관계를
  추적할 수 있는 `request_id`를 미들웨어에서 생성해 로그와 응답 헤더에 포함한다.
- 최소 기록 항목: 요청 경로, 메서드, 상태 코드, 처리 시간(ms), `request_id`,
  (인증된 요청이면) `sub` 앞부분만 마스킹한 사용자 식별자. 자막 원문, 사용자
  메시지 전체, provider 응답 원문, 토큰류는 로그에 남기지 않는다.
- 예외는 스택 트레이스를 서버 로그에는 남기되, 클라이언트 응답에는 API 명세가
  정의한 오류 형식만 노출한다.
- 로그 레벨 기준: 정상 요청은 INFO, 재시도된 provider 실패나 캐시 miss처럼 예상된
  이상 상황은 WARNING, 처리 불가능한 예외는 ERROR로 구분한다.
- 새 로그 필드를 추가하거나 형식을 바꾸면 관련 문서(`docs/architecture/architecture.md` 등)에
  반영해 다른 담당자가 같은 방식으로 파싱할 수 있게 한다.

### AI·외부 서비스

- 자막, 사용자 질문, 외부 API 응답은 신뢰할 수 없는 입력으로 취급한다.
- provider/model, timeout, quota, fallback 동작을 바꾸면 관련 환경변수와
  `docs/ai/ai-tutor.md`를 갱신한다.
- 실 API를 기본 테스트에 의존시키지 않는다. 기본 테스트는 stub/fake client로
  재현 가능해야 한다.
- provider 응답 원문, Access Token, 개인 식별 가능 정보는 로그에 남기지 않는다.
- **프롬프트 인젝션 방어**: 시스템 프롬프트(Tutor의 역할·규칙)와 사용자 입력
  (`user_message`, `current_subtitle`, `nearby_subtitles`)은 항상 구조적으로
  분리해서 provider에 전달한다. 자막이나 사용자 메시지 안에 "지시문처럼 보이는
  문장"(예: "이전 지시를 무시하고…")이 있어도 시스템 규칙보다 우선하지 않도록
  provider 호출 구조와 프롬프트 템플릿에서 강제한다.
- **대화 이력 관리**: `conversation_history`는 provider별 컨텍스트 한도를 넘지
  않도록 최근 N턴 또는 토큰 예산 기준으로 자르는 규칙을 두고, 자르는 기준(턴 수 또는
  토큰 수)을 `docs/ai/ai-tutor.md`에 명시한다.
- **사용량·비용 제어**: 사용자당/세션당 Tutor 호출 빈도 제한(rate limit)과 요청당
  최대 토큰 한도를 두고, 초과 시 반환할 오류 형식을 API 명세에 정의한다. `usage`
  필드는 기록용이며 제한 로직을 대체하지 않는다.

## 5. API 변경 규칙

새 API를 만들거나 기존 API의 경로, 메서드, 요청/응답 모델, 인증, 상태 코드, 동작을
변경하면 **아래 산출물을 같은 변경에 포함**한다.

1. `app/schemas/`에 요청·응답 DTO와 검증 규칙을 작성한다.
2. `app/api/v1/`에 라우터를 구현하고 `app/main.py`에 등록한다.
3. 도메인 로직은 `services/` 또는 `ai/`로 분리한다.
4. `docs/api/api_spec.md`와 해당 도메인 명세(예: `docs/api/tutor_api_spec.md`)에 경로, 인증,
   요청, 성공/실패 응답 예시, 구현 상태를 갱신한다.
5. `postman/SubSync-API.postman_collection.json`에 요청을 추가하거나 수정한다.
   - `{{base_url}}`, `{{access_token}}` 등 환경 변수를 사용한다.
   - 정상 응답과 대표적인 실패 응답(최소 401/403/404/422 중 해당 항목)을 검증하는
     Postman test script를 넣는다.
   - 환경 변수의 추가·이름 변경 시
     `postman/SubSync-Local.postman_environment.json` 및 `postman/README.md`도 갱신한다.
6. `tests/`에 정상 흐름과 권한/입력 검증/소유권 실패 테스트를 추가·수정한다.
7. 하위 호환이 깨지는 변경(필드 삭제·이름/타입 변경·요청 구조 변경)은 `/api/v2`로
   분리한다. 선택 필드 추가는 v1에서 가능하다.

API만 추가하고 명세, Postman Collection, 테스트 중 하나를 생략한 변경은 완료가 아니다.

## 6. DB 변경 규칙

테이블, 컬럼, 제약조건, 인덱스, RLS 정책, 함수·트리거를 바꾸면 **SQL을 반드시 남긴다.**

1. `docs/migrations/`에 적용 순서가 드러나는 새 migration을 만든다.
   - 파일명: `YYYYMMDDHHMM_짧은-변경-설명.sql`
   - 예: `202609031030_add_saved_words_status.sql`
   - 이미 공유/적용한 migration은 수정하지 않고 새 migration으로 보완한다.
2. migration에는 필요한 `CREATE/ALTER/DROP`, 인덱스, RLS enable/policy 변경을 모두
   포함한다. 가능한 경우 재실행 안전성을 고려한다.
3. 되돌릴 가능성이 있는 변경은 같은 migration 파일 하단에 되돌리기용 SQL(예:
   `-- ROLLBACK:` 주석 아래 역방향 `DROP/ALTER`)을 함께 남긴다. 데이터 삭제·컬럼
   삭제처럼 되돌릴 수 없는 변경은 되돌리기가 불가능함을 파일 상단 주석과 PR 설명에
   명시하고, 필요하면 되돌리기 대신 백업/백필 절차를 적는다.
4. 현재 전체 스키마의 기준 문서인 `docs/database/db_schema.sql`도 최종 상태로 갱신한다.
5. 데이터 이동·backfill·되돌리기 어려운 변경은 migration 상단 주석에 영향과 실행
   순서를 적고, PR 설명에도 명시한다.
6. DB 모델/repository, Pydantic 스키마, API 명세, 테스트를 함께 갱신한다.

Supabase Auth 연동 테이블은 `auth.users(id)`를 참조하고, RLS에서
`auth.uid() = user_id` 원칙을 적용한다. 운영 데이터 삭제, 대량 갱신, `DROP`은 적용 전
대상·복구 방법을 확인하고 팀에 공유한다.

## 7. 의존성·환경 변수 변경 규칙

- **불필요한 외부 라이브러리 참조를 지양한다.** 새 패키지를 추가하기 전에 Python 표준
  라이브러리, 이미 설치된 패키지, FastAPI/Pydantic의 내장 기능으로 해결할 수 있는지
  먼저 확인한다. 단순 유틸리티 하나를 위해 큰 프레임워크나 중복 기능의 패키지를
  추가하지 않는다.
- 새 패키지가 꼭 필요하면 PR에 필요 이유, 대체하지 않은 이유, 사용 범위, 라이선스·보안
  영향을 짧게 남긴다. 유지되지 않거나 출처가 불분명한 패키지는 사용하지 않는다.
- 패키지 추가/제거/업데이트는 `uv add <package>` 또는 `uv add --dev <package>`로 한다.
  `pip install`로만 설치하거나 `requirements.txt`를 새로 만들지 않는다.
- `pyproject.toml`이 바뀌면 생성된 `uv.lock`도 반드시 함께 커밋한다.
- 새 환경변수는 `app/core/config.py`, `.env.example`, `README.md`의 환경변수 목록,
  사용 문서에 함께 추가한다. 실제 비밀값은 `.env`에만 두며 커밋하지 않는다.
- `.env.example`을 도입하면 키 이름만 담고 실제 값은 절대 넣지 않는다.

## 8. 테스트와 검증

기본 검증 명령은 다음과 같다.

```bash
uv sync
uv run pytest
uv run uvicorn app.main:app --reload --port 8000
```

- 새 기능은 성공 경로뿐 아니라 유효하지 않은 입력, 인증 누락/실패, 권한/소유권 오류,
  외부 provider 실패처럼 해당 기능의 실패 경로도 테스트한다.
- AI/시간/난수/외부 네트워크에 의존하는 테스트는 fake, fixture, dependency override로
  결정적으로 만든다.
- Tutor의 rate limit·토큰 한도·대화 이력 자르기처럼 4절에서 추가한 제어 로직은
  경계값(한도 직전/직후)을 검증하는 테스트를 포함한다.
- Postman Collection은 실행 가능한 JSON으로 유지하고, API 변경 후 로컬 서버에서
  최소한 변경된 요청을 직접 확인한다.
- 코드와 문서 편집 후 `git diff --check`를 실행한다.

## 9. Git과 협업 방식

- 한 작업은 하나의 목적에 집중한다. 다른 담당자의 파일을 무관하게 포맷하거나
  되돌리지 않는다.
- 브랜치는 `main`에 직접 커밋하지 않고 작업 단위로 분리한다. 이름은
  `feat/짧은-설명`, `fix/짧은-설명`, `docs/짧은-설명` 형식을 따른다.
- 커밋 전 `git status`, `git diff`로 의도하지 않은 파일·비밀값·빌드 산출물이 없는지
  확인한다.
- 커밋 메시지는 명령형으로 간결하게 작성한다. 예: `feat: add tutor feedback endpoint`
- 공유 파일(`app/main.py`, `app/core/config.py`, `docs/api/api_spec.md`, `docs/database/db_schema.sql`,
  `pyproject.toml`, Postman Collection)은 충돌 가능성이 높으므로 수정 범위를 작게 하고
  변경 이유를 PR에 남긴다.
- 공유 파일을 수정하는 PR은 해당 파일의 원 담당자(또는 영향받는 담당자) 리뷰를
  받은 뒤 병합한다. 담당 영역 내부만 수정하는 PR도 병합 전 최소 1인 리뷰를
  권장한다.
- API 계약이나 DB 구조가 바뀌면 구현 전에 팀에 공유하고, 프론트엔드가 사용할 수 있는
  상태인지 `IMPLEMENTED` 표기로 명확히 알린다.

## 10. 에이전트 작업 원칙

이 절은 사람 대신 코드를 작성·수정하는 에이전트(Claude Code 등)에게만 적용되는
행동 기준이다. 나머지 절의 규칙을 "무엇을 만들지"에 대한 계약이라면, 이 절은
"판단이 애매할 때 어떻게 행동할지"에 대한 계약이다.

- **담당 경계가 애매한 작업**: 요청한 작업이 한 사람의 주 담당 폴더를 벗어나거나
  공유 파일(9절 참고)을 수정해야 끝나는 경우, 에이전트는 임의로 다른 담당자의
  도메인 로직·스키마를 새로 설계하지 않는다. 대신 (1) 현재 상태를 그대로 두고
  fixture/mock으로 3절의 공통 데이터 계약에 맞춰 연결하거나, (2) 필요한 변경
  내용을 코드 대신 PR 설명이나 이슈로 남기고 작업을 멈춘 뒤 사람에게 확인을
  요청한다.
- **명세와 실제 요구사항이 다를 때**: `docs/`의 명세와 작업 지시가 충돌하면
  추측으로 하나를 선택해 진행하지 않는다. 충돌 내용을 구체적으로 설명하고 확인을
  요청한다. 단, 명세의 오탈자나 명백한 상태 표기 오류(`IMPLEMENTED`인데 라우터가
  없는 경우 등)는 고치면서 진행하되 어떤 근거로 고쳤는지 남긴다.
- **되돌리기 어려운 작업 전 확인**: 운영 데이터 삭제, 이미 적용된 migration 수정,
  `git push --force`, 다른 담당자의 브랜치 재작성처럼 되돌리기 어려운 작업은
  실행 전에 반드시 확인을 받는다.
- **범위를 넘어서는 개선 금지**: 요청받지 않은 리팩터링, 무관한 파일 포맷팅,
  요청 범위를 넘는 패키지 교체는 하지 않는다. 개선이 필요하다고 판단되면 별도로
  제안만 남긴다.
- **완료 보고의 정직성**: 테스트를 실행하지 못했거나 일부 체크리스트 항목을
  건너뛴 경우, 완료됐다고 보고하지 않고 무엇을 왜 못 했는지 그대로 남긴다.

## 11. 작업 완료 체크리스트

작업을 완료하기 전 해당 항목을 확인한다.

- [ ] 코드가 책임 경계에 맞게 배치되어 있다. 경계가 애매했다면 10절에 따라
  처리했다.
- [ ] 공개 함수·클래스·라우터에 초심자도 이해할 수 있는 docstring이 있고, 복잡한
  로직에는 "왜"를 설명하는 최신 주석이 있다.
- [ ] API 변경이면 명세, Postman Collection, 테스트가 함께 갱신되었다.
- [ ] DB 변경이면 migration SQL(가능하면 되돌리기 SQL 포함), `db_schema.sql`,
  RLS/인덱스, 관련 테스트가 갱신되었다.
- [ ] 인증이 필요한 기능은 JWT `sub` 기반 사용자 식별과 소유권 검증을 사용한다.
- [ ] Tutor 관련 변경이면 프롬프트 인젝션 방어, 대화 이력 자르기, 사용량 제한
  로직에 영향이 없는지 확인했다.
- [ ] 새 로그 필드나 형식 변경이 있으면 문서에 반영했고, 민감정보(원문 메시지,
  토큰, PII)는 로그에 남지 않는다.
- [ ] 새 외부 라이브러리의 필요성과 기존/표준 기능으로 대체할 수 없는 이유를 확인했다.
- [ ] 새 패키지는 `uv`로 추가되었고 `uv.lock`이 갱신되었다.
- [ ] 새 설정값은 환경변수와 문서에 반영되었으며 비밀값은 커밋되지 않았다.
- [ ] `uv run pytest`와 `git diff --check`를 실행했거나, 실행할 수 없었던 이유를 기록했다.
- [ ] 공유 파일을 수정했다면 관련 담당자 리뷰를 받았거나 요청해 두었다.
- [ ] 문서의 구현 상태와 실제 동작이 일치한다.
