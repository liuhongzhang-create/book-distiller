"""压缩：把整本书压成 AI 能一次读完、且每条都能回查的材料包。

这是省钱的关键一步。十万字的书不压缩直接喂，成本高、还容易漏章；
先用纯 Python 做提取式压缩（选出最像「方法论」的句子），
AI 只需要在几千字的材料上做提炼，输出质量反而更稳。
"""
import json
from collections import Counter
from pathlib import Path

from . import text as T
from .ingest import Book, split_paragraphs


SCALE_PER = 1000  # 每 1000 字正文，按 per_chapter 的密度给一份额度


def sentence_budget(chars: int, per_chapter: int, max_per_chapter: int) -> int:
    """这一章该抽几句。

    早先写死 k=per_chapter，导致「一本 6 万字的单章文档只抽 12 句」——
    网页长文和单章书都会被抽得只剩骨架，提炼出来必然失真。截图实测过：
    Paul Graham 长文 66,956 字 / 1 章，只出 12 句。

    所以按章长缩放，并给一个上限兜住 token 成本：
      文心雕龍 单章 ≈950 字 → 12 句（与旧行为一致，不回归）
      单章长文 66,000 字 → 触到上限
    """
    scaled = round(chars / SCALE_PER * per_chapter)
    return max(per_chapter, min(max_per_chapter, scaled))


def _excluded(ch, exclude) -> bool:
    if not exclude:
        return False
    idx_token = f"c{ch.idx:02d}"
    for rule in exclude:
        rule = str(rule).strip()
        if not rule:
            continue
        if rule.lower() == idx_token or rule == str(ch.idx):
            return True
        if rule in ch.title:
            return True
    return False


def condense(book: Book, work_dir, per_chapter: int = 12, full: bool = False,
             exclude=None, max_per_chapter: int = 100) -> dict:
    """exclude：要跳过的章节，按「标题包含」或「c15」这种编号写法匹配（附录、答话、译注常需要跳过）。"""
    work = Path(work_dir)
    prep = work / "prep"
    prep.mkdir(parents=True, exist_ok=True)

    book_tf = T.term_freq("\n".join(c.text for c in book.chapters))
    overview_rows = []
    written = []
    skipped = []

    for ch in book.chapters:
        if _excluded(ch, exclude):
            skipped.append(f"c{ch.idx:02d} {ch.title}")
            continue
        paras = split_paragraphs(ch.text)
        ids = [f"c{ch.idx:02d}p{i:03d}" for i in range(len(paras))]
        sentences = []
        for pid, para in zip(ids, paras):
            for s in T.iter_sentences(para):
                sentences.append((pid, s))

        flat = [s for _, s in sentences]
        budget = sentence_budget(len(ch.text), per_chapter, max_per_chapter)
        ordered = [(sentences[i][0], s) for i, s in T.pick_key_sentences(flat, book_tf, k=budget)]

        terms = T.top_terms(ch.text, k=8, min_count=2)
        body = [f"# c{ch.idx:02d} · {ch.title}", ""]
        body.append(f"字数 {len(ch.text):,} · 段落 {len(paras)} · 关键句额度 {budget}")
        if terms:
            body.append("关键词 " + " ".join(f"{w}({c})" for w, c in terms))
        body.append("")
        body.append("## 关键句（按原文顺序，方括号是段落 ID，引用时必须用它）")
        if ordered:
            body.extend(f"- [{pid}] {T.clip(s, 300)}" for pid, s in ordered)
        else:
            body.append("- （本章未提取到合格句子）")

        if full:
            body.append("")
            body.append("## 全文（--full 模式）")
            for pid, para in zip(ids, paras):
                body.append(f"[{pid}] {para}")

        path = prep / f"c{ch.idx:02d}.md"
        path.write_text("\n".join(body) + "\n", encoding="utf-8")
        written.append(path)
        overview_rows.append({
            "idx": ch.idx,
            "title": ch.title,
            "chars": len(ch.text),
            "paras": len(paras),
            "terms": [w for w, _ in terms[:5]],
        })

    stats = book.stats()
    top = T.top_terms("\n".join(c.text for c in book.chapters), k=30, min_count=3)
    overview = [
        f"# 材料包总览 · {book.title}",
        "",
        f"- 作者：{book.author or '（未标注）'}",
        f"- 来源：{book.source}",
        f"- 授权：{book.license or '（未标注）'}",
        f"- 规模：{stats['chapters']} 章 / {stats['chars']:,} 字 / {stats['paragraphs']} 段",
        f"- 生成日期：{book.created}",
        f"- 已跳过：{'、'.join(skipped)}" if skipped else "- 已跳过：无",
        "",
        "## 全书高频词（用来判断本书真正的核心概念）",
        "",
        "　".join(f"{w}({c})" for w, c in top) or "（无）",
        "",
        "## 章节一览",
        "",
        "| 章 | 标题 | 字数 | 段落 | 本章关键词 | 明细文件 |",
        "|---|---|---|---|---|---|",
    ]
    for row in overview_rows:
        overview.append(
            f"| c{row['idx']:02d} | {row['title']} | {row['chars']:,} | {row['paras']} "
            f"| {'、'.join(row['terms']) or '—'} | `prep/c{row['idx']:02d}.md` |"
        )
    overview += [
        "",
        "## 使用方法（给 AI）",
        "",
        "1. 先读本文件，形成全书地图。",
        "2. 再按需要读 `prep/cXX.md`，拿到带段落 ID 的关键句。",
        "3. 提炼出的每条结论必须挂方括号里的段落 ID，例如 `[c03p002]`。",
        "4. 段落 ID 可用 `dz.py show <workdir> <id>` 回查原文，也可在 `index.json` 中检索。",
        "",
    ]
    (prep / "00-overview.md").write_text("\n".join(overview), encoding="utf-8")

    meta = {
        "book": book.title,
        "chapters": stats["chapters"],
        "chars": stats["chars"],
        "paragraphs": stats["paragraphs"],
        "prep_files": [p.name for p in written],
        "top_terms": top,
        "full_text_included": full,
        "skipped": skipped,
        "per_chapter": per_chapter,
        "max_per_chapter": max_per_chapter,
    }
    (work / "prep" / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return meta
