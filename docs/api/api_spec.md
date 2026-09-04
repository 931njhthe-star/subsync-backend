# SubSync API 공통 명세서

이 문서는 SubSync 백엔드 API에서 모든 도메인이 공통으로 사용하는 접속 정보,
요청·응답 형식, 인증, 오류, 보안 규칙을 정의한다.

도메인별 API 명세서는 별도 문서로 관리한다.

- [Video Tutor API 명세서](./tutor_api_spec.md)
- [AI Tutor 요구사항 정리](../ai/ai_tutor_requirements.md)

실제 구현 여부는 각 도메인 문서의 상태 표기와 현재 FastAPI 소스 코드를 기준으로
판단한다.

## 1. 구현 상태 표기

| 표기 | 의미 |
| --- | --- |
| `IMPLEMENTED` | 현재 FastAPI 소스에 등록되어 테스트 가능한 API |
| `PROPOSED` | 요구사항 충족을 위해 추가 개발할 API 계약 |
| `DEPENDENCY` | 다른 도메인 기능을 위해 필요한 연동 API |

문서에 정의된 `PROPOSED` API는 라우터가 실제로 등록되기 전까지 프론트엔드에서
호출하지 않는다.

## 2. 접속 정보와 API 버전

### 2.1 기본 URL

```text
로컬:    http://127.0.0.1:8000
Swagger: http://127.0.0.1:8000/docs
OpenAPI: http://127.0.0.1:8000/openapi.json
```

실제 실행 포트나 배포 주소가 달라지면 `base_url`만 변경한다.

### 2.2 버전 경로

현재 도메인 API의 기본 경로는 다음과 같다.

```text
API v1: http://127.0.0.1:8000/api/v1
```

`v1`은 API 계약의 첫 번째 버전이다. 기존 클라이언트와의 호환성을 유지하면서
요청·응답 구조를 크게 변경해야 할 때 `/api/v2`를 추가할 수 있다.

- 선택 필드 추가처럼 하위 호환이 가능한 변경은 기존 버전에 반영한다.
- 필드 삭제·이름 변경, 타입 변경, 요청 구조 변경처럼 기존 클라이언트를 깨뜨리는
  변경은 새 버전으로 분리한다.
- `/health`는 서버 상태 확인용 공통 엔드포인트로 현재 버전 경로 밖에 둔다.

## 3. 공통 요청·응답 규칙

### 3.1 헤더

JSON을 사용하는 요청은 다음 헤더를 사용한다.

```http
Content-Type: application/json
Accept: application/json
```

인증이 필요한 API는 `Authorization` 헤더를 추가한다.

```http
Authorization: Bearer <supabase_access_token>
```

### 3.2 로컬 Chrome Extension CORS

Chrome Extension의 content script는 실행 중인 YouTube 페이지에서 동작하므로 로컬 FastAPI
호출의 origin이 `https://www.youtube.com`으로 보일 수 있다. JSON 요청 전에 발생하는
`OPTIONS` preflight를 위해 개발 서버는 `chrome-extension://<extension_id>`,
`https://www.youtube.com`, `localhost`/`127.0.0.1`의 로컬 포트를 허용한다. 운영 배포에서는
실제 Extension origin과 대시보드 origin만 별도로 허용하고, 임의의 origin을 열지 않는다.

### 3.3 데이터 형식

- 문자 인코딩은 UTF-8이다.
- 요청·응답 본문은 기본적으로 JSON이다.
- 모든 ID는 JSON에서 문자열로 표현한다.
- 서버가 생성하는 시각은 ISO 8601 형식의 UTC 시각을 사용한다. 예: `2026-09-03T12:00:00Z`
- `null`은 값이 없거나 아직 생성되지 않은 상태를 의미한다.
- 페이지네이션이 필요한 목록 API는 도메인 문서에서 `limit`, `cursor` 등의 세부 계약을
  별도로 정의한다.

### 3.4 응답 구조

성공 응답은 각 도메인의 리소스 구조를 그대로 반환하며, 모든 API에 임의의 공통
`data` 래퍼를 강제하지 않는다. 오류 응답만 아래의 공통 형식을 사용한다.

