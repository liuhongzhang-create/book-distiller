#!/usr/bin/env bash
# 离线冒烟测试：不依赖任何外部站点，验证本地全链路能跑通。
# 用法：bash scripts/smoke.sh
set -euo pipefail

PY="${PY:-python3}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "==> CLI 可用"
"$PY" "$ROOT/dz.py" --help > /dev/null

echo "==> 造一本本地测试书"
"$PY" - "$TMP/book.txt" <<'PY'
import sys
from pathlib import Path

ch1 = "这是第一章的正文。它的作用是让压缩环节有足够多的句子可以挑。" * 20
ch2 = "这是第二章的正文。它验证章节切分与关键句额度是否随章长缩放。" * 20
text = f"第一章 开端\n\n{ch1}\n\n第二章 转折\n\n{ch2}\n"
Path(sys.argv[1]).write_text(text, encoding="utf-8")
PY

cd "$TMP"

echo "==> ingest"
"$PY" "$ROOT/dz.py" ingest book.txt --out work/demo > /dev/null
test -f work/demo/book.json
test -f work/demo/index.json

echo "==> condense"
"$PY" "$ROOT/dz.py" condense work/demo > /dev/null
test -f work/demo/prep/00-overview.md
test -f work/demo/prep/c01.md

echo "==> tasks"
"$PY" "$ROOT/dz.py" tasks work/demo > /dev/null
test -f work/demo/TASKS.md

echo "==> show（段落 ID 回查原文）"
"$PY" "$ROOT/dz.py" show work/demo c01p000 | head -3

echo "==> verify 应拦住没写 SKILL.md 的情况"
if "$PY" "$ROOT/dz.py" verify work/demo > /dev/null 2>&1; then
  echo "❌ 质检本该失败却通过了"
  exit 1
fi
echo "✅ 冒烟测试全过"
