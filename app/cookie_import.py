# -*- coding: utf-8 -*-
"""
从多种粘贴格式中提取 Cookie 字符串。

支持：
  1. 原始 Cookie 字符串       hy_user=xxx; hy_token=yyy
  2. 完整请求头片段           Cookie: hy_user=xxx; ...
  3. 浏览器「Copy as cURL」   curl 'https://...' -H 'cookie: a=1; b=2'
  4. Cookie 插件导出的 JSON   [{"name":"hy_user","value":"xxx","domain":".tencent.com"}]
  5. JSON 对象               {"hy_user":"xxx","hy_token":"yyy"}
"""
import json
import re

__all__ = ["extract_cookie", "looks_like_cookie"]

# 常见 Cookie 名（用于判断一段文本是否已经是 Cookie 串）
_COOKIEISH = re.compile(r"^[\w.\-]+=[^;\s]*", re.UNICODE)
_KV_PAIR = re.compile(r"([\w.\-]+)=([^;\s]*)")


def _clean(value):
    value = (value or "").strip()
    # 命令行的续行符与转义
    value = value.replace("\\\r\n", " ").replace("\\\n", " ")
    value = value.replace("\r", " ").replace("\n", " ")
    return value.strip().strip("'\"").strip()


def _normalize_pairs(pairs):
    """按出现顺序去重，保留第一个值。"""
    seen, out = set(), []
    for name, val in pairs:
        name = name.strip()
        if not name or name in seen:
            continue
        # 过滤掉明显不是 Cookie 的键
        if name.lower() in ("cookie",):
            continue
        seen.add(name)
        out.append("%s=%s" % (name, val))
    return "; ".join(out)


def _from_curl(text):
    """从 cURL 命令里取 cookie 头。"""
    # -H 'cookie: ...'  /  --header "cookie: ..."  /  -b '...'
    patterns = [
        r"(?:-H|--header)\s+(['\"])\s*cookie\s*:\s*(.*?)\1",
        r"(?:-b|--cookie)\s+(['\"])(.*?)\1",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE | re.DOTALL)
        if m:
            raw = _clean(m.group(2))
            # 去掉 cURL 的 \' 转义
            raw = raw.replace("\\'", "'")
            if raw:
                return raw
    return ""


def _from_header_block(text):
    """从粘贴的请求头里取 Cookie: 那一行（可能跨行）。"""
    m = re.search(r"^\s*cookie\s*:\s*(.+?)(?=\n[\w\-]+\s*:|\Z)",
                  text, re.IGNORECASE | re.MULTILINE | re.DOTALL)
    if m:
        return _clean(m.group(1))
    return ""


def _from_json(text):
    """Cookie 插件导出的 JSON，或简单的键值对象。"""
    try:
        data = json.loads(text)
    except Exception:
        return ""
    if isinstance(data, list):
        pairs = []
        for item in data:
            if isinstance(item, dict) and item.get("name"):
                pairs.append((str(item["name"]), str(item.get("value", ""))))
        return _normalize_pairs(pairs)
    if isinstance(data, dict):
        for key in ("cookies", "cookie"):
            if key in data:
                return _from_json(json.dumps(data[key]))
        pairs = [(str(k), str(v)) for k, v in data.items()
                 if isinstance(v, (str, int, float))]
        if pairs:
            return _normalize_pairs(pairs)
    return ""


def _from_raw(text):
    """直接就是 a=1; b=2 形式的 Cookie 串。"""
    text = _clean(text)
    if not text or "=" not in text:
        return ""
    pairs = _KV_PAIR.findall(text)
    if not pairs:
        return ""
    return _normalize_pairs(pairs)


def looks_like_cookie(text):
    """粗略判断文本是否已是 Cookie 串。"""
    t = (text or "").strip()
    return bool(t) and "=" in t and not t.startswith("curl") and "\n" not in t


def extract_cookie(text):
    """
    尝试各种格式，返回 Cookie 字符串；失败返回空串。
    """
    if not text or not text.strip():
        return ""
    text = text.strip()

    # JSON 优先（结构明确，不会误判）
    if text[0] in "[{":
        got = _from_json(text)
        if got:
            return got

    # cURL（复制为 cURL 时会带 curl 或 -H 参数）
    if "curl" in text.lower() or re.search(r"(^|\s)-{1,2}(H|header|b|cookie)\s", text):
        got = _from_curl(text)
        if got:
            return got

    # 请求头块
    got = _from_header_block(text)
    if got:
        return got

    # 纯 Cookie 串
    return _from_raw(text)
