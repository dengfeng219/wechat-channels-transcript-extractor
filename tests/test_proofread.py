# -*- coding: utf-8 -*-
"""文案校对测试：固定替换表 + 自定义规则 + 接口。"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import _iso  # noqa: F401  (隔离 history/config，退出自动清理)
sys.stdout.reconfigure(encoding="utf-8")

from app import config, proofread  # noqa: E402

fails = []

def check(label, cond, detail=""):
    print("  %s %-44s %s" % ("✓" if cond else "✗", label, detail))
    if not cond:
        fails.append(label)

print("== 1. 内置替换表（你反馈的真实错例）==")
CASES = [
    ("就算这里了，点个恨通。", "看到这里了，点个赞吧。"),
    ("这小的山窝留不接", "这小的山窝留不住"),
    ("一花去梅韵，一花保平安", "一花去霉运，一花保平安"),
    ("老愿皆承", "所愿皆成"),
    ("青瘦身影莫入", "青瘦身影没入"),
    ("传送他的善举", "传颂他的善举"),
    ("造福相邻", "造福乡邻"),
    ("早晚也难逃天道成罚", "早晚也难逃天道惩罚"),
    ("李秀琴已经安享离世", "李秀琴已经安然离世"),
]
for bad, want in CASES:
    got, hits = proofread.apply_rules(bad)
    check(repr(bad)[:26], got == want, "-> %s" % got)

print()
print("== 2. 不该改的不能改 ==")
for text in ("正常的一句话，没有任何错字。", "第二天一早，人们发现李秀琴已经安然离世。"):
    got, hits = proofread.apply_rules(text)
    check("不改动 " + repr(text)[:20], got == text and not hits)

print()
print("== 3. 自定义替换（config.json）==")
config.save({"proofread_rules": [["张三", "张叁"], ["错别词", "正确词"]]})
proofread.invalidate_cache()
got, hits = proofread.apply_rules("张三说了错别词")
check("自定义规则生效", got == "张叁说了正确词", "-> %s" % got)
check("内置规则仍生效", proofread.apply_rules("留不接")[0] == "留不住")
config.save({"proofread_rules": []})
proofread.invalidate_cache()

print()
print("== 4. 没配 Key 时不调 LLM ==")
check("has_llm 为 False", proofread.has_llm() is False)
out, note = proofread.proofread_with_llm("随便一段话")
check("原样返回", out == "随便一段话", note)

print()
print("== 5. 接口 ==")
import threading  # noqa: E402
import time  # noqa: E402
import urllib.request  # noqa: E402

PORT = 8795
BASE = "http://127.0.0.1:%d" % PORT
from app.server import serve  # noqa: E402
threading.Thread(target=serve, kwargs={"port": PORT, "open_browser": False},
                 daemon=True).start()
time.sleep(1.2)

def get(p):
    with urllib.request.urlopen(BASE + p, timeout=20) as r:
        return json.loads(r.read().decode())

def post(p, o):
    req = urllib.request.Request(BASE + p, data=json.dumps(o).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())

info = get("/api/proofread/info")
check("info 接口可用", info["ok"] and info["builtin_rules"] > 10,
      "%d 条内置规则" % info["builtin_rules"])
r = post("/api/proofread/test", {"text": "就算这里了，点个恨通。"})
check("test 接口能纠错", r["after_rules"] == "看到这里了，点个赞吧。", r["after_rules"])
r = post("/api/proofread/save", {"rules": "甲=乙\n丙=丁"})
check("保存自定义规则", r["ok"] and r["rules"] == 2, "%d 条" % r["rules"])
r = post("/api/proofread/test", {"text": "甲和丙"})
check("新规则立刻生效", r["after_rules"] == "乙和丁", r["after_rules"])
h = urllib.request.urlopen(BASE + "/", timeout=15).read().decode()
check("页面含校对设置", "proofBox" in h and "llmKey" in h)

print()
print("PASS" if not fails else "FAIL: %s" % fails)
sys.exit(1 if fails else 0)
