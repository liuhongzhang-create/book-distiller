"""质检：这是「真检查」，不是数关键词。

同类工具的做法是全文搜「局限」「张力」这类词，出现就算过——写几个字就能骗过去。
这里改成结构化检查：
  · 每个引用 ID 必须能在 index.json 里解析（引用不可解析 = 编造）
  · 「核心模型」每个都要有引用且写了失效条件
  · 流程要有判据、清单要可勾选、反例要有出处
  · 覆盖章节比例不够 = 只精读了前几章
"""
import json
import re
from collections import Counter
from pathlib import Path

CITE_RE = re.compile(r"\[(c\d{2}p\d{3})\]")
HEAD_RE = re.compile(r"^##\s+(.+?)\s*$", re.M)
SUBHEAD_RE = re.compile(r"^###\s+(.+?)\s*$", re.M)
FAIL_RE = re.compile(r"只写优点|全部|所有|永远|一定|绝不")

DEFAULT_MIN_CITATIONS = 12
DEFAULT_MIN_COVERAGE = 0.6


def verify(work_dir, skill_name: str = "SKILL.md", min_citations: int = DEFAULT_MIN_CITATIONS,
           min_coverage: float = DEFAULT_MIN_COVERAGE) -> dict:
    from .pack import REQUIRED_SECTIONS

    work = Path(work_dir)
    skill_path = work / skill_name
    results = []

    if not skill_path.exists():
        return _report(work, [("❌", "产物存在", f"找不到 {skill_name}")], {}, min_citations, min_coverage)

    content = skill_path.read_text(encoding="utf-8")
    index = json.loads((work / "index.json").read_text(encoding="utf-8"))
    valid_ids = set(index.keys())
    total_chapters = len({v["chapter"] for v in index.values()})

    sections = {m.group(1).strip(): _section_body(content, m) for m in HEAD_RE.finditer(content)}

    results.append(_frontmatter_check(content))

    missing = [s for s in REQUIRED_SECTIONS if not _find_section(sections, s)]
    if missing:
        results.append(("❌", "结构契约", "缺少章节：" + "、".join(missing)))
    else:
        results.append(("✅", "结构契约", f"{len(REQUIRED_SECTIONS)} 个必填章节齐全"))

    empty = [s for s in REQUIRED_SECTIONS
             if (body := _find_section(sections, s)) and len(re.sub(r"\s|[-|#>]", "", body)) < 20]
    if empty:
        results.append(("⚠️", "章节非空", "内容过短，疑似占位：" + "、".join(empty)))
    elif not missing:
        results.append(("✅", "章节非空", "各节都有实质内容"))

    cites = CITE_RE.findall(content)
    unknown = sorted({c for c in cites if c not in valid_ids})
    if unknown:
        results.append(("❌", "引用可解析", f"{len(unknown)} 个 ID 在原文中不存在：{'、'.join(unknown[:6])}"))
    elif not cites:
        results.append(("❌", "引用可解析", "全文没有任何段落 ID 引用"))
    else:
        results.append(("✅", "引用可解析", f"{len(cites)} 处引用全部能解析回原文"))

    if len(cites) < min_citations:
        results.append(("❌", "引用数量", f"只有 {len(cites)} 处，要求 ≥{min_citations}"))
    else:
        results.append(("✅", "引用数量", f"{len(cites)} 处 ≥ {min_citations}"))

    cited_chapters = {index[c]["chapter"] for c in cites if c in valid_ids}
    coverage = len(cited_chapters) / total_chapters if total_chapters else 0
    if coverage < min_coverage:
        results.append(("❌", "章节覆盖", f"只引用了 {len(cited_chapters)}/{total_chapters} 章（{coverage:.0%}），"
                                         f"要求 ≥{min_coverage:.0%}——可能只精读了开头"))
    else:
        results.append(("✅", "章节覆盖", f"{len(cited_chapters)}/{total_chapters} 章（{coverage:.0%}）"))

    if cites:
        top_share = Counter(cites).most_common(1)[0][1] / len(cites)
        if top_share > 0.4:
            results.append(("⚠️", "引用分布", f"有 {top_share:.0%} 的引用集中在同一段，疑似堆引用凑数"))
        else:
            results.append(("✅", "引用分布", "引用较分散，不是拿一段反复凑"))

    results.extend(_model_checks(sections))
    results.extend(_process_checks(sections))
    results.extend(_list_checks(sections))
    results.extend(_counter_checks(sections))
    results.extend(_boundary_checks(sections))

    return _report(work, results, {"skill": str(skill_path), "chapters": total_chapters,
                                   "citations": len(cites)}, min_citations, min_coverage)


def _find_section(sections: dict, name: str):
    for key, body in sections.items():
        if name in key:
            return body
    return None


def _section_body(content: str, match) -> str:
    rest = content[match.end():]
    nxt = re.search(r"^##\s", rest, re.M)
    return rest[: nxt.start()] if nxt else rest


def _frontmatter_check(content: str):
    m = re.match(r"^---\n(.*?)\n---", content, re.S)
    if not m:
        return ("❌", "frontmatter", "缺少 YAML frontmatter")
    fm = m.group(1)
    need = [k for k in ("name", "description") if not re.search(rf"^{k}\s*:", fm, re.M)]
    if need:
        return ("❌", "frontmatter", "缺字段：" + "、".join(need))
    return ("✅", "frontmatter", "name / description 齐全")


