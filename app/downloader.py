# -*- coding: utf-8 -*-
"""媒体下载：支持断点续传、进度回调、友好文件名。"""
import os
import re
import time

from .http import request

__all__ = ["download", "safe_filename"]

_ILLEGAL = re.compile(r'[\\/:*?"<>|\r\n\t]+')


def safe_filename(name, fallback="video", max_len=80):
    name = (name or "").strip()
    name = _ILLEGAL.sub("_", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    if not name:
        name = fallback
    return name[:max_len]


def download(url, dst, headers=None, progress=None, timeout=60, verbose=True):
    """
    下载 url 到 dst，返回 (文件路径, 字节数)。

    视频号 CDN 需要 Referer/UA；short 超时用于探测响应头。
    """
    h = {
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"),
        "Accept": "*/*",
        "Accept-Encoding": "identity",
        "Referer": "https://channels.weixin.qq.com/",
    }
    h.update(headers or {})

    os.makedirs(os.path.dirname(os.path.abspath(dst)) or ".", exist_ok=True)
    tmp = dst + ".part"
    start = os.path.getsize(tmp) if os.path.exists(tmp) else 0
    if start:
        h["Range"] = "bytes=%d-" % start

    try:
        import requests
        t0 = time.time()
        with requests.get(url, headers=h, stream=True, timeout=timeout) as r:
            if r.status_code == 416:  # 已下载完成
                os.replace(tmp, dst)
                return dst, os.path.getsize(dst)
            if r.status_code not in (200, 206):
                raise RuntimeError("下载失败 HTTP %s" % r.status_code)
            if start and r.status_code == 200:
                start = 0  # 服务端不支持续传
            total = int(r.headers.get("Content-Length") or 0) + start
            done = start
            with open(tmp, "ab" if start else "wb") as f:
                for chunk in r.iter_content(262144):
                    if not chunk:
                        continue
                    f.write(chunk)
                    done += len(chunk)
                    if progress:
                        progress(done, total, done / (time.time() - t0) if time.time() > t0 else 0)
    except ImportError:
        status, text = _download_urllib(url, h, tmp, start, progress)
        if status not in (200, 206):
            raise RuntimeError("下载失败 HTTP %s" % status)

    os.replace(tmp, dst)
    size = os.path.getsize(dst)
    if verbose:
        print("[下载] %s (%.1f MB)" % (dst, size / 1048576.0))
    return dst, size


def _download_urllib(url, headers, tmp, start, progress):
    import urllib.request
    req = urllib.request.Request(url, headers=headers)
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "ab" if start else "wb") as f:
        total = int(r.headers.get("Content-Length") or 0) + start
        done = start
        while True:
            chunk = r.read(262144)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if progress:
                progress(done, total, done / max(time.time() - t0, 0.001))
        return r.status, ""
