# -*- coding: utf-8 -*-
"""
视频号加密视频解密。

微信视频号 CDN 上的视频文件前 128KB 被 XOR 加密，密钥流由接口返回的
decode_key 通过 ISAAC64 生成。解密后偏移 4 处应出现 MP4 的 'ftyp' 签名。
"""
import os
import struct

from .isaac64 import KEYSTREAM_SIZE, keystream, xor_decrypt

__all__ = ["KEYSTREAM_SIZE", "extract_decode_key", "looks_encrypted", "decrypt_file", "decrypt_bytes"]


def _to_uint64(v):
    """decode_key 可能是十进制字符串、数字，或 0x 十六进制字符串。"""
    if isinstance(v, int):
        return v & 0xFFFFFFFFFFFFFFFF
    s = str(v).strip()
    if not s:
        raise ValueError("decode_key 为空")
    if s.lower().startswith("0x"):
        return int(s, 16) & 0xFFFFFFFFFFFFFFFF
    return int(s, 10) & 0xFFFFFFFFFFFFFFFF


def extract_decode_key(media):
    """
    从 media 字典中提取 decode_key，兼容 TikHub 蛇形与微信原始驼峰两种命名。
    """
    for name in ("decode_key", "decodeKey", "decodekey"):
        if name in media and media[name] not in (None, ""):
            return _to_uint64(media[name])
    raise KeyError("响应中未找到 decode_key")


def looks_encrypted(data, probe=32):
    """加密文件头部不会是合法 MP4：检查偏移 4 处是否有 'ftyp'。"""
    if len(data) < 12:
        return True
    return data[4:8] != b"ftyp"


def _is_valid_mp4(data):
    if len(data) < 12:
        return False
    if data[4:8] == b"ftyp":
        return True
    # 少数文件以 'styp'/'moov' 等 box 开头，退化为检查 box 结构合理性
    box = data[4:8]
    return box in (b"styp", b"moov", b"free", b"mdat", b"wide")


def decrypt_bytes(data, key, byteorder="big", reverse=False, enc_len=KEYSTREAM_SIZE):
    """解密内存中的视频字节，返回 (解密后字节, 是否得到合法 MP4)。"""
    out = xor_decrypt(data, key, enc_len=enc_len, byteorder=byteorder, reverse=reverse)
    return out, _is_valid_mp4(out)


def _auto_variant(data, key, enc_len=KEYSTREAM_SIZE):
    """
    自动探测正确的密钥流字节序/顺序变体。
    正常情况下 'big' + 不反转 即与 Go 参考实现一致；此处保留探测逻辑
    以便微信更换实现时仍能自愈。
    """
    probe = data[:enc_len] if len(data) >= enc_len else data
    for byteorder in ("big", "little"):
        for reverse in (False, True):
            out, ok = decrypt_bytes(probe, key, byteorder=byteorder, reverse=reverse, enc_len=len(probe))
            if ok:
                return byteorder, reverse
    return "big", False


def decrypt_file(src, dst=None, key=None, media=None, verbose=True):
    """
    解密视频文件。

    src   : 加密视频路径
    dst   : 输出路径，默认 <src 去扩展名>_decrypted.mp4
    key   : decode_key（数字或字符串）
    media : 也可直接传入 media 字典，自动取 decode_key

    返回 dict: {ok, path, variant, size, already_plain}
    """
    if key is None and media is not None:
        key = extract_decode_key(media)
    if key is None:
        raise ValueError("必须提供 key 或 media")

    key = _to_uint64(key)
    if dst is None:
        base, _ = os.path.splitext(src)
        dst = base + "_decrypted.mp4"

    with open(src, "rb") as f:
        data = f.read()

    if not looks_encrypted(data):
        if verbose:
            print("[解密] 文件本身已是明文 MP4，无需解密")
        if os.path.abspath(src) != os.path.abspath(dst):
            with open(dst, "wb") as f:
                f.write(data)
        return {"ok": True, "path": dst, "variant": None, "size": len(data), "already_plain": True}

    order, rev = _auto_variant(data, key)
    out = xor_decrypt(data, key, byteorder=order, reverse=rev)
    ok = _is_valid_mp4(out)

    with open(dst, "wb") as f:
        f.write(out)

    if verbose:
        print("[解密] decode_key=%d  变体=%s/%s  输出=%s (%.1f MB)  校验=%s"
              % (key, order, "reversed" if rev else "normal", dst, len(out) / 1048576.0,
                 "通过" if ok else "失败"))

    return {"ok": ok, "path": dst, "variant": (order, rev), "size": len(out), "already_plain": False}
