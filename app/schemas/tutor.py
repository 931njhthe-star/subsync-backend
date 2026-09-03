"""Video Tutor API의 외부 요청/응답 데이터 전송 객체(DTO).

이 모듈은 HTTP 입력을 검증하는 경계 계층이다. 내부 AI 로직은 Pydantic 모델 대신
``app.ai``의 dataclass를 사용하므로, 외부 API 형식이 바뀌어도 도메인 로직의
변경 범위를 좁힐 수 있다.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class SubtitleInput(BaseModel):
    """현재 재생 위치 주변에 포함할 하나의 자막 줄."""

    time: float = Field(ge=0, description="자막 시작 시각(초)")
    en: str = Field(min_length=1, max_length=500, description="영어 자막")
    ko: str | None = Field(default=None, max_length=500, description="한국어 자막")


class ConversationTurnInput(BaseModel):
    """이전 Tutor 대화 한 턴."""

    role: Literal["user", "tutor"] = Field(description="발화자")
    message: str = Field(min_length=1, max_length=2_000, description="대화 내용")


class SavedWordInput(BaseModel):
    """학습자가 저장한 단어 하나."""

    word: str = Field(min_length=1, max_length=100, description="저장 단어")


class LearnerSignalsInput(BaseModel):
    """사용자의 학습 행동을 프로필 추론기에 전달하는 입력."""

    saved_words: list[SavedWordInput] = Field(
        default_factory=list,
        max_length=500,
        description="현재 질문과 관련된 저장 단어 목록",
    )
    saved_word_count: int | None = Field(
        default=None,
        ge=0,
        le=100_000,
        description="전체 저장 단어 수",
    )
    quiz_accuracy: float | None = Field(
        default=None,
        ge=0,
        le=1,
        description="전체 퀴즈 정답률(0~1)",
    )
    average_response_time_ms: float | None = Field(
        default=None,
        ge=0,
        le=300_000,
        description="전체 평균 응답 시간(ms)",
    )
    recent_quiz_accuracy: float | None = Field(
        default=None,
        ge=0,
        le=1,
        description="최근 퀴즈 정답률(0~1)",
    )
    recent_response_time_ms: float | None = Field(
        default=None,
        ge=0,
        le=300_000,
        description="최근 평균 응답 시간(ms)",
    )
    quiz_attempts: int = Field(
        default=0,
        ge=0,
        le=100_000,
        description="프로필 신뢰도 보정에 사용할 퀴즈 시도 횟수",
    )


class TutorAskRequest(BaseModel):
    """Extension이 Tutor 질문 시 보내는 요청 본문."""

    video_id: str = Field(min_length=1, max_length=50, description="YouTube 영상 ID")
    timestamp: float = Field(ge=0, description="질문 시점(초)")
    user_message: str = Field(min_length=1, max_length=2_000, description="사용자 질문")
    recent_subtitles: list[SubtitleInput] = Field(
        default_factory=list,
        max_length=100,
        description="질문 시점 주변 자막",
    )
    learner_signals: LearnerSignalsInput = Field(
        default_factory=LearnerSignalsInput,
        description="학습자 수준 추론용 집계 신호",
    )
    conversation_history: list[ConversationTurnInput] = Field(
        default_factory=list,
        max_length=10,
        description="최근 Tutor 대화 이력",
    )
    focus_word: str | None = Field(
        default=None,
        max_length=100,
        description="사용자가 집중해서 보고 싶은 표현",
    )
    conversation_id: str | None = Field(
        default=None,
        max_length=100,
        description="이어갈 Tutor 대화 식별자",
    )


class ReplyTokenResponse(BaseModel):
    """Tutor 답변에서 Hover/Click 대상으로 표시할 영어 표현 하나."""

    surface: str = Field(description="답변에 실제 표시된 표현")
    normalized: str = Field(description="사전 검색에 사용할 정규화 표현")
    start: int = Field(ge=0, description="reply 내 UTF-16 시작 offset")
    end: int = Field(ge=0, description="reply 내 UTF-16 끝 offset(미포함)")
    interactive: bool = Field(
        default=True,
        description="Hover/Click 인터랙션 대상 여부",
    )


class TutorUsageResponse(BaseModel):
    """선택된 LLM provider가 반환한 토큰 사용량."""

    input_tokens: int = Field(ge=0, description="입력 토큰 수")
    output_tokens: int = Field(ge=0, description="출력 토큰 수")
    total_tokens: int = Field(ge=0, description="총 토큰 수")


class TutorAskResponse(BaseModel):
    """Video Tutor 답변과 개인화/비용 추적 메타데이터."""

    conversation_id: str = Field(description="현재 대화 식별자")
    message_id: str = Field(description="현재 Tutor 답변 식별자")
    reply: str = Field(description="Tutor 답변 본문")
    suggested_questions: list[str] = Field(description="후속 질문 목록(최대 3개)")
    provider: str = Field(description="실제 답변에 사용된 provider")
    model: str = Field(description="실제 답변에 사용된 모델명")
    usage: TutorUsageResponse = Field(description="LLM token 사용량")
    # 운영/대시보드에서 개인화 결과를 검증할 수 있도록 반환한다.
    # 실제 UI에서 숨기고 싶으면 API serializer 단계에서 제외하면 된다.
    learner_level: Literal["A1", "A2", "B1", "B2", "C1"] = Field(
        description="추론된 CEFR 수준",
    )
    tutor_difficulty: Literal[
        "foundational",
        "guided",
        "conversational",
        "nuanced",
        "challenge",
    ] = Field(description="수준에 맞춰 선택된 Tutor 답변 난이도")
    profile_confidence: float = Field(
        ge=0,
        le=1,
        description="학습자 수준 추론 신뢰도(0~1)",
    )
    context_subtitle_count: int = Field(
        ge=0,
        description="답변에 사용된 주변 자막 줄 수",
    )
    reply_tokens: list[ReplyTokenResponse] = Field(
        default_factory=list,
        description="답변에서 Hover/Click 가능한 영어 표현 목록",
    )


class TutorSettingsUpdateRequest(BaseModel):
    """Tutor 기능 활성화 상태를 변경하는 요청."""

    tutor_enabled: bool = Field(description="Tutor 기능 활성화 여부")


class TutorSettingsResponse(BaseModel):
    """현재 사용자의 Tutor 설정 응답."""

    tutor_enabled: bool = Field(description="Tutor 기능 활성화 여부")
    updated_at: datetime = Field(description="설정이 마지막으로 변경된 UTC 시각")


class ProactiveTutorRequest(BaseModel):
    """Tutor가 먼저 학습 질문을 제안할 때 필요한 영상 상태."""

    video_id: str = Field(min_length=1, max_length=50, description="YouTube 영상 ID")
    timestamp: float = Field(ge=0, description="현재 재생 시점(초)")
    recent_subtitles: list[SubtitleInput] = Field(
        max_length=100,
        description="현재 시점 주변 자막",
    )
    playback_state: Literal["playing", "paused", "seeking"] = Field(
        default="playing",
        description="현재 영상 재생 상태",
    )
    last_question_id: str | None = Field(
        default=None,
        max_length=100,
        description="마지막으로 표시한 선제 질문 ID",
    )
    last_question_at: float | None = Field(
        default=None,
        ge=0,
        description="마지막 선제 질문을 표시한 영상 시점(초)",
    )


class ProactiveTutorResponse(BaseModel):
    """선제 질문을 표시할지에 대한 판단 결과."""

    should_show: bool = Field(description="프론트가 선제 질문을 표시할지 여부")
    reason: Literal[
        "new_expression",
        "cooldown",
        "disabled",
        "insufficient_context",
        "already_seen",
        "paused",
    ] = Field(description="선제 질문 판단 사유")
    question_id: str | None = Field(
        default=None,
        description="선제 질문 ID. 표시하지 않으면 null",
    )
    question: str | None = Field(
        default=None,
        description="표시할 선제 질문. 표시하지 않으면 null",
    )
    focus_word: str | None = Field(
        default=None,
        description="선제 질문의 중심 표현",
    )
    expires_in_seconds: int | None = Field(
        default=None,
        ge=0,
        description="질문을 표시할 수 있는 유효 시간",
    )


class TutorFeedbackRequest(BaseModel):
    """Tutor 답변에 대한 사용자 평가 요청."""

    conversation_id: str = Field(
        min_length=1,
        max_length=100,
        description="Tutor 대화 식별자",
    )
    message_id: str = Field(
        min_length=1,
        max_length=100,
        description="평가할 Tutor 메시지 식별자",
    )
    rating: Literal["helpful", "not_helpful"] = Field(
        description="답변 유용성 평가",
    )
    reason: Literal[
        "incorrect",
        "too_difficult",
        "too_easy",
        "irrelevant",
        "other",
    ] | None = Field(
        default=None,
        description="부정 평가의 상세 사유",
    )
    comment: str | None = Field(
        default=None,
        max_length=1_000,
        description="사용자의 선택 의견",
    )


class TutorFeedbackResponse(BaseModel):
    """저장된 Tutor 답변 평가 응답."""

    feedback_id: str = Field(description="피드백 식별자")
    conversation_id: str = Field(description="Tutor 대화 식별자")
    message_id: str = Field(description="평가한 Tutor 메시지 식별자")
    rating: Literal["helpful", "not_helpful"] = Field(description="답변 유용성 평가")
    reason: Literal[
        "incorrect",
        "too_difficult",
        "too_easy",
        "irrelevant",
        "other",
    ] | None = Field(default=None, description="부정 평가의 상세 사유")
    comment: str | None = Field(default=None, description="사용자의 선택 의견")
    created_at: datetime = Field(description="피드백 생성 UTC 시각")
