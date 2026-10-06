# -*- coding: utf-8 -*-
"""
文案校对，两道工序：

  1) 固定替换表（离线、必跑）—— 处理短剧里反复出现的套话和同音字。
  2) LLM 校对（可选、需要填 API Key）—— 用上下文改掉识别不出来的同音字。
     识别引擎是逐音判断，看不出上下文；「就算这里了，点个恨通」这种
     只有懂上下文才改得对，所以这一步效果最明显。

LLM 走 OpenAI 兼容接口，默认 DeepSeek。
"""
import os
import re

__all__ = ["apply_rules", "proofread_with_llm", "DEFAULT_RULES", "has_llm", "invalidate_cache"]

# 短剧高频套话 + 常见同音误识（左：识别结果，右：正确写法）
DEFAULT_RULES = [
    ("就算这里了，点个恨通", "看到这里了，点个赞吧"),
    ("就算这里了，点个赞吧", "看到这里了，点个赞吧"),
    ("看到这里了点个恨通", "看到这里了，点个赞吧"),
    ("点个恨通", "点个赞吧"),
    ("点个赞吧吧", "点个赞吧"),
    ("一花去梅韵", "一花去霉运"),
    ("去梅韵", "去霉运"),
    ("老愿皆承", "所愿皆成"),
    ("愿意皆成", "所愿皆成"),
    ("留不接", "留不住"),
    ("留不注", "留不住"),
    ("莫入", "没入"),
    ("传送他的善举", "传颂他的善举"),
    ("天道成罚", "天道惩罚"),
    ("血液救龙", "舍血救龙"),
    ("积恶扬善", "积德扬善"),
    ("造福相邻", "造福乡邻"),
    ("安享离世", "安然离世"),
]

_RULE_CACHE = [None]


def _rules():
    """内置规则 + 用户在 config.json 里追加的规则（用户的优先）。"""
    if _RULE_CACHE[0] is not None:
        return _RULE_CACHE[0]
    rules = list(DEFAULT_RULES)
    try:
        from . import config
        extra = config.get("proofread_rules") or []
        if isinstance(extra, dict):
            extra = list(extra.items())
        for item in extra:
            if isinstance(item, (list, tuple)) and len(item) == 2:
                rules.append((str(item[0]), str(item[1])))
    except Exception:
        pass
    rules.sort(key=lambda kv: -len(kv[0]))     # 长的先替换
    _RULE_CACHE[0] = rules
    return rules


def invalidate_cache():
    _RULE_CACHE[0] = None


def apply_rules(text, log=None):
    """应用固定替换表，返回 (新文本, 命中列表)。"""
    if not text:
        return text, []
    hits = []
    out = text
    for bad, good in _rules():
        if bad and bad != good and bad in out:
            n = out.count(bad)
            out = out.replace(bad, good)
            hits.append((bad, good, n))
    if hits and log:
        log("[校对] 固定替换命中 %d 处：%s"
            % (sum(h[2] for h in hits),
               "，".join("%s→%s" % (b, g) for b, g, _ in hits[:6])))
    return out, hits


def has_llm():
    try:
        from . import config
        return bool((config.get("llm_api_key") or "").strip())
    except Exception:
        return False


PROMPT = ("你是中文短剧文案的校对员。下面是一段语音识别（ASR）生成的文案，"
          "里面会有同音字、近音字错误，以及人名地名被听错的情况。\n\n"
          "要求：\n"
          "1. 只修正明显的识别错误（同音字、近音字、错别字），保持原意、原句式和原长度；\n"
          "2. 不要改写、润色、扩写，不要增删句子，不要改变语气；\n"
          "3. 短剧常见的固定套话要写成正确形式（例如：看到这里了，点个赞吧 / "
          "左下角免费看全集 / 未完待续）；\n"
          "4. 直接输出校对后的完整文案，不要任何解释、不要加引号或标题。\n\n"
          "原文：\n%s")


def proofread_with_llm(text, log=None, timeout=180):
    """
    调 LLM 做上下文校对。没配 API Key 就原样返回。
    返回 (新文本, 说明)。
    """
    if not text or not text.strip():
        return text, "空文本"
    try:
        from . import config
    except Exception:
        return text, "读取配置失败"

    key = (config.get("llm_api_key") or "").strip()
    if not key:
        return text, "未配置 API Key，跳过 LLM 校对"

    base = (config.get("llm_base_url") or "https://api.deepseek.com").rstrip("/")
    model = (config.get("llm_model") or "deepseek-chat").strip()
    url = base + "/chat/completions"

    payload = {"model": model,
               "messages": [{"role": "user", "content": PROMPT % text}],
               "temperature": 0, "stream": False}
    headers = {"Authorization": "Bearer " + key, "Content-Type": "application/json"}

    try:
        from .http import request_json
        _, data = request_json("POST", url, headers=headers, json_body=payload,
                               timeout=timeout)
    except Exception as e:
        msg = str(e)
        if "401" in msg:
            return text, "API Key 无效（401）"
        if "402" in msg or "Insufficient" in msg:
            return text, "账户余额不足"
        return text, "请求失败：%s" % msg[:120]

    try:
        out = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
    except Exception:
        out = ""
    out = (out or "").strip()
    if not out:
        return text, "模型没有返回内容"

    # 保险：模型抽风时（输出解释、长度暴走）就不用它的结果
    if len(out) > len(text) * 1.8 + 80:
        return text, "返回长度异常，已忽略"
    fence = chr(96) * 3
    if out.startswith(fence):
        out = out.strip(chr(96)).strip()
        if out.lower().startswith("text"):
            out = out[4:].strip()

    changed = sum(1 for a, b in zip(text, out) if a != b)
    return out, "已校对（约 %d 处改动）" % changed