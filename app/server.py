# -*- coding: utf-8 -*-
"""
本地 Web 服务：为图形界面提供 REST 接口。

设计取舍：
  * 只用 Python 标准库（http.server），不引入额外 Web 框架，离线可用。
  * 任务串行执行（单个 ASR 模型实例），通过 /api/job 轮询进度。
  * 上传采用「原始二进制 + X-Filename 头」，避免手写 multipart 解析。
"""
import json
import os
import queue
import threading
import time
import traceback
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import __version__
from .asr import ENGINES, check_env
from .pipeline import DEFAULT_OUT, process
from .resolver import check_login, is_share_url

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB_DIR = os.path.join(ROOT, "web")
UPLOAD_DIR = os.path.join(ROOT, "uploads")

_JOBS = {}
_JOB_LOCK = threading.Lock()
_TASK_Q = queue.Queue()
_JOB_SEQ = [0]
_RECORDER = [None]


def _recorder():
    """全局单例录音器。"""
    from .loopback import Recorder
    if _RECORDER[0] is None:
        _RECORDER[0] = Recorder()
    return _RECORDER[0]


def _new_job_id():
    with _JOB_LOCK:
        _JOB_SEQ[0] += 1
        return "job%04d" % _JOB_SEQ[0]


def _update(job_id, **kw):
    with _JOB_LOCK:
        if job_id in _JOBS:
            _JOBS[job_id].update(kw)


def _worker():
    """串行消费任务队列。"""
    while True:
        job_id, req = _TASK_Q.get()
        try:
            _update(job_id, status="running", started=time.time())
            logs = []

            def _log(msg):
                logs.append("[%s] %s" % (time.strftime("%H:%M:%S"), msg))
                if len(logs) > 300:
                    del logs[:-300]
                _update(job_id, logs=list(logs))

            def _prog(info):
                _update(job_id, progress=info)

            result = process(req, on_progress=_prog, log=_log)
            _update(job_id, status="done", result=result, finished=time.time())
        except Exception as e:
            _update(job_id, status="error",
                    error="%s: %s" % (type(e).__name__, e),
                    trace=traceback.format_exc(), finished=time.time())
        finally:
            _TASK_Q.task_done()


threading.Thread(target=_worker, daemon=True).start()


