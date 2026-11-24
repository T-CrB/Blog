"""Owner-only GitHub sign-in. Served under /admin/ behind the site's HTTPS proxy."""

import base64
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import socket
import ssl
import threading
import time
from dataclasses import dataclass, field
from html import escape
from http import HTTPStatus
from http.client import HTTPException
from http.cookies import CookieError, SimpleCookie
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

AUTH_URL = "https://github.com/login/oauth/authorize"
TOKEN_URL = "https://github.com/login/oauth/access_token"
USER_URL = "https://api.github.com/user"
OAUTH_ERROR_CODES = frozenset({
    "incorrect_client_credentials", "redirect_uri_mismatch", "bad_verification_code", "unverified_user_email",
})
FLOW_COOKIE = "__Host-tcrb-admin-flow"
SESSION_COOKIE = "__Host-tcrb-admin-session"
FLOW_AGE = 10 * 60
SESSION_AGE = 8 * 60 * 60
OPAQUE_ID = re.compile(r"[A-Za-z0-9_-]{43}")
METHODS = {"/admin/": ("GET", "HEAD"), "/admin/login": ("GET",),
           "/admin/callback": ("GET",), "/admin/logout": ("POST",)}
LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class Config:
    origin: str
    client_id: str
    client_secret: str = field(repr=False)
    owner_id: int

    def __post_init__(self):
        if not re.fullmatch(r"https://[a-z0-9][a-z0-9.-]*", self.origin):
            raise ValueError("ADMIN_ORIGIN must be an HTTPS origin without a path or port")
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", self.client_id):
            raise ValueError("GITHUB_CLIENT_ID is invalid")
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,256}", self.client_secret):
            raise ValueError("The GitHub OAuth client secret is invalid")
        if type(self.owner_id) is not int or self.owner_id <= 0:
            raise ValueError("GITHUB_OWNER_ID must be a positive GitHub user ID")

    @property
    def host(self):
        return self.origin.removeprefix("https://")

    @property
    def callback(self):
        return f"{self.origin}/admin/callback"


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never send the client secret or a bearer token to a redirected URL.
        return None


class GitHubSignInError(ValueError):
    """Local diagnostic labels only, never an upstream message or response."""

    def __init__(self, stage, reason):
        self.stage = stage
        self.reason = reason
        super().__init__(f"{stage}: {reason}")


class GitHub:
    def __init__(self, config):
        self.config = config
        self.opener = build_opener(NoRedirect())

    def authorize(self, state, verifier):
        digest = hashlib.sha256(verifier.encode("ascii")).digest()
        challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
        return f"{AUTH_URL}?" + urlencode({
            "client_id": self.config.client_id,
            "redirect_uri": self.config.callback,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        })

    def _json(self, stage, url, *, data=None, headers):
        request = Request(url, data=data, headers={"User-Agent": "TCrB-Blog-Admin", **headers})
        try:
            with self.opener.open(request, timeout=8) as response:
                raw = response.read(65537)
        except HTTPError as error:
            error.close()
            raise GitHubSignInError(stage, f"http_{error.code}") from None
        except (OSError, HTTPException) as error:
            cause = error.reason if isinstance(error, URLError) else error
            if isinstance(cause, TimeoutError):
                reason = "timeout"
            elif isinstance(cause, socket.gaierror):
                reason = "dns_error"
            elif isinstance(cause, ssl.SSLError):
                reason = "tls_error"
            else:
                reason = "network_error"
            raise GitHubSignInError(stage, reason) from None
        if len(raw) > 65536:
            raise GitHubSignInError(stage, "response_too_large")
        try:
            result = json.loads(raw)
        except ValueError:
            raise GitHubSignInError(stage, "invalid_response") from None
        if not isinstance(result, dict):
            raise GitHubSignInError(stage, "invalid_response")
        return result

    def identify(self, code, verifier):
        token_reply = self._json("token_exchange", TOKEN_URL, headers={"Accept": "application/json"}, data=urlencode({
            "client_id": self.config.client_id,
            "client_secret": self.config.client_secret,
            "code": code,
            "code_verifier": verifier,
            "redirect_uri": self.config.callback,
        }).encode("ascii"))
        error = token_reply.get("error")
        if error:
            reason = error if isinstance(error, str) and error in OAUTH_ERROR_CODES else "oauth_error"
            raise GitHubSignInError("token_exchange", reason)
        if token_reply.get("scope", "") != "":
            raise GitHubSignInError("token_exchange", "unexpected_scope")
        token = token_reply.get("access_token")
        if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,512}", token):
            raise GitHubSignInError("token_exchange", "invalid_token")
        user = self._json("user_lookup", USER_URL, headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2026-03-10",
        })
        # Use the token once; do not put it in cookies or store it in a session.
        if type(user.get("id")) is not int or not isinstance(user.get("login"), str) or not user["login"]:
            raise GitHubSignInError("user_lookup", "invalid_identity")
        return user["id"], user["login"]


