"""REST API：账号/登录、会话、章节、记录、个人中心与配额。"""

from __future__ import annotations

import hashlib
import logging
import re
import time
import uuid
from collections import defaultdict, deque
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Tuple

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, Request, Response, UploadFile

from .. import db
from ..config import get_settings
from ..schemas import (
    LEVEL_LABELS,
    TYPE_LABELS,
    AuthResponse,
    ChapterDetail,
    ChapterListResponse,
    DevLoginRequest,
    HealthResponse,
    MeResponse,
    ProfilePayload,
    ProfileUpdate,
    ProgressUpdate,
    QuestionPublic,
    RecordItem,
    RecordListResponse,
    ReportPayload,
    SessionCreate,
    SessionDetail,
    SettingsUpdate,
    SettlementPayload,
    SourceItem,
    SubmitAnswers,
    UserSettings,
    WechatLoginRequest,
)
from ..services import auth as auth_service
from ..services import quota
from ..services.chapters import build_chapter_detail, build_profile, list_chapter_summaries
from ..services.grading import run_grading
from ..services.question_gen import generate_for_session
from ..services.settlement import build_settlement

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["learning"])

_rate: Dict[str, Deque[float]] = defaultdict(deque)
_login_rate: Dict[str, Deque[float]] = defaultdict(deque)
_WINDOW_SEC = 3600
_CLIENT_RE = re.compile(r"[^A-Za-z0-9_-]")
ALL_TYPES = list(TYPE_LABELS)

RECORD_STATUS_LABELS = {
    "queued": "生成中",
    "searching": "生成中",
    "digesting": "生成中",
    "generating": "生成中",
    "ready": "待答题",
    "grading": "批改中",
    "reporting": "批改中",
    "completed": "已完成",
    "failed": "生成失败",
}


def _rate_limited(bucket: Dict[str, Deque[float]], key: str, limit: int) -> bool:
    now = time.time()
    queue = bucket[key]
    while queue and now - queue[0] > _WINDOW_SEC:
        queue.popleft()
    if len(queue) >= limit:
        return True
    queue.append(now)
    return False


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _ip_hash(request: Request) -> str:
    return hashlib.sha256(_client_ip(request).encode("utf-8")).hexdigest()[:32]


def _client_id(request: Request) -> str:
    """匿名设备标识；登录后仍用它做游客数据迁移。"""
    raw = request.headers.get("x-client-id") or request.query_params.get("client_id") or "anonymous"
    cleaned = _CLIENT_RE.sub("", str(raw))[:64]
    return cleaned or "anonymous"


def _bearer(request: Request) -> Optional[str]:
    header = request.headers.get("authorization") or ""
    if not header:
        return None
    parts = header.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1].strip():
        raise HTTPException(status_code=401, detail="登录凭证格式不正确，请重新登录")
    return parts[1].strip()


def _current_user(request: Request) -> Optional[Dict[str, Any]]:
    token = _bearer(request)
    if not token:
        return None
    try:
        return auth_service.authenticate_token(token)
    except auth_service.AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


def _auth(request: Request) -> Tuple[Optional[Dict[str, Any]], str]:
    return _current_user(request), _client_id(request)


def _require_user(request: Request) -> Dict[str, Any]:
    user = _current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="请先登录")
    return user


def _assert_session_access(
    session: Dict[str, Any], user: Optional[Dict[str, Any]], client_id: str
) -> None:
    owner = session.get("user_id")
    if owner:
        if not user or user.get("id") != owner:
            raise HTTPException(status_code=404, detail="学习会话不存在或已过期")
        return
    if session.get("client_id") != client_id:
        raise HTTPException(status_code=404, detail="学习会话不存在或已过期")