class Handler(BaseHTTPRequestHandler):
    server_version = "WxTranscript/" + __version__

    def log_message(self, fmt, *args):
        pass  # 静音访问日志

    # ---------- 工具 ----------
    def _json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def _read_json(self):
        raw = self._read_body()
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    def _serve_static(self, rel):
        path = os.path.join(WEB_DIR, rel)
        if not os.path.isfile(path):
            self.send_error(404, "Not Found")
            return
        ext = os.path.splitext(path)[1].lower()
        ctype = {".html": "text/html; charset=utf-8",
                 ".js": "application/javascript; charset=utf-8",
                 ".css": "text/css; charset=utf-8",
                 ".svg": "image/svg+xml",
                 ".png": "image/png",
                 ".ico": "image/x-icon"}.get(ext, "application/octet-stream")
        with open(path, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ---------- GET ----------
    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)

        if u.path in ("/", "/index.html"):
            return self._serve_static("index.html")

        if u.path == "/api/env":
            from . import config
            env = check_env()
            saved_cookie = (config.get("yuanbao_cookie") or "").strip()
            return self._json({
                "version": __version__,
                "engines": list(ENGINES),
                "env": env,
                "outdir": DEFAULT_OUT,
                "has_saved_cookie": bool(saved_cookie),
                "saved_cookie_hint": ("已保存 %d 项" % len(saved_cookie.split("; "))
                                      if saved_cookie else ""),
            })

        if u.path == "/api/job":
            jid = (q.get("id") or [""])[0]
            with _JOB_LOCK:
                job = _JOBS.get(jid)
            if not job:
                return self._json({"error": "任务不存在"}, 404)
            return self._json(job)

        if u.path == "/api/record/devices":
            from .loopback import available_devices, have_loopback
            return self._json({"ok": True, "supported": have_loopback(),
                               "devices": available_devices()})

        if u.path == "/api/record/status":
            from .loopback import Recorder
            return self._json(_recorder().status())

        if u.path == "/api/browser_login_status":
            from .browser_login import status as bl_status
            return self._json(bl_status())

        if u.path == "/api/proofread/info":
            from . import config, proofread
            rules = config.get("proofread_rules") or []
            txt = "\n".join("%s=%s" % (r[0], r[1]) for r in rules
                             if isinstance(r, (list, tuple)) and len(r) == 2)
            return self._json({
                "ok": True,
                "has_key": proofread.has_llm(),
                "base_url": config.get("llm_base_url") or "https://api.deepseek.com",
                "model": config.get("llm_model") or "deepseek-chat",
                "rules_text": txt,
                "builtin_rules": len(proofread.DEFAULT_RULES),
            })

        if u.path == "/api/history":
            from . import history
            q = urllib.parse.parse_qs(u.query)
            limit = int((q.get("limit") or ["200"])[0])
            return self._json({"ok": True, "entries": history.list_entries()[:limit],
                               "total": len(history.list_entries())})

        if u.path == "/api/history/item":
            from . import history
            q = urllib.parse.parse_qs(u.query)
            tid = (q.get("id") or [""])[0]
            e = history.get_entry(tid)
            if not e:
                return self._json({"ok": False, "error": "记录不存在"}, 404)
            # 正文优先从文件读，文件没了就用历史里存的那份
            text = e.get("text") or ""
            tf = (e.get("files") or {}).get("txt")
            if tf and os.path.isfile(tf):
                try:
                    with open(tf, "r", encoding="utf-8") as f:
                        text = f.read()
                except Exception:
                    pass
            e["text"] = text
            return self._json({"ok": True, "entry": e})

        if u.path == "/api/jobs":
            with _JOB_LOCK:
                return self._json({"jobs": [
                    {"id": k, "status": v.get("status"),
                     "title": (v.get("result") or {}).get("meta", {}).get("title", ""),
                     "created": v.get("created")}
                    for k, v in sorted(_JOBS.items(), reverse=True)]})

        if u.path == "/api/file":
            p = (q.get("path") or [""])[0]
            p = os.path.abspath(p)
            if not os.path.isfile(p) or not p.startswith(os.path.abspath(ROOT)):
                return self._json({"error": "非法路径"}, 403)
            with open(p, "rb") as f:
                body = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        return self.send_error(404, "Not Found")

    # ---------- POST ----------
    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        try:
            if u.path == "/api/check_login":
                from . import config
                body = self._read_json()
                cookie = (body.get("cookie") or "").strip()
                ok, msg = check_login(cookie)
                if ok:  # 校验通过就持久化，下次不用再填
                    config.set_value("yuanbao_cookie", cookie)
                return self._json({"ok": ok, "message": msg,
                                   "saved": bool(ok and cookie)})

            # 从粘贴内容（Cookie 串 / 请求头 / Copy as cURL / 插件 JSON）中提取 Cookie
            if u.path == "/api/import_cookie":
                from .cookie_import import extract_cookie
                body = self._read_json()
                raw = body.get("text") or ""
                cookie = extract_cookie(raw)
                if not cookie:
                    return self._json({"ok": False,
                                       "error": "没能从粘贴内容里识别出 Cookie，"
                                                "请确认复制的是含 cookie 的请求"})
                ok, msg = check_login(cookie)
                names = [p.split("=", 1)[0] for p in cookie.split("; ") if "=" in p]
                if ok:  # 校验通过就写入本机配置
                    from . import config
                    config.set_value("yuanbao_cookie", cookie)
                return self._json({"ok": True, "cookie": cookie, "login_ok": ok,
                                   "saved": bool(ok), "message": msg,
                                   "count": len(names), "names": names[:12]})

            # ---- 一键浏览器登录 ----
            if u.path == "/api/browser_login":
                from .browser_login import start_login, status as bl_status
                body = self._read_json()
                st = start_login(timeout=int(body.get("timeout") or 300))
                return self._json(st)

            # ---- 录制电脑声音（无需登录态）----
            if u.path == "/api/record/start":
                body = self._read_json()
                r = _recorder()
                st = r.start(device_index=body.get("device_index"))
                if not st.get("recording"):
                    return self._json({"ok": False,
                                       "error": st.get("error") or "无法开始录制"}, 400)
                return self._json({"ok": True, "status": st})

            if u.path == "/api/record/stop":
                body = self._read_json()
                r = _recorder()
                st = r.stop()
                wav = st.get("path") or r.wav_path
                if not wav or not os.path.exists(wav) or os.path.getsize(wav) < 20000:
                    return self._json({"ok": False,
                                       "error": "没有录到有效声音，请确认播放时有声音输出"}, 400)
                jid = _new_job_id()
                req = {"source": "file", "path": wav,
                       "engine": body.get("engine") or "paraformer",
                       "language": body.get("language") or "zh"}
                if body.get("outdir"):
                    req["outdir"] = body["outdir"]
                with _JOB_LOCK:
                    _JOBS[jid] = {"id": jid, "status": "queued", "created": time.time(),
                                  "progress": {"stage": "排队中", "percent": 0, "message": ""},
                                  "logs": [], "req": {"source": "file"}}
                _TASK_Q.put((jid, req))
                return self._json({"ok": True, "job_id": jid, "wav": wav,
                                   "seconds": st.get("seconds")})

            if u.path == "/api/browser_login_cancel":
                from .browser_login import cancel
                cancel()
                return self._json({"ok": True})

            if u.path == "/api/resolve":
                from .resolver import resolve
                body = self._read_json()
                url = (body.get("url") or "").strip()
                if not is_share_url(url):
                    return self._json({"ok": False, "error": "不是有效的视频号分享链接"}, 400)
                feed = resolve(url, cookie=body.get("cookie"))
                feed.pop("raw", None)
                return self._json({"ok": True, "feed": feed})

            if u.path == "/api/upload":
                name = urllib.parse.unquote(self.headers.get("X-Filename") or "upload.mp4")
                name = os.path.basename(name)
                os.makedirs(UPLOAD_DIR, exist_ok=True)
                dst = os.path.join(UPLOAD_DIR, name)
                data = self._read_body()
                with open(dst, "wb") as f:
                    f.write(data)
                return self._json({"ok": True, "path": dst, "size": len(data)})

            if u.path == "/api/transcribe":
                body = self._read_json()

                # ---- 批量：一次提交多个链接 ----
                urls = body.get("urls")
                if isinstance(urls, list) and urls:
                    from .resolver import is_share_url
                    clean, bad = [], []
                    for raw in urls:
                        u = (raw or "").strip()
                        if is_share_url(u):
                            clean.append(u)
                        elif u:
                            bad.append(u)
                    if not clean:
                        return self._json({"ok": False,
                                           "error": "没有识别到有效的视频号分享链接"}, 400)
                    ids = []
                    for u in clean:
                        jid = _new_job_id()
                        req = {k: v for k, v in body.items() if k != "urls"}
                        req["source"] = "link"
                        req["url"] = u
                        with _JOB_LOCK:
                            _JOBS[jid] = {"id": jid, "status": "queued",
                                          "created": time.time(),
                                          "url": u,
                                          "progress": {"stage": "排队中", "percent": 0,
                                                       "message": ""},
                                          "logs": [], "req": {"source": "link"}}
                        _TASK_Q.put((jid, req))
                        ids.append({"job_id": jid, "url": u})
                    return self._json({"ok": True, "batch": True,
                                       "count": len(ids), "jobs": ids,
                                       "invalid": bad})

                if body.get("source") == "file":
                    p = body.get("path") or ""
                    if not os.path.isfile(p):
                        return self._json({"ok": False, "error": "文件不存在：%s" % p}, 400)
                jid = _new_job_id()
                with _JOB_LOCK:
                    _JOBS[jid] = {"id": jid, "status": "queued", "created": time.time(),
                                  "progress": {"stage": "排队中", "percent": 0, "message": ""},
                                  "logs": [], "req": {k: v for k, v in body.items() if k != "cookie"}}
                _TASK_Q.put((jid, body))
                return self._json({"ok": True, "job_id": jid})

            # ---- 历史任务 ----
            # ---- 文案校对设置 ----
            if u.path == "/api/proofread/save":
                from . import config, proofread
                body = self._read_json()
                upd = {}
                if "api_key" in body:
                    upd["llm_api_key"] = (body.get("api_key") or "").strip()
                if "base_url" in body:
                    upd["llm_base_url"] = (body.get("base_url") or "").strip() or "https://api.deepseek.com"
                if "model" in body:
                    upd["llm_model"] = (body.get("model") or "").strip() or "deepseek-chat"
                if "rules" in body:
                    raw = body.get("rules") or ""
                    rules = []
                    for line in str(raw).splitlines():
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        for sep in ("=", chr(8594), "->", "\t"):
                            if sep in line:
                                a, b = line.split(sep, 1)
                                a, b = a.strip(), b.strip()
                                if a and b and a != b:
                                    rules.append([a, b])
                                break
                    upd["proofread_rules"] = rules
                config.save(upd)
                proofread.invalidate_cache()
                return self._json({"ok": True, "has_key": proofread.has_llm(),
                                   "rules": len(config.get("proofread_rules") or [])})

            if u.path == "/api/proofread/test":
                from . import proofread
                body = self._read_json()
                src = (body.get("text") or "").strip()
                if not src:
                    return self._json({"ok": False, "error": "请先输入要试的文本"}, 400)
                after, hits = proofread.apply_rules(src)
                out = {"ok": True, "rules_hits": len(hits), "after_rules": after}
                if proofread.has_llm():
                    fixed, note = proofread.proofread_with_llm(after)
                    out["after_llm"] = fixed
                    out["note"] = note
                else:
                    out["note"] = "未配置 API Key，只做了固定替换"
                return self._json(out)

            if u.path == "/api/history/delete":
                from . import history
                body = self._read_json()
                return self._json({"ok": history.delete((body.get("id") or "").strip())})

            if u.path == "/api/history/scan":
                from . import history
                n = history.scan_output_dir()
                return self._json({"ok": True, "added": n})

            if u.path == "/api/history/migrate":
                from . import history
                n, detail = history.migrate_flat_tasks()
                history.scan_output_dir()      # 重新登记（路径已变）
                return self._json({"ok": True, "moved": n, "detail": detail[:40]})

            if u.path == "/api/history/clear":
                from . import history
                history.clear()
                return self._json({"ok": True})

            if u.path == "/api/extract_urls":
                from .resolver import extract_share_urls
                body = self._read_json()
                us = extract_share_urls(body.get("text") or "")
                return self._json({"ok": True, "urls": us, "count": len(us)})

            if u.path == "/api/open_folder":
                body = self._read_json()
                p = os.path.abspath(body.get("path") or DEFAULT_OUT)
                if not p.startswith(os.path.abspath(ROOT)):
                    return self._json({"ok": False, "error": "非法路径"}, 403)
                os.makedirs(p, exist_ok=True)
                if hasattr(os, "startfile"):
                    os.startfile(p)  # noqa: S606
                return self._json({"ok": True, "path": p})

        except Exception as e:
            return self._json({"ok": False, "error": "%s: %s" % (type(e).__name__, e),
                               "trace": traceback.format_exc()}, 500)

        return self.send_error(404, "Not Found")


def serve(host="127.0.0.1", port=8765, open_browser=True):
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    os.makedirs(DEFAULT_OUT, exist_ok=True)
    httpd = ThreadingHTTPServer((host, port), Handler)
    url = "http://%s:%d/" % (host, port)
    print("=" * 58)
    print("  视频号文案提取器  v%s" % __version__)
    print("  界面地址: %s" % url)
    print("  输出目录: %s" % DEFAULT_OUT)
    print("  按 Ctrl+C 退出")
    print("=" * 58)
    if open_browser:
        threading.Thread(target=lambda: (time.sleep(1.0), webbrowser.open(url)),
                         daemon=True).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已退出")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    serve()
