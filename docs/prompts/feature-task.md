# 바이브코딩 작업 프롬프트 템플릿

팀원이 AI 코딩 도구에 기능을 요청할 때 아래 내용을 복사해 작성한다. 한 번에 큰
기능을 맡기지 말고, 하나의 API나 하나의 저장 흐름처럼 작게 나눈다.

```text
저장소 루트의 AGENTS.md를 먼저 읽고 모든 규칙을 준수해줘.

작업 제목: [예: 저장 단어 목록 조회 API]
담당 영역: [소예 / 서윤 / 경락]
목표: [사용자가 무엇을 할 수 있어야 하는지 한 문장]

참고 문서:
- [예: docs/api/api_spec.md]
- [예: docs/database/db_schema.sql]
- [예: docs/api/tutor_api_spec.md]

수정 가능한 범위:
- [예: app/api/v1/, app/schemas/, app/services/, tests/, postman/]
- 담당자가 아닌 도메인 로직이나 공유 계약은 임의로 재설계하지 말 것

구현 조건:
- 외부 입력은 Pydantic schema로 검증할 것
- 보호 API는 Supabase JWT의 sub로 사용자 식별할 것
- 외부 API 없이 stub/fake로 테스트 가능할 것
- 초심자가 흐름을 이해할 수 있는 docstring과 필요한 "왜" 주석을 작성할 것

필수 산출물:
- [ ] 구현 코드
- [ ] 정상/실패 pytest
- [ ] API 변경이면 API 명세와 Postman Collection
- [ ] DB 변경이면 docs/migrations/의 SQL과 docs/database/db_schema.sql
- [ ] 새 환경변수면 .env.example과 README/관련 문서

검증:
- uv run pytest
- git diff --check

마지막 응답에는 다음을 요약해줘:
1. 수정한 파일과 각 파일의 이유
2. 구현한 동작과 미구현/가정
3. 실행한 검증 명령과 결과
4. 다른 담당자에게 확인이 필요한 계약 변경
```

AI가 요청 범위를 넘어 파일을 수정하거나 명세와 코드가 충돌한다고 판단하면
추측으로 진행하지 말고 먼저 충돌 내용을 설명하게 한다.
