# -*- coding: utf-8 -*-
"""桌面版外壳的端到端测试：真的开一个窗口，验证
  单实例 · 托盘隐藏 · 置顶（地址信箱 → 轮询 → 窗口）· 二次启动唤回前台

跑的是源码模式（python app.py），跟打包后的 exe 逻辑完全一样；
打包出来的 exe 用 --exe 参数再跑一遍即可。

用法: python functest_app.py [--exe 路径]
测试会临时改写状态文件 win_state.json，跑完还原。

平台：只能跑 Windows（ctypes.windll / wintypes / 注册表 / 窗口消息都是 Windows 专有）。
      别的平台上明确跳过并返回 3（"没执行"），不能算通过 —— 闸门空转等于没把关。
"""
import ctypes, io, json, os, re, subprocess, sys, time, urllib.request

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

# 必须在 from ctypes import wintypes 之前判断：Windows 之外连这个 import 都会抛
if sys.platform != 'win32':
    print('  · functest_app: 当前平台是 %s，桌面外壳闸门只能跑 Windows，跳过（返回码 3 = 没执行，不是通过）'
          % sys.platform)
    sys.exit(3)

from ctypes import wintypes

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
    """清掉上一轮残留的助手进程。

    注意：/quit 现在也要令牌（防同机网页关掉助手），所以测试没法再用「礼貌请走」那一招；
    改成按端口找占用者直接杀 —— 残留的助手会占着 51900-51904，让后面的检查认错对象。
    """
    # 1) 程序自己落的 PID 文件（源码版实例不会监听端口，只能靠它找）
    try:
        pid = io.open(os.path.join(CACHE, 'app.pid'), encoding='utf-8').read().strip()
        if pid.isdigit():
            subprocess.run(['taskkill', '/F', '/PID', pid], capture_output=True, timeout=30)
            print('    · 清掉上次遗留的实例 pid=%s（app.pid）' % pid)
    except Exception:
        pass
    # 2) 占着 51900-51904 的助手进程
    pids = set()
    try:
        out = subprocess.run(['netstat', '-ano', '-p', 'TCP'], capture_output=True,
                             text=True, timeout=30).stdout
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 5 and parts[3] == 'LISTENING' and parts[2].startswith('0.0.0.0:0'):
                for p in PORTS:
                    if parts[1].endswith(':%d' % p):
                        pids.add(parts[4])
    except Exception:
        pass
    for pid in pids:
        try:
            subprocess.run(['taskkill', '/F', '/PID', str(pid)],
                           capture_output=True, timeout=30)
            print('    · 清掉残留的助手进程 pid=%s' % pid)
        except Exception:
            pass
    if pids:
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


TOKEN = None


def refresh_token(port):
    """换了新实例就换一把令牌：每个壳进程自己生成，旧令牌对新助手无效（403）"""
    global TOKEN
    try:
        page = http('http://127.0.0.1:%d/' % port)
        m = re.search(r'window\.SQZY_TOKEN="([0-9a-f]{16,})"', page)
        TOKEN = m.group(1) if m else ''
    except Exception:
        TOKEN = ''
    return TOKEN


