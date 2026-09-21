"""载入与标准化：任意来源 → Book（章 + 段落 + 可回查的段落 ID）。

段落 ID 格式 `c03p012`：第 3 章第 12 段。
提炼出来的每一句结论都要挂这个 ID，verify 负责检查它能不能解析回原文。
"""
import html
import re
import zipfile
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path

from . import text as T

HEAD_PATTERNS = [
    re.compile(r"^==\s*(.+?)\s*==\s*$"),                                  # 维基文库
    re.compile(r"^#{1,3}\s+(.+?)\s*#*\s*$"),                              # markdown
    re.compile(r"^(第[一二三四五六七八九十百千零〇\d]{1,6}[章回節节篇卷部][^\n]{0,30})$"),
    # 英文书的章节标题：CHAPTER/Chapter + 罗马或阿拉伯数字，标题可有可无。
    # 限制标题部分不含句点，避免把小写开头的普通句子（"Chapter 1 is about..."）误当标题。
    re.compile(r"^(chapter\s+[IVXLC\d]{1,6}\.?(?:\s+[^\n.]{1,60})?)$", re.I),
]
MIN_CHAPTERS = 2
TOC_MIN_RUN = 3        # 连续多少个紧邻标题才判为目录
TOC_MAX_GAP = 1        # 相邻标题的行距 <= 此值算「紧邻」
TOC_ENTRY_MAX = 300    # 目录条目的正文长度上限（超过就不像目录）
BOILERPLATE = re.compile(r"^\s*(?:\[?\d+\]?|Page \d+|p\.\s*\d+)\s*$", re.I)


@dataclass
class Chapter:
    idx: int
    title: str
    text: str


@dataclass
class Book:
    title: str = ""
    author: str = ""
    source: str = ""
    license: str = ""
    chapters: list = field(default_factory=list)
    created: str = ""

    def paragraphs(self):
        """产出 (段落ID, 章序号, 章标题, 段落正文)。"""
        for ch in self.chapters:
            for pi, para in enumerate(split_paragraphs(ch.text)):
                yield f"c{ch.idx:02d}p{pi:03d}", ch.idx, ch.title, para

    def index(self):
        return {
            pid: {"chapter": ci, "chapter_title": ct, "text": T.clip(p, 400)}
            for pid, ci, ct, p in self.paragraphs()
        }

    def stats(self):
        total = sum(len(c.text) for c in self.chapters)
        return {
            "chapters": len(self.chapters),
            "chars": total,
            "paragraphs": sum(1 for _ in self.paragraphs()),
        }

    def to_json(self):
        data = asdict(self)
        data["created"] = self.created or datetime.now().strftime("%Y-%m-%d")
        return data

    @classmethod
    def from_json(cls, data):
        book = cls(
            title=data.get("title", ""),
            author=data.get("author", ""),
            source=data.get("source", ""),
            license=data.get("license", ""),
            created=data.get("created", ""),
        )
        book.chapters = [Chapter(**c) for c in data.get("chapters", [])]
        return book


def split_paragraphs(text: str) -> list:
    paras = []
    for raw in text.split("\n"):
        line = raw.strip()
        if not line or BOILERPLATE.match(line):
            continue
        paras.append(line)
    return paras


def _body_len(marks: list, i: int, lines: list) -> int:
    end = marks[i + 1][0] if i + 1 < len(marks) else len(lines)
    return len("\n".join(lines[marks[i][0] + 1 : end]).strip())


def _toc_drop_indexes(marks: list, lines: list) -> set:
    """找出目录区，返回要丢弃的 marks 下标。

    目录页的特征是十几个章标题**紧挨着**排列（中间几乎没正文），而正文里
    章节标题之间必定隔着大段内容。所以「紧邻」是区分二者的可靠信号；
    再加一道「条目正文都极短」的复核，避免误伤标题连续排布的诗集之类。
    """
    drop = set()
    i = 0
    while i < len(marks):
        j = i
        while j + 1 < len(marks) and marks[j + 1][0] - marks[j][0] <= TOC_MAX_GAP:
            j += 1
        run = list(range(i, j + 1))
        # 只复核 run[:-1]：run 的最后一项可能吞掉紧随目录之后的导论/前言正文
        if len(run) >= TOC_MIN_RUN and all(
            _body_len(marks, k, lines) <= TOC_ENTRY_MAX for k in run[:-1]
        ):
            drop.update(run)
        i = j + 1
    return drop


def split_chapters(text: str) -> list:
    """按标题切章。找不到标题就整本作一章。"""
    lines = text.split("\n")
    marks = []
    for line_no, line in enumerate(lines):
        s = line.strip()
        if not s or len(s) > 80:
            continue
        for pat in HEAD_PATTERNS:
            m = pat.match(s)
            if m:
                marks.append((line_no, m.group(1).strip()))
                break

    toc = _toc_drop_indexes(marks, lines)
    if toc:
        marks = [m for k, m in enumerate(marks) if k not in toc]

    if len(marks) < MIN_CHAPTERS:
        body = "\n".join(lines).strip()
        return [Chapter(idx=1, title="正文", text=body)] if body else []

    chapters = []
    head = "\n".join(lines[: marks[0][0]]).strip()
    if head:
        chapters.append(Chapter(idx=1, title="前言", text=head))
    for i, (line_no, title) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(lines)
        body = "\n".join(lines[line_no + 1 : end]).strip()
        body = re.sub(r"^[=\-#*\s]+$", "", body, flags=re.M).strip()
        chapters.append(Chapter(idx=len(chapters) + 1, title=title, text=body))
    return [c for c in chapters if c.text.strip()]


