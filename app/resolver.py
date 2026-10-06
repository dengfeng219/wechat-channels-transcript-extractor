# -*- coding: utf-8 -*-
"""
视频号分享链接解析。

微信的 get_feed_info 接口有两种调用方式：

  1) shortUri —— 公开预览通道，**不需要任何登录态**
     {"baseReq":{"generalToken":""}, "shortUri":"ARBFNO8PaW"}
     -> 标题、作者、封面、点赞数、以及 sceneInfo.dynamicExportId
     -> 但**不含视频地址**

  2) exportId + generalToken —— 完整通道
     generalToken 由腾讯元宝的解析接口下发（需要元宝登录态）；
     token 为空时服务端一律返回
     {"errMsg":{"type":2,"title":"此内容暂时无法播放"}}，
     看起来像"视频不可用"，其实是凭证没带上。

因此解析顺序为：先走公开通道确认链接有效并拿到元信息，
再走元宝通道取 generalToken 换取视频直链与 decodeKey。
"""
import json
import os
import random
import re
import time
import urllib.parse

from .http import request_json

__all__ = ["resolve", "normalize_feed", "SPH_RE", "is_share_url", "check_login",
           "NeedLogin", "FeedUnavailable"]

SPH_RE = re.compile(r"^https?://weixin\.qq\.com/sph/[A-Za-z0-9_\-]+/?$")
CHANNELS_FEED_RE = re.compile(r"^https?://channels\.weixin\.qq\.com/")

# 可通过环境变量覆盖，便于测试与自建代理
YUANBAO = os.environ.get("WXT_YUANBAO_BASE", "https://yuanbao.tencent.com")
FEED_INFO_URL = os.environ.get(
    "WXT_FEED_INFO_URL",
    "https://channels.weixin.qq.com/finder-preview/api/feed/get_feed_info")
AGENT_ID = "naQivTmsDa/cf4d0079-ed1b-4c55-a3f3-2ca1379727d1"

DESKTOP_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")


class FeedUnavailable(RuntimeError):
    """接口明确返回“不可播放”，携带原始响应便于诊断。"""

    def __init__(self, message, raw=None, export_id=""):
        self.raw = raw
        self.export_id = export_id
        super().__init__(message)


class NeedLogin(RuntimeError):
    """缺少腾讯元宝登录态。preview 里可能有公开通道拿到的元信息。"""

    def __init__(self, message, preview=None):
        self.preview = preview
        super().__init__(message)


def is_share_url(url):
    return bool(SPH_RE.match((url or "").strip()))


_SHARE_ANYWHERE = re.compile(r"https?://weixin\.qq\.com/sph/[A-Za-z0-9_\-]+")


def extract_share_urls(text):
    """
    从任意粘贴文本里提取所有视频号分享链接。
    微信「复制链接」经常把标题、话题一起复制进来，所以不能只按整串匹配。
    支持一行一个，也支持空格/换行/中英文标点分隔。
    """
    if not text:
        return []
    found = _SHARE_ANYWHERE.findall(str(text))
    out, seen = [], set()
    for u in found:
        u = u.rstrip("/")
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def _extract_short_id(url):
    """从分享链接里取出短号，例如 ARBFNO8PaW。"""
    m = re.search(r"/sph/([A-Za-z0-9_\-]+)", url or "")
    return m.group(1) if m else ""


# --------------------------------------------------------------------------
# 元宝（取 generalToken）
# --------------------------------------------------------------------------

def _cookie_from_env():
    for k in ("YUANBAO_COOKIE", "WX_SPH_COOKIE"):
        v = (os.environ.get(k) or "").strip()
        if v:
            return v
    try:  # 本机保存的登录态（界面里「一键获取」或「导入」后会自动写入）
        from . import config
        v = (config.get("yuanbao_cookie") or "").strip()
        if v:
            return v
    except Exception:
        pass
    return ""


def _yuanbao_headers(cookie, user_id=""):
    h = {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Origin": YUANBAO,
        "Referer": "%s/chat/%s" % (YUANBAO, AGENT_ID),
        "User-Agent": DESKTOP_UA,
        "X-Requested-With": "XMLHttpRequest",
        "X-Source": "web",
        "X-Platform": "mac",
        "X-AgentID": AGENT_ID,
    }
    if cookie:
        h["Cookie"] = cookie
    if user_id:
        uid = str(user_id)
        # 参考实现先取 userId 再解析；缺这两个头时接口可能返回降级结果
        h["T-UserID"] = uid
        h["X-ID"] = uid
        h["t-userid"] = uid
        h["x-id"] = uid
    return h


