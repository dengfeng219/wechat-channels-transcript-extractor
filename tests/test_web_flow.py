# -*- coding: utf-8 -*-
"""模拟真实用户操作：启动服务 -> 上传文件 -> 提交转写 -> 轮询 -> 校验结果。"""
import json
import os
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import _iso  # noqa: F401  (隔离 history/config，退出自动清理)

sys.stdout.reconfigure(encoding="utf-8")

PORT = 8792
BASE = "http://127.0.0.1:%d" % PORT

def post(path, obj=None, raw=None, headers=None):
    h = dict(headers or {})
    if obj is not None:
        raw = json.dumps(obj).encode("utf-8")
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE + path, data=raw, headers=h, method="POST")
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read().decode("utf-8"))

def get(path):
    with urllib.request.urlopen(BASE + path, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))

def main():
    from app.server import serve
    threading.Thread(target=serve, kwargs={"port": PORT, "open_browser": False},
                     daemon=True).start()
    time.sleep(1.2)

    src = os.path.join(HERE, "wx_decrypted.mp4")
    if not os.path.exists(src):
        print("SKIP: 缺少 %s（先运行 test_decrypt.py）" % src)
        return 2

    # 1) 上传（模拟拖拽文件）
    print("[1] 上传文件 ...")
    data = open(src, "rb").read()
    r = post("/api/upload", raw=data,
             headers={"X-Filename": urllib.parse.quote("测试视频.mp4"),
                      "Content-Length": str(len(data))})
    print("    上传成功:", r["path"], "(%.1f MB)" % (r["size"] / 1048576.0))
    assert r["ok"]

    # 2) 提交转写任务
    print("[2] 提交转写任务 ...")
    t0 = time.time()
    r = post("/api/transcribe", {"source": "file", "path": r["path"],
                                 "engine": "paraformer", "language": "zh",
                                 "outdir": os.path.join(_iso._DIR,
                                                        "wxt_webflow_out")})
    jid = r["job_id"]
    print("    任务号:", jid)
    assert r["ok"]

    # 3) 轮询进度
    print("[3] 等待识别 ...")
    last = ""
    while True:
        j = get("/api/job?id=" + jid)
        p = j.get("progress") or {}
        line = "[%5.1f%%] %s" % (p.get("percent", 0), p.get("stage", ""))
        if line != last:
            print("   ", line)
            last = line
        if j["status"] in ("done", "error"):
            break
        if time.time() - t0 > 900:
            print("超时"); return 1
        time.sleep(0.7)

    if j["status"] == "error":
        print("失败:", j.get("error"))
        print(j.get("trace", ""))
        return 1

    res = j["result"]
    print("[4] 完成，用时 %.1f 秒（服务端端到端）" % (time.time() - t0))
    print("    识别 %.1f 秒，共 %d 字，段落 %d 段"
          % (res["stats"]["elapsed"], res["stats"]["chars"], len(res["paragraphs"])))
    print()
    for i, p in enumerate(res["paragraphs"], 1):
        print("  段落%d: %s" % (i, p["text"]))
    print()
    print("    输出文件:")
    for k, v in res["files"].items():
        print("      %-6s %s" % (k, os.path.basename(v)))

    ok = res["stats"]["chars"] > 20 and len(res["paragraphs"]) >= 1
    print()
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1

if __name__ == "__main__":
    sys.exit(main())
