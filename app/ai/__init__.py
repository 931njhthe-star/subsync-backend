"""Video Tutor 도메인 로직.

이 패키지는 HTTP 라우터나 특정 LLM SDK에 종속되지 않는다.
프로필 추론과 프롬프트 생성은 결정적으로 테스트할 수 있고,
LLM 호출은 ``LLMClient`` 어댑터 뒤에 숨긴다.
"""

from app.ai.learner_profile import (
    CEFRLevel,
    LearnerProfile,
    LearnerSignals,
    TutorDifficulty,
    infer_learner_profile,
)

__all__ = [
    "CEFRLevel",
    "LearnerProfile",
    "LearnerSignals",
    "TutorDifficulty",
    "infer_learner_profile",
]
