# -*- coding: utf-8 -*-
"""快速页面结构断言（纯 HTTP，不需要浏览器）。"""
import json
import sys
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")
BASE = "http://127.0.0.1:8765"
fails = []

def check(label, cond, detail=""):
    print("  %s %-42s %s" % ("✓" if cond else "✗", label, detail))
    if not cond:
        fails.append(label)

def get(p):
    with urllib.request.urlopen(BASE + p, timeout=20) as r:
        return r.read().decode("utf-8", "replace")

html = get("/")
print("页面 %d 字节" % len(html))

print()
print("== 折叠相关结构 ==")
for token, desc in [
    (".ghead{", "分组标题样式"),
    (".gbody{display:none", "折叠体默认隐藏"),
    (".ghead.open .caret{transform:rotate(90deg)", "展开时箭头旋转"),
    ("data-gtoggle=", "分组标题带可点击标记"),
    ("data-gbody=", "折叠体带标记"),
    ("histExpandAll", "全部展开按钮"),
    ("histCollapseAll", "全部折叠按钮"),
    ("OPEN_GROUPS", "展开状态记录"),
    ("wxt_open_groups", "展开状态存到浏览器本地"),
    ("function toggleGroup", "切换函数"),
    ("ev.target.closest('[data-gtoggle]')", "点击委托"),
]:
    check(desc, token in html)

print()
print("== 分组标题带摘要 ==")
check("显示集数", "' 集'" in html or " 集</span>" in html or "items.length + ' 集'" in html)
check("显示最新一集", "'　最新 '" in html)

print()
print("== 接口连通 ==")
env = json.loads(get("/api/env"))
check("应用在线", bool(env.get("engines")), "引擎 %s" % ",".join(env["engines"]))
h = json.loads(get("/api/history"))
check("历史有记录", h["total"] > 0, "%d 条" % h["total"])
groups = {}
for e in h["entries"]:
    groups.setdefault(e.get("group") or "(未分组)", 0)
    groups[e.get("group") or "(未分组)"] += 1
for g, n in groups.items():
    print("     %s：%d 集" % (g, n))

print()
print("PASS" if not fails else "FAIL: %s" % fails)
sys.exit(1 if fails else 0)
