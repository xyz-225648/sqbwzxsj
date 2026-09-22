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
]
PAGE = sys.argv[1] if len(sys.argv) > 1 else '宿迁职业技术学院作息时间表.html'
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
    t = time.localtime()
    in_band = 8 * 60 <= t.tm_hour * 60 + t.tm_min <= 21 * 60 + 35
    if in_band:
        check('上课时段倒计时已渲染', n_cd >= 4, '倒计时只有 %s 条' % n_cd)
    else:
        print('    · 当前 %02d:%02d 不在 08:00–21:35，跳过倒计时断言' % (t.tm_hour, t.tm_min))

    # ---------- 2. 横竖版切换 ----------
    cdp.ev('window.SQTC.applyDevice("mobile")')
    time.sleep(0.7)
    dev = cdp.ev('document.documentElement.getAttribute("data-device")')
    check('切成手机版：data-device=mobile', dev == 'mobile', 'data-device=%s' % dev)
    check('手机版显示竖排时间轴',
          bools(cdp, 'getComputedStyle(document.getElementById("vtWrap")).display !== "none"'),
          '竖排时间轴仍隐藏')
    n_blk = bools(cdp, 'document.querySelectorAll("#vtPlot .vt-blk").length')
    check('竖排时间轴 52 个节块', n_blk == 52, '实际 %s 个' % n_blk)
    cdp.ev('window.SQTC.applyDevice("desktop")')
    time.sleep(0.7)
    check('切回桌面版', cdp.ev('document.documentElement.getAttribute("data-device")') == 'desktop',
          '没切回来')

    # ---------- 3. 悬停预览轴 / 钉住 ----------
    cdp.ev('window.scrollTo(0,0)')
    cdp.ev('document.getElementById("gGrid").scrollIntoView({block:"center"})')
    time.sleep(0.5)
    box = cdp.ev('(function(){var ar=document.querySelectorAll("#gGrid .g-lane .g-area")[1];'
                 'if(!ar) ar=document.querySelectorAll("#gGrid .g-lane")[1];'
                 'var b=ar.getBoundingClientRect();'
                 'return {x:b.left+b.width*0.45, y:Math.min(' + str(vh - 60) + ', b.top+b.height*0.5)};})()')
    print('    · 悬停落点 x=%.0f y=%.0f' % (box['x'], box['y']))
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
    cdp.ev('window.scrollTo(0,0)')
    time.sleep(0.2)
    cdp.ev('document.querySelectorAll("#gGrid .g-lane .g-name")[1].click()')
    time.sleep(0.5)
    check('点学院名跳到对应卡片并高亮',
          bools(cdp, '!!document.querySelector("#cards .card.flash")'), '卡片没有 flash')

    # ---------- 5. 回到顶部 ----------
    cdp.ev('window.scrollTo(0, 1200)')
    time.sleep(0.6)
    check('滚动后「回到顶部」按钮出现',
          bools(cdp, 'document.getElementById("toTop").classList.contains("on")'), '按钮没亮')
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
    check('关面板后解除滚动锁',
          not bools(cdp, 'document.documentElement.classList.contains("sheet-lock")'), 'sheet-lock 还在')
    y2 = cdp.ev('window.pageYOffset')
    check('关面板后回到原位置', abs((y2 or 0) - (y_open or 0)) < 6,
          '开面板前 %s → 关面板后 %s' % (y_open, y2))

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
                   'seen:localStorage.getItem("sqzy-seen-shell")};})()')
    check('程序本体落后 → 「关于」里如实写明并给出下载按钮',
          'v2.1.0' in (stale.get('txt') or '') and 'v2.1.1' in (stale.get('txt') or '')
          and stale.get('btn') != 'none' and 'hi' in (stale.get('hi') or ''),
          '关于区=%r' % (stale,))
    check('程序本体落后 → 弹一次性提示（并记住已提示）',
          stale.get('dlg') is True and stale.get('seen') == 'v2.1.1', '弹窗=%r' % (stale,))
    print('    · 关于区原文: %s' % (stale.get('txt') or '')[:64])
    cdp.ev('(function(){var d=document.getElementById("shClose"); if (d) d.click();})()')
    time.sleep(0.3)
    check('关掉提示后滚动锁也解除',
          not bools(cdp, 'document.documentElement.classList.contains("sheet-lock")'), '还被锁着')
    cdp.ev('window.SQZY_APPLYPROGRAM({exe:"v2.1.1", apk:"v2.1.1", tag:"v2.1.1"})')
    time.sleep(0.3)
    check('同一个新版本只弹一次（不再打扰）',
          not bools(cdp, '!!document.getElementById("shDlg")'), '又弹了一次')

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

    probe = cdp.ev('''(function(){
      var seg = window.SQZY_SEGAT, cfg = window.SQZY_CFG;
      var skip = ['gap','noon','eve'];
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

    # ---------- 9. 更新弹窗 ----------
    cdp.ev('window.applyUpdateInfo({v:"v9.9.9", t:"2026-01-01 00:00"}, true)')
    time.sleep(0.4)
    check('发现大版本更新时弹窗', bools(cdp, '!!document.getElementById("upDlg")'), '没有弹窗')
    href = cdp.ev('(function(){var a=document.querySelector("#upDlg a");return a?a.href:"";})()')
    check('弹窗里有安卓下载链接', bool(href) and 'releases/download/' in href, 'href=%r' % href)
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
    cdp.send('Emulation.clearDeviceMetricsOverride')


def main():
    exe = find_browser()
    if not exe:
        print('  ⚠ 没找到 Edge/Chrome，跳过交互测试')
        return 0
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
            print('  ⚠ 连不上浏览器调试端口，跳过交互测试')
            return 0
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