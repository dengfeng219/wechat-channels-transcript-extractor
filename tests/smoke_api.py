# -*- coding: utf-8 -*-
"""接口冒烟测试：页面、Cookie 导入、一键登录状态。"""
import json
import sys
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")
BASE = "http://127.0.0.1:8765"

def post(path, obj):
    req = urllib.request.Request(BASE + path, data=json.dumps(obj).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))

def get_raw(path):
    with urllib.request.urlopen(BASE + path, timeout=20) as r:
        return r.status, r.read().decode("utf-8")

def get(path):
    with urllib.request.urlopen(BASE + path, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))

fail = 0

def check(label, cond, detail=""):
    global fail
    print("  %s %-30s %s" % ("✓" if cond else "✗", label, detail))
    if not cond:
        fail += 1

print("== 页面 ==")
st, html = get_raw("/")
check("首页可访问", st == 200, "%d 字节" % len(html))
check("含「一键获取登录态」", "一键获取登录态" in html)
check("含第三方请求告警", "api.aida.qq.com" in html)
check("含 cURL 引导", "以 cURL 格式复制" in html)

print()
print("== Cookie 导入 ==")
r = post("/api/import_cookie",
         {"text": 'curl "https://yuanbao.tencent.com/api/getuserinfo" '
                  '-H "cookie: hy_user=abc123; hy_token=xyz789" -H "accept: */*"'})
check("cURL 格式", r.get("ok") and r.get("cookie") == "hy_user=abc123; hy_token=xyz789",
      "-> %s" % r.get("cookie"))
check("登录态校验已执行", r.get("login_ok") is False, "(%s)" % r.get("message"))

r = post("/api/import_cookie", {"text": "hy_user=aaa; hy_token=bbb"})
check("原始 Cookie 串", r.get("cookie") == "hy_user=aaa; hy_token=bbb", "-> %s" % r.get("cookie"))

r = post("/api/import_cookie", {"text": "这里没有 cookie"})
check("无效输入被拒绝", r.get("ok") is False, "-> %s" % r.get("error"))

print()
print("== 一键登录接口 ==")
s = get("/api/browser_login_status")
check("状态接口可用", "stage" in s, "stage=%s" % s.get("stage"))

print()
print("PASS" if fail == 0 else "FAIL: %d 项未通过" % fail)
sys.exit(0 if fail == 0 else 1)
