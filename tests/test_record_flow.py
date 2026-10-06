# -*- coding: utf-8 -*-
"""
「录制电脑声音」完整用户流程测试（走 HTTP 接口，等同于界面上的操作）：
  开始录制 -> 播放音频 -> 停止并转写 -> 轮询任务 -> 校验文案
"""
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

PORT = 8793
BASE = "http://127.0.0.1:%d" % PORT
PLAY = os.path.join(HERE, "_play16k.wav")

fails = []

def check(label, cond, detail=""):
    print("  %s %-40s %s" % ("✓" if cond else "✗", label, detail))
    if not cond:
        fails.append(label)

def get(p):
    with urllib.request.urlopen(BASE + p, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))

def post(p, obj):
    req = urllib.request.Request(BASE + p, data=json.dumps(obj).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))

def main():
    if not os.path.exists(PLAY):
        print("SKIP: 缺少 %s" % PLAY); return 2

    from app.server import serve
    threading.Thread(target=serve, kwargs={"port": PORT, "open_browser": False},
                     daemon=True).start()
    time.sleep(1.2)

    print("== 录制接口 ==")
    d = get("/api/record/devices")
    check("支持录制并且有设备", d["supported"] and len(d["devices"]) > 0,
          "%d 个设备" % len(d["devices"]))
    if not (d["supported"] and d["devices"]):
        print("FAIL"); return 1

    dev = next((x for x in d["devices"] if x.get("default")), d["devices"][0])
    check("设备列表标出了默认输出", any(x.get("default") for x in d["devices"]),
          dev["name"] if dev.get("default") else "(未标记，退化为第一个)")
    st = post("/api/record/start", {"device_index": dev["index"]})
    check("开始录制成功", st.get("ok") is True, st.get("status", {}).get("device", ""))

    played = {}
    def _play():
        try:
            import winsound
            winsound.PlaySound(PLAY, winsound.SND_FILENAME)
            played["ok"] = True
        except Exception as e:
            played["err"] = str(e)

    t = threading.Thread(target=_play, daemon=True)
    t.start()

    peak = 0.0
    t0 = time.time()
    while t.is_alive() and time.time() - t0 < 90:
        time.sleep(0.5)
        peak = max(peak, get("/api/record/status").get("level", 0.0))
    t.join(timeout=5)
    time.sleep(0.5)

    s = get("/api/record/status")
    check("录制中状态可见", s["recording"] is True, "%.1f 秒" % s["seconds"])
    check("捕获到声音", peak > 0.001, "峰值 %.4f" % peak)

    print()
    print("== 停止并转写 ==")
    r = post("/api/record/stop", {"engine": "paraformer", "language": "zh",
                                  "outdir": os.path.join(_iso._DIR,
                                                         "wxt_record_out")})
    check("停止成功并建任务", r.get("ok") is True and r.get("job_id"), "%.1f 秒" % r.get("seconds", 0))

    jid = r["job_id"]
    last = ""
    while True:
        j = get("/api/job?id=" + jid)
        p = (j.get("progress") or {})
        line = "[%5.1f%%] %s" % (p.get("percent", 0), p.get("stage", ""))
        if line != last:
            print("   ", line); last = line
        if j["status"] in ("done", "error"):
            break
        time.sleep(0.8)

    if j["status"] == "error":
        print("任务失败:", j.get("error")); print("FAIL"); return 1

    res = j["result"]
    text = res["text"]
    print()
    print("识别结果（%d 字）:" % len(text))
    print("  ", text[:300])
    KEYS = ["北京", "天安门", "故宫", "颐和园", "圆明园", "后悔"]
    hit = [k for k in KEYS if k in text]
    check("关键内容命中", len(hit) >= 4, "命中 %s" % hit)
    check("产出文案文件", os.path.exists(res["files"]["txt"]))

    print()
    print("PASS" if not fails else "FAIL: %s" % fails)
    return 1 if fails else 0

if __name__ == "__main__":
    sys.exit(main())
