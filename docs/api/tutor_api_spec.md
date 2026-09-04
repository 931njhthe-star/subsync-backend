# SubSync Video Tutor API 명세서

이 문서는 현재 시청 중인 YouTube 영상의 자막 문맥을 이용해 질문에 답하고, 학습자
수준에 따라 Tutor 답변 난이도를 조절하는 Video Tutor API를 정의한다.

공통 접속 정보, 인증, 오류, 보안 규칙은 [API 공통 명세서](./api_spec.md)를 따른다.
기획 요구사항의 AI Tutor 추출본은 [AI Tutor 요구사항 정리](../ai/ai_tutor_requirements.md)를
참고한다.

## 1. 요구사항과 API 매핑

| Video Tutor 요구사항 | API·응답 필드 | 상태 |
| --- | --- | --- |
| 현재 영상에 대해 질문 | `POST /api/v1/tutor/ask`의 `video_id`, `timestamp`, `user_message` | `IMPLEMENTED` |
| 영상 내용을 기반으로 답변 | `recent_subtitles`, `reply`, `context_subtitle_count` | `IMPLEMENTED` |
| Tutor가 먼저 학습 질문 제안 | `POST /api/v1/tutor/proactive` | `IMPLEMENTED`* |
| Tutor 영어 답변에 Hover/Click 적용 | `reply_tokens`와 사전 조회 API 연동 | 부분 구현 |
| Tutor ON/OFF | `GET/PATCH /api/v1/tutor/settings` | `IMPLEMENTED`* |
| 저장 단어·정답률·응답 시간 기반 개인화 | `learner_signals`, `learner_level`, `tutor_difficulty` | 프로토타입 구현 |

`suggested_questions`는 사용자가 질문한 뒤 제공하는 후속 질문이다. Tutor가 먼저 질문을
표시하는 요구사항은 `proactive` API에서 별도로 처리한다.

## 2. 구현 범위

### 2.1 현재 구현된 API

| 상태 | Method | Path | 설명 |
| --- | --- | --- | --- |
| `IMPLEMENTED` | `POST` | `/api/v1/tutor/ask` | 현재 자막 문맥 기반 질문 답변 |

### 2.2 구현된 확장 API

| 상태 | Method | Path | 설명 |
| --- | --- | --- | --- |
| `IMPLEMENTED`* | `GET` | `/api/v1/tutor/settings` | 현재 사용자의 Tutor 활성화 상태 조회 |
| `IMPLEMENTED`* | `PATCH` | `/api/v1/tutor/settings` | Tutor ON/OFF 변경 |
| `IMPLEMENTED`* | `POST` | `/api/v1/tutor/proactive` | 선제 질문 표시 여부 판단·생성 |
| `IMPLEMENTED`* | `POST` | `/api/v1/tutor/feedback` | Tutor 답변 평가 기록 |

`IMPLEMENTED`와 `PROPOSED`의 의미는 [API 공통 명세서](./api_spec.md)의 상태 표기를
따른다. `*`가 붙은 API는 현재 라우터에 등록되어 로컬에서 동작하지만, Supabase Auth와
영구 DB가 연결되기 전까지는 개발용 메모리 저장소를 사용한다.

## 3. 공통 요청 조건

### 3.1 현재 구현

현재 `/api/v1/tutor`에 등록된 개발 API에는 인증 dependency가 연결되어 있지 않다.
로컬 테스트는 `Content-Type` 헤더만으로 수행할 수 있다. 운영 전환 시 아래의
Bearer Token을 모든 사용자별 Tutor API에 적용한다.

```http
Content-Type: application/json
Accept: application/json
```

### 3.2 목표 구조

Supabase Auth 연동 후에는 사용자별 학습 데이터와 Tutor 설정을 사용하므로 다음 헤더를
추가한다.

```http
Authorization: Bearer <supabase_access_token>
```

현재는 요청 본문의 `learner_signals`를 사용하지만, 운영 구조에서는 인증된 JWT의
`sub`로 Supabase에서 학습 신호를 조회한다. 클라이언트가 임의로 전달한 사용자 ID를
신뢰하지 않는다.

## 4. Tutor 질문 — `IMPLEMENTED`

### `POST /api/v1/tutor/ask`

