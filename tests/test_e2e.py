# -*- coding: utf-8 -*-
"""
端到端测试：真实的视频号加密视频 -> 解密 -> 音轨提取 -> 语音识别 -> 文案文件。

样本是 Evil0ctal/WeChat-Channels-Video-File-Decryption 提供的真实加密视频，
配套 decode_key 来自同仓库的 wx_response.json（官方接口返回）。
"""
import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import _iso  # noqa: F401  (隔离 history/config，退出自动清理)

sys.stdout.reconfigure(encoding="utf-8")

from app.asr import check_env                      # noqa: E402
from app.pipeline import process                   # noqa: E402
from app.wxdecrypt import extract_decode_key       # noqa: E402

def main():
    env = check_env()
    print("=" * 64)
    print("运行环境：torch %s | CUDA %s %s | FunASR %s | PyAV %s"
          % (env["torch"], env["cuda"], env["gpu"] or "", env["funasr"], env["av"]))
    print("=" * 64)

    enc = os.path.join(HERE, "wx_encrypted.mp4")
    resp = os.path.join(HERE, "wx_response.json")
    if not os.path.exists(enc):
        print("SKIP: 缺少测试样本")
        return 2

    key = extract_decode_key(json.load(open(resp, encoding="utf-8"))
                             ["data"]["object_desc"]["media"][0])
    engine = sys.argv[1] if len(sys.argv) > 1 else "paraformer"

    t0 = time.time()
    last = [""]

    def prog(info):
        line = "[%5.1f%%] %s %s" % (info.get("percent", 0), info.get("stage", ""),
                                    info.get("message", ""))
        if line != last[0]:
            print(line, flush=True)
            last[0] = line

    print("输入：%s（加密，decode_key=%s）" % (os.path.basename(enc), key))
    print("引擎：%s" % engine)
    print("-" * 64)
    try:
        r = process({"source": "file", "path": enc, "decode_key": key,
                     "engine": engine, "language": "zh",
                     "outdir": os.path.join(HERE, "e2e_output")}, on_progress=prog)
    except Exception as e:
        import traceback
        traceback.print_exc()
        print("\nFAIL: %s" % e)
        return 1

    print("-" * 64)
    print("耗时 %.1f 秒 | 识别 %d 字 | 引擎 %s"
          % (r["elapsed"], r["stats"]["chars"], r["stats"]["engine"]))
    print()
    print("【提取到的文案】")
    for p in r["paragraphs"]:
        print("  " + p["text"])
    print()
    print("【输出文件】")
    for k, v in r["files"].items():
        print("  %-6s %s (%d 字节)" % (k, v, os.path.getsize(v)))

    ok = r["stats"]["chars"] > 20 and os.path.getsize(r["files"]["txt"]) > 10
    print()
    print("PASS" if ok else "FAIL: 文案内容过少")
    return 0 if ok else 1

if __name__ == "__main__":
    sys.exit(main())
