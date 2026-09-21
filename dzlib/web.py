"""在线取本：直接抓网页正文，不落地电子书文件。

两类来源：
    --ctext <slug>   中国哲学书电子化计划（公版古籍），按书的目录逐章抓取后合并
    --web <url>      任意网页文章，用「文本长度 × (1-链接密度)」挑出正文块

为什么要单独一层：`fetch.py` 只认纯文本，而网页给的是 HTML。
ctext 更极端——中文被整体转成 `&#x..;` 实体，直接当纯文本读会得到一堆编码，
所以必须走 HTMLParser 解码后再取正文。

两条实测得出的规矩（别改回去）：
1. ctext 的**卷级页面本身就含正文**（卷六页里有神思全篇）。若把「卷」和「章」都抓，
   内容会整块重复。所以按 `^卷[一二三…]+$` 把卷标记过滤掉，只抓叶子章。
2. ctext 正文在 `<td class="ctext">`；同一行还有个 `<td class="ctext opt">` 是章节标签，
   必须靠 class 分词排除，否则会把标签当正文。
"""
import html
import re
from html.parser import HTMLParser

from .fetch import FetchError, get

CTEXT_BASE = "https://ctext.org"
CTEXT_LICENSE = "ctext.org（中国哲学书电子化计划）公版古籍原文，引用请注明来源"

DROP_TAGS = {
    "script", "style", "nav", "header", "footer", "aside", "form", "noscript",
    "svg", "iframe", "button", "select", "option", "template", "canvas", "map",
}
HEAD_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
BREAK_TAGS = {
    "p", "div", "section", "article", "blockquote", "pre", "tr", "ul", "ol",
    "dl", "dt", "dd", "figure", "figcaption", "table", "tbody", "thead", "hr",
    "main", "li", "td", "th",
}
VOID_TAGS = {
    "br", "img", "hr", "meta", "link", "input", "source", "track", "wbr",
    "area", "base", "col", "embed", "param",
}
# 这几个空标签本身就是换行信号。不处理的话，用 <br><br> 分段的老式页面
# （Paul Graham 这类）会整篇黏成一段——实测踩到过。
LINE_BREAK_TAGS = {"br", "hr"}
# 正文候选容器，权重按「越像正文越优先」排
CAND_TAGS = {"article": 1.35, "main": 1.30, "section": 1.08, "div": 1.0, "td": 0.95, "body": 0.7}
MIN_BLOCK = 200          # 正文块至少这么多字，低于这个值不参与竞选
MAX_LINK_RATIO = 0.6     # 链接文字占比超过这个值，判定为导航区而非正文
VOLUME_RE = re.compile(r"^卷[一二三四五六七八九十百千]+$")
TD_RE = re.compile(r"<td([^>]*)>([\s\S]*?)</td>", re.I)
# 网页上反复出现、但不属于正文的独立短行
CHROME_LINES = {
    "home", "about", "contact", "login", "log in", "sign in", "sign up", "register",
    "subscribe", "newsletter", "share", "comment", "comments", "rss", "privacy",
    "terms", "copyright", "menu", "search", "next", "previous", "more", "read more",
    "首页", "登录", "注册", "关于", "关于我们", "联系我们", "菜单", "搜索", "分享",
    "评论", "更多", "返回", "上一篇", "下一篇", "阅读全文", "版权所有", "免责声明",
}


class _Node:
    __slots__ = ("tag", "attrs", "children", "_len", "_link")

    def __init__(self, tag, attrs):
        self.tag = tag
        self.attrs = attrs
        self.children = []
        self._len = None
        self._link = None


