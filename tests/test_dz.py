"""蒸馏工坊 · 测试

覆盖四类容易出错的地方：
  1. 维基模板嵌套（实测踩过：正则会整块匹配失败，把 `|title=...` 漏进正文）
  2. 章节切分与段落 ID 稳定性（ID 是整套引用体系的地基，漂了就等于全部失效）
  3. 压缩不丢章节
  4. 质检真的能拦住问题产物（而不是数关键词）
"""
import json
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dzlib import condense as condense_mod  # noqa: E402
from dzlib import fetch as fetch_mod  # noqa: E402
from dzlib import ingest as ingest_mod  # noqa: E402
from dzlib import pack as pack_mod  # noqa: E402
from dzlib import text as T  # noqa: E402
from dzlib import verify as verify_mod  # noqa: E402
from dzlib import web as web_mod  # noqa: E402

WIKI_SAMPLE = """{{Textquality|75%}}
{{header
|title=測試書
|author=某人
|notes={{wikipedia|測試}}另見《[[附錄]]》
}}

== 第一章 起 ==
第一段話，講的是原則問題。

第二段話，說明必須先判斷再行動。

== 第二章 承 ==
第三段話，指出常見錯誤在於跳過驗證。

== 第三章 轉 ==
第四段話，強調邊界條件的重要性。
"""

MD_SAMPLE = """# 书名

## 一、开头
这是第一章的内容，讲一个核心原则。

## 二、中间
这是第二章的内容，讲判断标准。

## 三、结尾
这是第三章的内容，讲常见误区。
"""


class TextUtilsTests(unittest.TestCase):
    def test_nested_template_is_removed(self):
        out = T.strip_wiki(WIKI_SAMPLE)
        self.assertNotIn("{{", out)
        self.assertNotIn("|title=", out)
        self.assertNotIn("wikipedia", out)

    def test_wiki_link_keeps_label(self):
        out = T.strip_wiki("參見[[wikipedia:zh:某人|這個人]]的說法")
        self.assertIn("這個人", out)
        self.assertNotIn("[[", out)

    def test_tokens_filter_noise_chars(self):
        toks = T.tokens("孫子曰：兵者，國之大事")
        self.assertNotIn("曰", "".join(toks))
        self.assertTrue(any("大事" in t or "國之" in t for t in toks))

    def test_iter_sentences_splits_on_cjk_punctuation(self):
        sents = T.iter_sentences(
            "这是第一句话，讲的是原则问题。这是第二句话，讲的是判断标准！这是第三句话，测试问号切分？"
        )
        self.assertEqual(len(sents), 3)

    def test_iter_sentences_skips_short_and_blank(self):
        self.assertEqual(T.iter_sentences("\n\n。\n"), [])

    def test_pick_key_sentences_preserve_original_order(self):
        sents = [
            "无关的一句话，只是填充内容而已。",
            "这是核心原则，必须遵守，判断标准在此。",
            "又一句无关的填充内容，用来增加噪声。",
            "这条也重要，原则和标准都在这里。",
        ]
        tf = T.term_freq(" ".join(sents))
        picked = T.pick_key_sentences(sents, tf, k=2)
        idxs = [i for i, _ in picked]
        self.assertEqual(idxs, sorted(idxs))

    def test_top_terms_requires_min_count(self):
        self.assertEqual(T.top_terms("孤立词汇", k=5, min_count=2), [])


