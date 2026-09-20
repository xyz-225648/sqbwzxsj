# -*- coding: utf-8 -*-
"""不开窗口地验证 exe 的本地接口：直接把 exe 当助手进程跑（--api-server），
逐个打 /ping /notify /latest /quit，全部走本机 127.0.0.1，不带任何令牌。
用法: python selftest_api.py [exe路径] [端口]"""
import json, os, subprocess, sys, time, urllib.parse, urllib.request

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

exe = sys.argv[1] if len(sys.argv) > 1 else '宿迁职业技术学院作息时间表.exe'
port = int(sys.argv[2]) if len(sys.argv) > 2 else 18999

env = dict(os.environ)
env.pop('_MEIPASS2', None)
p = subprocess.Popen([exe, '--api-server', str(port)], env=env,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
base = 'http://127.0.0.1:%d' % port

def call(path, **q):
    url = base + path + (('?' + urllib.parse.urlencode(q)) if q else '')
    with urllib.request.urlopen(url, timeout=20) as r:
        return r.status, r.read().decode('utf-8')

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
        print('  ✗ 助手进程 15 秒内没起来（端口 %d）' % port)
        rc = 1
    else:
        st, body = call('/')
        ok_page = ('id="nowBar"' in body) and ("APP_VERSION = 'v" in body)
        print('  GET /      HTTP %d  %d 字节  页面自检 %s  ← exe 现在用 http 把页面发给窗口'
              % (st, len(body.encode('utf-8')), 'OK' if ok_page else '失败'))
        if not ok_page:
            rc = 1
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
        print('  ✗ /quit 之后助手进程还在（%.1fs 未退出）' % 10)
        p.kill(); rc = 1
    else:
        print('  助手进程已退出，返回码 %s' % p.returncode)
print('  selftest: %s' % ('PASS' if rc == 0 else 'FAIL'))
sys.exit(rc)
