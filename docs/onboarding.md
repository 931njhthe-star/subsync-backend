# SubSync Backend 온보딩

이 문서는 처음 참여한 팀원이 로컬에서 백엔드를 실행하고 첫 작업을 시작하기 위한
짧은 안내서다. 세부 규칙은 저장소 루트의 `AGENTS.md`를 먼저 읽는다.

## 1. 준비물

- Python 3.11 이상
- `uv`
- Git
- Postman (API 확인이 필요한 경우)

`uv` 설치 방법은 [공식 설치 안내](https://docs.astral.sh/uv/getting-started/installation/)를
따른다. 설치가 끝났는지 다음 명령으로 확인한다.

```bash
uv --version
python --version
```

## 2. 서버와 테스트 실행

터미널 1에서 서버를 실행한다.

```bash
uv run uvicorn app.main:app --reload --port 8000 --env-file .env
```

브라우저에서 다음 주소를 확인한다.

- Health: <http://127.0.0.1:8000/health>
- Swagger UI: <http://127.0.0.1:8000/docs>
- OpenAPI JSON: <http://127.0.0.1:8000/openapi.json>

터미널 2에서 테스트를 실행한다.

```bash
uv run pytest
```

테스트가 실패하면 먼저 서버가 필요한 테스트인지, `.env`의 provider가 `stub`인지,
`uv sync`가 끝났는지 확인한다.

## 3. Postman 확인

현재 공유 Collection의 기준 파일은 다음 JSON이다.

- `postman/SubSync-API.postman_collection.json`
- `postman/SubSync-Local.postman_environment.json`

Postman에서 두 JSON을 Import하고 `SubSync Local` 환경을 선택한다. 서버가 실행된
상태에서 Collection Runner를 실행한다. Google OAuth 로그인 자체는 브라우저 동의
화면이 필요하므로 Postman에서 자동 로그인하지 않고, 로그인 후 받은 Supabase
Access Token을 환경 변수 `access_token`에 넣어 보호 API를 확인한다.

Postman의 폴더형 YAML 파일은 현재 JSON Collection에서 파생된 작업 공간 자료다. API
요청을 추가할 때는 JSON 기준 파일을 먼저 갱신하고, YAML 자료를 계속 사용한다면
내보내기 결과가 일치하는지 확인한다.

## 4. 작업 시작 방법

1. `AGENTS.md`와 수정 분야의 `docs/` 문서를 읽는다.
2. 작업 브랜치를 만든다.
3. 기능 하나를 구현하면서 API 명세, Postman, 테스트 또는 migration을 함께 갱신한다.
4. 제출 전에 다음 명령을 실행한다.

```bash
uv run pytest
git diff --check
git status
```

## 5. 담당 영역

- 소예: Auth, User, Word Save, History, Feedback, Supabase, DB/RLS/migration
- 서윤: Video, Subtitle, Script, Dictionary, Hover, Redis, 콘텐츠 API
- 경락: LLM, AI Tutor, 문맥·프롬프트·provider/fallback

다른 담당자의 영역과 연결이 필요하면 먼저 `AGENTS.md`의 공통 데이터 계약을
확인하고, 구현이 끝나지 않은 영역은 fixture/mock으로 연결한다. 계약을 임의로
바꾸지 말고 API 명세와 테스트를 함께 수정한다.