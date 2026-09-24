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
def _page_file():
    """页面文件名（P2）：本地开发叫「宿迁职业技术学院作息时间表.html」，仓库里是 index.html。
    仓库只保留一份（避免两份内容漂移），所以这里按顺序找，clone 下来就能直接跑。"""
    for _n in ('宿迁职业技术学院作息时间表.html', 'index.html'):
        if os.path.exists(_n):
            return _n
    raise SystemExit('找不到页面文件：宿迁职业技术学院作息时间表.html 或 index.html（请在仓库根目录执行）')

import http.server
import json
import os
import re
import secrets
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

HTML_NAME = _page_file()
APP_TITLE = '宿迁职业技术学院作息时间表'
# 桌面壳自己的版本号：必须和页面里的 APP_VERSION、安卓 versionName 一致。
# 页面拿它跟仓库里的 program.txt 比，用来发现「网页是最新的、但程序本体老了」。
SHELL_VERSION = 'v2.3.12'
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


def fetch_program():
    """程序本体（exe/apk）当前发布的版本：仓库里的 program.txt。
    网页能热更新，程序本体不能 —— 这个文件就是用来提醒用户「去下新版」的。"""
    if not UPDATE_BASE:
        return None
    for base in base_candidates():
        for attempt in range(2):
            try:
                txt = http_text(base + 'program.txt?t=%d' % int(time.time()))
                m = re.search(r'\{.*\}', txt, re.S)
                if m:
                    return json.loads(m.group(0))
            except Exception as exc:
                api_log('program 第%d次失败 %r' % (attempt + 1, exc), 'warn')
                time.sleep(1)
    return None


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


def _page_ver(html):
    """页面里的 APP_VERSION 换算成可比较的数字（用于判断"新不新"）。"""
    m = re.search(r"var APP_VERSION = 'v([0-9]+)\.([0-9]+)\.([0-9]+)'", html or '')
    return (int(m.group(1)) * 10000 + int(m.group(2)) * 100 + int(m.group(3))) if m else -1