## 4. 인증과 세션

### 4.1 인증 방식

Supabase Auth가 Google 로그인과 Access/Refresh Token 발급·갱신을 담당한다.
백엔드는 인증이 필요한 요청에서 다음 절차를 수행한다.

1. `Authorization: Bearer <access_token>` 헤더를 확인한다.
2. Supabase JWT의 서명과 만료 시간을 검증한다.
3. 검증된 토큰의 `sub`를 사용자 ID로 사용한다.
4. 요청 본문에 전달된 `user_id`는 소유권 판단에 사용하지 않는다.

Refresh Token 원문을 백엔드 API 요청이나 일반 로그에 포함하지 않는다. 토큰 갱신은
Supabase 클라이언트의 세션 관리 흐름을 사용한다.

### 4.2 공개·보호 API

| 구분 | 인증 헤더 | 예시 |
| --- | --- | --- |
| 공개 API | 불필요 | `GET /health` |
| 보호 API | 필요 | 도메인별 사용자 데이터 조회·생성 API |

현재 구현 상태에서 인증 dependency가 아직 연결되지 않은 API는 해당 도메인 문서에
명시한다. 인증 연동 후에는 보호 API에 Bearer Token 검증을 적용한다.

## 5. 공통 오류 응답

### 5.1 일반 오류

```json
{
  "detail": "오류 설명"
}
```

### 5.2 요청 검증 오류

FastAPI와 Pydantic의 요청 검증 오류는 다음 형태를 사용한다.

```json
{
  "detail": [
    {
      "loc": ["body", "field_name"],
      "msg": "Input should be greater than or equal to 0",
      "type": "greater_than_equal"
    }
  ]
}
```

### 5.3 주요 상태 코드

| 상태 코드 | 의미 |
| --- | --- |
| `200` | 정상 처리 |
| `201` | 리소스 생성 완료 |
| `204` | 응답 본문 없는 정상 처리 |
| `400` | 형식은 맞지만 처리할 수 없는 요청 |
| `401` | Access Token 없음·만료·변조 |
| `403` | 인증은 되었지만 권한 없음 |
| `404` | 요청한 리소스 없음 |
| `409` | 현재 리소스 상태와 요청이 충돌함 |
| `422` | 요청 DTO 검증 실패 |
| `429` | 요청 빈도 또는 외부 서비스 사용량 제한 초과 |
| `503` | 외부 인증·DB·LLM 등 의존 서비스 일시 장애 |

## 6. 공통 보안 규칙

1. 사용자 식별자는 클라이언트가 보낸 `user_id`가 아니라 검증된 JWT의 `sub`를 사용한다.
2. 사용자별 데이터에는 `auth.uid() = user_id` 형태의 Supabase RLS 정책을 적용한다.
3. `service_role` 키는 일반 사용자 요청 처리에 사용하지 않는다.
4. Access Token과 Refresh Token 원문을 DB, 로그, 응답 URL에 저장하지 않는다.
5. 자막, 사용자 질문, 외부 연동 데이터는 신뢰할 수 없는 입력으로 취급한다.
6. 사용자 입력을 SQL, HTML, 로그 포맷에 직접 삽입하지 않고 각 계층의 안전한 인코딩·바인딩
   방식을 사용한다.

## 7. Health Check — `IMPLEMENTED`

### `GET /health`

서버 프로세스가 HTTP 요청을 받을 수 있는지만 확인한다. Supabase, Redis, LLM과 같은
외부 의존 서비스의 연결 상태까지 검사하지 않는다.

### 인증

불필요하다.

### 응답 `200 OK`

```json
{
  "status": "ok"
}
```

## 8. 문서 관리 원칙

- 라우터에 실제 등록된 API는 `IMPLEMENTED`로 표시한다.
- 요구사항에는 필요하지만 아직 구현되지 않은 API는 `PROPOSED`로 표시한다.
- `PROPOSED` API를 구현하면 실제 Pydantic 스키마, 상태 코드, 응답 예시를 검증한 뒤
  `IMPLEMENTED`로 변경한다.
- 공통 규칙 변경 시 도메인 문서의 중복 설명도 함께 확인한다.
