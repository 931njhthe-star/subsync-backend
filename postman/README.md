# Postman API 테스트

현재 구현된 FastAPI API를 Postman에서 바로 실행할 수 있도록 Collection과 로컬 환경을
제공한다.

## 구성 파일

- `SubSync-API.postman_collection.json`: 요청과 자동 테스트 스크립트
- `SubSync-Local.postman_environment.json`: 로컬 서버 주소와 선택적 Supabase Access Token

## 실행 방법

1. FastAPI 서버를 실행한다.

   ```powershell
   uv run uvicorn app.main:app --reload --port 8000 --env-file .env
   ```

2. Postman에서 **Import**를 선택하고 위의 Collection JSON과 Environment JSON을 각각
   가져온다.
3. 환경을 `SubSync Local`로 선택한다.
4. Collection의 **Run**을 선택한다.
5. 모든 요청을 실행하면 Health, 정상 Tutor 요청, 대화 이력 요청, 422 validation 요청을
   순서대로 확인할 수 있다.

## 인증 토큰 사용

현재 `/api/v1/tutor/ask`에는 인증 dependency가 연결되어 있지 않으므로 토큰 없이도
테스트된다. Supabase Auth 연동 후에는 `SubSync Local` 환경의 `access_token`에 Access
Token을 입력하면 Collection의 사전 요청 스크립트가 다음 헤더를 자동으로 추가한다.

```http
Authorization: Bearer <access_token>
```

Google OAuth 자체는 브라우저 로그인과 동의 화면이 포함되므로 Postman Collection에서
계정 로그인을 완전히 자동화하지 않는다. 로그인 후 발급된 Supabase Access Token으로
백엔드 API를 검증하는 방식이다.
