# -*- coding: utf-8 -*-
"""
本机配置：把登录态等设置保存在项目内的 config.json，避免每次都要重新获取。

文件权限尽量收紧（仅当前用户可读写），并且只在解析请求时随请求发给腾讯元宝，
不会发送到任何其它服务器。
"""
import json
import os
import stat
import threading

__all__ = ["load", "save", "get", "set_value", "path"]

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_PATH = os.path.join(ROOT, "config.json")


def path():
    """配置文件位置；测试可用 WXT_CONFIG_PATH 指向临时文件，避免动到真实登录态。"""
    return os.environ.get("WXT_CONFIG_PATH") or DEFAULT_PATH
# 注意：save() 内部会调用 load()，必须用可重入锁，否则自锁死
_LOCK = threading.RLock()
_CACHE = None

_DEFAULTS = {
    "yuanbao_cookie": "",
    "engine": "paraformer",
    "language": "zh",
    # —— 文案校对（可选）——
    "llm_api_key": "",            # 留空则跳过 AI 校对
    "llm_base_url": "https://api.deepseek.com",
    "llm_model": "deepseek-chat",
    "proofread_rules": [],        # 用户自定义替换：[["错词","对词"], ...]
}


def _read_file():
    data = {}
    try:
        p = path()
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                saved = json.load(f)
            if isinstance(saved, dict):
                data = {k: v for k, v in saved.items() if not k.startswith("_")}
    except Exception:
        pass
    return data


def load(force=False):
    global _CACHE
    with _LOCK:
        if _CACHE is not None and not force:
            return dict(_CACHE)
        data = dict(_DEFAULTS)
        data.update(_read_file())
        _CACHE = data
        return dict(data)


def save(data):
    global _CACHE
    with _LOCK:
        merged = dict(_DEFAULTS)
        merged.update(_read_file())      # 直接读文件，避免重入 load()
        merged.update(data or {})
        p = path()
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(merged, f, ensure_ascii=False, indent=2)
        try:
            os.replace(tmp, p)
        except OSError:
            # 目标文件 ACL 不给删除权限时（老版本收紧过头留下的），
            # 退化成直接写入，至少别让用户改不了设置。
            try:
                with open(p, "w", encoding="utf-8") as f:
                    json.dump(merged, f, ensure_ascii=False, indent=2)
            finally:
                try:
                    os.remove(tmp)
                except OSError:
                    pass
        _harden(p)
        _CACHE = merged
        return dict(merged)


def _harden(path):
    """
    把配置文件权限收紧为「仅当前用户可访问」。
    Windows 上 POSIX 权限位无效，必须用 icacls 改 ACL（去掉继承，只授权当前用户）。

    注意必须给 (F) 完全控制，不能只给 (R,W)：
    save() 是「写临时文件再改名覆盖」实现的，而改名覆盖需要目标文件的
    删除权限；只给 R,W 会导致**第二次保存开始全部失败**。
    """
    if os.name == "nt":
        user = os.environ.get("USERNAME") or ""
        if not user:
            return
        try:
            import subprocess
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            subprocess.run(
                ["icacls", path, "/inheritance:r", "/grant:r", "%s:(F)" % user],
                capture_output=True, creationflags=flags, timeout=15)
        except Exception:
            pass
    else:
        try:
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
        except Exception:
            pass


def get(key, default=None):
    return load().get(key, default)


def set_value(key, value):
    return save({key: value})
