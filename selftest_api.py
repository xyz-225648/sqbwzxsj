# -*- coding: utf-8 -*-
"""不开窗口地验证桌面版的本地接口：直接把 app.py / exe 当助手进程跑（--api-server），
逐个打 /ping / /state /notify /latest /quit，全部走本机 127.0.0.1。

用法: python selftest_api.py [exe 或 app.py 路径] [端口]
"""
import json, os, subprocess, sys, time, urllib.parse, urllib.request

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

TITLE = '宿迁职业技术学院作息时间表'
target = sys.argv[1] if len(sys.argv) > 1 else '宿迁职业技术学院作息时间表.exe'
port = int(sys.argv[2]) if len(sys.argv) > 2 else 18999
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

        # 窗口状态信箱：读默认 → 写 → 读回 → 落盘
        st, body = call('/state')
        d0 = json.loads(body)
        print('  /state(读) HTTP %d  %s' % (st, body[:120]))
        if not (d0.get('ok') and isinstance(d0.get('state'), dict)
                and 'always_on_top' in d0['state']):
            print('    ✗ /state 读回来的结构不对'); rc = 1

        st, body = call('/state', top='1', close='exit')
        d1 = json.loads(body)
        print('  /state(写) HTTP %d  top=1 close=exit  → %s' % (st, body[:120]))
        disk = read_state()
        if not (d1.get('state', {}).get('always_on_top') is True
                and disk.get('always_on_top') is True
                and disk.get('close_mode') == 'exit'):
            print('    ✗ 写进去的状态没有落盘（文件里是 %r）' % (disk,)); rc = 1
        else:
            print('    ✓ 状态已落盘 win_state.json（主进程靠它把置顶应用到窗口上）')

        st, body = call('/state', top='0', close='tray')
        if json.loads(body).get('state', {}).get('always_on_top') is not False:
            print('    ✗ 取消置顶没生效：%s' % body[:120]); rc = 1

        st, body = call('/notify', title='exe 接口自检', body='不带令牌的通知测试')
        print('  /notify    HTTP %d  %s   ← ok:true 说明不再要求令牌' % (st, body))
        if '"ok": true' not in body and '"ok":true' not in body:
            rc = 1

        st, body = call('/latest')
        print('  /latest    HTTP %d  %s' % (st, body[:150]))
        if '"v": "v' not in body:
            rc = 1

        st, body = call('/quit')
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