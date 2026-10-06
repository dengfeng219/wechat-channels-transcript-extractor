# -*- coding: utf-8 -*-
"""验证「一键获取登录态」的底层机制：启动浏览器 + 通过 CDP 读取 Cookie。"""
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8")

from app import browser_login as bl  # noqa: E402

def main():
    exe = bl.find_browser()
    print("浏览器:", exe or "未找到")
    if not exe:
        return 1

    os.makedirs(bl.PROFILE_DIR, exist_ok=True)
    print("配置目录:", bl.PROFILE_DIR)
    print("调试端口:", bl.DEBUG_PORT)

    proc = subprocess.Popen([
        exe,
        "--remote-debugging-port=%d" % bl.DEBUG_PORT,
        "--user-data-dir=%s" % bl.PROFILE_DIR,
        "--no-first-run", "--no-default-browser-check",
        "https://yuanbao.tencent.com/chat/",
    ])
    print("已启动浏览器，PID", proc.pid)

    try:
        ws = bl._wait_debugger(40)
        print("DevTools 就绪:", bool(ws))
        assert ws, "调试端口未就绪"
        print("  WS:", ws[:70], "...")

        cookies = bl._read_cookies(ws)
        print("通过 CDP 读到 Cookie 总数:", len(cookies))
        domains = sorted({(c.get("domain") or "") for c in cookies})
        print("  域名:", domains[:10] or "(尚未登录，暂无 Cookie —— 符合预期)")

        header = bl._cookie_header(cookies)
        print("  腾讯域 Cookie 头:", header[:60] if header else "(空 —— 未登录，符合预期)")

        # 读取机制本身可用即算通过
        print()
        print("PASS：CDP 通道可用，扫码登录后即可取到完整 Cookie（含 HttpOnly）")
        return 0
    except Exception as e:
        import traceback
        traceback.print_exc()
        print("FAIL:", e)
        return 1
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=6)
        except Exception:
            proc.kill()
        print("浏览器已关闭，调试端口已释放")
        # 清理测试用的配置目录，避免占用空间
        import shutil
        shutil.rmtree(bl.PROFILE_DIR, ignore_errors=True)

if __name__ == "__main__":
    sys.exit(main())