def _pick_user_id(data):
    d = data.get("data") if isinstance(data, dict) and isinstance(data.get("data"), dict) else data
    for k in ("userId", "userid", "user_id", "id"):
        if isinstance(d, dict) and d.get(k):
            return str(d[k])
    return ""


def check_login(cookie):
    """校验元宝登录态是否有效，返回 (ok, 说明)。"""
    if not cookie:
        return False, "未提供 Cookie"
    try:
        _, data = request_json("GET", YUANBAO + "/api/getuserinfo",
                               headers=_yuanbao_headers(cookie), timeout=20)
    except Exception as e:
        return False, "请求失败：%s" % e
    uid = _pick_user_id(data)
    if uid:
        return True, "已登录 (用户 ID %s)" % uid
    return False, "登录态无效或已过期，请重新登录腾讯元宝后复制 Cookie"


def _get_user_id(cookie):
    if not cookie:
        return ""
    try:
        _, data = request_json("GET", YUANBAO + "/api/getuserinfo",
                               headers=_yuanbao_headers(cookie), timeout=20)
    except Exception:
        return ""
    return _pick_user_id(data)


def _parse_share_url(share_url, cookie, user_id=""):
    payload = {"type": "video_channel_url", "url": share_url, "scene": 1}
    try:
        _, data = request_json("POST", YUANBAO + "/api/weixin/get_parse_result",
                               headers=_yuanbao_headers(cookie, user_id),
                               json_body=payload, timeout=30)
    except Exception as e:
        msg = str(e)
        if "401" in msg:
            raise NeedLogin(
                "腾讯元宝接口返回 401：登录态无效。\n"
                "请点击界面上的「一键获取登录态」重新扫码，或粘贴新的 Cookie。") from None
        raise RuntimeError("调用元宝解析接口失败：%s" % msg) from None

    body = data.get("data") if isinstance(data, dict) else None
    if not body:
        raise RuntimeError("元宝未返回解析结果：%s" % str(data)[:200])
    return body


# --------------------------------------------------------------------------
# 取值工具
# --------------------------------------------------------------------------

_TOKEN_KEYS = ("token", "generaltoken", "general_token", "playtoken", "play_token",
               "access_token", "accesstoken")
_EID_KEYS = ("eid", "exportid", "export_id", "wx_export_id", "wxexportid")


def _query(url):
    try:
        return urllib.parse.parse_qs(urllib.parse.urlparse(str(url)).query)
    except Exception:
        return {}


def _collect_urls(node, depth=0, prefix=""):
    out = []
    if depth > 5:
        return out
    if isinstance(node, dict):
        for k, v in node.items():
            out += _collect_urls(v, depth + 1, "%s.%s" % (prefix, k) if prefix else str(k))
    elif isinstance(node, list):
        for i, v in enumerate(node[:20]):
            out += _collect_urls(v, depth + 1, "%s[%d]" % (prefix, i))
    elif isinstance(node, str) and node.startswith("http"):
        out.append((prefix, node))
    return out


def _hunt_key(node, keys, depth=0, prefix=""):
    if depth > 6:
        return None
    if isinstance(node, dict):
        for k, v in node.items():
            if str(k).lower() in keys and isinstance(v, str) and v.strip():
                return v.strip(), ("%s.%s" % (prefix, k) if prefix else str(k))
        for k, v in node.items():
            got = _hunt_key(v, keys, depth + 1, "%s.%s" % (prefix, k) if prefix else str(k))
            if got:
                return got
    elif isinstance(node, list):
        for i, v in enumerate(node[:20]):
            got = _hunt_key(v, keys, depth + 1, "%s[%d]" % (prefix, i))
            if got:
                return got
    return None