class ChapterSplitTests(unittest.TestCase):
    def test_wiki_headings_split(self):
        book = ingest_mod.build(title="x", text=T.strip_wiki(WIKI_SAMPLE))
        self.assertEqual(len(book.chapters), 3)
        self.assertEqual(book.chapters[0].title, "第一章 起")

    def test_markdown_headings_split(self):
        book = ingest_mod.build(title="x", text=MD_SAMPLE)
        self.assertEqual(len(book.chapters), 3)

    def test_english_headings_split(self):
        """Gutenberg 英文书常见三种写法都要认：全大写罗马、首字母大写罗马、阿拉伯数字。"""
        text = (
            "Chapter I. LAYING PLANS\n\n"
            "Sun Tzŭ said: the art of war is of vital importance to the State.\n\n"
            "CHAPTER XII. THE ATTACK BY FIRE\n\n"
            "There are five ways of attacking with fire.\n\n"
            "Chapter 3. ATTACK BY STRATAGEM\n\n"
            "The best thing of all is to take the enemy's country whole.\n"
        )
        book = ingest_mod.build(title="x", text=text)
        self.assertEqual(len(book.chapters), 3)
        self.assertEqual(book.chapters[0].title, "Chapter I. LAYING PLANS")
        self.assertEqual(book.chapters[1].title, "CHAPTER XII. THE ATTACK BY FIRE")
        self.assertEqual(book.chapters[2].title, "Chapter 3. ATTACK BY STRATAGEM")

    def test_english_sentence_is_not_a_heading(self):
        """小写 chapter 开头的普通句子不能被当成标题（标题部分含句点即排除）。"""
        text = (
            "Chapter 1 is about planning and how it decides the outcome.\n\n"
            "Chapter 2 is about waging war and the cost of a long campaign.\n\n"
            "That is all.\n"
        )
        book = ingest_mod.build(title="x", text=text)
        self.assertEqual(len(book.chapters), 1, "普通句子不该触发切章")
        self.assertEqual(book.chapters[0].title, "正文")

    def test_toc_entries_are_dropped(self):
        """目录页里紧挨着排列的章标题要整块丢掉，只留正文那份。"""
        body_a = "真正的第一章正文。" * 60
        body_b = "真正的第二章正文。" * 60
        text = (
            "Contents\n\n"
            "Chapter I. Laying plans\n"
            "Chapter II. Waging War\n"
            "Chapter III. Attack by Stratagem\n"
            "\n"
            f"Chapter I. LAYING PLANS\n\n{body_a}\n\n"
            f"Chapter II. WAGING WAR\n\n{body_b}\n"
        )
        book = ingest_mod.build(title="x", text=text)
        titles = [c.title for c in book.chapters]
        # 目录三项被丢弃；剩下的正文两章 + 前面的 "Contents" 成了前言
        self.assertNotIn("Chapter III. Attack by Stratagem", titles, f"目录项没被丢掉：{titles}")
        self.assertNotIn("Chapter I. Laying plans", titles)
        self.assertEqual(titles.count("Chapter I. LAYING PLANS"), 1)
        self.assertEqual(titles.count("Chapter II. WAGING WAR"), 1)
        self.assertEqual(len(body_a), len(book.chapters[1].text))
        self.assertEqual([c.idx for c in book.chapters], list(range(1, len(titles) + 1)))

    def test_dense_headings_with_long_bodies_are_not_toc(self):
        """标题挨得近但每章都有实质内容时，不能误判成目录。"""
        seg = "有实质内容的一段话。" * 20
        text = "\n\n".join(f"第{n}章 标题\n{seg}" for n in "一二三四")
        book = ingest_mod.build(title="x", text=text)
        self.assertEqual(len(book.chapters), 4, "有内容的章不该被当目录丢掉")

    def test_same_title_across_volumes_is_kept(self):
        """分卷同名章（两份都有实质内容）不能被误当成目录项丢掉。"""
        vol1 = "卷一的第一章内容。" * 50
        vol2 = "卷二的同名第一章内容。" * 50
        text = (
            f"Chapter I. LAYING PLANS\n\n{vol1}\n\n"
            f"Chapter I. LAYING PLANS\n\n{vol2}\n"
        )
        book = ingest_mod.build(title="x", text=text)
        self.assertEqual(len(book.chapters), 2, "同名但都有内容，应保留两份")

    def test_no_heading_single_chapter(self):
        book = ingest_mod.build(title="x", text="就一段话，没有标题。\n\n还有一段。")
        self.assertEqual(len(book.chapters), 1)
        self.assertEqual(book.chapters[0].title, "正文")

    def test_paragraph_ids_are_stable(self):
        book = ingest_mod.build(title="x", text=T.strip_wiki(WIKI_SAMPLE))
        ids = [pid for pid, *_ in book.paragraphs()]
        self.assertEqual(ids[0], "c01p000")
        self.assertEqual(len(ids), len(set(ids)), "段落 ID 不能重复")

    def test_index_maps_id_to_chapter(self):
        book = ingest_mod.build(title="x", text=T.strip_wiki(WIKI_SAMPLE))
        index = book.index()
        self.assertEqual(index["c01p000"]["chapter"], 1)
        self.assertIn("第一章", index["c01p000"]["chapter_title"])

    def test_save_and_load_roundtrip(self):
        book = ingest_mod.build(title="测试", text=T.strip_wiki(WIKI_SAMPLE))
        with tempfile.TemporaryDirectory() as tmp:
            ingest_mod.save(book, tmp)
            again = ingest_mod.load_work(tmp)
        self.assertEqual(again.title, "测试")
        self.assertEqual(len(again.chapters), len(book.chapters))
        self.assertEqual(list(again.index()), list(book.index()))


