# -*- coding: utf-8 -*-
"""本机配置（登录态持久化）测试。"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import _iso  # noqa: F401  (隔离 history/config，退出自动清理)

sys.stdout.reconfigure(encoding="utf-8")

from app import config, resolver  # noqa: E402

fails = []

def check(label, cond, detail=""):
    print("  %s %-36s %s" % ("✓" if cond else "✗", label, detail))
    if not cond:
        fails.append(label)

def acl_is_private(path):
    """Windows: ACL 里不应再出现 Everyone / BUILTIN\\Users 的完全控制。"""
    if os.name != "nt":
        m = os.stat(path).st_mode
        return not (m & 0o077)
    try:
        out = subprocess.run(["icacls", path], capture_output=True, text=True,
                             errors="ignore", timeout=15).stdout
    except Exception:
        return False
    lowered = out.lower()
    for bad in ("everyone", "authenticated users", "builtin\\users", "users:"):
        if bad in lowered:
            return False
    return True

p = config.path()
backup = open(p, "rb").read() if os.path.exists(p) else None

try:
    print("配置文件:", p)
    if os.path.exists(p):
        os.remove(p)
    config.load(force=True)
    check("默认无 cookie", config.get("yuanbao_cookie") == "")

    config.set_value("yuanbao_cookie", "hy_user=TEST; hy_token=ABC")
    check("写入后可读回", config.get("yuanbao_cookie") == "hy_user=TEST; hy_token=ABC")
    check("文件已创建", os.path.exists(p))
    check("权限已收紧（非全员可读）", acl_is_private(p))

    config._CACHE = None
    check("模拟重启后仍在", config.get("yuanbao_cookie").endswith("ABC"))
    check("resolver 能回退读取", resolver._cookie_from_env().endswith("ABC"))
    check("引擎默认值存在", config.get("engine") == "paraformer")

    # 保存其它键不应丢掉 cookie
    config.set_value("language", "auto")
    check("保存其它键不丢 cookie", config.get("yuanbao_cookie").endswith("ABC"))

    # 回归：_harden() 早期只给了 (R,W)，而 save() 是「写临时文件再改名覆盖」，
    # 改名需要目标文件的删除权限 -> 权限收紧后第二次保存就开始全部失败。
    print()
    print("== 权限收紧后还能继续保存（回归）==")
    ok_saves = 0
    for v in ("paraformer", "sensevoice", "whisper", "paraformer", "paraformer"):
        try:
            config.set_value("engine", v)
            ok_saves += 1
        except Exception as e:
            print("     保存失败:", e)
    check("连续保存 5 次都成功", ok_saves == 5, "%d/5" % ok_saves)
    check("最后一次的值读得回来", config.get("engine") == "paraformer")
    check("权限依然收紧", acl_is_private(p))

    config.set_value("yuanbao_cookie", "")
    check("清空后回退为空", resolver._cookie_from_env() == "")
finally:
    if backup is not None:
        open(p, "wb").write(backup)
    elif os.path.exists(p):
        os.remove(p)
    config.load(force=True)

print()
print("PASS" if not fails else "FAIL: %s" % fails)
sys.exit(1 if fails else 0)
