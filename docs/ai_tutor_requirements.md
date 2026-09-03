# SubSync AI Tutor 요구사항 정리

이 문서는 시스템 요구사항 정의서에서 Video Tutor와 직접 관련된 항목만 추려서
정리한 문서다. 원문에 포함된 YouTube 연동, 이중자막, 사전, 단어장, 인증,
학습 기록 요구사항 중 Tutor 동작에 필요한 부분만 연결 관계로 남겼다.

API의 요청·응답 계약은 [Tutor API 명세서](./tutor_api_spec.md), 인증·오류·보안과
같은 공통 규칙은 [API 공통 명세서](./api_spec.md)를 따른다.

## 1. 기능 범위

Video Tutor는 사용자가 현재 시청 중인 YouTube 영상의 문맥을 바탕으로 영어 학습
질문에 답하는 기능이다.

```text
YouTube 영상
  ├─ video_id
  ├─ 현재 timestamp
  ├─ 현재 시점 주변 자막/Script
  └─ 이전 Tutor 대화
          │
          ▼
       Tutor API
          │
          ├─ 학습자 수준 추론
          ├─ 문맥 기반 prompt 생성
          ├─ LLM provider 호출
          ├─ 대화 상태 저장
          └─ Tutor 응답 반환
```

## 2. 핵심 기능 요구사항

| ID | 요구사항 | 우선순위 | 현재 상태 |
| --- | --- | --- | --- |
| `SR-51` | Tutor는 현재 영상의 식별 정보를 전달받아야 한다. | P0 | 완료 |
| `SR-52` | Tutor는 영상 내용을 참고할 수 있는 Context를 전달받아야 한다. | P0 | 완료 |
| `SR-53` | 사용자 질문을 LLM에 전달하고 답변을 반환해야 한다. | P0 | 완료 |
| `SR-54` | Tutor 대화의 이전 Context를 유지할 수 있어야 한다. | P0 | 개발용 완료 |
| `SR-55` | Tutor 답변을 사용자별 대화 기록으로 저장할 수 있어야 한다. | P0 | Supabase 연동 필요 |
| `SR-56` | Tutor가 먼저 학습 질문이나 제안을 생성할 수 있어야 한다. | P0 | 기본 기능 완료 |
| `SR-57` | Tutor OFF 상태에서는 Tutor UI 및 선제 질문을 비활성화해야 한다. | P0 | API 완료, UI 연동 필요 |
| `SR-58` | Tutor 영어 답변에 공통 Mouse Interaction을 적용해야 한다. | P0 | 토큰 API 완료, 사전 연동 필요 |

### 상태 의미

- `완료`: 현재 백엔드 코드로 요구사항의 핵심 동작을 확인할 수 있다.
- `개발용 완료`: 메모리 저장소 등 로컬 검증용 구현이며, 운영용 영구 저장·인증이
  아직 필요하다.
- `Supabase 연동 필요`: API 흐름은 준비할 수 있지만 사용자별 영구 데이터 보장은
  실제 인증·DB 계층을 연결해야 한다.
- `API 완료, UI 연동 필요`: 백엔드 계약은 제공하지만 Chrome Extension 화면 동작은
  프론트엔드에서 연결해야 한다.
- `토큰 API 완료, 사전 연동 필요`: Tutor 답변에서 단어 위치를 제공하지만 뜻 조회와
  저장은 사전·단어장 API가 담당한다.

## 3. Tutor 입력 Context

### 3.1 필수 Context

| 데이터 | 설명 | API 필드 |
| --- | --- | --- |
| 영상 식별자 | 현재 시청 중인 YouTube 영상 | `video_id` |
| 재생 시점 | 사용자가 질문한 영상 위치(초) | `timestamp` |
| 사용자 질문 | Tutor가 답변할 자연어 질문 | `user_message` |

### 3.2 선택 Context

