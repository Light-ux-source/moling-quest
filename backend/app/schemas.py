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
    # 多数据源：web = 联网检索，kb = 用户知识库片段
    kind: str = "web"
    ref: str = ""
    kb_id: str = ""
    doc_id: str = ""
    locator: str = ""


class SessionCreate(BaseModel):
    topic: str = Field(..., min_length=2, max_length=200, description="想学习的知识点")
    level: Level = "basic"
    question_count: int = Field(default=5, ge=3, le=15)
    types: Optional[List[QuestionType]] = None
    kind: Literal["standard", "daily"] = "standard"
    kb_ids: List[str] = Field(default_factory=list, description="选中的知识库 ID，最多 3 个")
    # model: 保持现状；kb_only: 只读知识库；hybrid: 知识库优先 + 联网补充
    source_mode: Literal["model", "kb_only", "hybrid"] = "model"

    @field_validator("topic")
    @classmethod
    def _clean_topic(cls, v: str) -> str:
        cleaned = " ".join(v.replace("\u3000", " ").split())
        if len(cleaned) < 2:
            raise ValueError("学习主题至少需要 2 个字符")
        return cleaned

    @field_validator("kb_ids")
    @classmethod
    def _clean_kb_ids(cls, values: List[str]) -> List[str]:
        cleaned: List[str] = []
        for value in values or []:
            item = str(value or "").strip()
            if not item:
                continue
            if not item.startswith("kb_") or len(item) > 64:
                raise ValueError("知识库 ID 格式不正确")
            if item not in cleaned:
                cleaned.append(item)
        if len(cleaned) > 3:
            raise ValueError("一次最多选择 3 个知识库")
        return cleaned


class RetrievalInfo(BaseModel):
    mode: str = "model"
    rounds: int = 0
    queries: List[str] = Field(default_factory=list)
    chunks: int = 0
    web_sources: int = 0
    fallback: bool = False


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
    kb_ids: List[str] = Field(default_factory=list)
    source_mode: str = "model"
    retrieval: Optional[RetrievalInfo] = None
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
    search_provider: str = "none"
    database: str = "mysql"
    auth: str = "wechat"
    wechat_login: bool = False
    dev_login: bool = False
    embedding: str = "none"
    embedding_model: str = ""
    vector_store: str = "none"
    rag: bool = False
    kb_enabled: bool = True


class KbLimits(BaseModel):
    max_kbs: int = 5
    used_kbs: int = 0
    remaining_kbs: int = 5
    max_docs_per_kb: int = 30
    max_file_bytes: int = 20 * 1024 * 1024
    max_text_chars: int = 200_000
    max_session_kbs: int = 3
    can_create: bool = True


class KbSummary(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    doc_count: int = 0
    chunk_count: int = 0
    char_count: int = 0
    status: str = "active"
    is_guest: bool = True
    created_at: str
    updated_at: str


class KbDocumentPublic(BaseModel):
    id: str
    kb_id: str
    kind: str = "file"
    title: str
    source_url: Optional[str] = None
    filename: Optional[str] = None
    mime: Optional[str] = None
    size_bytes: int = 0
    status: str = "queued"
    progress: int = 0
    error: Optional[str] = None
    char_count: int = 0
    chunk_count: int = 0
    created_at: str
    updated_at: str
    completed_at: Optional[str] = None


class KbDocumentListResponse(BaseModel):
    items: List[KbDocumentPublic] = Field(default_factory=list)


class KbDetail(KbSummary):
    documents: List[KbDocumentPublic] = Field(default_factory=list)
    limits: KbLimits = Field(default_factory=KbLimits)


class KbListResponse(BaseModel):
    items: List[KbSummary] = Field(default_factory=list)
    limits: KbLimits = Field(default_factory=KbLimits)


class KbCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=40)
    description: Optional[str] = Field(default=None, max_length=120)

    @field_validator("name")
    @classmethod
    def _clean_name(cls, v: str) -> str:
        cleaned = " ".join(v.replace("\u3000", " ").split())
        if not cleaned:
            raise ValueError("资料库名称不能为空")
        return cleaned


class KbUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=40)
    description: Optional[str] = Field(default=None, max_length=120)


class KbUrlCreate(BaseModel):
    url: str = Field(..., min_length=8, max_length=2048)
    title: Optional[str] = Field(default=None, max_length=200)


class KbTextCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    text: str = Field(..., min_length=1, max_length=200_000)


class KbSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500)
    top_k: int = Field(default=5, ge=1, le=20)


class KbSearchHit(BaseModel):
    chunk_id: str
    doc_id: str
    doc_title: str = ""
    locator: str = ""
    content: str = ""
    score: float = 0.0


class KbSearchResponse(BaseModel):
    query: str
    items: List[KbSearchHit] = Field(default_factory=list)

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
    kb_ids: List[str] = Field(default_factory=list)
    source_mode: str = "model"
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
    kb_count: int = 0
    source_mode: str = "model"
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
    limit: int = 3
    remaining: int = 3
    period: str = "day"
    source: str = "daily"
    reset_at: Optional[str] = None
    is_guest: bool = False


class WeeklyPoint(BaseModel):
    date: str
    exp: int = 0


class UserPublic(BaseModel):
    id: str
    nickname: str = "旅人"
    avatar_url: Optional[str] = None
    wechat_bound: bool = False
    is_guest: bool = False


class ProfilePayload(BaseModel):
    client_id: str
    user_id: Optional[str] = None
    nickname: str = "旅人"
    avatar_url: Optional[str] = None
    is_guest: bool = True
    is_logged_in: bool = False
    wechat_bound: bool = False
    chapters_completed: int = 0
    total_stars: int = 0
    total_exp: int = 0
    points: int = 0
    leaf_count: int = 0
    streak_days: int = 0
    rank: RankInfo
    quota: QuotaInfo
    weekly: List[WeeklyPoint] = Field(default_factory=list)
    recent_chapters: List[ChapterSummary] = Field(default_factory=list)


class WechatLoginRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=512)
    nickname: Optional[str] = Field(default=None, max_length=16)
    avatar_url: Optional[str] = Field(default=None, max_length=512)


class DevLoginRequest(BaseModel):
    nickname: Optional[str] = Field(default=None, max_length=16)


class AuthResponse(BaseModel):
    token: str
    expires_at: str
    user: UserPublic
    migrated: Dict[str, int] = Field(default_factory=dict)
    is_new: bool = False


class MeResponse(BaseModel):
    authenticated: bool = False
    user: Optional[UserPublic] = None


class ProfileUpdate(BaseModel):
    nickname: Optional[str] = Field(default=None, min_length=1, max_length=16)
    avatar_url: Optional[str] = Field(default=None, max_length=512)

    @field_validator("nickname")
    @classmethod
    def _clean_nickname(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        cleaned = " ".join(v.replace("\u3000", " ").split())
        if not cleaned:
            raise ValueError("昵称不能为空")
        return cleaned


class RecordItem(BaseModel):
    id: str
    chapter_id: Optional[str] = None
    topic: str
    level: str
    level_label: str = ""
    kind: str = "standard"
    status: str
    status_label: str = ""
    question_count: int = 0
    stars: int = 0
    accuracy: float = 0.0
    points: int = 0
    created_at: str
    completed_at: Optional[str] = None


class RecordListResponse(BaseModel):
    items: List[RecordItem] = Field(default_factory=list)
    total: int = 0
    has_more: bool = False


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