def _assert_chapter_access(
    chapter: Dict[str, Any], user: Optional[Dict[str, Any]], client_id: str
) -> None:
    owner = chapter.get("user_id")
    if owner:
        if not user or user.get("id") != owner:
            raise HTTPException(status_code=404, detail="章节不存在或已过期")
        return
    if chapter.get("client_id") != client_id:
        raise HTTPException(status_code=404, detail="章节不存在或已过期")


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
    user_id: Optional[str],
    topic: str,
    level: str,
    count: int,
    kind: str = "standard",
    parent_chapter_id: Optional[str] = None,
) -> None:
    db.create_chapter(
        {
            "id": chapter_id,
            "user_id": user_id,
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


def _create_session_with_quota(
    *,
    user: Optional[Dict[str, Any]],
    client_id: str,
    request: Request,
    topic: str,
    level: str,
    count: int,
    types: List[str],
    kind: str,
    parent_chapter_id: Optional[str] = None,
) -> Tuple[str, str]:
    """统一处理配额校验、游客试用消费与会话/章节创建。"""
    settings = get_settings()
    quota.ensure_can_create(user, client_id)
    session_id = _new_session_id()
    chapter_id = _new_chapter_id()
    is_guest = user is None
    consume_trial = is_guest and settings.quota_enforced
    if consume_trial:
        if not db.consume_guest_trial(client_id, session_id, _ip_hash(request)):
            raise HTTPException(status_code=429, detail="已体验 1 组。登录后可继续造关，学习记录也会跟着账号走。")
    try:
        db.create_session(
            {
                "id": session_id,
                "user_id": user["id"] if user else None,
                "client_id": client_id,
                "chapter_id": chapter_id,
                "parent_chapter_id": parent_chapter_id,
                "topic": topic,
                "level": level,
                "requested_types": types,
                "question_count": count,
                "kind": kind,
                "status": "queued",
                "stage": "queued",
                "progress": 2,
                "current_seq": 1,
                "guest_trial": consume_trial,
                "model": settings.deepseek_model if not settings.is_mock else "mock-deepseek-flash",
            }
        )
        _create_chapter_for_session(
            chapter_id=chapter_id,
            session_id=session_id,
            client_id=client_id,
            user_id=user["id"] if user else None,
            topic=topic,
            level=level,
            count=count,
            kind=kind,
            parent_chapter_id=parent_chapter_id,
        )
    except Exception:
        if consume_trial:
            db.refund_guest_trial(client_id, session_id)
        raise
    return session_id, chapter_id


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(
        version=settings.app_version,
        mode=settings.mode,
        model=settings.deepseek_model if not settings.is_mock else "mock-deepseek-flash",
        web_search=settings.enable_web_search and not settings.is_mock,
        database="mysql",
        auth="wechat",
        wechat_login=settings.wechat_login_configured,
        dev_login=settings.dev_login_allowed,
    )


# --------------------------------------------------------------------------- #
# auth
# --------------------------------------------------------------------------- #
@router.post("/auth/wechat", response_model=AuthResponse)
async def auth_wechat(payload: WechatLoginRequest, request: Request) -> AuthResponse:
    settings = get_settings()
    if _rate_limited(_login_rate, _client_ip(request), settings.login_rate_limit_per_hour):
        raise HTTPException(status_code=429, detail="登录尝试太频繁，请稍后再试")
    try:
        result = await auth_service.login_with_wechat(
            code=payload.code,
            client_id=_client_id(request),
            nickname=payload.nickname,
            avatar_url=payload.avatar_url,
        )
    except auth_service.AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return AuthResponse(**result)


@router.post("/auth/dev", response_model=AuthResponse)
async def auth_dev(payload: DevLoginRequest, request: Request) -> AuthResponse:
    settings = get_settings()
    if _rate_limited(_login_rate, _client_ip(request), settings.login_rate_limit_per_hour):
        raise HTTPException(status_code=429, detail="登录尝试太频繁，请稍后再试")
    try:
        result = auth_service.login_dev(_client_id(request), payload.nickname)
    except auth_service.AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return AuthResponse(**result)


@router.get("/auth/me", response_model=MeResponse)
async def auth_me(request: Request) -> MeResponse:
    token = _bearer(request)
    if not token:
        return MeResponse(authenticated=False)
    try:
        user = auth_service.authenticate_token(token)
    except auth_service.AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return MeResponse(authenticated=True, user=auth_service.public_user(user))


@router.post("/auth/logout")
async def auth_logout(request: Request) -> Dict[str, Any]:
    token = _bearer(request)
    if token:
        auth_service.logout(token)
    return {"ok": True}


# --------------------------------------------------------------------------- #
# sessions
# --------------------------------------------------------------------------- #
@router.post("/sessions", response_model=SessionDetail, status_code=202)
async def create_session(
    payload: SessionCreate, request: Request, background_tasks: BackgroundTasks
) -> SessionDetail:
    settings = get_settings()
    if _rate_limited(_rate, _client_ip(request), settings.rate_limit_per_hour):
        raise HTTPException(status_code=429, detail="请求过于频繁，请休息一会儿再试")

    user, client_id = _auth(request)
    kind = payload.kind
    count = 3 if kind == "daily" else max(
        settings.min_question_count, min(payload.question_count, settings.max_question_count)
    )
    types = ALL_TYPES if kind == "daily" else (payload.types or ALL_TYPES)
    types = [t for t in types if t in TYPE_LABELS] or ALL_TYPES

    try:
        session_id, chapter_id = _create_session_with_quota(
            user=user,
            client_id=client_id,
            request=request,
            topic=payload.topic,
            level=payload.level,
            count=count,
            types=types,
            kind=kind,
        )
    except quota.QuotaError as exc:
        raise HTTPException(status_code=429, detail=exc.message) from exc

    background_tasks.add_task(generate_for_session, session_id)
    session = db.get_session(session_id)
    return _to_detail(session or {})


@router.get("/sessions/{session_id}", response_model=SessionDetail)
async def get_session(session_id: str, request: Request) -> SessionDetail:
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="学习会话不存在或已过期")
    user, client_id = _auth(request)
    _assert_session_access(session, user, client_id)

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
    user, client_id = _auth(request)
    _assert_session_access(session, user, client_id)
    if session["status"] != "ready":
        raise HTTPException(status_code=409, detail="题目尚未生成完成或已提交，无法更新进度")
    count = int(session.get("question_count") or 0)
    if payload.current_seq > count:
        raise HTTPException(status_code=422, detail=f"当前关序号不能超过 {count}")
    db.update_session(session_id, current_seq=payload.current_seq)
    return {"session_id": session_id, "current_seq": payload.current_seq}


@router.post("/sessions/{session_id}/answers", status_code=202)
async def submit_answers(
    session_id: str, payload: SubmitAnswers, request: Request, background_tasks: BackgroundTasks
) -> Dict:
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="学习会话不存在或已过期")
    user, client_id = _auth(request)
    _assert_session_access(session, user, client_id)
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
async def get_report(session_id: str, request: Request) -> ReportPayload:
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="学习会话不存在或已过期")
    user, client_id = _auth(request)
    _assert_session_access(session, user, client_id)
    if session["status"] == "failed":
        raise HTTPException(status_code=409, detail=session.get("error") or "生成失败，请重试")
    report = db.get_report(session_id)
    if not report:
        raise HTTPException(status_code=409, detail="报告还在生成中，请稍候")
    return ReportPayload(**report)


