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
import datetime, io, os, re, shutil, subprocess, sys, tempfile

PAGE_NAMES = ('宿迁职业技术学院作息时间表.html', 'index.html')

def _page_file():
    """页面文件名（P2）：本地开发用「宿迁职业技术学院作息时间表.html」，仓库里只保留 index.html。
    两份内容必须一致，所以按顺序找，clone 下来也能直接跑。"""
    for _n in (PAGE_NAMES):
        if os.path.exists(_n):
            return _n
    raise SystemExit('找不到页面文件：' + ' 或 '.join(PAGE_NAMES) + '（请在仓库根目录执行）')

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
    r"/usr/bin/microsoft-edge",
    r"/usr/bin/google-chrome",
    r"/usr/bin/google-chrome-stable",
    r"/usr/bin/chromium",
    r"/usr/bin/chromium-browser",
    r"/snap/bin/chromium",
    r"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    r"/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
]
# P4：找不到浏览器时**必须报错**，不能静默当成 PASS（否则闸门空转、发布质量无保障）

# 把 PATH 里能找到的浏览器补进候选表：
# 原来只查硬编码路径，/usr/local/bin/chromium 这种（PATH 可达但不在表里）会被误判成"没有浏览器"，
# 于是 smoke 静默跳过（exit 0）、functest 误报找不到（exit 2）。
for _n in ('msedge', 'microsoft-edge', 'google-chrome',
           'google-chrome-stable', 'chromium', 'chromium-browser', 'chrome'):
    _w = shutil.which(_n)
    if _w and _w not in BROWSERS:
        BROWSERS.insert(0, _w)

import shutil as _shutil
if not any(os.path.exists(_b) for _b in BROWSERS) and not any(
        _shutil.which(_b) for _b in ('msedge', 'microsoft-edge', 'google-chrome',
                                     'google-chrome-stable', 'chromium', 'chromium-browser')):
    raise SystemExit('✗ 找不到任何浏览器（Edge / Chrome / Chromium）—— 渲染与交互闸门无法执行；'
                     '装一个浏览器，或用 BROWSER=<路径> 指定后再跑（不静默 PASS）')


target = sys.argv[1] if len(sys.argv) > 1 else _page_file()
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
    raise SystemExit('✗ 找不到 Edge / Chrome / Chromium —— 渲染冒烟闸门无法执行，不静默放行')
    sys.exit(0)


ANDROID_UA = ('Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) '
              'Chrome/120.0.0.0 Mobile Safari/537.36')


# 定时刻渲染：把「现在」钉死，倒计时断言才不受当天是周几 / 节假日影响。
# 页面读时间的入口只有 Date 和 localStorage['sqzy-today']（见页面里的 resolveSchedule），
# 所以拷一份页面、在 <head> 后注入假时钟 + 模板覆盖，就能确定性地验倒计时规则。
PIN_JS = (
    "<script>(function(){"
    "var FIX=Date.parse('@D@T@:00');var _D=Date;"
    "function ND(a,b,c,d,e,f,g){var n=arguments.length;"
    " if(n===0)return new _D(FIX);"
    " if(n===1)return new _D(a);"
    " return new _D(a,b,c,d,e,f,g);}"
    "ND.prototype=_D.prototype;ND.now=function(){return FIX;};ND.parse=_D.parse;ND.UTC=_D.UTC;"
    "window.Date=ND;"
    "function ov(){try{localStorage.setItem('sqzy-today','@O@');"
    " return localStorage.getItem('sqzy-today')==='@O@';}catch(e){return false;}}"
    "if(!ov()){var S={getItem:function(k){return k==='sqzy-today'?'@O@':null;},"
    " setItem:function(){},removeItem:function(){}};"
    " try{Object.defineProperty(window,'localStorage',{value:S,configurable:true});}catch(e2){}}"
    "})();</script>")


