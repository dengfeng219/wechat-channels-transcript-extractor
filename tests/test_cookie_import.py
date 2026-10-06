# -*- coding: utf-8 -*-
"""Cookie 导入格式解析测试。"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.stdout.reconfigure(encoding="utf-8")

from app.cookie_import import extract_cookie  # noqa: E402

CASES = [
    ("原始 Cookie 串", "hy_user=abc123; hy_token=xyz789; hy_source=web",
     "hy_user=abc123; hy_token=xyz789; hy_source=web"),

    ("请求头片段", "Accept: */*\nCookie: hy_user=abc123; hy_token=xyz789\nOrigin: https://yuanbao.tencent.com",
     "hy_user=abc123; hy_token=xyz789"),

    ("Copy as cURL (bash)",
     "curl 'https://yuanbao.tencent.com/api/getuserinfo' \\\n"
     "  -H 'accept: application/json, text/plain, */*' \\\n"
     "  -H 'cookie: hy_user=abc123; hy_token=xyz789; hy_source=web' \\\n"
     "  -H 'user-agent: Mozilla/5.0'",
     "hy_user=abc123; hy_token=xyz789; hy_source=web"),

    ("Copy as cURL 双引号 + -b",
     'curl "https://yuanbao.tencent.com/api/x" -b "hy_user=abc123; hy_token=xyz789"',
     "hy_user=abc123; hy_token=xyz789"),

    ("Cookie 插件 JSON 数组",
     '[{"name":"hy_user","value":"abc123","domain":".tencent.com"},'
     '{"name":"hy_token","value":"xyz789","domain":".tencent.com"}]',
     "hy_user=abc123; hy_token=xyz789"),

    ("JSON 对象", '{"hy_user":"abc123","hy_token":"xyz789"}',
     "hy_user=abc123; hy_token=xyz789"),

    ("去重", "hy_user=a; hy_user=b; hy_token=c", "hy_user=a; hy_token=c"),

    ("空输入", "", ""),
    ("无 Cookie 的 cURL", "curl 'https://example.com' -H 'accept: */*'", ""),
]

def main():
    bad = 0
    for name, raw, want in CASES:
        got = extract_cookie(raw)
        ok = got == want
        if not ok:
            bad += 1
        print("  %s %-22s -> %s" % ("✓" if ok else "✗", name, got or "(空)"))
        if not ok:
            print("      期望: %s" % (want or "(空)"))
    print()
    print("PASS" if bad == 0 else "FAIL: %d 项不符" % bad)
    return 0 if bad == 0 else 1

if __name__ == "__main__":
    sys.exit(main())
