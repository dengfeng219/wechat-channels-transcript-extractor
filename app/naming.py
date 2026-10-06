# -*- coding: utf-8 -*-
"""
输出目录命名：从标题里识别「短剧名」和「第几集」，用于分层归档。

目标结构：
    output/
      └── 凤命轮回：弃婴渡世/        <- 上级文件夹：短剧名
          ├── 第14集/                <- 任务文件夹：集数
          │   ├── xxx.txt / .srt / .md / .json / .mp4
          └── 第15集/

识别不出短剧时，退化为按「账号名」分组；连账号也没有就直接放 output/ 下。
"""
import re

__all__ = ["split_series", "episode_of", "group_of", "clean_name", "plan_folders"]

# 「第14集 / 第3话 / 第2期 / 第5季」，含全角数字
_EP_CN = r"[0-9０-９一二三四五六七八九十百千]+"
_EP_RE = re.compile(r"第\s*(%s)\s*[集话話期季]" % _EP_CN)
_EP_EN_RE = re.compile(r"\b(?:EP|Ep|ep|E)\s*(\d{1,4})\b")

# 名字里不允许的字符
_BAD = re.compile(r'[\\/:*?"<>|\r\n\t]+')
# 去掉后仍要清理的首尾分隔符
_TRIM = " -_—–·|:：,，.。、[]【】()（）《》<>\"'"


def clean_name(name, fallback="", max_len=60):
    """把任意字符串变成安全的文件夹名。"""
    s = _BAD.sub("_", str(name or ""))
    s = re.sub(r"\s+", " ", s).strip().strip(_TRIM).strip()
    if not s:
        s = fallback
    return s[:max_len].strip().strip(_TRIM).strip() or fallback


def split_series(title):
    """
    从标题里拆出 (短剧名, 集数标签)。
    例：'凤命轮回：弃婴渡世-第14集' -> ('凤命轮回：弃婴渡世', '第14集')
    识别不到集数时返回 ('', '')。
    """
    t = str(title or "").strip()
    if not t:
        return "", ""

    for rx in (_EP_RE, _EP_EN_RE):
        m = rx.search(t)
        if not m:
            continue
        label = m.group(0).strip()
        rest = (t[:m.start()] + " " + t[m.end():]).strip()
        series = clean_name(rest)
        if series:
            return series, label
    return "", ""


def episode_of(title):
    """只取集数标签，取不到返回空串。"""
    return split_series(title)[1]


def group_of(title, author=""):
    """
    上层文件夹名：优先短剧名，其次账号名，都没有则空串（表示不分组）。
    """
    series, _ep = split_series(title)
    if series:
        return series
    return clean_name(author, max_len=40)


def plan_folders(outroot, title, author="", fallback_stamp=""):
    """
    计算 (父目录, 任务目录名)。
      - 有短剧名/作者 -> outroot/<组名>/<集数或标题>
      - 没有          -> outroot/<标题或时间戳>
    返回的是「建议路径」，是否已存在由调用方用 _unique_dir 处理。
    """
    import os
    series, ep = split_series(title)
    group = series or clean_name(author, max_len=40)

    inner_title = clean_name(title, fallback="")
    if ep and series:
        inner = clean_name(ep, fallback=inner_title)     # 已经是「第N集」形式
    elif inner_title:
        inner = inner_title
    else:
        inner = fallback_stamp or "task"

    parent = os.path.join(outroot, group) if group else outroot
    return parent, inner, {"series": series, "episode": ep, "group": group}