def silent_update(window):
    html, ver = check_update()
    # 只在新版号更大时才替换：否则会把本地/新版页面降级成线上的旧页面（v2.3.0 测试时踩到）
    if _page_ver(html) <= _page_ver(load_current_html()):
        api_log('线上页面 %s 不比本地新，跳过替换' % ver)
        return
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
<toast duration="long" activationType="protocol" launch="sqzy:open"><visual><binding template="ToastGeneric">__ICONIMG__<text>__TITLE__</text><text>__BODY__</text></binding></visual></toast>
"@)
$t = New-Object Windows.UI.Notifications.ToastNotification $xml
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("__APPID__").Show($t)
"""


def register_protocol():
    """注册 sqzy: 协议（HKCU，不需要管理员）。

    为什么要它：Windows 的 toast 点击后靠 activationType 找目标。桌面应用要么注册 COM 激活器，
    要么用 protocol —— 后者只要一个注册表键就能工作，点通知就等于用系统默认方式启动本程序
    （第二次启动会走单实例逻辑把已有窗口叫到前台）。""" 
    try:
        import winreg
        exe = self_command_path()
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r'Software\Classes\sqzy') as k:
            winreg.SetValueEx(k, '', 0, winreg.REG_SZ, 'URL:sqzy')
            winreg.SetValueEx(k, 'URL Protocol', 0, winreg.REG_SZ, '')
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER,
                              r'Software\Classes\sqzy\shell\open\command') as k:
            winreg.SetValueEx(k, '', 0, winreg.REG_SZ, exe)
        return True
    except Exception as exc:
        api_log('注册 sqzy: 协议失败 %r' % (exc,), 'warn')
        return False


def self_command_path():
    """点通知要执行的命令行（不带 --tray：通知被点了就该把窗口亮出来）。

    已经是唯一实例时，这次启动只会给在跑的进程发一个「请显示到前台」，自己马上退 ——
    所以点通知 = 把托盘里的窗口叫出来，不会开出第二个窗口。"""
    if getattr(sys, 'frozen', False):
        return '"%s"' % sys.executable
    return '"%s" "%s"' % (sys.executable, os.path.abspath(sys.argv[0]))


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
        register_protocol()
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
# 本地接口的令牌：每次启动随机生成，只注入给本程序自己发出的页面。
# 为什么必须要有：接口监听在 127.0.0.1:51900，浏览器里打开的**任意网页**都能向它发 GET
# （CORS 只拦读响应，不拦发请求），于是能伪造系统通知、改窗口状态、甚至把助手关掉。
# 只读接口（页面本体、版本、/ping）放行，会改东西的接口（state / notify / open / quit / config）必须带令牌。
_TOKEN = [secrets.token_hex(16)]
OPEN_PATHS = ('/', '/index.html', '/ping', '/latest', '/version')


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

    def _reply(self, obj, code=200):
        try:
            body = json.dumps(obj, ensure_ascii=False).encode('utf-8')
            self.send_response(code)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            # 不发 Access-Control-Allow-Origin：页面与接口本来就同源，不需要它；
            # 发 * 等于允许任何网站读走本地接口的响应（多余暴露）。
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception as exc:
            api_log('reply 失败 %r' % (exc,), 'warn')

    def token_ok(self, q):
        given = (q.get('k', [''])[0] or self.headers.get('X-SQZY-Token', '') or '').strip()
        return bool(given) and given == _TOKEN[0]

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        # 跨站请求一律拒：页面同源发请求时不带 Origin（或带自己的 127.0.0.1 端口）
        origin = (self.headers.get('Origin') or '').strip()
        if origin and not (origin.startswith('http://127.0.0.1:')
                           or origin.startswith('http://localhost:')):
            api_log('拒绝跨站请求 Origin=%r path=%s' % (origin, u.path), 'warn')
            return self._reply({'ok': False, 'err': 'cross-site request refused'}, code=403)
        # 会改状态的接口必须带令牌；/state 只在「写」的时候要求（只读无副作用）
        need = False
        if (u.path == '/notify' or u.path == '/open' or u.path == '/quit'
                or u.path == '/config' or u.path == '/download' or u.path == '/apply'):
            need = True
        elif u.path == '/state' and any(k in q for k in ('top', 'close', 'show', 'startup')):
            need = True
        if need and not self.token_ok(q):
            api_log('拒绝无令牌请求 %s（可能有网页在扫本地端口）' % u.path, 'warn')
            return self._reply({'ok': False, 'err': 'missing or bad token'}, code=403)
        # 不加访问令牌。曾经加过，代价是老版本缓存页不带令牌就被拒绝，
        # 直接导致「检查更新失败」和「通知发不出去」两次线上故障；
        # 而它挡住的只是「同机网页可能伪造一条通知」，收益远小于代价。
        # 真正的防护是：只监听 127.0.0.1 + 随机端口。
        if u.path in ('/', '/index.html'):
            # 页面走 http 打开，而不是 pywebview 的 html= 直塞：
            # 直塞出来的文档 origin 是 opaque，localStorage 直接抛 SecurityError，
            # 表现就是「设置改完不保存」。给它一个真实 origin 即可。
            try:
                body = with_api(load_current_html()).encode('utf-8')
            except Exception as exc:
                # 内置页面缺失之类：别让请求静默断掉，至少回一页说明并记日志
                api_log('首页内容取不到 %r' % (exc,), 'error')
                api_log(traceback.format_exc().replace(chr(10), ' | '), 'error')
                body = ('<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
                        '<title>页面暂时读不出来</title>'
                        '<body style="font-family:system-ui;padding:32px">'
                        '<h3>页面暂时读不出来</h3><p>程序自己的日志里有详细原因'
                        '（api.log）。可以按下面两步试试：</p>'
                        '<ol><li>关掉程序重新打开</li><li>还不行就把 api.log 发出来</li></ol>'
                        '</body></html>').encode('utf-8')
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
            # 窗口状态信箱：网页在这里读/写「置顶、关闭方式、开机自启动、恢复显示」
            if any(k in q for k in ('top', 'close', 'show', 'startup')):
                kw = {}
                if 'startup' in q:
                    # 自启动是注册表说了算，不放状态文件里（状态文件只管窗口）
                    set_autostart(q['startup'][0] not in ('0', 'false', 'off', ''))
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
            st['autostart'] = get_autostart()      # 页面拿它决定开关的勾选状态
            return self._reply({'ok': True, 'state': st})
        if u.path == '/ping':
            return self._reply({'ok': True, 'native': True, 'name': APP_TITLE,
                                'shell': SHELL_VERSION})
        if u.path == '/version':
            # 页面用它判断「程序本体要不要更新」（网页自己能热更新，exe 不能）
            return self._reply({'ok': True, 'kind': 'exe', 'shell': SHELL_VERSION})
        if u.path == '/file':
            # 只读代理：把仓库里的文本文件（目前只放行 calendar.txt）转给页面，白名单写死。
            # 为什么要它：网页版读 GitHub 镜像，校园网/内网常常不通；桌面版走本地壳 → Gitee，稳得多。
            name = q.get('name', [''])[0]
            if name not in ('calendar.txt',):
                return self._reply({'ok': False, 'err': 'not allowed'})
            txt = None
            for b in base_candidates():
                try:
                    txt = http_text(b + name + '?t=%d' % int(time.time()))
                    break
                except Exception as exc:
                    api_log('代理取 %s 失败 %r' % (name, exc), 'warn')
            api_log('代理取文件 %s -> %s' % (name, 'ok' if txt else 'fail'))
            return self._reply({'ok': bool(txt), 'name': name, 'text': txt or ''})
        if u.path == '/download':
            url = q.get('url', [''])[0]
            sha = q.get('sha256', [''])[0]
            if not url.startswith('https://gitee.com/'):
                return self._reply({'ok': False, 'err': '只允许 gitee.com 的下载地址'})
            dest = os.path.join(tempfile.gettempdir(), 'sqzy_new.exe')
            ok, msg = download_file(url, dest, sha)
            if ok:
                _UPDATE['path'] = dest
                _UPDATE['version'] = q.get('v', [''])[0]
            api_log('下载新版：%s（%s）' % (ok, msg))
            return self._reply({'ok': ok, 'msg': msg})
        if u.path == '/apply':
            ok, msg = apply_update()
            return self._reply({'ok': ok, 'msg': msg})
        if u.path == '/config':
            # 页面设置的落盘副本：GET 读，?set=<json> 写（都要令牌，见上面闸门）
            if 'set' in q:
                return self._reply({'ok': write_settings(q['set'][0])})
            return self._reply({'ok': True, 'settings': read_settings()})
        if u.path == '/open':
            url = q.get('url', [''])[0]
            if url.startswith('https://gitee.com/') or url.startswith('https://github.com/'):
                try:
                    # WebView2 里点外链不会自动走系统浏览器，交给壳来开
                    os.startfile(url)
                    api_log('已在系统浏览器打开 %s' % url)
                    return self._reply({'ok': True})
                except Exception as exc:
                    api_log('打开外链失败 %r' % (exc,), 'warn')
                    return self._reply({'ok': False, 'err': str(exc)[:120]})
            return self._reply({'ok': False, 'err': '只允许 gitee.com / github.com 的链接'})
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
            return self._reply({'ok': bool(info), 'latest': info, 'program': fetch_program()})
        if u.path == '/notify':
            title = q.get('title', [''])[0][:80]
            body = q.get('body', [''])[0][:180]
            ok = notify_windows(title, body)
            api_log('notify(%r) -> %r' % (title, ok))
            return self._reply({'ok': ok})
        return self._reply({'ok': False, 'err': 'unknown'})


def settings_path():
    return os.path.join(cache_dir(), 'settings.json')


def read_settings():
    """页面的设置落一份到文件：只靠 WebView2 的 localStorage，「设置改完马上重启」时
    可能还没刷盘，下次打开就回到了默认（issue IKHTOU 里的「快速重启丢设置」）。"""
    raw = read_text(settings_path())
    if not raw:
        return None
    try:
        o = json.loads(raw)
        return o if isinstance(o, dict) else None
    except Exception:
        return None


def write_settings(text):
    """接收页面传来的 {'cfg':..., 't':...}，原子落盘；只接受小体积 JSON 对象"""
    if not text or len(text) > 16384:
        return False
    try:
        o = json.loads(text)
    except Exception:
        return False
    if not isinstance(o, dict) or 'cfg' not in o:
        return False
    tmp = settings_path() + '.tmp'
    try:
        with open(tmp, 'w', encoding='utf-8', newline='') as f:
            json.dump(o, f, ensure_ascii=False)
        os.replace(tmp, settings_path())
        return True
    except Exception as exc:
        api_log('写设置失败 %r' % (exc,), 'warn')
        return False


_UPDATE = {'path': None, 'version': ''}


def ascii_safe_url(url):
    """把 URL 里的非 ASCII 字符（比如中文资产名）转义掉再发请求。
    urllib 构造请求行时只接受 ASCII，裸中文会抛 UnicodeEncodeError —— 这也是
    v2.3.0 里『一键更新』下载失败的根因之一（program.txt 里的地址没转义）。"""
    try:
        url.encode('ascii')
        return url
    except Exception:
        return urllib.parse.quote(url, safe=':/?&=%~#+[]@!$&()*,;')


def download_file(url, dest, sha256=None):
    url = ascii_safe_url(url)
    """下载到临时目录并校验 sha256；返回 (ok, 说明)"""
    try:
        req = urllib.request.Request(url, headers={'User-Agent': UA})
        with urllib.request.urlopen(req, timeout=120) as r, open(dest, 'wb') as f:
            while True:
                chunk = r.read(1 << 16)
                if not chunk:
                    break
                f.write(chunk)
        size = os.path.getsize(dest)
        if size < 100000:                     # exe 至少十几 MB，太小肯定不对
            return False, '文件太小（%d 字节）' % size
        if sha256:
            import hashlib
            h = hashlib.sha256()
            with open(dest, 'rb') as f:
                for chunk in iter(lambda: f.read(1 << 20), b''):
                    h.update(chunk)
            if h.hexdigest().lower() != sha256.lower():
                return False, '校验不通过（下载可能被截断/篡改）'
        return True, '已下载 %d 字节' % size
    except Exception as exc:
        return False, '下载失败：%s' % str(exc)[:120]


def apply_update():
    """退出后旁路替换自己：PyInstaller onefile 运行中不能覆盖自身，
    所以写一个 cmd，等本进程退出后 move 覆盖再重启。"""
    if not getattr(sys, 'frozen', False):
        return False, '源码模式不支持自我替换（请用发行版里的 exe）'
    if not _UPDATE['path'] or not os.path.exists(_UPDATE['path']):
        return False, '还没有下载好的新版本'
    exe = sys.executable
    cmd_path = os.path.join(tempfile.gettempdir(), 'sqzy_update.cmd')
    new = _UPDATE['path']
    pid = os.getpid()
    # 注意：newline='' —— 行尾自己写成 CRLF，别让 Python 再翻译一次（会变成 CR CR LF，
    # cmd 解析不了整段脚本，替换就静默失效了，这个坑踩过一次）
    try:
        vbs_path = os.path.join(tempfile.gettempdir(), 'sqzy_update.vbs')
        with open(vbs_path, 'w', encoding='gbk', newline='\r\n') as f:
            # 用 vbs 以「完全隐藏」方式跑 cmd，避免弹黑窗口（用户反馈过）
            f.write('CreateObject("WScript.Shell").Run "cmd /c ""' + cmd_path + '"" ""' + _UPDATE['path'] + '"" ""' + exe + '""", 0, False' + chr(13) + chr(10))
        with open(cmd_path, 'w', encoding='gbk', newline='') as f:
            f.write('@echo off\r\n')
            f.write('rem 先等助手退出，再结束主程序 —— 主程序不退出，exe 文件被占用，move 一定失败（踩过）\r\n')
            f.write('ping -n 3 127.0.0.1 >nul\r\n')
            f.write('taskkill /IM "%~nx1" /F >nul 2>nul\r\n')
            f.write('set /a n=0\r\n')
            f.write(':retry\r\n')
            f.write('move /y "%~1" "%~2" >nul 2>nul\r\n')
            f.write('if not exist "%~1" goto :run\r\n')
            f.write('set /a n+=1\r\n')
            f.write('if %n% geq 40 goto :fail\r\n')
            f.write('ping -n 2 127.0.0.1 >nul\r\n')
            f.write('goto :retry\r\n')
            f.write(':run\r\n')
            f.write('start "" "%~2"\r\n')
            f.write('del "%~f0"\r\n')
            f.write('del "%~f0".vbs >nul 2>nul\r\n')
            f.write('exit /b\r\n')
            f.write(':fail\r\n')
            f.write('echo %date% %time% 替换失败，新版本仍在 %~1 > "%TEMP%\sqzy_update.log"\r\n')
            f.write('start "" "%~2"\r\n')
            f.write('del "%~f0"\r\n')
        # 参数：新文件、目标 exe（%~nx1 用于 taskkill，先停主程序再替换）
        subprocess.Popen(['wscript.exe', vbs_path], creationflags=0x08000000, close_fds=True)
        api_log('已安排替换并重启：%s' % _UPDATE['version'])
        return True, '程序将退出并在替换后自动重启'
    except Exception as exc:
        api_log('安排替换失败 %r' % (exc,), 'error')
        return False, str(exc)[:120]


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


