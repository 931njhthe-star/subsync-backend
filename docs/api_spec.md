# SubSync REST API 명세서 (v1)

> **Base URL**: `http://localhost:8000/api/v1` (로컬) / `https://api.subsync.xyz/api/v1` (운영)  
> 모든 요청과 응답은 `application/json; charset=utf-8`을 기본으로 한다.

---

## 1. 인증 (Authentication)

### 1.1 회원가입
- **Endpoint**: `POST /auth/signup`
- **Request Body**:
```json
{
  "email": "user@example.com",
  "password": "securepassword123",
  "nickname": "지훈"
}
```
- **Response (201 Created)**:
```json
{
  "user_id": "usr_9f8c12a4",
  "email": "user@example.com",
  "nickname": "지훈",
  "access_token": "eyJhbGciOi...",
  "token_type": "bearer"
}
```

### 1.2 로그인
- **Endpoint**: `POST /auth/login`
- **Request Body**:
```json
{
  "email": "user@example.com",
  "password": "securepassword123"
}
```
- **Response (200 OK)**:
```json
{
  "user_id": "usr_9f8c12a4",
  "email": "user@example.com",
  "nickname": "지훈",
  "access_token": "eyJhbGciOi...",
  "token_type": "bearer"
}
```

### 1.3 내 정보 조회 (인증 테스트용)
- **Endpoint**: `GET /auth/me`
- **Headers**: `Authorization: Bearer <access_token>`
- **Response (200 OK)**:
```json
{
  "user_id": "usr_9f8c12a4",
  "email": "user@example.com",
  "nickname": "지훈",
  "saved_words_count": 14
}
```

---

## 2. 사전 (Dictionary)

### 2.1 Hover 빠른 단어 뜻 조회 (로그인 불필요)
- **Endpoint**: `GET /dict/hover?word={word}`
- **설명**: 0.5초 이내 빠른 응답. Redis/로컬사전 우선 조회.
- **Response (200 OK)**:
```json
{
  "word": "honest",
  "meanings": ["정직한", "솔직한"]
}
```

### 2.2 Click 상세 단어 설명 조회 (로그인 필요)
- **Endpoint**: `GET /dict/detail?word={word}&context={sentence}`
- **Headers**: `Authorization: Bearer <access_token>`
- **Query Params**:
  - `word`: 검색 단어
  - `context` (선택): 단어가 등장한 자막 문장
- **Response (200 OK)**:
```json
{
  "word": "honest",
  "phonetic": "/ˈɒnɪst/",
  "part_of_speech": "형용사",
  "definitions": [
    "정직한, 솔직한",
    "순수한, 정당한"
  ],
  "context_meaning": "현재 문장에서는 '솔직한'이라는 의미입니다.",
  "phrases": [
    {
      "expression": "be honest with ~",
      "meaning": "~에게 솔직하다"
    }
  ],
  "is_saved": false
}
```

---

## 3. 단어장 (Saved Words)

### 3.1 단어 저장 (로그인 필요)
- **Endpoint**: `POST /words/save`
- **Headers**: `Authorization: Bearer <access_token>`
- **Request Body**:
```json
{
  "word": "honest",
  "meaning": "정직한, 솔직한",
  "video_id": "arj7oStGLkU",
  "timestamp": 156.4,
  "context_sentence": "I want to be honest with you."
}
```
- **Response (201 Created)**:
```json
{
  "id": "wrd_88a1b2",
  "word": "honest",
  "saved_at": "2026-09-02T16:00:00Z"
}
```

### 3.2 저장 단어 목록 조회
- **Endpoint**: `GET /words/list?limit=50&offset=0`
- **Headers**: `Authorization: Bearer <access_token>`
- **Response (200 OK)**:
```json
{
  "total": 1,
  "words": [
    {
      "id": "wrd_88a1b2",
      "word": "honest",
      "meaning": "정직한, 솔직한",
      "video_id": "arj7oStGLkU",
      "context_sentence": "I want to be honest with you.",
      "saved_at": "2026-09-02T16:00:00Z"
    }
  ]
}
```

---

## 4. Video Tutor (AI)

### 4.1 영상 기반 사용자 질문/답변 (로그인 필요)
- **Endpoint**: `POST /tutor/ask`
- **Headers**: `Authorization: Bearer <access_token>`
- **Request Body**:
```json
{
  "video_id": "arj7oStGLkU",
  "timestamp": 156.4,
  "user_message": "방금 나온 'be honest with'는 언제 주로 쓰나요?",
  "recent_subtitles": [
    { "time": 150.0, "en": "I know it sounds crazy.", "ko": "말도 안 되게 들리겠지만요." },
    { "time": 156.4, "en": "I want to be honest with you.", "ko": "솔직하게 말씀드리고 싶어요." }
  ]
}
```
- **Response (200 OK)**:
```json
{
  "conversation_id": "conv_49a1d",
  "message_id": "msg_001",
  "reply": "상대방에게 숨김없이 진심이나 사실을 털어놓을 때 주로 사용해요. 예를 들어 'Be honest with me'는 '나한테 솔직하게 말해줘'라는 뜻입니다.",
  "suggested_questions": [
    "비슷한 다른 표현은 없나요?",
    "예문 더 보여줘"
  ]
}
```

### 4.2 Video Tutor 선제 질문 트리거 (로그인 필요)
- **Endpoint**: `POST /tutor/proactive`
- **Headers**: `Authorization: Bearer <access_token>`
- **Request Body**:
```json
{
  "video_id": "arj7oStGLkU",
  "current_timestamp": 210.5,
  "current_subtitle_en": "I ended up working there for five years."
}
```
- **Response (200 OK)**:
```json
{
  "has_proactive": true,
  "message_id": "msg_002",
  "question": "방금 유용한 표현이 하나 나왔어요.\n\n\"I ended up working there for five years.\"\n\n'end up ~ing'가 어떤 의미인지 알고 있나요?",
  "options": [
    { "id": "opt_yes", "label": "알아요" },
    { "id": "opt_no", "label": "모르겠어요" }
  ]
}
```

### 4.3 Tutor 응답 피드백 수집 (로그인 필요)
- **Endpoint**: `POST /tutor/feedback`
- **Headers**: `Authorization: Bearer <access_token>`
- **Request Body**:
```json
{
  "message_id": "msg_001",
  "rating": "up",
  "reason": null
}
```
*(rating: `"up"` | `"down"`, reason: `"너무 길어요"` | `"설명이 어려워요"` | `"영상과 무관"` | `"오답"`)*
- **Response (200 OK)**:
```json
{ "status": "ok" }
```

---

## 5. 실시간 로그 및 이벤트 수집 (Logging)

### 5.1 사용자 행동 로그 전송
- **Endpoint**: `POST /logs/event`
- **Headers**: `Authorization: Bearer <access_token>` (비로그인은 토큰 생략 가능)
- **Request Body**:
```json
{
  "event_type": "word_click",
  "video_id": "arj7oStGLkU",
  "timestamp": 156.4,
  "payload": {
    "word": "honest",
    "context": "I want to be honest with you."
  }
}
```
*(event_type 종류: `"login"`, `"watch_start"`, `"word_click"`, `"word_save"`, `"tutor_ask"`, `"tutor_proactive"`, `"feedback"`)*
- **Response (200 OK)**:
```json
{ "status": "recorded" }
```
