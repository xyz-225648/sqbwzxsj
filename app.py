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
    try:
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
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


def silent_update(window):
    html, ver = check_update()
    if not html:
        return
    try:
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
<toast duration="long"><visual><binding template="ToastGeneric"><text>__TITLE__</text><text>__BODY__</text></binding></visual></toast>
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


def notify_windows(title, body):
    """不阻塞地发一条 Windows 原生通知，失败返回 False"""
    if not sys.platform.startswith('win'):
        return False
    try:
        _ensure_appid()
        ps = (_TOAST_PS
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
_TOKEN = [secrets.token_hex(8)]


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
                base = UPDATE_BASE if UPDATE_BASE.endswith('/') else UPDATE_BASE + '/'
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
            api_log('latest -> %r' % (info,))
            return self._reply({'ok': bool(info), 'latest': info})
        if u.path == '/notify':
            title = q.get('title', [''])[0][:80]
            body = q.get('body', [''])[0][:180]
            ok = notify_windows(title, body)
            api_log('notify(%r) -> %r' % (title, ok))
            return self._reply({'ok': ok})
        return self._reply({'ok': False, 'err': 'unknown'})


def pick_free_port():
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

    window = webview.create_window(
        APP_TITLE,
        html=with_api(html),
        width=1120,
        height=760,
        min_size=(340, 480),
        resizable=True,
        text_select=False,
        confirm_close=False,
        background_color='#f1f5f9',
    )
    if UPDATE_BASE:
        threading.Thread(target=silent_update, args=(window,), daemon=True).start()
    webview.start()
    stop_helper()


def main():
    if '--api-server' in sys.argv:
        run_api_server(int(sys.argv[sys.argv.index('--api-server') + 1]))
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
