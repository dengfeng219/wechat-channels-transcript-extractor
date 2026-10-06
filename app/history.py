# -*- coding: utf-8 -*-
"""
历史任务记录。

每次成功提取都会追加一条记录，界面「历史任务」里可以随时回看和复制。
文案正文也一并存下来 —— 即使输出目录被清理，历史里依然看得到内容。
"""
import json
import os
import threading
import time

__all__ = ["record", "list_entries", "get_entry", "delete", "clear",
           "scan_output_dir", "migrate_flat_tasks", "path"]

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_PATH = os.path.join(ROOT, "history.json")
MAX_ENTRIES = 500          # 防止无限增长
MAX_TEXT = 200000          # 单条文案最多存 20 万字符

_LOCK = threading.RLock()
_CACHE = None


def path():
    return os.environ.get("WXT_HISTORY_PATH") or DEFAULT_PATH


# --------------------------------------------------------------------------
# 读写
# --------------------------------------------------------------------------

def _read():
    p = path()
    if not os.path.exists(p):
        return []
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and isinstance(data.get("entries"), list):
            return data["entries"]
    except Exception:
        pass
    return []


def _write(entries):
    global _CACHE
    with _LOCK:
        p = path()
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(entries[:MAX_ENTRIES], f, ensure_ascii=False, indent=2)
        os.replace(tmp, p)
        _CACHE = entries[:MAX_ENTRIES]


def _load(force=False):
    global _CACHE
    with _LOCK:
        if _CACHE is None or force:
            _CACHE = _read()
        return list(_CACHE)


# --------------------------------------------------------------------------
# 写
# --------------------------------------------------------------------------

def _time_str(ts=None):
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts or time.time()))


def record(result, kind="", source=""):
    """
    把一次成功提取写进历史。result 是 pipeline.process() 的返回值。
    返回写入的记录（含 id）。
    """
    outdir = result.get("outdir") or ""
    meta = result.get("meta") or {}
    stats = result.get("stats") or {}
    files = result.get("files") or {}

    text = result.get("text") or ""
    if not text and files.get("txt") and os.path.exists(files["txt"]):
        try:
            with open(files["txt"], "r", encoding="utf-8") as f:
                text = f.read()
        except Exception:
            text = ""

    entry = {
        "id": os.path.basename(outdir.rstrip("\\/")) or ("task_%d" % int(time.time())),
        "created": time.time(),
        "created_str": _time_str(),
        "title": meta.get("title") or "未命名",
        "author": meta.get("author") or "",
        "source_url": meta.get("source_url") or source or "",
        "kind": kind,
        "engine": stats.get("engine") or "",
        "chars": stats.get("chars") or len(text),
        "duration_s": meta.get("duration_s") or 0,
        "elapsed": round(result.get("elapsed") or 0, 1),
        "outdir": outdir,
        "group": result.get("group") or "",
        "series": result.get("series") or "",
        "episode": result.get("episode") or "",
        "files": {k: v for k, v in files.items()},
        "text": text[:MAX_TEXT],
    }

    with _LOCK:
        entries = _load(force=True)
        entries = [e for e in entries if e.get("id") != entry["id"]]
        entries.insert(0, entry)
        _write(entries)
    return entry


def delete(task_id):
    with _LOCK:
        entries = _load(force=True)
        left = [e for e in entries if e.get("id") != task_id]
        if len(left) == len(entries):
            return False
        _write(left)
        return True


def clear():
    with _LOCK:
        _write([])
    return True


# --------------------------------------------------------------------------
# 读
# --------------------------------------------------------------------------

def list_entries():
    """返回历史列表（不含正文，减小体积）。"""
    out = []
    for e in _load(force=True):
        out.append({k: v for k, v in e.items() if k != "text"})
    return out


def get_entry(task_id):
    for e in _load(force=True):
        if e.get("id") == task_id:
            return dict(e)
    return None


# --------------------------------------------------------------------------
# 导入已有的输出目录
# --------------------------------------------------------------------------

def _entry_meta(folder):
    """从任务目录里的 json 读出标题/作者（用于归档）."""
    js = None
    for fn in sorted(os.listdir(folder)):
        if fn.endswith(".json"):
            js = os.path.join(folder, fn)
            break
    if not js:
        return "", ""
    try:
        with open(js, "r", encoding="utf-8") as f:
            d = json.load(f)
        m = d.get("meta") or {}
        return m.get("title") or "", m.get("author") or ""
    except Exception:
        return "", ""


