# -*- coding: utf-8 -*-
"""
宿迁职业技术学院作息时间表 —— 桌面版

用 Windows 的 WebView2(Edge 内核) 显示网页，窗口可自由缩放；
窗口变窄时页面会自动切换成竖排时间轴。

自动更新（配合码云仓库使用）：
  启动瞬间先显示本地版本（内置版或上次缓存），随后在后台悄悄去码云检查；
  发现新版本就静默热替换，用户几乎无感。断网时一切照旧，不影响使用。
  把 UPDATE_BASE 填成你的仓库 raw 地址即可启用。
"""
import os
import sys
import tempfile
import threading
import urllib.request

import webview

HTML_NAME = '宿迁职业技术学院作息时间表.html'
APP_TITLE = '宿迁职业技术学院作息时间表'
WEBVIEW2_GUID = '{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}'

# ==================== 自动更新配置 ====================
# 码云仓库的 raw 地址（结尾要带 /），留空表示关闭自动更新。
# 例：UPDATE_BASE = 'https://gitee.com/zhangsan/sqzy-timetable/raw/master/'
UPDATE_BASE = 'https://gitee.com/xyz-225648/sqbwzxsj/raw/master/'
FETCH_TIMEOUT = 8
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
VALID_MARKERS = ('宿迁职业技术学院作息时间表', '<html')
MIN_HTML = 5000


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
    """优先用上次缓存到的新版本，其次用内置版本"""
    cached = read_text(os.path.join(cache_dir(), 'index.html'))
    if is_valid(cached):
        return cached
    return read_embedded()


def http_text(url):
    req = urllib.request.Request(url, headers={
        'User-Agent': UA,
        'Cache-Control': 'no-cache',
        'Pragma': 'no-cache',
    })
    with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as resp:
        return resp.read().decode('utf-8', 'replace')


def check_update():
    """有新版本返回 (html, 版本号)，否则 (None, None)。任何异常都静默忽略。"""
    if not UPDATE_BASE:
        return None, None
    for base in base_candidates():
        html, ver = _try_base(base)
        if html:
            return html, ver
    return None, None


def base_candidates():
    """master / main 两个分支都试一下，避免默认分支猜错导致更新失效"""
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


def silent_update(window):
    """后台线程：查到新版本就热替换页面（已实测可从非 UI 线程调用）"""
    html, ver = check_update()
    if not html:
        return
    try:
        window.load_html(html)
    except Exception:
        pass


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


def run_window(html):
    window = webview.create_window(
        APP_TITLE,
        html=html,
        width=1120,
        height=760,
        min_size=(340, 480),
        resizable=True,
        text_select=False,       # 与页面一致：禁止选中文字
        confirm_close=False,
        background_color='#f1f5f9',
    )
    if UPDATE_BASE:
        threading.Thread(target=silent_update, args=(window,), daemon=True).start()
    webview.start()


def main():
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
