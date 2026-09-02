# SubSync 시스템 아키텍처 및 데이터 흐름도

## 1. 전체 아키텍처 개요

```text
  [ Chrome Extension (Frontend) ]
                 │
                 │ HTTP / REST API (JSON)
                 ▼
     [ FastAPI Server (Backend) ]
        │         │          │
        ▼         ▼          ▼
   [ Supabase ] [ Redis ] [ Gemini AI ]
    (PostgreSQL) (Cache)  (Video Tutor)
        │
        ▼
[ Streamlit Dashboard & Analytics ]
```

## 2. 레이어별 역할 분담

1. **`app/core`**: 환경변수(`config.py`), 보안(`security.py`), DB 클라이언트(`database.py`), 캐시(`redis_client.py`)
2. **`app/api/v1`**: 엔드포인트 라우터 (`auth`, `dictionary`, `words`, `tutor`, `logs`)
3. **`app/schemas`**: Pydantic DTO (요청/응답 규격)
4. **`app/services`**: 비즈니스 로직 및 3단계 사전 캐시 흐름
5. **`app/ai`**: Gemini SDK 연동, 프롬프트 엔지니어링 및 컨텍스트 빌더
6. **`dashboard`**: Streamlit 관제 대시보드 및 pandas 기반 로그 분석
