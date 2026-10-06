# -*- coding: utf-8 -*-
"""视频号文案提取器 —— 程序入口（启动本地图形界面）。"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.server import serve  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="视频号文案提取器")
    ap.add_argument("--port", type=int, default=8765, help="服务端口，默认 8765")
    ap.add_argument("--host", default="127.0.0.1", help="监听地址，默认仅本机")
    ap.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    args = ap.parse_args()
    serve(host=args.host, port=args.port, open_browser=not args.no_browser)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
