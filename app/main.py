"""One-port FastAPI shell for Codespaces and Render, with SQLite-only sign-in."""
import asyncio
import json
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, update
from sqlalchemy.exc import OperationalError
from .passwords import check_password_hash
from . import agent, security
from .database import SessionLocal, init_db
from .models import User, LoginSession, ChatMessage, UserMemory, MemoryHistory, LoginFailure
from .settings import ROOT, SESSION_TIMEOUT

app = FastAPI(title="Agent Shell", version="0.1.0")
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
templates = Jinja2Templates(directory=str(ROOT / "templates"))
_locks: dict[str, asyncio.Lock] = {}

@app.on_event("startup")
def startup():
    init_db()


def utcnow():
    return datetime.now(timezone.utc)


def as_utc(value):
    if value is None:
        return datetime.fromtimestamp(0, timezone.utc)
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def page(request, template, **context):
    return templates.TemplateResponse(request=request, name=template, context=context)


def user_session(request, touch=True):
    pair = security.get_cookie_session(request)
    if pair is None:
        raise HTTPException(401, "Please sign in")
    uid, sid = pair
    with SessionLocal.begin() as db:
        active = db.get(LoginSession, sid)
        if not active or not active.active or active.user_id != uid:
            raise HTTPException(401, "Session inactive")
        expired = (utcnow() - as_utc(active.last_seen)).total_seconds() > SESSION_TIMEOUT
        if expired:
            active.active = False
            active.ended_reason = "expired"
        elif touch:
            active.last_seen = utcnow()
    if expired:
        raise HTTPException(401, "Session expired. Please log in again")
    return uid, sid


def chat_history(db, sid):
    rows = db.scalars(select(ChatMessage).where(ChatMessage.session_id == sid).order_by(ChatMessage.id)).all()
    return [{"role": r.role, "content": r.content, "citations": json.loads(r.sources_json)} for r in rows]


@app.get("/health")
def health():
    return {"status": "ok", "database": "sqlite", "agent_features": "shell"}


@app.get("/", response_class=HTMLResponse)
def root(request: Request):
    token = security.csrf_token()
    response = page(request, "login.html", csrf=token, error="")
    security.set_csrf(response, token)
    return response


@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...), csrf: str = Form(...)):
    security.check_csrf(request, csrf)
    username = username.strip()
    if not username or len(username) > 128:
        return page(request, "login.html", csrf=csrf, error="Invalid username or password")
    # SQLite's write transaction serializes concurrent logins; one-active-session is enforced in DB.
    with SessionLocal() as db:
        db.connection().exec_driver_sql("BEGIN IMMEDIATE")
        now = utcnow()
        remote = request.client.host if request.client else "unknown"
        bucket = hashlib.sha256(f"{remote}:{username.lower()}".encode()).hexdigest()
        fail = db.get(LoginFailure, bucket)
        if fail and (now - as_utc(fail.first_at)).total_seconds() >= 600:
            db.delete(fail)
            db.flush()
            fail = None
        if fail and fail.failures >= 5:
            db.commit()
            raise HTTPException(429, "Too many failed sign-ins. Retry after ten minutes.")
        user = db.scalar(select(User).where(User.username == username))
        if user is None or not check_password_hash(user.password_hash, password):
            if fail:
                fail.failures += 1
            else:
                db.add(LoginFailure(bucket=bucket, failures=1, first_at=now))
            db.commit()
            return page(request, "login.html", csrf=csrf, error="Invalid username or password")
        if fail:
            db.delete(fail)
        # Verify existing active login before creating a new one.
        sessions = db.scalars(select(LoginSession).where(LoginSession.user_id == user.id, LoginSession.active.is_(True))).all()
        for s in sessions:
            if (now - as_utc(s.last_seen)).total_seconds() > SESSION_TIMEOUT:
                s.active = False
                s.ended_reason = "expired"
            else:
                db.rollback()
                return page(request, "login.html", csrf=csrf,
                            error="This account already has an active session. Select EXIT there or wait for its inactivity timeout.")
        sid = secrets.token_urlsafe(32)
        db.add(LoginSession(id=sid, user_id=user.id, started_at=now, last_seen=now, active=True))
        db.commit()
        uid = user.id
    response = RedirectResponse("/chat", status_code=303)
    security.set_session(response, uid, sid)
    return response


