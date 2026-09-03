# SubSync REST API 명세서

현재 저장소에 실제로 등록된 FastAPI 라우트와 Pydantic 스키마를 기준으로 작성한 문서다.

## 공통 정보

- 로컬 Base URL: `http://127.0.0.1:8000`
- API v1 Base URL: `http://127.0.0.1:8000/api/v1`
- 요청/응답 형식: `application/json; charset=utf-8`
- Swagger UI: `http://127.0.0.1:8000/docs`
- Google 로그인과 Access/Refresh Token 발급은 Supabase Auth와 프론트 클라이언트가 담당한다.
- 인증이 필요한 API는 `Authorization: Bearer <Supabase Access Token>` 헤더를 요구한다.
- FastAPI는 Access Token을 검증한 뒤 JWT의 `sub`를 사용자 ID로 사용한다.

## 현재 구현된 엔드포인트

| Method | Path | 인증 | 설명 |
| --- | --- | --- | --- |
| `GET` | `/health` | 불필요 | 서버 상태 확인 |
| `GET` | `/api/v1/auth/me` | 필요 | 현재 인증 사용자 확인 |
| `POST` | `/api/v1/tutor/ask` | 필요 | 영상 자막 문맥 기반 Tutor 질문 |

---

## 1. Health Check

### `GET /health`

서버 프로세스가 요청을 받을 수 있는지 확인한다. 외부 LLM, DB, Redis 상태까지 검사하지는
않는다.

### 응답 `200 OK`

```json
{
  "status": "ok"
}
```

---

## 2. 현재 사용자 확인

### `GET /api/v1/auth/me`

Supabase Access Token을 검증하고 현재 로그인한 사용자의 최소 식별 정보를 반환한다.
Google 로그인 화면이나 토큰 발급은 이 API가 담당하지 않는다.

### 요청 헤더

```http
Authorization: Bearer <supabase_access_token>
```

### 응답 `200 OK`

```json
{
  "user_id": "7b5d2f32-1234-4f4a-8abc-123456789abc",
  "email": "learner@example.com",
  "role": "authenticated",
  "session_id": null
}
```

`session_id`는 비대칭 JWT claim에 포함된 경우에만 반환된다. Supabase Auth 검증 API
방식에서는 `null`일 수 있다.

### 응답 `401 Unauthorized`

토큰이 없거나 만료·변조되었거나 발급자 또는 대상이 올바르지 않은 경우 반환한다.

```json
{
  "detail": "유효하지 않거나 만료된 Access Token입니다."
}
```

### 응답 `503 Service Unavailable`

서버에 Supabase Auth 설정이 없거나 JWKS/Auth 검증 서버에 일시적으로 접근할 수 없는
경우 반환한다.

---

## 3. Video Tutor 질문

### `POST /api/v1/tutor/ask`

현재 영상 시점의 자막과 사용자의 학습 행동 데이터를 이용해 Tutor 답변을 생성한다.

### 요청 헤더

```http
Content-Type: application/json
Authorization: Bearer <supabase_access_token>
```

### 요청 본문

| 필드 | 타입 | 필수 | 제한/기본값 |
| --- | --- | --- | --- |
| `video_id` | string | 예 | 1~50자 |
| `timestamp` | number | 예 | 0 이상, 초 단위 |
| `user_message` | string | 예 | 1~2,000자 |
| `recent_subtitles` | array | 아니오 | 최대 100개, 기본값 `[]` |
| `learner_signals` | object | 아니오 | 기본값 `{}` |
| `conversation_history` | array | 아니오 | 최대 10개, 기본값 `[]` |
| `focus_word` | string/null | 아니오 | 최대 100자, 기본값 `null` |

#### `recent_subtitles` 원소

| 필드 | 타입 | 필수 | 제한/기본값 |
| --- | --- | --- | --- |
| `time` | number | 예 | 0 이상, 초 단위 |
| `en` | string | 예 | 1~500자 |
| `ko` | string/null | 아니오 | 최대 500자, 기본값 `null` |

#### `learner_signals`

| 필드 | 타입 | 필수 | 제한/기본값 |
| --- | --- | --- | --- |
| `saved_words` | array | 아니오 | 최대 500개, 기본값 `[]` |
| `saved_word_count` | integer/null | 아니오 | 0~100,000, 기본값 `null` |
| `quiz_accuracy` | number/null | 아니오 | 0~1, 기본값 `null` |
| `average_response_time_ms` | number/null | 아니오 | 0~300,000, 기본값 `null` |
| `recent_quiz_accuracy` | number/null | 아니오 | 0~1, 기본값 `null` |
| `recent_response_time_ms` | number/null | 아니오 | 0~300,000, 기본값 `null` |
| `quiz_attempts` | integer | 아니오 | 0~100,000, 기본값 `0` |

`saved_words`의 원소는 다음 형식이다.

```json
{
  "word": "honest"
}
```

#### `conversation_history` 원소