def build(title="", author="", source="", license="", text="") -> Book:
    return Book(
        title=title,
        author=author,
        source=source,
        license=license,
        chapters=split_chapters(T.clean(text)),
        created=datetime.now().strftime("%Y-%m-%d"),
    )


def from_text_file(path) -> Book:
    path = Path(path)
    raw = path.read_text(encoding="utf-8", errors="replace")
    name = path.stem
    title = name
    for line in raw.split("\n")[:20]:
        s = line.strip()
        if s and not s.startswith("***") and len(s) < 60:
            title = s
            break
    return build(title=title, source=str(path), text=raw)


def from_epub(path) -> Book:
    path = Path(path)
    with zipfile.ZipFile(path) as zf:
        order = _epub_spine(zf)
        chunks = []
        for href in order:
            try:
                raw = zf.read(href)
            except KeyError:
                continue
            chunks.append(_html_to_text(raw))
    text = "\n\n".join(c for c in chunks if c.strip())
    title = path.stem
    meta = _epub_meta(path)
    return build(title=meta.get("title") or title, author=meta.get("creator", ""), source=str(path), text=text)


def _epub_spine(zf) -> list:
    try:
        container = zf.read("META-INF/container.xml").decode("utf-8", "replace")
    except KeyError:
        return [n for n in zf.namelist() if n.lower().endswith((".xhtml", ".html", ".htm"))]
    m = re.search(r'full-path="([^"]+)"', container)
    if not m:
        return []
    opf_path = m.group(1)
    base = opf_path.rsplit("/", 1)[0] + "/" if "/" in opf_path else ""
    opf = zf.read(opf_path).decode("utf-8", "replace")

    manifest = dict(re.findall(r'<item\b[^>]*\bid="([^"]+)"[^>]*\bhref="([^"]+)"', opf))
    manifest.update({i: h for h, i in re.findall(r'<item\b[^>]*\bhref="([^"]+)"[^>]*\bid="([^"]+)"', opf)})
    spine = re.findall(r'<itemref\b[^>]*\bidref="([^"]+)"', opf)

    order = []
    for idref in spine:
        href = manifest.get(idref)
        if href:
            order.append(base + href)
    return order or [n for n in zf.namelist() if n.lower().endswith((".xhtml", ".html", ".htm"))]


def _epub_meta(path) -> dict:
    with zipfile.ZipFile(path) as zf:
        try:
            container = zf.read("META-INF/container.xml").decode("utf-8", "replace")
            opf_path = re.search(r'full-path="([^"]+)"', container).group(1)
            opf = zf.read(opf_path).decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            return {}
    out = {}
    for tag, key in (("dc:title", "title"), ("dc:creator", "creator")):
        m = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", opf, re.S | re.I)
        if m:
            out[key] = html.unescape(re.sub(r"<[^>]+>", "", m.group(1))).strip()
    return out


def _html_to_text(raw: bytes) -> str:
    s = raw.decode("utf-8", "replace")
    s = re.sub(r"<(script|style)\b.*?</\1>", " ", s, flags=re.S | re.I)
    s = re.sub(r"<br\s*/?>|</p>|</div>|</h[1-6]>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    return html.unescape(s)


def from_pdf(path) -> Book:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError(
            "读 PDF 需要 pypdf（唯一的可选依赖）。装法：\n"
            "  python3 -m pip install pypdf\n"
            "或者先把 PDF 另存为文本/EPUB 再喂进来。"
        ) from exc
    path = Path(path)
    reader = PdfReader(str(path))
    pages = [(pg.extract_text() or "") for pg in reader.pages]
    text = "\n\n".join(pages)
    return build(title=path.stem, source=str(path), text=text)


LOADERS = {".txt": from_text_file, ".text": from_text_file, ".md": from_text_file,
           ".markdown": from_text_file, ".epub": from_epub, ".pdf": from_pdf}


def load(path) -> Book:
    path = Path(path)
    loader = LOADERS.get(path.suffix.lower())
    if not loader:
        raise RuntimeError(f"暂不支持 {path.suffix}。支持：{', '.join(sorted(LOADERS))}")
    return loader(path)


def save(book: Book, work_dir) -> Path:
    import json

    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)
    path = work / "book.json"
    path.write_text(json.dumps(book.to_json(), ensure_ascii=False, indent=2), encoding="utf-8")
    (work / "index.json").write_text(
        json.dumps(book.index(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return path


def load_work(work_dir) -> Book:
    import json

    data = json.loads((Path(work_dir) / "book.json").read_text(encoding="utf-8"))
    return Book.from_json(data)
