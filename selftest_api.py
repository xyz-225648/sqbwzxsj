# -*- coding: utf-8 -*-
"""不开窗口地验证桌面版的本地接口：直接把 app.py / exe 当助手进程跑（--api-server），
逐个打 /ping / /state /notify /latest /quit，全部走本机 127.0.0.1。

用法: python selftest_api.py [exe 或 app.py 路径] [端口]
"""
import json, os, socket, subprocess, sys, time, urllib.error, urllib.parse, urllib.request

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

TITLE = '宿迁职业技术学院作息时间表'
target = sys.argv[1] if len(sys.argv) > 1 else '宿迁职业技术学院作息时间表.exe'
def free_port():
    """默认端口动态挑一个：固定端口在上次残留 / TIME_WAIT 时会卡住重跑"""
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    p = s.getsockname()[1]
    s.close()
    return p


port = int(sys.argv[2]) if len(sys.argv) > 2 else free_port()
TESTHOME = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.testdata')
STATE = os.path.join(TESTHOME, TITLE, 'win_state.json')

env = dict(os.environ)
env.pop('_MEIPASS2', None)
env['LOCALAPPDATA'] = TESTHOME        # 被测程序的缓存落到工作区，不碰用户真实数据
cmd = [sys.executable, target] if target.lower().endswith('.py') else [target]
p = subprocess.Popen(cmd + ['--api-server', str(port)], env=env,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
base = 'http://127.0.0.1:%d' % port

backup = None
if os.path.exists(STATE):
    with open(STATE, 'rb') as f:
        backup = f.read()


def call(path, **q):
    url = base + path + (('?' + urllib.parse.urlencode(q)) if q else '')
    with urllib.request.urlopen(url, timeout=20) as r:
        return r.status, r.read().decode('utf-8')


def read_state():
    try:
        with open(STATE, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


rc = 0
try:
    ok = False
    for _ in range(30):
        try:
            st, body = call('/ping')
            print('  /ping      HTTP %d  %s' % (st, body))
            ok = True
            break
        except Exception:
            time.sleep(1)
    if not ok:
        print('  ✗ 助手进程 30 秒内没起来（端口 %d）' % port)
        rc = 1
    else:
        st, body = call('/')
        injected = 'window.SQZY_API="http://127.0.0.1:' in body
        ok_page = ('id="nowBar"' in body) and ("APP_VERSION = 'v" in body) and injected
        if not injected:
            print('    ✗ 页面里没有注入 window.SQZY_API（页面会以为自己在浏览器里，通知会失效）')
        print('  GET /      HTTP %d  %d 字节  页面自检 %s  ← exe 用 http 把页面发给窗口'
              % (st, len(body.encode('utf-8')), 'OK' if ok_page else '失败'))
        if not ok_page:
            rc = 1

        st, body = call('/version')
        print('  /version   HTTP %d  %s   ← 页面靠它判断「程序本体要不要更新」' % (st, body))
        # 令牌：从壳发出来的页面里取（页面该有、别人不该有）
        st, body = call('/')
        import re as _re
        m = _re.search(r'window.SQZY_TOKEN="([0-9a-f]+)"', body)
        token = m.group(1) if m else ''
        print('  页面里的令牌：%s' % (('已注入（%d 位）' % len(token)) if token else '✗ 没注入'))
        if not token:
            print('    ✗ 页面没拿到令牌 → 页面自己的通知/状态写入会被壳拒绝'); rc = 1

        # 不带令牌的写操作必须被拒（否则同机任意网页都能伪造通知、改状态、关助手）
        for label, path in (('/notify', '/notify?title=x&body=y'), ('/state 写', '/state?top=1'),
                            ('/config 写', '/config?set=%7B%22cfg%22%3A%7B%7D%7D'),
                            ('/open', '/open?url=https%3A%2F%2Fgitee.com%2Fx')):
            try:
                st2, body2 = call(path)
            except urllib.error.HTTPError as e:
                st2, body2 = e.code, e.read().decode('utf-8', 'replace')[:70]
            print('   %-11s 无令牌 → HTTP %s %s' % (label, st2, body2[:52]))
            if st2 != 403:
                print('    ✗ 居然没拒绝（CSRF 面还在）'); rc = 1

        st3, body3 = call('/notify', k=token, title='exe 接口自检', body='带令牌的通知')
        print('   /notify    带令牌 → HTTP %s %s' % (st3, body3[:40]))
        # 令牌这一关过了就行；ok 的真假取决于平台（非 Windows 上发不出系统通知，返回 false 是对的）
        if st3 != 200 or '"missing or bad token"' in body3:
            print('    ✗ 带令牌也被拒了（页面会发不出通知）'); rc = 1
        elif sys.platform.startswith('win') and '"ok": true' not in body3:
            print('    ✗ Windows 上带令牌应该能发通知'); rc = 1
        elif not sys.platform.startswith('win'):
            print('    · 非 Windows：ok=%s 属正常（没有 Windows 通知通道）'
                  % ('true' if '"ok": true' in body3 else 'false'))

        payload = json.dumps({'cfg': {'on': True, 'min': 9, 'tracks': [True, False, True, True]}, 't': 123456})
        st4, body4 = call('/config', k=token, set=payload)
        st5, body5 = call('/config', k=token)
        print('   /config    写+读 → %s' % ('落盘并读回 ✓（min=9）' if '123456' in body5 else '✗ %s / %s' % (body4[:30], body5[:60])))
        if '123456' not in body5:
            print('    ✗ 设置没落盘（快速重启丢设置的问题还在）'); rc = 1

        st, body = call('/version')      # 上面几步把 body 覆盖了，重新取一次再校验

        if '"shell": "v' not in body:
            print('    ✗ /version 没返回壳版本（页面的程序本体检查会失效）'); rc = 1

        # 窗口状态信箱：读默认 → 写 → 读回 → 落盘
        st, body = call('/state')
        d0 = json.loads(body)
        print('  /state(读) HTTP %d  %s' % (st, body[:120]))
        if not (d0.get('ok') and isinstance(d0.get('state'), dict)
                and 'always_on_top' in d0['state']):
            print('    ✗ /state 读回来的结构不对'); rc = 1

        st, body = call('/state', k=token, top='1', close='exit')
        d1 = json.loads(body)
        print('  /state(写) HTTP %d  top=1 close=exit  → %s' % (st, body[:120]))
        disk = read_state()
        if not (d1.get('state', {}).get('always_on_top') is True
                and disk.get('always_on_top') is True
                and disk.get('close_mode') == 'exit'):
            print('    ✗ 写进去的状态没有落盘（文件里是 %r）' % (disk,)); rc = 1
        else:
            print('    ✓ 状态已落盘 win_state.json（主进程靠它把置顶应用到窗口上）')

        st, body = call('/state', k=token, top='0', close='tray')
        if json.loads(body).get('state', {}).get('always_on_top') is not False:
            print('    ✗ 取消置顶没生效：%s' % body[:120]); rc = 1

        st, body = call('/notify', k=token, title='exe 接口自检', body='带令牌的通知')
        print('  /notify    HTTP %d  %s   ← 带令牌才允许（ok 取决于平台有没有通知通道）' % (st, body))
        if st != 200 or '"missing or bad token"' in body:
            print('    ✗ 带令牌仍被拒'); rc = 1

        st, body = call('/latest')
        print('  /latest    HTTP %d  %s' % (st, body[:150]))
        if '"v": "v' not in body:
            rc = 1

        # 通知可点击（issue IKHWKA #2）：发通知前要注册 sqzy: 协议，
        # 否则 Windows 点了通知不知道该拉起谁（点了没反应的根源）
        if sys.platform.startswith('win'):
            try:
                import winreg
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                    r'Software\Classes\sqzy\shell\open\command') as k:
                    cmdline = winreg.QueryValueEx(k, '')[0]
                print('  sqzy: 协议 → %s' % cmdline[:110])
                if os.path.basename(target).lower() not in cmdline.lower():
                    print('    ✗ 协议没指向本程序（%s）→ 点了通知会拉起别的东西'
                          % os.path.basename(target)); rc = 1
            except FileNotFoundError:
                print('    ✗ 没注册 sqzy: 协议（Windows 上点通知会没反应）'); rc = 1
            except Exception as exc:
                print('    · 协议检查跳过：%r' % (exc,))

        # 一键更新（issue IKHWKA #3）：只有页面拿着令牌才能让 exe 下载/替换自己
        for label, path in (('/download', '/download?url=https%3A%2F%2Fgitee.com%2Fx%2Fy.exe'),
                            ('/apply', '/apply')):
            try:
                st2, body2 = call(path)
            except urllib.error.HTTPError as e:
                st2, body2 = e.code, e.read().decode('utf-8', 'replace')[:70]
            print('   %-10s 无令牌 → HTTP %s %s' % (label, st2, body2[:44]))
            if st2 != 403:
                print('    ✗ 居然没拒绝（任意本机网页都能让 exe 换掉自己）'); rc = 1

        st, body = call('/download', k=token, url='https://example.com/x.exe')
        print('  /download  非 gitee 地址 → %s' % body[:80])
        if '"ok": true' in body:
            print('    ✗ 非 gitee 地址也放行了'); rc = 1
        elif 'gitee' not in body:
            print('    ✗ 没说明拒绝原因'); rc = 1

        st, body = call('/apply', k=token)
        print('  /apply     %s → %s' % ('源码模式（必须明确拒绝）' if target.lower().endswith('.py')
                                         else 'exe，还没下载过新版', body[:90]))
        if '"ok": true' in body:
            print('    ✗ 源码模式居然同意替换自己'); rc = 1

        st, body = call('/quit', k=token)
        print('  /quit      HTTP %d  %s' % (st, body))
finally:
    for _ in range(20):
        if p.poll() is not None:
            break
        time.sleep(0.5)
    if p.poll() is None:
        print('  ✗ /quit 之后助手进程还在（10s 未退出）')
        p.kill(); rc = 1
    else:
        print('  助手进程已退出，返回码 %s' % p.returncode)
    try:
        if backup is not None:
            with open(STATE, 'wb') as f:
                f.write(backup)
    except Exception:
        pass
print('  selftest: %s' % ('PASS' if rc == 0 else 'FAIL'))
sys.exit(rc)