@router.get("/sessions/{session_id}/settlement", response_model=SettlementPayload)
async def get_settlement(session_id: str, request: Request) -> SettlementPayload:
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="学习会话不存在或已过期")
    user, client_id = _auth(request)
    _assert_session_access(session, user, client_id)
    if session["status"] != "completed":
        raise HTTPException(status_code=409, detail="本组题目尚未完成，暂时没有结算数据")
    report = db.get_report(session_id)
    if not report:
        raise HTTPException(status_code=409, detail="报告还在生成中，请稍候")
    settlement = report.get("settlement")
    if not settlement:
        previous_exp = sum(
            int(item.get("exp") or 0)
            for item in db.list_completed_sessions(
                session.get("client_id") or "anonymous", user_id=session.get("user_id")
            )
            if item.get("id") != session_id
        )
        settlement = build_settlement(
            session, report.get("items") or [], previous_exp, int(report.get("duration_sec") or 0)
        )
    return SettlementPayload(**settlement)


@router.post("/sessions/{session_id}/retry", response_model=SessionDetail, status_code=202)
async def retry_session(
    session_id: str, request: Request, background_tasks: BackgroundTasks
) -> SessionDetail:
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="学习会话不存在或已过期")
    user, client_id = _auth(request)
    _assert_session_access(session, user, client_id)
    if session["status"] != "failed":
        raise HTTPException(status_code=409, detail="只有生成失败的会话可以重新生成")

    settings = get_settings()
    # 失败重试重新计入额度；游客失败已退回试用，重试时重新占用。
    if user is None and session.get("guest_trial") and settings.quota_enforced:
        if not db.consume_guest_trial(client_id, session_id, _ip_hash(request)):
            raise HTTPException(status_code=429, detail="试用额度已被占用，请登录后继续。")
    quota.reset_retry(session_id)
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