class _ApiServer(socketserver.ThreadingTCPServer):
    """SO_REUSEADDR + 每个连接一个线程；这两个都必须是类属性，构造时就生效"""
    allow_reuse_address = True
    daemon_threads = True


def run_api_server(port):
    """助手进程里跑这个：独立进程不受 pywebview 消息循环影响"""
    # 助手自己也要知道自己在哪个端口：它负责把页面用 http 发给窗口，
    # 而页面靠注入的 window.SQZY_API 才能认出「这是桌面版」并走系统通知。
    # 不设这个值 → 注入被跳过 → 页面以为自己在浏览器里，通知全落到页面内提示。
    _PORT[0] = port
    try:
        # 注意：allow_reuse_address 必须在**实例化之前**设成类属性 —— 绑定发生在
        # 构造函数里，构造完再赋值是无效的（踩过：助手退出后 60 秒内 TIME_WAIT 没散，
        # 重启就 bind 失败，只好退到 51901+，而 localStorage 按「host:端口」隔离，
        # 设置看起来又"丢"了）。
        srv = _ApiServer(('127.0.0.1', port), _ApiHandler)
        api_log('助手进程开始服务 端口=%d' % port)
        srv.serve_forever()
        api_log('助手进程已优雅退出')
    except Exception as exc:
        api_log('助手进程启动失败 %r' % (exc,), 'error')


