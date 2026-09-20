# -*- coding: utf-8 -*-
"""
宿迁职业技术学院作息时间表 —— 桌面版

用 Windows 的 WebView2(Edge 内核) 显示网页，窗口可自由缩放；
窗口变窄时页面会自动切换成竖排时间轴。

自动更新：启动先显示本地版本，后台悄悄去码云检查，有新版本静默热替换。

网页 <-> exe 的通道：exe 起一个只监听 127.0.0.1 的小 HTTP 服务（独立助手进程），
网页用 fetch 调。不用 pywebview 的 js_api —— 本机 WebView2 与 .NET 版本不匹配时
window.pywebview.api 整个暴露不出来（实测踩过）。
"""
import base64
import http.server
import json
import os
import re
import socket
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import urllib.parse
import urllib.request

import webview

HTML_NAME = '宿迁职业技术学院作息时间表.html'
APP_TITLE = '宿迁职业技术学院作息时间表'
WEBVIEW2_GUID = '{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}'

UPDATE_BASE = 'https://gitee.com/xyz-225648/sqbwzxsj/raw/master/'
FETCH_TIMEOUT = 8
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
VALID_MARKERS = ('宿迁职业技术学院作息时间表', '<html')
MIN_HTML = 5000


# ==================== 基础工具 ====================
def base_dir():
    return getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))


def cache_dir():
    d = os.path.join(os.environ.get('LOCALAPPDATA') or tempfile.gettempdir(), APP_TITLE)
    try:
        os.makedirs(d, exist_ok=True)
    except Exception:
        pass
    return d


def read_text(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception:
        return None


def write_text(path, text):
    """落盘必须按字节写（newline=''）：文本模式在 Windows 上会把 \n 自动转成 \r\n，
    缓存下来的页面就跟仓库里发布的那一份不一样了（实测差了一千多个字节）。"""
    try:
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8', newline='') as f:
            f.write(text)
        os.replace(tmp, path)
        return True
    except Exception:
        return False


def read_embedded():
    with open(os.path.join(base_dir(), HTML_NAME), 'r', encoding='utf-8') as f:
        return f.read()


def is_valid(html):
    return bool(html) and len(html) >= MIN_HTML and all(m in html for m in VALID_MARKERS)


def load_current_html():
    cached = read_text(os.path.join(cache_dir(), 'index.html'))
    if is_valid(cached):
        return cached
    return read_embedded()


def http_text(url):
    req = urllib.request.Request(url, headers={
        'User-Agent': UA, 'Cache-Control': 'no-cache', 'Pragma': 'no-cache'})
    with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as resp:
        return resp.read().decode('utf-8', 'replace')


def api_log(text, level='info'):
    """分级日志：info / warn / error，带时间戳。网页侧看不到 exe 的运行情况，全靠它。"""
    try:
        path = os.path.join(cache_dir(), 'api.log')
        line = '%s [%-5s] %s' % (time.strftime('%H:%M:%S'), level, text)
        with open(path, 'a', encoding='utf-8') as f:
            f.write(line + chr(10))
        if os.path.getsize(path) > 40000:
            with open(path, 'r', encoding='utf-8') as f:
                tail = f.readlines()[-200:]
            with open(path, 'w', encoding='utf-8') as f:
                f.writelines(tail)
    except Exception:
        pass


# ==================== 自动更新 ====================
def base_candidates():
    b = UPDATE_BASE if UPDATE_BASE.endswith('/') else UPDATE_BASE + '/'
    out = [b]
    if '/master/' in b:
        out.append(b.replace('/master/', '/main/'))
    elif '/main/' in b:
        out.append(b.replace('/main/', '/master/'))
    return out


def _try_base(base):
    try:
        lines = http_text(base + 'version.txt').strip().splitlines()
        remote_ver = lines[0].strip() if lines else ''
        if not remote_ver:
            return None, None
        local_ver = (read_text(os.path.join(cache_dir(), 'version.txt')) or '').strip()
        if remote_ver == local_ver:
            return None, None
        html = http_text(base + 'index.html')
        if not is_valid(html):
            return None, None
        write_text(os.path.join(cache_dir(), 'index.html'), html)
        write_text(os.path.join(cache_dir(), 'version.txt'), remote_ver)
        return html, remote_ver
    except Exception:
        return None, None


def check_update():
    if not UPDATE_BASE:
        return None, None
    for base in base_candidates():
        html, ver = _try_base(base)
        if html:
            return html, ver
    return None, None


def wait_window_ready(window, timeout=20.0):
    """等 webview.start() 把窗口建出来。
    在那之前 window.gui 还是 None，load_url() 直接 AttributeError ——
    页面已经写进缓存了，但这一次换不上，用户要等到下次打开才看到新版。"""
    end = time.time() + timeout
    while time.time() < end:
        if getattr(window, 'gui', None) is not None:
            return True
        time.sleep(0.2)
    return False


def silent_update(window):
    html, ver = check_update()
    if not html:
        return
    if not wait_window_ready(window):
        api_log('窗口还没建好，新版本 %s 留到下次打开再生效' % ver, 'warn')
        return
    try:
        # 走 http 重新加载，保持同一个 origin，设置不会因为换页而丢
        if _PORT[0]:
            window.load_url('http://127.0.0.1:%d/?v=%d' % (_PORT[0], int(time.time())))
        else:
            window.load_html(with_api(html))
        api_log('已热替换到新版本 %s' % ver)
    except Exception as exc:
        api_log('热替换失败 %r' % (exc,), 'error')


# ==================== Windows 原生通知 ====================
_TOAST_PS = r"""
$ErrorActionPreference = "Stop"
[void][Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType=WindowsRuntime]
[void][Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType=WindowsRuntime]
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml(@"
<toast duration="long"><visual><binding template="ToastGeneric">__ICONIMG__<text>__TITLE__</text><text>__BODY__</text></binding></visual></toast>
"@)
$t = New-Object Windows.UI.Notifications.ToastNotification $xml
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("__APPID__").Show($t)
"""


def _ensure_appid():
    try:
        import winreg
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER,
                              'Software\\Classes\\AppUserModelId\\' + APP_TITLE) as k:
            winreg.SetValueEx(k, 'DisplayName', 0, winreg.REG_SZ, APP_TITLE)
        return True
    except Exception:
        return False


