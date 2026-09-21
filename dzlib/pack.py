"""提炼任务包：给 AI 的作业说明 + 严格输出契约。

同类工具的失败在于「让它自由发挥」——结果是看起来漂亮、实则不可追溯的文本。
这里改成：先定契约，产物缺项或引用不可解析就会被 verify 拦下。
"""
from pathlib import Path

REQUIRED_SECTIONS = [
    "这本书解决什么问题",
    "核心模型",
    "可执行流程",
    "判断清单",
    "反例与失败模式",
    "边界",
    "原文索引",
]

TEMPLATE = """---
name: {slug}
description: 从《{title}》蒸馏出的可执行方法论。说「用{short}的方法」「按{short}来」时启用。
source: {source}
author: {author}
distilled: {date}
chapters: {chapters}
---

# {title} · 可执行方法论

> 本文中每条结论后的方括号如 `[c03p002]` 指向原书段落，可用 `dz.py show <工作目录> c03p002` 回查。

## 这本书解决什么问题

（≤120 字，说清它在什么场景下有用，以及它假设你已经有什么条件）

## 核心模型

### 模型一：（名称，≤12 字）

- **一句话**：（这个模型在说什么）
- **原文依据**：[cXXpYY] （必须来自材料包，至少 1 条，可多条）
- **什么时候用**：（具体场景）
- **什么时候失效**：（边界条件，必须写）

### 模型二：……

（3–5 个，宁少勿多。「所有聪明人都这么说」的道理不算模型）

## 可执行流程

**Step 1 ·（动作名）**
- 做什么：
- 判据： [cXXpYY] （凭什么判断做对了）
- 常见错误：

**Step 2 ·** ……

（至少 3 步，每步都要有判据。步骤要能直接照着做，不要写「要重视」「要思考」这类空话）

## 判断清单

- [ ] （能在 10 秒内回答是/否的检查项，至少 5 条，尽量带判据 [cXXpYY]）

## 反例与失败模式

| 错误做法 | 为什么错 | 原文依据 |
|---|---|---|
| （原书明确反对的做法） | | [cXXpYY] |

（至少 3 条。只写你从原文里读到的，不要补充自己的经验）

## 边界

- （原书没覆盖的）
- （时代局限：写在什么年代，哪些前提今天已变）
- （不适用场景）

（至少 3 条）

## 原文索引

| 段落 ID | 所属章节 | 摘要 |
|---|---|---|
| cXXpYY | （章节标题） | （这句话在说什么） |

（把你引用过的段落全部列出）
"""


def build(book, work_dir, meta=None) -> Path:
    """生成 TASKS.md：AI 读它 + prep/ 材料，产出 SKILL.md。"""
    work = Path(work_dir)
    meta = meta or {}
    slug = _slugify(book.title)
    short = (book.title or "本书")[:8]
    body = [
        f"# 提炼任务 ·《{book.title}》",
        "",
        "## 你要做什么",
        "",
        f"把《{book.title}》提炼成一份**可执行方法论**，写成 `SKILL.md`。",
        "",
        "先读 `prep/00-overview.md` 拿到全书地图，再按需读 `prep/cXX.md`。",
        "**不要去搜网上的书评和解读**——只允许使用 prep/ 里的材料，这样每个结论都能回查原文。",
        "",
        "## 硬规则（违反即不合格）",
        "",
        "1. 每条结论后必须挂原文段落 ID，格式 `[c03p002]`，ID 只能取自 prep/ 文件。",
        "2. 不许出现材料里没有的说法。你自己的经验可以写，但必须单独标注「（个人补充）」。",
        "3. 「核心模型」每个都要写**失效条件**——只写优点的模型视为没写。",
        "4. 「可执行流程」每步都要有**判据**，判据必须能挂到某个段落 ID。",
        "5. 拿不准的地方，写进「边界」，不要含糊过去。",
        f"6. 至少 {meta.get('min_citations', 12)} 处引用，且覆盖至少 60% 的章节。",
        "",
        "## 结构契约（缺任一节都不合格）",
        "",
        *[f"- `## {s}`" for s in REQUIRED_SECTIONS],
        "",
        "## 参考骨架",
        "",
        "```markdown",
        TEMPLATE.format(
            slug=slug,
            title=book.title,
            short=short,
            source=book.source,
            author=book.author or "",
            date=book.created,
            chapters=meta.get("chapters", len(book.chapters)),
        ),
        "```",
        "",
        "## 完成后自检",
        "",
        f"- 运行：`python3 dz.py verify {work}`",
        "- 报告里出现 ❌ 就回到对应部分改，改完再跑一次。",
        "",
    ]
    path = work / "TASKS.md"
    path.write_text("\n".join(body), encoding="utf-8")
    return path


def _slugify(title: str) -> str:
    import re

    s = re.sub(r"[^\w\u4e00-\u9fff]+", "-", (title or "book").strip().lower())
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s or "book"
