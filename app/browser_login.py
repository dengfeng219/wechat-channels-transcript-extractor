# -*- coding: utf-8 -*-
"""
一键获取腾讯元宝登录态。

思路：用系统自带的 Edge/Chrome 开一个**独立配置目录**的窗口打开元宝，
你在里面扫码登录后，本程序通过 Chrome DevTools Protocol 读取该配置下的
全部 Cookie（包含 HttpOnly 的那些，因此比手工复制更完整）。

只监听 127.0.0.1，读取完成后立即关闭浏览器并释放调试端口。
"""
import json
import os
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request

__all__ = ["start_login", "status", "cancel"]

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROFILE_DIR = os.path.join(ROOT, ".browser_profile")
DEBUG_PORT = 9333
YUANBAO_URL = "https://yuanbao.tencent.com/chat/"

_STATE = {
    "running": False,
    "stage": "",
    "message": "",
    "cookie": "",
    "ok": False,
    "error": "",
}
_LOCK = threading.Lock()
_CANCEL = threading.Event()
_PROC = None


def _set(**kw):
    with _LOCK:
        _STATE.update(kw)


def status():
    with _LOCK:
        return dict(_STATE)


def cancel():
    _CANCEL.set()


def _browser_candidates():
    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    lad = os.environ.get("LOCALAPPDATA", "")
    return [
        os.path.join(pf86, r"Microsoft\Edge\Application\msedge.exe"),
        os.path.join(pf, r"Microsoft\Edge\Application\msedge.exe"),
        os.path.join(pf, r"Google\Chrome\Application\chrome.exe"),
        os.path.join(pf86, r"Google\Chrome\Application\chrome.exe"),
        os.path.join(lad, r"Google\Chrome\Application\chrome.exe") if lad else "",
    ]


def find_browser():
    for path in _browser_candidates():
        if path and os.path.isfile(path):
            return path
    return ""


def _wait_debugger(timeout=30):
    """等待 DevTools 端口就绪，返回 browser 的 webSocketDebuggerUrl。"""
    deadline = time.time() + timeout
    url = "http://127.0.0.1:%d/json/version" % DEBUG_PORT
    while time.time() < deadline:
        if _CANCEL.is_set():
            return ""
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                data = json.loads(r.read().decode("utf-8"))
            ws = data.get("webSocketDebuggerUrl") or ""
            if ws:
                return ws
        except Exception:
            pass
        time.sleep(0.6)
    return ""


def _read_cookies(ws_url, timeout=20):
    """通过 CDP 读取浏览器上下文里的全部 Cookie。"""
    from websockets.sync.client import connect
    with connect(ws_url, open_timeout=timeout, close_timeout=5,
                 max_size=16 * 1024 * 1024) as ws:
        ws.send(json.dumps({"id": 1, "method": "Storage.getCookies", "params": {}}))
        deadline = time.time() + timeout
        while time.time() < deadline:
            raw = ws.recv(timeout=max(1, deadline - time.time()))
            msg = json.loads(raw)
            if msg.get("id") == 1:
                return (msg.get("result") or {}).get("cookies") or []
    return []


def _cookie_header(cookies):
    """只保留腾讯域下的 Cookie，拼成请求头。"""
    parts, seen = [], set()
    for c in cookies:
        domain = (c.get("domain") or "").lower()
        name = c.get("name") or ""
        if "tencent.com" not in domain and "yuanbao" not in domain and "qq.com" not in domain:
            continue
        if not name or name in seen:
            continue
        seen.add(name)
        parts.append("%s=%s" % (name, c.get("value") or ""))
    return "; ".join(parts)


def _run(timeout=300):
    global _PROC
    try:
        exe = find_browser()
        if not exe:
            _set(stage="error", error="没有找到 Edge 或 Chrome 浏览器", running=False)
            return

        os.makedirs(PROFILE_DIR, exist_ok=True)
        _set(stage="launching", message="正在打开登录窗口…")
        creation = 0
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            creation = 0  # 浏览器是 GUI 程序，不需要隐藏窗口
        _PROC = subprocess.Popen([
            exe,
            "--remote-debugging-port=%d" % DEBUG_PORT,
            "--user-data-dir=%s" % PROFILE_DIR,
            "--no-first-run", "--no-default-browser-check",
            "--disable-features=Translate",
            YUANBAO_URL,
        ], creationflags=creation)

        ws_url = _wait_debugger(40)
        if not ws_url:
            _set(stage="error", running=False,
                 error="浏览器调试端口未就绪，请重试（或改用「复制为 cURL」方式）")
            return

        _set(stage="waiting", message="请在打开的窗口里扫码登录腾讯元宝…")

        deadline = time.time() + timeout
        last_msg = ""
        while time.time() < deadline and not _CANCEL.is_set():
            try:
                cookies = _read_cookies(ws_url)
            except Exception as e:
                last_msg = "读取 Cookie 失败：%s" % e
                cookies = []
            header = _cookie_header(cookies)
            if header:
                _set(stage="verifying", message="已读取到登录态，正在校验…", cookie=header)
                from .resolver import check_login
                ok, msg = check_login(header)
                if ok:
                    try:  # 写入本机配置，之后不用再扫码
                        from . import config
                        config.set_value("yuanbao_cookie", header)
                    except Exception:
                        pass
                    _set(running=False, ok=True, stage="done", cookie=header,
                         message="登录成功，登录态已保存到本机")
                    return
                last_msg = msg
            time.sleep(2)

        if _CANCEL.is_set():
            _set(running=False, stage="cancelled", error="已取消")
        else:
            _set(running=False, stage="error",
                 error="超时未检测到有效登录态。%s" % last_msg)
    except Exception as e:
        _set(running=False, stage="error", error="%s: %s" % (type(e).__name__, e))
    finally:
        _close_browser()


def _close_browser():
    global _PROC
    try:
        if _PROC and _PROC.poll() is None:
            _PROC.terminate()
            try:
                _PROC.wait(timeout=6)
            except Exception:
                _PROC.kill()
    except Exception:
        pass
    _PROC = None


def start_login(timeout=300):
    """启动一键登录流程（后台线程），立即返回当前状态。"""
    with _LOCK:
        if _STATE.get("running"):
            return dict(_STATE)
    _CANCEL.clear()
    _set(running=True, ok=False, error="", cookie="", stage="starting",
         message="正在准备登录窗口…")
    threading.Thread(target=_run, kwargs={"timeout": timeout}, daemon=True).start()
    return status()
