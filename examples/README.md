# 示例产物

这两个目录是**真实跑出来的**蒸馏结果，原样放在这里，方便你先看效果再决定要不要用工具。

| 目录 | 来源 | 取本方式 | 规模 |
|---|---|---|---|
| `sunzi/` | 维基文库《孫子兵法》（公版原文） | `--wikisource` | 14 章 / 51 处引用 / 质检全过 |
| `wenxin/` | ctext.org《文心雕龍》 | `--ctext wenxin-diaolong` | 50 章 / 87 处引用 / 质检全过 |

每个目录下两个文件：

- `SKILL.md` —— 最终产物，可执行的方法论。含核心模型（每个都写了**什么时候失效**）、执行流程、判断清单、反例与失败模式。
- `REPORT.md` —— 质检报告，逐项列出检查结果。

## 关于路径

`SKILL.md` 里会出现 `work/sunzi/c04p003` 这种段落 ID 引用。回查原文需要完整的 `work/` 目录
（含 `index.json`），而 `work/` 因为体积大没有入库（见 `.gitignore`）。想复现就自己跑一遍：

```bash
python3 dz.py pipe --wikisource 孫子兵法 --out work/sunzi
python3 dz.py show work/sunzi c04p003
```

原始的 `work/sunzi` 和 `work/wenxin` 就是这么来的。