class CondenseTests(unittest.TestCase):
    def _book(self):
        return ingest_mod.build(title="測試書", text=T.strip_wiki(WIKI_SAMPLE))

    def test_writes_prep_per_chapter(self):
        with tempfile.TemporaryDirectory() as tmp:
            meta = condense_mod.condense(self._book(), tmp)
            self.assertEqual(len(meta["prep_files"]), 3)
            self.assertTrue((Path(tmp) / "prep" / "00-overview.md").exists())

    def test_prep_citations_resolve_to_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            book = self._book()
            condense_mod.condense(book, tmp)
            ingest_mod.save(book, tmp)
            index = json.loads((Path(tmp) / "index.json").read_text(encoding="utf-8"))
            body = (Path(tmp) / "prep" / "c01.md").read_text(encoding="utf-8")
            found = __import__("re").findall(r"\[(c\d{2}p\d{3})\]", body)
            self.assertTrue(found, "材料包里应该有段落 ID")
            for cid in found:
                self.assertIn(cid, index, "材料包里的段落 ID 必须能在索引中解析")

    def test_exclude_skips_chapter(self):
        with tempfile.TemporaryDirectory() as tmp:
            meta = condense_mod.condense(self._book(), tmp, exclude=["第二章"])
            self.assertEqual(len(meta["prep_files"]), 2)
            self.assertTrue(any("第二章" in s for s in meta["skipped"]))

    def test_exclude_by_index_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            meta = condense_mod.condense(self._book(), tmp, exclude=["c03"])
            self.assertEqual(len(meta["prep_files"]), 2)

    def test_overview_lists_every_chapter(self):
        with tempfile.TemporaryDirectory() as tmp:
            condense_mod.condense(self._book(), tmp)
            ov = (Path(tmp) / "prep" / "00-overview.md").read_text(encoding="utf-8")
        for title in ("第一章 起", "第二章 承", "第三章 轉"):
            self.assertIn(title, ov)


class PackTests(unittest.TestCase):
    def test_tasks_contains_contract_and_rules(self):
        book = ingest_mod.build(title="測試書", text=T.strip_wiki(WIKI_SAMPLE))
        with tempfile.TemporaryDirectory() as tmp:
            path = pack_mod.build(book, tmp, {"chapters": 3})
            body = path.read_text(encoding="utf-8")
        self.assertIn("硬规则", body)
        for section in pack_mod.REQUIRED_SECTIONS:
            self.assertIn(section, body)
        self.assertIn("verify", body)

    def test_slug_is_filesystem_safe(self):
        self.assertEqual(pack_mod._slugify("《孫子兵法》 卷一!"), "孫子兵法-卷一")


