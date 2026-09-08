# Postman 빠른 실행

Postman을 처음 열어도 Tutor API를 바로 확인할 수 있도록, 실행용 예시만 담은
Collection을 제공한다.

## 구성 파일

- `SubSync-API.postman_collection.json`: 바로 실행할 6개 요청과 자동 테스트 스크립트
- `SubSync-Local.postman_environment.json`: 선택 가능한 로컬 서버 주소 환경

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