def call_state(port, qs):
    """带令牌调 /state：壳现在会校验令牌，不带一律 403"""
    return http('http://127.0.0.1:%d/state?%s&k=%s' % (port, qs, TOKEN or ''))


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
    had = None
    touched_run = False
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
        refresh_token(port)
        check('助手能把页面用 http 发给窗口',
              'window.SQZY_API="http://127.0.0.1:%d"' % port in page and 'id="nowBar"' in page,
              '页面注入或内容不对（%d 字节）' % len(page.encode('utf-8')))
        # 本地接口的令牌：页面必须拿到（页面靠它调 /notify /state /config 等写接口），
        # 而且壳必须会校验（无令牌一律 403，见 selftest_api）
        head = page.split('</head>')[0]
        m = re.search(r'window\.SQZY_TOKEN="([0-9a-f]{16,})"', head)
        check('注入的标签里带着本地接口令牌', bool(m),
              '注入里没有带够长度的 SQZY_TOKEN：%r' % (head[:120],))
        with open(os.path.join(here, '宿迁职业技术学院作息时间表.html'), encoding='utf-8') as f:
            master = f.read()
        check('主页面把令牌带给每个本地接口调用', 'apiQs()' in master and 'SQZY_TOKEN' in master,
              '页面里没有用令牌')

        # ---- 置顶：网页写状态 → 助手落盘 → 主进程轮询 → 窗口 ----
        call_state(port, 'top=1')
        got = wait_for(lambda: is_topmost(hwnd), 8)
        check('网页点「置顶」→ 窗口真的置顶', got, '窗口 EXSTYLE 里没有 WS_EX_TOPMOST')
        call_state(port, 'top=0')
        gone = wait_for(lambda: not is_topmost(hwnd), 8)
        check('取消置顶 → 窗口恢复正常层级', gone, '还是置顶状态')
        st = read_state()
        check('置顶状态落盘（下次打开还记得）', st.get('always_on_top') is False,
              'win_state.json=%r' % st)

        # ---- 关闭按钮 → 隐藏到托盘 ----
        call_state(port, 'close=tray')
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
        call_state(port, 'top=1')
        wait_for(lambda: is_topmost(hwnd), 8)
        p3 = launch(cmd)
        wait_for(lambda: p3.poll() is not None, 12)
        check('唤回前台不会丢掉置顶状态', wait_for(lambda: is_topmost(hwnd), 5),
              '置顶被清掉了')

        # ---- 关闭方式=直接退出 ----
        call_state(port, 'close=exit')
        time.sleep(0.6)
        user32.PostMessageW(hwnd, 0x0010, 0, 0)
        gone_proc = wait_for(lambda: p1.poll() is not None, 20)
        check('close_mode=exit：点 ✕ 直接退出', gone_proc,
              '进程还在（返回码 %s）' % p1.poll())
        check('退出后助手进程也没了', helper_port() is None, '助手还在应答')

        # ---- 开机自启动：网页开关 → 注册表 HKCU\...\Run ----
        had = read_run()
        touched_run = True
        if had:
            print('    · 机器上本来就有自启动项，先记下来，测试结束时原样还原：%s' % had[:60])
        else:
            check('默认没有自启动项', True, '')
        cleanup_helpers()          # 起新实例前先让残留的助手让位
        p4 = launch(cmd)
        port4 = wait_for(helper_port, 20)
        refresh_token(port4)
        if not port4:
            bad('自启动测试：助手没起来', '51900-51904 都没应答')
        else:
            call_state(port4, 'startup=1')
            v1 = wait_for(read_run, 6)
            check('勾上「开机自启动」→ 写入启动项', bool(v1), '注册表里没有启动项')
            check('启动项命令带 --tray（开机静默进托盘）', bool(v1) and '--tray' in v1,
                  '启动项=%r' % (v1,))
            st = json.loads(http('http://127.0.0.1:%d/state' % port4))
            check('页面能从 /state 读到自启动状态', st.get('state', {}).get('autostart') is True,
                  'state=%r' % (st.get('state'),))
            call_state(port4, 'startup=0')
            time.sleep(0.8)
            check('取消勾选 → 启动项被移除', read_run() is None, '还留着：%r' % (read_run(),))
            # 再打开一次，用来测 --tray 静默启动
            call_state(port4, 'close=exit')
            call_state(port4, 'startup=1')
            time.sleep(0.5)
            ctypes.windll.user32.PostMessageW(windows_of_title()[-1], 0x0010, 0, 0)
            wait_for(lambda: p4.poll() is not None, 20)

        cleanup_helpers()
        p5 = launch(cmd + ['--tray'])
        port5 = wait_for(helper_port, 20)
        refresh_token(port5)
        hwnd5 = wait_for(lambda: (windows_of_title() or [None])[-1], 20)
        if not hwnd5 or not port5:
            bad('--tray 静默启动', '窗口或助手没起来')
        else:
            time.sleep(1.5)
            check('--tray 启动时窗口是隐藏的（不打扰开机）', not is_visible(hwnd5),
                  '窗口居然可见')
            call_state(port5, 'close=exit')
            time.sleep(0.5)
            ctypes.windll.user32.PostMessageW(hwnd5, 0x0010, 0, 0)
            check('隐藏启动的进程能正常退出', wait_for(lambda: p5.poll() is not None, 20),
                  '进程还在（返回码 %s）' % p5.poll())
    finally:
        # 注册表里的自启动项一定要复原：中途崩了也不能在用户机器上留下开机自启
        if touched_run:
            restore_run(had)
            print('    · 自启动项已还原')
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