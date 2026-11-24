"""Verify the editor's repository contract without a real GitHub credential."""

import base64
import hashlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "deploy" / "admin"))
from article_editor import article_from_form, values_from_article  # noqa: E402
from github_editor import (  # noqa: E402
    API_PREFIX, ARTICLES, ArticleConflict, ArticleUnchanged, GitHubEditor, PublishInterrupted, RepositoryError,
    app_jwt, valid_slug,
)

MAIN = "a" * 40
PREVIOUS = "b" * 40
MARKER = {"name": ".editor-v1", "type": "file", "sha": PREVIOUS}
FILE = {"name": "notes.json", "type": "file", "sha": PREVIOUS}
TOKEN_PATH = "/app/installations/123/access_tokens"
ROOT_PATH = f"{API_PREFIX}/contents/{ARTICLES}"


class FakeAPI:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.requests = []

    def open(self, request, *, timeout):
        self.requests.append((request.get_method(), urlsplit(request.full_url),
                              json.loads(request.data) if request.data else None, request.get_header("Authorization")))
        if not self.replies:
            raise AssertionError("Unexpected API call")
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return io.BytesIO(json.dumps(reply, ensure_ascii=False).encode("utf-8"))


def fake_client(*replies):
    api = FakeAPI({"token": "mock_short_lived_token"}, *replies)
    client = GitHubEditor("Iv1.example", "123", "/not/a/real/key", api, signer=lambda *_: "mock_signed_jwt")
    return client, api


class EditorRepositoryTest(unittest.TestCase):
    def test_migrated_articles_round_trip_without_content_loss(self):
        posts = sorted((ROOT / ARTICLES).glob("*.json"))
        self.assertTrue(posts)
        for post in posts:
            raw = json.loads(post.read_text(encoding="utf-8"))
            with self.subTest(file=post.name):
                self.assertEqual(post.stem, raw["slug"])
                self.assertEqual(raw, article_from_form(values_from_article(raw)))

    def test_create_pr_writes_only_one_article_and_never_main(self):
        for previous, listing in (("", [MARKER]), (PREVIOUS, [MARKER, FILE])):
            with self.subTest(edit=bool(previous)):
                client, api = fake_client({"object": {"sha": MAIN}}, listing, {}, {}, {"number": 51})
                article = {"slug": "notes", "title": "测试文章"}
                self.assertEqual(client.publish(article, previous), 51)
                self.assertTrue(all(url.scheme == "https" and url.netloc == "api.github.com" for _, url, _, _ in api.requests))
                self.assertEqual([(m, url.path) for m, url, _, _ in api.requests], [
                    ("POST", TOKEN_PATH), ("GET", f"{API_PREFIX}/git/ref/heads/main"), ("GET", ROOT_PATH),
                    ("POST", f"{API_PREFIX}/git/refs"), ("PUT", f"{ROOT_PATH}/notes.json"), ("POST", f"{API_PREFIX}/pulls"),
                ])
                self.assertEqual(api.requests[0][2], {
                    "repositories": ["Blog"], "permissions": {"contents": "write", "pull_requests": "write"},
                })
                self.assertEqual(api.requests[0][3], "Bearer mock_signed_jwt")
                self.assertTrue(all(req[3] == "Bearer mock_short_lived_token" for req in api.requests[1:]))
                self.assertEqual(api.requests[2][1].query, f"ref={MAIN}")
                created, changed, pull = (request[2] for request in api.requests[3:])
                self.assertRegex(changed["branch"], r"^blog-editor/notes-[0-9a-f]{12}$")
                self.assertEqual(created, {"sha": MAIN, "ref": f'refs/heads/{changed["branch"]}'})
                self.assertEqual(changed.get("sha", ""), previous)
                self.assertEqual(json.loads(base64.b64decode(changed["content"])), article)
                self.assertEqual((pull["base"], pull["head"]), ("main", changed["branch"]))

    def test_outdated_article_and_unmerged_layout_stop_before_new_branch(self):
        for listing, expected_error in (([MARKER, FILE], ArticleConflict), ([FILE], RepositoryError)):
            client, api = fake_client({"object": {"sha": MAIN}}, listing)
            with self.assertRaises(expected_error):
                client.publish({"slug": "notes"}, "")
            self.assertEqual(len(api.requests), 3)
            self.assertTrue(all(req[0] == "GET" for req in api.requests[1:]))

    def test_unchanged_article_does_not_create_a_branch(self):
        article = {"slug": "notes", "title": "A note"}
        raw = (json.dumps(article, ensure_ascii=False, indent=2) + "\n").encode()
        sha = hashlib.sha1(f"blob {len(raw)}\0".encode() + raw, usedforsecurity=False).hexdigest()
        client, api = fake_client({"object": {"sha": MAIN}}, [MARKER, {**FILE, "sha": sha}])
        with self.assertRaises(ArticleUnchanged):
            client.publish(article, sha)
        self.assertEqual(len(api.requests), 3)

    def test_read_uses_main_and_checks_exact_article_path(self):
        payload = {"slug": "notes", "title": "A note"}
        record = {"type": "file", "path": f"{ARTICLES}/notes.json", "encoding": "base64",
                  "content": base64.b64encode(json.dumps(payload).encode()).decode(), "sha": PREVIOUS}
        client, api = fake_client(record)
        self.assertEqual(client.read("notes"), (payload, PREVIOUS))
        self.assertEqual(api.requests[-1][1].query, "ref=main")
        for slug in ["..", "a/b", "Main/refs", "COM1", "nul", "a" * 65]:
            self.assertFalse(valid_slug(slug))
            with self.assertRaises(ArticleConflict):
                client.publish({"slug": slug}, "")
        self.assertEqual(len(api.requests), 2)

    def test_lost_write_response_is_not_retried_or_echoed(self):
        client, api = fake_client({"object": {"sha": MAIN}}, [MARKER], {}, {},
                                  HTTPError("https://api.github.com", 403, "do not expose this", {}, None))
        with self.assertRaises(PublishInterrupted) as error:
            client.publish({"slug": "notes"}, "")
        self.assertRegex(error.exception.branch, "^blog-editor/notes-")
        self.assertEqual((error.exception.stage, error.exception.reason), ("create_pull", "http_403"))
        self.assertNotIn("do not expose", str(error.exception))
        self.assertEqual(len(api.requests), 6)

    @unittest.skipUnless(shutil.which("openssl"), "OpenSSL is not installed")
    def test_app_jwt_is_signed_rs256_with_short_expiry(self):
        openssl = shutil.which("openssl")
        with tempfile.TemporaryDirectory() as temp:
            key, public, signature = [Path(temp) / name for name in ("temporary.pem", "pub.pem", "sig.bin")]
            quiet = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "check": True, "timeout": 10}
            subprocess.run([openssl, "genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:2048", "-out", str(key)], **quiet)
            subprocess.run([openssl, "pkey", "-in", str(key), "-pubout", "-out", str(public)], **quiet)
            header, claims, signed = app_jwt("Iv1.example", key, openssl=openssl, clock=lambda: 123456).split(".")
            self.assertEqual(json.loads(base64.urlsafe_b64decode(header + "=="))["alg"], "RS256")
            self.assertEqual(json.loads(base64.urlsafe_b64decode(claims + "==")),
                             {"iss": "Iv1.example", "iat": 123396, "exp": 123756})
            signature.write_bytes(base64.urlsafe_b64decode(signed + "=="))
            subprocess.run([openssl, "dgst", "-sha256", "-verify", str(public), "-signature", str(signature)],
                           input=f"{header}.{claims}".encode(), **quiet)


if __name__ == "__main__":
    unittest.main()
