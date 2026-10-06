# -*- coding: utf-8 -*-
"""极简 HTTP 封装：优先 requests，缺失时回退到标准库。"""
import json
import ssl
import urllib.error
import urllib.request

try:
    import requests
    _HAVE_REQUESTS = True
except Exception:
    _HAVE_REQUESTS = False


class HttpError(RuntimeError):
    def __init__(self, status, body, url=""):
        self.status = status
        self.body = body
        self.url = url
        super().__init__("HTTP %s %s" % (status, (body or "")[:200]))


def request(method, url, headers=None, json_body=None, data=None,
            timeout=30, allow_redirects=True):
    """返回 (status, text)。非 2xx 抛 HttpError。"""
    headers = dict(headers or {})
    body = data
    if json_body is not None:
        body = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
        headers.setdefault("Content-Type", "application/json")

    if _HAVE_REQUESTS:
        r = requests.request(method, url, headers=headers, data=body,
                             timeout=timeout, allow_redirects=allow_redirects)
        if r.status_code >= 400:
            raise HttpError(r.status_code, r.text, url)
        return r.status_code, r.text

    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            raw = resp.read()
            return resp.status, raw.decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        raise HttpError(e.code, e.read().decode("utf-8", "replace"), url) from None
    except urllib.error.URLError as e:
        raise RuntimeError("网络请求失败: %s" % (e.reason,)) from None


def request_json(method, url, **kw):
    status, text = request(method, url, **kw)
    try:
        return status, json.loads(text)
    except Exception:
        raise RuntimeError("接口返回的不是 JSON: %s" % text[:200])