class _Tree(HTMLParser):
    """把 HTML 变成一棵最小树。只用标准库，不引 bs4/lxml。"""

    def __init__(self):
        super().__init__(convert_charrefs=True)  # 关键：把 &#x..; 实体一并解掉
        self.root = _Node("root", {})
        self.stack = [self.root]
        self.skip = []

    def handle_starttag(self, tag, attrs):
        if tag in DROP_TAGS:
            self.skip.append(tag)
            return
        if self.skip:
            return
        if tag in LINE_BREAK_TAGS:
            self.stack[-1].children.append("\n")
            return
        node = _Node(tag, dict(attrs))
        self.stack[-1].children.append(node)
        if tag not in VOID_TAGS:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        if self.skip or tag in DROP_TAGS:
            return
        if tag in LINE_BREAK_TAGS:
            self.stack[-1].children.append("\n")
            return
        self.stack[-1].children.append(_Node(tag, dict(attrs)))

    def handle_endtag(self, tag):
        if self.skip:
            if tag in DROP_TAGS and self.skip[-1] == tag:
                self.skip.pop()
            return
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                return

    def handle_data(self, data):
        if self.skip or not data.strip():
            return
        self.stack[-1].children.append(data)


def parse(page: str) -> _Node:
    tree = _Tree()
    tree.feed(page)
    tree.close()
    return tree.root


def text_len(node: _Node) -> int:
    if node._len is None:
        node._len = sum(len(c) if isinstance(c, str) else text_len(c) for c in node.children)
    return node._len


def link_len(node: _Node) -> int:
    """节点内落在 <a> 里的文字长度——用来识别导航区。"""
    if node._link is None:
        total = 0
        for c in node.children:
            if isinstance(c, str):
                continue
            total += text_len(c) if c.tag == "a" else link_len(c)
        node._link = total
    return node._link


def pick_main(root: _Node) -> _Node:
    """挑正文块：字数多、链接少、标签像正文的赢。找不到就用整棵树。"""
    best, best_score = None, 0.0
    stack = [root]
    while stack:
        n = stack.pop()
        stack.extend(c for c in n.children if not isinstance(c, str))
        if n.tag not in CAND_TAGS:
            continue
        size = text_len(n)
        if size < MIN_BLOCK:
            continue
        ratio = link_len(n) / max(1, size)
        if ratio > MAX_LINK_RATIO:
            continue
        score = size * (1 - ratio) ** 2 * CAND_TAGS[n.tag]
        if score > best_score:
            best, best_score = n, score
    return best or root


def _inline(node: _Node) -> str:
    out = []
    stack = [node]
    while stack:
        n = stack.pop(0)
        for c in n.children:
            if isinstance(c, str):
                out.append(c)
            elif c.tag not in DROP_TAGS:
                stack.append(c)
    return re.sub(r"\s+", " ", "".join(out)).strip()


def _render(node: _Node, parts: list) -> None:
    for c in node.children:
        if isinstance(c, str):
            parts.append(c)
            continue
        if c.tag in DROP_TAGS:
            continue
        if c.tag in HEAD_TAGS:
            head = _inline(c)
            if head:
                parts.append(f"\n\n## {head}\n\n")
        elif c.tag == "li":
            item = _inline(c)
            if item:
                parts.append(f"\n- {item}\n")
        elif c.tag in BREAK_TAGS:
            parts.append("\n")
            _render(c, parts)
            parts.append("\n")
        else:
            _render(c, parts)


INLINE_JUNK_RE = re.compile(r"\[(?:编辑|編輯|edit|note\s*\d*|\d+)\]", re.I)


