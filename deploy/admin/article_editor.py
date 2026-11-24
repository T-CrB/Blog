"""Server-rendered article forms. The browser never receives a GitHub credential."""

import hmac
import logging
import re
from datetime import date
from html import escape
from urllib.parse import parse_qs, urlencode

from github_editor import (
    ArticleConflict, ArticleNotFound, ArticleUnchanged, PublishInterrupted, REPOSITORY, RepositoryError, valid_sha,
    valid_slug,
)

EDITOR_METHODS = {
    "/admin/articles": ("GET",),
    "/admin/article": ("GET",),
    "/admin/article/preview": ("POST",),
    "/admin/article/publish": ("POST",),
}
MAX_REQUEST = 256 * 1024
MAX_BODY_CHARS = 18_000
TOKEN = re.compile(r"[A-Za-z0-9_-]{43}")
ACCENTS = {"coral": "珊瑚", "blue": "蓝色", "green": "绿色", "yellow": "黄色"}
FIELDS = (
    ("title", "标题", 100), ("excerpt", "摘要", 300), ("category", "分类", 56),
    ("readTime", "阅读时间", 32), ("coverLabel", "封面编号", 40),
)
BACK = '<a href="/admin/">返回后台</a>'
ARTICLES_LINK = '<a href="/admin/articles">文章列表</a>'
ADD = '<a class="button" href="/admin/article">写新文章</a>'
LOG = logging.getLogger(__name__)


class InvalidArticle(ValueError):
    """Validation errors are safe to display to the signed-in owner."""


def parse_body(value):
    value = value.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not value or len(value) > MAX_BODY_CHARS or re.search(r"[\x00-\x08\x0b-\x1f\x7f]", value):
        raise InvalidArticle("正文不能为空、不能超过 18,000 字，也不能含控制字符。")
    blocks = []
    for part in re.split(r"\n[ \t]*\n+", value):
        lines = part.split("\n")
        if len(lines) == 1 and part.startswith("## ") and part[3:].strip():
            block = {"type": "h2", "text": part[3:].strip()}
        elif all(line.startswith("- ") and line[2:].strip() for line in lines):
            block = {"type": "list", "items": [line[2:].strip() for line in lines]}
        elif all(line.startswith("> ") and line[2:].strip() for line in lines):
            cite = lines.pop()[2:] if len(lines) > 1 and lines[-1].startswith("> — ") else ""
            block = {"type": "quote", "text": "\n".join(line[2:] for line in lines)}
            if cite:
                block["cite"] = cite
        else:
            block = {"type": "p", "text": part.strip()}
        blocks.append(block)
    if len(blocks) > 200:
        raise InvalidArticle("正文最多保留 200 个段落、标题、引用或列表块。")
    return blocks


def body_to_text(blocks):
    parts = []
    for block in blocks:
        kind = block["type"]
        if kind == "list":
            parts.append("\n".join(f"- {item}" for item in block["items"]))
        elif kind == "h2":
            parts.append(f'## {block["text"]}')
        elif kind == "quote":
            quote = "\n".join(f"> {line}" for line in block["text"].split("\n"))
            parts.append(quote + (f'\n> {block["cite"]}' if block.get("cite") else ""))
        elif kind == "p":
            parts.append(block["text"])
        else:
            raise ValueError("Invalid body block")
    return "\n\n".join(parts)


def article_from_form(values):
    slug = values.get("slug", "")
    if not valid_slug(slug):
        raise InvalidArticle("文章网址只能用小写英文字母、数字和单个连字符，最长 64 个字符。")
    article = {"slug": slug}
    for key, label, limit in FIELDS:
        value = values.get(key, "").strip()
        if not value or len(value) > limit or re.search(r"[\x00-\x1f\x7f]", value):
            raise InvalidArticle(f"{label}不能为空，且最多 {limit} 个字符。")
        article[key] = value
    value = values.get("date", "")
    try:
        if date.fromisoformat(value).isoformat() != value:
            raise ValueError
    except ValueError:
        raise InvalidArticle("请填写有效的发布日期。") from None
    article["date"] = value
    accent = values.get("accent", "")
    if accent not in ACCENTS:
        raise InvalidArticle("请选择一个封面颜色。")
    article["accent"] = accent
    tags = [part.strip() for part in re.split(r"[,，、]", values.get("tags", "")) if part.strip()]
    if len(tags) > 10 or any(len(tag) > 32 or re.search(r"[\x00-\x1f\x7f]", tag) for tag in tags):
        raise InvalidArticle("最多填写 10 个标签，每个不超过 32 个字符。")
    article["tags"] = tags
    if values.get("featured") == "1":
        article["featured"] = True
    article["body"] = parse_body(values.get("body", ""))
    return article