현재 영상 재생 시점, 주변 자막, 사용자 질문을 바탕으로 Tutor 답변을 생성한다.
저장 단어·퀴즈 정답률·응답 시간 등의 신호가 전달되면 학습자 수준을 추론하여 답변
난이도에 반영한다.

### 4.1 요청 헤더

현재 로컬 구현:

```http
Content-Type: application/json
Accept: application/json
```

Supabase Auth 연동 후:

```http
Authorization: Bearer <supabase_access_token>
```

### 4.2 요청 본문

| 필드 | 타입 | 필수 | 제한·기본값 | 설명 |
| --- | --- | --- | --- | --- |
| `video_id` | string | 예 | 1~50자 | YouTube 영상 ID |
| `timestamp` | number | 예 | 0 이상 | 질문 시점(초) |
| `user_message` | string | 예 | 1~2,000자 | 사용자의 질문 |
| `recent_subtitles` | array | 아니오 | 최대 100개, 기본 `[]` | 질문 시점 주변 자막 |
| `learner_signals` | object | 아니오 | 기본 `{}` | 학습자 수준 추론용 입력 |
| `conversation_history` | array | 아니오 | 최대 10개, 기본 `[]` | 최근 Tutor 대화 이력 |
| `focus_word` | string/null | 아니오 | 최대 100자, 기본 `null` | 집중해서 설명할 표현 |
| `conversation_id` | string/null | 아니오 | 최대 100자, 기본 `null` | 이어갈 Tutor 대화 식별자 |

#### `recent_subtitles` 원소

| 필드 | 타입 | 필수 | 제한 | 설명 |
| --- | --- | --- | --- | --- |
| `time` | number | 예 | 0 이상 | 자막 시작 시각(초) |
| `en` | string | 예 | 1~500자 | 영어 자막 |
| `ko` | string/null | 아니오 | 최대 500자 | 한국어 자막 |

#### `learner_signals`

| 필드 | 타입 | 필수 | 제한·기본값 | 설명 |
| --- | --- | --- | --- | --- |
| `saved_words` | array | 아니오 | 최대 500개, 기본 `[]` | 현재 질문과 관련된 저장 단어 |
| `saved_word_count` | integer/null | 아니오 | 0~100,000 | 전체 저장 단어 수 |
| `quiz_accuracy` | number/null | 아니오 | 0~1 | 전체 퀴즈 정답률 |
| `average_response_time_ms` | number/null | 아니오 | 0~300,000 | 전체 평균 응답 시간(ms) |
| `recent_quiz_accuracy` | number/null | 아니오 | 0~1 | 최근 퀴즈 정답률 |
| `recent_response_time_ms` | number/null | 아니오 | 0~300,000 | 최근 평균 응답 시간(ms) |
| `quiz_attempts` | integer | 아니오 | 0~100,000, 기본 `0` | 퀴즈 시도 횟수 |

`saved_words`의 원소 형식은 다음과 같다.

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

