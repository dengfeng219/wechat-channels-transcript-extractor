# -*- coding: utf-8 -*-
"""解析器逻辑测试（多通道架构）。"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import _iso  # noqa: F401  (隔离 history/config，退出自动清理)
sys.stdout.reconfigure(encoding="utf-8")

from app import resolver  # noqa: E402
from app.resolver import FeedUnavailable, NeedLogin, normalize_feed  # noqa: E402

fails = []

def check(label, cond, detail=""):
    print("  %s %-44s %s" % ("✓" if cond else "✗", label, detail))
    if not cond:
        fails.append(label)

SHARE = "https://weixin.qq.com/sph/ARBFNO8PaW"
GOOD_MEDIA = {"url": "https://finder.video.qq.com/251/20302/stodownload?x=1",
              "decodeKey": "2136343393", "fileSize": 100, "width": 720, "height": 1280,
              "spec": [{"fileFormat": "xWT111", "durationMs": 52000}]}
PREVIEW = {"errCode": 0, "data": {
    "authorInfo": {"nickname": "果粒AI漫剧"},
    "feedInfo": {"description": "凤命轮回：弃婴渡世-第14集", "coverUrl": "https://x/c.jpg"},
    "sceneInfo": {"dynamicExportId": "export/DYN_111", "entryScene": 64},
    "errMsg": {"type": 0}}}
FULL = {"errCode": 0, "data": {
    "authorInfo": {"nickname": "果粒AI漫剧"},
    "feedInfo": {"description": "凤命轮回：弃婴渡世-第14集", "media": [GOOD_MEDIA]},
    "errMsg": {"type": 0}}}
DEAD = {"errCode": 0, "data": {"errMsg": {"type": 2, "title": "此内容暂时无法播放"}}}

_orig = (resolver._feed_call, resolver._parse_share_url, resolver._get_user_id,
         resolver._save_diagnostic)
resolver._save_diagnostic = lambda *a, **k: None

# ---- 1. 公开通道直接给媒体 -> 无需登录 ----
print("== 1. 公开通道直接返回媒体时，不应要求登录 ==")
resolver._feed_call = lambda payload, short_id="", page="feed": FULL
f = resolver.resolve(SHARE, cookie=None, verbose=False)
check("无需 Cookie 即成功", f["title"] == "凤命轮回：弃婴渡世-第14集")
check("解析出 decodeKey", f["media"][0]["decode_key"] == "2136343393")
check("时长换算正确", abs(f["duration_s"] - 52.0) < 0.1, "%.1fs" % f["duration_s"])

# ---- 2. 公开通道只给预览 + 无 Cookie -> NeedLogin ----
print()
print("== 2. 只有预览且无登录态时，提示登录并带上视频信息 ==")
resolver._feed_call = lambda payload, short_id="", page="feed": PREVIEW
try:
    resolver.resolve(SHARE, cookie=None, verbose=False)
    check("抛出 NeedLogin", False, "未抛出")
except NeedLogin as e:
    check("抛出 NeedLogin", True)
    check("提示里带上视频标题", "凤命轮回：弃婴渡世-第14集" in str(e))
    check("preview 一并返回", (e.preview or {}).get("data", {}).get("sceneInfo") is not None)

# ---- 3. 有登录态：多个组合依次尝试，最后一个命中 ----
print()
print("== 3. 有登录态时按顺序尝试多种组合 ==")
tried = []

def feed_multi(payload, short_id="", page="feed"):
    if "shortUri" in payload:
        tried.append("shortUri")
        return PREVIEW
    cid = payload.get("exportId")
    tried.append(cid)
    if cid == "export/DYN_111":   # 只有 dynamicExportId 这一个能成
        return FULL
    return DEAD

resolver._feed_call = feed_multi
resolver._parse_share_url = lambda u, c, user_id="": {
    "wx_export_id": "export/WXID_999",
    "playable_url": "https://channels.weixin.qq.com/x?token=TOK&eid=EID_PLAY",
}
resolver._get_user_id = lambda cookie: "user123"
f = resolver.resolve(SHARE, cookie="c", verbose=False)
check("最终拿到视频", f["media"][0]["url"].startswith("https://finder.video.qq.com"))
check("尝试顺序含 shortUri", "shortUri" in tried)
check("回退到 dynamicExportId", tried[-1] == "export/DYN_111", "顺序=%s" % tried)

# ---- 4. 全部失败 -> 可诊断的错误 + 诊断文件 ----
print()
print("== 4. 全部失败时给出可诊断错误 ==")
saved = {}

def feed_dead(payload, short_id="", page="feed"):
    if "shortUri" in payload:
        return PREVIEW
    return DEAD

resolver._feed_call = feed_dead
resolver._save_diagnostic = lambda *a, **k: saved.update({"called": True})
try:
    resolver.resolve(SHARE, cookie="c", verbose=False)
    check("抛出异常", False, "未抛出")
except RuntimeError as e:
    msg = str(e)
    check("抛出异常", "此内容暂时无法播放" in msg)
    for marker in ("诊断信息", "元宝返回字段", "generalToken", "尝试过的组合", "末次响应字段"):
        check("诊断块含 %s" % marker, marker in msg)
    check("写出诊断文件", saved.get("called") is True)

# ---- 5. token / exportId 多形态提取 ----
print()
print("== 5. generalToken / exportId 多形态提取 ==")
from app.resolver import _hunt, _TOKEN_KEYS, _EID_KEYS  # noqa: E402
CASES = {
    "playable_url 的 token": ({"playable_url": "https://a/b?token=T1&eid=E1"}, "T1", "E1"),
    "驼峰 generalToken": ({"playableUrl": "https://a/b?generalToken=T2&exportId=E2"}, "T2", "E2"),
    "顶层 token 字段": ({"playable_url": "https://a/b?eid=E3", "token": "T3"}, "T3", "E3"),
    "嵌套 data 里": ({"data": {"playable_url": "https://a/b?token=T4&eid=E4"}}, "T4", "E4"),
    "百分号编码": ({"playable_url": "https://a/b?token=T%2B5&eid=E%2B5"}, "T+5", "E+5"),
}
for name, (payload, wt, we) in CASES.items():
    t, _ = _hunt(payload, _TOKEN_KEYS)
    e, _ = _hunt(payload, _EID_KEYS)
    check(name, t == wt and e == we, "token=%s eid=%s" % (t or "无", e or "无"))

# ---- 6. 媒体嵌套结构容错 ----
print()
print("== 6. 各种响应嵌套结构都能定位媒体 ==")
M = [GOOD_MEDIA]
SHAPES = {
    "data.feedInfo.objectDesc.media": {"data": {"feedInfo": {"objectDesc": {"media": M}}}},
    "data.feedInfo.media": {"data": {"feedInfo": {"media": M, "description": "T"}}},
    "data.objectDesc.media": {"data": {"objectDesc": {"media": M}}},
    "data.object_desc.media": {"data": {"object_desc": {"media": M}}},
    "data.media": {"data": {"media": M}},
    "深层嵌套": {"data": {"a": {"b": {"c": {"objectDesc": {"media": M}}}}}},
    "数组包裹": {"data": {"items": [{"x": 1}, {"objectDesc": {"media": M}}]}},
}
for name, resp in SHAPES.items():
    check(name, resolver._has_media(resp))
check("空响应不误判", resolver._has_media({"data": {}}) is False)

# 还原
(resolver._feed_call, resolver._parse_share_url, resolver._get_user_id,
 resolver._save_diagnostic) = _orig

# ---- 7. 新版 feedInfo（videoUrl / h264VideoInfo）----
print()
print("== 7. 新版结构：feedInfo 直接给 videoUrl，没有 media 数组 ==")
H264 = "https://finder.video.qq.com/251/20302/stodownload?encfilekey=h264"
H265 = "https://finder.video.qq.com/251/20302/stodownload?encfilekey=h265"
NEW_CASES = {
    "feedInfo.videoUrl": {"data": {"feedInfo": {"description": "T", "mediaType": 4,
                                          "videoUrl": H264, "coverUrl": "https://x/c.jpg"}}},
    "h264VideoInfo.videoUrl": {"data": {"feedInfo": {"description": "T",
                                                   "h264VideoInfo": {"videoUrl": H264}}}},
    "h265VideoInfo.videoUrl": {"data": {"feedInfo": {"description": "T",
                                                   "h265VideoInfo": {"videoUrl": H265}}}},
    "h264 优先于 h265": {"data": {"feedInfo": {"h264VideoInfo": {"videoUrl": H264},
                                             "h265VideoInfo": {"videoUrl": H265}}}},
}
for name, resp in NEW_CASES.items():
    check("识别 " + name, resolver._has_media(resp))
    f = normalize_feed(resp)
    check("  取到 url " + name, f["media"][0]["url"].startswith("https://finder.video.qq.com"),
          f["media"][0]["url"][-12:])
check("新版结构 decode_key 为空（明文 MP4）",
      normalize_feed(NEW_CASES["feedInfo.videoUrl"])["media"][0]["decode_key"] == "")

# ---- 8. token 必须优先取 playable_url，而不是 cover_url ----
print()
print("== 8. generalToken 必须来自 playable_url（cover_url 有同名参数）==")
from app.resolver import _hunt, _TOKEN_KEYS  # noqa: E402
MIXED = {
    "cover_url": "https://finder.video.qq.com/251/20350/stodownload?encfilekey=zz&token=COVER_CDN_TOKEN",
    "playable_url": "https://channels.weixin.qq.com/x?token=REAL_GENERAL_TOKEN&eid=E1",
    "wx_export_id": "export/WX",
}
got, src = _hunt(MIXED, _TOKEN_KEYS, prefer=("playable",))
check("取到 playable_url 的 token", got == "REAL_GENERAL_TOKEN", "得到 %s（来源 %s）" % (got[:20], src))
bad, bsrc = _hunt(MIXED, _TOKEN_KEYS)
check("不加 prefer 会取错（回归保护）", bad != "REAL_GENERAL_TOKEN", "得到 %s" % bad[:20])

print()
print("PASS" if not fails else "FAIL: %s" % fails)
sys.exit(1 if fails else 0)