class ExpiringIds:
    """Bounded, thread-safe state shared by the login service's threads."""

    def __init__(self, ttl, capacity, clock, *, evict_oldest=True):
        self.ttl, self.capacity, self.clock = ttl, capacity, clock
        self.evict_oldest = evict_oldest
        self.entries = {}
        self.lock = threading.Lock()

    def issue(self, value, *, replace=""):
        with self.lock:
            now = self.clock()
            self.entries = {key: item for key, item in self.entries.items() if item[0] > now}
            if len(self.entries) >= self.capacity and replace not in self.entries:
                if not self.evict_oldest:
                    return None
                self.entries.pop(next(iter(self.entries)))
            self.entries.pop(replace, None)
            key = secrets.token_urlsafe(32)
            self.entries[key] = (now + self.ttl, value)
            return key

    def read(self, key, *, consume=False, matches=None):
        with self.lock:
            entry = self.entries.get(key)
            if not entry:
                return None
            if entry[0] <= self.clock():
                self.entries.pop(key)
                return None
            if matches is not None and not matches(entry[1]):
                return None
            if consume:
                self.entries.pop(key)
            return entry[1]


def cookie(name, key, age):
    return ("Set-Cookie", f"{name}={key}; Path=/; Max-Age={age}; Secure; HttpOnly; SameSite=Lax")


def cookie_id(environ, name):
    cookies = SimpleCookie()
    try:
        cookies.load(environ.get("HTTP_COOKIE", ""))
    except CookieError:
        return ""
    morsel = cookies.get(name)
    return morsel.value if morsel and OPAQUE_ID.fullmatch(morsel.value) else ""


def one(params, name):
    values = params.get(name, [])
    return values[0] if len(values) == 1 else ""


def fields(query):
    return parse_qs(query, keep_blank_values=True, max_num_fields=12)


def valid_logout(environ, expected):
    try:
        length = int(environ.get("CONTENT_LENGTH") or "0")
        media_type = environ.get("CONTENT_TYPE", "").split(";")[0]
        if not 0 < length <= 256 or media_type != "application/x-www-form-urlencoded":
            return False
        supplied = one(fields(environ["wsgi.input"].read(length).decode("ascii")), "csrf")
        return bool(OPAQUE_ID.fullmatch(supplied)) and hmac.compare_digest(supplied, expected)
    except ValueError:
        return False


def page(title, text, action=""):
    return f"""<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow"><title>{escape(title)} · TCrB</title>
<style>
:root {{color-scheme:light dark;--paper:#f4f0e8;--card:#fffdf9;--ink:#1d2b2a;--soft:#52625c;--line:#c8c4b9;--accent:#af4228}}
@media(prefers-color-scheme:dark) {{:root {{--paper:#17211f;--card:#22302c;--ink:#f4f0e8;--soft:#b2c0b9;--line:#56655f;--accent:#ffad95}}}}
* {{box-sizing:border-box}} body {{margin:0;padding:clamp(2rem,12vh,8rem) 1.25rem;background:var(--paper);color:var(--ink);font:1rem/1.65 system-ui,sans-serif}}
main {{max-width:34rem;margin:auto;padding:clamp(1.5rem,5vw,3rem);border:1px solid var(--line);border-top:3px solid var(--accent);background:var(--card);box-shadow:0 18px 40px #0001}}
.label {{font:0.78rem ui-monospace,monospace;letter-spacing:.14em;color:var(--accent);margin:0 0 1rem}} h1 {{font-size:clamp(1.8rem,6vw,2.5rem);line-height:1.2;margin:0}} p {{color:var(--soft)}}
.actions {{display:flex;flex-wrap:wrap;gap:.75rem;align-items:center;margin-top:1.5rem}} form {{margin:0}}
a,button {{font:inherit;color:inherit}} .button {{display:inline-block;padding:.52rem 1rem;border:1px solid var(--ink);border-radius:2rem;text-decoration:none;background:var(--ink);color:var(--card);cursor:pointer}}
:focus-visible {{outline:2px solid var(--accent);outline-offset:4px}}
</style><main><p class="label">TCRB / ADMIN</p><h1>{escape(title)}</h1>
<p>{escape(text)}</p><div class="actions">{action}<a href="/blog/">返回博客</a></div></main></html>"""


LOGIN = '<a class="button" href="/admin/login">用 GitHub 登录</a>'
RETRY = '<a class="button" href="/admin/">返回登录页</a>'
HEADERS = (
    ("Cache-Control", "no-store"),
    ("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"),
    ("Referrer-Policy", "no-referrer"),
    ("X-Content-Type-Options", "nosniff"),
)


