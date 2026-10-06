# -*- coding: utf-8 -*-
"""
端到端集成测试：用一个"模拟已登录"的本地服务，跑通
  解析(公开通道 -> 元宝通道) -> 下载 -> 解密 -> 音轨 -> 语音识别 -> 文案文件

这验证的是：只要拥有元宝登录态，整条链路一定能出文案。
（真实接口需要用户扫码，测试用本地 mock 替代网络部分，其余全部是真实代码。）
"""
import json
import os
import random
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import _iso  # noqa: F401  (隔离 history/config，退出自动清理)

sys.stdout.reconfigure(encoding="utf-8")

# 隔离测试：不要读写用户真实的登录态配置

MOCK_PORT = 18761
MOCK = "http://127.0.0.1:%d" % MOCK_PORT
SHORT_ID = "ARBFNO8PaW"
TOKEN = "GENERAL_TOKEN_ABC123"
EID = "export/UzFfBgAAxOygcAUjeICKk8zT4DCghqmRqVXgcBw3FmNpNDgZwQ"

ENC = os.path.join(HERE, "wx_encrypted.mp4")
DEC = os.path.join(HERE, "wx_decrypted.mp4")
KEY = "2136343393"

class Mock(BaseHTTPRequestHandler):
    """模拟腾讯元宝 + 微信 get_feed_info + 视频 CDN。"""

    def log_message(self, *a):
        pass

    def _send(self, obj, code=200, raw=None, ctype="application/json"):
        body = raw if raw is not None else json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        p = self.path.split("?")[0]
        if p == "/api/getuserinfo":
            if "hy_user" not in (self.headers.get("Cookie") or ""):
                return self._send({"error": {"code": "20001", "message": "token无效"}}, 401)
            return self._send({"data": {"userId": "user-9527"}})
        if p == "/video.mp4":
            with open(ENC, "rb") as f:
                data = f.read()
            return self._send(None, raw=data, ctype="video/mp4")
        return self._send({"error": "not found"}, 404)

    def do_POST(self):
        p = self.path.split("?")[0]
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n).decode("utf-8")) if n else {}

        # 元宝解析
        if p == "/api/weixin/get_parse_result":
            if "hy_user" not in (self.headers.get("Cookie") or ""):
                return self._send({"error": {"code": "20001", "message": "token无效"}}, 401)
            return self._send({"data": {
                "wx_export_id": EID,
                "playable_url": ("https://channels.weixin.qq.com/finder-preview/pages/feed"
                                 "?entry_card_type=48&comment_scene=39&appid=0"
                                 "&token=%s&entry_scene=0&eid=%s" % (TOKEN, EID)),
            }})

        # 微信 get_feed_info
        if "get_feed_info" in p:
            base = body.get("baseReq") or {}
            if "shortUri" in body:
                # 公开预览通道：给元信息，不给媒体
                return self._send({"errCode": 0, "errMsg": "", "data": {
                    "authorInfo": {"nickname": "果粒AI漫剧"},
                    "feedInfo": {"description": "凤命轮回：弃婴渡世-第14集",
                                 "coverUrl": "https://x/cover.jpg", "picInfo": []},
                    "sceneInfo": {"dynamicExportId": "export/DYN_999",
                                  "entryScene": 64, "entryCardType": 48, "commentScene": 39},
                    "errMsg": {"type": 0}}})
            # exportId 通道：必须带正确 token
            if base.get("generalToken") != TOKEN:
                return self._send({"errCode": 0, "errMsg": "", "data": {
                    "errMsg": {"type": 2, "title": "此内容暂时无法播放"}}})
            return self._send({"errCode": 0, "errMsg": "", "data": {
                "authorInfo": {"nickname": "果粒AI漫剧"},
                "feedInfo": {
                    "description": "凤命轮回：弃婴渡世-第14集",
                    "coverUrl": "https://x/cover.jpg",
                    "media": [{
                        "url": MOCK + "/video.mp4",
                        "decodeKey": KEY,
                        "fileSize": os.path.getsize(ENC),
                        "width": 720, "height": 1280, "mediaType": 4,
                        "spec": [{"fileFormat": "xWT111", "codingFormat": "h264",
                                  "durationMs": 52300, "width": 720, "height": 1280}],
                    }]},
                "errMsg": {"type": 0}}})
        return self._send({"error": "not found"}, 404)

def main():
    if not os.path.exists(ENC):
        print("SKIP: 缺少加密样本"); return 2

    srv = ThreadingHTTPServer(("127.0.0.1", MOCK_PORT), Mock)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    time.sleep(0.4)

    os.environ["WXT_YUANBAO_BASE"] = MOCK
    os.environ["WXT_FEED_INFO_URL"] = MOCK + "/finder-preview/api/feed/get_feed_info"

    # 必须在设置环境变量之后再导入
    for mod in [m for m in list(sys.modules) if m.startswith("app.")]:
        del sys.modules[mod]
    from app.pipeline import process  # noqa: E402

    fails = []

    def check(label, cond, detail=""):
        print("  %s %-42s %s" % ("✓" if cond else "✗", label, detail))
        if not cond:
            fails.append(label)

    print("=" * 66)
    print("1. 无登录态：应走到公开通道并提示登录")
    from app.resolver import NeedLogin, resolve  # noqa: E402
    try:
        resolve("https://weixin.qq.com/sph/" + SHORT_ID, cookie=None, verbose=False)
        check("无登录态应提示登录", False, "却成功了")
    except NeedLogin as e:
        check("无登录态提示登录", True)
        check("提示里带真实标题", "凤命轮回" in str(e))

    print()
    print("2. 错误 token：应如实报“无法播放”并给诊断")
    from app.resolver import FeedUnavailable  # noqa: E402
    try:
        # 直接调底层，模拟 token 不对
        from app.resolver import _feed_call  # noqa: E402
        d = _feed_call({"baseReq": {"generalToken": "WRONG"}, "exportId": EID})
        check("错误 token 返回不可播放", not __import__("app.resolver", fromlist=["x"])._has_media(d))
    except Exception as e:
        check("错误 token 处理", False, str(e)[:60])

    print()
    print("3. 正确登录态：完整跑通 解析->下载->解密->识别->文案")
    out = os.path.join(HERE, "integration_output")
    t0 = time.time()
    r = process({"source": "link", "url": "https://weixin.qq.com/sph/" + SHORT_ID,
                 "cookie": "hy_user=fake; hy_token=fake", "engine": "paraformer",
                 "language": "zh", "outdir": out})
    check("流程成功", r.get("ok") is True)
    check("标题正确", "凤命轮回" in (r["meta"].get("title") or ""), r["meta"].get("title"))
    check("作者正确", r["meta"].get("author") == "果粒AI漫剧")
    check("识别出文案", r["stats"]["chars"] > 100, "%d 字" % r["stats"]["chars"])
    check("产出 4 种文件", len([k for k in r["files"] if k != "video"]) == 4)
    print()
    print("  提取到的文案：")
    for p in r["paragraphs"]:
        print("   ", p["text"])
    print()
    print("  耗时 %.1f 秒" % (time.time() - t0))

    print()
    print("PASS" if not fails else "FAIL: %s" % fails)
    return 1 if fails else 0

if __name__ == "__main__":
    sys.exit(main())
