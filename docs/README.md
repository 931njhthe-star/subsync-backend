# SubSync 문서 인덱스

`docs/`는 현재 구현, API 계약, DB 기준을 분리해 관리한다. 구현 상태는 문서가 아니라
FastAPI 라우터와 테스트가 최종 기준이며, DB의 실제 생성 기준은
[database/README.md](database/README.md)에 명시한다.

## 문서 구조

```text
docs/
├── onboarding.md                         # 로컬 실행과 작업 시작 방법
├── auth-login.md                         # Google 로그인·users/login_history 연동
└── database/
    ├── README.md                         # SQL 정본, 실행 순서, 정합성 점검 결과
    ├── 1. users.sql ... 6. api_logs.sql
    └── db_schema.sql                     # 1~6번 SQL을 합친 참조용 스키마
```

## 권장 읽는 순서

1. [온보딩 안내](onboarding.md)와 저장소 루트의 `AGENTS.md`를 읽는다.
2. 로그인·`users`/`login_history` 연동은 [auth-login.md](auth-login.md)를 확인한다.
3. API 계약은 로컬 서버의 `/docs`, Postman Collection, `tests/`를 기준으로 확인하고,
   AI·DB 작업은 해당 문서를 읽는다.
4. DB 변경 전에는 반드시 [DB 기준과 점검 결과](database/README.md)를 확인한다.

## 변경 규칙

- API 계약이 바뀌면 Pydantic DTO, Postman Collection, 테스트를 함께 갱신하고
  `/openapi.json`에 의도한 경로·스키마가 노출되는지 확인한다.
- Streamlit Dashboard API는 `app/api/v1/dashboard.py`와
  `app/services/dashboard.py`에서 `llm_usage`·`api_logs` 조회 및 집계를 담당한다.
- Tutor 동작·provider·사용량 제한이 바뀌면 코드 docstring, `.env.example`, 테스트를 함께 갱신한다.
- 이미 실행한 DB 기준 SQL은 수정하지 않는다. 변경은 새 migration으로 추가하고,
  적용 후 `db_schema.sql`과 `database/README.md`를 갱신한다.
- 계획 문서에는 현재 구현 여부를 명확히 표시하고, 존재하지 않는 파일이나 API를
  현재 동작처럼 기술하지 않는다.
