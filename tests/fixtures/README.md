# 테스트 fixture

세 담당자가 서로의 구현을 기다리지 않고 API와 AI 로직을 개발할 수 있도록 공유하는
최소 예시 데이터다. 실제 사용자 정보, Access Token, API 키를 넣지 않는다.

- `tutor_request.json`: Tutor API에 보낼 수 있는 대표 요청
- `subtitles.json`: Video/Subtitle API와 Tutor 문맥에서 사용하는 표준 자막
- `saved_words.json`: 사용자 저장 단어와 Tutor 학습 신호 예시
- `users.json`: 테스트용 가상 사용자 식별자와 프로필

fixture 필드의 이름이나 타입을 바꾸면 관련 Pydantic schema, API 명세, 테스트를 함께
확인한다.