def _model_blocks(body: str) -> list:
    """按 `### ` 切出每个模型的内容块。

    注意：必须切到**下一个** `### ` 为止。早先的写法是 `body[m.end():]`，
    等于每个块都把后面所有模型的内容吞进来——于是「第一个模型没写失效条件」
    永远检不出来（因为后面某个模型写了）。测试就是为了钉住这类错误。
    """
    matches = list(SUBHEAD_RE.finditer(body))
    blocks = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        blocks.append(body[m.end():end])
    return blocks


def _model_checks(sections: dict):
    body = _find_section(sections, "核心模型") or ""
    blocks = _model_blocks(body)
    if not blocks:
        return [("❌", "核心模型", "没有用 `### ` 分出模型条目")]
    out = []
    no_cite = [i + 1 for i, b in enumerate(blocks) if not CITE_RE.search(b)]
    no_limit = [i + 1 for i, b in enumerate(blocks) if not re.search(r"失效|不适用|边界|前提", b)]
    if not 3 <= len(blocks) <= 5:
        out.append(("⚠️", "模型数量", f"{len(blocks)} 个（建议 3–5 个）"))
    else:
        out.append(("✅", "模型数量", f"{len(blocks)} 个"))
    if no_cite:
        out.append(("❌", "模型带引用", f"第 {'、'.join(map(str, no_cite))} 个模型没有原文依据"))
    else:
        out.append(("✅", "模型带引用", "每个模型都有原文依据"))
    if no_limit:
        out.append(("❌", "模型写失效条件",
                    f"第 {'、'.join(map(str, no_limit))} 个模型没写失效条件——只写优点等于没写"))
    else:
        out.append(("✅", "模型写失效条件", "每个模型都写了失效条件"))
    return out


def _process_checks(sections: dict):
    body = _find_section(sections, "可执行流程") or ""
    steps = re.findall(r"^\s*(?:\*\*)?(?:Step\s*\d+|\d+[.、)])", body, re.M)
    judged = len(re.findall(r"判据", body))
    out = []
    if len(steps) >= 3:
        out.append(("✅", "流程步数", f"{len(steps)} 步"))
    else:
        out.append(("❌", "流程步数", f"只有 {len(steps)} 步，要求 ≥3"))
    if judged >= max(3, len(steps) - 1):
        out.append(("✅", "步骤有判据", f"{judged} 处判据"))
    else:
        out.append(("❌", "步骤有判据", f"只有 {judged} 处判据，每步都应给出判断标准"))
    vague = len(FAIL_RE.findall(body))
    if vague:
        out.append(("⚠️", "空话检查", f"出现 {vague} 处「全部/永远/一定」这类绝对表述，建议换成具体条件"))
    else:
        out.append(("✅", "空话检查", "没有绝对化空话"))
    return out


def _list_checks(sections: dict):
    body = _find_section(sections, "判断清单") or ""
    boxes = len(re.findall(r"^\s*[-*]\s*\[[ xX]\]", body, re.M))
    if boxes >= 5:
        return [("✅", "判断清单", f"{boxes} 条可勾选项")]
    bullets = len(re.findall(r"^\s*[-*]\s+\S", body, re.M))
    if bullets >= 5:
        return [("⚠️", "判断清单", f"{bullets} 条，但没用复选框格式，无法直接照着打勾")]
    return [("❌", "判断清单", f"只有 {boxes} 条检查项，要求 ≥5 条")]


def _counter_checks(sections: dict):
    body = _find_section(sections, "反例与失败模式") or ""
    rows = [ln for ln in body.splitlines()
            if ln.strip().startswith("|") and not re.match(r"^\s*\|[-:\s|]+\|\s*$", ln)
            and "错误做法" not in ln]
    with_cite = [r for r in rows if CITE_RE.search(r)]
    if len(rows) >= 3 and len(with_cite) >= 2:
        return [("✅", "反例与失败模式", f"{len(rows)} 条，其中 {len(with_cite)} 条带原文出处")]
    return [("❌", "反例与失败模式", f"{len(rows)} 条（要求 ≥3，且至少 2 条带出处）")]


def _boundary_checks(sections: dict):
    body = _find_section(sections, "边界") or ""
    items = [ln for ln in body.splitlines() if re.match(r"^\s*[-*]\s+\S", ln)]
    return [("✅", "边界", f"{len(items)} 条")] if len(items) >= 3 else \
           [("❌", "边界", f"只有 {len(items)} 条，要求 ≥3")]


def _report(work: Path, results: list, meta: dict, min_citations: int, min_coverage: float) -> dict:
    fails = [r for r in results if r[0] == "❌"]
    warns = [r for r in results if r[0] == "⚠️"]
    lines = [
        "# 质检报告",
        "",
        f"- 结论：{'❌ 不合格（%d 项）' % len(fails) if fails else '✅ 通过'}",
        f"- 警告：{len(warns)} 项",
        f"- 对应产物：{meta.get('skill', '—')}",
        f"- 规模：{meta.get('chapters', 0)} 章 / {meta.get('citations', 0)} 处引用",
        "",
        "| 结果 | 检查项 | 说明 |",
        "|---|---|---|",
    ]
    for mark, name, detail in results:
        lines.append(f"| {mark} | {name} | {detail} |")
    lines += [
        "",
        "> 与同类工具的差别：本检查不搜关键词，而是逐条核对引用能否解析回原文、",
        "> 模型是否写了失效条件、流程是否给了判据。写几个字骗不过去。",
        "",
    ]
    report = "\n".join(lines)
    (work / "REPORT.md").write_text(report, encoding="utf-8")
    return {"ok": not fails, "fails": fails, "warns": warns, "results": results,
            "report": str(work / "REPORT.md")}
