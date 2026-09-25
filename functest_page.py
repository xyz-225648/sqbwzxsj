# -*- coding: utf-8 -*-
"""交互功能测试：无头 Edge + CDP 真点、真悬停、真滚轮，把页面每个功能走一遍。

和 smoke_page.py 的分工：
  smoke_page.py    = 打开就完事，只看「有没有报错、有没有渲染出来」
  functest_page.py = 真交互：悬停/钉住、学院跳转、回到顶部、设置面板 + 滚动锁、
                     通知判定（含「只勾选部分学院时不许发别的学院」）、更新弹窗、
                     缩放记忆、防右键/防调试/禁复制、手机版竖排点按

页面用 http://127.0.0.2:端口/ 打开（不是 127.0.0.1）：这样 location.hostname
既不是 127.0.0.1 也不是 localhost，页面走「网页版」分支，跟真实浏览器访问一致；
同时又有真实 origin，localStorage 能用（file:// 下 Chrome 不给 localStorage）。

用法: python functest_page.py [本地页面路径]
"""
import json, os, re, shutil, socket, subprocess, sys, tempfile, threading, time

PAGE_NAMES = ('宿迁职业技术学院作息时间表.html', 'index.html')

def _page_file():
    """页面文件名（P2）：本地开发用「宿迁职业技术学院作息时间表.html」，仓库里只保留 index.html。
    两份内容必须一致，所以按顺序找，clone 下来也能直接跑。"""
    for _n in (PAGE_NAMES):
        if os.path.exists(_n):
            return _n
    raise SystemExit('找不到页面文件：' + ' 或 '.join(PAGE_NAMES) + '（请在仓库根目录执行）')

from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import quote

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

import websocket

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

PAGE = sys.argv[1] if len(sys.argv) > 1 else _page_file()
PAGE = os.path.abspath(PAGE)
HOST = '127.0.0.2'
VIEW_W, VIEW_H = 1280, 900

passed, failed = [], []


def ok(label, extra=''):
    passed.append(label)
    print('    ✓ %s%s' % (label, ('  ' + extra) if extra else ''))


def bad(label, why):
    failed.append('%s：%s' % (label, why))
    print('    ✗ %s  ← %s' % (label, why))


def check(label, cond, why='', extra=''):
    if cond:
        ok(label, extra)
    else:
        bad(label, why or '断言不成立')
    return bool(cond)


def free_port():
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    p = s.getsockname()[1]
    s.close()
    return p