def values_from_article(article):
    values = {key: article[key] for key in ("slug", "date", "accent", *(item[0] for item in FIELDS))}
    if not all(isinstance(value, str) for value in values.values()):
        raise ValueError("Invalid article field")
    return {**values, "tags": ", ".join(article["tags"]), "body": body_to_text(article["body"]),
            "featured": "1" if article.get("featured") else ""}


def read_form(env):
    try:
        length = int(env.get("CONTENT_LENGTH") or "0")
        if (not 0 < length <= MAX_REQUEST
                or env.get("CONTENT_TYPE", "").split(";", 1)[0] != "application/x-www-form-urlencoded"):
            raise ValueError
        body = env["wsgi.input"].read(length)
        if len(body) != length:
            raise ValueError
        fields = parse_qs(body.decode("ascii"), keep_blank_values=True, errors="strict", max_num_fields=14)
        if any(len(items) != 1 for items in fields.values()):
            raise ValueError
        return {name: items[0] for name, items in fields.items()}
    except ValueError:
        raise InvalidArticle("表单格式不正确或内容过长，请返回文章编辑页重新提交。") from None


def preview(article):
    out = [f'<article class="article-preview"><div class="label">ARTICLE PREVIEW</div><h2>{escape(article["title"])}</h2>',
           f'<p>{escape(article["excerpt"])}</p>']
    for block in article["body"]:
        kind = block["type"]
        if kind == "list":
            out.extend(("<ul>", *(f"<li>{escape(item)}</li>" for item in block["items"]), "</ul>"))
        elif kind == "quote":
            cite = f'<cite>{escape(block["cite"])}</cite>' if block.get("cite") else ""
            out.append(f'<blockquote>{escape(block["text"])}{cite}</blockquote>')
        else:
            tag = "h3" if kind == "h2" else "p"
            out.append(f'<{tag}>{escape(block["text"])}</{tag}>')
    return "".join(out) + "</article>"


def form_html(values, csrf, ticket):
    def v(name):
        return escape(values.get(name, ""), quote=True)

    base = v("base")
    slug_input = (f'<input name="slug" required maxlength="64" pattern="[a-z0-9]+(-[a-z0-9]+)*" '
                  f'value="{v("slug")}" {"readonly" if base else ""}>')
    inputs = "".join(f'<label>{label}<input name="{key}" required maxlength="{limit}" value="{v(key)}"></label>'
                     for key, label, limit in FIELDS)
    options = "".join(f'<option value="{key}" {"selected" if values.get("accent") == key else ""}>{label}</option>'
                      for key, label in ACCENTS.items())
    checked = "checked" if values.get("featured") == "1" else ""
    return f'''<form class="editor" method="post" action="/admin/article/preview" accept-charset="UTF-8">
<input type="hidden" name="csrf" value="{csrf}"><input type="hidden" name="ticket" value="{ticket}">
<input type="hidden" name="base" value="{base}">
<div class="editor-grid"><label>文章网址（slug）{slug_input}</label>{inputs}
<label>日期<input type="date" required name="date" value="{v("date")}"></label>
<label>标签（逗号分隔）<input name="tags" maxlength="340" value="{v("tags")}"></label>
<label>封面颜色<select name="accent">{options}</select></label>
<label class="editor-check"><input type="checkbox" name="featured" value="1" {checked}>突出显示文章卡片</label></div>
<label for="body">正文</label><p class="editor-hint" id="body-hint">用空行分段。<code>## </code>是小标题，<code>&gt; </code>是引用，<code>- </code>是列表。正文不会执行 HTML。</p>
<textarea id="body" name="body" aria-describedby="body-hint" required rows="13" maxlength="{MAX_BODY_CHARS}">{v("body")}</textarea>
<div class="actions"><button class="button" type="submit">预览文章</button>
<button class="button" type="submit" formaction="/admin/article/publish">创建 GitHub PR</button></div>
</form>'''