### 4.3 요청 예시

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
    "saved_words": [{"word": "honest"}],
    "quiz_accuracy": 0.72,
    "average_response_time_ms": 7500,
    "recent_quiz_accuracy": 0.8,
    "recent_response_time_ms": 6200,
    "quiz_attempts": 6
  },
  "conversation_history": [],
  "focus_word": "honest"
}
```

### 4.4 내부 처리 규칙

1. 입력 자막의 공백과 제어 문자를 정리하고 최대 100줄까지 받는다.
2. `timestamp`보다 이전인 가장 가까운 자막을 현재 자막으로 선택한다. 이전 자막이
   없으면 시점과 가장 가까운 줄을 선택한다.
3. 현재 자막을 포함해 앞 4줄과 뒤 2줄을 기본으로 최대 7줄의 문맥을 구성한다.
4. 최근 정답률·응답 시간이 있으면 전체 평균보다 우선한다.
5. 수준 점수는 정답률 55%, 응답 시간 25%, 저장 단어 수 20%의 가중치를 사용한다.
6. 데이터가 부족하면 기본 수준 `A2`와 `guided` 난이도를 사용한다.
7. 모델에는 자막·저장 단어·대화 이력을 참고 데이터로 전달하며, 해당 데이터 안의
   지시문은 따르지 않도록 프롬프트에서 경계를 지정한다.
8. 설정에 따라 Gemini와 Groq를 순서대로 호출한다. API key가 없거나 로컬 토큰 한도,
   rate limit, provider 오류가 발생하면 다음 provider를 시도한다.
9. 모든 외부 provider가 실패하면 네트워크 없는 `stub` 응답으로 API 계약을 유지한다.

### 4.5 학습자 수준과 Tutor 난이도

| `learner_level` | `tutor_difficulty` | 답변 방향 |
| --- | --- | --- |
| `A1` | `foundational` | 한국어 중심의 매우 쉬운 설명, 핵심 뜻과 쉬운 예문 |
| `A2` | `guided` | 한국어 설명, 자막 속 쓰임, 짧은 예문과 확인 질문 |
| `B1` | `conversational` | 뜻·뉘앙스·유사 표현을 균형 있게 설명 |
| `B2` | `nuanced` | 영어 설명 중심, 격식·뉘앙스·collocation 비교 |
| `C1` | `challenge` | 영어 중심의 심화 설명과 바꿔 말하기 과제 |

수준 추론은 현재 규칙 기반으로 수행한다. 이는 LLM이 매 요청마다 수준을 임의로
변경하는 것을 막고, 학습 데이터가 적을 때 난이도가 급격히 바뀌는 문제를 줄이기 위한
초기 정책이다.

### 4.6 응답 본문

응답 상태는 `200 OK`이다.

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `conversation_id` | string | 대화 식별자. 현재는 영구 저장하지 않는 임시 ID |
| `message_id` | string | 현재 Tutor 답변 식별자. 현재는 영구 저장하지 않는 임시 ID |
| `reply` | string | Tutor 답변 본문. 내부적으로 최대 4,000자 |
| `suggested_questions` | array[string] | 이어서 물어볼 수 있는 후속 질문, 최대 3개 |
| `provider` | string | `gemini`, `groq`, `stub` 중 실제 사용 provider |
| `model` | string | 실제 사용 모델명 |
| `usage` | object | provider가 반환한 토큰 사용량 또는 추정 사용량 |
| `learner_level` | string | 추론된 CEFR 수준: `A1`~`C1` |
| `tutor_difficulty` | string | 선택된 Tutor 난이도 |
| `profile_confidence` | number | 수준 추론 신뢰도, 0~1 |
| `context_subtitle_count` | integer | 답변에 사용한 주변 자막 줄 수 |
| `reply_tokens` | array | 답변에서 Hover/Click 가능한 영어 표현 목록 |

#### `usage` 원소

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `input_tokens` | integer | 입력 토큰 수 |
| `output_tokens` | integer | 출력 토큰 수 |
| `total_tokens` | integer | 입력·출력 토큰 합계 |

provider가 usage를 제공하지 않는 경우 값이 추정되거나 `0`일 수 있다. 현재 토큰
tracker는 프로세스 메모리 기반 개발용 저장소이므로 서버를 재시작하면 누적 사용량이
초기화된다.

Gemini/Groq provider의 한 요청 최대 출력은 800 token이며, 로컬 quota guard는 이 값을
예약 토큰으로 사용한다.

### 4.7 응답 예시

```json
{
  "conversation_id": "conv_49a1d",
  "message_id": "msg_001",
  "reply": "'be honest with'는 상대방에게 솔직하게 말할 때 사용하는 표현이에요. 이 자막에서는 '너에게 솔직해지고 싶다'는 의미입니다.",
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
  "context_subtitle_count": 2,
  "reply_tokens": [
    {
      "surface": "honest",
      "normalized": "honest",
      "start": 4,
      "end": 10,
      "interactive": true
    }
  ]
}
```

### 4.8 오류 및 예외

| 상태 코드 | 조건 |
| --- | --- |
| `422` | 필수 필드 누락, 길이 제한 초과, 음수 timestamp, 허용 범위를 벗어난 학습 신호 |
| `401` | Supabase Auth 연동 후 Access Token 없음·만료·변조 |
| `404` | 존재하지 않는 `conversation_id`로 대화를 이어가려는 경우 |
| `409` | Tutor OFF 정책에서 수동 질문을 차단하거나, 다른 영상에 연결된 `conversation_id`를 재사용한 경우 |
| `429` | 사용자(로그인 전에는 `anonymous`)별 Tutor 요청 빈도 제한을 초과한 경우 |
| `503` | 인증·DB 등 필수 의존 서비스 장애. 현재 외부 LLM 실패는 `stub`으로 처리 |

공통 오류 응답 형식은 다음과 같다.

```json
{
  "detail": "오류 설명"
}
```

## 5. Tutor ON/OFF — `IMPLEMENTED*`

Tutor OFF 상태에서는 Tutor가 자동으로 표시하는 선제 질문을 절대 생성하거나 표시하지
않는다. 설정은 사용자별로 저장한다.

### 5.1 `GET /api/v1/tutor/settings`

현재 사용자의 Tutor 설정을 조회한다.

#### 요청 헤더

```http
Authorization: Bearer <supabase_access_token>
```

현재 로컬 구현에서는 인증 헤더를 검사하지 않는다. Supabase Auth 연동 후 사용자별
설정을 보호하기 위해 필수 헤더로 변경한다.

#### 응답 `200 OK`

```json
{
  "tutor_enabled": true,
  "updated_at": "2026-09-03T12:00:00Z"
}
```

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `tutor_enabled` | boolean | Tutor 기능 활성화 여부 |
| `updated_at` | string | 설정이 마지막으로 변경된 UTC 시각 |

### 5.2 `PATCH /api/v1/tutor/settings`

현재 사용자의 Tutor 활성화 상태를 변경한다.

#### 요청 본문

```json
{
  "tutor_enabled": false
}
```

#### 응답 `200 OK`

```json
{
  "tutor_enabled": false,
  "updated_at": "2026-09-03T12:05:00Z"
}
```

설정 변경 시 서버는 사용자의 다른 계정 설정을 덮어쓰지 않아야 한다. 사용자 식별자는
요청 본문이 아니라 검증된 Access Token에서 가져온다.

## 6. Tutor 선제 질문 — `IMPLEMENTED*`

### `POST /api/v1/tutor/proactive`

사용자가 먼저 질문하지 않아도 현재 영상 문맥에 학습 가치가 있는 표현이 있는지 판단하고,
필요한 경우 Tutor 질문을 반환한다.

프론트엔드는 자막이 바뀔 때마다 호출하지 않고, 새로운 표현이 등장하거나 일정 시간
간격이 지난 경우에만 호출한다.

### 6.1 요청 헤더

```http
Content-Type: application/json
Accept: application/json
Authorization: Bearer <supabase_access_token>
```

현재 로컬 구현에서는 인증 헤더를 검사하지 않으며, 운영 전환 후 사용자별 선제 질문
이력과 설정을 보호하기 위해 필수로 적용한다.

### 6.2 요청 본문

| 필드 | 타입 | 필수 | 제한·기본값 | 설명 |
| --- | --- | --- | --- | --- |
| `video_id` | string | 예 | 1~50자 | 현재 영상 ID |
| `timestamp` | number | 예 | 0 이상 | 현재 재생 시점(초) |
| `recent_subtitles` | array | 예 | 최대 100개 | 현재 시점 주변 자막 |
| `playback_state` | string | 아니오 | `playing` | `playing`, `paused`, `seeking` |
| `last_question_id` | string/null | 아니오 | 기본 `null` | 마지막으로 표시한 선제 질문 ID |
| `last_question_at` | number/null | 아니오 | 기본 `null` | 마지막 질문 표시 시점(초) |

### 6.3 요청 예시

```json
{
  "video_id": "arj7oStGLkU",
  "timestamp": 156.4,
  "recent_subtitles": [
    {
      "time": 156.4,
      "en": "I want to be honest with you.",
      "ko": "솔직하게 말씀드리고 싶어요."
    }
  ],
  "playback_state": "playing",
  "last_question_id": null,
  "last_question_at": null
}
```

### 6.4 응답 `200 OK`

```json
{
  "should_show": true,
  "reason": "new_expression",
  "question_id": "pq_01HZX8",
  "question": "방금 나온 'be honest with'의 뜻을 추측해 볼까요?",
  "focus_word": "honest",
  "expires_in_seconds": 30
}
```

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `should_show` | boolean | 프론트가 질문을 표시할지 여부 |
| `reason` | string | 판단 사유 |
| `question_id` | string/null | 선제 질문 ID. 표시하지 않으면 `null` |
| `question` | string/null | 표시할 질문. 표시하지 않으면 `null` |
| `focus_word` | string/null | 질문의 중심 표현 |
| `expires_in_seconds` | integer/null | 질문을 표시할 수 있는 유효 시간 |

`reason` 권장 값:

| 값 | 의미 |
| --- | --- |
| `new_expression` | 새로 학습할 만한 표현 발견 |
| `cooldown` | 직전 질문 이후 대기 시간 미충족 |
| `disabled` | Tutor가 OFF 상태 |
| `insufficient_context` | 판단에 필요한 자막 문맥 부족 |
| `already_seen` | 동일 표현에 대해 이미 질문함 |
| `paused` | 영상이 일시정지 또는 탐색 중 |

### 6.5 Tutor OFF 응답

```json
{
  "should_show": false,
  "reason": "disabled",
  "question_id": null,
  "question": null,
  "focus_word": null,
  "expires_in_seconds": null
}
```

### 6.6 호출 제어 정책

- 같은 `video_id`와 가까운 timestamp에 선제 질문을 반복하지 않는다.
- 질문 간 최소 cooldown은 초기 30~60초로 둔다.
- `paused`와 `seeking` 상태에서는 질문하지 않는다.
- 동일 표현을 이미 표시했으면 `already_seen`을 반환한다.
- 문맥이 부족하면 LLM을 호출하지 않고 `insufficient_context`를 반환할 수 있다.
- cooldown과 표시 이력은 Redis 또는 사용자별 저장소에 기록한다.

### 6.7 Tutor 요청 빈도 제한

`TUTOR_REQUESTS_PER_MINUTE` 환경변수로 사용자별 `POST /api/v1/tutor/ask` 호출 상한을
설정한다. 기본값은 30회/분이며 `0`이면 제한하지 않는다. 현재 인증 dependency가
연결되지 않은 로컬 구현에서는 모든 요청이 `anonymous` actor 하나의 제한을 공유한다.
제한을 초과하면 다음 오류를 반환한다.

```json
{
  "detail": "Tutor 요청이 너무 많습니다. 잠시 후 다시 시도해 주세요."
}
```

## 7. Tutor 답변 Hover/Click — `IMPLEMENTED*`

현재 `reply`와 함께 `reply_tokens`를 반환해 프론트엔드가 영어 학습 대상 단어를
안정적으로 식별할 수 있다. 사전 조회와 단어 저장은 별도 도메인 API의 구현이 필요하다.

### 7.1 `reply_tokens` 형식

```json
[
  {
    "surface": "honest",
    "normalized": "honest",
    "start": 14,
    "end": 20,
    "interactive": true
  }
]
```

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `surface` | string | 답변에 실제 표시된 표현 |
| `normalized` | string | 사전 검색용 정규화 표현 |
| `start` | integer | `reply` 내 시작 offset |
| `end` | integer | `reply` 내 끝 offset. 끝 위치는 포함하지 않음 |
| `interactive` | boolean | Hover/Click 대상 여부 |

offset은 Chrome Extension과 JavaScript의 문자열 처리를 맞추기 위해 UTF-16 code unit
기준으로 정의한다. `interactive=true`는 영문 학습 대상 표현에만 부여한다.

프론트엔드는 모델 답변을 HTML로 직접 렌더링하지 않고, `reply` 원문과 token offset을
이용해 안전하게 단어 요소를 생성한다.

### 7.2 사전·단어장 연동

Hover/Click 기능을 완성하려면 다음 별도 도메인 API와 연동한다. 이 문서는 Tutor가
해당 API를 어떻게 사용하는지만 정의하며, 사전·단어장 자체의 상세 계약은 해당 도메인
명세서에서 관리한다.

| 동작 | 연동 API | Tutor 화면에서의 사용 |
| --- | --- | --- |
| Hover | `GET /api/v1/dict/hover` | 짧은 뜻·품사·발음 표시 |
| Click | `GET /api/v1/dict/detail` | 상세 뜻·예문·관련 표현 표시 |
| 저장 | `POST /api/v1/words/save` | 사용자가 선택한 단어를 단어장에 저장 |

## 8. Tutor 답변 피드백 — `IMPLEMENTED*`

### `POST /api/v1/tutor/feedback`

사용자가 Tutor 답변의 유용성을 평가한 결과를 저장한다. 향후 프롬프트 개선과 답변 품질
분석에 사용한다.

### 요청 헤더

```http
Content-Type: application/json
Accept: application/json
Authorization: Bearer <supabase_access_token>
```

현재 로컬 구현에서는 인증 헤더를 검사하지 않는다. 운영 전환 후 피드백의 사용자
소유권을 검증한다.

### 요청 본문

```json
{
  "conversation_id": "conv_49a1d",
  "message_id": "msg_001",
  "rating": "helpful",
  "reason": null,
  "comment": null
}
```

| 필드 | 타입 | 필수 | 제한·기본값 | 설명 |
| --- | --- | --- | --- | --- |
| `conversation_id` | string | 예 | 최대 100자 | Tutor 대화 ID |
| `message_id` | string | 예 | 최대 100자 | 평가할 Tutor 메시지 ID |
| `rating` | string | 예 | `helpful` 또는 `not_helpful` | 답변 유용성 평가 |
| `reason` | string/null | 아니오 | 최대 50자 | `incorrect`, `too_difficult`, `too_easy`, `irrelevant`, `other` |
| `comment` | string/null | 아니오 | 최대 1,000자 | 선택 의견 |

### 응답 `201 Created`

```json
{
  "feedback_id": "fb_01HZX8",
  "conversation_id": "conv_49a1d",
  "message_id": "msg_001",
  "rating": "helpful",
  "reason": null,
  "comment": "자막 문맥에 맞는 설명이라 이해하기 쉬웠어요.",
  "created_at": "2026-09-03T12:10:00Z"
}
```

피드백은 동일한 `message_id`에 대해 최신 평가로 갱신한다. 현재는 개발용 메모리에
저장하며, 존재하지 않거나 다른 대화에 속한 메시지를 평가하면 `404`를 반환한다.

## 9. 프론트엔드 연동 순서

### 9.1 현재 MVP

1. Extension에서 현재 `video_id`, `timestamp`, 주변 자막을 수집한다.
2. `POST /api/v1/tutor/ask`를 호출한다.
3. 응답의 `reply`와 `suggested_questions`를 Tutor 채팅 UI에 표시한다.
4. 응답의 `learner_level`, `tutor_difficulty`를 개발 중 개인화 결과 확인에 사용한다.

### 9.2 요구사항 완성 단계

1. Supabase Google 로그인 후 Access Token을 Tutor API에 전달한다.
2. `GET/PATCH /api/v1/tutor/settings`로 Tutor ON/OFF 상태를 동기화한다.
3. 재생 이벤트를 cooldown 정책과 함께 `POST /api/v1/tutor/proactive`에 전달한다.
4. `reply_tokens`를 기준으로 영어 답변에 Hover/Click 인터랙션을 부여한다.
5. Hover는 간이 사전, Click은 상세 사전, 저장 버튼은 단어장 API와 연결한다.
6. 답변 평가 버튼은 `/api/v1/tutor/feedback`을 호출한다.
7. 학습 신호는 요청 본문이 아니라 인증된 사용자 ID로 DB에서 조회한다.

## 10. 현재 구현과 목표 상태

| 항목 | 현재 | 목표 |
| --- | --- | --- |
| 영상 질문·답변 | `POST /tutor/ask` 구현 | 인증 적용 후 유지 |
| 영상 문맥 | 클라이언트가 자막 전달 | 자막 전달 + 필요 시 서버 검증·캐시 |
| 개인화 | 요청의 `learner_signals` 사용 | 사용자별 DB 조회 |
| 수준 판정 | 규칙 기반 A1~C1 추론 | 학습 기록과 피드백을 이용해 지속 개선 |
| LLM provider | Gemini/Groq failover + stub fallback | 사용량 저장소·운영 모니터링 고도화 |
| 선제 질문 | 규칙 기반 + 메모리 cooldown | `proactive` + Redis cooldown |
| Tutor ON/OFF | anonymous actor 메모리 설정 | 사용자별 설정 저장 및 호출 차단 |
| Hover/Click | `reply_tokens` 반환 | 사전 API·단어장 API 연결 |
| 대화 저장 | 최근 10턴 메모리 | Supabase 사용자별 저장 |
| 답변 피드백 | 메모리 저장 | Supabase 저장 및 분석 |

현재 `IMPLEMENTED*` 항목은 실제 라우터에 등록되어 로컬 검증이 가능하다. 운영 전환 시
Supabase Auth·DB·Redis를 연결하고 사용자별 소유권과 영구 저장을 검증한 뒤 별표를
제거한다.