class SilentHandler(SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


class CDP:
    def __init__(self, ws_url):
        self.ws = websocket.create_connection(ws_url, suppress_origin=True, timeout=60)
        self.n = 0
        self.events = []

    def send(self, method, params=None):
        self.last = method
        self.n += 1
        mine = self.n
        self.ws.send(json.dumps({'id': mine, 'method': method, 'params': params or {}}))
        end = time.time() + 60
        while time.time() < end:
            try:
                msg = json.loads(self.ws.recv())
            except websocket.WebSocketTimeoutException:
                raise RuntimeError('CDP 超时: ' + method)
            if msg.get('id') == mine:
                if msg.get('error'):
                    raise RuntimeError('%s -> %s' % (method, json.dumps(msg['error'])[:200]))
                return msg.get('result', {})
            self.events.append(msg)
        raise RuntimeError('CDP 无回包: ' + method)

    def ev(self, expr):
        r = self.send('Runtime.evaluate',
                      {'expression': expr, 'returnByValue': True, 'awaitPromise': True})
        if r.get('exceptionDetails'):
            raise RuntimeError('JS 异常: %s' % json.dumps(r['exceptionDetails'])[:400])
        return (r.get('result') or {}).get('value')

    def js_ok(self, expr):
        try:
            return bool(self.ev('(function(){ return !!(%s); })()' % expr))
        except Exception:
            return False

    def mouse(self, kind, x, y, button='none', buttons=0, modifiers=0, delta_y=0):
        p = {'type': kind, 'x': x, 'y': y, 'button': button, 'buttons': buttons,
             'clickCount': 1 if kind in ('mousePressed', 'mouseReleased') else 0,
             'modifiers': modifiers}
        if kind == 'mouseWheel':
            p['deltaX'] = 0
            p['deltaY'] = delta_y
        return self.send('Input.dispatchMouseEvent', p)

    def hover(self, x, y):
        self.mouse('mouseMoved', x, y)

    def click_at(self, x, y):
        self.mouse('mouseMoved', x, y)
        self.mouse('mousePressed', x, y, button='left', buttons=1)
        self.mouse('mouseReleased', x, y, button='left', buttons=0)

    def wheel(self, x, y, dy, ctrl=False):
        self.mouse('mouseWheel', x, y, delta_y=dy, modifiers=2 if ctrl else 0)

    def esc(self):
        """按 Esc。必须用合成事件：Edge 无头模式真的按 Esc 会弹出
        edge://sync-confirmation-dialog/ 新标签页，把 CDP 目标抢走导致断线。"""
        try:
            self.ev('document.body.dispatchEvent(new KeyboardEvent("keydown",'
                    '{key:"Escape",code:"Escape",keyCode:27,bubbles:true,cancelable:true}))')
        except Exception:
            pass

    def wait_boot(self, extra=''):
        for _ in range(120):
            if self.js_ok('window.SQTC' + extra):
                return True
            time.sleep(0.25)
        return False

    def nav(self, url):
        self.send('Page.navigate', {'url': url})
        self.wait_boot()
        time.sleep(1.0)

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass


def bools(cdp, expr):
    """取布尔值；页面里取不到元素等异常一律当 False，并给出原因"""
    v = cdp.ev('(function(){ try { return %s; } catch(e){ return "ERR:" + e; } })()' % expr)
    if isinstance(v, str) and v.startswith('ERR:'):
        raise RuntimeError(v)
    return v


def find_browser():
    for p in BROWSERS:
        if os.path.exists(p):
            return p
    return None


def run_all(cdp, url, vw, vh):
    # ---------- 0. 启动是否干净 ----------
    uncaught = [e for e in cdp.events if e.get('method') == 'Runtime.exceptionThrown']
    console_err = []
    for e in cdp.events:
        if e.get('method') == 'Runtime.consoleAPICalled' and e['params'].get('type') == 'error':
            txt = ' '.join(str(a.get('value', a.get('description', '')))
                           for a in e['params'].get('args', []))
            console_err.append(txt)
    boot_fail = [t for t in console_err if '[启动失败]' in t]
    check('重新加载后无未捕获异常', not uncaught, '有 %d 条异常' % len(uncaught))
    check('启动步骤无异常', not boot_fail, '；'.join(boot_fail)[:160])
    check('暴露自检入口 window.SQTC', bools(cdp, 'typeof window.SQTC === "object"'),
          'window.SQTC 不存在')
    check('走网页版分支（不是本地助手）', bools(cdp, 'window.SQZY_API === undefined'),
          '本页被当成了桌面版')

    cdp.ev('localStorage.clear()')
    time.sleep(0.2)
    cdp.nav(url + '?clean=1')

    # ---------- 1. 当前状态 / 倒计时 ----------
    n_items = bools(cdp, 'document.querySelectorAll("#nowBar .nowitem").length')
    check('当前状态条 4 个学院', n_items == 4, '实际 %s 个' % n_items)
    n_cd = bools(cdp, 'document.querySelectorAll("#nowBar .cd").length')
    n_meta = bools(cdp, 'document.querySelectorAll("#cards .card-h .m").length')
    check('卡片状态文字 4 条', n_meta == 4, '实际 %s 条' % n_meta)
    # 倒计时该不该有：只看渲染出来的状态，不按「现在几点」硬判 ——
    # 节假日/周末整天休息，本来就没有倒计时（以前按 08:00–21:35 判，节假日必误报）。
    states = cdp.ev('''[].slice.call(document.querySelectorAll("#nowBar .nowitem")).map(function(it){
        var s = it.querySelector("span"), cd = it.querySelector(".cd");
        return {txt: s ? s.textContent : "", cd: cd ? cd.textContent : ""};})''') or []
    bad = []
    for it in states:
        txt, cd = it.get('txt', ''), it.get('cd', '')
        base = txt.split(' ')[0]
        if base in ('未开课', '已关寝'):
            if cd:
                bad.append('%s 不该有倒计时' % txt)
        elif base == '休息':
            if cd and '关寝' not in cd:
                bad.append('休息段的倒计时应为距关寝：%s' % cd)
        elif base == '就寝准备':
            if not cd:
                bad.append('%s 缺距关寝倒计时' % txt)
        elif re.search(r'\d{1,2}:\d{2}[\u2013\u2014-]\d{1,2}:\d{2}', txt):
            if not cd:
                bad.append('%s 在时段内却没有倒计时' % txt)
    check('状态与倒计时自洽', not bad, '；'.join(bad[:3]))
    print('    · 倒计时 %s 条 %s' % (n_cd, ('例: ' + (states[0].get('cd') or '无')) if states else ''))

    # ---------- 2. 横竖版切换 ----------
    cdp.ev('window.SQTC.applyDevice("mobile")')
    time.sleep(0.7)
    dev = cdp.ev('document.documentElement.getAttribute("data-device")')
    check('切成手机版：data-device=mobile', dev == 'mobile', 'data-device=%s' % dev)
    check('手机版显示竖排时间轴',
          bools(cdp, 'getComputedStyle(document.getElementById("vtWrap")).display !== "none"'),
          '竖排时间轴仍隐藏')
    n_blk = bools(cdp, 'document.querySelectorAll("#vtPlot .vt-blk").length')
    # 休息段已合并显示：周内 52 块；周六=上午4节+1休息（4院×5）；周日=1休息+4晚段（4院×5）；
    # 放假=1休息（4院×1）。按当前实际作息模板动态断言，节假日/周末不会再误报。
    sched = cdp.ev('(window.resolveSchedule(new Date()) || {}).label || ""')
    expected = 52
    if '周六' in sched or '周日' in sched:
        expected = 20
    elif '放假' in sched:
        expected = 4
    check('竖排时间轴节块数符合当前作息', n_blk == expected,
          '实际 %s 个（%s 应为 %s）' % (n_blk, sched, expected))
    cdp.ev('window.SQTC.applyDevice("desktop")')
    time.sleep(0.7)
    check('切回桌面版', cdp.ev('document.documentElement.getAttribute("data-device")') == 'desktop',
          '没切回来')

    # ---------- 3. 悬停预览轴 / 钉住 ----------
    # 页面版本刚升、线上 version.txt 还没发出去时，页面会**按设计**自动弹一层「有新版本」
    # （带滚动锁，会把后面所有真实交互挡住）。这不是缺陷，但会让交互测试不可复现，
    # 所以先把自动弹出来的关掉，并断言关干净了。
    shut = cdp.ev('(function(){var n=[];document.querySelectorAll(".sheet.on").forEach(function(s){'
                  'var x=s.querySelector(".sheet-x");if(x){x.click();n.push(s.id);}});return n;})()')
    time.sleep(0.5)
    if shut:
        print('    · 先关掉页面自动弹出的提示层 %r（线上版本数据比本地页面旧时会有）' % (shut,))
    check('交互前没有残留弹层 / 滚动锁',
          cdp.ev('document.querySelectorAll(".sheet.on").length') == 0
          and cdp.ev('document.documentElement.classList.contains("sheet-lock")') is False,
          '还有弹层或滚动锁')
    cdp.ev('window.scrollTo(0,0)')
    cdp.ev('document.getElementById("gGrid").scrollIntoView({block:"center"})')
    time.sleep(0.5)
    box = cdp.ev('(function(){var ar=document.querySelectorAll("#gGrid .g-lane .g-area")[1];'
                 'if(!ar) ar=document.querySelectorAll("#gGrid .g-lane")[1];'
                 'var b=ar.getBoundingClientRect();'
                 'return {x:b.left+b.width*0.45, y:Math.min(' + str(vh - 60) + ', b.top+b.height*0.5)};})()')
    print('    · 悬停落点 x=%.0f y=%.0f' % (box['x'], box['y']))
    diag = cdp.ev('(function(){var ar=document.querySelectorAll("#gGrid .g-lane .g-area")[1];'
                  'var b=ar.getBoundingClientRect();var x=b.left+b.width*0.45;'
                  'var y=Math.min(' + str(vh - 60) + ', b.top+b.height*0.5);'
                  'var el=document.elementFromPoint(x,y);'
                  'return {hit:el?(el.id||el.className||el.tagName):null,'
                  'inGrid:!!(el&&el.closest&&el.closest("#gGrid"))};})()')
    print('    · 悬停点命中 %r' % (diag,))
    check('悬停点确实落在时间轴上（没被弹层挡住）',
          (diag or {}).get('inGrid') is True, '落点上不是时间轴：%r' % (diag,))
    cdp.hover(box['x'], box['y'])
    time.sleep(0.4)
    check('悬停出现预览竖线',
          bools(cdp, 'document.getElementById("guide").classList.contains("on")'), 'guide 没有 on')
    bub = cdp.ev('document.getElementById("guideBubble").textContent')
    check('预览气泡显示时刻', bool(re.match(r'^\d{2}:\d{2}$', bub or '')), '气泡内容=%r' % bub)
    chips = cdp.ev('(function(){var a=[];document.querySelectorAll("#gGrid .gchip").forEach('
                   'function(c){a.push(c.textContent.trim());});return a;})()')
    check('四条泳道都有状态胶囊', len(chips) == 4 and all(chips), '胶囊=%r' % (chips,))
    cdp.click_at(box['x'], box['y'])
    time.sleep(0.4)
    check('点击可钉住预览轴',
          bools(cdp, 'document.getElementById("guide").classList.contains("pinned")'), '没有 pinned')
    check('钉住后气泡带取消按钮', '✕' in (cdp.ev(
        'document.getElementById("guideBubble").textContent') or ''), '气泡里没有取消按钮')
    cdp.esc()
    time.sleep(0.4)
    check('Esc 取消钉住',
          not bools(cdp, 'document.getElementById("guide").classList.contains("pinned")'), '仍然钉着')

    # ---------- 4. 点学院名跳转 ----------
    # 先等校历回调：applyCalendar 会 renderGantt() 重建 #gGrid 的所有子节点。
    # 以前监听是逐元素绑的，重建后点学院名就没反应了（v2.3.14 改成事件委托），
    # 所以这条断言必须在校历回调之后点，否则测不出这个真 bug。
    cal = ''
    for _ in range(80):
        cal = cdp.ev('(function(){var n=document.getElementById("calNote");return n?n.textContent:"";})()') or ''
        if cal:
            break
        time.sleep(0.25)
    print('    · 校历回调: %s' % (cal or '(没等到，按「没校历」继续)')[:52])
    cdp.ev('window.scrollTo(0,0)')
    time.sleep(0.2)
    cdp.ev('document.querySelectorAll("#gGrid .g-lane .g-name")[1].click()')
    # 轮询 1.8 秒：点一下就同步加上 flash 了，但卡片若正好被重绘（校历回调/跨天）会换成新节点，
    # 单点采样容易假失败。轮询只放宽读取时机，不放宽'点了没反应'这件事。
    flash = 0
    for _ in range(12):
        time.sleep(0.15)
        flash = cdp.ev('document.querySelectorAll("#cards .card.flash").length') or 0
        if flash:
            break
    if not flash:
        print('    · 点击诊断 %r' % (cdp.ev('''(function(){
            var n = document.querySelectorAll("#gGrid .g-lane .g-name")[1];
            var cards = [].slice.call(document.querySelectorAll("#cards .card"));
            return {name: !!n, title: n ? n.title : '', cards: cards.length,
                    cls: cards.map(function(c){ return c.className; }),
                    sheets: document.querySelectorAll('.sheet.on').length,
                    y: window.pageYOffset};})()'''),))
    check('点学院名跳到对应卡片并高亮（校历重绘后仍有效）', bool(flash), '卡片没有 flash')

    # ---------- 5. 回到顶部 ----------
    # 页面中途可能自己弹一层（线上版本数据比本地页面新时的「发现新版本」），
    # 它带滚动锁（html.sheet-lock body{position:fixed}），会让滚动测试假失败 —— 先关掉。
    shut = cdp.ev('(function(){var n=[];document.querySelectorAll(".sheet.on").forEach(function(s){'
                  'var x=s.querySelector(".sheet-x");if(x){x.click();n.push(s.id);}});return n;})()')
    if shut:
        print('    · 滚动前先关掉自动弹层 %r' % (shut,))
        time.sleep(0.4)
    # 滚到底，不写死 1200：页面高度跟布局/作息有关（桌面布局只有 ~1000 高、最多滚 200），
    # 写死 1200 时 pageYOffset 会被夹到 200 多，而「回到顶部」的阈值是 300 —— 于是假失败。
    cdp.ev('window.scrollTo(0, 99999)')
    time.sleep(0.6)
    diag = cdp.ev('({y:window.pageYOffset,vh:window.innerHeight,'
                  'sh:document.documentElement.scrollHeight,'
                  'cls:document.documentElement.className,'
                  'sheets:document.querySelectorAll(".sheet.on").length,'
                  'btn:document.getElementById("toTop").className})') or {}
    print('    · 滚动诊断 %r' % (diag,))
    lit = bools(cdp, 'document.getElementById("toTop").classList.contains("on")')
    if (diag.get('y') or 0) > 300:
        check('滚动超过 300px 后「回到顶部」按钮出现', lit is True, '按钮没亮')
    else:
        # 滚不到阈值时按钮就不该亮（阈值在页面 bindToTop 里写死 300）
        check('页面只滚得动 %s px（不足 300）时按钮不亮' % diag.get('y'), lit is False,
              '没到阈值按钮就亮了')
    cdp.ev('document.getElementById("toTop").click()')
    time.sleep(1.4)
    y = cdp.ev('window.pageYOffset')
    check('点「回到顶部」能回顶', (y or 0) <= 4, '当前 pageYOffset=%s' % y)

    # ---------- 6. 设置面板 + 滚动锁 ----------
    cdp.ev('window.scrollTo(0, 500)')
    time.sleep(0.4)
    y_open = cdp.ev('window.pageYOffset')
    cdp.ev('document.getElementById("setBtn").click()')
    time.sleep(0.5)
    check('设置面板能打开',
          bools(cdp, 'document.getElementById("setSheet").classList.contains("on")'), '面板没打开')
    check('打开面板时锁定页面滚动',
          bools(cdp, 'document.documentElement.classList.contains("sheet-lock")'), '没有 sheet-lock')
    y_locked = cdp.ev('window.pageYOffset')
    locked_top = cdp.ev('document.body.style.top')
    cbox = cdp.ev('(function(){var r=document.querySelector("#setSheet .sheet-card").getBoundingClientRect();'
                  'return {l:r.left, t:r.top, b:r.bottom};})()')
    bx = max(4, cbox['l'] / 2)
    by = vh - 30
    cdp.wheel(bx, by, 400)
    time.sleep(0.5)
    y1 = cdp.ev('window.pageYOffset')
    kept_top = cdp.ev('document.body.style.top')
    check('在遮罩上滚轮不穿透到时间表', abs((y1 or 0) - (y_locked or 0)) < 2 and kept_top == locked_top,
          '滚动位置从 %s 变成 %s，body.top=%r' % (y_locked, y1, kept_top))
    can_scroll = cdp.ev('(function(){var c=document.querySelector("#setSheet .sheet-card");'
                        'c.scrollTop = 60; return {sh:c.scrollHeight, ch:c.clientHeight, st:c.scrollTop};})()')
    check('设置面板自己还能滚', ((can_scroll or {}).get('st', 0) > 0)
          or ((can_scroll or {}).get('sh', 0) <= (can_scroll or {}).get('ch', 0) + 1),
          '面板被锁住滚不动: %r' % (can_scroll,))

    # ---------- 7. 设置项写入 localStorage + 重开还在 ----------
    cdp.ev('document.getElementById("setBefore").click()')
    cdp.ev('document.getElementById("setStart").click()')
    cdp.ev('(function(){var m=document.getElementById("setMin");m.value="7";'
           'm.dispatchEvent(new Event("change",{bubbles:true}));})()')
    for i in (1, 2, 3):
        cdp.ev('document.querySelectorAll("#setTracks label")[%d].click()' % i)
    time.sleep(0.4)
    cfg = cdp.ev('localStorage.getItem("sqzy-notify")')
    parsed = json.loads(cfg) if cfg else {}
    check('设置立刻写进 localStorage',
          parsed.get('min') == 7 and parsed.get('before') is False and parsed.get('start') is True,
          'localStorage=%r' % cfg)
    check('学院勾选写进 tracks', parsed.get('tracks') == [True, False, False, False],
          'tracks=%r' % parsed.get('tracks'))
    cdp.ev('document.getElementById("setClose").click()')
    time.sleep(0.5)
    print('    · 关面板诊断 %r' % (cdp.ev('({cls:document.documentElement.className,'
                                       'on:document.getElementById("setSheet").className,'
                                       'y:window.pageYOffset})'),))
    check('关面板后解除滚动锁',
          not bools(cdp, 'document.documentElement.classList.contains("sheet-lock")'), 'sheet-lock 还在')
    y2 = cdp.ev('window.pageYOffset')
    check('关面板后回到原位置', abs((y2 or 0) - (y_open or 0)) < 6,
          '开面板前 %s → 关面板后 %s' % (y_open, y2))

    # ---------- 7.1 安卓返回键：有弹窗先关弹窗，不退出 App ----------
    cdp.ev('document.getElementById("setBtn").click()')
    time.sleep(0.3)
    back_close = cdp.ev('(function(){var r=window.SQZY_BACK_CLOSE_SHEET();'
                        'return {r:r,on:document.getElementById("setSheet").classList.contains("on"),'
                        'lock:document.documentElement.classList.contains("sheet-lock")};})()')
    check('返回键优先关弹窗（SQZY_BACK_CLOSE_SHEET）',
          back_close.get('r') is True and back_close.get('on') is False
          and back_close.get('lock') is False,
          '结果=%r' % (back_close,))
    again = cdp.ev('window.SQZY_BACK_CLOSE_SHEET()')
    check('没有弹窗时返回键不再拦截', again is False, '返回值=%r' % (again,))

    cdp.nav(url + '?again=1')
    keep = cdp.ev('(function(){return {min:document.getElementById("setMin").value,'
                  'before:document.getElementById("setBefore").checked,'
                  'start:document.getElementById("setStart").checked,'
                  'tracks:[].slice.call(document.querySelectorAll("#setTracks label"))'
                  '.map(function(l){return !!l.querySelector("input").checked;})};})()')
    check('重开页面设置还在（真的保存了）',
          keep and keep.get('min') == '7' and keep.get('before') is False
          and keep.get('start') is True and keep.get('tracks') == [True, False, False, False],
          '重开后=%r' % (keep,))

    # ---------- 7.5 桌面版专属开关（打桩 fetch 假装自己在 exe 里） ----------
    cdp.ev('''(function(){
      window.__realFetch = window.fetch;
      window.SQZY_API = 'http://127.0.0.1:9';
      window.fetch = function(){ return Promise.resolve({
        json: function(){ return Promise.resolve({ok:true, state:{
          always_on_top:true, close_mode:'exit', autostart:true}}); } }); };
      document.querySelectorAll(".sysToast").forEach(function(e){ e.remove(); });
      window.winInit();
    })()''')
    time.sleep(0.5)
    desk = cdp.ev('(function(){return {'
                  'sec:getComputedStyle(document.getElementById("winSec")).display,'
                  'auto:document.getElementById("setAuto").checked,'
                  'top:document.getElementById("setTop").checked,'
                  'tray:document.getElementById("setCloseTray").checked,'
                  'startup:window.winCtl.startup,'
                  'btn:(document.getElementById("topBtn")||{}).textContent};})()')
    check('桌面版才显示「窗口」分区（含开机自启动）',
          desk.get('sec') != 'none' and desk.get('startup') is True, '桌面区块=%r' % (desk,))
    check('桌面状态回显：自启动 / 置顶 / 直接退出',
          desk.get('auto') is True and desk.get('top') is True and desk.get('tray') is False,
          '回显=%r' % (desk,))
    check('置顶按钮显示「已置顶」', (desk.get('btn') or '').strip() == '已置顶',
          '按钮文字=%r' % desk.get('btn'))
    cdp.ev('document.getElementById("setAuto").click()')
    time.sleep(0.5)
    after = cdp.ev('(function(){return {checked:document.getElementById("setAuto").checked,'
                   'toast:document.querySelectorAll(".sysToast").length,'
                   'txt:(document.querySelector(".sysToast b")||{}).textContent};})()')
    check('exe 说没关掉就如实回显 + 提示（不假装成功）',
          after.get('checked') is True and after.get('toast', 0) > 0, '回显=%r' % (after,))
    print('    · 提示原文: %s' % (after.get('txt') or ''))
    cdp.ev('(function(){window.fetch = window.__realFetch; delete window.SQZY_API; window.winInit();})()')
    time.sleep(0.5)
    back = cdp.ev('(function(){return {ok:window.winCtl.ok,'
                  'sec:getComputedStyle(document.getElementById("winSec")).display};})()')
    check('回到网页版后「窗口」分区又藏起来', back.get('ok') is False and back.get('sec') == 'none',
          '回退后=%r' % (back,))

    # ---------- 7.6 程序本体（exe/apk）版本检查 ----------
    cdp.ev('localStorage.removeItem("sqzy-seen-shell")')
    # 页面会异步去读线上的 version.txt / program.txt，读到后会把夹具结果覆盖掉
    # （线上一直是 v2.2.x，夹具是 v2.1.x，断言就必然失败）——这里把远端读取挡掉，保证可复现
    cdp.ev('window.__realFetch = window.fetch; window.fetch = function(){return new Promise(function(){}); };')

    cdp.ev('window.SQZY_SETSHELL(null)')
    cdp.ev('window.SQZY_APPLYPROGRAM({exe:"v9.9.9", apk:"v9.9.9", tag:"v9.9.9"})')
    time.sleep(0.3)
    web = cdp.ev('document.getElementById("aboutShell").textContent')
    check('网页版没有程序本体，不提示换壳', not (web or '').strip(), '竟然提示了：%r' % (web,))

    cdp.ev('window.SQZY_SETSHELL("v2.1.0")')
    cdp.ev('window.SQZY_APPLYPROGRAM({exe:"v2.1.1", apk:"v2.1.1", tag:"v2.1.1"})')
    time.sleep(0.4)
    stale = cdp.ev('(function(){return {txt:document.getElementById("aboutShell").textContent,'
                   'hi:document.getElementById("aboutShell").className,'
                   'btn:getComputedStyle(document.getElementById("aboutDownload")).display,'
                   'dlg:!!document.getElementById("shDlg"),'
                   'x:!!document.getElementById("shClose"),'
                   'seen:localStorage.getItem("sqzy-seen-shell")};})()')
    check('程序本体落后 → 「关于」里如实写明并给出下载按钮',
          'v2.1.0' in (stale.get('txt') or '') and 'v2.1.1' in (stale.get('txt') or '')
          and stale.get('btn') != 'none' and 'hi' in (stale.get('hi') or ''),
          '关于区=%r' % (stale,))
    check('程序本体落后 → 强制弹窗更新（没有关闭按钮）',
          stale.get('dlg') is True and stale.get('x') is False and stale.get('seen') == 'v2.1.1',
          '弹窗=%r' % (stale,))
    print('    · 关于区原文: %s' % (stale.get('txt') or '')[:64])
    cdp.ev('window.SQZY_CLOSE_SHELL_DIALOG()')
    time.sleep(0.3)
    check('测试钩子能关掉强制弹窗且滚动锁解除',
          not bools(cdp, 'document.documentElement.classList.contains("sheet-lock")'), '还被锁着')
    cdp.ev('window.SQZY_APPLYPROGRAM({exe:"v2.1.1", apk:"v2.1.1", tag:"v2.1.1"})')
    time.sleep(0.3)
    check('同一个旧版本再次检查仍会强制弹窗（直到更新完成）',
          bools(cdp, '!!document.getElementById("shDlg")'), '没有再次弹出')
    cdp.ev('window.SQZY_CLOSE_SHELL_DIALOG()')
    time.sleep(0.3)

    cdp.ev('window.SQZY_SETSHELL("v2.1.1")')
    cdp.ev('window.SQZY_APPLYPROGRAM({exe:"v2.1.1", apk:"v2.1.1", tag:"v2.1.1"})')
    time.sleep(0.3)
    fresh = cdp.ev('(function(){return {txt:document.getElementById("aboutShell").textContent,'
                   'btn:getComputedStyle(document.getElementById("aboutDownload")).display,'
                   'dlg:!!document.getElementById("shDlg")};})()')
    check('程序本体已是最新 → 只报平安、不弹窗、不给下载按钮',
          '最新' in (fresh.get('txt') or '') and fresh.get('btn') == 'none'
          and fresh.get('dlg') is False, '结果=%r' % (fresh,))
    cdp.ev('window.SQZY_SETSHELL(null)')

    cdp.ev('if(window.__realFetch){window.fetch=window.__realFetch;window.__realFetch=null;}')
    # 断言失败也不许把弹层留在页面上（滚动锁会连带毁掉后面的用例）
    cdp.ev('(function(){document.querySelectorAll(".sheet.on .sheet-x").forEach(function(x){x.click();});return document.querySelectorAll(".sheet.on").length;})()')
    time.sleep(0.4)

    # ---------- 7.5 安装包下载：浏览器也要存成 .apk（issue IKHWKA 追问） ----------
    # gitee 附件 CDN 对 apk 固定返回 application/zip（上传时指定 Content-Type 也改不了，实测过），
    # 手机浏览器按 MIME 补后缀就变成 xxx.apk.zip。所以页面改成：支持 CORS 的镜像 fetch 成 blob
    # 后自己指定文件名保存 —— 文件名由页面说了算，与服务器 MIME 无关。
    mir = cdp.ev('window.SQZY_APK.mirrors({tag:"v9.9.9"})')
    ok_mir = (isinstance(mir, list) and len(mir) >= 3
              and all(str(u).startswith('https://') for u in mir)
              and any('jsdelivr' in str(u) for u in mir) and any('ghproxy' in str(u) for u in mir))
    check('镜像下载线路齐全（jsDelivr 三个域名 + ghproxy）', ok_mir, '线路=%r' % (mir,))
    saved = cdp.ev('(function(){'
                   'window.__saved=null;'
                   'var oc=URL.createObjectURL;URL.createObjectURL=function(b){window.__saved={size:b.size};return "blob:x";};'
                   'var ck=HTMLAnchorElement.prototype.click;'
                   'HTMLAnchorElement.prototype.click=function(){window.__saved.name=this.download;};'
                   'window.fetch=function(){return Promise.resolve({ok:true,status:200,'
                   'arrayBuffer:function(){return Promise.resolve(new Uint8Array(150000).buffer);}});};'
                   'try{window.SQZY_APK.smart({tag:"v9.9.9",apkSha256:""});}catch(e){return {err:String(e)};}'
                   'return {soon:true,name:"pending"};})()')
    time.sleep(1.0)
    got = cdp.ev('window.__saved')
    check('浏览器路径下载后文件名以 .apk 结尾（不是 .apk.zip）',
          bool(got) and str(got.get('name', '')).endswith('.apk') and 'v9.9.9' in str(got.get('name')),
          '捕获到的文件名=%r' % (got,))
    check('blob 是真的拿到字节了（不是空壳）', bool(got) and (got.get('size') or 0) >= 100000,
          '字节数=%r' % ((got or {}).get('size'),))
    bridged = cdp.ev('(function(){document.documentElement.setAttribute("data-android","1");'
                     'window.__bridge=null;'
                     'window.SQZY_ANDROID={downloadApk:function(u){window.__bridge=u;return "ok";}};'
                     'try{window.SQZY_APK.smart({tag:"v9.9.9"});}catch(e){}'
                     'var u=window.__bridge;'
                     'delete window.SQZY_ANDROID;'
                     'document.documentElement.removeAttribute("data-android");'
                     'return u;})()')
    check('有原生桥时仍然交给系统下载器（存成 .apk、不会被改名）',
          bool(bridged) and 'gitee.com' in str(bridged), '桥收到=%r' % (bridged,))
    bridged_as = cdp.ev('(function(){document.documentElement.setAttribute("data-android","1");'
                        'window.__bridgeAs=null;'
                        'window.SQZY_ANDROID={downloadApkAs:function(u,v){window.__bridgeAs={u:u,v:v};return "ok";}};'
                        'try{window.SQZY_APK.smart({tag:"v9.9.9",apk:"v9.9.9"});}catch(e){}'
                        'var b=window.__bridgeAs;'
                        'delete window.SQZY_ANDROID;'
                        'document.documentElement.removeAttribute("data-android");'
                        'return b;})()')
    check('安卓桥优先按目标版本命名下载（downloadApkAs 收到目标版本）',
          bool(bridged_as) and 'gitee.com' in str(bridged_as.get('u', '')) and bridged_as.get('v') == 'v9.9.9',
          '桥收到=%r' % (bridged_as,))
    auto_dl = cdp.ev('''(function(){
      document.documentElement.setAttribute("data-android","1");
      window.__auto=null; window.shellAutoDl=false;
      localStorage.removeItem("sqzy-seen-shell");
      window.SQZY_SETSHELL("v2.1.0");
      window.SQZY_ANDROID={
        version:function(){return "2.1.0";},
        downloadApkAs:function(u,v){window.__auto={u:u,v:v};return "ok";}
      };
      window.SQZY_APPLYPROGRAM({exe:"v9.9.9",apk:"v9.9.9",tag:"v9.9.9",
        apkUrl:"https://gitee.com/xyz-225648/sqbwzxsj/releases/download/v9.9.9/x.apk"});
      var a=window.__auto;
      try{closeDialog("shDlg");}catch(e){}
      delete window.SQZY_ANDROID;
      document.documentElement.removeAttribute("data-android");
      return a;
    })()''')
    check('安卓发现新版本后自动开始下载（不用用户点按钮）',
          bool(auto_dl) and 'gitee.com' in str(auto_dl.get('u', '')) and auto_dl.get('v') == 'v9.9.9',
          '自动下载桥收到=%r' % (auto_dl,))

    # ---------- 8. 通知判定（假时钟，可复现） ----------
    def arm_clock(hh, mi, day=21):
        """把页面里的 Date 换成假时钟，并清掉磁盘上的去重表；返回后必须自己再设一遍规则
        （loadCfg 会拿 localStorage 里存的设置覆盖内存里的设置）。
        注意：内存里的 firedKeys 清不掉（没暴露），所以换一天来测，顺带验证跨天会清旧记录。"""
        return ('''(function(){
          var R = window.__RealDate || Date, fixed = new R(2026, 8, %d, %d, %d, 0);
          function Fake(){
            if (!arguments.length) return fixed;
            return new R(arguments[0], arguments[1], arguments[2], arguments[3],
                         arguments[4], arguments[5]);
          }
          Fake.now = function(){ return fixed.getTime(); };
          window.Date = Fake; window.__RealDate = R;
          localStorage.removeItem("sqzy-notify-fired");
          if (window.loadCfg) window.loadCfg();
          var c = window.SQZY_CFG;
          c.on = true; c.before = true; c.start = false; c.next = false; c.end = false;
          c.tracks = [true, false, false, false];
          document.querySelectorAll(".sysToast").forEach(function(e){ e.remove(); });
        })()''' % (day, hh, mi))

    # 先把假钟设到 2026-09-21（周一），再等页面按这个日期重新解析作息。
    # 页面缓存的是"今天"的模板（_curDay），今天要是周末/节假日，不重解析就跟假的周一对不上：
    # 下面探到的"下课前 N 分钟"会落在休息段，通知永远不触发 —— 闸门会在节假日/周末误报。
    # 重解析有两条现成的路：20 秒的 setInterval，和 visibilitychange（同一条 rerenderSchedule）。
    cdp.ev(arm_clock(0, 0))
    flipped = False
    for _ in range(40):
        cdp.ev('document.dispatchEvent(new Event("visibilitychange"))')
        time.sleep(0.3)
        if cdp.ev('''(function(){var g = window.SQZY_SEGAT && window.SQZY_SEGAT(0, 600);
                     return !!(g && ['gap','noon','eve','free'].indexOf(g.cat) < 0);})()'''):
            flipped = True
            break
    print('    · 假钟重解析作息: %s（10:00 处 %s）'
          % ('已切到周内模板' if flipped else '没切过去，下面的判定可能不准', '有正课' if flipped else '仍是休息'))

    probe = cdp.ev('''(function(){
      var seg = window.SQZY_SEGAT, cfg = window.SQZY_CFG;
      var skip = ['gap','noon','eve','free'];
      for (var m = 0; m < 1440; m++){
        var g = seg(0, m);
        if (g && skip.indexOf(g.cat) < 0 && g.e - m === cfg.min) return m;
      }
      return -1;
    })()''')
    if probe is None or probe < 0:
        bad('通知判定：找得到可触发的时刻', '没找到「下课前 N 分钟」的时刻')
    else:
        print('    · 假时钟设到 %02d:%02d（第 1 个学院下课前 %d 分钟）'
              % (probe // 60, probe % 60, cdp.ev('window.SQZY_CFG.min')))
        cdp.ev(arm_clock(probe // 60, probe % 60))
        cdp.ev('window.SQZY_CHECKNOTIFY()')
        time.sleep(0.4)
        fired = cdp.ev('localStorage.getItem("sqzy-notify-fired")') or '{}'
        keys = list(json.loads(fired).keys())
        want = '2026-9-21|0|%d|before' % probe
        mine = [k for k in keys if k.split('|')[1] == '0']
        others = [k for k in keys if k.split('|')[1] != '0']
        check('只勾选的学院才会收到提醒', bool(mine) and not others, '全部触发键=%r' % (keys,))
        check('提醒去重键 = 日期|学院|分钟|类型', keys == [want],
              '触发键=%r（应为 %s）' % (keys, want))
        cdp.ev('window.SQZY_CHECKNOTIFY()')
        time.sleep(0.3)
        again = json.loads(cdp.ev('localStorage.getItem("sqzy-notify-fired")') or '{}')
        check('同一分钟不会重复提醒', list(again.keys()) == [want], '重复提醒了：%r' % (again,))
        check('触发提醒时页面内有提示',
              bools(cdp, 'document.querySelectorAll(".sysToast").length > 0'), '没有 .sysToast')
        want2 = '2026-9-22|0|%d|before' % probe
        cdp.ev(arm_clock((probe + 1) // 60, (probe + 1) % 60, 22))
        cdp.ev('window.SQZY_CHECKNOTIFY()')
        time.sleep(0.3)
        late = list(json.loads(cdp.ev('localStorage.getItem("sqzy-notify-fired")') or '{}').keys())
        check('整分钟被跳过时会补发上一分钟的提醒', late == [want2],
              '补发键=%r（应为 %s）' % (late, want2))
        check('换天后旧的去重记录被清掉', want not in late, '还留着昨天的键：%r' % (late,))
        cdp.ev('(function(){ if (window.__RealDate) window.Date = window.__RealDate; })()')

    # ---------- 9.4 检查更新在网页版/安卓版真的能读到版本（issue IKHWKA #1） ----------
    cdp.ev('document.getElementById("aboutNote").textContent = ""')
    cdp.ev('window.applyUpdateInfo(null, false)')
    cdp.ev('window.checkAppUpdate(true)')
    time.sleep(8)
    note = cdp.ev('document.getElementById("aboutNote").textContent')
    check('网页版能读到版本信息（不再被 nosniff/CORS 卡死）', bool((note or '').strip()),
          '关于区还是空的 —— 说明版本文件没读到（可能又用回 <script src> 了）')
    print('    · 关于区原文: %s' % (note or '')[:64])
    check('页面没有用 <script src> 加载 version/program 文件',
          bools(cdp, 'document.querySelectorAll("script[src*=\'version\'],script[src*=\'program\']").length === 0'),
          '又出现 script src 了')

    # 安卓路径：走原生桥 fetchUrl（不受 MIME/CORS 限制）
    cdp.ev('''(function(){
      window.__got = null;
      window.SQZY_ANDROID = {
        version: function(){ return '2.1.0'; },
        fetchUrl: function(u){ window.__got = u;
          return 'window.SQZY_LATEST={"v":"v9.9.9","h":"x","t":"2026-09-22 20:00"};'; }
      };
      document.getElementById("aboutNote").textContent = "";
      window.applyUpdateInfo(null, false);
      window.checkAppUpdate(false);
    })()''')
    time.sleep(1.5)
    via = cdp.ev('(function(){return {url: window.__got,'
                 ' note: document.getElementById("aboutNote").textContent,'
                 ' latest: !!window.latestInfo};})()')
    check('安卓版走原生桥读版本（命令行里带 gitee raw 地址）',
          bool(via.get('url')) and 'gitee.com' in (via.get('url') or ''),
          '没走桥：%r' % (via,))
    check('桥回来的版本被页面采纳', via.get('latest') is True, '页面没拿到版本：%r' % (via,))
    cdp.ev('delete window.SQZY_ANDROID')

    # ---------- 9. 更新弹窗 ----------
    cdp.ev('window.applyUpdateInfo({v:"v9.9.9", t:"2026-01-01 00:00"}, true)')
    time.sleep(0.4)
    check('发现大版本更新时弹窗', bools(cdp, '!!document.getElementById("upDlg")'), '没有弹窗')
    # 直链放在 data-url 里、href 故意留 javascript:void 0（v2.3.2 起）：
    # gitee 附件 CDN 对 apk 返回 application/zip，手机浏览器按 href 直链下就存成 .apk.zip，
    # 所以点击改成走 JS（安卓交原生桥 getApkSmart / 桌面走一键更新）。
    dl = cdp.ev('(function(){var a=document.querySelector("#upDlg a");'
                'return a?{url:a.getAttribute("data-url")||"",href:a.href||"",'
                'txt:a.textContent||"",wired:!!a.onclick}:null;})()') or {}
    check('弹窗里的下载按钮指向发行版附件（.apk 直链）',
          'releases/download/' in dl.get('url', '') and dl.get('url', '').endswith('.apk'),
          'data-url=%r' % dl.get('url'))
    check('桌面版不把直链放在 href（免得被存成 zip），点击交给 JS',
          dl.get('href') == 'javascript:void 0' and dl.get('wired') is True
          and ('发行版' in dl.get('txt', '') or dl.get('txt', '').startswith('一键更新')),
          'href=%r 文字=%r' % (dl.get('href'), dl.get('txt')))
    cdp.ev('document.querySelector("#upDlg .sheet-x").click()')
    time.sleep(0.4)
    check('弹窗能关掉', not bools(cdp, '!!document.getElementById("upDlg")'), '弹窗还在')
    check('关掉弹窗后滚动锁也解除',
          not bools(cdp, 'document.documentElement.classList.contains("sheet-lock")'), 'sheet-lock 还在')
    cdp.ev('window.applyUpdateInfo({v:"v9.9.9", t:""}, false)')
    time.sleep(0.3)
    check('同一个新版本只弹一次（不再打扰）',
          not bools(cdp, '!!document.getElementById("upDlg")'), '又弹了一次')
    cdp.ev('window.applyUpdateInfo(null, true)')
    time.sleep(0.4)
    check('查不到版本时给提示而不是没反应',
          bools(cdp, 'document.querySelectorAll(".sysToast").length > 0'), '没有提示')

    # ---------- 10. 发测试通知这个按钮 ----------
    check('前面的弹层都关干净了（没有残留滚动锁）',
          not bools(cdp, 'document.documentElement.classList.contains("sheet-lock")'), '滚动锁没释放')
    cdp.ev('window.scrollTo(0,0)')
    cdp.ev('document.getElementById("setBtn").click()')
    time.sleep(0.4)
    cdp.ev('document.getElementById("setTest").click()')
    time.sleep(0.5)
    note = cdp.ev('document.getElementById("setNote").textContent')
    check('发测试通知后有明确反馈', bool(note) and len(note) > 4, 'setNote=%r' % note)
    if note and '系统通知中心' in note and '网页版' in (cdp.ev(
            '(function(){return document.getElementById("setNote").textContent;})()') or ''):
        pass
    print('    · 提示原文: %s' % (note or '')[:70])
    cdp.ev('document.getElementById("setClose").click()')
    time.sleep(0.4)
    check('关掉设置面板后滚动锁释放',
          not bools(cdp, 'document.documentElement.classList.contains("sheet-lock")'), '还被锁着')

    # ---------- 11. Ctrl+滚轮缩放 ----------
    cdp.wheel(640, 300, -120, ctrl=True)
    time.sleep(0.5)
    z = cdp.ev('document.documentElement.style.zoom')
    check('Ctrl+滚轮放大生效', z not in (None, '', '1'), 'zoom=%r' % z)
    zs = cdp.ev('localStorage.getItem("sqzy-zoom")')
    check('缩放比例被记住', zs == z, 'localStorage=%r style=%r' % (zs, z))
    cdp.ev('document.dispatchEvent(new KeyboardEvent("keydown",{key:"0",code:"Digit0",ctrlKey:true,bubbles:true,cancelable:true}))')
    time.sleep(0.4)
    check('Ctrl+0 恢复 100%', cdp.ev('document.documentElement.style.zoom') == '1',
          'zoom=%r' % cdp.ev('document.documentElement.style.zoom'))
    cdp.ev('window.SQZY_SETZOOM(1)')
    time.sleep(0.3)

    # ---------- 12. 防右键 / 防调试 / 禁复制 ----------
    probes = [
        ('右键菜单被拦截',
         'document.body.dispatchEvent(new MouseEvent("contextmenu",{bubbles:true,cancelable:true}))'),
        ('F12 被拦截',
         'document.body.dispatchEvent(new KeyboardEvent("keydown",{key:"F12",keyCode:123,bubbles:true,cancelable:true}))'),
        ('Ctrl+Shift+I 被拦截',
         'document.body.dispatchEvent(new KeyboardEvent("keydown",{key:"I",ctrlKey:true,shiftKey:true,bubbles:true,cancelable:true}))'),
        ('Ctrl+Shift+J 被拦截',
         'document.body.dispatchEvent(new KeyboardEvent("keydown",{key:"J",ctrlKey:true,shiftKey:true,bubbles:true,cancelable:true}))'),
        ('Ctrl+U 被拦截',
         'document.body.dispatchEvent(new KeyboardEvent("keydown",{key:"u",ctrlKey:true,bubbles:true,cancelable:true}))'),
        ('Ctrl+S 被拦截',
         'document.body.dispatchEvent(new KeyboardEvent("keydown",{key:"s",ctrlKey:true,bubbles:true,cancelable:true}))'),
        ('复制被拦截',
         'document.body.dispatchEvent(new Event("copy",{bubbles:true,cancelable:true}))'),
        ('剪切被拦截',
         'document.body.dispatchEvent(new Event("cut",{bubbles:true,cancelable:true}))'),
        ('拖拽选字被拦截',
         'document.body.dispatchEvent(new Event("selectstart",{bubbles:true,cancelable:true}))'),
    ]
    for label, code in probes:
        r = cdp.ev('(function(){var r = %s; return r === false;})()' % code)
        check(label, r is True, '事件没有被拦下')

    # ---------- 13. 手机版竖排点按 ----------
    cdp.send('Emulation.setDeviceMetricsOverride',
             {'width': 420, 'height': 900, 'deviceScaleFactor': 1, 'mobile': True})
    cdp.ev('window.SQTC.applyDevice("mobile")')
    time.sleep(0.9)
    cdp.ev('document.getElementById("vtWrap").scrollIntoView({block:"start"})')
    time.sleep(0.8)
    vbox = cdp.ev('(function(){var r=document.getElementById("vtPlot").getBoundingClientRect();'
                  'return {x:r.left+r.width/2, top:r.top, h:r.height,'
                  ' lock:document.documentElement.classList.contains("sheet-lock"),'
                  ' y:window.pageYOffset};})()')
    print('    · 竖排时间轴 top=%.0f h=%.0f 锁=%s scrollY=%s'
          % (vbox['top'], vbox['h'], vbox['lock'], vbox['y']))
    if not vbox or vbox['h'] < 10:
        bad('手机版竖排点按钉住', 'vtPlot 没有高度')
    else:
        target_y = max(40.0, min(860.0, vbox['top'] + vbox['h'] * 0.25))
        print('    · 手机版点按落点 y=%.0f（vtPlot top=%.0f h=%.0f）'
              % (target_y, vbox['top'], vbox['h']))
        cdp.click_at(vbox['x'], target_y)
        time.sleep(0.5)
        check('手机版点一下能钉住时刻',
              bools(cdp, 'document.getElementById("vtGuide").classList.contains("on")'), 'vt-guide 没亮')
        uid = cdp.ev('(function(){var f=document.querySelector("#vtGuide .vt-flag");'
                     'return f?f.textContent:"";})()')
        check('手机版钉住显示时刻', bool(re.search(r'\d{2}:\d{2}', uid or '')), '气泡=%r' % uid)
        cdp.esc()
        time.sleep(0.4)
        check('手机版 Esc 能取消钉住',
              not bools(cdp, 'document.getElementById("vtGuide").classList.contains("on")'), '还在钉着')
        # 竖版表头点学院名：renderVertical() 重绘格子后也要还能跳（同 v2.3.14 的事件委托修复）
        cdp.ev('document.querySelectorAll("#vtHeads .vt-head-cell")[0].click()')
        time.sleep(0.5)
        check('手机版点学院名也能跳到卡片并高亮',
              bools(cdp, '!!document.querySelector("#cards .card.flash")'), '竖版表头没反应')
    cdp.send('Emulation.clearDeviceMetricsOverride')


def main():
    exe = find_browser()
    if not exe:
        # P4：找不到浏览器必须报错退出，不能 return 0（那是"通过"的返回码，闸门会空转）
        print('  ✗ 找不到 Edge / Chrome / Chromium，交互闸门无法执行 —— 不静默放行')
        return 2
    here = os.path.dirname(PAGE)
    port = free_port()
    srv = ThreadingHTTPServer((HOST, port), partial(SilentHandler, directory=here))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = 'http://%s:%d/%s' % (HOST, port, quote(os.path.basename(PAGE)))
    dbg = free_port()
    prof = tempfile.mkdtemp(prefix='sqzy_func_')
    blog = open(os.path.join(tempfile.gettempdir(), 'sqzy_func_browser.log'), 'wb')
    proc = subprocess.Popen([exe, '--headless=new', '--disable-gpu', '--no-first-run',
                             '--no-default-browser-check', '--disable-extensions', '--disable-sync',
                             '--disable-background-networking',
                             '--user-data-dir=' + prof, '--window-size=%d,%d' % (VIEW_W, VIEW_H),
                             '--remote-debugging-port=%d' % dbg, url],
                            stdout=blog, stderr=blog)
    cdp = None
    try:
        import urllib.request
        ws_url = None
        end = time.time() + 40
        while time.time() < end and not ws_url:
            try:
                with urllib.request.urlopen('http://127.0.0.1:%d/json/list' % dbg, timeout=3) as r:
                    tabs = json.loads(r.read().decode('utf-8'))
                for tb in tabs:
                    if tb.get('type') == 'page' and tb.get('webSocketDebuggerUrl'):
                        ws_url = tb['webSocketDebuggerUrl']
                        break
            except Exception:
                pass
            if not ws_url:
                time.sleep(0.4)
        if not ws_url:
            # P4：浏览器起来了却连不上调试端口，同样是"闸门没跑"，不能当成通过（返回码 2）
            print('  ✗ 浏览器起来了但连不上调试端口（%d）—— 交互闸门没有执行，不静默放行' % dbg)
            try:
                proc.kill()
            except Exception:
                pass
            return 2
        cdp = CDP(ws_url)
        cdp.send('Runtime.enable')
        cdp.send('Log.enable')
        cdp.send('Page.enable')
        print('  [交互遍历] %s' % url)
        cdp.nav(url + '?fresh=1')
        run_all(cdp, url, VIEW_W, VIEW_H)
    except Exception as exc:
        alive = proc.poll()
        extra = '（浏览器进程 %s，最后一条命令 %s）' % (
            '已退出，返回码 %s' % alive if alive is not None else '仍在运行',
            getattr(cdp, 'last', '?'))
        bad('交互测试中断', '%s: %s %s' % (type(exc).__name__, str(exc)[:160], extra))
    finally:
        if cdp:
            cdp.close()
        try:
            proc.terminate()
            proc.wait(timeout=10)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        try:
            blog.close()
        except Exception:
            pass
        srv.shutdown()
        shutil.rmtree(prof, ignore_errors=True)

    print('  交互遍历: %s（通过 %d 项）' % ('PASS' if not failed else 'FAIL', len(passed)))
    for x in failed:
        print('    ✗ ' + x)
    return 1 if failed else 0


sys.exit(main())