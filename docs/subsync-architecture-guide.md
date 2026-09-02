# SubSync 아키텍처 및 레포지토리/폴더 구조 설계서

> **문서 목적**: 5인 팀이 단기 스프린트 동안 충돌 없이 고품질 제품(SubSync)을 완성할 수 있도록, **2개 레포지토리 분리 이유**와 **프론트엔드/백엔드 세분화 폴더 구조의 설계 근거**를 명문화한다.

---

## 1. 2개 레포지토리(Multi-repo) 분리 근거

본 프로젝트는 다음과 같은 기술적·협업적 이유로 **Frontend**와 **Backend/Data** 2개 레포지토리로 분리 관리한다.

```text
┌──────────────────────────────────────┐     ┌──────────────────────────────────────┐
│  📦 1. subsync-extension (Frontend)  │     │   📦 2. subsync-backend (Backend)    │
│  - Chrome Extension Manifest V3      │     │  - FastAPI REST API 서버             │
│  - HTML / CSS / Vanilla JavaScript   │     │  - Gemini AI (Video Tutor)           │
│  - DOM 조작 & 마우스 이벤트 처리     │     │  - Supabase PostgreSQL + Redis       │
│  - 클라이언트 로컬 스토리지 캐시     │     │  - Streamlit 운영/분석 대시보드      │
└──────────────────────────────────────┘     └──────────────────────────────────────┘
                  ▲                                             │
                  │              HTTP / HTTPS (JSON)            │
                  └─────────────────────────────────────────────┘
```

### 1.1 기술 스택 및 런타임 환경의 완전한 분리
- **Frontend**: 브라우저 런타임(V8 엔진)에서 실행되는 Manifest V3 Chrome Extension. 빌드/배포 단위가 웹스토어 패키징 또는 개발자 모드 로드임.
- **Backend/AI/Dashboard**: Python 3.11+ 런타임에서 실행되는 FastAPI + Gemini SDK + Streamlit. 서버 인프라(Docker, 클라우드 서버)에 배포됨.
- 의존성 관리 도구(`npm/package.json` vs `pip/requirements.txt`)가 완전히 달라 레포지토리가 섞일 경우 환경 충돌 및 불필요한 설정 오버헤드가 발생함.

### 1.2 Git 충돌(Conflict) 원천 차단
- 5명이 1개 레포지토리를 공유할 경우 루트의 `.gitignore`, `README.md`, 공통 설정 파일에서 머지 충돌 위험이 상존함.
- 클라이언트 작업(UI/마우스)과 서버 작업(DB/AI/API)의 커밋 히스토리를 분리하여 병렬 작업 속도를 극대화함.

### 1.3 배포 및 CI/CD 독립성
- 백엔드 서버 변경 배포 시 확장 프로그램 레포는 영향을 받지 않으며, 확장 프로그램 UI 패치 시 백엔드 재배포가 불필요함.

---

## 2. 레포지토리별 세분화 폴더 구조 및 설계 이유

### 2.1 [Frontend 레포] `subsync-extension`

```text
subsync-extension/
├── manifest.json              # Chrome Extension MV3 메타데이터
├── popup.html                 # 확장 프로그램 툴바 팝업
│
├── assets/                    # 아이콘 및 정적 리소스
│   └── icons/                 # icon16, icon48, icon128
│
├── styles/                    # 컴포넌트별 CSS 모듈 분리
│   ├── main.css               # 2열 메인 레이아웃 및 리셋
│   ├── subtitle.css           # 영상 오버레이 실시간 이중자막
│   ├── script.css             # 전체 스크립트 패널
│   ├── interactive.css        # Hover 툴팁, Click 상세 팝업
│   ├── tutor.css              # Video Tutor 채팅창 및 피드백 버튼
│   └── modal.css              # 비로그인 유도 팝업 모달
│
└── src/
    ├── core/                  # [엔진 계층] YouTube 핵심 캡처 및 제어
    │   ├── inject.js          # (MAIN 월드) YouTube pot 우회 및 timedtext URL 가로채기
    │   ├── captions.js        # 다국어 자막 파싱 및 시간 병합
    │   └── player.js          # YouTube 동영상 재생/일시정지/타임스탬프 이동(Seek) 제어
    │
    ├── components/            # [UI 계층] 독립된 화면 조각 컴포넌트
    │   ├── layout.js          # 2열 패널 프레임 (영상 영역 / AI 패널)
    │   ├── subtitle_view.js   # 실시간 이중자막 렌더러
    │   ├── script_panel.js    # 전체 스크립트 리스트 ON/OFF 및 스크롤 동기화
    │   ├── tutor_chat.js      # Video Tutor 메시지 리스트 & 질문 입력창
    │   └── auth_modal.js      # 비로그인 시 Click 차단 및 로그인 안내 모달
    │
    ├── interactive/           # [핵심 계층] InteractiveEnglishText 공통 모듈
    │   ├── tokenizer.js       # 영문 문장을 특수문자 분리해 단어(span) 단위로 토큰화
    │   ├── hover_tooltip.js   # 0.5초 Hover 빠른 사전 뜻 툴팁 (비로그인 허용)
    │   ├── click_popup.js     # Click 상세 단어 설명 팝업 및 단어 저장 버튼
    │   └── interactive_text.js# 자막/스크립트/튜터 메시지에 위 이벤트를 부착하는 공통 래퍼
    │
    ├── services/              # [통신/데이터 계층] 백엔드 연동 및 로컬 캐시
    │   ├── api_client.js      # fetch 공통 래퍼 (Base URL, JWT 토큰 주입, 에러 핸들링)
    │   ├── dict_service.js    # 사전 조회 (sessionStorage 1차 캐시 → 백엔드 요청)
    │   ├── tutor_service.js   # Video Tutor API (질문, 선제 질문, 피드백)
    │   ├── auth_service.js    # 로그인/회원가입/토큰 저장 (chrome.storage)
    │   └── log_service.js     # 단어 클릭/저장/시청 행동 로그 전송
    │
    └── content_main.js        # [조립 엔트리포인트] 전체 컴포넌트 초기화 및 이벤트 연결
```

