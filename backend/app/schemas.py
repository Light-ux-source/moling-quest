"""API 与领域数据模型（Pydantic v2）。"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator

Level = Literal["basic", "advanced", "challenge"]
QuestionType = Literal["single_choice", "multiple_choice", "true_false", "short_answer"]
SessionStatus = Literal[
    "queued", "searching", "digesting", "generating", "ready",
    "grading", "reporting", "completed", "failed",
]

TYPE_LABELS: Dict[str, str] = {
    "single_choice": "单选题",
    "multiple_choice": "多选题",
    "true_false": "判断题",
    "short_answer": "简答题",
}

LEVEL_LABELS: Dict[str, str] = {
    "basic": "入门",
    "advanced": "进阶",
    "challenge": "挑战",
}


class Option(BaseModel):
    key: str
    text: str

    @field_validator("key")
    @classmethod
    def _upper_key(cls, v: str) -> str:
        return v.strip().upper()


class QuestionFull(BaseModel):
    """内部完整题目：含答案与解析，绝不下发给答题阶段的客户端。"""

    model_config = ConfigDict(extra="ignore")

    id: str
    seq: int
    type: QuestionType
    title: str = ""
    knowledge_point: str = ""
    stem: str
    options: List[Option] = Field(default_factory=list)
    correct_answer: Union[str, List[str]]
    explanation: str = ""
    difficulty: str = "medium"
    rubric: List[str] = Field(default_factory=list)
    source_refs: List[str] = Field(default_factory=list)


class QuestionPublic(BaseModel):
    """答题阶段下发给客户端的题目，隐去答案与解析。"""

    id: str
    seq: int
    type: QuestionType
    title: str = ""
    stem: str
    options: List[Option] = Field(default_factory=list)
    difficulty: str = "medium"


class SourceItem(BaseModel):
    title: str = ""
    url: str = ""
    site_name: Optional[str] = None
    summary: str = ""


class SessionCreate(BaseModel):
    topic: str = Field(..., min_length=2, max_length=200, description="想学习的知识点")
    level: Level = "basic"
    question_count: int = Field(default=5, ge=3, le=10)
    types: Optional[List[QuestionType]] = None
    kind: Literal["standard", "daily"] = "standard"

    @field_validator("topic")
    @classmethod
    def _clean_topic(cls, v: str) -> str:
        cleaned = " ".join(v.replace("\u3000", " ").split())
        if len(cleaned) < 2:
            raise ValueError("学习主题至少需要 2 个字符")
        return cleaned


class SessionDetail(BaseModel):
    id: str
    chapter_id: Optional[str] = None
    parent_chapter_id: Optional[str] = None
    topic: str
    level: Level
    question_count: int
    types: List[str]
    kind: str = "standard"
    status: SessionStatus
    stage: Optional[str] = None
    progress: int = 0
    current_seq: int = 1
    error: Optional[str] = None
    questions: List[QuestionPublic] = Field(default_factory=list)
    sources: List[SourceItem] = Field(default_factory=list)
    answered_count: int = 0
    model: Optional[str] = None
    created_at: str
    updated_at: str


class AnswerItem(BaseModel):
    question_id: str
    answer: Union[str, List[str]] = ""


class SubmitAnswers(BaseModel):
    answers: List[AnswerItem] = Field(..., min_length=1)


class AnswerResult(BaseModel):
    question_id: str
    seq: int
    type: str
    type_label: str
    stem: str
    options: List[Option] = Field(default_factory=list)
    user_answer: Union[str, List[str], None] = None
    correct_answer: Union[str, List[str], None] = None
    is_correct: bool = False
    score: float = 0.0
    feedback: str = ""
    explanation: str = ""
    rubric: List[str] = Field(default_factory=list)
    source_refs: List[str] = Field(default_factory=list)


class ReportPayload(BaseModel):
    session_id: str
    topic: str
    level: str
    level_label: str
    score: int
    total: int
    correct: int
    accuracy: float
    summary: str
    level_tag: str = ""
    by_type: Dict[str, Dict[str, int]] = Field(default_factory=dict)
    items: List[AnswerResult] = Field(default_factory=list)
    knowledge_gaps: List[str] = Field(default_factory=list)
    next_steps: List[str] = Field(default_factory=list)
    suggested_topics: List[str] = Field(default_factory=list)
    sources: List[SourceItem] = Field(default_factory=list)
    duration_sec: int = 0
    generated_at: str = ""
    model: Optional[str] = None
    usage: Dict[str, Any] = Field(default_factory=dict)
    settlement: Optional[Dict[str, Any]] = None


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str
    mode: str
    model: str
    web_search: bool

class ProgressUpdate(BaseModel):
    current_seq: int = Field(..., ge=1, le=50)


class ChapterNode(BaseModel):
    seq: int
    title: str
    kind: str = "question"
    status: str
    stars: int = 0
    score: float = 0.0
    is_correct: bool = False
    question_id: Optional[str] = None
    chapter_id: Optional[str] = None
    session_id: Optional[str] = None


class ChapterProgress(BaseModel):
    done: int = 0
    total: int = 0


class ChapterDetail(BaseModel):
    id: str
    session_id: str
    parent_chapter_id: Optional[str] = None
    title: str
    topic: str
    level: str
    question_count: int
    kind: str = "standard"
    status: str
    error: Optional[str] = None
    stars: int = 0
    accuracy: float = 0.0
    exp: int = 0
    progress: ChapterProgress
    current_node: int = 1
    nodes: List[ChapterNode] = Field(default_factory=list)
    comprehensive: Optional[ChapterNode] = None
    sources: List[SourceItem] = Field(default_factory=list)
    created_at: str
    completed_at: Optional[str] = None


class ChapterSummary(BaseModel):
    id: str
    session_id: str
    title: str
    topic: str
    level: str
    question_count: int = 5
    kind: str = "standard"
    status: Optional[str] = None
    stars: int = 0
    accuracy: float = 0.0
    exp: int = 0
    progress: ChapterProgress
    next_title: str = ""
    created_at: str
    completed_at: Optional[str] = None


class ChapterListResponse(BaseModel):
    items: List[ChapterSummary] = Field(default_factory=list)


class RankInfo(BaseModel):
    key: str
    label: str
    exp: int
    next_key: Optional[str] = None
    next_label: Optional[str] = None
    exp_to_next: int = 0
    progress_pct: int = 0


class QuotaInfo(BaseModel):
    used: int = 0
    limit: int = 10
    remaining: int = 10
    period: str = "month"


class WeeklyPoint(BaseModel):
    date: str
    exp: int = 0


class ProfilePayload(BaseModel):
    client_id: str
    nickname: str = "旅人"
    chapters_completed: int = 0
    total_stars: int = 0
    total_exp: int = 0
    leaf_count: int = 0
    streak_days: int = 0
    rank: RankInfo
    quota: QuotaInfo
    weekly: List[WeeklyPoint] = Field(default_factory=list)
    recent_chapters: List[ChapterSummary] = Field(default_factory=list)


class SettlementPayload(BaseModel):
    session_id: str
    chapter_id: Optional[str] = None
    stars: int
    accuracy: float
    correct: int
    total: int
    exp: int
    combo: int
    wrong_count: int
    duration_sec: int = 0
    rank_before: RankInfo
    rank_after: RankInfo
    level_up: bool = False
    exp_to_next: int = 0
