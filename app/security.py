import hmac
import secrets
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from fastapi import HTTPException, Request
from .settings import SESSION_SECRET_KEY, COOKIE_SECURE, SESSION_TIMEOUT

COOKIE = "agent_session"
CSRF_COOKIE = "agent_csrf"


def serializer():
    if not SESSION_SECRET_KEY or len(SESSION_SECRET_KEY) < 24:
        raise HTTPException(503, "SESSION_SECRET_KEY must contain at least 24 characters")
    return URLSafeTimedSerializer(SESSION_SECRET_KEY, salt="agent-shell-v1")


def csrf_token():
    return secrets.token_urlsafe(32)


def check_csrf(request: Request, provided: str):
    actual = request.cookies.get(CSRF_COOKIE, "")
    if not actual or not provided or not hmac.compare_digest(actual, provided):
        raise HTTPException(403, "Invalid CSRF token. Refresh the page and retry.")


def set_csrf(response, token):
    response.set_cookie(CSRF_COOKIE, token, secure=COOKIE_SECURE, httponly=False, samesite="lax", max_age=86400)


def set_session(response, uid: int, sid: str):
    response.set_cookie(COOKIE, serializer().dumps({"uid": uid, "sid": sid}),
                        secure=COOKIE_SECURE, httponly=True, samesite="lax", max_age=SESSION_TIMEOUT)


def get_cookie_session(request: Request):
    cookie = request.cookies.get(COOKIE)
    if not cookie:
        return None
    try:
        value = serializer().loads(cookie, max_age=SESSION_TIMEOUT)
        return int(value["uid"]), str(value["sid"])
    except (BadSignature, SignatureExpired, KeyError, ValueError, TypeError):
        return None


def clear_session(response):
    response.delete_cookie(COOKIE, secure=COOKIE_SECURE, samesite="lax")