def pin_html(text, override, ymd, hm):
    """在页面 <head> 后插一段假时钟：override 是模板名（weekday/saturday/...）"""
    js = PIN_JS.replace('@D@T@', ymd + 'T' + hm).replace('@O@', override)
    m = re.search(r'<head[^>]*>', text, re.I)
    if not m:
        return None
    return text[:m.end()] + js + text[m.end():]


def render_pin(page_text, override, ymd, hm, w, h, name, android=False):
    """按钉死的时间渲染一遍；拿到 (dom, err)，失败返回 (None, None)"""
    if not page_text:
        return None, None
    html = pin_html(page_text, override, ymd, hm)
    if html is None:
        return None, None
    prof = tempfile.mkdtemp(prefix='sqzy_pin_')
    try:
        p = os.path.join(prof, name)
        io.open(p, 'w', encoding='utf-8').write(html)
        return render(w, h, android, path=p)
    finally:
        shutil.rmtree(prof, ignore_errors=True)


BROWSER_TIMEOUT = 'BROWSER-TIMEOUT'


def render(w, h, android=False, path=None, tries=2):
    """跑一次无头浏览器。超时（机器忙 / 杀软拦 / 浏览器卡住）重试一次再放弃：
    以前超时直接抛 subprocess.TimeoutExpired，整个闸门只剩一段 traceback，看不出是什么问题。"""
    for attempt in range(tries):
        prof = tempfile.mkdtemp(prefix='sqzy_smoke_')
        u = url if path is None else 'file:///' + quote(os.path.abspath(path).replace('\\', '/'), safe='/:')
        cmd = [exe, '--headless=new', '--disable-gpu', '--no-first-run',
               '--user-data-dir=' + prof, '--window-size=%d,%d' % (w, h),
               '--virtual-time-budget=6000', '--enable-logging=stderr', '--v=0',
               '--dump-dom', u]
        if android:
            cmd.insert(1, '--user-agent=' + ANDROID_UA)
        try:
            try:
                r = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8',
                                   errors='replace', timeout=120)
            except subprocess.TimeoutExpired:
                print('    · 无头浏览器 120 秒没返回（第 %d/%d 次），重试' % (attempt + 1, tries))
                continue
            return r.stdout or '', r.stderr or ''
        finally:
            shutil.rmtree(prof, ignore_errors=True)
    return '', BROWSER_TIMEOUT


def now_items(bar):
    """拆 #nowBar：每个学院 -> (状态文字, 倒计时类型, 倒计时文字)"""
    out = []
    for chunk in bar.split('<div class="nowitem')[1:]:
        st = re.search(r'<span>([^<]*)</span>', chunk)
        cd = re.search(r'<em class="cd ([a-z]+)">([^<]*)</em>', chunk)
        out.append((st.group(1).strip() if st else '',
                    cd.group(1) if cd else '', cd.group(2) if cd else ''))
    return out


RANGE = r'\d{1,2}:\d{2}[–—-]\d{1,2}:\d{2}'
NO_CD_STATE = ('未开课', '已关寝')
FREE_STATE = '休息'
PREP_STATE = '就寝准备'