```json
{
  "role": "user",
  "message": "이 표현을 다른 상황에서도 사용할 수 있나요?"
}
```

`role`은 `user` 또는 `tutor`만 허용한다.

### 요청 예시

```json
{
  "video_id": "arj7oStGLkU",
  "timestamp": 156.4,
  "user_message": "방금 나온 'be honest with'는 언제 주로 쓰나요?",
  "recent_subtitles": [
    {
      "time": 150.0,
      "en": "I know it sounds crazy.",
      "ko": "말도 안 되게 들리겠지만요."
    },
    {
      "time": 156.4,
      "en": "I want to be honest with you.",
      "ko": "솔직하게 말씀드리고 싶어요."
    }
  ],
  "learner_signals": {
    "saved_words": [
      { "word": "honest" }
    ],
    "quiz_accuracy": 0.72,
    "average_response_time_ms": 7500,
    "quiz_attempts": 6
  },
  "conversation_history": [],
  "focus_word": "honest"
}
```

### 내부 처리

1. `timestamp` 주변의 자막을 최대 7줄로 구성한다.
2. 저장 단어, 퀴즈 정답률, 평균 응답 시간을 이용해 내부 CEFR 수준을 추론한다.
3. 현재 기준 가중치는 정답률 55%, 응답 시간 25%, 저장 단어 수 20%다.
4. 데이터가 부족하면 A2/`guided`를 기본값으로 사용하고, 퀴즈 시도 횟수로 confidence를
   보정한다.
5. 설정된 LLM provider를 순서대로 호출한다.

Provider 순서는 `LLM_PROVIDER` 값에 따라 다음과 같다.

| `LLM_PROVIDER` | 호출 순서 |
| --- | --- |
| `stub` | Rule-based stub |
| `gemini` | Gemini → Groq → stub |
| `auto` | Gemini → Groq → stub |
| `groq` | Groq → Gemini → stub |

API key가 없는 provider는 건너뛴다. provider가 `429`를 반환하거나 로컬 token guard에
도달하면 다음 provider를 시도한다. 모든 외부 provider가 실패하면 stub 응답을 반환한다.

### 응답 `200 OK`

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `conversation_id` | string | 현재 대화 식별자. 현재는 영구 저장하지 않는다. |
| `message_id` | string | 현재 답변 식별자. 현재는 영구 저장하지 않는다. |
| `reply` | string | Tutor 답변 |
| `suggested_questions` | array[string] | 후속 질문 최대 3개 |
| `provider` | string | 실제 답변에 사용된 provider: `gemini`, `groq`, `stub` |
| `model` | string | 실제 사용 모델명 |
| `usage` | object | provider 응답에서 정규화한 토큰 사용량 |
| `learner_level` | string | `A1`, `A2`, `B1`, `B2`, `C1` |
| `tutor_difficulty` | string | 내부 Tutor 난이도 |
| `profile_confidence` | number | 0~1 사이의 수준 추론 신뢰도 |
| `context_subtitle_count` | integer | 답변에 사용한 주변 자막 수 |

`usage`는 다음 형식이다.

```json
{
  "input_tokens": 642,
  "output_tokens": 118,
  "total_tokens": 760
}
```

stub 응답은 실제 LLM token usage가 없으므로 usage 값이 0이다.

### 응답 예시

```json
{
  "conversation_id": "conv_49a1d",
  "message_id": "msg_001",
  "reply": "'be honest with'는 상대방에게 솔직하게 말하거나 진실을 숨기지 않을 때 사용해요. 이 자막에서는 '너에게 솔직해지고 싶다'는 의미입니다.",
  "suggested_questions": [
    "비슷한 다른 표현은 없나요?",
    "예문을 더 보여줘"
  ],
  "provider": "groq",
  "model": "openai/gpt-oss-20b",
  "usage": {
    "input_tokens": 642,
    "output_tokens": 118,
    "total_tokens": 760
  },
  "learner_level": "A2",
  "tutor_difficulty": "guided",
  "profile_confidence": 0.31,
  "context_subtitle_count": 2
}
```

### 유효성 검증 실패 `422 Unprocessable Entity`

FastAPI 기본 validation 응답을 반환한다. 예를 들어 `timestamp`가 음수이거나 `en`이
빈 문자열이면 요청이 거부된다.

```json
{
  "detail": [
    {
      "loc": ["body", "timestamp"],
      "msg": "Input should be greater than or equal to 0",
      "type": "greater_than_equal"
    }
  ]
}
```

---

## 4. Supabase Auth 환경변수

환경변수는 서버 시작 시 읽는다. Google OAuth Provider와 사용자 계정은 Supabase Dashboard에서
설정하고, 백엔드는 아래 값으로 Access Token을 검증한다.