| 데이터 | 설명 | API 필드 |
| --- | --- | --- |
| 주변 자막 | 현재 자막을 중심으로 한 영어·한국어 자막 | `recent_subtitles` |
| 집중 표현 | 사용자가 특정 단어·구문을 지정한 경우 | `focus_word` |
| 학습 신호 | 저장 단어 수, 정답률, 응답 시간 등 | `learner_signals` |
| 대화 ID | 기존 Tutor 대화를 이어갈 때 사용 | `conversation_id` |
| 대화 이력 | 개발 단계에서 직접 전달할 수 있는 최근 대화 | `conversation_history` |

### 3.3 Context 구성 정책

현재 구현은 다음 정책을 사용한다.

1. 전달받은 자막의 공백·제어 문자를 정리하고 최대 100줄까지 처리한다.
2. `timestamp`보다 이전인 가장 가까운 자막을 현재 자막으로 선택한다.
3. 이전 자막이 없으면 timestamp와 가장 가까운 자막을 선택한다.
4. 현재 자막을 포함해 앞 4줄과 뒤 2줄, 최대 7줄을 LLM Context로 사용한다.
5. 대화 이력은 최근 6턴까지만 prompt에 전달한다.
6. 자막·사용자 입력·저장 단어는 명령이 아닌 참고 데이터로 취급하여 prompt injection을
   방지한다.
7. Context가 부족하면 모델이 장면·화자·사실을 임의로 만들지 않고 부족한 정보를
   안내하도록 한다.

운영 환경에서는 Extension이 보낸 자막을 그대로 신뢰하기보다, 필요 시 서버의
Script 저장소·YouTube 자막 처리 계층과 대조하는 확장을 고려한다.

## 4. 학습자 수준 기반 Tutor 난이도

저장 단어, 퀴즈 정답률, 응답 시간은 Tutor 답변의 난이도를 조절하는 보조 신호다.
현재는 매 요청마다 LLM에게 수준을 판정시키지 않고 규칙 기반으로 계산한다.

| 신호 | 가중치 | 해석 |
| --- | ---: | --- |
| 최근 또는 전체 퀴즈 정답률 | 55% | 가장 중요한 실력 신호 |
| 최근 또는 전체 응답 시간 | 25% | 답변 처리 속도 보조 신호 |
| 저장 단어 수 | 20% | 학습량을 나타내는 약한 신호 |

최근 값이 있으면 전체 평균보다 최근 값을 우선한다. 관측 데이터가 적을 때는
기본 수준 `A2`에 가깝게 유지하여 Tutor 난이도가 갑자기 바뀌지 않도록 한다.

| 추론 수준 | 내부 Tutor 난이도 | 답변 스타일 |
| --- | --- | --- |
| `A1` | `foundational` | 한국어 중심의 아주 쉬운 설명과 짧은 예문 |
| `A2` | `guided` | 뜻·자막 속 쓰임·짧은 예문·확인 질문 |
| `B1` | `conversational` | 뜻·뉘앙스·유사 표현을 균형 있게 설명 |
| `B2` | `nuanced` | 격식·뉘앙스·collocation 비교 |
| `C1` | `challenge` | 영어 중심의 심화 설명과 바꿔 말하기 과제 |

## 5. LLM 처리 및 안정성

### 5.1 응답 생성

- 기본 provider는 Gemini다.
- Gemini quota·rate limit·네트워크 오류가 발생하면 Groq를 시도한다.
- `LLM_PROVIDER=groq`이면 Groq를 먼저 사용하고 Gemini를 다음으로 시도한다.
- 외부 provider를 사용할 수 없으면 개발용 rule-based `stub` 응답을 반환한다.
- provider가 반환한 입력·출력·총 토큰 사용량을 응답의 `usage`에 포함한다.
- 로컬 quota guard와 실패 cooldown으로 한 provider에 요청이 집중되는 것을 줄인다.

### 5.2 선제 질문의 비용 제어

선제 질문은 자막이 변경될 때마다 LLM을 호출하지 않는다.

