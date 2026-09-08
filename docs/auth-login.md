# 로그인 연동 변경사항과 주의사항

최종 정리: 2026-09-08

Google 로그인은 확장이 하고, FastAPI는 Access Token을 검증한 뒤 `public.users`와
`login_history`만 기록한다. 비밀번호 로그인 API는 없다.

## 동작 흐름

```text
Google 로그인 (확장)
  → Supabase Auth (auth.users)
  → chrome.storage에 access_token 저장
  → 서비스 워커가 GET /api/v1/auth/me
  → public.users upsert + login_history insert

로그아웃 (확장)
  → 서비스 워커가 POST /api/v1/auth/logout
  → 같은 login_history 행의 logout_at 갱신
  → Supabase Auth logout + 로컬 토큰 삭제
```

Tutor·Hover는 로그인 없이 동작한다. `/words` 같은 보호 API는 아직 없다.

## 변경한 곳

### 백엔드

| 경로 | 역할 |
|---|---|
| `GET /api/v1/auth/me` | JWT 검증, `users` upsert, `login_history` insert |
| `POST /api/v1/auth/logout` | 열린 이력에 `logout_at` 기록 |
| `app/api/deps.py` | `get_current_user` (Bearer, 실패 시 401) |
| `app/core/security.py` | Supabase `GET /auth/v1/user`로 토큰 확인 |
| `app/db/users.py` | `public.users` |
| `app/db/login_history.py` | `login_history` |
| `app/core/config.py` | 서버 시작 시 백엔드 루트 `.env` 로드 |

사용자 ID는 요청 body가 아니라 JWT `sub`다. `public.users.id` = `auth.users.id`.

### 확장

| 경로 | 역할 |
|---|---|
| `src/background.js` | 로그인/로그아웃 직후 FastAPI 호출 |
| `src/services/auth_service.js` | Google OAuth는 서비스 워커에 위임 |
| `src/services/api_client.js` | 이후 API에 `Authorization: Bearer` 첨부 |

`/auth/me`와 `/auth/logout`은 **content script가 아니라 service worker**에서 친다.

## 채워지는 테이블

| 시점 | `auth.users` | `public.users` | `login_history` |
|---|---|---|---|
| Google 로그인만 (서버 꺼짐) | 채워짐 | 비어 있음 | 비어 있음 |
| 로그인 + FastAPI `/me` 성공 | 그대로 | upsert | 새 행 (`logout_at`은 NULL) |
| 로그아웃 + `/logout` 성공 | 그대로 | 그대로 | **같은 행**의 `logout_at` 채움 |

로그아웃은 새 줄을 만들지 않는다. Table Editor에서 로그인 때 생긴 행을 보면 된다.

`last_access_at`은 로그인/로그아웃 시점에만 넣고, 매 API마다 올리지 않는다.
`saved_words` 등 다른 테이블은 이 작업 범위 밖이다.

## 로컬에서 확인하는 방법

백엔드 폴더:

```powershell
uv run uvicorn app.main:app --reload --port 8000
```

`--env-file .env`는 필요 없다. `config.py`가 `.env`를 읽는다. `.env`만 수정하면
`--reload`가 감지를 못 하니 서버를 한 번 재시작한다.

1. `SUPABASE_URL`, `SUPABASE_SECRET_KEY`가 `.env`에 있는지 확인한다.
2. 확장 프로그램(`chrome://extensions`)을 다시 로드한다.
3. YouTube 탭을 새로고침한다.
4. Google 로그인 후 `users` / `login_history`를 확인한다.
5. 로그아웃 후 같은 `login_history` 행의 `logout_at`을 확인한다.

코드만 바꾸고 확장을 재로드하지 않으면 예전 서비스 워커가 그대로 돈다.

## 주의사항

1. **Google 로그인 ≠ 앱 테이블 기록**  
   Auth 창만 성공하고 FastAPI가 꺼져 있으면 `auth.users`만 생기고 이력은 비어 있다.
   FastAPI 장애는 구글 로그인을 실패로 바꾸지 않고, 콘솔에 경고만 남긴다.

2. **HTTPS YouTube → HTTP FastAPI**  
   content script에서 `http://127.0.0.1:8000`을 치면 mixed content로 막힌다.
   로그인 이력 동기화는 `background.js`에만 둔다. 페이지의 `api_client`로 `/auth/me`를
   다시 넣지 않는다.

3. **Redirect URL**  
   `https://<확장ID>.chromiumapp.org/supabase` 가 Dashboard Redirect URLs와 같아야 한다.
   `getRedirectURL("supabase")`와 path까지 맞춘다. 확장 ID가 바뀌면 다시 등록한다.

4. **authorize URL의 apikey**  
   호스팅된 Supabase는 `/auth/v1/authorize`에 키가 필요하다. 창이
   `Authorization page could not be loaded`로 끝나면 Redirect보다 이 문제를 먼저 본다.

5. **키 구분**  
   확장 `auth_config.js`: publishable/anon 키만.  
   백엔드 `.env`: `SUPABASE_SECRET_KEY` (service role).  
   Postman·로그·확장에 service role을 넣지 않는다.

6. **저장 키**  
   확장 storage는 `subsync_token`, `subsync_auth_session`이다. `access_token`이라는
   키 이름으로 찾으면 안 나온다.

7. **pytest**  
   테스트 실행 중에는 `.env`를 읽지 않는다. Tutor stub이 유지돼야 한다.

8. **아직 안 한 것**  
   Redis 세션, `/words` 보호 API, `api_logs.user_id` 연결, Tutor 로그인 필수화.
