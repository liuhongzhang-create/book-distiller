"""取书：公版书（Project Gutenberg / 维基文库）+ 任意 URL。

不接盗版站。图书馆（国图/世图）的受版权保护馆藏拿不到全文，只能查目录——
这一点在 README 里写清楚了，工具不假装能取。
"""
import gzip
import io
import re
import urllib.error
import urllib.request

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) distill-workshop/0.1"

GUTENBERG_TXT = "https://www.gutenberg.org/cache/epub/{eid}/pg{eid}.txt"
WIKISOURCE_RAW = "https://zh.wikisource.org/w/index.php?title={title}&action=raw"


class FetchError(RuntimeError):
    pass


def _opener(use_proxy: bool):
    handlers = []
    if not use_proxy:
        handlers.append(urllib.request.ProxyHandler({}))
    return urllib.request.build_opener(*handlers)


def get(url: str, timeout: int = 30) -> str:
    """先按环境代理取，失败再直连。返回解码后的文本。"""
    last = None
    for use_proxy in (True, False):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with _opener(use_proxy).open(req, timeout=timeout) as resp:
                raw = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                return _decode(raw)
        except Exception as exc:  # noqa: BLE001 - 两种通道都要试，错误留给调用方
            last = exc
    raise FetchError(f"取不到 {url}：{last}")


def _decode(raw: bytes) -> str:
    for enc in ("utf-8", "gb18030", "big5", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def fetch_gutenberg(ebook_id: int) -> dict:
    url = GUTENBERG_TXT.format(eid=ebook_id)
    text = get(url)
    title = _gutenberg_title(text) or f"Gutenberg #{ebook_id}"
    return {
        "title": title,
        "author": _gutenberg_author(text) or "",
        "source": url,
        "license": "Project Gutenberg（公版，美国境内外多数地区可自由使用）",
        "text": text,
    }


def fetch_wikisource(page_title: str) -> dict:
    from urllib.parse import quote

    url = WIKISOURCE_RAW.format(title=quote(page_title))
    text = get(url)
    title = _wiki_field(text, "title") or page_title
    return {
        "title": title,
        "author": _wiki_field(text, "author") or "",
        "source": url,
        "license": "维基文库（CC BY-SA / 公版原文，引用需注明来源）",
        "text": text,
    }


def fetch_url(url: str) -> dict:
    text = get(url)
    return {"title": url.rsplit("/", 1)[-1] or url, "author": "", "source": url, "license": "", "text": text}


def _gutenberg_title(text: str) -> str:
    m = re.search(r"^Title:\s*(.+)$", text, re.M)
    if m:
        return m.group(1).strip()
    m = re.search(r"The Project Gutenberg eBook of (.+?)\s*$", text, re.M)
    return m.group(1).strip() if m else ""


def _gutenberg_author(text: str) -> str:
    m = re.search(r"^Author:\s*(.+)$", text, re.M)
    return m.group(1).strip() if m else ""


def _wiki_field(text: str, field: str) -> str:
    m = re.search(rf"^\|\s*{field}\s*=\s*(.+?)\s*$", text, re.M)
    return m.group(1).strip() if m else ""


def strip_gutenberg_boilerplate(text: str) -> str:
    """去掉 Gutenberg 的法律声明头尾。"""
    start = re.search(r"\*\*\*\s*START OF (?:THE|THIS) PROJECT GUTENBERG.*?\*\*\*", text)
    end = re.search(r"\*\*\*\s*END OF (?:THE|THIS) PROJECT GUTENBERG.*?\*\*\*", text)
    if start:
        text = text[start.end():]
    if end:
        text = text[: end.start()]
    return text.strip()


def save_raw(out_dir, name: str, text: str):
    from pathlib import Path

    out = Path(out_dir) / "raw"
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{name}.txt"
    path.write_text(text, encoding="utf-8")
    return path