def _xml_escape(text):
    return (str(text).replace('&', '&amp;').replace('<', '&lt;')
            .replace('>', '&gt;').replace('"', '&quot;'))[:180]


def toast_icon_uri():
    """通知左侧的校徽图标：从页面里抠出那张内嵌 PNG，落到纯英文的临时目录，
    返回 file:/// 形式（百分号编码，避免中文路径把 toast 的图片解析搞挂）。
    取不到图标就返回空串，通知照发，只是没有图标。"""
    try:
        p = os.path.join(tempfile.gettempdir(), 'sqzy_toast_icon.png')
        if not (os.path.exists(p) and os.path.getsize(p) > 200):
            html = load_current_html() or ''
            m = re.search(r'data:image/png;base64,([A-Za-z0-9+/=]+)', html)
            if not m:
                return ''
            raw = base64.b64decode(m.group(1))
            if len(raw) < 200 or raw[:8] != b'\x89PNG\r\n\x1a\n':
                return ''
            with open(p, 'wb') as fp:
                fp.write(raw)
        return 'file:///' + urllib.parse.quote(p.replace('\\', '/'), safe='/:')
    except Exception as exc:
        api_log('取通知图标失败 %r' % (exc,), 'warn')
        return ''


def notify_windows(title, body):
    """不阻塞地发一条 Windows 原生通知，失败返回 False"""
    if not sys.platform.startswith('win'):
        return False
    try:
        _ensure_appid()
        icon = toast_icon_uri()
        img = ('<image placement="appLogoOverride" hint-crop="circle" src="%s"/>'
               % _xml_escape(icon)) if icon else ''
        ps = (_TOAST_PS
              .replace('__ICONIMG__', img)
              .replace('__TITLE__', _xml_escape(title))
              .replace('__BODY__', _xml_escape(body))
              .replace('__APPID__', APP_TITLE.replace('"', '')))
        enc = base64.b64encode(ps.encode('utf-16-le')).decode('ascii')
        subprocess.Popen(
            ['powershell', '-NoProfile', '-NonInteractive', '-WindowStyle', 'Hidden',
             '-EncodedCommand', enc],
            creationflags=0x08000000,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception as exc:
        api_log('notify_windows 失败 %r' % (exc,), 'error')
        api_log(traceback.format_exc().replace(chr(10), ' | '), 'error')
        return False


# ==================== 网页 <-> exe 的本地接口 ====================
_PORT = [0]
_HELPER = []


def stop_helper():
    """退出前请助手进程自己走（正常退出，它才能清掉自己的临时目录）"""
    if _PORT[0] and _HELPER:
        try:
            urllib.request.urlopen('http://127.0.0.1:%d/quit' % _PORT[0], timeout=1).read()
        except Exception:
            pass
    for proc in list(_HELPER):
        try:
            if proc.poll() is None:
                try:
                    proc.wait(timeout=2)
                except Exception:
                    proc.terminate()
                    try:
                        proc.wait(timeout=2)
                    except Exception:
                        proc.kill()
        except Exception:
            pass
    _HELPER[:] = []


class _ApiHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _reply(self, obj):
        try:
            body = json.dumps(obj, ensure_ascii=False).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception as exc:
            api_log('reply 失败 %r' % (exc,), 'warn')

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        # 不加访问令牌。曾经加过，代价是老版本缓存页不带令牌就被拒绝，
        # 直接导致「检查更新失败」和「通知发不出去」两次线上故障；
        # 而它挡住的只是「同机网页可能伪造一条通知」，收益远小于代价。
        # 真正的防护是：只监听 127.0.0.1 + 随机端口。
        if u.path in ('/', '/index.html'):
            # 页面走 http 打开，而不是 pywebview 的 html= 直塞：
            # 直塞出来的文档 origin 是 opaque，localStorage 直接抛 SecurityError，
            # 表现就是「设置改完不保存」。给它一个真实 origin 即可。
            body = with_api(load_current_html()).encode('utf-8')
            try:
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except Exception as exc:
                api_log('首页回包失败 %r' % (exc,), 'warn')
            return
        if u.path == '/state':
            # 窗口状态信箱：网页在这里读/写「置顶、关闭方式、恢复显示」
            if any(k in q for k in ('top', 'close', 'show')):
                kw = {}
                if 'top' in q:
                    kw['always_on_top'] = q['top'][0] not in ('0', 'false', 'off', '')
                if 'close' in q:
                    kw['close_mode'] = q['close'][0]
                if 'show' in q:
                    kw['show'] = int(time.time() * 1000)
                st = write_win_state(**kw)
                api_log('窗口状态更新 -> %r' % (st,))
            else:
                st = read_win_state()
            return self._reply({'ok': True, 'state': st})
        if u.path == '/ping':
            return self._reply({'ok': True, 'native': True, 'name': APP_TITLE})
        if u.path == '/quit':
            self._reply({'ok': True})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            api_log('收到 /quit，助手准备退出')
            return
        if u.path == '/latest':
            info = None
            if UPDATE_BASE:
                for base in base_candidates():
                    # version.txt 的 CDN 缓存偶尔会慢一拍，重试两次再放弃
                    for attempt in range(3):
                        try:
                            txt = http_text(base + 'version.txt?t=%d' % int(time.time()))
                            m = re.search(r'\{.*\}', txt, re.S)
                            if m:
                                info = json.loads(m.group(0))
                                break
                        except Exception as exc:
                            api_log('latest 第%d次失败 %r' % (attempt + 1, exc), 'warn')
                            time.sleep(1)
                    if info:
                        break
            api_log('latest -> %r' % (info,))
            return self._reply({'ok': bool(info), 'latest': info})
        if u.path == '/notify':
            title = q.get('title', [''])[0][:80]
            body = q.get('body', [''])[0][:180]
            ok = notify_windows(title, body)
            api_log('notify(%r) -> %r' % (title, ok))
            return self._reply({'ok': ok})
        return self._reply({'ok': False, 'err': 'unknown'})


def port_free(p):
    try:
        sk = socket.socket()
        sk.bind(('127.0.0.1', p))
        sk.close()
        return True
    except Exception:
        return False


def pick_free_port():
    """端口优先固定：页面改用 http://127.0.0.1:端口 打开，而端口是 origin 的一部分，
    端口一变 localStorage（也就是「设置」）就相当于换了一份，设置又会「丢」。"""
    for p in (51900, 51901, 51902, 51903, 51904):
        if port_free(p):
            return p
    try:
        sk = socket.socket()
        sk.bind(('127.0.0.1', 0))
        p = sk.getsockname()[1]
        sk.close()
        return p
    except Exception:
        return 0


def run_api_server(port):
    """助手进程里跑这个：独立进程不受 pywebview 消息循环影响"""
    # 助手自己也要知道自己在哪个端口：它负责把页面用 http 发给窗口，
    # 而页面靠注入的 window.SQZY_API 才能认出「这是桌面版」并走系统通知。
    # 不设这个值 → 注入被跳过 → 页面以为自己在浏览器里，通知全落到页面内提示。
    _PORT[0] = port
    try:
        srv = socketserver.ThreadingTCPServer(('127.0.0.1', port), _ApiHandler)
        srv.daemon_threads = True
        srv.allow_reuse_address = True
        api_log('助手进程开始服务 端口=%d' % port)
        srv.serve_forever()
        api_log('助手进程已优雅退出')
    except Exception as exc:
        api_log('助手进程启动失败 %r' % (exc,), 'error')


def with_api(html):
    """把本地接口地址注入页面（自动更新热替换后也要重新注入）"""
    if not _PORT[0]:
        return html
    tag = '<script>window.SQZY_API="http://127.0.0.1:%d";</script>' % _PORT[0]
    if '<head>' in html:
        return html.replace('<head>', '<head>' + tag, 1)
    return tag + html


# ==================== WebView2 检测与回退 ====================
def msgbox(text, icon=0x40):
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, text, APP_TITLE, icon)
    except Exception:
        pass


