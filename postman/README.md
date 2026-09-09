# Postman 빠른 실행

Postman을 처음 열어도 Tutor API를 바로 확인할 수 있도록, 실행용 예시만 담은
Collection을 제공한다.

## 구성 파일

- `SubSync-API.postman_collection.json`: Tutor와 Dashboard 조회 요청 및 자동 테스트 스크립트
- `SubSync-Local.postman_environment.json`: 선택 가능한 로컬 서버 주소 환경

`Dictionary — Hover 호환 확인` 폴더에서는 Extension이 실제로 사용하는
`/api/v1/dict/hover` 경로와 빈 검색어 422 응답을 확인할 수 있습니다.

## 실행 방법

1. FastAPI 서버를 실행한다.

   ```powershell
   uv run uvicorn app.main:app --reload --port 8000
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

`▶ 저장 단어 — OAuth 연결 전 개발용` 폴더는 Google OAuth가 아직 연결되지 않은
상태에서 저장 단어 API를 확인할 때 사용한다. Collection 변수 `dev_user_id`를
Supabase `public.users`에 실제로 존재하는 UUID로 바꾼 뒤 저장·조회·삭제 요청을
순서대로 실행한다. 이 임시 header 방식은 개발 환경에서만 동작하며, OAuth 연동 후에는
`Authorization: Bearer <access_token>` 방식으로 교체한다.

선제 질문 답변은 4번 요청의 `question_id`를 5번 요청의
`proactive_question_id`로 전달해야 한다. 일반 Tutor 질문은 pending 선제 질문이
있어도 채점 모드로 바뀌지 않으며, 선제 질문은 표시 후 30초가 지나면 만료된다.

`Dashboard — 운영 지표 조회` 폴더에는 Streamlit 화면에 연결할 다음 조회 API가 있다.

1. `GET /api/v1/dashboard/overview` — KPI·일별 AI 사용량·최근 AI/API 활동·사용자 목록
2. `GET /api/v1/dashboard/usage` — 토큰·provider/model·오류율·P95·상세 요청 내역
3. `GET /api/v1/dashboard/api-calls` — endpoint·성공률·P95·전체 호출·상태 코드 집계

기본 요청은 `dashboard_days` Collection 변수를 사용하며 1~90일을 지원한다.
Streamlit처럼 달력의 정확한 날짜를 조회할 때는 `from_date=YYYY-MM-DD`와
`to_date=YYYY-MM-DD`를 함께 사용한다. `user_id`, `model_name`, `api_name`을
추가하면 해당 필터가 적용된다. Supabase 설정이 없는 로컬 환경에서는 정상 응답과
함께 빈 배열·0 집계가 반환된다.


## 인증 토큰 사용

Tutor API는 로그인 없이 실행된다. 로그인 동기화는 선택 폴더의 7~9번 요청이다.

1. 확장 프로그램에서 Google 로그인한다.
2. `chrome.storage.local`의 `subsync_token` 또는 세션 `access_token`을 복사한다.
3. Collection 변수 `access_token`에 넣는다. `service_role` 키는 넣지 않는다.
4. `7. 로그인 세션 확인`을 실행하면 `public.users`와 `login_history`가 채워진다.

```http
Authorization: Bearer <access_token>
```

토큰이 없으면 `GET /api/v1/auth/me`는 401이다. Google OAuth 창은 Postman에서
자동화하지 않는다.
