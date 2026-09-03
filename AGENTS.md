# SubSync Backend 협업 지침

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
| 모든 API 공통 규칙·인증·오류 | `docs/api_spec.md` |
| Video Tutor API | `docs/tutor_api_spec.md`, `docs/ai-tutor.md` |
| DB 테이블·인덱스 | `docs/db_schema.sql` |
| 시스템/폴더 구조 | `docs/architecture.md`, `docs/subsync-architecture-guide.md` |
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
docs/migrations/  적용 순서가 보존되는 DB 변경 SQL (DB 변경 시 생성)
postman/          공유 가능한 Collection·Environment JSON
dashboard/        Streamlit 운영·분석 화면
```

라우터에 DB/LLM 세부 로직을 넣지 않는다. 요청/응답 스키마는 `schemas/`에 두고,
외부 서비스 호출은 `ai/`, `db/`, `cache/` 또는 해당 service를 통해 수행한다.

## 3. 공통 구현 규칙

### Python·FastAPI

- 타입 힌트를 작성하고, 외부 입력은 Pydantic 모델로 검증한다.
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

### AI·외부 서비스

- 자막, 사용자 질문, 외부 API 응답은 신뢰할 수 없는 입력으로 취급한다.
- provider/model, timeout, quota, fallback 동작을 바꾸면 관련 환경변수와
  `docs/ai-tutor.md`를 갱신한다.
- 실 API를 기본 테스트에 의존시키지 않는다. 기본 테스트는 stub/fake client로
  재현 가능해야 한다.
- provider 응답 원문, Access Token, 개인 식별 가능 정보는 로그에 남기지 않는다.

## 4. API 변경 규칙

새 API를 만들거나 기존 API의 경로, 메서드, 요청/응답 모델, 인증, 상태 코드, 동작을
변경하면 **아래 산출물을 같은 변경에 포함**한다.

1. `app/schemas/`에 요청·응답 DTO와 검증 규칙을 작성한다.
2. `app/api/v1/`에 라우터를 구현하고 `app/main.py`에 등록한다.
3. 도메인 로직은 `services/` 또는 `ai/`로 분리한다.
4. `docs/api_spec.md`와 해당 도메인 명세(예: `docs/tutor_api_spec.md`)에 경로, 인증,
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

## 5. DB 변경 규칙

테이블, 컬럼, 제약조건, 인덱스, RLS 정책, 함수·트리거를 바꾸면 **SQL을 반드시 남긴다.**

1. `docs/migrations/`에 적용 순서가 드러나는 새 migration을 만든다.
   - 파일명: `YYYYMMDDHHMM_짧은-변경-설명.sql`
   - 예: `202609031030_add_saved_words_status.sql`
   - 이미 공유/적용한 migration은 수정하지 않고 새 migration으로 보완한다.
2. migration에는 필요한 `CREATE/ALTER/DROP`, 인덱스, RLS enable/policy 변경을 모두
   포함한다. 가능한 경우 재실행 안전성을 고려한다.
3. 현재 전체 스키마의 기준 문서인 `docs/db_schema.sql`도 최종 상태로 갱신한다.
4. 데이터 이동·backfill·되돌리기 어려운 변경은 migration 상단 주석에 영향과 실행
   순서를 적고, PR 설명에도 명시한다.
5. DB 모델/repository, Pydantic 스키마, API 명세, 테스트를 함께 갱신한다.

Supabase Auth 연동 테이블은 `auth.users(id)`를 참조하고, RLS에서
`auth.uid() = user_id` 원칙을 적용한다. 운영 데이터 삭제, 대량 갱신, `DROP`은 적용 전
대상·복구 방법을 확인하고 팀에 공유한다.

## 6. 의존성·환경 변수 변경 규칙

- 패키지 추가/제거/업데이트는 `uv add <package>` 또는 `uv add --dev <package>`로 한다.
  `pip install`로만 설치하거나 `requirements.txt`를 새로 만들지 않는다.
- `pyproject.toml`이 바뀌면 생성된 `uv.lock`도 반드시 함께 커밋한다.
- 새 환경변수는 `app/core/config.py`, `README.md`의 환경변수 목록, 사용 문서에 함께
  추가한다. 실제 비밀값은 `.env`에만 두며 커밋하지 않는다.
- `.env.example`을 도입하면 키 이름만 담고 실제 값은 절대 넣지 않는다.

## 7. 테스트와 검증

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
- Postman Collection은 실행 가능한 JSON으로 유지하고, API 변경 후 로컬 서버에서
  최소한 변경된 요청을 직접 확인한다.
- 코드와 문서 편집 후 `git diff --check`를 실행한다.

## 8. Git과 협업 방식

- 한 작업은 하나의 목적에 집중한다. 다른 담당자의 파일을 무관하게 포맷하거나
  되돌리지 않는다.
- 커밋 전 `git status`, `git diff`로 의도하지 않은 파일·비밀값·빌드 산출물이 없는지
  확인한다.
- 커밋 메시지는 명령형으로 간결하게 작성한다. 예: `feat: add tutor feedback endpoint`
- 공유 파일(`app/main.py`, `app/core/config.py`, `docs/api_spec.md`, `docs/db_schema.sql`,
  `pyproject.toml`, Postman Collection)은 충돌 가능성이 높으므로 수정 범위를 작게 하고
  변경 이유를 PR에 남긴다.
- API 계약이나 DB 구조가 바뀌면 구현 전에 팀에 공유하고, 프론트엔드가 사용할 수 있는
  상태인지 `IMPLEMENTED` 표기로 명확히 알린다.

## 9. 작업 완료 체크리스트

작업을 완료하기 전 해당 항목을 확인한다.

- [ ] 코드가 책임 경계에 맞게 배치되어 있다.
- [ ] API 변경이면 명세, Postman Collection, 테스트가 함께 갱신되었다.
- [ ] DB 변경이면 migration SQL, `db_schema.sql`, RLS/인덱스, 관련 테스트가 갱신되었다.
- [ ] 인증이 필요한 기능은 JWT `sub` 기반 사용자 식별과 소유권 검증을 사용한다.
- [ ] 새 패키지는 `uv`로 추가되었고 `uv.lock`이 갱신되었다.
- [ ] 새 설정값은 환경변수와 문서에 반영되었으며 비밀값은 커밋되지 않았다.
- [ ] `uv run pytest`와 `git diff --check`를 실행했거나, 실행할 수 없었던 이유를 기록했다.
- [ ] 문서의 구현 상태와 실제 동작이 일치한다.
