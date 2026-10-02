"""Optional sign-in for the whole API (``SIQE_API_AUTH=keys``).

Scripts send ``Authorization: Bearer <key>`` (or ``X-API-Key``). The web app signs in once with a
key and gets it back as an HttpOnly, SameSite=Strict cookie, so page scripts never see it. Both
are checked the same way, so revoking a key signs out every browser that used it.

This is plain ASGI so it covers the events WebSocket as well as HTTP.
"""

from http.cookies import SimpleCookie
from typing import Any

from starlette.types import ASGIApp, Receive, Scope, Send

from siqe.auth.keys import check
from siqe.core.errors import PROBLEM_JSON, AppError
from siqe.db.session import session_scope

COOKIE = "siqe_session"
# Reachable without a key: liveness checks, signing in, and the API description.
OPEN_PATHS = ("/api/health", "/api/auth/", "/api/openapi.json", "/api/docs")


def credential(scope: Scope) -> str | None:
    headers: dict[str, str] = {
        k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])
    }
    auth = headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    if headers.get("x-api-key"):
        return headers["x-api-key"].strip()
    raw = headers.get("cookie")
    if raw:
        jar: SimpleCookie = SimpleCookie()
        try:
            jar.load(raw)
        except Exception:
            return None
        if COOKIE in jar:
            return jar[COOKIE].value
    return None


def is_open(path: str) -> bool:
    return not path.startswith("/api/") or any(path.startswith(p) for p in OPEN_PATHS)


class ApiKeyAuth:
    def __init__(self, app: ASGIApp, *, enabled: bool) -> None:
        self.app = app
        self.enabled = enabled

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not self.enabled or scope["type"] not in ("http", "websocket") or is_open(scope["path"]):
            await self.app(scope, receive, send)
            return
        secret = credential(scope)
        ok = None
        if secret:
            async with session_scope() as session:
                ok = await check(session, secret)
        if ok is not None:
            scope.setdefault("state", {})["api_key"] = ok
            await self.app(scope, receive, send)
            return
        if scope["type"] == "websocket":
            # Closing before accept tells the browser the socket was refused (code 1008, policy).
            await send({"type": "websocket.close", "code": 1008, "reason": "Sign in first"})
            return
        await _deny(scope, send, wrong=bool(secret))


async def _deny(scope: Scope, send: Send, *, wrong: bool) -> None:
    import json

    if wrong:
        err = AppError(
            "auth.invalid_key",
            "That API key isn't valid. It may have been revoked.",
            status=401,
            title="Key not accepted",
            fix="Create a new key in Settings (or with `siqe keys create`) and use that.",
        )
    else:
        err = AppError(
            "auth.required",
            "This SIQE Studio asks for an API key.",
            status=401,
            title="Sign in",
            fix="Sign in with an API key, or send it as 'Authorization: Bearer <key>'.",
        )
    body = json.dumps(err.to_problem(scope["path"])).encode()
    headers: list[tuple[bytes, bytes]] = [
        (b"content-type", PROBLEM_JSON.encode()),
        (b"content-length", str(len(body)).encode()),
        (b"www-authenticate", b'Bearer realm="siqe"'),
    ]
    start: dict[str, Any] = {"type": "http.response.start", "status": 401, "headers": headers}
    await send(start)
    await send({"type": "http.response.body", "body": body})
