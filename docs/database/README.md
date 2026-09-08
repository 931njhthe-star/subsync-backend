# SubSync DB 기준

이 폴더의 SQL은 현재 Supabase 테이블 정보를 기준으로 정리한 DDL 스냅샷이다.
번호 파일과 `db_schema.sql`은 같은 6개 테이블을 표현한다.

## 테이블과 실행 순서

```text
1. users            # auth.users와 연결된 앱 사용자
2. login_history    # 로그인·접근 이력
3. saved_words      # 저장 단어
4. ai_conversations # AI 질문·답변·피드백
5. llm_usage        # LLM 토큰 사용량
6. api_logs         # API 요청 로그
```

`users.id`는 `auth.users(id)`를 참조한다. 나머지 사용자 데이터 테이블의 `user_id`는
`public.users(id)`를 참조하므로, 번호 순서대로 실행한다.

새 환경에서는 번호 SQL 파일 또는 `db_schema.sql` 중 하나만 실행한다. 이미 존재하는
운영 테이블을 이 DDL로 다시 만들거나 수정하지 않는다. 실제 DB를 변경해야 하면
`docs/migrations/`에 새 migration을 추가한다.

## 현재 애플리케이션 상태

`GET /api/v1/auth/me`와 `POST /api/v1/auth/logout`이 `public.users`와
`login_history`를 읽고 쓴다. Tutor 대화·피드백은 아직 개발용 메모리에 두고,
`saved_words` repository는 구현되어 있지 않다.

## 미확인 항목

제공된 테이블 정보에는 다음 항목이 포함되지 않아 이 SQL에 추측으로 추가하지 않았다.

- `NOT NULL`, `DEFAULT`, `ON DELETE` 제약조건
- 인덱스와 unique 제약조건(`google_account_id` 외)
- RLS 활성화 및 정책
- trigger, 함수, view, extension

이 항목까지 DB와 완전히 대조하려면 Supabase의 schema-only dump 또는 SQL Editor에서
추출한 테이블·인덱스·RLS 정책 정의가 필요하다.
