#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
整理剧集文件 —— 把一部短剧下每集文件夹里的 txt / mp4 各自汇总到一个文件夹。

汇总文件夹会自动带上短剧名，方便单独拷走时一眼认得出是哪部剧：

    第14集/凤命轮回：弃婴渡世-第14集.txt  ┐
    第15集/凤命轮回：弃婴渡世-第15集.txt  ├─►  凤命轮回：弃婴渡世-文案TXT/   （全部 txt）
    第16集/凤命轮回：弃婴渡世-第16集.txt  ┘
    第14集/凤命轮回：弃婴渡世-第14集.mp4  ┐
    第15集/凤命轮回：弃婴渡世-第15集.mp4  ├─►  凤命轮回：弃婴渡世-视频MP4/  （全部 mp4）
    第16集/凤命轮回：弃婴渡世-第16集.mp4  ┘

特点：
  * 默认「复制」，原文件夹一个都不动（加 --move 才是剪切）
  * 集数按数字排序（第2集 在 第10集 前面），不会按字典序乱掉
  * 重复运行安全：已经整理过的文件会跳过，不会重复复制
  * 重名文件自动加序号，不会互相覆盖
  * 汇总完会报告哪几集缺 txt / 缺 mp4
  * 只用 Python 标准库，任何 Python 3.8+ 都能跑
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import sys
from pathlib import Path

# ────────────────────────────── 可调参数 ──────────────────────────────

# 汇总文件夹名，{剧名} 会被替换成短剧名；想改回不带剧名的，写 "文案TXT" 即可
TXT_DIRNAME = "{剧名}-文案TXT"
MP4_DIRNAME = "{剧名}-视频MP4"
# 老版本（或手工改名）留下的汇总文件夹，扫描时同样要跳过，否则会被当成源文件再收一遍
LEGACY_TXT_SUFFIX = "文案TXT"
LEGACY_MP4_SUFFIX = "视频MP4"
TXT_SUFFIX = ".txt"
MP4_SUFFIX = ".mp4"

# 集数识别：第12集 / 第12话 / 第12話 / EP12 / 第12期
EP_PATTERNS = [
    re.compile(r"第\s*(\d{1,4})\s*[集话話]"),
    re.compile(r"EP\s*(\d{1,4})", re.IGNORECASE),
    re.compile(r"第\s*(\d{1,4})\s*期"),
]

# ────────────────────────────── 小工具函数 ──────────────────────────────


def human_size(num_bytes: int) -> str:
    """把字节数变成好看的字符串。"""
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{size:.1f} TB"


def episode_number(text: str):
    """从一段文字里抠出集数，抠不到返回 None。"""
    for pattern in EP_PATTERNS:
        found = pattern.search(text)
        if found:
            return int(found.group(1))
    return None


def sort_key(name: str):
    """排序键：有集数的按集数从小到大，没集数的排在最后按名字排。"""
    number = episode_number(name)
    if number is None:
        return (1, 0, name)
    return (0, number, name)


def is_inside(child: Path, parent: Path) -> bool:
    """child 是否在 parent 里面（用来避免把自己的输出再收一遍）。"""
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


# ────────────────────────────── 扫描 ──────────────────────────────


def resolve_dirname(pattern: str, drama_name: str) -> str:
    """把汇总文件夹名里的 {剧名} / {name} 换成真正的短剧名。"""
    return pattern.replace("{剧名}", drama_name).replace("{name}", drama_name)


def is_aggregate_dir(dirname: str, resolved: tuple) -> bool:
    """
    这个文件夹是不是我们自己的汇总文件夹（要跳过，别当源文件收）。

    除了按名字精确判断，还兜住两种历史情况：
      * 老版本生成的「文案TXT」「视频MP4」（不带剧名）
      * 手工改过名的「某某剧-文案TXT」
    """
    if dirname in resolved:
        return True
    return dirname.endswith(LEGACY_TXT_SUFFIX) or dirname.endswith(LEGACY_MP4_SUFFIX)


