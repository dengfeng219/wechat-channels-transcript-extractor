# -*- coding: utf-8 -*-
"""输出目录命名规则测试。"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import _iso  # noqa: F401
sys.stdout.reconfigure(encoding="utf-8")

from app.naming import clean_name, group_of, plan_folders, split_series  # noqa: E402

fails = []

def check(label, cond, detail=""):
    print("  %s %-44s %s" % ("✓" if cond else "✗", label, detail))
    if not cond:
        fails.append(label)

print("== 1. 短剧名 / 集数 拆分 ==")
CASES = [
    ("凤命轮回：弃婴渡世-第14集", "凤命轮回：弃婴渡世", "第14集"),
    ("凤命轮回：弃婴渡世第15集", "凤命轮回：弃婴渡世", "第15集"),
    ("【逆天改命】第03集", "逆天改命", "第03集"),   # 首尾括号会被清理，更干净
    ("都市之王者归来 第 7 话", "都市之王者归来", "第 7 话"),
    ("Season2-EP12", "Season2", "EP12"),
    ("某剧 第１４集", "某剧", "第１４集"),
    ("带孩子来北京旅游第一天我就后悔了", "", ""),
    ("", "", ""),
]
for raw, want_series, want_ep in CASES:
    s, e = split_series(raw)
    ok = (s == want_series and e == want_ep)
    check(repr(raw)[:34], ok, "-> (%r, %r)" % (s, e))

print()
print("== 2. 上层文件夹（短剧名优先，其次账号）==")
check("有短剧名用短剧名", group_of("凤命轮回：弃婴渡世-第14集", "果粒AI漫剧") == "凤命轮回：弃婴渡世")
check("无短剧名退化为账号", group_of("带孩子来北京旅游", "果粒AI漫剧") == "果粒AI漫剧")
check("都没有则为空", group_of("随便一个视频", "") == "")

print()
print("== 3. 非法字符清理 ==")
check("斜杠冒号被替换", clean_name('a/b:c*d?e"f<g>h|i') == "a_b_c_d_e_f_g_h_i")
check("首尾分隔符去掉", clean_name("--第14集--") == "第14集")
check("空串走 fallback", clean_name("   ", fallback="未命名") == "未命名")

print()
print("== 4. 目录规划 ==")
p, inner, meta = plan_folders(r"D:\out", "凤命轮回：弃婴渡世-第14集", "果粒AI漫剧")
check("父目录 = 短剧名", p == r"D:\out\凤命轮回：弃婴渡世", p)
check("任务目录 = 集数", inner == "第14集", inner)
check("返回分组信息", meta["series"] == "凤命轮回：弃婴渡世" and meta["episode"] == "第14集")

p2, inner2, _ = plan_folders(r"D:\out", "带孩子来北京旅游", "果粒AI漫剧")
check("非短剧按账号分组", p2 == r"D:\out\果粒AI漫剧", p2)
check("任务目录 = 标题", inner2 == "带孩子来北京旅游", inner2)

p3, inner3, _ = plan_folders(r"D:\out", "凤命轮回-第3集", "", fallback_stamp="task_1")
check("无账号也在短剧名下", p3 == r"D:\out\凤命轮回", p3)
check("任务目录 = 第3集", inner3 == "第3集", inner3)

print()
print("PASS" if not fails else "FAIL: %s" % fails)
sys.exit(1 if fails else 0)