GOOD_SKILL = """---
name: test-skill
description: 从《測試書》蒸馏出的可执行方法论。
source: sample
---

# 測試書 · 可执行方法论

## 这本书解决什么问题

讲怎样在做事之前先做判断，适用于需要反复决策且犯错成本高的场景。

## 核心模型

### 模型一：先判断再行动

- **一句话**：不要先做，先判断。
- **原文依据**：[c01p000]
- **什么时候用**：任何要投入资源之前。
- **什么时候失效**：信息完全无法获取时，此模型失效。

### 模型二：验证不可跳过

- **一句话**：跳过验证是常见错误。
- **原文依据**：[c02p000]
- **什么时候用**：交付前。
- **什么时候失效**：一次性小事上不适用。

### 模型三：看清边界条件

- **一句话**：边界条件决定成败。
- **原文依据**：[c03p000]
- **什么时候用**：方案定稿前。
- **什么时候失效**：边界极稳定的场景下影响很小（不适用）。

## 可执行流程

**Step 1 · 收集事实**
- 做什么：先把已知条件写下来。
- 判据：条件写满一页 [c01p000]
- 常见错误：凭感觉开始。

**Step 2 · 做判断**
- 做什么：按原则判断做还是不做。
- 判据：能一句话说出判断依据 [c02p000]
- 常见错误：跳过验证直接上。

**Step 3 · 定边界**
- 做什么：写清什么情况下方案会失效。
- 判据：边界写到三条以上 [c03p000]
- 常见错误：只写优点。

## 判断清单

- [ ] 条件是否写全了？[c01p000]
- [ ] 是否先判断再行动？[c01p000]
- [ ] 验证环节有没有跳过？[c02p000]
- [ ] 交付前有没有回看？[c02p000]
- [ ] 边界条件写了吗？[c03p000]

## 反例与失败模式

| 错误做法 | 为什么错 | 原文依据 |
|---|---|---|
| 跳过验证直接行动 | 常见错误来源 | [c02p000] |
| 只写优点不写边界 | 会在边界处翻车 | [c03p000] |
| 不先判断就投资源 | 成本高 | [c01p000] |

## 边界

- 原书没有覆盖执行层面的组织管理问题。
- 写作年代较早，部分工具条件已经变化。
- 不适用于信息完全缺失的场景。

## 原文索引

| 段落 ID | 所属章节 | 摘要 |
|---|---|---|
| c01p000 | 第一章 起 | 讲原则 |
| c02p000 | 第二章 承 | 讲常见错误 |
| c03p000 | 第三章 轉 | 讲边界 |
"""