def migrate_flat_tasks(outroot=None):
    """
    把散在 output/ 下的 task_* 文件夹，按「短剧名/第N集」重新归档。

    只移动本程序自己建的 task_* 目录，其它目录一律不碰；
    移动前会打印计划，遇到同名目录自动加序号。返回 (移动数, 明细)。
    """
    import shutil
    from .naming import plan_folders

    outroot = outroot or os.path.join(ROOT, "output")
    if not os.path.isdir(outroot):
        return 0, []

    moved = []
    for name in sorted(os.listdir(outroot)):
        full = os.path.join(outroot, name)
        if not os.path.isdir(full) or not name.startswith("task_"):
            continue

        title, author = _entry_meta(full)
        if not title:
            continue
        parent, inner, info = plan_folders(outroot, title, author, fallback_stamp=name)
        if os.path.abspath(parent) == os.path.abspath(outroot) and not info.get("group"):
            continue                      # 没有分组信息，保持原样
        os.makedirs(parent, exist_ok=True)

        target = os.path.join(parent, inner)
        if os.path.exists(target):
            target = os.path.join(parent, "%s_%d" % (inner, 2))
            n = 2
            while os.path.exists(target):
                n += 1
                target = os.path.join(parent, "%s_%d" % (inner, n))
        try:
            shutil.move(full, target)
            moved.append({"from": full, "to": target, "title": title,
                          "group": info.get("group") or "", "episode": info.get("episode") or ""})
        except Exception as e:
            moved.append({"from": full, "to": "", "title": title, "error": str(e)})

    # 同步修正历史里的路径
    if moved:
        mapping = {m["from"]: m["to"] for m in moved if m.get("to")}
        with _LOCK:
            entries = _load(force=True)
            for e in entries:
                od = e.get("outdir") or ""
                if od in mapping:
                    newdir = mapping[od]
                    for k, v in list((e.get("files") or {}).items()):
                        if v.startswith(od):
                            e["files"][k] = newdir + v[len(od):]
                    e["outdir"] = newdir
                    e["id"] = os.path.basename(newdir.rstrip("\\/"))
            _write(entries)

    return len([m for m in moved if m.get("to")]), moved


def scan_output_dir(outroot=None):
    """
    扫描 output/ 下已有的 task_* 目录，把还没记进历史的任务补进来。
    每次成功任务都写了 json，从这里恢复标题、正文等信息。
    """
    outroot = outroot or os.path.join(ROOT, "output")
    if not os.path.isdir(outroot):
        return 0

    known = {e.get("id") for e in _load(force=True)}
    added = []

    candidates = []
    for name in sorted(os.listdir(outroot)):
        full = os.path.join(outroot, name)
        if not os.path.isdir(full):
            continue
        if name.startswith("task_"):
            candidates.append(full)
        else:                                   # 上一层是「短剧名」，里面按集数分
            for sub in sorted(os.listdir(full)):
                subfull = os.path.join(full, sub)
                if os.path.isdir(subfull):
                    candidates.append(subfull)

    for full in candidates:
        # 去重键必须和写入时的 id 一致（相对 output 的路径），
        # 否则新老结构混用时每次扫描都会重复导入。
        rel = os.path.relpath(full, outroot).replace(os.sep, "/")
        name = os.path.basename(full.rstrip("\\/"))
        if rel in known or name in known:
            continue

        txt = js = None
        for fn in sorted(os.listdir(full)):
            if fn.endswith(".txt"):
                txt = os.path.join(full, fn)
            elif fn.endswith(".json"):
                js = os.path.join(full, fn)
        if not (txt or js):
            continue

        text, meta, stats, files = "", {}, {}, {}
        if js and os.path.exists(js):
            try:
                with open(js, "r", encoding="utf-8") as f:
                    d = json.load(f)
                meta = d.get("meta") or {}
                stats = d.get("stats") or {}
                text = d.get("text") or ""
            except Exception:
                pass
        if not text and txt and os.path.exists(txt):
            try:
                with open(txt, "r", encoding="utf-8") as f:
                    text = f.read()
            except Exception:
                pass

        for fn in sorted(os.listdir(full)):
            low = fn.lower()
            p = os.path.join(full, fn)
            if low.endswith(".txt"):
                files["txt"] = p
            elif low.endswith(".srt"):
                files["srt"] = p
            elif low.endswith(".md"):
                files["md"] = p
            elif low.endswith(".json"):
                files["json"] = p
            elif low.endswith((".mp4", ".m4a", ".wav", ".mp3")):
                files["video"] = p

        from .naming import clean_name, group_of, split_series
        _title = meta.get("title") or (os.path.splitext(os.path.basename(txt))[0] if txt else name)
        series, ep = split_series(_title)
        group = series or group_of(_title, meta.get("author") or "")

        mtime = os.path.getmtime(full)
        added.append({
            "id": rel,
            "created": mtime,
            "created_str": _time_str(mtime),
            "title": _title,
            "author": meta.get("author") or "",
            "source_url": meta.get("source_url") or "",
            "kind": "scan",
            "engine": stats.get("engine") or "",
            "chars": stats.get("chars") or len(text),
            "duration_s": meta.get("duration_s") or 0,
            "elapsed": 0,
            "outdir": full,
            "group": group,
            "series": series,
            "episode": ep,
            "files": files,
            "text": text[:MAX_TEXT],
        })

    if added:
        with _LOCK:
            entries = _load(force=True)
            entries.extend(added)
            entries.sort(key=lambda e: e.get("created") or 0, reverse=True)
            _write(entries)
    return len(added)