- 영상 재생이 `paused` 또는 `seeking`이면 질문하지 않는다.
- 새 학습 표현이 없으면 질문하지 않는다.
- 같은 영상의 같은 표현을 반복해서 제안하지 않는다.
- 기본 cooldown은 45초이며 `TUTOR_PROACTIVE_COOLDOWN_SECONDS`로 조정할 수 있다.
- 현재 구현은 자막에서 후보 단어를 고르는 규칙 기반 방식이다. 향후 후보 품질을
  높이기 위해서만 선택적으로 LLM을 사용할 수 있다.

## 6. 대화 상태와 기록

### 6.1 대화 이어가기

첫 질문 응답의 `conversation_id`를 다음 질문에 보내면 같은 Tutor 대화를 이어간다.
프론트엔드는 매 요청마다 전체 대화 이력을 다시 보내지 않아도 된다.

```text
첫 요청                         다음 요청
POST /tutor/ask                 POST /tutor/ask
conversation_id 없음            conversation_id=첫 응답 ID
        │                                  │
        └────────── 같은 대화로 연결 ────────┘
```

현재 개발용 구현은 최근 10턴을 메모리에 보관한다. 서버 재시작·다중 worker 환경에서는
상태가 사라지므로 운영 단계에서 `tutor_conversations`와 `tutor_messages`를 Supabase에
저장하고, 사용자 ID와 RLS로 소유권을 제한해야 한다.

### 6.2 관련 원문 요구사항

| ID | 요구사항 | 구현 방향 |
| --- | --- | --- |
| `SR-61` | Tutor 대화 기록을 저장해야 한다. | 현재 메모리 저장, Supabase repository로 교체 |
| `SR-67` | 화면 간 현재 `video_id`를 유지해야 한다. | Extension 공통 상태에서 관리 |
| `SR-68` | 화면 간 현재 timestamp를 유지해야 한다. | Extension 공통 상태에서 관리 |
| `SR-69` | 화면 간 로그인 상태를 유지해야 한다. | Supabase Auth 세션에서 관리 |
| `SR-70` | Tutor `conversation_id`를 유지해야 한다. | API 응답·요청으로 구현 |

사용자별 영구 저장이 완료되기 전까지 메모리 구현을 운영 데이터로 간주하지 않는다.

## 7. Tutor ON/OFF

### 7.1 동작 규칙

- Tutor ON이면 수동 질문과 선제 질문을 사용할 수 있다.
- Tutor OFF이면 선제 질문 응답은 `should_show=false`, `reason=disabled`를 반환한다.
- Tutor OFF 상태에서 수동 질문 요청은 비용이 발생하지 않도록 `409`로 차단한다.
- ON/OFF 설정을 변경해도 다른 SubSync 기능 설정은 변경하지 않는다.
- 현재 개발용 설정은 `anonymous` actor 기준 메모리에 저장된다.
- 운영 단계에서는 Supabase 사용자별 설정으로 교체해야 한다.

### 7.2 UI 책임

백엔드는 상태와 선제 질문 판단을 제공하지만 다음은 Extension이 처리한다.

- Tutor 패널 표시·숨김
- OFF 상태에서 입력창·선제 질문 숨김
- 요청 중 로딩 상태 표시
- 영상과 분리된 Tutor 창을 닫아도 공통 상태 유지

## 8. Tutor 답변 Mouse Interaction

Tutor API는 `reply_tokens`로 답변 내 영어 표현의 위치를 제공한다.

```json
{
  "surface": "honest",
  "normalized": "honest",
  "start": 14,
  "end": 20,
  "interactive": true
}
```

- offset은 JavaScript와 호환되는 UTF-16 code unit 기준이다.
- 프론트엔드는 답변 원문과 offset을 이용해 안전하게 단어 요소를 생성한다.
- Hover 시 간단 뜻 조회, Click 시 상세 정보 조회를 사전 API에 위임한다.
- 단순 Hover는 MVP 학습 기록으로 저장하지 않는다.
- Click 이후 인증이 필요한 상세 학습·단어 저장은 Auth/단어장 API가 담당한다.

