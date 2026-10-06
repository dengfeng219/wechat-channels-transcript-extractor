# -*- coding: utf-8 -*-
"""用本机保存的登录态，真实提取 ARBFNO8PaW 这条视频的文案。"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8")

from app import config                      # noqa: E402
from app.resolver import check_login        # noqa: E402

URL = sys.argv[1] if len(sys.argv) > 1 else "https://weixin.qq.com/sph/ARBFNO8PaW"
# 手动验证跑默认写到临时目录，避免污染用户真实的 output/
import tempfile  # noqa: E402
OUTDIR = sys.argv[2] if len(sys.argv) > 2 else os.path.join(tempfile.gettempdir(), "wxt_manual_out")

ck = (config.get("yuanbao_cookie") or "").strip()
print("登录态项数:", len(ck.split("; ")))
names = [p.split("=", 1)[0] for p in ck.split("; ") if "=" in p]
print("包含:", ", ".join(names))
print()
ok, msg = check_login(ck)
print("登录态校验:", "有效 ✓" if ok else "无效 ✗", "-", msg)
if not ok:
    sys.exit(2)

print()
print("=" * 68)
print("开始提取:", URL)
print("=" * 68)

from app.pipeline import process  # noqa: E402

last = [""]
def prog(info):
    line = "[%5.1f%%] %s  %s" % (info.get("percent", 0), info.get("stage", ""), info.get("message", ""))
    if line != last[0]:
        print(line, flush=True); last[0] = line

try:
    r = process({"source": "link", "url": URL, "engine": "paraformer", "language": "zh",
                 "outdir": OUTDIR}, on_progress=prog)
except Exception as e:
    print()
    print("!!! 失败 !!!")
    print("%s: %s" % (type(e).__name__, e))
    sys.exit(1)

print()
print("=" * 68)
print("成功！耗时 %.1f 秒" % r["elapsed"])
print("标题:", r["meta"].get("title"))
print("作者:", r["meta"].get("author"))
print("=" * 68)
for p in r["paragraphs"]:
    print(p["text"])
    print()
print("输出文件:")
for k, v in r["files"].items():
    print("  %-6s %s" % (k, v))