class Admin:
    def __init__(self, config, github=None, clock=time.monotonic):
        self.config = config
        self.github = github or GitHub(config)
        self.flows = ExpiringIds(FLOW_AGE, 512, clock, evict_oldest=False)
        self.sessions = ExpiringIds(SESSION_AGE, 32, clock)

    def _callback(self, environ, session_id):
        clear = cookie(FLOW_COOKIE, "", 0)
        try:
            query = fields(environ.get("QUERY_STRING", ""))
        except ValueError:
            query = {}
        state, code = one(query, "state"), one(query, "code")
        flow = None
        if OPAQUE_ID.fullmatch(state):
            flow = self.flows.read(cookie_id(environ, FLOW_COOKIE), consume=True,
                                   matches=lambda entry: hmac.compare_digest(entry[0], state))
        if not flow:
            # An old callback must not invalidate a newer login in the same browser.
            return 400, page("登录请求无效", "登录请求不匹配或已过期，请继续最近一次登录，或重新登录。", RETRY), []
        if "error" in query or not re.fullmatch(r"[A-Za-z0-9._~-]{1,512}", code):
            return 400, page("未完成 GitHub 登录", "请返回并重新登录。", RETRY), [clear]
        try:
            user_id, login = self.github.identify(code, flow[1])
        except (OSError, HTTPException, ValueError) as error:
            # Do not log exception text, authorization codes, credentials, or response bodies.
            stage, reason = (error.stage, error.reason) if isinstance(error, GitHubSignInError) else (
                "unknown", "unexpected_error",
            )
            LOG.warning("GitHub sign-in failed: stage=%s reason=%s", stage, reason)
            return 502, page("暂时无法登录", "未能向 GitHub 验证身份，请稍后重新登录。", RETRY), [clear]
        if user_id != self.config.owner_id:
            return 403, page("没有站长权限", "这个 GitHub 账号不是博客的站长。", RETRY), [clear]
        self.sessions.read(session_id, consume=True)
        key = self.sessions.issue((login, secrets.token_urlsafe(32)))
        return 303, "", [("Location", "/admin/"), clear, cookie(SESSION_COOKIE, key, SESSION_AGE)]

    def _route(self, env):
        if env.get("HTTP_HOST", "").lower() != self.config.host:
            return 400, page("无效的站点地址", "请从博客的 HTTPS 地址访问后台。"), []
        path, method = env.get("PATH_INFO", ""), env.get("REQUEST_METHOD", "")
        if path not in METHODS:
            return 404, page("找不到页面", "这个后台页面不存在。", RETRY), []
        if method not in METHODS[path]:
            return 405, page("不支持的操作", "请从后台页面继续操作。", RETRY), [("Allow", ", ".join(METHODS[path]))]

        key = cookie_id(env, SESSION_COOKIE)
        session = self.sessions.read(key)
        if path == "/admin/callback":
            return self._callback(env, key)
        if path == "/admin/logout":
            if not session or not valid_logout(env, session[1]):
                return 403, page("无法退出", "登录已过期，或请求无效。", RETRY), []
            self.sessions.read(key, consume=True)
            return 303, "", [("Location", "/admin/"), cookie(SESSION_COOKIE, "", 0)]
        if path == "/admin/login":
            if session:
                return 303, "", [("Location", "/admin/")]
            state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            flow_id = self.flows.issue((state, verifier), replace=cookie_id(env, FLOW_COOKIE))
            if flow_id is None:
                return 503, page("暂时无法开始登录", "当前登录请求较多，请稍后重试。", RETRY), [("Retry-After", "60")]
            return 302, "", [("Location", self.github.authorize(state, verifier)), cookie(FLOW_COOKIE, flow_id, FLOW_AGE)]
        if not session:
            return 200, page("站长登录", "博客对所有人开放，只有站长能进入管理后台。", LOGIN), []
        logout = ('<form method="post" action="/admin/logout">'
                  f'<input type="hidden" name="csrf" value="{session[1]}">'
                  '<button class="button" type="submit">退出登录</button></form>')
        return 200, page("站长 · 已验证", f"当前账号：@{session[0]}。本阶段仅验证身份，尚未开放编辑和发布。", logout), []

    def __call__(self, environ, start_response):
        status, body, headers = self._route(environ)
        data = body.encode("utf-8")
        start_response(f"{status} {HTTPStatus(status).phrase}", [*HEADERS, *headers,
            ("Content-Type", "text/html; charset=utf-8"), ("Content-Length", str(len(data)))])
        return [b"" if environ.get("REQUEST_METHOD") == "HEAD" else data]


def create_app():
    directory = Path(os.environ["CREDENTIALS_DIRECTORY"])
    return Admin(Config(
        origin=os.environ["ADMIN_ORIGIN"],
        client_id=os.environ["GITHUB_CLIENT_ID"],
        client_secret=(directory / "github-client-secret").read_text(encoding="ascii").strip(),
        owner_id=int(os.environ["GITHUB_OWNER_ID"]),
    ))
