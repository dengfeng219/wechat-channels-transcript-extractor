# -*- coding: utf-8 -*-
"""
命令行入口。

用法示例：
  python -m app.cli --url "https://weixin.qq.com/sph/xxxx" --cookie "hy_user=..."
  python -m app.cli --file "D:\\video.mp4"
  python -m app.cli --direct "https://finder.video.qq.com/..." --key 2136343393
  python -m app.cli --check
"""
import argparse
import os
import sys

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.asr import check_env          # noqa: E402
from app.pipeline import process       # noqa: E402
from app.resolver import check_login   # noqa: E402


MEDIA_EXT = {".mp4", ".mov", ".mkv", ".avi", ".flv", ".wmv", ".webm", ".m4v",
             ".mp3", ".m4a", ".wav", ".aac", ".flac", ".ogg", ".wma"}


def run_batch(args):
    """批量处理目录下的所有音视频文件。"""
    root = os.path.abspath(args.dir)
    if not os.path.isdir(root):
        print("目录不存在：%s" % root, file=sys.stderr)
        return 1
    files = [os.path.join(root, f) for f in sorted(os.listdir(root))
             if os.path.splitext(f)[1].lower() in MEDIA_EXT]
    if not files:
        print("目录中没有找到音视频文件：%s" % root, file=sys.stderr)
        return 1

    print("共 %d 个文件待处理\n" % len(files))
    ok = fail = 0
    for i, f in enumerate(files, 1):
        print("=" * 60)
        print("[%d/%d] %s" % (i, len(files), os.path.basename(f)))
        print("=" * 60)
        req = {"source": "file", "path": f, "decode_key": args.key,
               "engine": args.engine, "language": args.language,
               "keep_video": not args.no_video}
        if args.outdir:
            req["outdir"] = args.outdir
        try:
            r = process(req)
            print("  ✓ %d 字 -> %s" % (r["stats"]["chars"], r["files"]["txt"]))
            ok += 1
        except Exception as e:
            print("  ✗ 失败：%s: %s" % (type(e).__name__, e), file=sys.stderr)
            fail += 1
    print("\n全部完成：成功 %d，失败 %d" % (ok, fail))
    return 0 if fail == 0 else 1


def main(argv=None):
    ap = argparse.ArgumentParser(prog="视频号文案提取器",
                                 description="提取微信视频号视频的文案（本地语音识别）")
    src = ap.add_argument_group("输入（三选一）")
    src.add_argument("--url", help="视频号分享链接 https://weixin.qq.com/sph/xxxx")
    src.add_argument("--file", help="本地视频/音频文件路径")
    src.add_argument("--direct", help="视频直链（finder.video.qq.com）")
    src.add_argument("--dir", help="批量处理一个目录下的所有音视频文件")

    ap.add_argument("--key", "--decode-key", dest="key", help="解密密钥 decode_key")
    ap.add_argument("--cookie", help="腾讯元宝 Cookie（解析分享链接用）")
    ap.add_argument("--engine", default="paraformer",
                    choices=["paraformer", "sensevoice", "whisper"], help="识别引擎")
    ap.add_argument("--language", default="zh", help="语言，默认 zh，可选 auto/en")
    ap.add_argument("-o", "--outdir", help="输出根目录")
    ap.add_argument("--no-video", action="store_true", help="不保留解密后的视频文件")
    ap.add_argument("--check", action="store_true", help="检查运行环境后退出")
    args = ap.parse_args(argv)

    if args.check:
        env = check_env()
        print("PyTorch      :", env["torch"])
        print("CUDA 可用    :", env["cuda"], env["gpu"] or "")
        print("FunASR       :", env["funasr"])
        print("faster-whisper:", env["faster_whisper"])
        print("PyAV         :", env["av"])
        if args.cookie:
            ok, msg = check_login(args.cookie)
            print("元宝登录态   :", "有效" if ok else "无效", "-", msg)
        return 0

    if args.dir:
        return run_batch(args)

    if args.url:
        req = {"source": "link", "url": args.url, "cookie": args.cookie}
    elif args.direct:
        req = {"source": "direct", "url": args.direct, "decode_key": args.key}
    elif args.file:
        req = {"source": "file", "path": args.file, "decode_key": args.key}
    else:
        ap.print_help()
        return 2

    req.update(engine=args.engine, language=args.language,
               keep_video=not args.no_video)
    if args.outdir:
        req["outdir"] = args.outdir

    def on_progress(info):
        sys.stdout.write("\r[%5.1f%%] %s  %s          "
                         % (info.get("percent", 0), info.get("stage", ""),
                            info.get("message", "")[:60]))
        sys.stdout.flush()

    try:
        r = process(req, on_progress=on_progress)
    except Exception as e:
        sys.stdout.write("\n")
        print("失败：%s: %s" % (type(e).__name__, e), file=sys.stderr)
        return 1

    print("\n" + "=" * 60)
    print("文案（%d 字，用时 %.1f 秒）:" % (r["stats"]["chars"], r["elapsed"]))
    print("=" * 60)
    for p in r["paragraphs"]:
        print(p["text"])
        print()
    print("=" * 60)
    for k, v in r["files"].items():
        print("%-6s %s" % (k, v))
    return 0


if __name__ == "__main__":
    sys.exit(main())