class Found:
    """扫描结果：每个文件属于哪一集。"""

    def __init__(self):
        self.txts = []   # [(集数或None, 集标签, Path)]
        self.mp4s = []

    def add(self, episode_no, label: str, path: Path):
        if path.suffix.lower() == TXT_SUFFIX:
            self.txts.append((episode_no, label, path))
        elif path.suffix.lower() == MP4_SUFFIX:
            self.mp4s.append((episode_no, label, path))

    def sort(self):
        self.txts.sort(key=lambda item: sort_key(item[1]) + (str(item[2]),))
        self.mp4s.sort(key=lambda item: sort_key(item[1]) + (str(item[2]),))


def scan_drama(drama_dir: Path, resolved_names: tuple) -> Found:
    """
    遍历一部短剧文件夹，收集所有 txt / mp4。

    resolved_names 是这次要生成的两个汇总文件夹名；它们在扫描时会被跳过，
    这样重复运行不会把汇总结果当成源文件再收一遍。
    """
    result = Found()

    for dirpath, dirnames, filenames in os.walk(drama_dir):
        current = Path(dirpath)

        # 剪掉汇总文件夹，也剪掉明显的临时/隐藏目录
        dirnames[:] = [
            d for d in dirnames
            if not is_aggregate_dir(d, resolved_names) and not d.startswith(".")
        ]

        # 集标签：优先用「第N集」这种文件夹名，其次用文件名
        for filename in filenames:
            path = current / filename
            if path.suffix.lower() not in (TXT_SUFFIX, MP4_SUFFIX):
                continue
            try:
                if path.is_symlink() or not path.is_file():
                    continue
            except OSError:
                continue

            label = current.name if current != drama_dir else path.stem
            number = episode_number(current.name)
            if number is None:
                number = episode_number(filename)
            result.add(number, label, path)

    result.sort()
    return result


# ────────────────────────────── 复制 / 移动 ──────────────────────────────


def unique_destination(dest_dir: Path, filename: str) -> Path:
    """目标重名时自动加 _2、_3 ……"""
    candidate = dest_dir / filename
    if not candidate.exists():
        return candidate
    stem, suffix = os.path.splitext(filename)
    index = 2
    while True:
        candidate = dest_dir / f"{stem}_{index}{suffix}"
        if not candidate.exists():
            return candidate
        index += 1


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def files_equal(a: Path, b: Path) -> bool:
    """两个文件内容是否一致：先比大小，再比哈希。"""
    try:
        if a.stat().st_size != b.stat().st_size:
            return False
        if a.stat().st_size == 0:
            return True
    except OSError:
        return False
    return _sha256(a) == _sha256(b)


def find_identical_copy(dest_dir: Path, filename: str, src: Path):
    """
    目标文件夹里是否已经有这个文件的等价副本（包括 _2、_3 这类重命名版本）。
    有就返回它 —— 这样重复运行不会越堆越多。
    """
    if not dest_dir.is_dir():
        return None

    stem, suffix = os.path.splitext(filename)
    pattern = re.compile(re.escape(stem) + r"(?:_\d+)?$", re.IGNORECASE)

    try:
        src_size = src.stat().st_size
        entries = list(dest_dir.iterdir())
    except OSError:
        return None

    for candidate in entries:
        try:
            if not candidate.is_file() or candidate.suffix.lower() != suffix.lower():
                continue
            if not pattern.fullmatch(candidate.stem):
                continue
            if candidate.stat().st_size != src_size:
                continue
        except OSError:
            continue
        if files_equal(src, candidate):
            return candidate
    return None


def transfer(src: Path, dest_dir: Path, move: bool, dry_run: bool):
    """
    返回 (状态, 目标路径, 字节数)
    状态：copied / moved / skipped（已整理过）/ planned（预演）
    """
    dest = dest_dir / src.name
    size = src.stat().st_size

    # 已经整理过：内容一致就跳过，保证重复运行幂等
    if dest.exists() and files_equal(src, dest):
        return "skipped", dest, size

    # 内容相同的副本可能已经以 _2 / _3 的名字存在，也算整理过
    twin = find_identical_copy(dest_dir, src.name, src)
    if twin is not None:
        return "skipped", twin, size

    # 预演模式下不建目录、不动文件，保证真的什么都没改
    if dry_run:
        return "planned", dest, size

    dest_dir.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        dest = unique_destination(dest_dir, src.name)

    if move:
        shutil.move(str(src), str(dest))
        return "moved", dest, dest.stat().st_size

    shutil.copy2(str(src), str(dest))
    # 复制后校验大小，防止半截文件
    if dest.stat().st_size != size:
        raise IOError(f"复制后大小不一致：{dest}")
    return "copied", dest, dest.stat().st_size


