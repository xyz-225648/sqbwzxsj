# -*- coding: utf-8 -*-
"""桌面版外壳的端到端测试：真的开一个窗口，验证
  单实例 · 托盘隐藏 · 置顶（地址信箱 → 轮询 → 窗口）· 二次启动唤回前台

跑的是源码模式（python app.py），跟打包后的 exe 逻辑完全一样；
打包出来的 exe 用 --exe 参数再跑一遍即可。

用法: python functest_app.py [--exe 路径]
测试会临时改写状态文件 win_state.json，跑完还原。
"""
import ctypes, json, os, re, subprocess, sys, time, urllib.request
from ctypes import wintypes

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

TITLE = '宿迁职业技术学院作息时间表'
# 测试自己一个数据目录（放在工作区里）：既不碰用户真实的缓存，也不受系统目录权限影响
TESTHOME = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.testdata')
CACHE = os.path.join(TESTHOME, TITLE)
STATE = os.path.join(CACHE, 'win_state.json')
RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
PORTS = (51900, 51901, 51902, 51903, 51904)

user32 = ctypes.windll.user32
k32 = ctypes.windll.kernel32
GWL_EXSTYLE = -20
WS_EX_TOPMOST = 0x8

passed, failed = [], []


def ok(label, extra=''):
    passed.append(label)
    print('    ✓ %s%s' % (label, ('  ' + extra) if extra else ''))


def bad(label, why):
    failed.append('%s：%s' % (label, why))
    print('    ✗ %s  ← %s' % (label, why))


def check(label, cond, why=''):
    if cond:
        ok(label)
    else:
        bad(label, why)
    return bool(cond)


def windows_of_title():
    found = []
    CB = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

    def cb(hwnd, _):
        n = user32.GetWindowTextLengthW(hwnd)
        if n:
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, buf, n + 1)
            if buf.value == TITLE:
                found.append(hwnd)
        return True

    user32.EnumWindows(CB(cb), 0)
    return found


def is_topmost(hwnd):
    return bool(user32.GetWindowLongW(hwnd, GWL_EXSTYLE) & WS_EX_TOPMOST)


def is_visible(hwnd):
    return bool(user32.IsWindowVisible(hwnd))


def cleanup_helpers():
    """上一轮测试如果被硬杀，助手子进程会活下来占着 51900-51904，
    导致本轮的辅助检查认错端口；它自己有 /quit，先礼貌请走。"""
    for port in PORTS:
        try:
            with urllib.request.urlopen('http://127.0.0.1:%d/quit' % port, timeout=1) as r:
                r.read()
            print('    · 清掉了上一轮残留的助手进程（端口 %d）' % port)
        except Exception:
            pass
    time.sleep(1.0)


def probe(port):
    try:
        with urllib.request.urlopen('http://127.0.0.1:%d/ping' % port, timeout=1) as r:
            return r.status == 200
    except Exception:
        return False


def port_from_log():
    """程序优先用 51900-51904，全被占时会退到随机端口；
    这时候只能从它自己的日志里读端口，别去猜。"""
    try:
        with open(os.path.join(CACHE, 'api.log'), encoding='utf-8', errors='replace') as f:
            hits = re.findall(r'端口=(\d+)', f.read())
        return int(hits[-1]) if hits else None
    except Exception:
        return None


def helper_port():
    for p in PORTS:
        if probe(p):
            return p
    p = port_from_log()
    return p if p and probe(p) else None


def http(path, timeout=3):
    with urllib.request.urlopen(path, timeout=timeout) as r:
        return r.read().decode('utf-8', 'replace')


