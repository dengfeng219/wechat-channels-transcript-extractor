# -*- coding: utf-8 -*-
"""把 index.html 里的内联 JS 抽出来，用 node --check 做语法检查。"""
import os
import re
import subprocess
import sys
import tempfile

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8")

html = open(os.path.join(PROJ, "web", "index.html"), encoding="utf-8").read()
blocks = re.findall(r"<script>(.*?)</script>", html, re.S)
print("内联 script 块:", len(blocks))
if not blocks:
    print("FAIL: 没找到 script"); sys.exit(1)

js = "\n".join(blocks)
tmp = os.path.join(tempfile.gettempdir(), "wxt_check.js")
open(tmp, "w", encoding="utf-8").write(js)
print("JS 长度:", len(js))

node = None
for c in (r"C:\Program Files\nodejs\node.exe", "node"):
    try:
        subprocess.run([c, "--version"], capture_output=True, timeout=15, check=True)
        node = c
        break
    except Exception:
        continue
if not node:
    print("SKIP: 没找到 node"); sys.exit(2)

# 顶层 await 在普通脚本里不合法，这里用 --input-type=module 包一层不合适，
# 直接 --check 即可（我们的代码里没有顶层 await）。
r = subprocess.run([node, "--check", tmp], capture_output=True, text=True,
                   encoding="utf-8", errors="replace", timeout=30)
if r.returncode == 0:
    print("PASS: JS 语法正确")
    sys.exit(0)
print("FAIL: JS 有语法错误")
print(r.stderr[:1500])
sys.exit(1)
