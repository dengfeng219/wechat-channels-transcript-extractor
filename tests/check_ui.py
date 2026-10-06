# -*- coding: utf-8 -*-
"""
界面自检：用 CDP 打开本地界面，断言关键元素、点按钮、截图。
（走 Target.attachToTarget 扁平模式，兼容新版 Edge）

前置：应用已在 8765 端口运行。
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8")

from tests.cdp import Browser  # noqa: E402

APP = "http://127.0.0.1:8765/"
fails = []

def check(label, cond, detail=""):
    print("  %s %-42s %s" % ("✓" if cond else "✗", label, detail))
    if not cond:
        fails.append(label)

def main():
    b = Browser(9366, os.path.join(ROOT, ".browser_profile_shot"))
    if not b.connect():
        print("FAIL: 浏览器未就绪"); return 1
    try:
        b.open(APP, wait=9)

        print("== 首页 ==")
        check("页面已加载", "视频号文案提取器" in (b.js("document.title") or ""),
              b.js("document.title"))
        check("有 5 个标签页", b.js("document.querySelectorAll('.tabs button').length") == 5)
        check("链接框是多行文本", b.js("document.querySelector('#linkUrl').tagName") == "TEXTAREA")

        b.js("document.querySelector('#linkUrl').value="
             "'https://weixin.qq.com/sph/ARBFNO8PaW\\n"
             "https://weixin.qq.com/sph/ABCDEF1234';"
             "document.querySelector('#linkUrl').dispatchEvent(new Event('input'));")
        time.sleep(2.5)
        cnt = b.js("document.querySelector('#linkCount').textContent") or ""
        check("批量提示出现", "2" in cnt, cnt[:30])
        b.shot(os.path.join(HERE, "ui_batch.png"))

        print()
        print("== 历史任务：折叠 ==")
        b.js("document.querySelector('#histTabBtn') ? 0 : "
             "[...document.querySelectorAll('.tabs button')]"
             ".find(x=>x.dataset.tab==='history').click()")
        time.sleep(3)
        n_ghead = b.js("document.querySelectorAll('#histList .ghead').length") or 0
        n_body = b.js("document.querySelectorAll('#histList .gbody').length") or 0
        n_open = b.js("document.querySelectorAll('#histList .gbody.open').length") or 0
        check("有分组标题", n_ghead > 0, "%d 个分组" % n_ghead)
        check("有折叠体", n_body == n_ghead, "%d 个" % n_body)
        check("默认只展开第一个", n_open == 1, "展开 %d 个" % n_open)
        check("提取按钮已隐藏",
              b.js("document.querySelector('#runActions').classList.contains('hide')") is True)
        b.shot(os.path.join(HERE, "ui_history.png"))

        print()
        print("== 点击标题折叠 / 展开 ==")
        before = b.js("document.querySelectorAll('#histList .gbody.open').length") or 0
        b.js("document.querySelector('#histList .ghead').click()")
        time.sleep(1)
        after = b.js("document.querySelectorAll('#histList .gbody.open').length") or 0
        check("点标题可折叠", after == before - 1, "%d -> %d" % (before, after))
        b.js("document.querySelector('#histList .ghead').click()")
        time.sleep(1)
        back = b.js("document.querySelectorAll('#histList .gbody.open').length") or 0
        check("再点可展开", back == before, "%d -> %d" % (after, back))

        print()
        print("== 全部展开 / 全部折叠 ==")
        b.js("document.querySelector('#histExpandAll').click()")
        time.sleep(1.5)
        allopen = b.js("document.querySelectorAll('#histList .gbody.open').length") or 0
        check("全部展开", allopen == n_ghead, "%d/%d" % (allopen, n_ghead))
        b.js("document.querySelector('#histCollapseAll').click()")
        time.sleep(1.5)
        none = b.js("document.querySelectorAll('#histList .gbody.open').length") or 0
        check("全部折叠", none == 0, "%d 个展开" % none)
        b.shot(os.path.join(HERE, "ui_history_allclosed.png"))

        print()
        print("== 展开状态会被记住 ==")
        b.js("document.querySelectorAll('#histList .ghead')[1].click()")
        time.sleep(1)
        saved = b.js("localStorage.getItem('wxt_open_groups')")
        check("写入了本地存储", bool(saved) and saved != "[]", str(saved)[:50])
        b.js("location.reload()")
        time.sleep(9)
        b.js("[...document.querySelectorAll('.tabs button')]"
             ".find(x=>x.dataset.tab==='history').click()")
        time.sleep(3)
        re_open = b.js("document.querySelectorAll('#histList .gbody.open').length") or 0
        check("刷新后仍是展开的", re_open >= 1, "%d 个展开" % re_open)
        b.shot(os.path.join(HERE, "ui_history_open.png"))

        print()
        print("== 历史详情 ==")
        b.js("const x=document.querySelector('[data-hview]'); if(x) x.click();")
        time.sleep(2.5)
        check("详情能打开",
              b.js("!document.querySelector('#histDetail').classList.contains('hide')") is True)
        check("详情有正文", (b.js("document.querySelector('#histText').textContent.length") or 0) > 50,
              "%s 字" % b.js("document.querySelector('#histText').textContent.length"))
    finally:
        b.close()

    print()
    print("PASS" if not fails else "FAIL: %s" % fails)
    return 1 if fails else 0

if __name__ == "__main__":
    sys.exit(main())