class ArticleEditor:
    def __init__(self, publisher, origin, page, tickets):
        self.publisher = publisher
        self.origin = origin
        self.page = page
        self.tickets = tickets

    def _form(self, values, csrf, *, status=200, message=None, extra="", ticket=None):
        title = "编辑文章" if values.get("base") else "写新文章"
        text = "创建 PR 只会提交文章修改，合并后才会发布。离开本页前，未提交的文字不会自动保存。"
        controls = form_html(values, csrf, ticket or self.tickets.issue(csrf))
        notice = f'<p class="editor-notice" role="alert">{escape(message)}</p>' if message else ""
        return status, self.page(title, text, ARTICLES_LINK, content=notice + controls + extra, wide=True), []

    def handle(self, path, env, csrf):
        if env.get("REQUEST_METHOD") == "GET":
            try:
                if path == "/admin/articles":
                    items = self.publisher.list_slugs()
                    links = "".join(f'<li><a href="/admin/article?{urlencode({"slug": slug})}">{escape(slug)}</a></li>'
                                    for slug in items if valid_slug(slug))
                    content = f'<ul class="article-list">{links}</ul>' if links else '<p>还没有文章。</p>'
                    return 200, self.page("文章管理", "编辑已发布的文章，或者写一篇新的。", ADD + BACK,
                                          content=content, wide=True), []
                params = parse_qs(env.get("QUERY_STRING", ""), keep_blank_values=True, max_num_fields=2)
                if not params:
                    return self._form({"date": date.today().isoformat(), "readTime": "5 min read",
                                       "coverLabel": "TCrB / note", "accent": "coral"}, csrf)
                slugs = params.get("slug", [])
                if len(slugs) != 1 or not valid_slug(slugs[0]):
                    raise ArticleNotFound("invalid_article_slug")
                article, sha = self.publisher.read(slugs[0])
                return self._form({**values_from_article(article), "base": sha}, csrf)
            except ArticleNotFound:
                return 404, self.page("找不到文章", "请从文章列表重新打开。", ARTICLES_LINK), []
            except (RepositoryError, ValueError, TypeError, KeyError) as error:
                LOG.warning("Article editor read failed: %s", error if isinstance(error, RepositoryError) else "invalid_article")
                return 502, self.page("暂时无法读取文章", "请确认编辑功能已合并到 main，或稍后重试。", BACK), []

        try:
            values = read_form(env)
        except InvalidArticle as error:
            return 400, self.page("无法读取表单", str(error), ARTICLES_LINK), []
        supplied = values.get("csrf", "")
        ticket = values.get("ticket", "")
        origin = env.get("HTTP_ORIGIN")
        same_origin = origin == self.origin or (origin in (None, "null") and env.get("HTTP_SEC_FETCH_SITE") == "same-origin")
        if (not same_origin or not TOKEN.fullmatch(supplied)
                or not hmac.compare_digest(csrf, supplied) or not TOKEN.fullmatch(ticket)
                or self.tickets.read(ticket) != csrf):
            return 403, self.page("编辑请求无效", "请在同一个浏览器重新打开后台文章页。", BACK), []
        base = values.get("base", "")
        if base and not valid_sha(base):
            return 400, self.page("文章版本无效", "请从文章列表重新打开。", ARTICLES_LINK), []
        try:
            article = article_from_form(values)
        except InvalidArticle as error:
            return self._form(values, csrf, status=422, message=str(error), ticket=ticket)
        if path == "/admin/article/preview":
            return self._form(values, csrf, extra=preview(article), ticket=ticket)
        if self.tickets.read(ticket, consume=True) != csrf:
            return 409, self.page("这次提交已处理", "请先在 GitHub 查看是否已经创建 PR。", ARTICLES_LINK), []
        try:
            number = self.publisher.publish(article, base)
        except ArticleUnchanged:
            return self._form(values, csrf, status=422, message="文章没有改动，所以没有创建 PR。")
        except ArticleConflict:
            return self._form(values, csrf, status=409, message="文章已更新，或这个网址已存在。请保留你的文字并重新打开最新版本。")
        except PublishInterrupted as error:
            LOG.warning("Article editor write interrupted: stage=%s reason=%s branch=%s",
                        error.stage, error.reason, error.branch)
            return self._form(values, csrf, status=502, message=f"请先到 GitHub 检查 {error.branch} 分支是否已有提交或 PR，再决定是否重试。")
        except RepositoryError as error:
            LOG.warning("Article editor publish failed: %s", error)
            return self._form(values, csrf, status=502, message="未能准备文章 PR，本次文字仍保留在下面。请检查 GitHub 配置或网络后再试。")
        action = f'<a class="button" href="https://github.com/{REPOSITORY}/pull/{number}">在 GitHub 查看 PR #{number}</a>'
        return 201, self.page("文章 PR 已创建", "这篇文章还没有上线。请在 GitHub 审阅并合并，之后会自动部署。",
                              action + ARTICLES_LINK), []