def _hunt(payload, keys, prefer=()):
    """
    按「URL 查询参数 -> 字段名」两级顺序查找目标值，返回 (值, 来源描述)。

    prefer: 字段名关键词优先级。必须传！因为元宝返回里 cover_url 和 playable_url
            都带一个叫 token 的参数——前者是封面图的 CDN token，后者才是 generalToken。
    """
    urls = _collect_urls(payload)
    if prefer:
        def rank(item):
            name = item[0].lower()
            for i, kw in enumerate(prefer):
                if kw in name:
                    return i
            return len(prefer)
        urls = sorted(urls, key=rank)

    for name, url in urls:
        qs = _query(url)
        for real_key, vals in qs.items():
            if real_key.lower() in keys and vals and vals[0].strip():
                return vals[0].strip(), "%s 的 %s 参数" % (name, real_key)
    got = _hunt_key(payload, keys)
    if got:
        return got[0], "字段 %s" % got[1]
    return "", ""


def _first(d, *names, **kw):
    default = kw.get("default")
    for n in names:
        if isinstance(d, dict) and d.get(n) not in (None, ""):
            return d[n]
    return default


def _find_media_container(node, depth=0):
    if depth > 8 or not isinstance(node, (dict, list)):
        return None
    if isinstance(node, list):
        for item in node[:20]:
            got = _find_media_container(item, depth + 1)
            if got:
                return got
        return None
    media = node.get("media")
    if isinstance(media, list) and media:
        return node
    for key in ("objectDesc", "object_desc"):
        od = node.get(key)
        if isinstance(od, dict) and isinstance(od.get("media"), list) and od["media"]:
            return od
    for key in ("data", "feedInfo", "feed_info", "objectDesc", "object_desc", "feed", "info"):
        if key in node:
            got = _find_media_container(node[key], depth + 1)
            if got:
                return got
    for value in node.values():
        got = _find_media_container(value, depth + 1)
        if got:
            return got
    return None


def _pick_media_list(feed):
    """兼容多种响应结构，最后一个兜底会递归查找任何含非空 media 的节点。"""
    for path in (("data", "feedInfo", "objectDesc"),
                 ("data", "feedInfo", "objectDesc", "media"),
                 ("data", "objectDesc"),
                 ("data", "object_desc"),
                 ("feedInfo", "objectDesc"),
                 ("objectDesc",),
                 ("object_desc",)):
        cur = feed
        ok = True
        for p in path:
            if isinstance(cur, dict) and p in cur:
                cur = cur[p]
            else:
                ok = False
                break
        if ok and isinstance(cur, dict) and isinstance(cur.get("media"), list):
            return cur
        if ok and isinstance(cur, list):
            return {"media": cur}
    return _find_media_container(feed)


def _video_url_from(node):
    """
    新版 feedInfo 不再返回 media 数组，而是直接给 videoUrl /
    h264VideoInfo.videoUrl / h265VideoInfo.videoUrl，这里统一取出来。
    """
    if not isinstance(node, dict):
        return ""
    for key in ("videoUrl", "video_url", "playUrl", "play_url"):
        v = node.get(key)
        if isinstance(v, str) and v.startswith("http"):
            return v
    for key in ("h264VideoInfo", "h265VideoInfo", "h264_video_info",
                "h265_video_info", "videoInfo", "video_info"):
        sub = node.get(key)
        if isinstance(sub, dict):
            for k2 in ("videoUrl", "video_url"):
                v = sub.get(k2)
                if isinstance(v, str) and v.startswith("http"):
                    return v
    return ""


def _feed_info_node(feed):
    """定位真正承载视频信息的那个节点。"""
    data = feed.get("data") if isinstance(feed.get("data"), dict) else feed
    for key in ("feedInfo", "feed_info", "objectDesc", "object_desc"):
        node = data.get(key) if isinstance(data, dict) else None
        if isinstance(node, dict) and (_video_url_from(node) or node.get("media")):
            return node
    return None


def _has_media(data):
    """只要拿到 media 数组或 videoUrl，就算有视频。"""
    try:
        desc = _pick_media_list(data)
    except Exception:
        desc = None
    if desc and desc.get("media"):
        return True
    node = _feed_info_node(data)
    return bool(node and _video_url_from(node))


# --------------------------------------------------------------------------
# 微信 get_feed_info
# --------------------------------------------------------------------------

def _generate_rid():
    return "%x-%s" % (int(time.time()),
                      "".join(random.choice("0123456789abcdef") for _ in range(8)))


