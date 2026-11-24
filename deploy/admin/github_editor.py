"""Narrow GitHub App client: only article files on new branches of T-CrB/Blog."""

import base64
import hashlib
import json
import re
import secrets
import subprocess
import time
from http.client import HTTPException
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request

REPOSITORY = "T-CrB/Blog"
BASE = "main"
ARTICLES = "src/content/blog"
FORMAT_MARKER = ".editor-v1"
API_ROOT = "https://api.github.com"
API_PREFIX = f"/repos/{REPOSITORY}"
SHA = re.compile(r"[0-9a-f]{40}")
SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
APP_CLIENT = re.compile(r"[A-Za-z0-9._-]{1,128}")
INSTALLATION = re.compile(r"[1-9][0-9]{0,19}")


class RepositoryError(Exception):
    """Only local error categories (or a numeric HTTP status)."""


class ArticleConflict(RepositoryError):
    pass


class ArticleUnchanged(RepositoryError):
    pass


class ArticleNotFound(RepositoryError):
    pass


class PublishInterrupted(RepositoryError):
    def __init__(self, branch, stage, reason):
        super().__init__("check_branch_before_retry")
        self.branch, self.stage, self.reason = branch, stage, reason


def valid_slug(value):
    return (isinstance(value, str) and len(value) <= 64 and bool(SLUG.fullmatch(value))
            and not re.fullmatch(r"con|prn|aux|nul|com[0-9]|lpt[0-9]", value))


def valid_sha(value):
    return isinstance(value, str) and bool(SHA.fullmatch(value))


