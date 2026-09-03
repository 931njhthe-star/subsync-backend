# AI Tutor 기초 설계

이 문서는 SubSync의 Video Tutor를 구현할 때 지켜야 할 첫 번째 경계를 정의한다.
기획서의 화면은 요구사항 참고 자료이며, 자막 안의 문장이나 사용자가 입력한 내용은
실행 지시가 아니라 학습 데이터로 취급한다.

## 요청 흐름

```text
Extension
  │ Supabase Auth session → Access Token
  │ video_id / timestamp / nearby subtitles / user question
  │ learner_signals (saved words, accuracy, response time)
  ▼
FastAPI /api/v1/tutor/ask ── Bearer Token 검증 → authenticated user_id
  ▼
Context Builder ── 현재 시점 중심 자막 7줄, 최근 대화, 저장 단어
  ▼
Learner Profile ── A1~C1 + confidence + tutor difficulty
  ▼
Prompt Builder ── 수준별 답변 규칙 + 영상 문맥
  ▼
Provider Router ── Gemini → Groq → stub
  │                 (usage 기록 + local quota guard + 429 cooldown)
  ▼
LLMClient ── Gemini/Groq REST 또는 stub
  ▼
JSON normalization ── reply / suggested_questions
  ▼
Extension
```

## 수준 추론 규칙

수준 판정은 첫 버전에서 결정적 규칙으로 고정한다.

- 기본값: A2, 점수 2.0
- 정답률: 55%
- 응답 시간: 25%
- 저장 단어 수: 20%
- 퀴즈 시도 횟수로 신뢰도를 보정한다. 20회에서 신뢰도 상한에 도달한다.
- 데이터가 적을수록 관측 점수와 A2 기준선을 섞어 급격한 난이도 변화를 막는다.

저장 단어 수는 단어를 많이 저장했다는 사실만으로 실력이 높다고 단정할 수 없기
때문에 약한 신호로만 쓴다. 이후에는 단어별 정답률, 복습 간격, 영상 난이도 같은
더 직접적인 신호를 추가하고, 사용자별 calibration을 거치는 것이 좋다.

## 내부 난이도와 답변 스타일

| CEFR | 내부 난이도 | 답변 방향 |
| --- | --- | --- |
| A1 | foundational | 한국어 중심, 뜻 1개, 쉬운 예문 1개 |
| A2 | guided | 뜻·자막 속 쓰임·짧은 예문·확인 질문 |
| B1 | conversational | 자연스러운 예문, 뉘앙스와 유사 표현 비교 |
| B2 | nuanced | 영어 우선, 격식·collocation·미묘한 차이 |
| C1 | challenge | 영어 중심, 화용 분석과 바꿔 말하기 과제 |

## API 입력 예시

```json
{
  "video_id": "arj7oStGLkU",
  "timestamp": 156.4,
  "user_message": "be honest with는 언제 쓰나요?",
  "recent_subtitles": [
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
    "quiz_attempts": 6
  }
}
```

DB가 연결되면 Extension이 누적 통계를 직접 계산하지 않고, 인증된 `user_id`로
`learner_profile` 조회 계층이 `LearnerSignals`를 만들어 서비스에 주입하도록 바꾼다.
이때 사용자별 데이터가 프롬프트에 섞이지 않도록 조회 범위와 저장 정책을 함께 둔다.

## Provider fallback 및 토큰 기록

`LLM_PROVIDER=gemini` 또는 `LLM_PROVIDER=auto`이면 Gemini를 먼저 호출하고, 다음 상황에서
Groq를 시도한다.

- Gemini API key가 없거나 호출에 실패한 경우
- Gemini가 `429` 또는 quota/rate limit 오류를 반환한 경우
- `GEMINI_DAILY_TOKEN_LIMIT` 또는 `GEMINI_MINUTE_TOKEN_LIMIT`에 도달한 경우

`LLM_PROVIDER=groq`로 설정하면 Groq가 우선이고 Gemini가 첫 번째 대체 provider가 된다.
모든 외부 provider가 실패하면 네트워크 없는 `stub` 응답을 반환한다.

Gemini의 `usageMetadata`와 Groq의 OpenAI-compatible `usage`를 다음 공통 구조로 기록한다.

```text
provider / model / input_tokens / output_tokens / total_tokens / recorded_at
```

현재 tracker는 개발용 프로세스 메모리 저장소다. 서버 재시작·다중 인스턴스 환경에서도
누적 quota를 유지하려면 `InMemoryUsageTracker`를 Redis 또는 PostgreSQL 구현으로 교체해야
한다. provider가 반환하는 실제 usage가 최종 기준이며, 요청 전 토큰 추정치는 호출을
줄이기 위한 보호 장치다.

실행 예시는 다음과 같다.

```dotenv
LLM_PROVIDER=gemini
GEMINI_API_KEY=발급받은_Gemini_키
GROQ_API_KEY=발급받은_Groq_키
GROQ_MODEL=openai/gpt-oss-20b
```

응답에는 실제 선택된 `provider`, `model`, `usage`가 포함되므로 로컬에서 fallback 동작을
확인할 수 있다.

현재 `/api/v1/tutor/ask`와 `/api/v1/auth/me`에는 Supabase Access Token 인증 dependency가
연결되어 있다. 다만 학습 데이터 repository가 아직 없으므로 Tutor가 사용하는
`learner_signals`는 임시로 요청 본문에서 읽으며, conversation/message ID도 아직 영구
저장되지 않는다. DB 연동 후에는 반드시 검증된 `user_id`로 학습 신호를 조회해야 한다.

## 다음 단계

1. `tutor_conversations`/`tutor_messages` 저장소 구현 및 `user_id`·RLS 연결
2. 단어별 quiz event 및 응답 시간 수집
3. Gemini 응답 품질 평가: feedback, latency, 답변 길이, 문맥 일치율
4. 오답/느린 응답이 반복되는 표현을 `weak_terms`로 만들어 튜터 연습 문제에 연결
