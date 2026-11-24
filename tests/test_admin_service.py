"""Exercise the real admin WSGI routes with simulated GitHub responses."""

import base64
import hashlib
import io
import json
import re
import sys
import unittest
from pathlib import Path
from html import unescape
from types import SimpleNamespace
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from wsgiref.util import setup_testing_defaults

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy" / "admin"))
from article_editor import TICKET_AGE  # noqa: E402
from admin_service import (  # noqa: E402
    Admin, Config, ExpiringIds, FLOW_AGE, FLOW_COOKIE, GitHub, SESSION_AGE, SESSION_COOKIE, TOKEN_URL, USER_URL,
)


class FakeUpstream:
    def __init__(self):
        self.requests = []
        self.replies = []

    def open(self, request, *, timeout):
        self.requests.append(request)
        if not self.replies:
            raise AssertionError("The application unexpectedly contacted GitHub")
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return io.BytesIO(json.dumps(reply).encode("utf-8"))


class FakePublisher:
    def __init__(self):
        self.reads = []
        self.published = []
        self.article = None
        self.sha = "a" * 40

    def list_slugs(self):
        self.reads.append("list")
        return ["test-article"]

    def read(self, slug):
        self.reads.append(slug)
        return self.article, self.sha

    def publish(self, article, base):
        self.published.append((article, base))
        return 44


