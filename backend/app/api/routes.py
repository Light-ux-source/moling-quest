"""REST API：会话创建 → 轮询 → 提交答案 → 结算 → 报告；章节地图与个人统计。"""

from __future__ import annotations

import logging
import re
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
    ChapterDetail,
    ChapterListResponse,
    HealthResponse,
    ProfilePayload,
    ProgressUpdate,
    QuestionPublic,
    ReportPayload,
    SessionCreate,
    SessionDetail,
    SettlementPayload,
    SourceItem,
    SubmitAnswers,
)
from ..services.chapters import build_chapter_detail, list_chapter_summaries
from ..services.grading import run_grading
from ..services.question_gen import generate_for_session
from ..services.settlement import build_settlement

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["learning"])

_rate: Dict[str, Deque[float]] = defaultdict(deque)
_WINDOW_SEC = 3600
_CLIENT_RE = re.compile(r"[^A-Za-z0-9_-]")
ALL_TYPES = list(TYPE_LABELS)


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


def _client_id(request: Request) -> str:
    """匿名设备标识；没有登录，但章节/错题/统计按设备隔离。"""
    raw = request.headers.get("x-client-id") or request.query_params.get("client_id") or "anonymous"
    cleaned = _CLIENT_RE.sub("", str(raw))[:64]
    return cleaned or "anonymous"


def _new_chapter_id() -> str:
    return f"c_{uuid.uuid4().hex[:12]}"


def _new_session_id() -> str:
    return f"s_{uuid.uuid4().hex[:12]}"


def _to_detail(session: Dict, questions: Optional[List[Dict]] = None, answered: int = 0) -> SessionDetail:
    public = [
        QuestionPublic(
            id=q["id"],
            seq=q["seq"],
            type=q["type"],
            title=q.get("title") or "",
            stem=q["stem"],
            options=q["options"],
            difficulty=q["difficulty"],
        )
        for q in (questions or [])
    ]
    return SessionDetail(
        id=session["id"],
        chapter_id=session.get("chapter_id"),
        parent_chapter_id=session.get("parent_chapter_id"),
        topic=session["topic"],
        level=session["level"],
        question_count=session["question_count"],
        types=session["requested_types"],
        kind=session.get("kind") or "standard",
        status=session["status"],
        stage=session.get("stage"),
        progress=session.get("progress", 0),
        current_seq=int(session.get("current_seq") or 1),
        error=session.get("error"),
        questions=public,
        sources=[SourceItem(**s) for s in (session.get("sources") or []) if isinstance(s, dict)],
        answered_count=answered,
        model=session.get("model"),
        created_at=session["created_at"],
        updated_at=session["updated_at"],
    )


def _create_chapter_for_session(
    *,
    chapter_id: str,
    session_id: str,
    client_id: str,
    topic: str,
    level: str,
    count: int,
    kind: str = "standard",
    parent_chapter_id: Optional[str] = None,
) -> None:
    db.create_chapter(
        {
            "id": chapter_id,
            "client_id": client_id,
            "session_id": session_id,
            "title": topic[:40],
            "topic": topic,
            "level": level,
            "question_count": count,
            "kind": kind,
            "parent_chapter_id": parent_chapter_id,
        }
    )


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(
        version=settings.app_version,
        mode=settings.mode,
        model=settings.deepseek_model if not settings.is_mock else "mock-deepseek-flash",
        web_search=settings.enable_web_search and not settings.is_mock,
    )


@router.post("/sessions", response_model=SessionDetail, status_code=202)
async def create_session(
    payload: SessionCreate, request: Request, background_tasks: BackgroundTasks
) -> SessionDetail:
    settings = get_settings()
    if _rate_limited(_client_ip(request), settings.rate_limit_per_hour):
        raise HTTPException(status_code=429, detail="请求过于频繁，请休息一会儿再试")

    client_id = _client_id(request)
    kind = payload.kind
    count = 3 if kind == "daily" else max(
        settings.min_question_count, min(payload.question_count, settings.max_question_count)
    )
    types = ALL_TYPES if kind == "daily" else (payload.types or ALL_TYPES)
    types = [t for t in types if t in TYPE_LABELS] or ALL_TYPES

    chapter_id = _new_chapter_id()
    session_id = _new_session_id()
    db.create_session(
        {
            "id": session_id,
            "client_id": client_id,
            "chapter_id": chapter_id,
            "topic": payload.topic,
            "level": payload.level,
            "requested_types": types,
            "question_count": count,
            "kind": kind,
            "status": "queued",
            "stage": "queued",
            "progress": 2,
            "current_seq": 1,
            "model": settings.deepseek_model if not settings.is_mock else "mock-deepseek-flash",
        }
    )
    _create_chapter_for_session(
        chapter_id=chapter_id,
        session_id=session_id,
        client_id=client_id,
        topic=payload.topic,
        level=payload.level,
        count=count,
        kind=kind,
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


@router.patch("/sessions/{session_id}/progress")
async def update_progress(session_id: str, payload: ProgressUpdate, request: Request) -> Dict:
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="学习会话不存在或已过期")
    if session["status"] != "ready":
        raise HTTPException(status_code=409, detail="题目尚未生成完成或已提交，无法更新进度")
    count = int(session.get("question_count") or 0)
    if payload.current_seq > count:
        raise HTTPException(status_code=422, detail=f"当前关序号不能超过 {count}")
    db.update_session(session_id, current_seq=payload.current_seq)
    return {"session_id": session_id, "current_seq": payload.current_seq}


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
        session_id,
        status="grading",
        stage="grading",
        progress=30,
        current_seq=len(questions),
        submitted_at=db.now_iso(),
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


