"""Shared-password login: signed session cookie, constant-time compare, simple lockout."""
import hmac
import secrets
import time

from fastapi import HTTPException, Request
from itsdangerous import BadSignature, URLSafeTimedSerializer

from .config import Settings

COOKIE = "whoop_session"
MAX_AGE = 30 * 24 * 3600
MAX_FAILURES = 5
LOCKOUT_SECONDS = 60


class Sessions:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.serializer = URLSafeTimedSerializer(settings.session_secret, salt="whoop-session")
        self._failures: dict[str, tuple[int, float]] = {}  # ip -> (count, lockout_until)

    # cookie helpers ------------------------------------------------------
    def read(self, request: Request) -> dict:
        raw = request.cookies.get(COOKIE)
        if not raw:
            return {}
        try:
            return self.serializer.loads(raw, max_age=MAX_AGE)
        except BadSignature:
            return {}

    def write(self, response, data: dict):
        response.set_cookie(COOKIE, self.serializer.dumps(data), max_age=MAX_AGE, httponly=True,
                            secure=self.settings.cookie_secure, samesite="lax", path="/")

    def clear(self, response):
        response.delete_cookie(COOKIE, path="/")

    def is_authed(self, request: Request) -> bool:
        return bool(self.read(request).get("auth"))

    def require(self, request: Request):
        """Dependency: 401 JSON for API callers, used by routes that need a login."""
        if not self.is_authed(request):
            raise HTTPException(status_code=401, detail="login required")

    # password + lockout --------------------------------------------------
    def locked_out(self, ip: str) -> bool:
        count, until = self._failures.get(ip, (0, 0.0))
        if until and time.time() < until:
            return True
        if until and time.time() >= until:
            self._failures.pop(ip, None)
        return False

    def check_password(self, ip: str, password: str) -> bool:
        if self.locked_out(ip):
            return False
        ok = hmac.compare_digest(password.encode(), self.settings.dashboard_password.encode())
        if ok:
            self._failures.pop(ip, None)
            return True
        count = self._failures.get(ip, (0, 0.0))[0] + 1
        until = time.time() + LOCKOUT_SECONDS if count >= MAX_FAILURES else 0.0
        self._failures[ip] = (count, until)
        return False

    @staticmethod
    def new_state() -> str:
        return secrets.token_urlsafe(16)


def client_ip(request: Request) -> str:
    # Fly terminates TLS and sets Fly-Client-IP; fall back to the socket address locally.
    return request.headers.get("fly-client-ip") or (request.client.host if request.client else "unknown")
