"""文本处理：清洗 / 去 wiki 标记 / 分句 / 无分词器的中文关键词提取 / 关键句打分。

为什么不用 jieba：保持零依赖，装不上就不会有人用。
中文没有分词器时，用「汉字二元组 + 停用字过滤」做关键词提取，
在方法论类书籍上的效果足够——这类书的关键词本来就高度重复（原则、判断、成本、用户...）。
"""
import re
import math
from collections import Counter

CJK_BLOCK = r"\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"
CJK_RE = re.compile(rf"[{CJK_BLOCK}]+")
LATIN_RE = re.compile(r"[A-Za-z][A-Za-z'\-]{2,}")
SENT_END = "。！？!?；;…"
WIKI_FILE_RE = re.compile(r"\[\[(?:File|Image|文件|檔案|图像):[^\]]*\]\]", re.I)
WIKI_LINK_RE = re.compile(r"\[\[(?:[^\]|]*\|)?([^\]|]*)\]\]")
WIKI_TAG_RE = re.compile(r"<[^>]{1,80}>")

STOP_ZH = set(
    "的了和是在有就不人都一个上也很到说要去你会着没看好自己这那我们他们什么"
    "可以但因为所以如果虽然然后还是只被把从对与及等使能需又再更最而以为之其"
    "此于乎者亦且则乃矣焉耳哉于是可于"
    # 古籍里的对话衬字，留着会让高频词变成「武曰」「王問」这类噪声
    "曰問吾何敢應對請願謂蓋夫唯唯"
)
STOP_EN = set(
    "the a an and or of to in is are was were be been being it its this that these "
    "those for with as by on at from not but if then than so such which who whom "
    "whose what when where how can could may might must should would will shall do "
    "does did done have has had there here they them their you your we our he she "
    "his her him i me my one two also more most very much many some any all other "
    "into over out up down only just now then than about after before while during "
    "against because through between under above again further once same own too"
)

MODEL_SIGNAL_ZH = (
    "本质", "原则", "关键", "必须", "不要", "绝不能", "误区", "错误", "正确",
    "就是", "指的是", "意味着", "方法是", "第一步", "其次", "最后", "因此",
    "判断", "标准", "条件", "前提", "只要", "只有", "凡是", "不能", "应当",
)
MODEL_SIGNAL_EN = (
    "principle", "the key", "must", "never", "always", "mistake", "means",
    "the point", "because", "should", "foundation", "rule", "test", "avoid",
)


def clean(text: str) -> str:
    """统一换行、去掉零宽字符与多余空行。"""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\u200b", "").replace("\ufeff", "")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def strip_templates(text: str) -> str:
    """去掉 {{...}} 模板，支持嵌套（维基的 header 里常嵌 wikipedia 模板）。

    `\\{\\{[^{}]*\\}\\}` 这种正则遇到嵌套就整块匹配不上，会把模板原样留在正文里——
    这正是实测踩到的坑：前言章节变成一堆 `|title=...` 的模板碎片。
    这里用花括号计数逐字符扫描，从内到外可重复清理。
    """
    out = []
    depth = 0
    i = 0
    n = len(text)
    while i < n:
        if text.startswith("{{", i):
            depth += 1
            i += 2
            continue
        if text.startswith("}}", i) and depth > 0:
            depth -= 1
            i += 2
            continue
        if depth == 0:
            out.append(text[i])
        i += 1
    return "".join(out)


def strip_wiki(text: str) -> str:
    """去掉维基标记，留下可读正文。"""
    text = WIKI_FILE_RE.sub("", text)
    text = WIKI_LINK_RE.sub(r"\1", text)
    for _ in range(3):  # 模板去掉后可能露出新的嵌套模板
        new = strip_templates(text)
        if new == text:
            break
        text = new
    text = WIKI_TAG_RE.sub("", text)
    text = re.sub(r"^[_\-=*]{4,}\s*$", "", text, flags=re.M)
    text = re.sub(r"'{2,}", "", text)
    return text


def has_cjk(text: str) -> bool:
    return bool(CJK_RE.search(text))


def tokens(text: str) -> list:
    """关键词 token：拉丁词 + 汉字二元组（过滤停用字）。"""
    out = []
    for w in LATIN_RE.findall(text):
        w = w.lower()
        if w not in STOP_EN:
            out.append(w)
    for run in CJK_RE.findall(text):
        chars = [c for c in run if c not in STOP_ZH]
        out.extend(a + b for a, b in zip(chars, chars[1:]))
    return out


def term_freq(text: str) -> Counter:
    return Counter(tokens(text))


def top_terms(text: str, k: int = 10, min_count: int = 2) -> list:
    """返回 [(词, 次数)]，按次数降序。"""
    counter = term_freq(text)
    items = [(w, c) for w, c in counter.most_common() if c >= min_count]
    return items[:k]


def iter_sentences(text: str, min_len: int = 8) -> list:
    """中英混排分句。中文按句末标点，拉丁文按句点。"""
    out = []
    for para in text.split("\n"):
        para = para.strip()
        if not para:
            continue
        if re.match(r"^[#=\-*>\s|]*$", para):
            continue
        cur = ""
        for ch in para:
            cur += ch
            if ch in SENT_END:
                _push(out, cur, min_len)
                cur = ""
        _push(out, cur, min_len)
    return out


def _push(out: list, raw: str, min_len: int) -> None:
    s = raw.strip()
    if len(s) < min_len:
        return
    if len(s) > 180 and not has_cjk(s):
        parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+", s) if p.strip()]
        out.extend(p for p in parts if len(p) >= min_len)
        return
    out.append(s)


def _signal_bonus(sentence: str) -> float:
    if has_cjk(sentence):
        hits = sum(1 for w in MODEL_SIGNAL_ZH if w in sentence)
    else:
        low = sentence.lower()
        hits = sum(1 for w in MODEL_SIGNAL_EN if w in low)
    return min(hits, 3) * 0.6


def score_sentences(sentences: list, tf: Counter) -> list:
    """给句子打分：关键词密度 + 方法论信号词 + 位置权重 + 长度惩罚。

    tf 用全书词频（跨章统计），这样「只在某一章反复出现」的概念会被自然压低，
    而全书核心概念会浮现——这是没分词器时最接近 TF-IDF 的替代方案。
    """
    scored = []
    n = len(sentences)
    for i, s in enumerate(sentences):
        toks = tokens(s)
        if not toks:
            continue
        density = sum(math.log1p(tf[t]) for t in toks) / (len(toks) ** 0.8)
        pos = 1.25 if i == 0 else (1.1 if i < max(2, n // 10) else 1.0)
        if i >= n - 2:
            pos += 0.08
        length_penalty = 1.0
        if len(s) < 12:
            length_penalty = 0.5
        elif len(s) > 160:
            length_penalty = 0.85
        scored.append((density * pos * length_penalty + _signal_bonus(s), i, s))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return scored


def pick_key_sentences(sentences: list, tf: Counter, k: int = 10) -> list:
    """挑关键句并按原文顺序返回 [(原序号, 句子)]，避免读起来跳来跳去。"""
    ranked = score_sentences(sentences, tf)[:k]
    ranked.sort(key=lambda x: x[1])
    return [(idx, s) for _, idx, s in ranked]


def clip(text: str, limit: int = 220) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"
