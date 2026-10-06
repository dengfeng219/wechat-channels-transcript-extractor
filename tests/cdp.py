# -*- coding: utf-8 -*-
"""
极简 CDP 客户端（浏览器级 + 扁平会话模式）。

新版 Edge/Chrome 直接连「页面 target」的 websocket 不再响应命令，
必须走 Target.attachToTarget(flatten=True) 拿到 sessionId，
再把命令带上 sessionId 发到浏览器级 websocket。这个模块就是干这个的。
"""
import base64
import json
import os
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import browser_login as bl          # noqa: E402
from websockets.sync.client import connect   # noqa: E402

def _free_port():
    """让系统分配一个空闲端口，避免撞上残留实例占用的端口。"""
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p

def _kill_stale(profile_dir):
    """
    只杀掉「命令行里带着我们这个配置目录」的 Edge 进程。
    绝不动用户自己开的浏览器。
    """
    key = os.path.basename(profile_dir.rstrip("\\/"))
    try:
        import subprocess as sp
        out = sp.run(["wmic", "process", "where", "name='msedge.exe'", "get",
                      "ProcessId,CommandLine", "/format:csv"],
                     capture_output=True, text=True, errors="ignore", timeout=25).stdout
    except Exception:
        return 0
    killed = 0
    for line in out.splitlines():
        if key and key in line and "msedge.exe" in line.lower():
            parts = line.rsplit(",", 1)
            try:
                pid = int(parts[-1].strip())
            except Exception:
                continue
            try:
                sp.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, timeout=10)
                killed += 1
            except Exception:
                pass
    return killed

class Browser(object):
    def __init__(self, port, profile_dir, headless=False, window="1280,1500"):
        self.profile = profile_dir
        os.makedirs(profile_dir, exist_ok=True)
        n = _kill_stale(profile_dir)
        if n:
            print("  清理了 %d 个残留的调试浏览器进程" % n)
            time.sleep(2)
        # 端口被占就换一个，确保连到的是我们自己刚启动的实例
        if port:
            import socket
            s = socket.socket()
            try:
                s.bind(("127.0.0.1", port))
                s.close()
            except OSError:
                print("  端口 %d 被占用，改用空闲端口" % port)
                port = _free_port()
            else:
                s.close()
        self.port = port or _free_port()
        exe = bl.find_browser()
        if not exe:
            raise RuntimeError("没找到 Edge/Chrome")
        args = [exe, "--remote-debugging-port=%d" % self.port,
                "--user-data-dir=%s" % profile_dir, "--no-first-run",
                "--no-default-browser-check", "--hide-scrollbars",
                "--window-size=%s" % window]
        if headless:
            args.append("--headless=new")
        args.append("about:blank")
        self.proc = subprocess.Popen(args)
        self.ws = None
        self.session = None
        self._id = 0

    # ---------- 连接 ----------
    def connect(self, timeout=120):
        for _ in range(timeout):
            try:
                with urllib.request.urlopen("http://127.0.0.1:%d/json/version" % self.port,
                                            timeout=3) as r:
                    ver = json.loads(r.read())
                self.ws = connect(ver["webSocketDebuggerUrl"], open_timeout=30,
                                  max_size=128 * 1024 * 1024)
                return True
            except Exception:
                time.sleep(1)
        return False

    def send(self, method, params=None, session=None):
        self._id += 1
        msg = {"id": self._id, "method": method, "params": params or {}}
        sid = session if session is not None else self.session
        if sid:
            msg["sessionId"] = sid
        self.ws.send(json.dumps(msg))
        return self._id

    def wait(self, want_id, timeout=25):
        dl = time.time() + timeout
        while time.time() < dl:
            try:
                m = json.loads(self.ws.recv(timeout=3))
            except Exception:
                continue
            if m.get("id") == want_id:
                return m
        return {}

    def call(self, method, params=None, timeout=25):
        return self.wait(self.send(method, params), timeout)

    # ---------- 打开页面 ----------
    def open(self, url, wait=8):
        r = self.call("Target.createTarget", {"url": url}, timeout=30)
        tid = (r.get("result") or {}).get("targetId")
        if not tid:
            raise RuntimeError("创建页面失败: %s" % r)
        r = self.call("Target.attachToTarget", {"targetId": tid, "flatten": True}, timeout=30)
        self.session = (r.get("result") or {}).get("sessionId")
        if not self.session:
            raise RuntimeError("附加页面失败: %s" % r)
        self.call("Page.enable")
        self.call("Runtime.enable")
        time.sleep(wait)
        return tid

    # ---------- 常用操作 ----------
    def js(self, expr, timeout=25):
        r = self.call("Runtime.evaluate",
                      {"expression": expr, "returnByValue": True, "awaitPromise": True},
                      timeout)
        res = (r.get("result") or {})
        out = res.get("result") or {}
        if out.get("subtype") == "error" or res.get("exceptionDetails"):
            return None
        return out.get("value")

    def shot(self, path, timeout=30):
        r = self.call("Page.captureScreenshot", {"format": "png"}, timeout)
        d = (r.get("result") or {}).get("data")
        if not d:
            return ""
        with open(path, "wb") as f:
            f.write(base64.b64decode(d))
        return path

    def close(self):
        try:
            if self.ws:
                self.ws.close()
        except Exception:
            pass
        try:
            self.proc.terminate()
            self.proc.wait(timeout=8)
        except Exception:
            try:
                self.proc.kill()
            except Exception:
                pass
