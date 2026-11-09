"""REST API：会话创建 → 轮询 → 提交答案 → 获取报告。"""

from __future__ import annotations

import logging
import time
import uuid
from collections import defaultdict, deque
from typing import Deque, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from .. import db
from ..config import get_settings
from ..schemas import (
    LEVEL_LABELS,
    TYPE_LABELS,
    HealthResponse,
    QuestionPublic,
    ReportPayload,
    SessionCreate,
    SessionDetail,
    SourceItem,
    SubmitAnswers,
)
from ..services.grading import run_grading
from ..services.question_gen import generate_for_session

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["learning"])

_rate: Dict[str, Deque[float]] = defaultdict(deque)
_WINDOW_SEC = 3600


def _rate_limited(ip: str, limit: int) -> bool:
    now = time.time()
    bucket = _rate[ip]
    while bucket and now - bucket[0] > _WINDOW_SEC:
        bucket.popleft()
    if len(bucket) >= limit:
        return True
    bucket.append(now)
    return False


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(
        version=settings.app_version,
        mode=settings.mode,
        model=settings.deepseek_model if not settings.is_mock else "mock-deepseek-flash",
        web_search=settings.enable_web_search and not settings.is_mock,
    )


def _to_detail(session: Dict, questions: Optional[List[Dict]] = None, answered: int = 0) -> SessionDetail:
    public = [
        QuestionPublic(
            id=q["id"],
            seq=q["seq"],
            type=q["type"],
            stem=q["stem"],
            options=q["options"],
            difficulty=q["difficulty"],
        )
        for q in (questions or [])
    ]
    return SessionDetail(
        id=session["id"],
        topic=session["topic"],
        level=session["level"],
        question_count=session["question_count"],
        types=session["requested_types"],
        status=session["status"],
        stage=session.get("stage"),
        progress=session.get("progress", 0),
        error=session.get("error"),
        questions=public,
        sources=[SourceItem(**s) for s in (session.get("sources") or []) if isinstance(s, dict)],
        answered_count=answered,
        model=session.get("model"),
        created_at=session["created_at"],
        updated_at=session["updated_at"],
    )


@router.post("/sessions", response_model=SessionDetail, status_code=202)
async def create_session(
    payload: SessionCreate, request: Request, background_tasks: BackgroundTasks
) -> SessionDetail:
    settings = get_settings()
    if _rate_limited(_client_ip(request), settings.rate_limit_per_hour):
        raise HTTPException(status_code=429, detail="请求过于频繁，请休息一会儿再试")

    count = max(settings.min_question_count, min(payload.question_count, settings.max_question_count))
    types = payload.types or ["single_choice", "multiple_choice", "true_false", "short_answer"]
    types = [t for t in types if t in TYPE_LABELS] or list(TYPE_LABELS)

    session_id = f"s_{uuid.uuid4().hex[:12]}"
    db.create_session(
        {
            "id": session_id,
            "topic": payload.topic,
            "level": payload.level,
            "requested_types": types,
            "question_count": count,
            "status": "queued",
            "stage": "queued",
            "progress": 2,
            "model": settings.deepseek_model if not settings.is_mock else "mock-deepseek-flash",
        }
    )
    background_tasks.add_task(generate_for_session, session_id)
    session = db.get_session(session_id)
    return _to_detail(session or {})


@router.get("/sessions/{session_id}", response_model=SessionDetail)
async def get_session(session_id: str) -> SessionDetail:
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="学习会话不存在或已过期")

    questions: List[Dict] = []
    answered = 0
    if session["status"] in {"ready", "grading", "reporting", "completed"}:
        questions = db.list_questions(session_id)
        answered = len(db.list_answers(session_id)) if session["status"] != "ready" else 0
    return _to_detail(session, questions, answered)


@router.post("/sessions/{session_id}/answers", status_code=202)
async def submit_answers(
    session_id: str, payload: SubmitAnswers, background_tasks: BackgroundTasks
) -> Dict:
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="学习会话不存在或已过期")
    if session["status"] in {"grading", "reporting"}:
        raise HTTPException(status_code=409, detail="答案已提交，正在批改中")
    if session["status"] == "completed":
        raise HTTPException(status_code=409, detail="本组题目已提交，请开始新的一组")
    if session["status"] != "ready":
        raise HTTPException(status_code=409, detail="题目还在生成中，请稍候")

    questions = db.list_questions(session_id)
    if not questions:
        raise HTTPException(status_code=409, detail="题目数据异常，请重新开始")

    question_map = {q["id"]: q for q in questions}
    provided = {a.question_id: a.answer for a in payload.answers}
    unknown = [qid for qid in provided if qid not in question_map]
    if unknown:
        raise HTTPException(status_code=400, detail=f"存在无效题目 ID：{unknown[:3]}")

    raw_answers = []
    for q in questions:
        answer = provided.get(q["id"], "")
        raw_answers.append(
            {
                "id": f"ans_{q['id']}",
                "question_id": q["id"],
                "seq": q["seq"],
                "user_answer": answer,
                "is_correct": False,
                "score": 0.0,
                "feedback": "待批改",
            }
        )
    db.upsert_answers(session_id, raw_answers)
    db.update_session(
        session_id, status="grading", stage="grading", progress=30, submitted_at=db.now_iso()
    )
    background_tasks.add_task(run_grading, session_id)
    return {"session_id": session_id, "status": "grading", "progress": 30}


@router.get("/sessions/{session_id}/report", response_model=ReportPayload)
async def get_report(session_id: str) -> ReportPayload:
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="学习会话不存在或已过期")
    if session["status"] == "failed":
        raise HTTPException(status_code=409, detail=session.get("error") or "生成失败，请重试")
    report = db.get_report(session_id)
    if not report:
        raise HTTPException(status_code=409, detail="报告还在生成中，请稍候")
    return ReportPayload(**report)


@router.get("/sessions")
async def recent_sessions(limit: int = 10) -> Dict:
    return {"items": db.list_recent_sessions(limit)}