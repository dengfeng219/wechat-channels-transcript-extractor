# -*- coding: utf-8 -*-
"""同一段音频跑三个引擎，对比识别质量。"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8")

from app import media             # noqa: E402
from app.asr import ASREngine     # noqa: E402

# 拿一集真实短剧
CAND = [
    os.path.join(ROOT, "output", "凤命轮回：弃婴渡世", "第14集",
                 "凤命轮回：弃婴渡世-第14集.mp4"),
    os.path.join(ROOT, "output", "雪夜藏金龙，善妇福满门", "第1集",
                 "雪夜藏金龙，善妇福满门-第1集.mp4"),
]
SRC = next((p for p in CAND if os.path.exists(p)), "")
if not SRC:
    print("找不到样本视频"); sys.exit(2)
print("样本:", os.path.basename(SRC))

WAV = os.path.join(HERE, "_cmp16k.wav")
if not os.path.exists(WAV):
    media.extract_audio(SRC, WAV)

ENGINES = sys.argv[1:] or ["paraformer", "sensevoice"]
results = {}

for name in ENGINES:
    print()
    print("=" * 68)
    print("引擎:", name)
    print("=" * 68)
    try:
        eng = ASREngine(engine=name)
        t0 = time.time()
        r = eng.transcribe(WAV, language="zh")
        results[name] = r["text"]
        print("用时 %.1f 秒，%d 字" % (time.time() - t0, len(r["text"])))
        print()
        print(r["text"])
    except Exception as e:
        print("失败:", type(e).__name__, e)
        results[name] = ""

if len(results) > 1:
    print()
    print("=" * 68)
    print("逐字符差异（以第一个引擎为基准）")
    print("=" * 68)
    names = list(results)
    a, b = results[names[0]], results[names[1]]
    import difflib
    sm = difflib.SequenceMatcher(None, a, b)
    print("相似度: %.2f%%" % (sm.ratio() * 100))
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag != "equal":
            print("  %-8s %r  ->  %r" % (tag, a[i1:i2], b[j1:j2]))