class VerifyTests(unittest.TestCase):
    def _setup(self, skill_text):
        tmp = tempfile.TemporaryDirectory()
        book = ingest_mod.build(title="測試書", text=T.strip_wiki(WIKI_SAMPLE))
        ingest_mod.save(book, tmp.name)
        condense_mod.condense(book, tmp.name)
        (Path(tmp.name) / "SKILL.md").write_text(skill_text, encoding="utf-8")
        return tmp

    def test_good_skill_passes(self):
        with self._setup(GOOD_SKILL) as tmp:
            result = verify_mod.verify(tmp)
        self.assertTrue(result["ok"], [f for f in result["fails"]])

    def test_missing_skill_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            book = ingest_mod.build(title="x", text=T.strip_wiki(WIKI_SAMPLE))
            ingest_mod.save(book, tmp)
            result = verify_mod.verify(tmp)
        self.assertFalse(result["ok"])

    def test_fabricated_citation_is_caught(self):
        bad = GOOD_SKILL.replace("[c01p000]", "[c09p999]")
        with self._setup(bad) as tmp:
            result = verify_mod.verify(tmp)
        names = [n for _, n, _ in result["fails"]]
        self.assertIn("引用可解析", names)

    def test_no_citation_is_caught(self):
        bad = __import__("re").sub(r"\[c\d{2}p\d{3}\]", "", GOOD_SKILL)
        with self._setup(bad) as tmp:
            result = verify_mod.verify(tmp)
        names = [n for _, n, _ in result["fails"]]
        self.assertIn("引用可解析", names)

    def test_missing_section_is_caught(self):
        bad = GOOD_SKILL.replace("## 边界", "## 别的")
        with self._setup(bad) as tmp:
            result = verify_mod.verify(tmp)
        names = [n for _, n, _ in result["fails"]]
        self.assertIn("结构契约", names)

    def test_model_without_failure_condition_is_caught(self):
        bad = GOOD_SKILL.replace(
            "- **什么时候失效**：信息完全无法获取时，此模型失效。",
            "- **备注**：总是好用。",
        )
        with self._setup(bad) as tmp:
            result = verify_mod.verify(tmp)
        names = [n for _, n, _ in result["fails"]]
        self.assertIn("模型写失效条件", names)

    def test_low_coverage_is_caught(self):
        only_first = __import__("re").sub(r"\[c0[23]p\d{3}\]", "[c01p000]", GOOD_SKILL)
        with self._setup(only_first) as tmp:
            result = verify_mod.verify(tmp, min_coverage=0.6)
        names = [n for _, n, _ in result["fails"]]
        self.assertIn("章节覆盖", names)

    def test_keyword_stuffing_does_not_pass(self):
        """对着同类工具的坑：写满「局限」「张力」这类词，也不该通过。"""
        stuffed = """---
name: fake
description: 假的
---

## 这本书解决什么问题

局限 张力 矛盾 盲区 失效 不适用 边界——把这些词堆满，看看能不能骗过检查。

## 核心模型

### 模型一

局限 张力 矛盾

## 可执行流程

局限 张力

## 判断清单

局限

## 反例与失败模式

局限

## 边界

局限

## 原文索引

无
"""
        with self._setup(stuffed) as tmp:
            result = verify_mod.verify(tmp)
        self.assertFalse(result["ok"], "堆关键词不应该通过质检")

    def test_report_is_written(self):
        with self._setup(GOOD_SKILL) as tmp:
            verify_mod.verify(tmp)
            self.assertTrue((Path(tmp) / "REPORT.md").exists())


class FetchTests(unittest.TestCase):
    def test_wikisource_url_is_quoted(self):
        from urllib.parse import quote

        self.assertEqual(fetch_mod.WIKISOURCE_RAW.format(title=quote("孫子兵法")).count("%"), 12)

    def test_gutenberg_boilerplate_stripped(self):
        raw = "前言\n*** START OF THE PROJECT GUTENBERG EBOOK X ***\n正文\n*** END OF THE PROJECT GUTENBERG EBOOK X ***\n尾"
        out = fetch_mod.strip_gutenberg_boilerplate(raw)
        self.assertIn("正文", out)
        self.assertNotIn("START OF", out)
        self.assertNotIn("前言", out)


