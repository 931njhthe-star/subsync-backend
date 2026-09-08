# Postman 빠른 실행

Postman을 처음 열어도 Tutor API를 바로 확인할 수 있도록, 실행용 예시만 담은
Collection을 제공한다.

## 구성 파일

- `SubSync-API.postman_collection.json`: Tutor와 Dashboard 조회 요청 및 자동 테스트 스크립트
- `SubSync-Local.postman_environment.json`: 선택 가능한 로컬 서버 주소 환경

## 실행 방법

1. FastAPI 서버를 실행한다.

   ```powershell
   uv run uvicorn app.main:app --reload --port 8000 --env-file .env
   ```

2. Postman에서 **Import**를 선택하고 위의 Collection JSON을 가져온다.
   `SubSync-Local.postman_environment.json`은 다른 서버 주소를 쓰고 싶을 때만 함께
   가져와 선택한다.
3. 왼쪽 Collection에서 **`▶ 바로 실행 — 이것만 Run`** 폴더를 선택한 뒤 **Run**을
   누른다.
4. **Run SubSync API - Quick Start**를 누른다.

환경 변수 입력 없이 다음 두 요청이 순서대로 실행되고 둘 다 통과하면 정상이다.

1. `1. 서버 연결 확인` — `/health`가 `200`인지 확인
2. `2. Tutor에게 자막 질문하기` — TED-Ed 자막 예시로 실제 Tutor 답변을 받는지 확인

`▶ 선택 기능 — 바로 실행 후 사용` 폴더에는 후속 대화, 선제 질문, 답변 평가와 중복 평가
거부 예시가 있다. 전체 Collection을 Run 하면 첫 Tutor 요청이 저장한
`conversation_id`와 `message_id`를 자동으로 이어서 사용한다.

`Dashboard — 운영 지표 조회` 폴더에는 Streamlit 화면에 연결할 다음 조회 API가 있다.

1. `GET /api/v1/dashboard/overview` — 두 테이블의 KPI와 최근 API 활동
2. `GET /api/v1/dashboard/usage` — `llm_usage`의 토큰·provider/model·일별 집계
3. `GET /api/v1/dashboard/api-calls` — `api_logs`의 endpoint·성공률·latency 집계

조회 기간은 `dashboard_days` Collection 변수를 사용하며 1~90일을 지원한다. Supabase
설정이 없는 로컬 환경에서는 정상 응답과 함께 빈 배열·0 집계가 반환된다.

## 인증 토큰 사용

현재 Tutor API에는 인증 dependency가 연결되어 있지 않으므로 토큰 없이 실행된다.
Supabase Auth를 도입하면 보호 API 요청에 다음 헤더를 추가한다.

```http
Authorization: Bearer <access_token>
```

Google OAuth 자체는 브라우저 로그인과 동의 화면이 포함되므로 Postman Collection에서
계정 로그인을 완전히 자동화하지 않는다. 로그인 후 발급된 Supabase Access Token으로
백엔드 API를 검증하는 방식이다.