def with_api(html):
    """把本地接口地址注入页面（自动更新热替换后也要重新注入）"""
    if not _PORT[0]:
        return html
    tag = ('<script>window.SQZY_API="http://127.0.0.1:%d";'
           'window.SQZY_TOKEN="%s";</script>') % (_PORT[0], _TOKEN[0])
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
            (winreg.HKEY_LOCAL_MACHINE, 'SOFTWARE\\WOW6432Node\\Microsoft\\EdgeUpdate\\Clients\\' + WEBVIEW2_GUID),
            (winreg.HKEY_LOCAL_MACHINE, 'SOFTWARE\\Microsoft\\EdgeUpdate\\Clients\\' + WEBVIEW2_GUID),
            (winreg.HKEY_CURRENT_USER, 'SOFTWARE\\Microsoft\\EdgeUpdate\\Clients\\' + WEBVIEW2_GUID),
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
# 命令行带 --tray（开机自启动拉起来的那次）时，窗口建好就直接进托盘
START_HIDDEN = '--tray' in sys.argv


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


# ==================== 开机自启动 ====================
# 只用 HKCUSoftwareMicrosoftWindowsCurrentVersionRun：
# 不写系统目录、不要管理员权限,卸载时删掉这个值即可（绿色软件该有的样子）。
AUTOSTART_NAME = APP_TITLE
AUTOSTART_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'


