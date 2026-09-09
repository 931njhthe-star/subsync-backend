"""학습 데이터에서 학습자 수준과 튜터 난이도를 추론한다.

초기 버전에서는 LLM에게 수준 판정을 맡기지 않는다. 같은 입력에 같은 결과를
내고, 데이터가 부족할 때 기본 수준(A2)으로 완만하게 수렴하도록 만든다.
저장 단어 수는 사용자의 학습량을 보여주는 약한 신호이므로 정답률과 응답 시간보다
낮은 가중치를 둔다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping


class CEFRLevel(str, Enum):
    """튜터가 사용할 내부 영어 수준 구간."""

    A1 = "A1"
    A2 = "A2"
    B1 = "B1"
    B2 = "B2"
    C1 = "C1"


class TutorDifficulty(str, Enum):
    """수준을 실제 튜터 답변 스타일로 변환한 내부 난이도."""

    FOUNDATIONAL = "foundational"
    GUIDED = "guided"
    CONVERSATIONAL = "conversational"
    NUANCED = "nuanced"
    CHALLENGE = "challenge"


@dataclass(frozen=True)
class LearnerSignals:
    """프로필 추론에 필요한 집계 학습 신호.

    ``accuracy``와 ``average_response_time_ms``는 같은 기간의 값으로 보내는 것을
    권장한다. ``recent_*`` 값이 있으면 전체 평균보다 최근 값을 우선한다.
    ``saved_words``는 현재 요청과 관련된 저장 단어를 프롬프트에 넣기 위한 값이며,
    수준 추론에는 ``saved_word_count``만 사용한다.
    """

    saved_word_count: int = 0
    quiz_attempts: int = 0
    accuracy: float | None = None
    average_response_time_ms: float | None = None
    recent_accuracy: float | None = None
    recent_response_time_ms: float | None = None
    saved_words: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class LearnerProfile:
    """추론 결과와 근거를 담는 값 객체."""

    level: CEFRLevel
    tutor_difficulty: TutorDifficulty
    score: float
    confidence: float
    evidence: Mapping[str, float] = field(default_factory=dict)


_LEVEL_BY_SCORE: tuple[tuple[float, CEFRLevel], ...] = (
    (1.5, CEFRLevel.A1),
    (2.5, CEFRLevel.A2),
    (3.5, CEFRLevel.B1),
    (4.5, CEFRLevel.B2),
    (float("inf"), CEFRLevel.C1),
)

_DIFFICULTY_BY_LEVEL: dict[CEFRLevel, TutorDifficulty] = {
    CEFRLevel.A1: TutorDifficulty.FOUNDATIONAL,
    CEFRLevel.A2: TutorDifficulty.GUIDED,
    CEFRLevel.B1: TutorDifficulty.CONVERSATIONAL,
    CEFRLevel.B2: TutorDifficulty.NUANCED,
    CEFRLevel.C1: TutorDifficulty.CHALLENGE,
}


def _clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    """수치를 지정한 범위 안으로 제한한다."""

    return max(minimum, min(value, maximum))


def _interpolate(value: float, points: tuple[tuple[float, float], ...]) -> float:
    """단조로운 기준점 사이를 선형 보간해 1~5 점수로 만든다."""

    if value <= points[0][0]:
        return points[0][1]
    for (left_x, left_y), (right_x, right_y) in zip(points, points[1:]):
        if value <= right_x:
            ratio = (value - left_x) / (right_x - left_x)
            return left_y + ratio * (right_y - left_y)
    return points[-1][1]


def _accuracy_score(accuracy: float) -> float:
    """퀴즈 정답률을 1~5 수준 점수로 변환한다."""

    # 단순한 맞힌 개수보다 구간 사이의 완만한 변화를 주기 위한 기준점이다.
    return _interpolate(
        _clamp(accuracy),
        (
            (0.00, 1.0),
            (0.50, 1.5),
            (0.65, 2.5),
            (0.78, 3.5),
            (0.90, 4.5),
            (1.00, 5.0),
        ),
    )


def _response_time_score(response_time_ms: float) -> float:
    """평균 응답 시간을 1~5 수준 점수로 변환한다.

    응답 시간이 짧을수록 높은 점수를 주지만, 부주의한 빠른 응답이 전체 수준을
    과도하게 높이지 않도록 전체 점수의 25%만 반영한다.
    """

    # 짧을수록 높은 점수지만, 수준 판정의 보조 신호로만 사용한다.
    return _interpolate(
        max(response_time_ms, 0.0),
        (
            (2_500.0, 5.0),
            (4_500.0, 4.0),
            (7_000.0, 3.0),
            (10_000.0, 2.0),
            (15_000.0, 1.0),
        ),
    )


def _saved_word_score(saved_word_count: int) -> float:
    """저장 단어 수를 학습량의 약한 대리 지표로 변환한다.

    단어를 많이 저장하는 것이 곧 높은 실력이라는 뜻은 아니므로 기준선 주변의
    작은 영향만 주도록 사용한다. 단어 수가 0이면 정보가 없는 것으로 취급한다.
    """

    if saved_word_count <= 0:
        return 2.0
    return _interpolate(
        float(saved_word_count),
        (
            (1.0, 1.5),
            (10.0, 2.0),
            (30.0, 2.8),
            (80.0, 3.8),
            (150.0, 4.5),
            (250.0, 5.0),
        ),
    )


def _pick_level(score: float) -> CEFRLevel:
    """종합 점수를 CEFR 구간으로 변환한다."""

    for boundary, level in _LEVEL_BY_SCORE:
        if score < boundary:
            return level
    return CEFRLevel.C1


def _confidence(signals: LearnerSignals, has_accuracy: bool, has_response_time: bool) -> float:
    """관측량을 0~1로 정규화한다.

    퀴즈 20회 정도가 쌓이면 정답률/응답 시간의 신뢰도를 최대치로 본다. 저장
    단어만 있는 신규 사용자는 낮은 신뢰도로 A2 기준선에 가깝게 유지한다.
    """

    attempts_factor = _clamp(signals.quiz_attempts / 20.0)
    signal_factor = (
        (0.55 if has_accuracy else 0.0)
        + (0.25 if has_response_time else 0.0)
        + (0.20 if signals.saved_word_count > 0 else 0.0)
    )
    if signal_factor == 0.0:
        return 0.0

    # 집계값만 전달되고 attempts가 생략된 경우에도 완전한 0으로 만들지 않는다.
    observation_factor = max(0.25, attempts_factor) if signals.quiz_attempts == 0 else attempts_factor
    return round(_clamp(signal_factor * observation_factor), 2)


def infer_learner_profile(signals: LearnerSignals) -> LearnerProfile:
    """학습 신호를 이용해 수준과 튜터 난이도를 결정한다.

    기본 수준은 A2(점수 2.0)다. 관측 신뢰도가 높아질수록 신호 기반 점수에
    가까워진다. 이 방식은 첫 질문 한 번의 오답 때문에 튜터가 갑자기 C1에서
    A1으로 바뀌는 현상을 줄인다.
    """

    # 최근 데이터가 있으면 오래된 전체 평균보다 현재 실력을 더 잘 반영한다고 본다.
    accuracy = signals.recent_accuracy
    if accuracy is None:
        accuracy = signals.accuracy

    response_time = signals.recent_response_time_ms
    if response_time is None:
        response_time = signals.average_response_time_ms

    evidence: dict[str, float] = {}
    weighted_score = 0.0
    total_weight = 0.0

    if accuracy is not None:
        evidence["accuracy"] = round(_accuracy_score(accuracy), 2)
        weighted_score += evidence["accuracy"] * 0.55
        total_weight += 0.55

    if response_time is not None:
        evidence["response_time"] = round(_response_time_score(response_time), 2)
        weighted_score += evidence["response_time"] * 0.25
        total_weight += 0.25

    if signals.saved_word_count > 0:
        evidence["saved_words"] = round(_saved_word_score(signals.saved_word_count), 2)
        weighted_score += evidence["saved_words"] * 0.20
        total_weight += 0.20

    # 데이터가 전혀 없거나 적을 때는 A2를 기준으로 삼아 난이도가 급변하지 않게 한다.
    baseline_score = 2.0  # A2
    observed_score = weighted_score / total_weight if total_weight else baseline_score
    confidence = _confidence(signals, accuracy is not None, response_time is not None)
    score = baseline_score + confidence * (observed_score - baseline_score)
    score = round(_clamp(score, 1.0, 5.0), 2)
    level = _pick_level(score)

    return LearnerProfile(
        level=level,
        tutor_difficulty=_DIFFICULTY_BY_LEVEL[level],
        score=score,
        confidence=confidence,
        evidence=evidence,
    )
