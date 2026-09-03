# SubSync 문서 인덱스

`docs/`는 문서의 목적과 변경 주체가 섞이지 않도록 분야별 폴더로 관리한다. 새 문서는
가장 가까운 분야 폴더에 넣고, 여러 분야에 걸치면 이 인덱스와 관련 문서에서 링크한다.

## 문서 구조

```text
docs/
├── architecture/
│   ├── architecture.md                 # 시스템 구성과 데이터 흐름
│   └── subsync-architecture-guide.md   # 레포지토리·폴더·역할·협업 설계
├── api/
│   ├── api_spec.md                     # API 공통 규칙·인증·오류
│   └── tutor_api_spec.md               # Video Tutor API 계약
├── ai/
│   ├── ai_tutor_requirements.md        # AI Tutor 요구사항 정리
│   └── ai-tutor.md                     # AI Tutor 구현 설계
├── database/
│   └── db_schema.sql                   # 현재 전체 Supabase 스키마
└── migrations/                         # DB 변경 이력 (변경 발생 시 생성)
```

## 권장 읽는 순서

1. [시스템 아키텍처](architecture/architecture.md)로 전체 흐름을 파악한다.
2. [레포지토리·역할 설계](architecture/subsync-architecture-guide.md)로 담당 범위를 확인한다.
3. 작업 분야에 따라 [API 공통 규칙](api/api_spec.md), [DB 스키마](database/db_schema.sql),
   [AI Tutor 요구사항](ai/ai_tutor_requirements.md)을 읽는다.
4. 구현할 API는 [Tutor API 계약](api/tutor_api_spec.md) 등 도메인 명세를 기준으로 한다.

## 분야별 변경 규칙

- **Architecture**: 시스템 구성, 폴더 책임, 팀 역할이 바뀔 때 갱신한다.
- **API**: 경로·요청·응답·인증·상태 코드가 바뀔 때 `api/` 명세와 Postman, 테스트를 함께 갱신한다.
- **AI**: 프롬프트, 문맥, 모델, fallback, 토큰 한도가 바뀔 때 `ai/` 문서와 테스트를 함께 갱신한다.
- **Database**: 테이블·컬럼·인덱스·RLS가 바뀔 때 `migrations/`에 SQL을 추가하고
  `database/db_schema.sql`을 최신 상태로 갱신한다.

문서의 구현 상태는 실제 코드와 일치해야 한다. 문서 간 링크가 깨지지 않는지도 변경 후 확인한다.