## 9. Tutor 피드백

### 9.1 원문 요구사항

| ID | 요구사항 | 우선순위 | 현재 상태 |
| --- | --- | --- | --- |
| `SR-64` | Tutor 답변별 👍/👎 평가를 저장할 수 있어야 한다. | P1 | 개발용 완료 |
| `SR-65` | 👎 선택 시 불만족 이유를 저장할 수 있어야 한다. | P1 | 개발용 완료 |
| `SR-66` | 피드백을 Tutor 품질 분석에 활용할 수 있어야 한다. | P1 | 분석 계층 필요 |

### 9.2 저장 항목

```text
user_id
conversation_id
message_id
rating
reason
comment
created_at
```

현재 API는 `rating`, `reason`, `comment`를 받아 메모리에 기록한다. 운영 단계에서는
`tutor_feedback` 테이블에 저장하고 `user_id`는 요청 본문이 아니라 검증된 JWT에서
가져와야 한다.

## 10. 비기능 요구사항

### 성능

- Tutor 요청 중 프론트엔드는 응답 생성 중 상태를 표시한다.
- 주변 자막과 대화 이력을 제한해 prompt 크기와 응답 지연을 관리한다.
- 반복적인 선제 질문과 불필요한 LLM 호출을 줄인다.
- Hover 단어 조회는 Tutor LLM을 사용하지 않고 사전 Cache 경로를 사용한다.

### 안정성

- Gemini·Groq provider 실패 시 다음 provider 또는 stub으로 전환한다.
- Tutor 오류가 YouTube 기본 재생을 중단시키지 않도록 Extension에서 오류를 격리한다.
- 외부 LLM이 JSON 형식을 지키지 않아도 백엔드가 응답을 정규화한다.

### 보안

- Gemini·Groq API key는 Chrome Extension에 노출하지 않는다.
- 인증 후 사용자별 Tutor 대화·피드백을 분리한다.
- 자막·질문·대화 이력은 신뢰할 수 없는 외부 입력으로 취급한다.
- 운영 환경에서는 Backend와 Extension 간 HTTPS를 사용한다.

## 11. 구현 완료 및 후속 작업

### 이번 단계에서 구현한 범위

- `POST /api/v1/tutor/ask`에 `conversation_id` 입력 지원
- 개발용 대화 이력 저장 및 다음 질문에 자동 전달
- `reply_tokens` 생성 및 UTF-16 offset 반환
- `GET/PATCH /api/v1/tutor/settings`
- Tutor OFF 시 선제 질문 숨김 및 수동 질문 `409` 차단
- `POST /api/v1/tutor/proactive`
- cooldown·중복 표현·paused/seeking 제어
- `POST /api/v1/tutor/feedback`
- 피드백 rating·reason·comment 개발용 저장
- 관련 Pydantic DTO, docstring, 단위/API 테스트

### 후속 구현 범위

1. Supabase JWT 인증 dependency 연결
2. `tutor_conversations`, `tutor_messages`, `tutor_feedback` 영구 저장
3. 사용자별 Tutor 설정 및 RLS 적용
4. Redis cooldown·Cache 연결
5. 사전·단어장 API와 `reply_tokens` 연결
6. Extension Tutor UI와 ON/OFF·선제 질문·로딩 상태 연결
7. 피드백 분석과 Tutor 품질 대시보드 연결

## 12. MVP 제외 범위

첨부 요구사항 정의서의 다음 항목은 이번 AI Tutor 구현 범위에서 제외한다.

- 복잡한 개인별 약점 추론 모델
- 자동 복습 알고리즘
- 개인화 영상 추천
- Long Click 문장 분석
- 피드백 기반 자동 prompt 최적화
- 관리자 분석 Dashboard 자체 구현