def self_command():
    """自启动要执行的命令行。打包后就是 exe 自己；源码模式带上 python 和脚本路径。
    末尾的 --tray 让它在开机时直接进托盘，不打扰人。"""
    if getattr(sys, 'frozen', False):
        return '"%s" --tray' % sys.executable
    return '"%s" "%s" --tray' % (sys.executable, os.path.abspath(sys.argv[0]))


def get_autostart():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, AUTOSTART_KEY) as k:
            val, _ = winreg.QueryValueEx(k, AUTOSTART_NAME)
            return bool(val)
    except Exception:
        return False


def set_autostart(on):
    try:
        import winreg
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, AUTOSTART_KEY) as k:
            if on:
                winreg.SetValueEx(k, AUTOSTART_NAME, 0, winreg.REG_SZ, self_command())
            else:
                try:
                    winreg.DeleteValue(k, AUTOSTART_NAME)
                except FileNotFoundError:
                    pass
        api_log('开机自启动 -> %s' % get_autostart())
    except Exception as exc:
        api_log('设置开机自启动失败 %r' % (exc,), 'warn')
    return get_autostart()


def refresh_autostart():
    """已经开了自启动的话，每次启动顺手把命令里的路径刷新一遍：
    用户把 exe 挪了地方（或换了新版本），注册表里那条旧路径就会失效。"""
    try:
        if not get_autostart():
            return
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, AUTOSTART_KEY) as k:
            old, _ = winreg.QueryValueEx(k, AUTOSTART_NAME)
        if old != self_command():
            set_autostart(True)
            api_log('自启动路径已刷新')
    except Exception:
        pass


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
        if START_HIDDEN:
            # 开机自启动拉起来的这次：直接进托盘，别在开机时糊人一脸窗口
            _do_hide()
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


def helper_ready(port, timeout=15.0):
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
        api_log('助手进程 15 秒内没有应答，本次改为直接塞页面'
                '（系统通知/窗口置顶/设置落盘会缺）', 'warn')
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
        if START_HIDDEN:
            # 开机自启动的这次发现已经有一个在跑（用户自己先开过）：
            # 悄悄退出就行，别在开机时把窗口弹到人脸上
            api_log('已有实例在运行，本次为开机自启动，静默退出')
            return
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
    refresh_autostart()                 # exe 被挪了地方也能自愈
    # 把 PID 落盘：启动不了时（比如上次的进程没退干净）能一眼看出是谁占着
    write_text(os.path.join(cache_dir(), 'app.pid'), str(os.getpid()))
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