def _feed_call(payload, short_id="", page="feed"):
    """
    调用微信 get_feed_info。payload 由调用方决定（shortUri 或 exportId）。
    page 决定 _pageUrl 与 Referer，页面自己就是这么调的。
    """
    page_url = os.environ.get("WXT_PAGE_BASE", "https://channels.weixin.qq.com") \
        + "/finder-preview/pages/%s" % page
    api = "%s?_rid=%s&_pageUrl=%s" % (FEED_INFO_URL, _generate_rid(),
                                      urllib.parse.quote(page_url, safe=""))
    referer = ("%s?id=%s" % (page_url, short_id)) if page == "sph" else page_url
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Content-Type": "application/json",
        "Origin": "https://channels.weixin.qq.com",
        "Referer": referer,
        "User-Agent": DESKTOP_UA,
    }
    _, data = request_json("POST", api, headers=headers, json_body=payload, timeout=30)
    if not isinstance(data, dict):
        raise RuntimeError("视频详情接口返回异常")
    if data.get("errCode"):
        raise RuntimeError("视频详情接口错误 %s: %s" % (data.get("errCode"), data.get("errMsg")))
    return data


def _unavailable_reason(data):
    detail = (data.get("data") or {}).get("errMsg")
    if isinstance(detail, dict) and (detail.get("title") or detail.get("content")):
        return "%s %s" % (detail.get("title", ""), detail.get("content", ""))
    return ""


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------

def resolve(share_url, cookie=None, verbose=True, log=None):
    """
    解析视频号分享链接，返回规范化后的 feed 字典。

    返回 {id, title, author, avatar, cover, duration_s, create_time, media:[...]}
    """
    def emit(msg):
        if not verbose:
            return
        if log:
            log(msg)
        else:
            print(msg)

    share_url = (share_url or "").strip()
    if not is_share_url(share_url):
        raise ValueError("不是有效的视频号分享链接（应形如 https://weixin.qq.com/sph/xxxx）")

    short_id = _extract_short_id(share_url)
    emit("[解析] 分享短号：%s" % (short_id or "(未识别)"))

    # ---------- 通道 1：公开预览接口（无需登录） ----------
    preview = None
    if short_id:
        emit("[解析] 通道 1：公开预览接口（无需登录）…")
        try:
            pub = _feed_call({"baseReq": {"generalToken": ""}, "shortUri": short_id},
                             short_id=short_id, page="sph")
            if _has_media(pub):
                emit("       ✓ 公开接口直接返回视频媒体，无需登录")
                return normalize_feed(pub)
            preview = pub
            fi = (pub.get("data") or {}).get("feedInfo") or {}
            emit("       ✓ 链接有效：%s / %s" % (fi.get("description") or "(无标题)",
                                                 (pub.get("data") or {}).get("authorInfo", {}).get("nickname") or ""))
            emit("       ✗ 预览通道不含视频地址，需要登录态换取")
        except Exception as e:
            emit("       ✗ 公开通道失败：%s" % e)

    # ---------- 通道 2：元宝登录态 ----------
    cookie = (cookie or _cookie_from_env()).strip()
    if not cookie:
        raise NeedLogin(_need_login_message(preview), preview)

    emit("[解析] 通道 2：元宝解析取 generalToken …")
    user_id = _get_user_id(cookie)
    emit("       元宝用户 ID: %s" % (user_id or "未取到（仍继续尝试）"))
    parsed = _parse_share_url(share_url, cookie, user_id)

    # 注意优先级：playable_url 里的 token 才是 generalToken，
    # cover_url 里那个同名 token 是封面图的 CDN 凭证，用错必然报“此内容暂时无法播放”。
    token, token_src = _hunt(parsed, _TOKEN_KEYS, prefer=("playable",))
    eid, eid_src = _hunt(parsed, _EID_KEYS, prefer=("playable",))
    wx_export_id = str(_first(parsed, "wx_export_id", "wxExportId", default="") or "")

    emit("       元宝返回字段：%s" % (", ".join(sorted(parsed.keys())) or "(无)"))
    for name, url in _collect_urls(parsed):
        emit("       %s 参数: %s" % (name, ", ".join(sorted(_query(url).keys())) or "(无)"))
    emit("       generalToken: %s"
         % ("已获取（来自 %s，%d 字符）" % (token_src, len(token)) if token
            else "★ 未找到 —— 这会导致“此内容暂时无法播放”"))
    emit("       exportId 来源: %s" % (eid_src or "(未找到)"))

    deid = ((preview or {}).get("data") or {}).get("sceneInfo", {}).get("dynamicExportId") \
        if preview else None

    # 依次尝试多种 payload：先 shortUri+token，再各种 exportId
    payloads = []
    if short_id:
        payloads.append(("shortUri+token",
                         {"baseReq": {"generalToken": token}, "shortUri": short_id}))
    for label, cid in (("eid", eid), ("wx_export_id", wx_export_id), ("dynamicExportId", deid)):
        if cid:
            payloads.append(("exportId(%s)" % label,
                             {"baseReq": {"generalToken": token}, "exportId": cid}))

    if not payloads:
        raise RuntimeError("元宝解析结果中缺少 exportId，链接可能已失效")

    last_error = None
    for label, payload in payloads:
        try:
            data = _feed_call(payload, short_id=short_id, page="feed")
            if _has_media(data):
                emit("       ✓ 命中：%s" % label)
                return normalize_feed(data)
            reason = _unavailable_reason(data)
            last_error = FeedUnavailable(reason or "未返回视频媒体", raw=data, export_id=label)
            emit("       ✗ %s -> %s" % (label, reason or "无媒体"))
        except FeedUnavailable as e:
            last_error = e
            emit("       ✗ %s -> %s" % (label, e))
        except Exception as e:
            last_error = e
            emit("       ✗ %s -> %s" % (label, e))

    _save_diagnostic(parsed, payloads, last_error, token_src, eid_src)
    raise RuntimeError(_failure_message(parsed, payloads, token, token_src, eid_src,
                                        last_error, preview))


