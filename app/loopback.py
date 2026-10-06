# -*- coding: utf-8 -*-
"""
录制电脑正在播放的声音（WASAPI Loopback）。

用途：视频号视频在微信里能正常播放，但拿不到视频文件。
      那就把「电脑发出的声音」原样录下来，再做语音识别 —— 全程不需要任何登录态。

录到的是 48kHz 立体声 WAV，随后由 media.extract_audio() 转成 16kHz 单声道。
"""
import os
import threading
import time
import wave

__all__ = ["available_devices", "Recorder", "have_loopback"]

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REC_DIR = os.path.join(ROOT, "recordings")

try:
    import pyaudiowpatch as _pa
    _HAVE = True
except Exception:
    _pa = None
    _HAVE = False


def have_loopback():
    return _HAVE


def default_loopback_index():
    """当前系统默认输出设备对应的环回设备下标（录到的才是真正在响的那个）。"""
    if not _HAVE:
        return None
    try:
        p = _pa.PyAudio()
    except Exception:
        return None
    try:
        return int(p.get_default_wasapi_loopback().get("index"))
    except Exception:
        return None
    finally:
        try:
            p.terminate()
        except Exception:
            pass


def available_devices():
    """列出可用于环回录制的设备；default=True 的那个是系统默认输出。"""
    if not _HAVE:
        return []
    out = []
    try:
        p = _pa.PyAudio()
    except Exception:
        return []
    try:
        try:
            didx = int(p.get_default_wasapi_loopback().get("index"))
        except Exception:
            didx = -1
        for i in range(p.get_device_count()):
            try:
                d = p.get_device_info_by_index(i)
            except Exception:
                continue
            if d.get("maxInputChannels", 0) > 0 and d.get("isLoopbackDevice"):
                out.append({
                    "index": i,
                    "name": str(d.get("name") or ""),
                    "channels": int(d.get("maxInputChannels") or 2),
                    "rate": int(d.get("defaultSampleRate") or 48000),
                    "default": (i == didx),
                })
    finally:
        try:
            p.terminate()
        except Exception:
            pass
    out.sort(key=lambda d: (not d["default"], d["index"]))
    return out


class Recorder(object):
    """单例录音器：后台线程持续读环回数据。"""

    def __init__(self):
        self._thread = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._pa = None
        self._stream = None
        self.wav_path = ""
        self.started_at = 0.0
        self.error = ""
        self.frames = 0
        self.rate = 48000
        self.channels = 2
        self.device_name = ""
        self.level = 0.0
        self.last_seconds = 0.0   # 上一次录制的时长（stop() 后仍可读）

    # ---------- 对外 ----------
    @property
    def recording(self):
        return self._thread is not None and self._thread.is_alive()

    def status(self):
        seconds = (time.time() - self.started_at) if self.started_at else self.last_seconds
        return {
            "recording": self.recording,
            "seconds": round(seconds, 1),
            "device": self.device_name,
            "level": round(self.level, 3),
            "path": self.wav_path if not self.recording else "",
            "error": self.error,
        }

    def start(self, device_index=None, name_hint=None):
        if self.recording:
            return self.status()
        if not _HAVE:
            self.error = "未安装 pyaudiowpatch，无法录制系统声音"
            return self.status()

        os.makedirs(REC_DIR, exist_ok=True)
        self.error = ""
        self.frames = 0
        self.level = 0.0
        self.wav_path = os.path.join(REC_DIR, "录音_%s.wav" % time.strftime("%Y%m%d_%H%M%S"))
        self._stop.clear()
        self._dev_index = device_index
        self._name_hint = name_hint
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        # 等设备就绪，最多 6 秒
        deadline = time.time() + 6
        while time.time() < deadline and not self.error and self.frames == 0:
            time.sleep(0.1)
        return self.status()

    def stop(self):
        if self.started_at:
            self.last_seconds = max(0.0, time.time() - self.started_at)
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=10)
        self._thread = None
        self.started_at = 0.0
        return self.status()

    # ---------- 内部 ----------
    def _pick_device(self, p, device_index, name_hint):
        if device_index is not None:
            d = p.get_device_info_by_index(int(device_index))
            return d
        if name_hint:
            for i in range(p.get_device_count()):
                d = p.get_device_info_by_index(i)
                if d.get("isLoopbackDevice") and name_hint in str(d.get("name") or ""):
                    return d
        return p.get_default_wasapi_loopback()

    def _run(self):
        p = None
        stream = None
        wf = None
        try:
            p = _pa.PyAudio()
            d = self._pick_device(p, self._dev_index, self._name_hint)
            self.device_name = str(d.get("name") or "")
            self.rate = int(d.get("defaultSampleRate") or 48000)
            self.channels = int(d.get("maxInputChannels") or 2)
            idx = int(d.get("index"))

            stream = p.open(format=_pa.paInt16, channels=self.channels,
                            rate=self.rate, input=True, input_device_index=idx,
                            frames_per_buffer=1024)
            wf = wave.open(self.wav_path, "wb")
            wf.setnchannels(self.channels)
            wf.setsampwidth(2)
            wf.setframerate(self.rate)
            self.started_at = time.time()

            while not self._stop.is_set():
                try:
                    data = stream.read(1024, exception_on_overflow=False)
                except Exception:
                    time.sleep(0.05)
                    continue
                wf.writeframes(data)
                self.frames += 1
                if self.frames % 8 == 0:  # 粗略音量，用于界面显示
                    try:
                        import numpy as np
                        a = np.frombuffer(data, dtype=np.int16)
                        self.level = float(abs(a).mean()) / 32768.0
                    except Exception:
                        pass
        except Exception as e:
            self.error = "%s: %s" % (type(e).__name__, e)
        finally:
            try:
                if wf:
                    wf.close()
            except Exception:
                pass
            try:
                if stream:
                    stream.stop_stream()
                    stream.close()
            except Exception:
                pass
            try:
                if p:
                    p.terminate()
            except Exception:
                pass
            self.level = 0.0