@app.get("/chat", response_class=HTMLResponse)
def chat_page(request: Request):
    try:
        uid, sid = user_session(request)
    except HTTPException:
        return RedirectResponse("/", status_code=303)
    with SessionLocal() as db:
        username = db.get(User, uid).username
    token = request.cookies.get(security.CSRF_COOKIE) or security.csrf_token()
    response = page(request, "chat.html", username=username, csrf=token)
    security.set_csrf(response, token)
    security.set_session(response, uid, sid)
    return response


@app.get("/api/history")
def history(request: Request):
    _, sid = user_session(request)
    with SessionLocal() as db:
        messages = chat_history(db, sid)
    result = JSONResponse({"messages": messages})
    uid, _ = security.get_cookie_session(request)
    security.set_session(result, uid, sid)
    return result


@app.post("/api/message")
async def message(request: Request):
    uid, sid = user_session(request)
    payload = await request.json()
    security.check_csrf(request, payload.get("csrf", ""))
    question = payload.get("message")
    if not isinstance(question, str) or not 1 <= len(question.strip()) <= 8000:
        raise HTTPException(422, "Message must contain 1 to 8000 characters")
    # Locks prevent two concurrent requests within one server process from overwriting chat order.
    lock = _locks.setdefault(sid, asyncio.Lock())
    if lock.locked():
        raise HTTPException(409, "Another reply is in progress")
    async with lock:
        with SessionLocal() as db:
            transcript = chat_history(db, sid)
            stored_memory = db.get(UserMemory, uid)
            previous_memory = stored_memory.content if stored_memory else ""
        try:
            answer, citations = await agent.answer(transcript, previous_memory, question.strip())
        except Exception:
            raise HTTPException(503, "Assistant request failed; previously saved chat remains intact")
        with SessionLocal.begin() as db:
            record = db.get(LoginSession, sid)
            if not record or not record.active:
                raise HTTPException(409, "Session no longer active")
            db.add(ChatMessage(session_id=sid, role="user", content=question.strip()))
            db.add(ChatMessage(session_id=sid, role="assistant", content=answer, sources_json=json.dumps(citations)))
            record.last_seen = utcnow()
        response = JSONResponse({"answer": answer, "citations": citations})
        security.set_session(response, uid, sid)
        return response


@app.post("/api/exit")
async def exit_chat(request: Request):
    uid, sid = user_session(request)
    payload = await request.json()
    security.check_csrf(request, payload.get("csrf", ""))
    lock = _locks.setdefault(sid, asyncio.Lock())
    if lock.locked():
        raise HTTPException(409, "Wait for the active reply before exiting")
    async with lock:
        with SessionLocal() as db:
            messages = chat_history(db, sid)
            old = db.get(UserMemory, uid)
            current_memory = old.content if old else ""
            already = db.scalar(select(MemoryHistory).where(MemoryHistory.session_id == sid))
        if messages and already is None:
            try:
                updated_memory = await agent.summarize(current_memory, messages)
            except Exception:
                raise HTTPException(503, "Memory update failed. Chat remains stored. Retry EXIT.")
        else:
            updated_memory = current_memory
        with SessionLocal.begin() as db:
            existing = db.scalar(select(MemoryHistory).where(MemoryHistory.session_id == sid))
            if not existing and messages:
                db.add(MemoryHistory(user_id=uid, session_id=sid, content=updated_memory))
                mem = db.get(UserMemory, uid)
                if mem:
                    mem.content = updated_memory
                    mem.updated_at = utcnow()
                else:
                    db.add(UserMemory(user_id=uid, content=updated_memory))
            current = db.get(LoginSession, sid)
            if current:
                current.active = False
                current.ended_reason = "exit"
        response = JSONResponse({"ok": True, "redirect": "/"})
        security.clear_session(response)
        return response


@app.get("/api/session")
def session_info(request: Request):
    uid, sid = user_session(request)
    return {"user_id": uid, "session_id": sid, "timeout_seconds": SESSION_TIMEOUT}
