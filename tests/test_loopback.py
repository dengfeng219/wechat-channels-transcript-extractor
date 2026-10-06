# -*- coding: utf-8 -*-
"""
验证「录制电脑声音」这条通路：
  播放样例视频的音轨 -> 环回录制 -> 转 16k -> 语音识别 -> 与已知文案比对

这条路径完全不需要视频号登录态，是拿不到视频文件时最实用的兜底方案。
"""
import os
import sys
import threading
import time
import wave

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8")

from app import media  # noqa: E402
from app.asr import ASREngine  # noqa: E402
from app.loopback import Recorder, available_devices, have_loopback  # noqa: E402

fails = []

def check(label, cond, detail=""):
    print("  %s %-40s %s" % ("✓" if cond else "✗", label, detail))
    if not cond:
        fails.append(label)

print("环回支持:", have_loopback())
devs = available_devices()
print("可用环回设备 %d 个:" % len(devs))
for d in devs[:4]:
    print("   [%d] %s (%dch %dHz)" % (d["index"], d["name"], d["channels"], d["rate"]))
if not devs:
    print("没有环回设备，跳过"); sys.exit(2)

PLAY = os.path.join(HERE, "_play16k.wav")
if not os.path.exists(PLAY):
    print("缺少 %s，先跑一次 test_e2e 生成" % PLAY); sys.exit(2)

rec = Recorder()
print()
print("开始录制 …")
st = rec.start()
check("录制已启动", st["recording"], st.get("error") or st.get("device"))
if not st["recording"]:
    print("录制无法启动"); sys.exit(1)

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
print("正在播放样例音轨（%.0f 秒）…" % 52.3)

# 播放期间观察电平
peak = 0.0
t0 = time.time()
while t.is_alive() and time.time() - t0 < 90:
    time.sleep(0.5)
    peak = max(peak, rec.status().get("level", 0.0))
t.join(timeout=5)

time.sleep(0.5)
st = rec.stop()
wav = st.get("path") or rec.wav_path
print("录制结束:", wav)
check("捕获到声音（电平非零）", peak > 0.001, "峰值电平 %.4f" % peak)
if played.get("err"):
    print("  播放报错:", played["err"])

if not os.path.exists(wav) or os.path.getsize(wav) < 100000:
    check("录音文件有效", False, "文件过小"); print("FAIL"); sys.exit(1)
with wave.open(wav) as w:
    dur = w.getnframes() / float(w.getframerate())
check("录音时长合理", 40 <= dur <= 70, "%.1f 秒" % dur)

print()
print("转 16k 并识别 …")
wav16 = os.path.join(HERE, "_loopback16k.wav")
media.extract_audio(wav, wav16)
eng = ASREngine(engine="paraformer")
r = eng.transcribe(wav16, language="zh")
text = r["text"]
print()
print("识别结果（%d 字）:" % len(text))
print("  ", text[:400])

# 已知文案关键词（原始视频内容）
KEYS = ["北京", "天安门", "故宫", "长城", "颐和园", "圆明园", "后悔"]
hit = [k for k in KEYS if k in text]
check("识别出关键内容", len(hit) >= 4, "命中 %s" % hit)
check("文本长度合理", len(text) > 100, "%d 字" % len(text))

for f in (wav16,):
    try:
        os.remove(f)
    except Exception:
        pass

print()
print("PASS" if not fails else "FAIL: %s" % fails)
sys.exit(1 if fails else 0)
