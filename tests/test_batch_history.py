# -*- coding: utf-8 -*-
"""新功能测试：批量提交、URL 提取、历史任务（列表/详情/复制源/删除）。"""
import json
import os
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import _iso  # noqa: F401  (隔离 history/config，退出自动清理)
sys.stdout.reconfigure(encoding="utf-8")

PORT = 8794
BASE = "http://127.0.0.1:%d" % PORT
fails = []

def check(label, cond, detail=""):
    print("  %s %-42s %s" % ("✓" if cond else "✗", label, detail))
    if not cond:
        fails.append(label)

def get(p):
    with urllib.request.urlopen(BASE + p, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))

def post(p, obj=None):
    req = urllib.request.Request(BASE + p, data=json.dumps(obj or {}).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:      # 400/404 也要能把 body 读出来断言
        return json.loads(e.read().decode("utf-8", "replace"))

def raw(p):
    with urllib.request.urlopen(BASE + p, timeout=30) as r:
        return r.read().decode("utf-8")

def main():
    from app.server import serve
    threading.Thread(target=serve, kwargs={"port": PORT, "open_browser": False},
                     daemon=True).start()
    time.sleep(1.2)

    print("== 1. 界面元素 ==")
    html = raw("/")
    for el in ("批量", "历史任务", "pane-history", "linkCount", "batchList",
               "histCopy", "复制文案"):
        check("页面含 " + el, el in html)

    print()
    print("== 2. 从粘贴文本里提取链接 ==")
    blob = ("看看这个 https://weixin.qq.com/sph/ARBFNO8PaW\n"
            "还有 https://weixin.qq.com/sph/ABCDEF1234 ，重复 https://weixin.qq.com/sph/ARBFNO8PaW")
    r = post("/api/extract_urls", {"text": blob})
    check("提取并去重", r["count"] == 2, "得到 %d 条" % r["count"])
    check("保留顺序", r["urls"][0].endswith("ARBFNO8PaW") and r["urls"][1].endswith("ABCDEF1234"))
    r = post("/api/extract_urls", {"text": "这里没有任何链接"})
    check("无链接时返回 0", r["count"] == 0)

    print()
    print("== 3. 批量提交 ==")
    batchout = os.path.join(_iso._DIR, "wxt_batch_out_%d" % os.getpid())
    r = post("/api/transcribe", {"urls": ["https://weixin.qq.com/sph/FAKE000001",
                                          "https://weixin.qq.com/sph/FAKE000002",
                                          "https://weixin.qq.com/sph/FAKE000003"],
                                 "outdir": batchout})
    check("返回 batch 标记", r.get("batch") is True)
    check("创建 3 个任务", r.get("count") == 3, "jobs=%d" % len(r.get("jobs", [])))
    ids = [j["job_id"] for j in r["jobs"]]
    t0 = time.time()
    statuses = {}
    while time.time() - t0 < 180:
        statuses = {i: get("/api/job?id=" + i)["status"] for i in ids}
        if all(s in ("done", "error") for s in statuses.values()):
            break
        time.sleep(1.0)
    check("3 个任务都跑到终态", all(s in ("done", "error") for s in statuses.values()),
          str(list(statuses.values())))

    r = post("/api/transcribe", {"urls": ["这不是链接"]})
    check("全是无效链接时拒绝", r.get("ok") is False)

    print()
    print("== 4. 历史任务 ==")
    h = get("/api/history")
    check("初始历史为空", h["total"] == 0, "total=%d" % h["total"])

    # 用本地文件跑一次真实提取，验证会自动写进历史
    from app.pipeline import process
    sample = os.path.join(HERE, "wx_decrypted.mp4")
    if not os.path.exists(sample):
        print("  (缺少样例视频，跳过历史写入验证)")
    else:
        # 用临时输出目录，别污染用户真实的 output/
        tmpout = os.path.join(_iso._DIR, "wxt_hist_out_%d" % os.getpid())
        res = process({"source": "file", "path": sample, "engine": "paraformer",
                       "language": "zh", "keep_video": False, "outdir": tmpout})
        h = get("/api/history")
        check("提取后自动入历史", h["total"] == 1, "total=%d" % h["total"])
        e = h["entries"][0]
        check("记录含标题", bool(e.get("title")), e.get("title"))
        check("记录含字数", (e.get("chars") or 0) > 100, "%s 字" % e.get("chars"))
        check("记录含文件列表", bool(e.get("files")), str(sorted(e.get("files", {}).keys())))

        d = get("/api/history/item?id=" + urllib.parse.quote(e["id"]))
        check("详情能取到正文", len(d["entry"].get("text") or "") > 100,
              "%d 字" % len(d["entry"].get("text") or ""))
        check("正文与识别一致", "北京" in d["entry"]["text"])

        post("/api/history/scan", {})          # 第一次扫描：已记录的任务不应重复导入
        s = post("/api/history/scan", {})       # 再扫一次：必须是幂等的
        check("扫描是幂等的（不重复导入）", s["added"] == 0, "added=%d" % s["added"])

        dl = post("/api/history/delete", {"id": e["id"]})
        check("删除记录成功", dl["ok"] is True)
        gone = True
        try:
            get("/api/history/item?id=" + urllib.parse.quote(e["id"]))
            gone = False
        except urllib.error.HTTPError as ex:
            gone = (ex.code == 404)
        check("删除后该记录不存在", gone)
        check("文件仍在磁盘上（只删记录）", os.path.exists(e["files"]["txt"]))

        import shutil
        shutil.rmtree(tmpout, ignore_errors=True)
        shutil.rmtree(batchout, ignore_errors=True)

    print()
    print("PASS" if not fails else "FAIL: %s" % fails)
    return 1 if fails else 0

if __name__ == "__main__":
    import urllib.parse  # noqa: E402
    sys.exit(main())