def check(label, dom, err, mobile=False, android=False, pin=None):
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

    if BROWSER_TIMEOUT in (err or ''):
        fail.append('无头浏览器两次都 120 秒没返回 —— 环境问题（机器忙/杀软拦），不是页面缺陷；重跑一次')
        return fail
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
        # 休息段合并后：周内 52、周六/周日 20、放假 4 —— 这里只校验“每个学院至少生成 1 块”
        if blk < 4:
            fail.append('竖排时间轴没生成（只有 %d 个节块）' % blk)
        if 'id="vtNow"' not in body:
            fail.append('竖排时间轴的「现在」线没有生成')

    rows = now_items(bar)
    if pin is not None:
        kind_want, word_want, n_want = pin
        got = [(k, w) for _, k, w in rows if k]      # 只看真的渲染出倒计时的那些
        bad = []
        if len(rows) != 4:
            bad.append('学院卡片 %d 条（应为 4）' % len(rows))
        if len(got) != n_want:
            bad.append('倒计时 %d 条（应为 %d）：%s' % (len(got), n_want, [w for _, w in got]))
        for k, w in got:
            if kind_want and k != kind_want:
                bad.append('倒计时类型 %s（应为 %s）：%s' % (k, kind_want, w))
            if word_want and word_want not in w:
                bad.append('倒计时文字里没有「%s」：%s' % (word_want, w))
        if bad:
            for x in bad[:4]:
                print('    ✗ %s' % x)
            fail.append('定时刻断言不符 %d 处' % len(bad))
        else:
            print('    ✓ 定时刻断言通过：%s'
                  % ('、'.join(w for _, w in got) if got else '全部休息，无倒计时'))
        return fail

    # 倒计时该不该有：只看渲染出来的状态，不看今天是周几
    # （节假日/周末没课，本来就没有倒计时 —— 以前按「08:00–21:35 必有倒计时」判，节假日必误报）
    bad = []
    for txt, kind, word in rows:
        base = txt.split(' ')[0]
        if base in NO_CD_STATE:
            if kind:
                bad.append('%s 不该有倒计时（%s）' % (txt, word))
        elif base == FREE_STATE:
            if kind and '关寝' not in word:
                bad.append('休息段的倒计时应为「距关寝」：%s' % word)
        elif base == PREP_STATE:
            if not kind:
                bad.append('%s 缺「距关寝」倒计时' % txt)
        elif re.search(RANGE, txt):
            if not kind:
                bad.append('%s 在时段内却没有倒计时' % txt)
        else:
            print('    · 认不出的状态文字（不判失败）: %s' % txt)
    if bad:
        for x in bad[:4]:
            print('    ✗ %s' % x)
        fail.append('状态与倒计时不一致 %d 处' % len(bad))
    else:
        print('    ✓ 状态与倒计时自洽（%d 条学院卡片，%s）'
              % (len(rows), datetime.datetime.now().strftime('%H:%M')))
    return fail


PAGE_TEXT = ''
if not target.startswith(('http://', 'https://')):
    try:
        PAGE_TEXT = io.open(target, encoding='utf-8').read()
    except Exception as e:
        print('  · 读不到页面源码（%s），跳过定时刻渲染' % e)

allfail = []
for label, w, h, mob, andr in (('横版 1400x1000', 1400, 1000, False, False),
                              ('竖版 420x900', 420, 900, True, False),
                              ('安卓 UA 430x900', 430, 900, True, True)):
    dom, err = render(w, h, andr)
    allfail += check(label, dom, err, mob, andr)

# 定时刻跑三遍：倒计时规则跟「今天周几 / 是不是节假日」脱钩，否则节假日必误报。
# 覆盖三条规则：周内正课有倒计时 / 休息段距关寝 ≤2 小时要报关寝 / 白天休息不乱报。
for label, ov, ymd, hm, kind, word, n in (
        ('定时 周三 10:00 · 周内正课', 'weekday', '2026-09-23', '10:00', 'end', '下课', 4),
        ('定时 周六 17:30 · 休息距关寝', 'saturday', '2026-09-26', '17:30', 'end', '关寝', 4),
        ('定时 周日 09:00 · 白天休息', 'sunday', '2026-09-27', '09:00', '', '', 0)):
    dom, err = render_pin(PAGE_TEXT, ov, ymd, hm, 1400, 700, os.path.basename(target))
    if dom is None:
        print('  [%s]  · 跳过（只有本地页面文件才能定时刻渲染）' % label)
        continue
    allfail += check(label, dom, err, pin=(kind, word, n))

print('  smoke: %s' % ('PASS' if not allfail else 'FAIL'))
for x in allfail:
    print('    ✗ ' + x)
sys.exit(1 if allfail else 0)
