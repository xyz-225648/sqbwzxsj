# -*- coding: utf-8 -*-
"""发布前渲染冒烟测试：用无头 Edge/Chrome 真跑一遍页面，抓三类问题

  1) 任何未捕获的 JS 异常（Uncaught ...）—— node --check 查不出来，
     但一个 ReferenceError 就能让它后面的所有初始化代码不执行。
  2) 被 bootStep 兜住的启动步骤异常：说明某个功能其实没跑起来。
  3) 「当前状态 / 还有多久下课」到底渲染出来没有：真跑完必须能在 DOM 里看到
     状态文字和倒计时 —— 专门防「页面看着正常、功能却没了」。

横版（1400x1000）和竖版（420x900）各跑一遍，手机版多验一条：竖排时间轴有没有生成。

用法: python smoke_page.py [本地页面路径 或 http(s) URL]
"""
import datetime, os, re, shutil, subprocess, sys, tempfile
from urllib.parse import quote

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BROWSERS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]

target = sys.argv[1] if len(sys.argv) > 1 else '宿迁职业技术学院作息时间表.html'
if target.startswith(('http://', 'https://')):
    url = target
elif os.path.exists(target):
    url = 'file:///' + quote(os.path.abspath(target).replace('\\', '/'), safe='/:')
else:
    print('  找不到页面: %s' % target)
    sys.exit(1)

exe = None
for p in BROWSERS:
    if os.path.exists(p):
        exe = p
        break
if not exe:
    print('  ⚠ 没找到 Edge/Chrome，跳过渲染冒烟测试（语法检查已单独执行）')
    sys.exit(0)


ANDROID_UA = ('Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) '
              'Chrome/120.0.0.0 Mobile Safari/537.36')


def render(w, h, android=False):
    prof = tempfile.mkdtemp(prefix='sqzy_smoke_')
    cmd = [exe, '--headless=new', '--disable-gpu', '--no-first-run',
           '--user-data-dir=' + prof, '--window-size=%d,%d' % (w, h),
           '--virtual-time-budget=6000', '--enable-logging=stderr', '--v=0',
           '--dump-dom', url]
    if android:
        cmd.insert(1, '--user-agent=' + ANDROID_UA)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8',
                           errors='replace', timeout=120)
    finally:
        shutil.rmtree(prof, ignore_errors=True)
    return r.stdout or '', r.stderr or ''


def check(label, dom, err, mobile=False, android=False):
    fail = []
    print('  [%s]' % label)

    uncaught = [l.strip() for l in err.split('\n') if 'Uncaught' in l]
    for l in uncaught[:6]:
        m = re.search(r'"([^"]*Uncaught[^"]*)"', l)
        print('    ✗ 页面抛异常: %s' % (m.group(1) if m else l[:160]))
    if uncaught:
        fail.append('未捕获异常 %d 条' % len(uncaught))
    else:
        print('    未捕获异常: 0 条')

    steps = sorted(set(re.findall(r'\[启动失败\] ([^\s"\\]+)', err)))
    if steps:
        print('    ✗ 有启动步骤抛异常: %s' % ', '.join(steps))
        fail.append('启动步骤异常: %s' % ', '.join(steps))
    else:
        print('    启动步骤异常: 0 处')

    if '<html' not in dom.lower():
        fail.append('页面没有渲染出 DOM（拿到 %d 字节）' % len(dom))
        return fail

    body = re.sub(r'<script[\s\S]*?</script>', '', dom, flags=re.I)
    body = re.sub(r'<style[\s\S]*?</style>', '', body, flags=re.I)

    m = re.search(r'id="nowBar">([\s\S]{0,6000})', body)
    bar = m.group(1) if m else ''
    if not bar:
        fail.append('找不到 #nowBar 内容')
    else:
        items = bar.count('class="nowitem')
        cds = re.findall(r'<em class="cd ([a-z]+)">([^<]*)</em>', bar)
        print('    当前状态条: %d 个学院, 倒计时 %d 条 %s'
              % (items, len(cds), ('例: ' + cds[0][1]) if cds else ''))
        if items < 4:
            fail.append('当前状态条只有 %d 个学院（应为 4）' % items)

    ms = re.findall(r'<div class="m">([^<]*)</div>', body)
    print('    卡片状态文字: %d 个 %s' % (len(ms), ('例: ' + ms[0]) if ms else ''))
    if len(ms) < 4:
        fail.append('卡片只有 %d 个（应为 4）' % len(ms))
    elif any(not x.strip() for x in ms):
        fail.append('有卡片的状态文字是空的 —— renderNow 没跑完')

    if android:
        marked = 'data-android="1"' in dom
        rule = 'data-android="1"] #devBtn' in dom
        print('    安卓标记 data-android=1:', marked, '| 隐藏规则存在:', rule)
        if not marked:
            fail.append('安卓 UA 下没有打上 data-android 标记')
        if not rule:
            fail.append('页面里没有「安卓隐藏 置顶/切换」的 CSS 规则')

    if mobile:
        blk = len(re.findall(r'class="vt-blk', body))
        print('    竖排时间轴节块: %d 个' % blk)
        if blk < 40:
            fail.append('竖排时间轴没生成（只有 %d 个节块）' % blk)
        if 'id="vtNow"' not in body:
            fail.append('竖排时间轴的「现在」线没有生成')

    now = datetime.datetime.now()
    mins = now.hour * 60 + now.minute
    if 8 * 60 <= mins <= 21 * 60 + 35:      # 这段区间里必然有课/课间，倒计时不该为空
        if re.search(r'<em class="cd ([a-z]+)">', bar):
            print('    ✓ 倒计时已渲染（当前 %s 在上课时段内）' % now.strftime('%H:%M'))
        else:
            fail.append('当前 %s 属于上课时段，却一条倒计时都没有' % now.strftime('%H:%M'))
    else:
        print('    · 当前 %s 不在 08:00–21:35 内，跳过倒计时断言' % now.strftime('%H:%M'))
    return fail


allfail = []
for label, w, h, mob, andr in (('横版 1400x1000', 1400, 1000, False, False),
                              ('竖版 420x900', 420, 900, True, False),
                              ('安卓 UA 430x900', 430, 900, True, True)):
    dom, err = render(w, h, andr)
    allfail += check(label, dom, err, mob, andr)

print('  smoke: %s' % ('PASS' if not allfail else 'FAIL'))
for x in allfail:
    print('    ✗ ' + x)
sys.exit(1 if allfail else 0)
