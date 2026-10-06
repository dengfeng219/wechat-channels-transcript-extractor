# -*- coding: utf-8 -*-
"""一键跑完所有测试。"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.stdout.reconfigure(encoding="utf-8")

# 注意：check_ui.py 需要真实浏览器，比较慢且偶发卡住，不放进常规套件；
# 需要时单独跑： python tests/check_ui.py
TESTS = [
    ("解密正确性", "test_decrypt.py"),
    ("公开通道(实时)", "test_public_channel.py"),
    ("登录态持久化", "test_config.py"),
    ("全链路(模拟登录)", "test_full_with_login.py"),
    ("录制系统声音", "test_loopback.py"),
    ("录制用户流程", "test_record_flow.py"),
    ("批量与历史", "test_batch_history.py"),
    ("目录命名规则", "test_naming.py"),
    ("文案校对", "test_proofread.py"),
    ("解析器逻辑", "test_resolver_logic.py"),
    ("Cookie 导入", "test_cookie_import.py"),
    ("解析与接口", "test_server.py"),
    ("接口冒烟", "smoke_api.py"),
    ("端到端转写", "test_e2e.py"),
    ("Web 全流程", "test_web_flow.py"),
]

results = []
for name, script in TESTS:
    print("=" * 62)
    print("  %s  (%s)" % (name, script))
    print("=" * 62)
    p = subprocess.run([sys.executable, os.path.join(HERE, script)],
                       cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    tail = [l for l in (p.stdout or "").splitlines()
            if l.strip() and not any(x in l for x in
            ("INFO", "DEBUG", "WARNING", "ffmpeg", "torchaudio", "apt install",
             "brew install", "it/s]", "s/it]", "model.pt:", "Prefix dict", "jieba"))]
    print("\n".join(tail[-12:]))
    ok = p.returncode == 0
    results.append((name, ok))

print()
print("=" * 62)
for name, ok in results:
    print("  %s  %s" % ("通过" if ok else "失败", name))
print("=" * 62)
bad = [n for n, ok in results if not ok]
print("全部通过 ✓" if not bad else "失败项: %s" % bad)
sys.exit(1 if bad else 0)
