from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field, model_validator

from interview_api.workflow.schemas import ApiModel

MAX_OFFSET_MS = 24 * 60 * 60 * 1000


class CaptureState(ApiModel):
    camera_active: bool
    microphone_active: bool
    screen_active: bool
    display_surface: Literal["monitor", "window", "browser"] | None = None


class IntegrityStartRequest(CaptureState):
    client_session_id: str = Field(min_length=1, max_length=100, pattern=r"^[\w-]+$")


class IntegrityHeartbeatRequest(CaptureState):
    offset_ms: int = Field(ge=0, le=MAX_OFFSET_MS)


class IntegrityEvent(ApiModel):
    client_event_id: str = Field(min_length=1, max_length=100)
    type: Literal[
        "visibility_change",
        "focus_lost",
        "focus_gained",
        "capture_stopped",
        "capture_restored",
        "device_change",
        "display_info",
        "face_absent",
        "head_deviation",
        "gaze_deviation",
        "calibration",
        "heuristic_unavailable",
        "technical_error",
        "question_started",
        "answer_started",
        "answer_ended",
        "recording_gap",
        "capture_state",
    ]
    offset_ms: int = Field(ge=0, le=MAX_OFFSET_MS)
    duration_ms: int = Field(default=0, ge=0, le=MAX_OFFSET_MS)
    question_id: str | None = Field(default=None, max_length=36)
    payload: dict[str, Any] = Field(default_factory=dict)


class IntegrityEventsRequest(ApiModel):
    events: list[IntegrityEvent] = Field(min_length=1, max_length=200)


class IntegrityFinishRequest(ApiModel):
    offset_ms: int = Field(ge=0, le=MAX_OFFSET_MS)


class IntegritySessionResponse(ApiModel):
    id: str
    interview_id: str
    status: str
    next_question_blocked: bool
    elapsed_ms: int
    heartbeat_interval_ms: int = 10_000


class TimeRange(ApiModel):
    start_ms: int = Field(ge=0, le=MAX_OFFSET_MS)
    end_ms: int = Field(gt=0, le=MAX_OFFSET_MS)

    @model_validator(mode="after")
    def increasing(self):
        if self.end_ms <= self.start_ms:
            raise ValueError("endMs must be greater than startMs")
        return self


class EvidenceRef(TimeRange):
    media_id: str = Field(min_length=1, max_length=36)


class FindingDraft(TimeRange):
    question_id: str | None = Field(default=None, max_length=36)
    category: str = Field(min_length=1, max_length=100)
    source: Literal["browser", "local_heuristic", "vlm"]
    observation: str = Field(min_length=1, max_length=4000)
    reason: str = Field(min_length=1, max_length=4000)
    alternative_explanations: list[str] = Field(min_length=1, max_length=10)
    limitations: list[str] = Field(min_length=1, max_length=10)
    evidence_refs: list[EvidenceRef] = Field(min_length=1, max_length=20)
    observability: Literal["clear", "partial", "limited"] = "partial"


class IntegrityReviewRequest(ApiModel):
    decision: Literal["explained", "confirmed", "needs_clarification"]
    comment: str = Field(default="", max_length=5000)

    @model_validator(mode="after")
    def confirmation_requires_comment(self):
        self.comment = self.comment.strip()
        if self.decision == "confirmed" and not self.comment:
            raise ValueError("Для подтверждения нарушения обязателен комментарий.")
        return self


class IntegrityReviewResponse(ApiModel):
    decision: Literal["explained", "confirmed", "needs_clarification"]
    comment: str
    reviewed_at: datetime


class IntegrityFindingResponse(FindingDraft):
    id: str
    interview_id: str
    video_available: bool
    review: IntegrityReviewResponse | None = None


class RecordingCoverage(ApiModel):
    camera_ms: int = 0
    screen_ms: int = 0
    joint_ms: int = 0
    total_ms: int = 0


class AnalysisCoverage(ApiModel):
    analyzed_ms: int = 0
    total_ms: int = 0


class IntegritySummaryResponse(ApiModel):
    enabled: bool
    session: IntegritySessionResponse | None = None
    findings: list[IntegrityFindingResponse] = Field(default_factory=list)
    recording_coverage: RecordingCoverage = Field(default_factory=RecordingCoverage)
    analysis_coverage: AnalysisCoverage = Field(default_factory=AnalysisCoverage)
    cost_usd: float = 0
    cost_known: bool = True
    pending_jobs: int = 0
    failed_jobs: int = 0


class PlaybackSegment(TimeRange):
    media_id: str
    stream_id: str
    url: str
    media_offset_ms: int = 0


class TranscriptWord(TimeRange):
    text: str


class PlaybackTranscript(ApiModel):
    question_id: str
    text: str
    start_ms: int | None = None
    end_ms: int | None = None
    words: list[TranscriptWord] = Field(default_factory=list)


class PlaybackObservation(TimeRange):
    source: str
    text: str


class IntegrityPlaybackResponse(ApiModel):
    finding_id: str
    title: str
    episode: TimeRange
    context: TimeRange
    answer_range: TimeRange | None = None
    camera: list[PlaybackSegment]
    screen: list[PlaybackSegment]
    transcript: list[PlaybackTranscript]
    observations: list[PlaybackObservation]
    expires_at: datetime