class AdminTest(unittest.TestCase):
    def setUp(self):
        self.now = 100
        self.config = Config("https://blog.example", "client_id_example", "test_only_secret", 101)
        github = GitHub(self.config)
        github.opener = self.upstream = FakeUpstream()
        self.app = Admin(self.config, github, lambda: self.now)

    def request(self, path="/admin/", *, cookie="", method="GET", body="", **headers):
        url = urlsplit(path)
        env = {
            "REQUEST_METHOD": method, "PATH_INFO": url.path, "QUERY_STRING": url.query,
            "HTTP_HOST": self.config.host, "HTTP_COOKIE": cookie,
            "CONTENT_LENGTH": str(len(body)), "CONTENT_TYPE": "application/x-www-form-urlencoded",
            "wsgi.input": io.BytesIO(body.encode("ascii")), "wsgi.url_scheme": "https", **headers,
        }
        setup_testing_defaults(env)
        response = SimpleNamespace(headers={})

        def start(status, pairs):
            response.status = int(status.split()[0])
            response.cookies = [v for k, v in pairs if k == "Set-Cookie"]
            response.headers = dict(pairs)

        response.body = b"".join(self.app(env, start)).decode("utf-8")
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        return response

    def begin(self, cookie=""):
        response = self.request("/admin/login", cookie=cookie)
        self.assertEqual(response.status, 302)
        url = urlsplit(response.headers["Location"])
        self.assertEqual((url.scheme, url.netloc, url.path), ("https", "github.com", "/login/oauth/authorize"))
        authorize = parse_qs(url.query, keep_blank_values=True)
        self.assertEqual(authorize["redirect_uri"], [self.config.callback])
        self.assertEqual(authorize["code_challenge_method"], ["S256"])
        self.assertNotIn("scope", authorize)
        self.assertNotIn("client_secret", authorize)
        self.assertNotIn("code_verifier", authorize)
        flow, flags = response.cookies[0].split("; ", 1)
        self.assertEqual(flags, f"Path=/; Max-Age={FLOW_AGE}; Secure; HttpOnly; SameSite=Lax")
        self.assertNotEqual(flow.split("=", 1)[1], authorize["state"][0])
        return flow, authorize

    def callback(self, flow, state, code="github-code"):
        return self.request("/admin/callback?" + urlencode({"state": state, "code": code}), cookie=flow)

    def owner_session(self, login="T-CrB"):
        flow, authorize = self.begin()
        self.upstream.replies.extend([
            {"access_token": "gho_test_access", "scope": ""}, {"id": self.config.owner_id, "login": login},
        ])
        response = self.callback(flow, authorize["state"][0])
        self.assertEqual(response.status, 303)
        self.assertEqual(response.headers["Location"], "/admin/")
        self.assertEqual(response.cookies[0], f"{FLOW_COOKIE}=; Path=/; Max-Age=0; Secure; HttpOnly; SameSite=Lax")
        session, flags = response.cookies[1].split("; ", 1)
        self.assertEqual(flags, f"Path=/; Max-Age={SESSION_AGE}; Secure; HttpOnly; SameSite=Lax")
        self.assertTrue(session.startswith(SESSION_COOKIE + "="))
        self.assertNotIn("gho_test_access", session)
        self.assertNotIn(self.config.client_secret, str(response))
        return session, authorize

    def test_guest_sees_login_without_contacting_github(self):
        for cookie in ("", f"{SESSION_COOKIE}={'x' * 43}"):
            result = self.request(cookie=cookie, HTTP_X_FORWARDED_USER="T-CrB")
            self.assertEqual(result.status, 200)
            self.assertIn("用 GitHub 登录", result.body)
            self.assertNotIn("已验证", result.body)
            self.assertEqual(result.cookies, [])
        self.assertEqual(self.upstream.requests, [])
        self.assertEqual(self.request("/admin/edit").status, 404)

    def test_owner_uses_pkce_and_receives_session_even_if_username_changes(self):
        session, authorize = self.owner_session(login="renamed-owner")
        token_req, user_req = self.upstream.requests
        self.assertEqual((token_req.full_url, token_req.get_method()), (TOKEN_URL, "POST"))
        data = parse_qs(token_req.data.decode("ascii"))
        self.assertEqual(data["redirect_uri"], [self.config.callback])
        self.assertEqual(data["client_secret"], [self.config.client_secret])
        digest = hashlib.sha256(data["code_verifier"][0].encode("ascii")).digest()
        self.assertEqual(authorize["code_challenge"], [base64.urlsafe_b64encode(digest).decode().rstrip("=")])
        self.assertEqual(user_req.full_url, USER_URL)
        self.assertEqual(user_req.get_header("Authorization"), "Bearer gho_test_access")
        self.assertIn("站长 · 已验证", self.request(cookie=session).body)
        self.assertIn("@renamed-owner", self.request(cookie=session).body)

    def test_same_display_login_with_different_id_is_denied(self):
        flow, authorize = self.begin()
        self.upstream.replies.extend([
            {"access_token": "gho_test_guest", "scope": ""}, {"id": 999, "login": "T-CrB"},
        ])
        response = self.callback(flow, authorize["state"][0])
        self.assertEqual(response.status, 403)
        self.assertIn("没有站长权限", response.body)
        self.assertFalse(any(item.startswith(SESSION_COOKIE + "=") for item in response.cookies))
        self.assertIn("站长登录", self.request(cookie=flow).body)

    def test_callback_without_correct_browser_state_is_rejected(self):
        flow, authorize = self.begin()
        state = authorize["state"][0]
        self.assertEqual(self.callback("", state).status, 400)
        rejected = self.callback(flow, "x" * 43)
        self.assertEqual(rejected.status, 400)
        self.assertEqual(rejected.cookies, [])
        self.assertEqual(self.upstream.requests, [])
        self.upstream.replies.extend([{"access_token": "gho_token"}, {"id": 101, "login": "T-CrB"}])
        self.assertEqual(self.callback(flow, state).status, 303)

    def test_old_callback_leaves_new_login_intact(self):
        previous, old = self.begin()
        current, new = self.begin(previous)
        rejected = self.callback(current, old["state"][0])
        self.assertEqual(rejected.status, 400)
        self.assertEqual(rejected.cookies, [])
        self.assertEqual(self.upstream.requests, [])
        self.upstream.replies.extend([{"access_token": "gho_token"}, {"id": 101, "login": "T-CrB"}])
        self.assertEqual(self.callback(current, new["state"][0]).status, 303)

    def test_full_flow_store_rejects_new_logins_without_evicting_active_flows(self):
        self.app.flows = ExpiringIds(FLOW_AGE, 2, lambda: self.now, evict_oldest=False)
        owner, _ = self.begin()
        self.begin()
        rejected = self.request("/admin/login")
        self.assertEqual(rejected.status, 503)
        self.assertEqual(rejected.cookies, [])
        self.assertIn("Retry-After", rejected.headers)
        # The same browser can replace its own pending login even at capacity.
        owner, auth = self.begin(owner)
        self.upstream.replies.extend([{"access_token": "gho_token"}, {"id": 101, "login": "T-CrB"}])
        self.assertEqual(self.callback(owner, auth["state"][0]).status, 303)
        self.begin()

    def test_callback_is_single_use(self):
        flow, authorize = self.begin()
        state = authorize["state"][0]
        self.upstream.replies.extend([{"access_token": "gho_token"}, {"id": 101, "login": "T-CrB"}])
        self.assertEqual(self.callback(flow, state).status, 303)
        self.assertEqual(self.callback(flow, state).status, 400)
        self.assertEqual(len(self.upstream.requests), 2)

    def test_callback_denial_and_duplicate_fields_do_not_use_github(self):
        flow, authorize = self.begin()
        state = authorize["state"][0]
        self.assertEqual(self.request(f"/admin/callback?state={state}&error=access_denied", cookie=flow).status, 400)
        flow, authorize = self.begin()
        state = authorize["state"][0]
        response = self.request(f"/admin/callback?state={state}&state={state}&code=a", cookie=flow)
        self.assertEqual(response.status, 400)
        self.assertEqual(self.upstream.requests, [])

    def test_flow_and_session_expire(self):
        flow, authorize = self.begin()
        self.now += FLOW_AGE
        self.assertEqual(self.callback(flow, authorize["state"][0]).status, 400)
        self.assertEqual(self.upstream.requests, [])
        session, _ = self.owner_session()
        self.now += SESSION_AGE
        self.assertIn("站长登录", self.request(cookie=session).body)

    def expect_sign_in_failure(self, replies, stage, reason):
        flow, authorize = self.begin()
        self.upstream.replies.extend(replies)
        with self.assertLogs("admin_service", level="WARNING") as logs:
            response = self.callback(flow, authorize["state"][0], code="must_not_log_code")
        self.assertEqual(response.status, 502)
        self.assertIn("暂时无法登录", response.body)
        self.assertEqual(len(response.cookies), 1)
        self.assertEqual(logs.output, [f"WARNING:admin_service:GitHub sign-in failed: stage={stage} reason={reason}"])
        self.assertNotIn("must", response.body + " ".join(logs.output))

    def test_network_or_scoped_token_fails_closed(self):
        self.expect_sign_in_failure([URLError(TimeoutError("must not appear"))], "token_exchange", "timeout")
        self.expect_sign_in_failure([{"scope": "repo", "access_token": "must_not_appear"}],
                                    "token_exchange", "unexpected_scope")
        self.assertEqual([req.full_url for req in self.upstream.requests], [TOKEN_URL, TOKEN_URL])

    def test_only_known_oauth_errors_are_logged(self):
        for code, reason in (("incorrect_client_credentials", "incorrect_client_credentials"),
                             ("must_not_appear", "oauth_error"), ({"must_not_appear": True}, "oauth_error")):
            self.expect_sign_in_failure([{"error": code, "error_description": "must not appear"}],
                                        "token_exchange", reason)
        self.assertEqual([req.full_url for req in self.upstream.requests], [TOKEN_URL] * 3)

    def test_user_lookup_failure_is_distinct_from_token_exchange(self):
        self.expect_sign_in_failure([{"access_token": "must_not_log_token", "scope": ""},
                                     HTTPError(USER_URL, 401, "must not log message", {}, None)],
                                    "user_lookup", "http_401")
        self.assertEqual([req.full_url for req in self.upstream.requests], [TOKEN_URL, USER_URL])

    def enable_editor(self):
        self.publisher = FakePublisher()
        self.app = Admin(self.config, self.app.github, lambda: self.now, publisher=self.publisher)

    def get_editor_form(self, session):
        page = self.request("/admin/article", cookie=session)
        self.assertEqual(page.status, 200)
        self.assertEqual(page.headers["Referrer-Policy"], "same-origin")
        return {**self.editor_tokens(page),
                "title": "A test & a preview", "slug": "test-article", "excerpt": "Test summary",
                "category": "Notes", "date": "2026-11-24", "readTime": "3 min read", "accent": "green",
                "coverLabel": "01 / TEST", "tags": "Astro, GitHub", "featured": "1",
                "body": "## 小标题\n\n这里是 <strong>普通文本</strong>。\n\n- 第一项\n- 第二项"}

    def editor_tokens(self, response):
        return dict(re.findall(r'name="(csrf|ticket|base)" value="([^"]*)"', response.body))

    def post_article(self, session, values, operation):
        return self.request(f"/admin/article/{operation}", cookie=session, method="POST",
                            body=urlencode(values), HTTP_ORIGIN=self.config.origin)

    def test_editor_does_not_contact_github_for_guests_or_when_disabled(self):
        session, _ = self.owner_session()
        self.assertEqual(self.request("/admin/articles", cookie=session).status, 404)
        self.enable_editor()
        self.assertEqual(self.request("/admin/articles").status, 403)
        self.assertEqual(self.request("/admin/article/publish", method="POST").status, 403)
        self.assertEqual(self.publisher.reads, [])
        self.assertEqual(self.publisher.published, [])

    def test_owner_can_preview_and_publish_exactly_once(self):
        self.enable_editor()
        session, _ = self.owner_session()
        self.assertIn("管理文章", self.request(cookie=session).body)
        self.assertIn("test-article", self.request("/admin/articles", cookie=session).body)
        values = self.get_editor_form(session)
        preview = self.post_article(session, values, "preview")
        self.assertEqual(preview.status, 200)
        self.assertIn("<h3>小标题</h3>", preview.body)
        self.assertIn("&lt;strong&gt;普通文本&lt;/strong&gt;", preview.body)
        self.assertNotIn("<strong>普通文本</strong>", preview.body)
        self.assertEqual(self.publisher.published, [])
        refreshed = self.editor_tokens(preview)
        self.assertNotEqual(refreshed["ticket"], values["ticket"])
        self.assertEqual(self.post_article(session, values, "publish").status, 409)
        values.update(refreshed)
        result = self.post_article(session, values, "publish")
        self.assertEqual(result.status, 201)
        self.assertIn("https://github.com/T-CrB/Blog/pull/44", result.body)
        self.assertEqual(self.publisher.published[0][0]["tags"], ["Astro", "GitHub"])
        replay = self.post_article(session, values, "publish")
        self.assertEqual(replay.status, 409)
        self.assertEqual(self.editor_tokens(replay)["ticket"], "")
        self.assertEqual(len(self.publisher.published), 1)

    def test_preview_refreshes_the_ticket_when_it_is_about_to_expire(self):
        self.enable_editor()
        session, _ = self.owner_session()
        values = self.get_editor_form(session)
        self.now += TICKET_AGE - 1
        preview = self.post_article(session, values, "preview")
        self.assertEqual(preview.status, 200)
        self.now += 2
        self.assertEqual(self.post_article(session, {**values, **self.editor_tokens(preview)}, "publish").status, 201)

    def test_expired_ticket_preserves_form_and_requires_new_preview(self):
        self.enable_editor()
        session, _ = self.owner_session()
        values = self.get_editor_form(session)
        self.now += TICKET_AGE + 1
        stale = self.post_article(session, values, "publish")
        self.assertEqual(stale.status, 409)
        self.assertIn(values["title"], unescape(stale.body))
        self.assertIn(values["body"], unescape(stale.body))
        recovery = {**values, **self.editor_tokens(stale)}
        self.assertEqual(recovery["ticket"], "")
        self.assertEqual(self.post_article(session, recovery, "publish").status, 409)
        self.assertEqual(self.publisher.published, [])
        preview = self.post_article(session, recovery, "preview")
        self.assertEqual(preview.status, 200)
        self.assertEqual(self.post_article(session, {**values, **self.editor_tokens(preview)}, "publish").status, 201)
        self.assertEqual(len(self.publisher.published), 1)

    def test_title_only_edit_preserves_body_and_tags_from_the_original_blob(self):
        self.enable_editor()
        session, _ = self.owner_session()
        values = self.get_editor_form(session)
        body = [{"type": "p", "text": "## This is literal text"},
                {"type": "quote", "text": "A quote", "cite": "An author"}]
        tags = ["HTML、CSS"]
        self.publisher.article = {
            **{name: values[name] for name in ("slug", "title", "excerpt", "category", "date", "readTime", "accent", "coverLabel")},
            "body": body, "tags": tags,
        }
        html = self.request("/admin/article?slug=test-article", cookie=session)
        self.assertEqual(html.status, 200)
        text = "## This is literal text\n\n> A quote\n> An author"
        self.assertIn(text, unescape(html.body))
        values.update(self.editor_tokens(html), title="Only the title changed", tags=tags[0], body=text.replace("\n", "\r\n"))
        self.assertEqual(self.post_article(session, values, "publish").status, 201)
        [(article, base)] = self.publisher.published
        self.assertEqual(base, self.publisher.sha)
        self.assertEqual(article["body"], body)
        self.assertEqual(article["tags"], tags)

    def test_stale_article_retains_input_without_publishing(self):
        self.enable_editor()
        session, _ = self.owner_session()
        values = self.get_editor_form(session)
        values["base"] = "b" * 40
        result = self.post_article(session, values, "publish")
        self.assertEqual(result.status, 409)
        self.assertIn(values["body"], unescape(result.body))
        self.assertEqual(self.publisher.published, [])

    def test_publish_rejects_bad_origin_csrf_and_path(self):
        self.enable_editor()
        session, _ = self.owner_session()
        values = self.get_editor_form(session)
        for changes, origin, status in (({}, "https://other.example", 403), ({"csrf": "错"}, self.config.origin, 403),
                                        ({"slug": "../index"}, self.config.origin, 422)):
            result = self.request("/admin/article/publish", cookie=session, method="POST",
                                  body=urlencode({**values, **changes}), HTTP_ORIGIN=origin)
            self.assertEqual(result.status, status)
        self.assertEqual(self.publisher.published, [])

    def test_logout_needs_session_and_csrf_and_revokes_session(self):
        session, _ = self.owner_session()
        dashboard = self.request(cookie=session).body
        csrf = re.search(r'name="csrf" value="([\w-]+)"', dashboard).group(1)
        body = urlencode({"csrf": csrf})
        self.assertEqual(self.request("/admin/logout", cookie=session).status, 405)
        self.assertEqual(self.request("/admin/logout", method="POST", body=body).status, 403)
        self.assertEqual(self.request("/admin/logout", cookie=session, method="POST", body="csrf=wrong").status, 403)
        self.assertEqual(self.request("/admin/logout", cookie=session, method="POST", body=body).status, 303)
        self.assertIn("站长登录", self.request(cookie=session).body)

    def test_host_and_rendered_text(self):
        self.assertEqual(self.request("/admin/login", HTTP_HOST="other.example").status, 400)
        result = self.request(method="HEAD")
        self.assertEqual(result.status, 200)
        self.assertEqual(result.body, "")
        session, _ = self.owner_session(login="a<&>")
        self.assertIn("@a&lt;&amp;&gt;", self.request(cookie=session).body)


if __name__ == "__main__":
    unittest.main()