class WebExtractTests(unittest.TestCase):
    """在线取本：HTML → 正文。这些都是实测踩过的坑，别再改回去。"""

    NAV_PAGE = (
        "<html><body>"
        '<div class="nav">'
        + "".join(f'<a href="/p{i}">栏目{i}</a>' for i in range(20))
        + "</div>"
        '<div class="article"><h2>第一章 起</h2>'
        "<p>" + "这是正文第一段，讲的是原则与判断标准，必须先把前提说清楚。" * 4 + "</p>"
        "<p>" + "这是正文第二段，指出常见错误在于跳过验证直接下结论。" * 4 + "</p>"
        "<h2>第二章 承</h2>"
        "<p>" + "这是第二章的正文，讲的是执行顺序与边界条件。" * 4 + "</p>"
        "</div></body></html>"
    )

    def test_entities_are_decoded(self):
        # ctext 把中文整体写成 &#x..; 实体，不解码就等于拿到一页乱码
        out = web_mod.html_to_text("<p>&#x5B6B;&#x5B50;&#x5175;&#x6CD5;是先秦兵书。</p>")
        self.assertIn("孫子兵法", out)

    def test_br_makes_a_line_break(self):
        # 实测 bug：<br><br> 分段的老式页面（Paul Graham 那种）会整篇黏成一段
        out = web_mod.html_to_text("<p>第一行<br><br>第二行这里是够长的正文内容。</p>")
        self.assertIn("第一行", out.split("\n"))
        self.assertIn("第二行这里是够长的正文内容。", out.split("\n"))

    def test_nav_with_many_links_is_not_chosen(self):
        out = web_mod.html_to_text(self.NAV_PAGE)
        self.assertIn("这是正文第一段", out)
        self.assertNotIn("栏目7", out)

    def test_script_and_style_dropped(self):
        out = web_mod.html_to_text(
            "<div><script>var secret=1;</script><style>.a{color:red}</style>"
            "<p>这里是有意义的正文内容，不能被脚本噪声污染。</p></div>"
        )
        self.assertNotIn("secret", out)
        self.assertNotIn("color:red", out)

    def test_heading_becomes_chapter_marker(self):
        out = web_mod.html_to_text(self.NAV_PAGE)
        self.assertIn("## 第一章 起", out)

    def test_html_output_splits_into_chapters(self):
        book = ingest_mod.build(title="测试", text=web_mod.html_to_text(self.NAV_PAGE))
        titles = [c.title for c in book.chapters]
        self.assertIn("第一章 起", titles)

    def test_short_meaningful_line_is_kept(self):
        # 回归：早先按「少于 12 字就丢」过滤，把 PG 开头的 July 2023 丢了
        out = web_mod.html_to_text("<div><p>July 2023</p><p>正文在这里，足够长的一句话。</p></div>")
        self.assertIn("July 2023", out)

    def test_pure_chrome_line_is_dropped(self):
        out = web_mod.html_to_text(
            "<div><p>首页</p><p>订阅</p><p>这里是一段真正有内容的正文，长度也足够。</p></div>"
        )
        self.assertNotIn("首页", out)
        self.assertIn("真正有内容的正文", out)

    def test_inline_edit_marker_removed(self):
        out = web_mod.html_to_text("<p>某段正文内容够长了[编辑]，后面还有一句。</p>")
        self.assertNotIn("[编辑]", out)