def tidy(text: str) -> str:
    """整理空白，并清掉导航残渣。

    这里**不做长度过滤**。早先按「少于 12 字就丢」写过一版，实测把 Paul Graham
    开头的 `July 2023` 这类正常短行也丢了——对一个承诺「每条结论可回查原文」的
    工具来说，静默丢正文比留一点噪声坏得多。改成对着已知的导航词精确清理。
    """
    text = INLINE_JUNK_RE.sub("", text)
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    kept = []
    for line in (l.strip() for l in text.split("\n")):
        if not line:
            kept.append("")
        elif line.startswith(("## ", "- ")):
            kept.append(line)
        elif line.strip("·—·|/").lower() in CHROME_LINES:
            continue
        else:
            kept.append(line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip()


def html_to_text(page: str, tidy_output: bool = True) -> str:
    parts = []
    _render(pick_main(parse(page)), parts)
    text = "".join(parts)
    return tidy(text) if tidy_output else text


def page_title(page: str) -> str:
    m = re.search(r"<title[^>]*>([\s\S]*?)</title>", page, re.I)
    if not m:
        return ""
    title = _strip_tags(m.group(1))
    return re.split(r"\s+[-–|:]\s+", title)[0].strip() or title


def _strip_tags(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", s))).strip()


# ---------------------------------------------------------------- 通用网页

def fetch_web(url: str) -> dict:
    page = get(url)
    return {
        "title": page_title(page) or url.rsplit("/", 1)[-1] or url,
        "author": "",
        "source": url,
        "license": "网页原文，版权归原站所有；蒸馏产物仅作个人学习用",
        "text": html_to_text(page),
    }


# ---------------------------------------------------------------- ctext

def fetch_ctext(slug: str, limit: int = 0) -> dict:
    """按 ctext 书的目录逐章抓取，合并成一份带 `## 章名` 的正文。"""
    index_url = f"{CTEXT_BASE}/{slug}/zh"
    page = get(index_url)
    toc = _ctext_toc(page, slug)
    if not toc:
        raise FetchError(f"在 {index_url} 没找到章节列表，slug 可能不对")
    if limit:
        toc = toc[:limit]

    chunks, done = [], []
    for name, rel in toc:
        try:
            body = _ctext_body(get(f"{CTEXT_BASE}/{rel}"))
        except FetchError:
            continue
        if not body:
            continue
        chunks.append(f"## {name}\n\n{body}")
        done.append(name)

    if not chunks:
        raise FetchError(f"{slug} 的章节页都没抓到正文")

    return {
        "title": _ctext_book_title(page) or slug,
        "author": "",
        "source": index_url,
        "license": CTEXT_LICENSE,
        "text": "\n\n".join(chunks),
        "chapters_fetched": len(done),
        "chapters_listed": len(toc),
    }


def _ctext_toc(page: str, slug: str) -> list:
    """返回 [(章名, 相对地址)]，按书上顺序。卷级页要跳过——它含子章正文，会重复。"""
    pattern = re.compile(
        r'<a[^>]*class="menuitem"[^>]*href="(' + re.escape(slug) + r'/[^"]+)"[^>]*>([^<]*)</a>',
        re.I,
    )
    self_link = f"{slug}/zh"  # 指向书本身的链接也会命中，它不是章
    out, seen = [], set()
    for m in pattern.finditer(page):
        href, name = m.group(1), html.unescape(m.group(2)).strip()
        if not name or VOLUME_RE.match(name):
            continue
        rel = href if href.endswith("/zh") else href.rstrip("/") + "/zh"
        if rel == self_link or rel in seen:
            continue
        seen.add(rel)
        out.append((name, rel))
    return out


def _ctext_body(page: str) -> str:
    """取 `<td class="ctext">` 的正文，排除 `<td class="ctext opt">` 这种章节标签。"""
    paras = []
    for m in TD_RE.finditer(page):
        classes = re.search(r'class="([^"]*)"', m.group(1))
        if not classes:
            continue
        names = classes.group(1).split()
        if "ctext" not in names or "opt" in names:
            continue
        text = _strip_tags(m.group(2))
        if text:
            paras.append(text)
    return "\n".join(paras)


def _ctext_book_title(page: str) -> str:
    # 索引页 <title> 是「书名 - 中國哲學書電子化計劃」，page_title 会切出书名
    title = page_title(page)
    if title and "中國哲學書" not in title:
        return title
    m = re.search(r'<meta name="ctp-urn"[^>]*content="ctp:([^"]+)"', page)
    return m.group(1) if m else title
