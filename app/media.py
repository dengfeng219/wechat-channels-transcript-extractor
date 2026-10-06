# -*- coding: utf-8 -*-
"""
媒体处理：探测信息 + 音轨提取。

使用 PyAV（自带 FFmpeg 库，无需系统安装 ffmpeg）完成解码，
输出 16kHz / 单声道 / 16bit PCM WAV 供 ASR 使用。
"""
import os
import wave

__all__ = ["probe", "extract_audio", "have_pyav"]

try:
    import av
    _HAVE_AV = True
except Exception:
    _HAVE_AV = False


def have_pyav():
    return _HAVE_AV


def probe(path):
    """读取媒体信息：时长、分辨率、编码、是否含音轨。"""
    if not _HAVE_AV:
        return {"ok": False, "error": "PyAV 未安装"}
    try:
        with av.open(path) as c:
            info = {"ok": True, "path": path, "duration": None,
                    "width": None, "height": None, "video_codec": None,
                    "audio_codec": None, "has_audio": False, "has_video": False}
            if c.duration:
                info["duration"] = c.duration / 1000000.0
            for s in c.streams.video:
                info["has_video"] = True
                info["width"] = s.codec_context.width
                info["height"] = s.codec_context.height
                info["video_codec"] = s.codec_context.name
                if info["duration"] is None and s.duration and s.time_base:
                    info["duration"] = float(s.duration * s.time_base)
                break
            for s in c.streams.audio:
                info["has_audio"] = True
                info["audio_codec"] = s.codec_context.name
                break
            return info
    except Exception as e:
        return {"ok": False, "error": "%s: %s" % (type(e).__name__, e)}


def extract_audio(src, dst=None, rate=16000, channels=1, verbose=True):
    """
    从任意音视频文件提取单声道 16kHz WAV。

    返回 wav 路径；调用方负责在不再需要时删除临时文件。
    """
    if not _HAVE_AV:
        raise RuntimeError("需要 PyAV 才能提取音轨，请运行: pip install av")

    if dst is None:
        base, _ = os.path.splitext(src)
        dst = base + ".16k.wav"

    with av.open(src) as container:
        if not container.streams.audio:
            raise RuntimeError("该文件不包含音轨，无法转写")

        stream = container.streams.audio[0]
        resampler = av.AudioResampler(format="s16", layout="mono", rate=rate)

        pcm = bytearray()
        for frame in container.decode(stream):
            for rframe in resampler.resample(frame):
                pcm += bytes(rframe.planes[0])[:rframe.samples * 2]
        # 冲刷重采样器
        try:
            for rframe in resampler.resample(None):
                pcm += bytes(rframe.planes[0])[:rframe.samples * 2]
        except Exception:
            pass

    with wave.open(dst, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(bytes(pcm))

    if verbose:
        print("[音频] 已提取 %s (%.1f 秒, %.1f MB)"
              % (dst, len(pcm) / 2.0 / rate, len(pcm) / 1048576.0))
    return dst