@router.post("/sessions/{session_id}/regenerate", response_model=SessionDetail, status_code=202)
async def regenerate_session(
    session_id: str, request: Request, background_tasks: BackgroundTasks
) -> SessionDetail:
    """预览页“重新生成”：复用原会话/章节，不额外消耗额度。"""
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="学习会话不存在或已过期")
    user, client_id = _auth(request)
    _assert_session_access(session, user, client_id)
    if session["status"] != "ready":
        raise HTTPException(status_code=409, detail="只有待答题（生成完成、未提交）的会话可以重新生成")

    db.delete_session_artifacts(session_id)
    db.update_session(
        session_id,
        status="queued",
        stage="queued",
        progress=2,
        error=None,
        knowledge_brief=None,
        sources=None,
        current_seq=1,
        submitted_at=None,
        completed_at=None,
    )
    if session.get("chapter_id"):
        db.update_chapter(session["chapter_id"], stars=0, accuracy=0, exp=0, completed_at=None)

    background_tasks.add_task(generate_for_session, session_id)
    fresh = db.get_session(session_id) or session
    return _to_detail(fresh)


@router.get("/sessions")
async def recent_sessions(request: Request, limit: int = 10) -> Dict:
    user, client_id = _auth(request)
    user_id = user["id"] if user else None
    return {
        "items": db.list_recent_sessions(
            max(1, min(limit, 50)), client_id=client_id, user_id=user_id
        )
    }


# --------------------------------------------------------------------------- #
# chapters
# --------------------------------------------------------------------------- #
@router.get("/chapters", response_model=ChapterListResponse)
async def list_chapters(request: Request, limit: int = 10) -> ChapterListResponse:
    user, client_id = _auth(request)
    user_id = user["id"] if user else None
    items = list_chapter_summaries(client_id, max(1, min(limit, 50)), user_id=user_id)
    return ChapterListResponse(items=items)