def transfer_all(items, dest_dir: Path, move: bool, dry_run: bool):
    """批量搬运，返回统计。保持顺序输出，方便看进度。"""
    stats = {"copied": 0, "moved": 0, "skipped": 0, "planned": 0, "bytes": 0}
    width = max((len(label) for _, label, _ in items), default=4)

    for number, label, path in items:
        try:
            status, dest, size = transfer(path, dest_dir, move, dry_run)
        except PermissionError:
            print(f"  ✗ {label:<{width}}  {path.name}")
            print(f"      没权限写入：{dest_dir}")
            print("      请关掉正在占用该文件夹的程序（播放器 / 资源管理器预览），或换个位置再试。")
            continue
        except Exception as exc:  # 单个文件失败不影响其它
            print(f"  ✗ {label:<{width}}  {path.name}  —— 失败：{exc}")
            continue

        stats[status] += 1
        stats["bytes"] += size

        if status == "skipped":
            print(f"  · {label:<{width}}  已整理过，跳过")
        elif status == "planned":
            print(f"  → {label:<{width}}  {path.name}")
        elif status == "moved":
            print(f"  ✓ {label:<{width}}  已剪切  {path.name}")
        else:
            print(f"  ✓ {label:<{width}}  {path.name}  ({human_size(size)})")

    return stats


# ────────────────────────────── 合集（可选） ──────────────────────────────