#### 프론트엔드 폴더 설계 이유
1. **`core/`의 격리**: YouTube pot 토큰 우회 및 자막 추출 로직은 민감하고 고난이도 코드이므로, 일반 UI 작업자가 실수로 훼손하지 않도록 별도 폴더로 격리함.
2. **`interactive/` 공통화**: *"영어가 보이는 모든 곳(자막, 스크립트, 챗봇)에서 동일한 마우스 인터랙션 제공"*이라는 핵심 원칙을 지키기 위해, 마우스 인터랙션을 단일 공통 모듈로 설계하여 어디서든 재사용 가능하게 함.
3. **`components/` 분업 용이성**: 스크립트 패널, 튜터 채팅창, 로그인 모달을 파일 단위로 쪼개어 다른 팀원이 프론트를 지원할 때 충돌 없이 특정 컴포넌트만 맡을 수 있게 함.
4. **`services/` 캡슐화**: API 통신 및 `sessionStorage` 캐싱 로직을 UI 코드와 분리하여 서버 URL 변경이나 API 스펙 변경 시 서비스 파일만 수정하면 됨.

---

### 2.2 [Backend & Data 레포] `subsync-backend`

```text
subsync-backend/
├── docs/                      # PM 및 팀 공통 계약 문서
│   ├── api_spec.md            # FE-BE REST API 입출력 JSON 명세서
│   ├── db_schema.sql          # Supabase PostgreSQL DDL 스키마
│   └── subsync-architecture-guide.md # 본 아키텍처 가이드 문서
│
├── app/                       # FastAPI 메인 애플리케이션
│   ├── main.py                # FastAPI 진입점 (CORS 미들웨어, 라우터 등록)
│   │
│   ├── core/                  # 인프라, 보안 및 DB 연결
│   │   ├── config.py          # 환경변수 로더 (Pydantic BaseSettings)
│   │   ├── security.py        # JWT 토큰 발급/검증, 비밀번호 bcrypt 해싱
│   │   ├── database.py        # Supabase 클라이언트 세션
│   │   └── redis_client.py    # Redis 연결 풀 및 고속 get/set 래퍼
│   │
│   ├── api/                   # HTTP 엔드포인트 라우터
│   │   ├── v1/
│   │   │   ├── auth.py        # POST /login, /signup, GET /me
│   │   │   ├── dictionary.py  # GET /dict/hover, GET /dict/detail
│   │   │   ├── words.py       # POST /words/save, GET /words/list
│   │   │   ├── tutor.py       # POST /tutor/ask, /tutor/proactive, /tutor/feedback
│   │   │   └── logs.py        # POST /logs/event (행동 로깅)
│   │   └── deps.py            # 공통 의존성 주입 (get_current_user, get_db)
│   │
│   ├── schemas/               # Pydantic DTO (요청/응답 데이터 검증)
│   │   ├── auth.py            # 로그인/회원가입 요청/응답 스키마
│   │   ├── dictionary.py      # Hover/Click 사전 응답 스키마
│   │   ├── tutor.py           # Tutor 질문/답변/피드백 스키마
│   │   └── logs.py            # 클릭/시청/에러 이벤트 로그 스키마
│   │
│   ├── services/              # 비즈니스 로직 계층
│   │   ├── auth_service.py    # 사용자 가입 및 비밀번호 검증
│   │   ├── dict_service.py    # 3단계 사전 검색 (로컬DB → Redis → FreeDict API)
│   │   ├── word_service.py    # 저장 단어 CRUD
│   │   └── log_service.py     # Supabase DB & Redis 로그 저장
│   │
│   ├── ai/                    # [AI 전담] Video Tutor & Gemini 파이프라인
│   │   ├── gemini_client.py   # Google GenAI SDK 초기화 및 호출 래퍼
│   │   ├── prompts.py         # 선제 질문 및 질의응답 시스템 프롬프트 모음
│   │   ├── context_builder.py # 현재 자막 타임라인 기반 Context 생성기
│   │   └── tutor_service.py   # AI 응답 생성 및 피드백 기반 튜닝 로직
│   │
│   └── data/                  # 오프라인 정적 사전 데이터
│       └── base_dictionary.json # 빈출 영단어 1~2만개 기본 사전 (초고속 응답용)
│
├── dashboard/                 # [Streamlit 운영 및 분석 대시보드]
│   ├── app.py                 # Streamlit 대시보드 메인 진입점
│   ├── components/            # 시각화 위젯 컴포넌트
│   │   ├── kpi_metrics.py     # DAU, 질문수, 클릭수, 저장수 KPI 카드
│   │   ├── realtime_logs.py   # 실시간 사용자 이벤트 스트리밍 뷰어
│   │   └── feedback_view.py   # AI 답변 만족도(👍/👎) 및 오류율 분석
│   └── analytics/             # 데이터 과학/분석 모듈
│       ├── data_loader.py     # Supabase 로그 추출 및 pandas 전처리
│       ├── user_patterns.py   # 학습 행동 패턴 및 취약 단어 빈도 분석
│       └── ai_quality_eval.py # 피드백-응답시간/길이 상관관계 분석 (scipy, sklearn)
│
├── tests/                     # pytest 단위/통합 테스트
│   ├── test_auth.py
│   ├── test_dict.py
│   └── test_tutor.py
│
├── requirements.txt           # Python 통합 의존성
└── .env.example               # 환경변수 예시 파일
```

