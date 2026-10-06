# -*- coding: utf-8 -*-
"""冒烟测试：解析结果规范化 + 本地服务接口。"""
import json
import os
import sys
import tempfile
import threading
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import _iso  # noqa: F401  (隔离 history/config，退出自动清理)

sys.stdout.reconfigure(encoding="utf-8")

from app.resolver import normalize_feed  # noqa: E402

PORT = 8791

def test_normalize():
    p = os.path.join(HERE, "wx_response.json")
    if not os.path.exists(p):
        print("SKIP normalize: 缺少样本")
        return
    feed = normalize_feed(json.load(open(p, encoding="utf-8")))
    print("== 规范化结果 ==")
    print("  标题:", feed["title"][:40])
    print("  作者:", feed["author"])
    print("  时长: %.1f 秒" % feed["duration_s"])
    m = feed["media"][0]
    print("  直链:", m["url"][:70], "...")
    print("  decode_key:", m["decode_key"])
    print("  分辨率: %sx%s  %s  %s" % (m["width"], m["height"], m["coding_format"], m["file_format"]))
    assert m["decode_key"] == "2136343393", m["decode_key"]
    assert m["url"].startswith("https://finder.video.qq.com/")
    print("  PASS")

def test_api():
    from app.server import serve
    t = threading.Thread(target=serve, kwargs={"port": PORT, "open_browser": False}, daemon=True)
    t.start()
    time.sleep(1.2)

    def get(p):
        try:
            with urllib.request.urlopen("http://127.0.0.1:%d%s" % (PORT, p), timeout=10) as r:
                return r.status, r.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", "replace")

    print("\n== 接口冒烟测试 ==")
    st, body = get("/")
    print("  GET /            -> %d, %d 字节 HTML, 含标题: %s"
          % (st, len(body), "视频号文案提取器" in body))
    assert st == 200 and "视频号文案提取器" in body

    st, body = get("/api/env")
    env = json.loads(body)
    print("  GET /api/env     -> %d, engines=%s" % (st, env["engines"]))
    print("     torch=%s cuda=%s gpu=%s" % (env["env"]["torch"], env["env"]["cuda"], env["env"]["gpu"]))
    print("     funasr=%s av=%s" % (env["env"]["funasr"], env["env"]["av"]))
    assert st == 200

    st, body = get("/api/job?id=nope")
    print("  GET /api/job     -> %d (预期 404)" % st)
    print("  PASS")

if __name__ == "__main__":
    test_normalize()
    test_api()
