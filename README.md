# 蒸馏工坊 book-distiller

把一本书变成**可执行的方法论**——不是读书笔记，是能照着做的流程、判据和检查清单。

零第三方依赖（读 PDF 除外，可选），纯 Python 标准库 + 命令行。产物是普通文件，跟 AI 平台无关。

## 它和同类工具的差别

| | 常见做法（如 nuwa / 各类蒸馏工具） | 蒸馏工坊 |
|---|---|---|
| 原材料 | 全网搜公开信息（多是二手转述） | **原文在手**——你给的书、或公版书全文 |
| 成本控制 | 全文丢给模型，烧 token | 先用纯 Python 压缩（实测压到原文的 25% 左右），模型只在压过的材料上工作 |
| 可追溯 | 结论无法回查，容易混入编造 | **每条结论挂段落 ID**，`dz.py show` 一键回查原文 |
| 质检 | 全文搜「局限」「张力」等关键词，写几个字就能过 | 逐条核对引用能否解析、模型有没有写失效条件、章节覆盖够不够 |
| 路径 | 常写死某个 runtime 的目录 | 与 runtime 无关，产物就是普通文件 |

## 安装

```bash
git clone https://github.com/liuhongzhang-create/book-distiller.git
cd book-distiller

# 直接用，不安装
python3 dz.py --help

# 或者装成命令 `dz`（可选）
python3 -m pip install -e .
```

需要 Python 3.9+。读 PDF 才需要额外装 `pypdf`（`python3 -m pip install -e ".[pdf]"`），其余功能零依赖。

## 看一眼产出

不想先跑一遍的话，`examples/` 里有真实产物：

- `examples/sunzi/SKILL.md` —— 从《孫子兵法》蒸出的竞争决策方法论，14 章 / 51 处引用。
- `examples/wenxin/SKILL.md` —— 从 ctext.org 在线蒸完整本《文心雕龍》，50 章 / 87 处引用。

每个模型长这样（摘一段）：

> ### 模型一：先胜后战
> - **一句话**：胜负在开打之前就定了，打只是把已经定下的结果取回来。
> - **原文依据**：「昔之善戰者，先為不可勝，以待敵之可勝」`[c04p000]`
> - **什么时候失效**：**当窗口期极短、机会只出现一次时，此模型失效**——先求不可胜会慢一步。

「什么时候失效」这一条是**硬性要求**，不写质检不给过。这是它和"总结型"工具最大的区别：只讲怎么用、不讲什么时候不管用的方法论，是没法照做的。

## 三层产物

```
work/<书名>/
├── raw/          取本原文
├── book.json     标准化结构（章 + 段落）
├── index.json    段落 ID → 原文（回查用）
├── prep/         压缩后的材料包（给 AI 读的）
│   ├── 00-overview.md   全书地图 + 高频词 + 章节表
│   └── cXX.md           每章的关键句（带段落 ID）
├── TASKS.md      提炼任务包（含输出契约）
├── SKILL.md      ← 最终产物：可执行方法论
└── REPORT.md     质检报告
```

## 快速开始

```bash
# 一步跑完：取本 → 切章 → 压缩 → 出任务包
python3 dz.py pipe --wikisource 孫子兵法 --out work/sunzi
python3 dz.py pipe --gutenberg 132 --out work/artofwar

# 在线蒸（不下载电子书文件）
python3 dz.py pipe --ctext wenxin-diaolong --out work/wenxin   # 整本，逐章抓
python3 dz.py pipe --web https://example.com/long-article      # 单篇网页

# 自己的电子书
python3 dz.py ingest ~/Desktop/我的书.epub --out work/mine
python3 dz.py condense work/mine --per-chapter 15

# 质检 / 回查原文 / 看章节
python3 dz.py verify work/sunzi
python3 dz.py show work/sunzi c04p003
```

压缩完成后，让 AI 读 `TASKS.md` + `prep/`，产出 `SKILL.md`，再跑 `verify`。

## 支持的来源

| 来源 | 状态 | 说明 |
|---|---|---|
| 你自己的电子书（EPUB / TXT / MD） | ✅ | 零依赖 |
| 你自己的 PDF | ✅ | 需 `pip install pypdf`（首次会提示装法） |
| Project Gutenberg 公版书 | ✅ | `--gutenberg <编号>` |
| 维基文库中文经典 | ✅ | `--wikisource 孫子兵法` |
| 任意纯文本 URL | ✅ | `--url` |
| **ctext.org 整本古籍** | ✅ | `--ctext <slug>`，按书的目录逐章在线抓取后合并 |
| **任意网页正文** | ✅ | `--web <url>`，按「字数多 × 链接少」挑出正文块 |
| ctext.org 网页 | ✅ | 免授权；注意只有 API 需要授权，网页不需要 |
| 国家哲学社会科学文献中心 ncpssd.org | ✅ | 免费·官方，需注册账号后下载 |

