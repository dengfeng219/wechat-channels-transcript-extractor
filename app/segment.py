# -*- coding: utf-8 -*-
"""
文案后处理：标点分句 -> 按停顿与长度智能分段 -> 输出 TXT / SRT / Markdown。
"""
import re

__all__ = ["split_sentences", "build_paragraphs", "to_srt", "to_markdown", "format_ts"]

# 句末标点
_END_PUNCT = "。！？!?…"
_SOFT_PUNCT = "，,、；;：:"


def format_ts(seconds, sep=","):
    if not seconds or seconds < 0:
        seconds = 0
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int(round((seconds - int(seconds)) * 1000))
    if ms >= 1000:
        ms = 999
    return "%02d:%02d:%02d%s%03d" % (h, m, s, sep, ms)


def split_sentences(text):
    """把整段文本切成句子（保留标点）。"""
    text = (text or "").replace("\r", "").strip()
    if not text:
        return []
    out, buf = [], ""
    for ch in text:
        buf += ch
        if ch in _END_PUNCT:
            if buf.strip():
                out.append(buf.strip())
            buf = ""
    if buf.strip():
        out.append(buf.strip())
    return out


def _split_long(sentence, max_len):
    """过长句子在软标点处再切。"""
    if len(sentence) <= max_len:
        return [sentence]
    parts, buf = [], ""
    for ch in sentence:
        buf += ch
        if ch in _SOFT_PUNCT and len(buf) >= max_len:
            parts.append(buf.strip())
            buf = ""
    if buf.strip():
        parts.append(buf.strip())
    return parts


def _adaptive_gap(units, lo=0.45, hi=1.1):
    """
    根据说话节奏自适应计算「换段停顿阈值」。

    口播语速快的人句间停顿普遍较短，固定阈值会切不出段落；
    这里取句间停顿的中位数放大后夹逼到 [lo, hi]。
    """
    gaps = []
    for i in range(1, len(units)):
        g = units[i]["start"] - units[i - 1]["end"]
        if g > 0:
            gaps.append(g)
    if len(gaps) < 3:
        return 0.75
    gaps.sort()
    mid = gaps[len(gaps) // 2]
    return max(lo, min(hi, mid * 2.5))


def build_paragraphs(segments, gap_threshold=None, max_len=150):
    """
    依据时间轴把识别结果合并成自然段。

    规则：句间停顿明显长于该视频的平均节奏（或超过 gap_threshold），
          或累计字数超过 max_len，则另起一段。
    segments: [{'start','end','text'}]
    """
    units = []
    for seg in segments:
        t = (seg.get("text") or "").strip()
        if not t:
            continue
        st, en = float(seg.get("start") or 0), float(seg.get("end") or 0)
        sents = split_sentences(t) or [t]
        if len(sents) == 1:
            units.append({"start": st, "end": en, "text": sents[0]})
        else:
            # 段内多句时按字数均分时间
            total = sum(len(s) for s in sents) or 1
            span = max(en - st, 0.0)
            cur = st
            for s in sents:
                d = span * (len(s) / total)
                units.append({"start": cur, "end": cur + d, "text": s})
                cur += d

    if not units:
        return []

    if gap_threshold is None:
        gap_threshold = _adaptive_gap(units)

    paragraphs, cur = [], {"start": units[0]["start"], "end": units[0]["end"], "text": ""}
    for u in units:
        gap = u["start"] - cur["end"] if cur["text"] else 0.0
        total = len(cur["text"]) + len(u["text"])
        # 已经是一个完整句子结尾时才允许因长度换段，保证段落总是断在句号处；
        # 但严重超长（1.8 倍）时强制换段，避免出现超长段落。
        at_sentence_end = bool(cur["text"]) and cur["text"][-1] in _END_PUNCT
        too_long = total > max_len and (at_sentence_end or total > max_len * 1.8)
        if cur["text"] and (gap >= gap_threshold or too_long):
            paragraphs.append(cur)
            cur = {"start": u["start"], "end": u["end"], "text": u["text"]}
        else:
            cur["text"] += u["text"]
            cur["end"] = u["end"]
    if cur["text"]:
        paragraphs.append(cur)

    return paragraphs


def to_srt(segments, max_chars=40):
    """把识别片段转成 SRT 字幕。"""
    lines, idx = [], 1
    for seg in segments:
        t = (seg.get("text") or "").strip()
        if not t:
            continue
        st, en = float(seg.get("start") or 0), float(seg.get("end") or 0)
        if en <= st:
            en = st + max(len(t) * 0.18, 1.0)
        chunks = [t[i:i + max_chars] for i in range(0, len(t), max_chars)]
        span = (en - st) / len(chunks)
        for k, c in enumerate(chunks):
            lines.append("%d\n%s --> %s\n%s\n" % (
                idx, format_ts(st + k * span), format_ts(st + (k + 1) * span), c))
            idx += 1
    return "\n".join(lines)


def to_markdown(meta, paragraphs, full_text, stats=None):
    """生成 Markdown 文案稿。"""
    out = ["# %s" % (meta.get("title") or "视频号文案"), ""]
    if meta.get("author"):
        out.append("- **作者**：%s" % meta["author"])
    if meta.get("source_url"):
        out.append("- **来源**：%s" % meta["source_url"])
    if meta.get("duration_s"):
        out.append("- **时长**：%s" % format_ts(meta["duration_s"], sep="."))
    if stats:
        out.append("- **字数**：%d 字" % stats.get("chars", 0))
        out.append("- **识别引擎**：%s" % stats.get("engine", ""))
        out.append("- **耗时**：%.1f 秒" % stats.get("elapsed", 0))
    out += ["", "---", "", "## 完整文案", ""]

    if paragraphs:
        for p in paragraphs:
            ts = "[%s] " % format_ts(p["start"], sep=".") if p.get("start") else ""
            out.append("%s%s" % (ts, p["text"]))
            out.append("")
    else:
        out.append(full_text)
        out.append("")
    return "\n".join(out)
