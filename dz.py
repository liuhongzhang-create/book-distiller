#!/usr/bin/env python3
"""蒸馏工坊 · 命令行

把一本书变成可执行的方法论。流程：
    取本 → 切章 → 压缩 → 生成提炼任务包 →（AI 写 SKILL.md）→ 质检

示例
    python3 dz.py pipe --wikisource 孫子兵法 --out work/sunzi
    python3 dz.py verify work/sunzi
    python3 dz.py show work/sunzi c03p002
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dzlib import condense as condense_mod  # noqa: E402
from dzlib import fetch as fetch_mod  # noqa: E402
from dzlib import ingest as ingest_mod  # noqa: E402
from dzlib import pack as pack_mod  # noqa: E402
from dzlib import text as text_mod  # noqa: E402
from dzlib import verify as verify_mod  # noqa: E402
from dzlib import web as web_mod  # noqa: E402


def cmd_new(args):
    work = Path(args.workdir)
    work.mkdir(parents=True, exist_ok=True)
    print(f"已建工作目录 {work}")
    return 0


def _resolve_out(args):
    if args.out:
        return Path(args.out)
    return Path("work") / "book"


def _fetch_source(args):
    """按来源取本，返回 (data, 存盘用的名字)。取不到就抛 FetchError。"""
    if args.gutenberg:
        data = fetch_mod.fetch_gutenberg(int(args.gutenberg))
        data["text"] = fetch_mod.strip_gutenberg_boilerplate(data["text"])
        return data, f"gutenberg-{args.gutenberg}"
    if args.wikisource:
        data = fetch_mod.fetch_wikisource(args.wikisource)
        data["text"] = text_mod.strip_wiki(data["text"])
        return data, args.wikisource
    if args.ctext:
        data = web_mod.fetch_ctext(args.ctext, limit=args.limit)
        print(f"在线抓取 ctext：{data['chapters_fetched']}/{data['chapters_listed']} 章成功")
        return data, f"ctext-{args.ctext}"
    if args.web:
        return web_mod.fetch_web(args.web), "web"
    if args.url:
        return fetch_mod.fetch_url(args.url), "url"
    return None, None


def cmd_fetch(args):
    out = _resolve_out(args)
    out.mkdir(parents=True, exist_ok=True)

    try:
        data, name = _fetch_source(args)
    except fetch_mod.FetchError as exc:
        print(f"取不到内容：{exc}")
        print("排查方向：地址是否有效、站点是否需要登录、内容是否靠 JS 渲染。")
        return 3

    if data is None:
        print("需要 --gutenberg / --wikisource / --ctext / --web / --url 之一")
        return 2
    fetch_mod.save_raw(out, name, data["text"])
    book = ingest_mod.build(
        title=data["title"], author=data["author"],
        source=data["source"], license=data["license"], text=data["text"],
    )
    if not book.chapters:
        print(f"没抓到可用的正文（来源 {data['source']}）。")
        print("网页类来源常见原因：内容靠 JS 渲染、需要登录、或整页都是导航。")
        return 3
    ingest_mod.save(book, out)
    stats = book.stats()
    print(f"《{book.title}》 作者 {book.author or '—'}")
    print(f"  来源 {book.source}")
    print(f"  规模 {stats['chapters']} 章 / {stats['chars']:,} 字 / {stats['paragraphs']} 段")
    for ch in book.chapters[:8]:
        print(f"    c{ch.idx:02d} {ch.title}（{len(ch.text):,} 字）")
    if len(book.chapters) > 8:
        print(f"    …共 {len(book.chapters)} 章")
    return 0


def cmd_ingest(args):
    out = Path(args.out) if args.out else Path("work") / "book"
    book = ingest_mod.load(args.path)
    ingest_mod.save(book, out)
    stats = book.stats()
    print(f"《{book.title}》 {stats['chapters']} 章 / {stats['chars']:,} 字 → {out}/book.json")
    return 0


def cmd_condense(args):
    book = ingest_mod.load_work(args.workdir)
    meta = condense_mod.condense(book, args.workdir, per_chapter=args.per_chapter,
                                 full=args.full, exclude=args.exclude,
                                 max_per_chapter=args.max_per_chapter)
    print(f"压缩完成：{meta['chapters']} 章 → prep/ 下 {len(meta['prep_files'])} 个文件")
    prep_chars = sum(f.stat().st_size for f in (Path(args.workdir) / "prep").glob("c*.md"))
    print(f"  原文字数 {meta['chars']:,} → 材料包约 {prep_chars // 3:,} 字"
          f"（压缩到 {prep_chars / 3 / max(1, meta['chars']):.0%}）")
    if meta.get("skipped"):
        print(f"  已跳过：{'、'.join(meta['skipped'])}")
    print("  全书高频词：" + "、".join(w for w, _ in meta["top_terms"][:12]))
    return 0


def cmd_tasks(args):
    book = ingest_mod.load_work(args.workdir)
    meta_path = Path(args.workdir) / "prep" / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    path = pack_mod.build(book, args.workdir, meta)
    print(f"已生成提炼任务包 {path}")
    print("下一步：让 AI 读 TASKS.md + prep/，产出 SKILL.md，再跑 verify")
    return 0


def cmd_show(args):
    index = json.loads((Path(args.workdir) / "index.json").read_text(encoding="utf-8"))
    item = index.get(args.pid)
    if not item:
        near = [k for k in index if k.startswith(args.pid[:3])][:5]
        print(f"没有 {args.pid}。同章可用的 ID 例如：{'、'.join(near) or '无'}")
        return 1
    print(f"{args.pid} → 第 {item['chapter']} 章《{item['chapter_title']}》")
    print()
    print(item["text"])
    return 0


def cmd_verify(args):
    result = verify_mod.verify(args.workdir, min_citations=args.min_citations,
                               min_coverage=args.min_coverage)
    for mark, name, detail in result["results"]:
        print(f"{mark} {name}：{detail}")
    print()
    print(f"报告：{result['report']}")
    return 0 if result["ok"] else 1


def cmd_pipe(args):
    out = Path(args.out)
    rc = cmd_fetch(argparse.Namespace(out=str(out), gutenberg=args.gutenberg,
                                      wikisource=args.wikisource, ctext=args.ctext,
                                      web=args.web, url=args.url, limit=args.limit))
    if rc:
        return rc
    book = ingest_mod.load_work(out)
    meta = condense_mod.condense(book, out, per_chapter=args.per_chapter,
                                 full=args.full, exclude=args.exclude,
                                 max_per_chapter=args.max_per_chapter)
    pack_mod.build(book, out, meta)
    print()
    print(f"材料包就绪：{out}")
    print(f"  {out}/TASKS.md      提炼任务包（给 AI 看）")
    print(f"  {out}/prep/         压缩后的材料")
    print(f"  {out}/index.json    段落 ID 索引（回查原文用）")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="dz", description="蒸馏工坊 · 把书变成可执行方法论")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("new", help="新建工作目录")
    p.add_argument("workdir")
    p.set_defaults(func=cmd_new)

    p = sub.add_parser("fetch", help="取本：公版书 / 在线网页")
    p.add_argument("--gutenberg", help="Project Gutenberg 电子书编号")
    p.add_argument("--wikisource", help="维基文库页面名，如 孫子兵法")
    p.add_argument("--ctext", help="ctext.org 书名 slug，如 wenxin-diaolong（整本在线抓）")
    p.add_argument("--web", help="网页文章地址（自动提取正文）")
    p.add_argument("--url", help="任意纯文本 URL")
    p.add_argument("--limit", type=int, default=0, help="--ctext 时最多抓几章（0=全部）")
    p.add_argument("--out", help="输出工作目录")
    p.set_defaults(func=cmd_fetch)

    p = sub.add_parser("ingest", help="载入本地文件（txt/md/epub/pdf）")
    p.add_argument("path")
    p.add_argument("--out", help="输出工作目录")
    p.set_defaults(func=cmd_ingest)

    p = sub.add_parser("condense", help="压缩成材料包")
    p.add_argument("workdir")
    p.add_argument("--per-chapter", type=int, default=12, help="每章提取多少关键句")
    p.add_argument("--full", action="store_true", help="材料包里附全文（更贵，但更全）")
    p.add_argument("--exclude", action="append", default=[],
                   help="跳过章节，可重复：--exclude 答話 --exclude c15")
    p.add_argument("--max-per-chapter", type=int, default=100,
                   help="单章关键句上限（长章会按字数放大，这是天花板）")
    p.set_defaults(func=cmd_condense)

    p = sub.add_parser("tasks", help="生成提炼任务包 TASKS.md")
    p.add_argument("workdir")
    p.set_defaults(func=cmd_tasks)

    p = sub.add_parser("show", help="按段落 ID 回查原文")
    p.add_argument("workdir")
    p.add_argument("pid")
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("verify", help="质检产物")
    p.add_argument("workdir")
    p.add_argument("--min-citations", type=int, default=12)
    p.add_argument("--min-coverage", type=float, default=0.6)
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("pipe", help="一步跑完：取本 → 压缩 → 出任务包")
    p.add_argument("--gutenberg")
    p.add_argument("--wikisource")
    p.add_argument("--ctext", help="ctext.org 书名 slug，如 wenxin-diaolong")
    p.add_argument("--web", help="网页文章地址")
    p.add_argument("--url")
    p.add_argument("--limit", type=int, default=0, help="--ctext 时最多抓几章（0=全部）")
    p.add_argument("--out", required=True)
    p.add_argument("--per-chapter", type=int, default=12)
    p.add_argument("--max-per-chapter", type=int, default=100)
    p.add_argument("--full", action="store_true")
    p.add_argument("--exclude", action="append", default=[])
    p.set_defaults(func=cmd_pipe)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
