# -*- coding: utf-8 -*-
"""用真实样本验证解密实现：wx_encrypted.mp4 + wx_response.json 中的 decode_key。"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from app.wxdecrypt import extract_decode_key, decrypt_file, looks_encrypted  # noqa: E402
from app.isaac64 import keystream  # noqa: E402

def main():
    enc = os.path.join(HERE, "wx_encrypted.mp4")
    resp = os.path.join(HERE, "wx_response.json")
    if not os.path.exists(enc):
        print("SKIP: 缺少样本 %s" % enc)
        return 2

    data = json.load(open(resp, encoding="utf-8"))
    media = data["data"]["object_desc"]["media"][0]
    key = extract_decode_key(media)
    print("decode_key = %d" % key)
    print("file_size  = %s (实际 %d)" % (media.get("file_size"), os.path.getsize(enc)))

    with open(enc, "rb") as f:
        head = f.read(32)
    print("加密头部   = %s" % head[:16].hex())
    assert looks_encrypted(head), "样本应为加密状态"

    out = os.path.join(HERE, "wx_decrypted.mp4")
    r = decrypt_file(enc, out, key=key)
    print("结果       = %s" % r)
    if r["ok"]:
        with open(out, "rb") as f:
            h = f.read(16)
        print("解密头部   = %s" % h.hex())
        print("ftyp 偏移  = %d" % h.find(b"ftyp"))
        print("PASS")
        return 0
    print("FAIL")
    return 1

if __name__ == "__main__":
    sys.exit(main())
