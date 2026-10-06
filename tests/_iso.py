# -*- coding: utf-8 -*-
"""
测试隔离：每个测试进程在项目内建一个独立临时目录存 history/config/输出，
退出时自动删掉。

为什么不放系统临时目录：测试进程在受限环境里跑，写不了 %TEMP% 之外
（沙箱只放行工作区），会直接 PermissionError。
放项目内既一定有写权限，又保证用完即删，不会污染项目。
"""
import atexit
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# 项目内的临时根目录，每个进程一个子目录
_BASE = os.path.join(ROOT, ".test_tmp")
_DIR = os.path.join(_BASE, "p%d" % os.getpid())
os.makedirs(_DIR, exist_ok=True)


def _cleanup():
    shutil.rmtree(_DIR, ignore_errors=True)
    # 顺手把空的临时根目录也删掉
    try:
        if os.path.isdir(_BASE) and not os.listdir(_BASE):
            os.rmdir(_BASE)
    except OSError:
        pass


atexit.register(_cleanup)

# 强制覆盖（不用 setdefault），保证测的一定是隔离路径
os.environ["WXT_HISTORY_PATH"] = os.path.join(_DIR, "history.json")
os.environ["WXT_CONFIG_PATH"] = os.path.join(_DIR, "config.json")

sys.stdout.reconfigure(encoding="utf-8")

__all__ = ["_DIR", "ROOT"]