def _need_login_message(preview):
    msg = ("解析视频号分享链接需要腾讯元宝登录态。\n"
           "请在界面展开「登录态设置」，点「一键获取登录态」扫码（约 20 秒，只需一次）。\n\n"
           "不想登录也可以：把视频文件拖到「本地视频 / 音频」标签页，"
           "那条路径不需要任何登录态。")
    if preview:
        fi = (preview.get("data") or {}).get("feedInfo") or {}
        ai = (preview.get("data") or {}).get("authorInfo") or {}
        if fi.get("description"):
            msg += "\n\n（已通过公开接口确认这条视频是：《%s》作者 %s，只是视频地址需要登录后才能取到）" \
                % (fi.get("description"), ai.get("nickname") or "")
    return msg


def _failure_message(parsed, payloads, token, token_src, eid_src, last_error, preview):
    keys = ""
    try:
        keys = ", ".join(sorted((getattr(last_error, "raw", None) or {}).get("data", {}).keys()))
    except Exception:
        pass
    return (
        "%s\n"
        "──────────────── 诊断信息 ────────────────\n"
        "元宝返回字段 : %s\n"
        "发现的链接   : %s\n"
        "generalToken : %s\n"
        "exportId 来源: %s\n"
        "尝试过的组合 : %s\n"
        "末次响应字段 : %s\n"
        "──────────────────────────────────────────\n"
        "完整诊断已写入输出目录下的 诊断.json。"
        % (last_error or "解析失败",
           ", ".join(sorted(parsed.keys())) or "(无)",
           "; ".join("%s(参数: %s)" % (n, ",".join(sorted(_query(u).keys())) or "无")
                     for n, u in _collect_urls(parsed)) or "(无)",
           ("已获取，来自 %s，%d 字符" % (token_src, len(token)) if token else "未找到"),
           eid_src or "(未找到)",
           " | ".join(l for l, _ in payloads) or "(无)",
           keys or "(读取失败)"))


_DIAG_DIR = [None]