#### 백엔드 폴더 설계 이유
1. **`app/ai/`의 완전 격리**: Gemini API 연동 및 프롬프트 엔지니어링은 변경 주기가 빠르므로, 일반 백엔드 API와 섞이지 않게 전용 폴더로 분리하여 AI 담당자(경락)가 독립적으로 튜닝할 수 있게 함.
2. **사전 3단계 캐싱 최적화 (`dict_service.py`)**: Hover는 초고속 응답(0.5초 이내)이 생명이므로 `Browser Storage` ➔ `Redis` ➔ `base_dictionary.json` ➔ `External API` 순으로 조회하는 파이프라인을 `services/dict_service.py` 한 곳에 캡슐화함.
3. **`dashboard/` 통합 관리**: Streamlit 대시보드와 pandas 분석 모듈이 백엔드와 동일한 Supabase DB 및 Redis를 바라보고 동일한 Python 환경을 공유하므로, 같은 레포 안의 독립 폴더로 배치해 데이터 모델 공유를 극대화함.
4. **`docs/` 명세 선행**: 프론트-백엔드 간 계약서 역할을 하는 `api_spec.md`와 `db_schema.sql`을 백엔드 루트 `docs/`에 배치하여 팀의 단일 진실 공급원(Single Source of Truth)으로 삼음.

---

## 3. 팀 역할 및 폴더 담당 매핑표

| 역할 | 담당자 | 주 작업 폴더 | 핵심 산출물 |
| :--- | :--- | :--- | :--- |
| **PM / Lead** | 노지훈 | `docs/`, `dashboard/` | 기획/일정 조율, `api_spec.md`, Streamlit 대시보드 & pandas 분석 |
| **Frontend Lead** | 김훈 | `subsync-extension/src/` | 2열 레이아웃, `interactive/` 마우스 엔진, 자막/스크립트 연동 |
| **Backend (DB/Auth/Log)** | 소예 | `app/api/v1/auth.py`, `logs.py`, `app/core/`, `app/services/` | Supabase 연동, JWT 인증, 실시간 로그 수집 API |
| **Backend (Dict/Cache/Words)** | 서윤 | `app/api/v1/dictionary.py`, `words.py`, `app/services/dict_service.py` | Redis 캐시 연동, 3단계 사전 검색 엔진, 단어 저장 API |
| **AI / Video Tutor** | 경락 | `app/ai/`, `app/api/v1/tutor.py` | Gemini 프롬프트 엔지니어링, 선제 질문 생성, 컨텍스트 빌더 |

---

## 4. 협업 워크플로우 (Day 1 시작 규칙)

1. **API First**: 백엔드는 첫날 1시간 내에 `docs/api_spec.md`를 기반으로 가짜 Mock JSON을 반환하는 더미 API를 먼저 배포한다.
2. **독립 개발**: 프론트엔드는 Mock API를 바라보며 UI와 마우스 인터랙션을 막힘없이 개발한다.
3. **CORS 전체 허용**: 로컬 개발 시 Chrome Extension에서 호출할 수 있도록 FastAPI `CORSMiddleware`에 `allow_origins=["*"]`를 설정한다.
4. **Secret 격리**: API Key 및 DB 접속 정보는 `.env`에 두고 절대 Git에 올리지 않는다 (`.env.example`만 공유).