@router.get("/chapters/{chapter_id}", response_model=ChapterDetail)
async def get_chapter(chapter_id: str, request: Request) -> ChapterDetail:
    chapter = db.get_chapter(chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在或已过期")
    user, client_id = _auth(request)
    _assert_chapter_access(chapter, user, client_id)
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
    user, client_id = _auth(request)
    _assert_chapter_access(chapter, user, client_id)
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

    count = 3
    topic = f"{chapter.get('topic') or chapter.get('title') or '本章'} · 章末综合"
    try:
        new_session_id, _ = _create_session_with_quota(
            user=user,
            client_id=client_id,
            request=request,
            topic=topic,
            level=chapter.get("level", "advanced"),
            count=count,
            types=ALL_TYPES,
            kind="comprehensive",
            parent_chapter_id=chapter_id,
        )
    except quota.QuotaError as exc:
        raise HTTPException(status_code=429, detail=exc.message) from exc
    background_tasks.add_task(generate_for_session, new_session_id)
    fresh = db.get_session(new_session_id) or {}
    return _to_detail(fresh)


# --------------------------------------------------------------------------- #
# profile / records / settings
# --------------------------------------------------------------------------- #
@router.get("/profile", response_model=ProfilePayload)
async def get_profile(request: Request) -> ProfilePayload:
    user, client_id = _auth(request)
    return ProfilePayload(**build_profile(client_id, user))


@router.patch("/profile", response_model=ProfilePayload)
async def update_profile(payload: ProfileUpdate, request: Request) -> ProfilePayload:
    user = _require_user(request)
    fields: Dict[str, Any] = {}
    if payload.nickname is not None:
        fields["nickname"] = payload.nickname
    if payload.avatar_url is not None:
        safe = payload.avatar_url.strip()
        if not (safe.startswith("/media/") or safe.startswith("http://") or safe.startswith("https://")):
            raise HTTPException(status_code=422, detail="头像地址不合法")
        fields["avatar_url"] = safe[:512]
    if not fields:
        raise HTTPException(status_code=400, detail="没有可更新的资料")
    db.update_user(user["id"], **fields)
    fresh = db.get_user(user["id"]) or user
    return ProfilePayload(**build_profile(_client_id(request), fresh))


@router.post("/profile/avatar")
async def upload_avatar(request: Request, file: UploadFile = File(...)) -> Dict[str, Any]:
    user = _require_user(request)
    settings = get_settings()
    content_type = (file.content_type or "").lower()
    ext_map = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
    if content_type not in ext_map:
        raise HTTPException(status_code=422, detail="头像仅支持 JPG / PNG / WebP")
    data = await file.read(settings.avatar_max_bytes + 1)
    if len(data) > settings.avatar_max_bytes:
        raise HTTPException(status_code=422, detail="头像不能超过 2MB")
    if not data:
        raise HTTPException(status_code=422, detail="头像文件为空")
    directory = Path(settings.avatar_upload_dir)
    directory.mkdir(parents=True, exist_ok=True)
    filename = f"{user['id']}_{uuid.uuid4().hex[:10]}.{ext_map[content_type]}"
    (directory / filename).write_bytes(data)
    url = f"/media/avatars/{filename}"
    db.update_user(user["id"], avatar_url=url)
    return {"avatar_url": url}


@router.get("/profile/settings", response_model=UserSettings)
async def get_settings_payload(request: Request) -> UserSettings:
    user = _require_user(request)
    return UserSettings(**db.get_user_settings(user["id"]))


@router.patch("/profile/settings", response_model=UserSettings)
async def update_settings_payload(payload: SettingsUpdate, request: Request) -> UserSettings:
    user = _require_user(request)
    data = db.upsert_user_settings(user["id"], reminder_enabled=payload.reminder_enabled)
    return UserSettings(**data)


@router.delete("/profile", status_code=204)
async def delete_profile(request: Request) -> Response:
    user = _require_user(request)
    db.anonymize_user_data(user["id"])
    db.soft_delete_user(user["id"])
    return Response(status_code=204)


@router.get("/records", response_model=RecordListResponse)
async def list_records(
    request: Request, limit: int = 20, offset: int = 0
) -> RecordListResponse:
    user, client_id = _auth(request)
    user_id = user["id"] if user else None
    rows, total = db.list_records(user_id, client_id, limit, offset)
    items = [
        RecordItem(
            id=row["id"],
            chapter_id=row.get("chapter_id"),
            topic=row["topic"],
            level=row["level"],
            level_label=LEVEL_LABELS.get(row["level"], row["level"]),
            kind=row.get("kind") or "standard",
            status=row["status"],
            status_label=RECORD_STATUS_LABELS.get(row["status"], row["status"]),
            question_count=int(row.get("question_count") or 0),
            stars=int(row.get("stars") or 0),
            accuracy=round(float(row.get("accuracy") or 0), 3),
            points=int(row.get("exp") or 0) if row["status"] == "completed" else 0,
            created_at=row["created_at"],
            completed_at=row.get("completed_at"),
        )
        for row in rows
    ]
    return RecordListResponse(
        items=items,
        total=total,
        has_more=offset + len(items) < total,
    )