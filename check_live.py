# -*- coding: utf-8 -*-
"""发布之后核验线上：网页和 version.txt 跟本地是否一致、下载链接是否可用。

用法: python check_live.py
"""
import hashlib, json, os, re, sys, time, urllib.parse, urllib.request

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

RAW = 'https://gitee.com/xyz-225648/sqbwzxsj/raw/master/'
REL = 'https://gitee.com/xyz-225648/sqbwzxsj/releases/download/'
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36',
      'Cache-Control': 'no-cache'}
PAGE = '宿迁职业技术学院作息时间表.html'
bad = []


def get(url, tries=6, timeout=60):
    """码云 CDN 刚推完会 451 / 缓存慢一拍，所以带时间戳重试"""
    for i in range(tries):
        try:
            req = urllib.request.Request(
                url + ('&' if '?' in url else '?') + 't=%d' % int(time.time() * 1000), headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as exc:
            print('    第%d次取不到（%s），6 秒后重试' % (i + 1, getattr(exc, 'code', exc)))
            time.sleep(6)
    return None


def say(ok_flag, text):
    print('  %s %s' % ('✓' if ok_flag else '✗', text))
    if not ok_flag:
        bad.append(text)


local_page = open(PAGE, 'rb').read()
local_ver = open('release/version.txt', encoding='utf-8').read().strip()
live_page = get(RAW + 'index.html')
live_ver = (get(RAW + 'version.txt') or b'').decode('utf-8').strip()
say(live_page == local_page, '线上 index.html 与本地一致（%d 字节，md5 %s）'
    % (len(local_page), hashlib.md5(local_page).hexdigest()[:10]))
say(live_ver == local_ver, '线上 version.txt 与本地一致：%s' % live_ver[:80])
m = re.search(r'\{.*\}', live_ver, re.S)
live_v = json.loads(m.group(0))['v'] if m else '?'
app_v = re.search(r"var APP_VERSION = '([^']+)'", local_page.decode('utf-8')).group(1)
say(live_v == app_v, '线上版本号 %s == 页面 APP_VERSION %s' % (live_v, app_v))
live_prog = (get(RAW + 'program.txt') or b'').decode('utf-8').strip()
local_prog = open('release/program.txt', encoding='utf-8').read().strip()
say(live_prog == local_prog, '线上 program.txt 与本地一致：%s' % live_prog[:80])
mp = re.search(r'\{.*\}', live_prog, re.S)
if mp:
    prog = json.loads(mp.group(0))
    say(prog.get('exe') == app_v and prog.get('apk') == app_v,
        'program.txt 里的程序本体版本 == 页面版本（%s / %s，页面 %s）'
        % (prog.get('exe'), prog.get('apk'), app_v))
tag = re.search(r"var RELEASE_TAG = '([^']+)'", local_page.decode('utf-8')).group(1)
for label, ext in (('安卓安装包', 'apk'), ('Windows 程序', 'exe')):
    name = '宿迁职业技术学院作息时间表.' + ext
    data = get(REL + tag + '/' + urllib.parse.quote(name))
    local = open(name, 'rb').read()
    say(data == local, '%s 下载可用且与本地一致（%s，md5 %s）'
        % (label, tag, hashlib.md5(local).hexdigest()[:10]))
print('  check_live: %s' % ('PASS' if not bad else 'FAIL'))
sys.exit(1 if bad else 0)