def read_text(path: Path) -> str:
    """txt 一般是 UTF-8，遇到老文件兜底 GBK。"""
    for encoding in ("utf-8-sig", "utf-8", "gbk", "cp936"):
        try:
            return path.read_text(encoding=encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def build_merged(txt_items, dest_dir: Path, title: str, dry_run: bool) -> Path:
    """把所有 txt 按集数顺序拼成一个合集文件。"""
    dest = dest_dir / f"{title}-全{len(txt_items)}篇合集.txt"
    if dry_run:
        return dest

    dest_dir.mkdir(parents=True, exist_ok=True)

    chunks = []
    for number, label, path in txt_items:
        body = read_text(path).strip()
        chunks.append(f"{'=' * 60}\n{label}\n{'=' * 60}\n\n{body}\n")

    dest.write_text("\n\n".join(chunks), encoding="utf-8")
    return dest


# ────────────────────────────── 交互 ──────────────────────────────


def looks_like_drama(path: Path) -> bool:
    """这个文件夹像不像「一部短剧」（里面装着第N集）。"""
    if not path.is_dir():
        return False
    try:
        children = [d for d in path.iterdir() if d.is_dir() and not d.name.startswith(".")]
    except OSError:
        return False
    if any(episode_number(d.name) is not None for d in children):
        return True
    # 或者文件夹本身就叫第N集，里面直接是文件
    if episode_number(path.name) is not None:
        return any(f.suffix.lower() in (TXT_SUFFIX, MP4_SUFFIX) for f in path.iterdir() if f.is_file())
    return False


def find_dramas(output_dir: Path):
    """在 output/ 下面找出一部部短剧。"""
    dramas = []
    if not output_dir.is_dir():
        return dramas
    for child in sorted(output_dir.iterdir(), key=lambda p: sort_key(p.name)):
        if not child.is_dir() or child.name.startswith("."):
            continue
        if looks_like_drama(child):
            dramas.append(child)
        else:
            # 多一层：output/某分类/某短剧
            for grand in sorted(child.iterdir(), key=lambda p: sort_key(p.name)):
                if grand.is_dir() and looks_like_drama(grand):
                    dramas.append(grand)
    return dramas


def count_media(drama: Path):
    resolved = (
        resolve_dirname(TXT_DIRNAME, drama.name),
        resolve_dirname(MP4_DIRNAME, drama.name),
    )
    found = scan_drama(drama, resolved)
    return len(found.txts), len(found.mp4s)


def choose_drama(dramas):
    """列出候选让用户挑。"""
    print("找到这些短剧文件夹：\n")
    info = []
    for index, drama in enumerate(dramas, 1):
        txt_count, mp4_count = count_media(drama)
        info.append((drama, txt_count, mp4_count))
        print(f"  [{index}] {drama.name}   （txt {txt_count} 个 / mp4 {mp4_count} 个）")

    print("\n  输入序号整理其中一部；输入 a 整理全部；直接回车取消。")
    while True:
        try:
            answer = input("> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return []
        if answer == "":
            return []
        if answer == "a":
            return [drama for drama, _, _ in info]
        if answer.isdigit() and 1 <= int(answer) <= len(info):
            return [info[int(answer) - 1][0]]
        print("  没看懂，请输入序号或 a：")


def report_missing(txt_numbers, mp4_numbers):
    """报告缺了哪几集。"""
    lines = []
    for name, numbers in (("txt", txt_numbers), ("mp4", mp4_numbers)):
        numbers = sorted(n for n in numbers if n is not None)
        if len(numbers) < 2:
            continue
        full = set(range(min(numbers), max(numbers) + 1))
        missing = sorted(full - set(numbers))
        if missing:
            preview = "、".join(f"第{n}集" for n in missing[:12])
            more = f" 等 {len(missing)} 集" if len(missing) > 12 else ""
            lines.append(f"  ⚠ 缺 {name}：{preview}{more}")
    return lines


# ────────────────────────────── 主流程 ──────────────────────────────


def process(drama: Path, args) -> None:
    # 汇总文件夹带上短剧名，例如「凤命轮回：弃婴渡世-文案TXT」
    txt_dirname = resolve_dirname(args.txt_dir, drama.name)
    mp4_dirname = resolve_dirname(args.mp4_dir, drama.name)
    txt_dir = drama / txt_dirname
    mp4_dir = drama / mp4_dirname

    print("=" * 64)
    print(f"短剧：{drama.name}")
    print(f"位置：{drama}")
    print("=" * 64)

    found = scan_drama(drama, (txt_dirname, mp4_dirname))

    if not found.txts and not found.mp4s:
        print("\n这个文件夹里没找到 txt / mp4，什么也没做。")
        print("（如果文件在更深的子文件夹里，检查一下文件夹名是否规范）")
        return

    print(f"\n扫描到：txt {len(found.txts)} 个，mp4 {len(found.mp4s)} 个")
    print(f"动作：{'剪切（原文件会被移走）' if args.move else '复制（原文件夹保持不动）'}"
          f"{'  —— 预演，不会真的动文件' if args.dry_run else ''}")

    # ── txt ──
    if found.txts:
        print(f"\n【文案 TXT】→ {txt_dirname}\\")
        txt_stats = transfer_all(found.txts, txt_dir, args.move, args.dry_run)
    else:
        txt_stats = {"copied": 0, "moved": 0, "skipped": 0, "planned": 0, "bytes": 0}

    # ── mp4 ──
    if found.mp4s:
        print(f"\n【视频 MP4】→ {mp4_dirname}\\")
        mp4_stats = transfer_all(found.mp4s, mp4_dir, args.move, args.dry_run)
    else:
        mp4_stats = {"copied": 0, "moved": 0, "skipped": 0, "planned": 0, "bytes": 0}

    # ── 可选合集 ──
    merged = None
    if args.merge and found.txts:
        print("\n【全集合集】")
        merged = build_merged(found.txts, txt_dir, drama.name, args.dry_run)
        if args.dry_run:
            print(f"  → 会生成 {merged.name}")
        else:
            print(f"  ✓ 已生成 {merged.name}  ({human_size(merged.stat().st_size)})")

    # ── 汇总 ──
    print("\n" + "-" * 64)
    verb = "预演" if args.dry_run else ("剪切" if args.move else "复制")
    for label, stats in (("txt", txt_stats), ("mp4", mp4_stats)):
        done = stats["copied"] + stats["moved"] + stats["planned"]
        print(f"  {label:<4} {verb} {done} 个，跳过 {stats['skipped']} 个，"
              f"共 {human_size(stats['bytes'])}")

    missing_lines = report_missing(
        [n for n, _, _ in found.txts],
        [n for n, _, _ in found.mp4s],
    )
    if missing_lines:
        print("\n集数完整性检查：")
        print("\n".join(missing_lines))

    if not args.dry_run:
        print("\n完成。汇总文件夹：")
        if found.txts:
            print(f"  {txt_dir}")
        if found.mp4s:
            print(f"  {mp4_dir}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="把一部短剧下每集的 txt / mp4 汇总到两个文件夹。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "例子（双击项目根目录的「整理剧集文件.bat」最省事）：\n"
            "  整理剧集文件.bat                  # 自动列出 output/ 里的短剧让你挑\n"
            "  整理剧集文件.bat \"output\\某部剧\"  # 直接整理这一部（或把文件夹拖到 .bat 上）\n"
            "  整理剧集文件.bat --all            # 整理 output/ 里全部短剧\n"
            "  整理剧集文件.bat --move           # 用剪切代替复制\n"
            "  整理剧集文件.bat --merge          # 顺便生成按集数排好的合集 txt\n"
            "  整理剧集文件.bat --dry-run        # 只看会做什么，不动文件\n"
            "\n"
            "也可以直接用 Python 跑：\n"
            "  .venv\\Scripts\\python.exe tools\\organize_episodes.py [选项]\n"
        ),
    )
    parser.add_argument("path", nargs="?", help="短剧文件夹（也可以把文件夹拖到 .bat 上）")
    parser.add_argument("--all", action="store_true", help="整理 output/ 里全部短剧")
    parser.add_argument("--move", action="store_true", help="剪切而不是复制")
    parser.add_argument("--merge", action="store_true", help="额外生成全集合集 txt")
    parser.add_argument("--dry-run", action="store_true", help="只预演，不动文件")
    parser.add_argument("--yes", "-y", action="store_true", help="不询问，直接执行")
    parser.add_argument("--txt-dir", default=TXT_DIRNAME,
                        help=f"txt 汇总文件夹名，{{剧名}} 会换成短剧名（默认 {TXT_DIRNAME}）")
    parser.add_argument("--mp4-dir", default=MP4_DIRNAME,
                        help=f"mp4 汇总文件夹名，{{剧名}} 会换成短剧名（默认 {MP4_DIRNAME}）")
    args = parser.parse_args()

    project_dir = Path(__file__).resolve().parent.parent
    output_dir = project_dir / "output"
    if not output_dir.is_dir():
        output_dir = Path.cwd() / "output"

    # ── 决定要处理哪几部短剧 ──
    if args.path:
        target = Path(args.path).expanduser()
        if not target.is_absolute():
            target = (Path.cwd() / target).resolve()
        if not target.is_dir():
            print(f"找不到文件夹：{target}")
            return 1

        if looks_like_drama(target):
            dramas = [target]
        else:
            # 传进来的是上一级目录（比如 output/），那就找里面的短剧
            dramas = [d for d in find_dramas(target)]
            if not dramas:
                # 也可能是单集文件夹，直接把它的上级当短剧
                dramas = [target]
    elif args.all:
        dramas = find_dramas(output_dir)
    else:
        dramas = find_dramas(output_dir)
        if not dramas:
            print(f"在 {output_dir} 里没找到任何短剧文件夹。")
            print("可以把短剧文件夹直接拖到「整理剧集文件.bat」上运行。")
            return 1
        if len(dramas) > 1 and not args.yes:
            dramas = choose_drama(dramas)
            if not dramas:
                print("已取消。")
                return 0

    if not dramas:
        print("没有要处理的短剧。")
        return 0

    # ── 执行 ──
    for drama in dramas:
        process(drama, args)
        if len(dramas) > 1:
            print()

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n已中断。")
        sys.exit(130)
