# -*- coding: utf-8 -*-
"""
端到端流程编排：链接/文件 -> (解析) -> (下载) -> (解密) -> 提取音轨 -> 语音识别 -> 文案。

三种输入方式：
  link   : 视频号分享链接 https://weixin.qq.com/sph/xxxx（需元宝登录态）
  direct : 视频直链（可选同时提供 decode_key，若视频已加密）
  file   : 本地视频/音频文件
"""
import json
import os
import time

from . import media, segment
from .asr import ASREngine
from .downloader import download, safe_filename
from .resolver import NeedLogin, is_share_url, resolve
from .wxdecrypt import looks_encrypted

__all__ = ["process", "PipelineError"]

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_OUT = os.path.join(ROOT, "output")

# 模型加载开销大，进程内复用
_ENGINE_CACHE = {}


class PipelineError(RuntimeError):
    pass


def _engine(name, device=None):
    key = (name, device)
    if key not in _ENGINE_CACHE:
        _ENGINE_CACHE[key] = ASREngine(engine=name, device=device)
    return _ENGINE_CACHE[key]


class Progress(object):
    def __init__(self, cb=None):
        self.cb = cb
        self.stage = ""
        self.pct = 0.0

    def set(self, stage, pct=None, msg=""):
        self.stage = stage
        if pct is not None:
            self.pct = max(0.0, min(100.0, float(pct)))
        if self.cb:
            try:
                self.cb({"stage": stage, "percent": round(self.pct, 1), "message": msg})
            except Exception:
                pass


def _make_workdir(outroot, title, author, stamp, log=print):
    """
    按「短剧名 / 第N集」分层建目录：
        output/<短剧名>/<第N集>/...
    识别不出短剧时按账号名分组；都没有就直接放在 outroot 下。
    """
    from .naming import plan_folders
    parent, inner, info = plan_folders(outroot, title, author, fallback_stamp=stamp)
    os.makedirs(parent, exist_ok=True)
    work = _unique_dir(parent, inner)
    os.makedirs(work, exist_ok=True)
    if info.get("group"):
        log("[任务] 归档到「%s」%s" % (info["group"],
              ("／" + info["episode"]) if info.get("episode") else ""))
    log("[任务] 输出目录 %s" % work)
    return work, info


def _unique_dir(base, name):
    p = os.path.join(base, name)
    if not os.path.exists(p):
        return p
    for i in range(2, 999):
        q = os.path.join(base, "%s_%d" % (name, i))
        if not os.path.exists(q):
            return q
    return p + "_%d" % int(time.time())