def b64url(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=")


def app_jwt(client_id, key_path, *, openssl="/usr/bin/openssl", clock=time.time):
    now = int(clock())
    claims = json.dumps({"iss": client_id, "iat": now - 60, "exp": now + 300}, separators=(",", ":"))
    message = b".".join((b64url(b'{"typ":"JWT","alg":"RS256"}'), b64url(claims.encode("ascii"))))
    try:
        signed = subprocess.run([openssl, "dgst", "-sha256", "-sign", str(key_path), "-passin", "pass:"],
                                input=message, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                check=True, timeout=4).stdout
    except (OSError, subprocess.SubprocessError):
        raise RepositoryError("app_signing_failed") from None
    if not signed:
        raise RepositoryError("app_signing_failed")
    return (message + b"." + b64url(signed)).decode("ascii")


class GitHubEditor:
    def __init__(self, client_id, installation_id, key_path, opener, *, signer=app_jwt):
        if not APP_CLIENT.fullmatch(client_id) or not INSTALLATION.fullmatch(installation_id):
            raise ValueError("Invalid GitHub Editor app configuration")
        self.client_id = client_id
        self.installation_id = installation_id
        self.key_path = key_path
        self.opener = opener
        self.signer = signer

    def _request(self, method, path, token, payload=None):
        data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = Request(API_ROOT + path, method=method, data=data, headers={
            "Accept": "application/vnd.github+json", "Authorization": f"Bearer {token}",
            "Content-Type": "application/json", "User-Agent": "TCrB-Blog-Article-Editor",
            "X-GitHub-Api-Version": "2026-03-10",
        })
        try:
            with self.opener.open(request, timeout=8) as response:
                raw = response.read(2 * 1024 * 1024 + 1)
            if len(raw) > 2 * 1024 * 1024:
                raise RepositoryError("response_too_large")
            return json.loads(raw)
        except HTTPError as error:
            error.close()
            raise RepositoryError(f"http_{error.code}") from None
        except (OSError, HTTPException, ValueError, RecursionError):
            raise RepositoryError("network_or_invalid_response") from None

    def _token(self):
        jwt = self.signer(self.client_id, self.key_path)
        response = self._request("POST", f"/app/installations/{self.installation_id}/access_tokens", jwt, {
            "repositories": [REPOSITORY.split("/")[1]],
            "permissions": {"contents": "write", "pull_requests": "write"},
        })
        token = response.get("token") if isinstance(response, dict) else None
        if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,4096}", token):
            raise RepositoryError("invalid_installation_token")
        return token

    def _listing(self, token, revision):
        entries = self._request("GET", f"{API_PREFIX}/contents/{ARTICLES}?{urlencode({'ref': revision})}", token)
        if not isinstance(entries, list) or not all(isinstance(entry, dict) for entry in entries):
            raise RepositoryError("invalid_article_directory")
        if not any(entry.get("type") == "file" and entry.get("name") == FORMAT_MARKER for entry in entries):
            raise RepositoryError("article_format_not_merged")
        files = {}
        for entry in entries:
            name, sha = entry.get("name"), entry.get("sha")
            if (entry.get("type") == "file" and isinstance(name, str) and name.endswith(".json")
                    and valid_slug(name[:-5]) and valid_sha(sha)):
                files[name[:-5]] = sha
        return files

    def list_slugs(self):
        return sorted(self._listing(self._token(), BASE))

    def read(self, slug):
        if not valid_slug(slug):
            raise ArticleNotFound("invalid_article_slug")
        try:
            info = self._request("GET", f"{API_PREFIX}/contents/{ARTICLES}/{slug}.json?ref={BASE}", self._token())
        except RepositoryError as error:
            if str(error) == "http_404":
                raise ArticleNotFound("article_not_found") from None
            raise
        if (not isinstance(info, dict) or info.get("type") != "file" or info.get("encoding") != "base64"
                or info.get("path") != f"{ARTICLES}/{slug}.json" or not valid_sha(info.get("sha"))
                or not isinstance(info.get("content"), str)):
            raise RepositoryError("invalid_article_file")
        try:
            document = json.loads(base64.b64decode("".join(info["content"].split()), validate=True))
        except (ValueError, RecursionError):
            raise RepositoryError("invalid_article_file") from None
        if not isinstance(document, dict) or document.get("slug") != slug:
            raise RepositoryError("invalid_article_file")
        return document, info["sha"]

    def _require_main_rules(self, token):
        rules = self._request("GET", f"{API_PREFIX}/rules/branches/{BASE}", token)
        if not isinstance(rules, list) or not all(isinstance(rule, dict) for rule in rules):
            raise RepositoryError("invalid_main_rules")
        active = {rule.get("type") for rule in rules if isinstance(rule.get("type"), str)}
        if not {"update", "pull_request"} <= active:
            raise RepositoryError("main_rules_not_configured")

    def publish(self, article, expected_sha):
        slug = article.get("slug")
        if not valid_slug(slug) or (expected_sha != "" and not valid_sha(expected_sha)):
            raise ArticleConflict("invalid_article_version")
        token = self._token()
        # This checks active rules, not their bypass list; never give the editor App a bypass.
        self._require_main_rules(token)
        ref = self._request("GET", f"{API_PREFIX}/git/ref/heads/{BASE}", token)
        head = ref.get("object", {}) if isinstance(ref, dict) else None
        if not isinstance(head, dict) or not valid_sha(head.get("sha")):
            raise RepositoryError("invalid_main_reference")
        main_sha = head["sha"]
        # The file version check and new branch both refer to the same immutable commit.
        if self._listing(token, main_sha).get(slug, "") != expected_sha:
            raise ArticleConflict("article_changed_or_slug_used")
        raw = (json.dumps(article, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        blob_sha = hashlib.sha1(f"blob {len(raw)}\0".encode("ascii") + raw, usedforsecurity=False).hexdigest()
        if blob_sha == expected_sha:
            raise ArticleUnchanged("article_unchanged")
        branch = f"blog-editor/{slug}-{secrets.token_hex(6)}"
        change = {
            "branch": branch, "message": f"blog: {'edit' if expected_sha else 'add'} {slug}",
            "content": base64.b64encode(raw).decode("ascii"),
        }
        if expected_sha:
            change["sha"] = expected_sha
        stage = "create_branch"
        try:
            self._request("POST", API_PREFIX + "/git/refs", token, {"ref": f"refs/heads/{branch}", "sha": main_sha})
            stage = "write_article"
            self._request("PUT", f"{API_PREFIX}/contents/{ARTICLES}/{slug}.json", token, change)
            stage = "create_pull"
            pull = self._request("POST", API_PREFIX + "/pulls", token, {
                "base": BASE, "head": branch, "title": f"blog: {'edit' if expected_sha else 'add'} {slug}",
                "body": f"Article `{slug}` from the owner-only blog editor. Review the change before merging.",
            })
            number = pull.get("number") if isinstance(pull, dict) else None
            if type(number) is not int or number <= 0:
                raise RepositoryError("invalid_pull_request_number")
        except RepositoryError as error:
            # A write may have succeeded even when its response was lost. Do not retry or delete it.
            raise PublishInterrupted(branch, stage, str(error)) from None
        return number