class CtextTests(unittest.TestCase):
    """ctext 专用抽取器。两条规矩都是踩出来的，见 web.py 顶部注释。"""

    def test_volume_pages_are_skipped(self):
        # 卷级页含子章正文，若和章一起抓内容会整块重复
        page = (
            '<a class="menuitem" href="bk/zh">书</a>'
            '<a class="menuitem" href="bk/juan-yi/zh">卷一</a>'
            '<a class="menuitem" href="bk/yuan-dao/zh">原道</a>'
            '<a class="menuitem" href="bk/juan-er/zh">卷二</a>'
            '<a class="menuitem" href="bk/zheng-sheng/zh">徵聖</a>'
        )
        toc = web_mod._ctext_toc(page, "bk")
        self.assertEqual([n for n, _ in toc], ["原道", "徵聖"])
        self.assertEqual([r for _, r in toc], ["bk/yuan-dao/zh", "bk/zheng-sheng/zh"])

    def test_self_link_is_not_a_chapter(self):
        page = '<a class="menuitem" href="bk/zh">書名</a><a class="menuitem" href="bk/shen-si/zh">神思</a>'
        self.assertEqual(len(web_mod._ctext_toc(page, "bk")), 1)

    def test_opt_label_cell_is_excluded(self):
        # 同一行还有个 class="ctext opt" 的章节标签，混进来会污染正文
        page = (
            '<td valign="top" class="ctext opt">神思:</td>'
            '<td class="ctext">古人云：「形在江海之上，心存魏闕之下。」</td>'
        )
        body = web_mod._ctext_body(page)
        self.assertIn("形在江海之上", body)
        self.assertNotIn("神思:", body)

    def test_fetch_ctext_assembles_chapters_in_order(self):
        index = (
            '<a class="menuitem" href="bk/zh">書</a>'
            '<a class="menuitem" href="bk/juan-yi/zh">卷一</a>'
            '<a class="menuitem" href="bk/a/zh">甲篇</a>'
            '<a class="menuitem" href="bk/b/zh">乙篇</a>'
        )
        pages = {
            "https://ctext.org/bk/zh": index,
            "https://ctext.org/bk/a/zh": '<td class="ctext">甲篇的正文内容在这里。</td>',
            "https://ctext.org/bk/b/zh": '<td class="ctext">乙篇的正文内容在这里。</td>',
        }
        with unittest.mock.patch.object(web_mod, "get", side_effect=lambda u, timeout=30: pages[u]):
            data = web_mod.fetch_ctext("bk")
        self.assertEqual(data["chapters_fetched"], 2)
        self.assertLess(data["text"].index("## 甲篇"), data["text"].index("## 乙篇"))

    def test_missing_toc_raises(self):
        with unittest.mock.patch.object(web_mod, "get", return_value="<html>空页</html>"):
            with self.assertRaises(fetch_mod.FetchError):
                web_mod.fetch_ctext("nothing-here")

    def test_a_failed_chapter_does_not_kill_the_book(self):
        index_url = "https://ctext.org/bk/zh"
        index = (
            '<a class="menuitem" href="bk/a/zh">甲篇</a>'
            '<a class="menuitem" href="bk/b/zh">乙篇</a>'
        )
        pages = {
            index_url: index,
            "https://ctext.org/bk/a/zh": '<td class="ctext">甲篇正文内容。</td>',
        }

        def fake_get(url, timeout=30):
            if url not in pages:
                raise fetch_mod.FetchError("boom")
            return pages[url]

        with unittest.mock.patch.object(web_mod, "get", side_effect=fake_get):
            data = web_mod.fetch_ctext("bk")
        self.assertEqual(data["chapters_fetched"], 1)
        self.assertIn("甲篇", data["text"])


class SentenceBudgetTests(unittest.TestCase):
    """关键句额度要随章长缩放。

    回归：早先写死 k=per_chapter，实测一本 66,956 字的单章网页只抽出 12 句，
    等于把正文压掉 98%——提炼必然失真。
    """

    def test_normal_chapter_keeps_default(self):
        self.assertEqual(condense_mod.sentence_budget(950, 12, 100), 12)

    def test_short_chapter_still_gets_floor(self):
        self.assertEqual(condense_mod.sentence_budget(200, 12, 100), 12)

    def test_long_chapter_scales_up(self):
        self.assertGreater(condense_mod.sentence_budget(20000, 12, 100), 12)

    def test_long_chapter_respects_ceiling(self):
        self.assertEqual(condense_mod.sentence_budget(66956, 12, 100), 100)

    def test_condense_actually_uses_more_for_long_chapter(self):
        long_para = "这是一句足够长的正文内容，用来说明判断标准与执行顺序的关系。" * 3
        text = "\n".join(long_para for _ in range(120))
        with tempfile.TemporaryDirectory() as tmp:
            book = ingest_mod.build(title="长文", text="## 第一章\n\n" + text + "\n\n## 第二章\n\n" + text)
            condense_mod.condense(book, tmp, per_chapter=12, max_per_chapter=100)
            body = (Path(tmp) / "prep" / "c01.md").read_text(encoding="utf-8")
            picks = [l for l in body.split("\n") if l.startswith("- [")]
        self.assertGreater(len(picks), 12)


if __name__ == "__main__":
    unittest.main(verbosity=2)