| 환경변수 | 기본값 | 설명 |
| --- | --- | --- |
| `SUPABASE_URL` | 빈 문자열 | Supabase 프로젝트 URL |
| `SUPABASE_KEY` | 빈 문자열 | HS256 Auth API 검증에 사용하는 publishable/anon key |
| `SUPABASE_JWT_AUDIENCE` | `authenticated` | 검증할 JWT `aud` claim |
| `SUPABASE_JWT_ISSUER` | `{SUPABASE_URL}/auth/v1` | 검증할 JWT `iss` claim |
| `SUPABASE_AUTH_VERIFICATION_MODE` | `auto` | `auto`, `jwks`, `auth_api` |
| `SUPABASE_JWKS_CACHE_SECONDS` | `600` | JWKS 키셋 캐시 시간(초) |
| `SUPABASE_AUTH_TIMEOUT_SECONDS` | `5` | Auth API 검증 요청 timeout(초) |

`auto` 모드에서는 비대칭 서명 알고리즘을 JWKS로 로컬 검증하고, `HS256` 토큰은
`/auth/v1/user`에 검증을 위임한다. `SUPABASE_KEY`와 JWT secret은 Git에 커밋하거나
프론트에 노출하지 않는다.

---

## 5. LLM 환경변수

환경변수는 서버 시작 시 읽는다. 값을 변경하면 서버를 재시작해야 한다.

| 환경변수 | 기본값 | 설명 |
| --- | --- | --- |
| `LLM_PROVIDER` | `stub` | `stub`, `gemini`, `groq`, `auto` |
| `GEMINI_API_KEY` | 빈 문자열 | Gemini API key |
| `GEMINI_MODEL` | `gemini-2.5-flash` | Gemini 모델명 |
| `GEMINI_TIMEOUT_SECONDS` | `20` | Gemini 요청 timeout |
| `GEMINI_DAILY_TOKEN_LIMIT` | `0` | 일일 로컬 guard, `0`이면 비활성화 |
| `GEMINI_MINUTE_TOKEN_LIMIT` | `0` | 분당 로컬 guard, `0`이면 비활성화 |
| `GROQ_API_KEY` | 빈 문자열 | Groq API key |
| `GROQ_MODEL` | `openai/gpt-oss-20b` | Groq 모델명 |
| `GROQ_TIMEOUT_SECONDS` | `20` | Groq 요청 timeout |
| `GROQ_DAILY_TOKEN_LIMIT` | `180000` | 일일 로컬 guard |
| `GROQ_MINUTE_TOKEN_LIMIT` | `7000` | 분당 로컬 guard |

설정 예시:

```dotenv
LLM_PROVIDER=gemini
GEMINI_API_KEY=your_gemini_api_key
GROQ_API_KEY=your_groq_api_key
GROQ_MODEL=openai/gpt-oss-20b
```

Groq 및 Gemini 사용량은 현재 프로세스 메모리에 기록된다. 서버 재시작 또는 다중 인스턴스
운영에서도 누적량을 유지하려면 `InMemoryUsageTracker`를 Redis/PostgreSQL 저장소로
교체해야 한다.

---

## 6. 로컬 호출 예시

서버 실행:

```powershell
uv run uvicorn app.main:app --reload --port 8000 --env-file .env
```

PowerShell에서 요청:

```powershell
$accessToken = "paste-your-supabase-access-token"

$body = @'
{
  "video_id": "arj7oStGLkU",
  "timestamp": 156.4,
  "user_message": "be honest with는 어떤 뜻인가요?",
  "recent_subtitles": [
    {
      "time": 156.4,
      "en": "I want to be honest with you.",
      "ko": "솔직하게 말씀드리고 싶어요."
    }
  ],
  "learner_signals": {
    "quiz_accuracy": 0.72,
    "average_response_time_ms": 7500,
    "quiz_attempts": 6
  }
}
'@

Invoke-RestMethod `
  -Uri 'http://127.0.0.1:8000/api/v1/tutor/ask' `
  -Method Post `
  -Headers @{ Authorization = "Bearer $accessToken" } `
  -ContentType 'application/json' `
  -Body $body
```

Gemini fallback을 확인하려면 Gemini의 로컬 한도를 낮춰 다음처럼 설정한다.

```dotenv
LLM_PROVIDER=gemini
GEMINI_DAILY_TOKEN_LIMIT=1
GROQ_API_KEY=your_groq_api_key
```

유효한 Groq key가 있고 서버를 재시작한 뒤 요청하면 응답의 `provider`가 `groq`인지
확인할 수 있다.

---

## 7. 미구현 예정 API

아래 경로는 기획/설계 문서에만 존재하며 현재 FastAPI 앱에는 등록되어 있지 않다.

- 인증: 프론트의 Supabase Auth Google 로그인, 백엔드 `/api/v1/auth/me`는 구현됨
- 사전: `/api/v1/dict/hover`, `/api/v1/dict/detail`
- 단어장: `/api/v1/words/save`, `/api/v1/words/list`
- Tutor 확장: `/api/v1/tutor/proactive`, `/api/v1/tutor/feedback`
- 행동 로그: `/api/v1/logs/event`

해당 기능을 구현할 때 이 문서의 현재 구현 섹션에 실제 스키마와 상태 코드를 추가한다.