@router.get("/sessions/{session_id}/settlement", response_model=SettlementPayload)
async def get_settlement(session_id: str) -> SettlementPayload:
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="学习会话不存在或已过期")
    if session["status"] != "completed":
        raise HTTPException(status_code=409, detail="本组题目尚未完成，暂时没有结算数据")
    report = db.get_report(session_id)
    if not report:
        raise HTTPException(status_code=409, detail="报告还在生成中，请稍候")
    settlement = report.get("settlement")
    if not settlement:
        previous_exp = sum(
            int(item.get("exp") or 0)
            for item in db.list_completed_sessions(session.get("client_id") or "anonymous")
            if item.get("id") != session_id
        )
        settlement = build_settlement(
            session, report.get("items") or [], previous_exp, int(report.get("duration_sec") or 0)
        )
    return SettlementPayload(**settlement)


@router.post("/sessions/{session_id}/retry", response_model=SessionDetail, status_code=202)
async def retry_session(
    session_id: str, background_tasks: BackgroundTasks
) -> SessionDetail:
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="学习会话不存在或已过期")
    if session["status"] != "failed":
        raise HTTPException(status_code=409, detail="只有生成失败的会话可以重新生成")

    db.delete_session_artifacts(session_id)
    db.update_session(
        session_id,
        status="queued",
        stage="queued",
        progress=2,
        error=None,
        current_seq=1,
        stars=0,
        exp=0,
        accuracy=0,
        combo=0,
        completed_at=None,
    )
    if session.get("chapter_id"):
        db.update_chapter(session["chapter_id"], stars=0, accuracy=0, exp=0, completed_at=None)
    background_tasks.add_task(generate_for_session, session_id)
    fresh = db.get_session(session_id) or session
    return _to_detail(fresh)


@router.get("/chapters", response_model=ChapterListResponse)
async def list_chapters(request: Request, limit: int = 10) -> ChapterListResponse:
    client_id = _client_id(request)
    items = list_chapter_summaries(client_id, max(1, min(limit, 50)))
    return ChapterListResponse(items=items)


@router.get("/chapters/{chapter_id}", response_model=ChapterDetail)
async def get_chapter(chapter_id: str) -> ChapterDetail:
    detail = build_chapter_detail(chapter_id)
    if not detail:
        raise HTTPException(status_code=404, detail="章节不存在或已过期")
    return ChapterDetail(**detail)


@router.post("/chapters/{chapter_id}/comprehensive", response_model=SessionDetail, status_code=202)
async def create_comprehensive(
    chapter_id: str, request: Request, background_tasks: BackgroundTasks
) -> SessionDetail:
    chapter = db.get_chapter(chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在或已过期")
    if chapter.get("kind") != "standard":
        raise HTTPException(status_code=409, detail="章末综合关只能基于标准章节生成")
    session = db.get_session(chapter["session_id"])
    if not session or session["status"] != "completed":
        raise HTTPException(status_code=409, detail="先完成本章 5 个节点，再来挑战章末综合")
    if db.get_comprehensive_chapter(chapter_id):
        raise HTTPException(status_code=409, detail="本章的章末综合已经生成过了")

    detail = build_chapter_detail(chapter_id)
    question_nodes = [n for n in (detail or {}).get("nodes", []) if n.get("kind") == "question"]
    if not question_nodes or any(int(n.get("stars") or 0) < 3 for n in question_nodes):
        raise HTTPException(status_code=409, detail="需要前 5 关全部满星才能解锁章末综合")

    settings = get_settings()
    client_id = chapter.get("client_id") or _client_id(request) or "anonymous"
    count = 3
    topic = f"{chapter.get('topic') or chapter.get('title') or '本章'} · 章末综合"
    new_chapter_id = _new_chapter_id()
    new_session_id = _new_session_id()
    db.create_session(
        {
            "id": new_session_id,
            "client_id": client_id,
            "chapter_id": new_chapter_id,
            "parent_chapter_id": chapter_id,
            "topic": topic,
            "level": chapter.get("level", "advanced"),
            "requested_types": ALL_TYPES,
            "question_count": count,
            "kind": "comprehensive",
            "status": "queued",
            "stage": "queued",
            "progress": 2,
            "current_seq": 1,
            "model": settings.deepseek_model if not settings.is_mock else "mock-deepseek-flash",
        }
    )
    _create_chapter_for_session(
        chapter_id=new_chapter_id,
        session_id=new_session_id,
        client_id=client_id,
        topic=topic,
        level=chapter.get("level", "advanced"),
        count=count,
        kind="comprehensive",
        parent_chapter_id=chapter_id,
    )
    background_tasks.add_task(generate_for_session, new_session_id)
    fresh = db.get_session(new_session_id) or {}
    return _to_detail(fresh)


@router.get("/profile", response_model=ProfilePayload)
async def get_profile(request: Request) -> ProfilePayload:
    from ..services.chapters import build_profile

    return ProfilePayload(**build_profile(_client_id(request)))


@router.get("/sessions")
async def recent_sessions(request: Request, limit: int = 10) -> Dict:
    return {"items": db.list_recent_sessions(limit, _client_id(request))}