def _save_diagnostic(parsed, payloads, last_error, token_src, eid_src):
    """把失败现场落盘，方便一次性定位问题（长字符串会截断）。"""
    try:
        base = _DIAG_DIR[0] or os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output")
        os.makedirs(base, exist_ok=True)
        path = os.path.join(base, "诊断.json")

        def trim(node, depth=0):
            if depth > 8:
                return "..."
            if isinstance(node, dict):
                return {k: trim(v, depth + 1) for k, v in node.items()}
            if isinstance(node, list):
                return [trim(v, depth + 1) for v in node[:10]]
            if isinstance(node, str) and len(node) > 80:
                return node[:80] + "…(%d字符)" % len(node)
            return node

        payload = {
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "yuanbao_response": trim(parsed),
            "generalToken_source": token_src,
            "exportId_source": eid_src,
            "attempts": [{"label": l, "payload": p} for l, p in payloads],
            "last_error": str(last_error),
            "last_response": trim(getattr(last_error, "raw", None)),
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def normalize_feed(feed):
    """把不同来源的响应整理成统一结构。"""
    data = feed.get("data") if isinstance(feed.get("data"), dict) else feed
    desc = _pick_media_list(feed)

    if desc is None or not desc.get("media"):
        # 新版结构：feedInfo.videoUrl / h264VideoInfo.videoUrl，没有 media 数组
        node = _feed_info_node(feed)
        if node is not None:
            desc = node
        elif isinstance(data.get("media"), list):
            desc = {"media": data["media"]}
        elif desc is None:
            raise RuntimeError("未能从响应中定位视频媒体列表")

    contact = _first(desc, "contact", default={}) or {}
    if not isinstance(contact, dict):
        contact = {}
    author_info = _first(data, "authorInfo", "author_info", default={}) or {}
    if not isinstance(author_info, dict):
        author_info = {}

    media_out = []
    for m in (desc.get("media") or []):
        if not isinstance(m, dict):
            continue
        spec = m.get("spec") or []
        sp = spec[0] if isinstance(spec, list) and spec else {}
        if not isinstance(sp, dict):
            sp = {}
        media_out.append({
            "url": _first(m, "url", "play_url", "playUrl", default=""),
            "thumb": _first(m, "thumb_url", "thumbUrl", default=""),
            "cover": (_first(m, "cover_url", "coverUrl", default="")
                      or _first(m, "thumb_url", "thumbUrl", default="")
                      or _first(desc, "coverUrl", "cover_url", default="")),
            "decode_key": _first(m, "decode_key", "decodeKey", default=""),
            "media_type": _first(m, "media_type", "mediaType", default=4),
            "file_size": _first(m, "file_size", "fileSize", default=0),
            "width": _first(m, "width", default=sp.get("width")),
            "height": _first(m, "height", default=sp.get("height")),
            "duration_ms": _first(m, "duration_ms", "durationMs",
                                  default=sp.get("duration_ms") or sp.get("durationMs")),
            "coding_format": sp.get("coding_format") or sp.get("codingFormat") or "",
            "file_format": sp.get("file_format") or sp.get("fileFormat") or "",
            "quality": sp.get("quality_score") or sp.get("qualityScore") or 0,
        })

    if not media_out:
        # 新版结构：把 videoUrl 包装成统一的 media 项。
        # 实测这类视频是明文 MP4（ftyp 就在偏移 4），因此 decode_key 为空。
        vu = _video_url_from(desc)
        if vu:
            media_out.append({
                "url": vu,
                "thumb": _first(desc, "thumbUrl", "thumb_url", default=""),
                "cover": _first(desc, "coverUrl", "cover_url", default=""),
                "decode_key": _first(desc, "decodeKey", "decode_key", default=""),
                "media_type": _first(desc, "mediaType", "media_type", default=4),
                "file_size": _first(desc, "fileSize", "file_size", default=0),
                "width": None, "height": None, "duration_ms": 0,
                "coding_format": "h264" if desc.get("h264VideoInfo") else "",
                "file_format": "", "quality": 0,
            })

    if not media_out:
        raise RuntimeError("响应中没有可用的视频媒体")

    dur_ms = media_out[0].get("duration_ms") or 0
    if not dur_ms:
        pl = _first(desc, "video_play_len", "videoPlayLen", default=0)
        dur_ms = int(pl) * 1000 if pl else 0

    return {
        "id": _first(data, "id", "object_id", "objectId", default=""),
        "title": (_first(desc, "description", "title", default="")
                  or _first(data, "description", default="")),
        "author": (_first(contact, "nickname", default="")
                   or author_info.get("nickname", "")
                   or _first(data, "nickname", default="")),
        "avatar": _first(contact, "head_url", "headUrl", default="")
                  or author_info.get("headImgUrl", ""),
        "description": _first(desc, "description", default=""),
        "cover": _first(desc, "coverUrl", "cover_url", default=""),
        "create_time": _first(data, "createtime", "create_time", default=0),
        "duration_s": (dur_ms or 0) / 1000.0,
        "media": media_out,
        "raw": feed,
    }
