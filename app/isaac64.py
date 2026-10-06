# -*- coding: utf-8 -*-
"""
微信视频号视频解密算法 —— ISAAC64 伪随机数生成器 (Python 移植)

来源与依据：
  - Go 参考实现: ltaoo/wx_channels_download  pkg/scraper/wxchannels/decrypt.go
                 (其注释声明移植自 Hanson/WechatSphDecrypt)
  - 微信客户端使用 ISAAC64 对视频文件 **前 128KB(131072 字节)** 做 XOR 加密，
    密钥流由接口返回的 decode_key 作为种子生成。

本文件为逐行等价移植，所有 uint64 运算显式掩码以保证与 Go/C 的无符号回绕一致。
"""

MASK64 = (1 << 64) - 1
GOLDEN = 0x9E3779B97F4A7C13

# 视频号加密覆盖的字节数（密钥流长度）
KEYSTREAM_SIZE = 131072


def _mix(s):
    """Go 的 mix(*a..*h)：对 8 个状态字做一轮可逆混合，结果写回 s。"""
    a, b, c, d, e, f, g, h = s
    a = (a - e) & MASK64
    f ^= (h >> 9)
    h = (h + a) & MASK64
    b = (b - f) & MASK64
    g ^= (a << 9) & MASK64
    a = (a + b) & MASK64
    c = (c - g) & MASK64
    h ^= (b >> 23)
    b = (b + c) & MASK64
    d = (d - h) & MASK64
    a ^= (c << 15) & MASK64
    c = (c + d) & MASK64
    e = (e - a) & MASK64
    b ^= (d >> 14)
    d = (d + e) & MASK64
    f = (f - b) & MASK64
    c ^= (e << 20) & MASK64
    e = (e + f) & MASK64
    g = (g - c) & MASK64
    d ^= (f >> 17)
    f = (f + g) & MASK64
    h = (h - d) & MASK64
    e ^= (g << 14) & MASK64
    g = (g + h) & MASK64
    s[0], s[1], s[2], s[3], s[4], s[5], s[6], s[7] = a, b, c, d, e, f, g, h


class RandCtx64(object):
    """ISAAC64 上下文，等价于 Go 的 RandCtx64。"""

    __slots__ = ("RandCnt", "Seed", "MM", "AA", "BB", "CC")

    def __init__(self, enc_key):
        self.RandCnt = 255
        self.Seed = [0] * 256
        self.MM = [0] * 256
        self.AA = 0
        self.BB = 0
        self.CC = 0
        self._init(enc_key & MASK64)

    def _init(self, enc_key):
        a = b = c = d = e = f = g = h = GOLDEN
        st = [a, b, c, d, e, f, g, h]

        self.Seed[0] = enc_key
        # 其余 255 个字保持为 0（__init__ 已初始化）

        for _ in range(4):
            _mix(st)

        mm = self.MM
        seed = self.Seed
        for i in range(0, 256, 8):
            st[0] = (st[0] + seed[i]) & MASK64
            st[1] = (st[1] + seed[i + 1]) & MASK64
            st[2] = (st[2] + seed[i + 2]) & MASK64
            st[3] = (st[3] + seed[i + 3]) & MASK64
            st[4] = (st[4] + seed[i + 4]) & MASK64
            st[5] = (st[5] + seed[i + 5]) & MASK64
            st[6] = (st[6] + seed[i + 6]) & MASK64
            st[7] = (st[7] + seed[i + 7]) & MASK64
            _mix(st)
            mm[i:i + 8] = st

        for i in range(0, 256, 8):
            st[0] = (st[0] + mm[i]) & MASK64
            st[1] = (st[1] + mm[i + 1]) & MASK64
            st[2] = (st[2] + mm[i + 2]) & MASK64
            st[3] = (st[3] + mm[i + 3]) & MASK64
            st[4] = (st[4] + mm[i + 4]) & MASK64
            st[5] = (st[5] + mm[i + 5]) & MASK64
            st[6] = (st[6] + mm[i + 6]) & MASK64
            st[7] = (st[7] + mm[i + 7]) & MASK64
            _mix(st)
            mm[i:i + 8] = st

        self._isaac64()

    def _isaac64(self):
        self.CC = (self.CC + 1) & MASK64
        self.BB = (self.BB + self.CC) & MASK64
        mm = self.MM
        seed = self.Seed
        aa = self.AA
        bb = self.BB

        for i in range(256):
            m = i & 3
            if m == 0:
                aa = (aa ^ ((aa << 21) & MASK64)) ^ MASK64
            elif m == 1:
                aa ^= (aa >> 5)
            elif m == 2:
                aa ^= (aa << 12) & MASK64
            else:
                aa ^= (aa >> 33)

            aa = (aa + mm[(i + 128) & 255]) & MASK64
            x = mm[i]
            y = (mm[(x >> 3) & 255] + aa + bb) & MASK64
            mm[i] = y
            bb = (mm[(y >> 11) & 255] + x) & MASK64
            seed[i] = bb

        self.AA = aa
        self.BB = bb

    def next_uint64(self):
        """等价于 Go 的 (*RandCtx64).ISAacRandom()。"""
        result = self.Seed[self.RandCnt]
        if self.RandCnt == 0:
            self._isaac64()
            self.RandCnt = 255
        else:
            self.RandCnt -= 1
        return result


def keystream(enc_key, length=KEYSTREAM_SIZE, byteorder="big", reverse=False):
    """
    由 decode_key 生成 length 字节的密钥流。

    byteorder: 'big'   -> 对应 Go 的 binary.BigEndian.PutUint64
               'little'-> 小端序变体
    reverse:   True 时整体反转（部分 JS/WASM 实现采用该顺序）
    """
    ctx = RandCtx64(enc_key)
    n_words = (length + 7) // 8
    out = bytearray()
    for _ in range(n_words):
        out += ctx.next_uint64().to_bytes(8, byteorder)
    out = out[:length]
    if reverse:
        out.reverse()
    return bytes(out)


def xor_decrypt(data, key, enc_len=KEYSTREAM_SIZE, byteorder="big", reverse=False):
    """就地 XOR 解密 data 的前 enc_len 字节并返回。"""
    if not data:
        return data
    n = min(enc_len, len(data))
    ks = keystream(key, length=n, byteorder=byteorder, reverse=reverse)
    buf = bytearray(data)
    # 向量化加速（numpy 可用时）
    try:
        import numpy as np
        a = np.frombuffer(bytes(buf[:n]), dtype=np.uint8)
        b = np.frombuffer(ks, dtype=np.uint8)
        buf[:n] = (a ^ b).tobytes()
    except Exception:
        for i in range(n):
            buf[i] ^= ks[i]
    return bytes(buf)