### 明确不支持

**盗版电子书站（Z-Library、LibGen、各类镜像）不接。** 原因不是道德姿态，是三条实际后果：

1. 未经授权分发受版权保护的书是侵权行为；用它蒸出来的内容再拿去交付或变现，把侵权链条接进了自己的业务。
2. 盗版文件质量不可控（错字、缺页、拼接错误），蒸出来的方法论看起来照样像样，但错在里面。
3. 这类站点随时被封，工具建在上面等于地基是流沙。

**图书馆（国图、世图等）拿不到全文。** 实测结论（2026-09-21）：

- 国图门户与古籍详情页**免登录可读**，能拿到**书目元数据 + 目录**（`POST read.nlc.cn/allSearch/formatCatalog`，参数 `id` + `indexName`）。
- **全文与影像拿不到**：阅读器 page 内含四道权限门（`dataInOutPermission` / `resInOutPermission` / `resIpPermission` / `permissionNew`），未登录一律返回 `{"obj":null,"success":false}`。
- 即使能看，国图的「在线阅读」本质是**扫描件 PDF**（详情页里注释掉的原始路径就是 `*.pdf`），要蒸馏必须先 OCR，而 OCR 的错字会原样蒸进产物。
- 技术上还有两个坑：`read.nlc.cn` **只有 HTTP、没有 HTTPS**（TLS 握手失败）；`/allSearch/permission`、`formatCatalog`、`/OutOpenBook/gotoPage` 都是 **POST-only**，GET 返 405。

所以国图在本工具里的定位是**核版本、查目录结构**，不是取正文。工具不假装能做这件事。

## 已知限制（诚实写下来）

- **PDF 抽取质量取决于文件本身**：扫描件没有文字层，抽出来是空的，需要先 OCR。
- **中文关键词用二元组近似，不是真分词**：省掉了 jieba 依赖，代价是会产出少量噪声词（如人名组合）。方法论类书籍上够用，文学类文本会差一些。
- **压缩是抽取式，不是摘要式**：只挑原句，不生成新句。好处是不会引入编造，坏处是长段落可能被截断。
- **`--full` 模式**会把全文放进材料包，更全但更贵。
- **中文网页可能有简体/繁体差异**：ctext 部分书只有繁体本，`?if=gb` 不一定能转简。高频词会显示为繁体。
- **网页正文提取靠启发式**，不是浏览器渲染。内容靠 JS 加载的页面、需要登录的页面抓不到，工具会明确报错而不是给半截内容。
- **每章的关键句额度按章长缩放**（每 1000 字约 `--per-chapter` 句，上限 `--max-per-chapter`，默认 100）。早先写死固定句数，导致一本 6.6 万字的单章网页只被抽 12 句——这个缺陷已修，回归测试钉住了。
- **没有任何自动判断「这本书值不值得蒸」的能力**——烂书蒸出来照样是合格的烂书。
- **章节识别靠标题的写法**，认这几种：中文「第X章/回/节/篇/卷/部」、`== 维基标题 ==`、markdown `#`、英文 `CHAPTER I` / `Chapter I.` / `Chapter 1`。排版不规范的电子书（标题混在段落里、不独占一行）会退化成一整章，这时需要先手工整理标题。目录页里连续紧邻排列的章标题会被识别并跳过，避免正文被目录吞掉。

## 测试

```bash
python3 -m unittest discover -s tests
# 或者不依赖网络的冒烟测试
bash scripts/smoke.sh
```

56 项，覆盖：维基模板嵌套剥离、章节切分（中英文标题、目录页跳过、同名分卷章不误删）、
段落 ID 稳定性、压缩不丢章、排除章节、关键句额度随章长缩放、
网页正文提取（实体解码 / `<br>` 换行 / 导航区识别 / 短行不丢）、
ctext 目录解析（卷级页去重、自身链接排除、标签单元格排除、单章失败不拖垮整本）、
以及质检能否真的拦住问题产物（编造引用 / 缺章节 / 没写失效条件 / 覆盖不足 / 堆关键词蒙混）。

## 项目结构

```
dz.py             命令行入口
dzlib/
├── text.py       清洗 / 分句 / 词频（中文用二元组近似，不引 jieba）
├── fetch.py      Gutenberg / 维基文库 / URL 取本
├── web.py        ctext 整本抓取、任意网页正文提取
├── ingest.py     本地 txt/md/epub/pdf → 标准化 Book（章 + 段落）
├── condense.py   压缩成材料包（关键句额度随章长缩放）
├── pack.py       生成提炼任务包 TASKS.md
└── verify.py     质检：引用能否解析、模型有无失效条件、章节覆盖
tests/test_dz.py     56 项测试
scripts/smoke.sh     离线冒烟测试（不依赖外网）
examples/            真实产物样例
```

## License

MIT
