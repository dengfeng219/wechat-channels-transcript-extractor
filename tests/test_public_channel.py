# -*- coding: utf-8 -*-
"""对真实分享链接测试「公开预览通道」（实时调用微信接口，无需登录）。"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import _iso  # noqa: F401  (隔离 history/config，退出自动清理)
sys.stdout.reconfigure(encoding="utf-8")

# 隔离：不要读到用户真实保存的登录态/历史，否则「无登录态」这条断言就没意义了

from app.resolver import (NeedLogin, _feed_call, _extract_short_id,  # noqa: E402
                          is_share_url, resolve)

URL = sys.argv[1] if len(sys.argv) > 1 else "https://weixin.qq.com/sph/ARBFNO8PaW"
fails = []

def check(label, cond, detail=""):
    print("  %s %-38s %s" % ("✓" if cond else "✗", label, detail))
    if not cond:
        fails.append(label)

print("=" * 64)
print("链接:", URL)
check("链接格式合法", is_share_url(URL))
sid = _extract_short_id(URL)
check("能取出短号", bool(sid), sid)
print("=" * 64)

data = _feed_call({"baseReq": {"generalToken": ""}, "shortUri": sid},
                  short_id=sid, page="sph")
fi = (data.get("data") or {}).get("feedInfo") or {}
ai = (data.get("data") or {}).get("authorInfo") or {}
sc = (data.get("data") or {}).get("sceneInfo") or {}

print("标题          :", fi.get("description"))
print("作者          :", ai.get("nickname"))
print("点赞/评论/转发:", fi.get("likeCountFmt"), "/", fi.get("commentCountFmt"),
      "/", fi.get("forwardCountFmt"))
print("dynamicExportId:", str(sc.get("dynamicExportId"))[:60])
print()

check("公开通道无需登录即可拿到标题", bool(fi.get("description")), str(fi.get("description"))[:24])
check("公开通道能拿到作者", bool(ai.get("nickname")), ai.get("nickname"))
check("公开通道不含视频地址（符合预期）", not (data.get("data") or {}).get("media"))

print()
print("调用完整 resolve（本测试内无登录态）：")
try:
    f = resolve(URL, cookie=None, verbose=False)
    check("无登录态时不应直接成功", False, "却拿到了 %d 个媒体" % len(f.get("media") or []))
except NeedLogin as e:
    check("按预期抛出 NeedLogin", True)
    check("提示里带上视频标题", "《" in str(e) and "》" in str(e))
    print("   提示:", str(e).split(chr(10))[-1][:70])
except Exception as e:
    check("抛出的是 NeedLogin", False, "%s: %s" % (type(e).__name__, e))

print()
print("PASS" if not fails else "FAIL: %s" % fails)
sys.exit(1 if fails else 0)