def has_webview2():
    try:
        import winreg
        roots = [
            (winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\\' + WEBVIEW2_GUID),
            (winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\Microsoft\EdgeUpdate\Clients\\' + WEBVIEW2_GUID),
            (winreg.HKEY_CURRENT_USER, r'SOFTWARE\Microsoft\EdgeUpdate\Clients\\' + WEBVIEW2_GUID),
        ]
        for root, path in roots:
            try:
                with winreg.OpenKey(root, path) as k:
                    ver, _ = winreg.QueryValueEx(k, 'pv')
                    if ver and ver != '0.0.0.0':
                        return True
            except OSError:
                continue
    except Exception:
        pass
    for p in (r'C:\Program Files (x86)\Microsoft\EdgeWebView\Application',
              r'C:\Program Files\Microsoft\EdgeWebView\Application'):
        try:
            if os.path.isdir(p) and any(n[0].isdigit() for n in os.listdir(p)):
                return True
        except Exception:
            pass
    return False


def open_in_browser(html, quiet=False):
    try:
        tmp = os.path.join(tempfile.gettempdir(), HTML_NAME)
        with open(tmp, 'w', encoding='utf-8') as f:
            f.write(html)
        os.startfile(tmp)
        if not quiet:
            msgbox('这台电脑没装 "Microsoft Edge WebView2 Runtime"，\n'
                   '已改用默认浏览器打开。\n\n'
                   '想以独立窗口运行的话，装一下微软官方的 WebView2 Runtime 即可（免费，约 2MB）。')
        return True
    except Exception as exc:
        if not quiet:
            msgbox('打开失败：\n' + str(exc), 0x10)
        return False


# ==================== 启动 ====================
_PROFILE_LOCK = []


def acquire_profile_lock():
    """WebView2 的 user data 目录同一时刻只能被一个实例占用。
    拿到锁就用它落盘（设置、缩放都能记住）；拿不到就退回私有模式，
    免得第二个窗口因为抢目录而打不开。"""
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        h = k32.CreateMutexW(None, False, 'Local\\sqzy_timetable_webview_profile')
        if not h:
            return False
        if k32.GetLastError() == 183:          # ERROR_ALREADY_EXISTS
            return False
        _PROFILE_LOCK.append(h)                # 留住句柄，别让互斥体提前释放
        return True
    except Exception:
        return False


# ==================== 窗口行为：托盘 / 关闭方式 / 置顶 ====================
# 这几件事只有主进程能做（窗口在它手里），但网页只会跟助手进程说话，
# 所以约定用一个状态文件当"信箱"：
#   网页 → 助手 : /state?top=1&close=tray&show=1  （助手写文件）
#   主进程       : 每 0.4 秒读一次文件，发现变化就应用到窗口上
# 好处是两边都不用跨进程调用，谁也不阻塞谁。
WIN_DEFAULTS = {'always_on_top': False, 'close_mode': 'tray', 'show': 0}
_UI = {'form': None, 'tray': None, 'icon': None, 'exiting': False}


_INSTANCE_LOCK = []


def acquire_instance_lock():
    """单实例：已经有窗口在跑就返回 False。
    第二个进程不建窗口，只把「请显示到前台」写进状态文件就退出。"""
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        h = k32.CreateMutexW(None, False, 'Local\\sqzy_timetable_single_instance')
        if not h:
            return True
        if k32.GetLastError() == 183:          # ERROR_ALREADY_EXISTS
            return False
        _INSTANCE_LOCK.append(h)               # 留住句柄，进程退出时系统自动释放
        return True
    except Exception:
        return True


def win_state_path():
    return os.path.join(cache_dir(), 'win_state.json')


def read_win_state():
    o = dict(WIN_DEFAULTS)
    try:
        raw = read_text(win_state_path())
        if raw:
            j = json.loads(raw)
            if isinstance(j, dict):
                for k in WIN_DEFAULTS:
                    if k in j:
                        o[k] = j[k]
    except Exception:
        pass
    o['always_on_top'] = bool(o['always_on_top'])
    if o['close_mode'] not in ('tray', 'exit'):
        o['close_mode'] = 'tray'
    try:
        o['show'] = int(o['show'])
    except Exception:
        o['show'] = 0
    return o


def write_win_state(**kw):
    o = read_win_state()
    o.update(kw)
    try:
        tmp = win_state_path() + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as fp:
            json.dump(o, fp, ensure_ascii=False)
        os.replace(tmp, win_state_path())
    except Exception as exc:
        api_log('写窗口状态失败 %r' % (exc,), 'warn')
    return o


def win_main_form():
    try:
        from webview.platforms.winforms import BrowserView
        views = list((getattr(BrowserView, 'instances', {}) or {}).values())
        return views[0] if views else None
    except Exception:
        return None


def ui_call(fn):
    """把活派回 UI 线程：WinForms 的控件只能在 UI 线程上碰"""
    try:
        from System import Action
        form = _UI.get('form')
        if form is None:
            return False
        form.BeginInvoke(Action(fn))
        return True
    except Exception as exc:
        api_log('派回 UI 线程失败 %r' % (exc,), 'warn')
        return False


def _tray_show(sender=None, e=None):
    win_show()


def _tray_quit(sender=None, e=None):
    win_quit()


def ensure_tray():
    """建托盘图标（必须在 UI 线程上调用）"""
    if _UI.get('tray') is not None:
        return
    import clr
    clr.AddReference('System.Windows.Forms')
    clr.AddReference('System.Drawing')
    from System.Windows.Forms import (NotifyIcon, ContextMenuStrip, ToolStripMenuItem,
                                      Application, ToolTipIcon)
    from System.Drawing import Icon
    ico = None
    try:
        ico = Icon.ExtractAssociatedIcon(Application.ExecutablePath)
    except Exception:
        pass
    tray = NotifyIcon()
    try:
        if ico is not None:
            tray.Icon = ico
        tray.Text = APP_TITLE
    except Exception:
        pass
    menu = ContextMenuStrip()
    mi_show = ToolStripMenuItem('显示主界面')
    mi_show.Click += _tray_show
    mi_quit = ToolStripMenuItem('退出')
    mi_quit.Click += _tray_quit
    menu.Items.Add(mi_show)
    menu.Items.Add(mi_quit)
    try:
        tray.ContextMenuStrip = menu
        tray.MouseDoubleClick += _tray_show
        tray.Visible = True
        tray.ShowBalloonTip(1200, APP_TITLE, '已隐藏到托盘，双击图标可恢复', ToolTipIcon.Info)
    except Exception as exc:
        api_log('托盘图标设置失败 %r' % (exc,), 'warn')
    _UI['tray'] = tray
    _UI['icon'] = ico
    api_log('托盘图标已就绪')


def _do_hide():
    form = _UI.get('form')
    if form is None:
        return
    try:
        ensure_tray()
        form.Hide()
        api_log('窗口已隐藏到托盘')
    except Exception as exc:
        api_log('隐藏到托盘失败 %r' % (exc,), 'warn')


def _do_show():
    form = _UI.get('form')
    if form is None:
        return
    try:
        from System.Windows.Forms import FormWindowState
        form.Show()
        form.WindowState = FormWindowState.Normal
        form.Activate()
        try:
            # Activate() 常常抢不到焦点（Windows 的前台限制），下面这套是通用做法：
            # 1) BringToFront + SW_RESTORE  2) AttachThreadInput 后 SetForegroundWindow
            # 3) 最后把 TopMost 闪一下（最有效的一招），再按状态文件恢复
            form.BringToFront()
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            user32.GetForegroundWindow.restype = wintypes.HWND
            user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.c_void_p]
            user32.SetForegroundWindow.argtypes = [wintypes.HWND]
            hwnd = wintypes.HWND(int(form.Handle))
            user32.ShowWindow(hwnd, 9)          # SW_RESTORE
            fg = user32.GetForegroundWindow()
            tid_fg = user32.GetWindowThreadProcessId(fg, None)
            tid_me = kernel32.GetCurrentThreadId()
            if tid_fg and tid_fg != tid_me:
                user32.AttachThreadInput(tid_me, tid_fg, True)
                user32.SetForegroundWindow(hwnd)
                user32.AttachThreadInput(tid_me, tid_fg, False)
            else:
                user32.SetForegroundWindow(hwnd)
            keep = bool(form.TopMost)
            form.TopMost = True
            form.TopMost = keep
        except Exception as exc:
            api_log('抢前台失败 %r' % (exc,), 'warn')
        api_log('窗口已恢复显示')
    except Exception as exc:
        api_log('恢复窗口失败 %r' % (exc,), 'warn')


def win_hide():
    ui_call(_do_hide)


def win_show():
    ui_call(_do_show)


def _dispose_tray():
    try:
        tray = _UI.get('tray')
        if tray is not None:
            tray.Visible = False
            tray.Dispose()
            _UI['tray'] = None
    except Exception:
        pass


def _do_quit():
    _UI['exiting'] = True
    _dispose_tray()
    try:
        form = _UI.get('form')
        if form is not None:
            form.Close()
    except Exception as exc:
        api_log('退出失败 %r' % (exc,), 'warn')


def win_quit():
    ui_call(_do_quit)


def _on_form_closing(sender, e):
    """点右上角 ✕ 时的分流：隐藏到托盘 / 直接退出（网页里可切）"""
    try:
        if _UI.get('exiting'):
            return
        mode = read_win_state()['close_mode']
        if mode == 'tray':
            e.Cancel = True
            api_log('关闭按钮 → 隐藏到托盘')
            _do_hide()
        else:
            _UI['exiting'] = True
            _dispose_tray()
            api_log('关闭按钮 → 直接退出')
    except Exception as exc:
        api_log('关闭处理失败 %r' % (exc,), 'warn')


def _on_form_resize(sender, e):
    try:
        from System.Windows.Forms import FormWindowState
        form = _UI.get('form')
        if form is not None and form.WindowState == FormWindowState.Minimized:
            form.WindowState = FormWindowState.Normal
            api_log('最小化 → 隐藏到托盘')
            _do_hide()
    except Exception as exc:
        api_log('最小化处理失败 %r' % (exc,), 'warn')


def _install_ui():
    """在 UI 线程上接管窗口（由 BeginInvoke 调进来）"""
    try:
        form = win_main_form()
        if form is None:
            api_log('拿不到主窗口，托盘/关闭接管跳过', 'warn')
            return
        _UI['form'] = form
        form.FormClosing += _on_form_closing
        form.Resize += _on_form_resize
        api_log('已接管窗口关闭/最小化（关闭方式：%s）' % read_win_state()['close_mode'])
    except Exception as exc:
        api_log('窗口接管失败 %r' % (exc,), 'error')


def install_window_behavior():
    def worker():
        for _ in range(150):
            form = win_main_form()
            if form is not None:
                try:
                    from System import Action
                    form.BeginInvoke(Action(_install_ui))
                    return
                except Exception:
                    pass
            time.sleep(0.2)
        api_log('等待主窗口超时，托盘未接管', 'warn')

    threading.Thread(target=worker, daemon=True).start()


def win_state_poller():
    """每 0.4 秒对一次状态文件：置顶 / 恢复显示，一律以文件为准"""
    applied_top = None
    applied_show = read_win_state().get('show', 0)
    while True:
        time.sleep(0.4)
        try:
            if _UI.get('form') is None:
                continue
            st = read_win_state()
            if applied_top is None or st['always_on_top'] != applied_top:
                v = st['always_on_top']
                ui_call(lambda v=v: setattr(_UI['form'], 'TopMost', v))
                applied_top = v
                api_log('置顶状态 → %s' % v)
            if st.get('show', 0) != applied_show:
                applied_show = st.get('show', 0)
                win_show()
        except Exception:
            pass


def helper_ready(port, timeout=4.0):
    """助手进程到底起来没有 —— 真连一次 /ping 才算数。
    不确认就拿 http://127.0.0.1:端口 去开窗口，助手要是没起来，
    用户看到的就是一页「无法访问此页面」（踩过）。"""
    end = time.time() + timeout
    while time.time() < end:
        try:
            with urllib.request.urlopen('http://127.0.0.1:%d/ping' % port, timeout=1) as r:
                if r.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(0.15)
    return False


def run_window(html):
    port = pick_free_port()
    if port:
        try:
            # 源码运行时 sys.executable 只是 python.exe，必须补上脚本路径，
            # 否则助手进程会把 --api-server 当成未知参数直接退出（踩过）。
            argv = [sys.executable]
            if not getattr(sys, 'frozen', False):
                argv.append(os.path.abspath(sys.argv[0]))
            argv += ['--api-server', str(port)]
            try:
                hlog = open(os.path.join(cache_dir(), 'helper.log'), 'ab')
            except Exception:
                hlog = subprocess.DEVNULL
            # 关键：清掉继承来的 _MEIPASS2。PyInstaller onefile 靠它让子进程共享
            # 父进程的解压目录，结果助手退出时也去删这个共享目录、而主程序还在用，
            # 就会弹「Failed to remove temporary directory」。
            env = dict(os.environ)
            env.pop('_MEIPASS2', None)
            proc = subprocess.Popen(argv, creationflags=0x08000000,
                                    stdout=hlog, stderr=hlog, close_fds=True, env=env)
            _HELPER.append(proc)
            try:
                if hlog is not subprocess.DEVNULL:
                    hlog.close()
            except Exception:
                pass
            _PORT[0] = port
            api_log('助手进程已起: %s' % ' '.join(argv[1:]))
        except Exception as exc:
            api_log('助手进程启动失败 %r' % (exc,), 'error')
    if port and not helper_ready(port):
        api_log('助手进程 4 秒内没有应答，本次改为直接塞页面（系统通知/窗口置顶会缺）', 'warn')
        stop_helper()
        _PORT[0] = 0
        port = 0

    opts = dict(width=1120, height=760, min_size=(340, 480), resizable=True,
                text_select=False, confirm_close=False, background_color='#f1f5f9')
    if port:
        # 有助手进程就让它把页面用 http 发出来（真实 origin → localStorage 可用）
        window = webview.create_window(APP_TITLE, url='http://127.0.0.1:%d/' % port, **opts)
    else:
        # 助手起不来时退回直塞，功能都在，只是设置不落盘
        window = webview.create_window(APP_TITLE, html=with_api(html), **opts)
    install_window_behavior()
    threading.Thread(target=win_state_poller, daemon=True).start()
    if UPDATE_BASE:
        threading.Thread(target=silent_update, args=(window,), daemon=True).start()
    # pywebview 默认 private_mode=True —— 文档原话「cookies and local storage are not
    # preserved」，而且窗口一关就把 profile 整个删掉。设置面板「改完不生效、下次打开
    # 又回到默认」就是这个原因（实测）。改成落盘 + 指定目录即可。
    if acquire_profile_lock():
        api_log('启用持久化配置目录，设置类改动会被记住')
        webview.start(private_mode=False, storage_path=os.path.join(cache_dir(), 'webview'))
    else:
        api_log('已有窗口在用配置目录，本次退回不落盘模式', 'warn')
        webview.start()
    stop_helper()


def main():
    if '--api-server' in sys.argv:
        run_api_server(int(sys.argv[sys.argv.index('--api-server') + 1]))
        return
    if not acquire_instance_lock():
        # 已经开着一个（哪怕它正藏在托盘里）：只请它显示到前台，本进程立刻退出。
        try:
            # 把「允许抢前台」的许可交给已在运行的那个进程，
            # 否则 Windows 会把它的 SetForegroundWindow 拦下来（只闪任务栏）。
            import ctypes
            ctypes.windll.user32.AllowSetForegroundWindow(-1)     # ASFW_ANY
        except Exception:
            pass
        write_win_state(show=int(time.time() * 1000))
        api_log('已有实例在运行，已请它显示到前台，本进程退出')
        return
    html = load_current_html()

    if not has_webview2():
        open_in_browser(html)
        return

    try:
        run_window(html)
    except Exception as exc:
        open_in_browser(html)
        print('webview failed:', exc, file=sys.stderr)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        msgbox('程序启动失败：\n' + str(exc), 0x10)