def process(req, on_progress=None, log=print):
    """
    执行一次完整流程，返回结果字典。

    req:
      source      'link' | 'direct' | 'file'
      url         链接或直链
      path        本地文件路径
      decode_key  可选，直链/本地文件解密用
      cookie      元宝 Cookie（source=link 时必需）
      engine      'paraformer' | 'sensevoice' | 'whisper'
      language    'zh' | 'auto' | 'en' ...
      outdir      输出根目录
      keep_video  是否保留解密后的视频（默认 True）
    """
    t0 = time.time()
    p = Progress(on_progress)
    source = (req.get("source") or "").strip()
    engine_name = req.get("engine") or "paraformer"
    language = req.get("language") or "zh"
    outroot = req.get("outdir") or DEFAULT_OUT
    keep_video = req.get("keep_video", True)

    stamp = "task_%s" % time.strftime("%Y%m%d_%H%M%S")
    # 输出目录要等拿到标题/作者才能定（按「短剧名/第N集」分层），先占位懒建
    work = ""
    folder_info = {}

    def ensure_work():
        nonlocal work
        if not work:
            work, info2 = _make_workdir(outroot, meta.get("title"), meta.get("author"),
                                        stamp, log=log)
            folder_info.update(info2)
        return work

    meta = {"title": "", "author": "", "source_url": "", "duration_s": 0}
    feed = None
    video_path = None
    tmp_files = []

    # ---------- 1. 取得视频文件 ----------
    if source == "link":
        url = (req.get("url") or "").strip()
        if not is_share_url(url):
            raise PipelineError("分享链接格式不正确，应形如 https://weixin.qq.com/sph/xxxx")
        p.set("解析视频号链接", 5, "正在解析分享链接…")
        try:
            feed = resolve(url, cookie=req.get("cookie"), log=log)
        except NeedLogin as e:
            # 公开通道已确认链接有效，把视频信息一并带出去，界面可直接展示
            pv = getattr(e, "preview", None)
            if pv:
                fi = (pv.get("data") or {}).get("feedInfo") or {}
                ai = (pv.get("data") or {}).get("authorInfo") or {}
                if fi.get("description"):
                    meta["title"] = fi["description"]
                    meta["author"] = ai.get("nickname") or ""
                    meta["cover"] = fi.get("coverUrl") or ""
            raise
        meta["title"] = feed.get("title") or ""
        meta["author"] = feed.get("author") or ""
        meta["source_url"] = url
        meta["duration_s"] = feed.get("duration_s") or 0

        m0 = feed["media"][0]
        if not m0.get("url"):
            raise PipelineError("未解析到视频直链")
        name = safe_filename(meta["title"] or feed.get("id") or "video")
        p.set("下载视频", 15, "正在下载视频…")

        def _dl(done, total, speed):
            if total:
                pct = 15 + 55.0 * done / total
                p.set("下载视频", pct, "%.1f/%.1f MB  %.1f MB/s"
                      % (done / 1048576.0, total / 1048576.0, speed / 1048576.0))

        ensure_work()
        raw_path, _ = download(m0["url"], os.path.join(work, name + ".mp4"), progress=_dl)
        video_path = raw_path
        if m0.get("decode_key"):
            p.set("解密视频", 72, "正在解密视频…")
            from .wxdecrypt import decrypt_file
            dec = decrypt_file(raw_path, os.path.join(work, name + "_decrypted.mp4"),
                               key=m0["decode_key"])
            video_path = dec["path"]

    elif source == "direct":
        url = (req.get("url") or "").strip()
        if not url:
            raise PipelineError("缺少视频直链")
        meta["source_url"] = url
        name = safe_filename(req.get("name") or "video")
        p.set("下载视频", 10, "正在下载视频…")

        def _dl2(done, total, speed):
            if total:
                p.set("下载视频", 10 + 60.0 * done / total,
                      "%.1f/%.1f MB" % (done / 1048576.0, total / 1048576.0))

        ensure_work()
        raw_path, _ = download(url, os.path.join(work, name + ".mp4"), progress=_dl2)
        video_path = raw_path
        key = req.get("decode_key")
        if key:
            p.set("解密视频", 72, "正在解密视频…")
            from .wxdecrypt import decrypt_file
            dec = decrypt_file(raw_path, os.path.join(work, name + "_decrypted.mp4"), key=key)
            video_path = dec["path"]

    elif source == "file":
        path = (req.get("path") or "").strip()
        if not path or not os.path.exists(path):
            raise PipelineError("本地文件不存在：%s" % path)
        meta["title"] = os.path.splitext(os.path.basename(path))[0]
        p.set("读取本地文件", 30, "已载入本地文件")

        with open(path, "rb") as f:
            head = f.read(32)
        key = req.get("decode_key")
        if key and looks_encrypted(head):
            ensure_work()
            p.set("解密视频", 40, "检测到视频号加密格式，正在解密…")
            from .wxdecrypt import decrypt_file
            dec = decrypt_file(path, os.path.join(work, safe_filename(meta["title"]) + "_decrypted.mp4"),
                               key=key)
            video_path = dec["path"]
        else:
            video_path = path
    else:
        raise PipelineError("未知的输入方式: %s" % source)

    # ---------- 2. 探测 ----------
    info = media.probe(video_path)
    if info.get("ok"):
        if info.get("duration"):
            meta["duration_s"] = info["duration"]
        meta["width"] = info.get("width")
        meta["height"] = info.get("height")
        meta["video_codec"] = info.get("video_codec")
        log("[探测] 时长 %.1fs  %sx%s  %s" % (meta["duration_s"] or 0,
              info.get("width"), info.get("height"), info.get("video_codec")))
    if not info.get("ok") or not info.get("has_audio"):
        raise PipelineError("视频中没有音轨，无法提取文案（%s）" % info.get("error", "无音频流"))

    # ---------- 3. 音轨 ----------
    ensure_work()
    p.set("提取音轨", 78, "正在提取音轨…")
    wav = os.path.join(work, "_audio16k.wav")
    media.extract_audio(video_path, wav)
    tmp_files.append(wav)

    # ---------- 4. 语音识别 ----------
    p.set("语音识别", 82, "正在加载识别模型（首次运行需下载模型，请稍候）…")
    eng = _engine(engine_name)

    def _asr_progress(*a, **k):
        pass

    p.set("语音识别", 86, "正在识别语音…")
    r = eng.transcribe(wav, language=language)
    text = r["text"]
    if not text.strip():
        raise PipelineError("未识别到任何语音内容（可能是纯音乐或无人声）")

    # ---------- 4.5 固定替换表（离线校对）----------
    # 连时间轴一起改，否则 SRT 和正文会对不上
    from . import proofread
    fixed = []
    for s in r["segments"]:
        nt, _ = proofread.apply_rules(s.get("text") or "")
        d = dict(s)
        d["text"] = nt
        fixed.append(d)
    r["segments"] = fixed

    # ---------- 5. 文案整理 ----------
    p.set("整理文案", 94, "正在分段…")
    paragraphs = segment.build_paragraphs(r["segments"])
    text = "".join(x["text"] for x in paragraphs) if paragraphs else text

    # ---------- 5.5 LLM 上下文校对（可选）----------
    correction_note = "未启用"
    if paragraphs and proofread.has_llm() and req.get("proofread", True):
        p.set("校对文案", 96, "正在用 AI 校对同音字…")
        joined = "\n\n".join(x["text"] for x in paragraphs)
        corrected, note = proofread.proofread_with_llm(joined, log=log)
        parts = [t.strip() for t in corrected.split("\n\n") if t.strip()]
        if len(parts) == len(paragraphs) and corrected != joined:
            for para, np_ in zip(paragraphs, parts):
                para["text"] = np_
            text = "".join(parts)
            correction_note = note
            log("[校对] %s" % note)
        elif corrected == joined:
            correction_note = "无改动"
            log("[校对] AI 未发现需要修改的地方")
        else:
            correction_note = "段落数不匹配，已保留规则校对结果"
            log("[校对] AI 返回 %d 段，本地 %d 段，对不上，保留规则校对结果"
                % (len(parts), len(paragraphs)))
    elif not proofread.has_llm():
        correction_note = "未配置 API Key"

    stats = {"chars": len(text), "engine": engine_name, "elapsed": r["elapsed"],
             "segments": len(r["segments"]), "proofread": correction_note}

    base = safe_filename(meta["title"] or "transcript")
    files = {}
    txt_path = os.path.join(work, base + ".txt")
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("\n\n".join(x["text"] for x in paragraphs) if paragraphs else text)
    files["txt"] = txt_path

    srt_path = os.path.join(work, base + ".srt")
    with open(srt_path, "w", encoding="utf-8") as f:
        f.write(segment.to_srt(r["segments"]))
    files["srt"] = srt_path

    md_path = os.path.join(work, base + ".md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(segment.to_markdown(meta, paragraphs, text, stats))
    files["md"] = md_path

    json_path = os.path.join(work, base + ".json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({"meta": {k: v for k, v in meta.items() if k != "raw"},
                   "stats": stats, "paragraphs": paragraphs,
                   "segments": r["segments"], "text": text,
                   "feed": feed}, f, ensure_ascii=False, indent=2)
    files["json"] = json_path

    if keep_video and video_path and os.path.abspath(video_path).startswith(os.path.abspath(work)):
        files["video"] = video_path

    # 清理临时音轨
    for t in tmp_files:
        try:
            os.remove(t)
        except Exception:
            pass

    p.set("完成", 100, "文案提取完成")
    result = {
        "ok": True,
        "task_id": os.path.basename(work.rstrip("\\/")),
        "outdir": work,
        "group": folder_info.get("group") or "",
        "series": folder_info.get("series") or "",
        "episode": folder_info.get("episode") or "",
        "files": files,
        "text": text,
        "paragraphs": paragraphs,
        "meta": {k: v for k, v in meta.items() if k != "raw"},
        "stats": stats,
        "elapsed": time.time() - t0,
    }
    log("[完成] 用时 %.1f 秒，共 %d 字，输出目录 %s" % (result["elapsed"], len(text), work))

    # 记入历史，界面「历史任务」里可以随时回看/复制
    try:
        from . import history
        history.record(result, kind=source)
    except Exception as e:
        log("[历史] 写入失败（不影响结果）：%s" % e)

    return result