def read_state():
    try:
        with open(STATE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def write_state(**kw):
    st = {'always_on_top': False, 'close_mode': 'tray', 'show': 0}
    st.update(read_state())
    st.update(kw)
    os.makedirs(CACHE, exist_ok=True)
    with open(STATE, 'w', encoding='utf-8') as f:
        json.dump(st, f)


def read_run():
    """读注册表里的开机自启动项（没有就返回 None）"""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            v, _ = winreg.QueryValueEx(k, TITLE)
            return v or None
    except Exception:
        return None


def restore_run(old):
    """把启动项恢复到测试前的样子"""
    try:
        import winreg
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            if old:
                winreg.SetValueEx(k, TITLE, 0, winreg.REG_SZ, old)
            else:
                try:
                    winreg.DeleteValue(k, TITLE)
                except FileNotFoundError:
                    pass
    except Exception:
        pass


def wait_for(pred, timeout, step=0.3):
    end = time.time() + timeout
    while time.time() < end:
        v = pred()
        if v:
            return v
        time.sleep(step)
    return None


def launch(cmd):
    env = dict(os.environ)
    env.pop('_MEIPASS2', None)
    env['LOCALAPPDATA'] = TESTHOME      # 让被测程序把缓存写到这里，别动真身
    log = open(os.path.join(os.environ.get('TEMP') or '.', 'sqzy_functest_app.log'), 'ab')
    # CREATE_NO_WINDOW：源码模式别弹黑窗；打包后的 exe 本来就是窗口程序
    return subprocess.Popen(cmd, env=env, stdout=log, stderr=log,
                            creationflags=0x08000000)


def main():
    exe_arg = None
    if '--exe' in sys.argv:
        exe_arg = sys.argv[sys.argv.index('--exe') + 1]
    here = os.path.dirname(os.path.abspath(__file__))
    if exe_arg:
        cmd = [os.path.abspath(exe_arg)]
        label = 'exe'
    else:
        cmd = [sys.executable, os.path.join(here, 'app.py')]
        label = '源码'

    cleanup_helpers()
    backup = None
    if os.path.exists(STATE):
        with open(STATE, 'rb') as f:
            backup = f.read()
    write_state(always_on_top=False, close_mode='tray', show=0)

    p1 = p2 = p4 = p5 = None
    try:
        print('  [桌面外壳 · %s]' % label)
        p1 = launch(cmd)
        hwnd = wait_for(lambda: (windows_of_title() or [None])[0], 40)
        if not hwnd:
            bad('窗口能开出来', '40 秒没等到标题为「%s」的窗口' % TITLE)
            return 1
        ok('窗口已创建', 'hwnd=%s' % hwnd)
        # 重新枚举一次，拿到窗口句柄列表（onefile exe 的窗口属于子进程）
        wins = windows_of_title()
        hwnd = wins[0] if wins else hwnd
        check('窗口默认可见', wait_for(lambda: is_visible(hwnd), 10), '窗口一直不可见')
        check('默认不置顶', not is_topmost(hwnd), '一开始就是置顶')

        port = wait_for(helper_port, 20)
        if not port:
            bad('本地助手进程起来并应答 /ping', '51900-51904 都没应答')
            return 1
        ok('本地助手进程在 %d 端口应答' % port)

        # ---- 首页真的由助手发出来（否则设置不落盘、通知发不出去） ----
        page = http('http://127.0.0.1:%d/' % port)
        check('助手能把页面用 http 发给窗口',
              'window.SQZY_API="http://127.0.0.1:%d"' % port in page and 'id="nowBar"' in page,
              '页面注入或内容不对（%d 字节）' % len(page.encode('utf-8')))
        # 注意：缓存里可能还躺着旧版页面（缓存优先是设计如此），
        # 所以令牌只在「注入的 head 标签」和「本地主页面」两处检查
        head = page.split('</head>')[0]
        check('注入的标签里不再有没人校验的令牌', 'SQZY_TOKEN' not in head, '注入里还有 SQZY_TOKEN')
        with open(os.path.join(here, '宿迁职业技术学院作息时间表.html'), encoding='utf-8') as f:
            master = f.read()
        check('主页面源码里也没有这个令牌了', 'SQZY_TOKEN' not in master, '主页面里还有 SQZY_TOKEN')

        # ---- 置顶：网页写状态 → 助手落盘 → 主进程轮询 → 窗口 ----
        http('http://127.0.0.1:%d/state?top=1' % port)
        got = wait_for(lambda: is_topmost(hwnd), 8)
        check('网页点「置顶」→ 窗口真的置顶', got, '窗口 EXSTYLE 里没有 WS_EX_TOPMOST')
        http('http://127.0.0.1:%d/state?top=0' % port)
        gone = wait_for(lambda: not is_topmost(hwnd), 8)
        check('取消置顶 → 窗口恢复正常层级', gone, '还是置顶状态')
        st = read_state()
        check('置顶状态落盘（下次打开还记得）', st.get('always_on_top') is False,
              'win_state.json=%r' % st)

        # ---- 关闭按钮 → 隐藏到托盘 ----
        http('http://127.0.0.1:%d/state?close=tray' % port)
        time.sleep(0.6)
        user32.PostMessageW(hwnd, 0x0010, 0, 0)      # WM_CLOSE
        hidden = wait_for(lambda: not is_visible(hwnd), 8)
        check('close_mode=tray：点 ✕ 只隐藏，不退出', hidden and p1.poll() is None,
              '窗口可见=%s 进程返回码=%s' % (is_visible(hwnd), p1.poll()))

        # ---- 二次启动：唤回前台后自己退出 ----
        p2 = launch(cmd)
        back = wait_for(lambda: is_visible(hwnd), 10)
        check('再开一次 → 原窗口被唤回前台', back, '窗口还是隐藏的')
        exited = wait_for(lambda: p2.poll() is not None, 12)
        check('第二个进程自己退出（不会多开）', exited, '第二个进程 12 秒还没退出（返回码 %s）' % p2.poll())
        n_win = len(windows_of_title())
        check('全机只有一个窗口', n_win == 1, '出现了 %d 个窗口' % n_win)

        # ---- 置顶也能被唤回后的窗口保持 ----
        http('http://127.0.0.1:%d/state?top=1' % port)
        wait_for(lambda: is_topmost(hwnd), 8)
        p3 = launch(cmd)
        wait_for(lambda: p3.poll() is not None, 12)
        check('唤回前台不会丢掉置顶状态', wait_for(lambda: is_topmost(hwnd), 5),
              '置顶被清掉了')

        # ---- 关闭方式=直接退出 ----
        http('http://127.0.0.1:%d/state?close=exit' % port)
        time.sleep(0.6)
        user32.PostMessageW(hwnd, 0x0010, 0, 0)
        gone_proc = wait_for(lambda: p1.poll() is not None, 20)
        check('close_mode=exit：点 ✕ 直接退出', gone_proc,
              '进程还在（返回码 %s）' % p1.poll())
        check('退出后助手进程也没了', helper_port() is None, '助手还在应答')

        # ---- 开机自启动：网页开关 → 注册表 HKCU\...\Run ----
        had = read_run()
        check('默认没有自启动项', had is None, '本来就有一条：%r' % (had,))
        cleanup_helpers()          # 起新实例前先让残留的助手让位
        p4 = launch(cmd)
        port4 = wait_for(helper_port, 20)
        if not port4:
            bad('自启动测试：助手没起来', '51900-51904 都没应答')
        else:
            http('http://127.0.0.1:%d/state?startup=1' % port4)
            v1 = wait_for(read_run, 6)
            check('勾上「开机自启动」→ 写入启动项', bool(v1), '注册表里没有启动项')
            check('启动项命令带 --tray（开机静默进托盘）', bool(v1) and '--tray' in v1,
                  '启动项=%r' % (v1,))
            st = json.loads(http('http://127.0.0.1:%d/state' % port4))
            check('页面能从 /state 读到自启动状态', st.get('state', {}).get('autostart') is True,
                  'state=%r' % (st.get('state'),))
            http('http://127.0.0.1:%d/state?startup=0' % port4)
            time.sleep(0.8)
            check('取消勾选 → 启动项被移除', read_run() is None, '还留着：%r' % (read_run(),))
            # 再打开一次，用来测 --tray 静默启动
            http('http://127.0.0.1:%d/state?close=exit' % port4)
            http('http://127.0.0.1:%d/state?startup=1' % port4)
            time.sleep(0.5)
            ctypes.windll.user32.PostMessageW(windows_of_title()[-1], 0x0010, 0, 0)
            wait_for(lambda: p4.poll() is not None, 20)

        cleanup_helpers()
        p5 = launch(cmd + ['--tray'])
        port5 = wait_for(helper_port, 20)
        hwnd5 = wait_for(lambda: (windows_of_title() or [None])[-1], 20)
        if not hwnd5 or not port5:
            bad('--tray 静默启动', '窗口或助手没起来')
        else:
            time.sleep(1.5)
            check('--tray 启动时窗口是隐藏的（不打扰开机）', not is_visible(hwnd5),
                  '窗口居然可见')
            http('http://127.0.0.1:%d/state?close=exit' % port5)
            time.sleep(0.5)
            ctypes.windll.user32.PostMessageW(hwnd5, 0x0010, 0, 0)
            check('隐藏启动的进程能正常退出', wait_for(lambda: p5.poll() is not None, 20),
                  '进程还在（返回码 %s）' % p5.poll())
        restore_run(had)
    finally:
        # 能好好退就好好退：硬杀会把它拉起的助手进程留成孤儿
        for p in (p1, p2, p4, p5):
            if not p or p.poll() is not None:
                continue
            try:
                for h in (windows_of_title() or []):
                    ctypes.windll.user32.PostMessageW(h, 0x0010, 0, 0)
                if not wait_for(lambda: p.poll() is not None, 8, 0.4):
                    p.kill()
            except Exception:
                pass
        cleanup_helpers()
        if backup is not None:
            try:
                with open(STATE, 'wb') as f:
                    f.write(backup)
            except Exception:
                pass

    print('  桌面外壳: %s（通过 %d 项）' % ('PASS' if not failed else 'FAIL', len(passed)))
    for x in failed:
        print('    ✗ ' + x)
    return 1 if failed else 0


sys.exit(main())