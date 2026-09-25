# -*- coding: utf-8 -*-
"""发布之后核验线上：网页和 version.txt 跟本地是否一致、下载链接是否可用。

用法: python check_live.py
"""
import base64, hashlib, json, os, re, sys, time, urllib.parse, urllib.request

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

RAW = 'https://gitee.com/xyz-225648/sqbwzxsj/raw/master/'
REL = 'https://gitee.com/xyz-225648/sqbwzxsj/releases/download/'
API_PAGE = 'https://gitee.com/api/v5/repos/xyz-225648/sqbwzxsj/contents/index.html?ref=master'
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


def get_once(url, timeout=60):
    """只试一次（不重试）：给"来源链"用，别在一个注定拿不到的来源上耗 36 秒"""
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except Exception:
        return None


def say(ok_flag, text):
    print('  %s %s' % ('✓' if ok_flag else '✗', text))
    if not ok_flag:
        bad.append(text)


local_page = open(PAGE, 'rb').read()
local_ver = open('release/version.txt', encoding='utf-8').read().strip()
app_v = re.search(r"var APP_VERSION = '([^']+)'", local_page.decode('utf-8')).group(1)
_tag = re.search(r"var RELEASE_TAG = '([^']+)'", local_page.decode('utf-8'))
tag = _tag.group(1) if _tag else app_v

# 页面本体跟两个壳的取法保持一致：发行版附件 → contents API → raw。
# 码云 raw 对 >~25 KB 的文件返回 451「The content may contain violation information」
# （实测 ≤24 KB 正常、≥39 KB 被挡，跟内容无关），页面有 148 KB —— 只查 raw 会一直假失败，
# 而且测不出用户到底拿不拿得到新页面。
_chain = [('发行版附件', REL + tag + '/index.html'),
          ('contents API', API_PAGE),
          ('raw', RAW + 'index.html')]
src, live_page = '(取不到)', b''
for _label, _url in _chain:
    _body = get_once(_url)
    if not _body:
        continue
    if _label == 'contents API':
        try:
            _body = base64.b64decode(json.loads(_body.decode('utf-8'))['content'].replace(chr(10), ''))
        except Exception:
            continue
    if _body:
        src, live_page = _label, _body
        break
say(live_page == local_page, '线上页面可取且与本地一致（来源 %s，%d 字节，md5 %s）'
    % (src, len(local_page), hashlib.md5(local_page).hexdigest()[:10]))
if src != '发行版附件':
    say(False, '发行版附件 index.html 拿不到 —— 发布时要把 release/index.html 也传成发行版附件（自动更新第一来源）')
if src != 'raw':
    print('    · 码云 raw 取不到 index.html（大文件被 451 挡）；壳会自动走发行版附件 / contents API')
live_ver = (get(RAW + 'version.txt') or b'').decode('utf-8').strip()
say(live_ver == local_ver, '线上 version.txt 与本地一致：%s' % live_ver[:80])
m = re.search(r'\{.*\}', live_ver, re.S)
live_v = json.loads(m.group(0))['v'] if m else '?'
say(live_v == app_v, '线上版本号 %s == 页面 APP_VERSION %s' % (live_v, app_v))

# 发布后必须同步更新 README（用户要求，也踩过：README 落后过两版）——这里机械校验，不靠记性
_readme = re.search(r'当前版本：\*\*(v[0-9.]+)\*\*', open('README.md', encoding='utf-8').read())
say(bool(_readme) and _readme.group(1) == app_v,
    'README 当前版本 %s == 页面 APP_VERSION %s' % ((_readme.group(1) if _readme else '没写'), app_v))
live_prog = (get(RAW + 'program.txt') or b'').decode('utf-8').strip()
local_prog = open('release/program.txt', encoding='utf-8').read().strip()
say(live_prog == local_prog, '线上 program.txt 与本地一致：%s' % live_prog[:80])
mp = re.search(r'\{.*\}', live_prog, re.S)
if mp:
    prog = json.loads(mp.group(0))
    say(prog.get('exe') == app_v and prog.get('apk') == app_v,
        'program.txt 里的程序本体版本 == 页面版本（%s / %s，页面 %s）'
        % (prog.get('exe'), prog.get('apk'), app_v))
for label, ext in (('安卓安装包', 'apk'), ('Windows 程序', 'exe')):
    name = '宿迁职业技术学院作息时间表.' + ext
    data = get(REL + tag + '/' + urllib.parse.quote(name))
    local = open(name, 'rb').read()
    say(data == local, '%s 下载可用且与本地一致（%s，md5 %s）'
        % (label, tag, hashlib.md5(local).hexdigest()[:10]))

# 闸门：APK 内部的 versionName 必须等于页面 APP_VERSION
# （v2.3.2 发布时 APK 编译失败、附件仍是旧构建，但哈希一致，所以只有比版本号才拦得住）
import glob as _glob, subprocess as _sub
_aapt = _glob.glob(os.path.join(".apkbuild", "tools", "sdk", "build-tools", "*", "aapt2.exe"))
_apk = "宿迁职业技术学院作息时间表.apk"
if _aapt and os.path.exists(_apk):
    try:
        _out = _sub.run([_aapt[0], "dump", "badging", _apk], capture_output=True, text=True,
                        encoding="utf-8", errors="replace").stdout
        _m = __import__("re").search(r"versionName=.(\d+\.\d+\.\d+)", _out or "")
        _vn = _m.group(1) if _m else "?"
        say(_vn == app_v.lstrip("v"), "APK 内部版本 %s == 页面 APP_VERSION %s" % (_vn, app_v))
    except Exception as _e:
        say(False, "APK 版本核验失败：%r" % (_e,))
else:
    print("  · 跳过 APK 版本核验（本机没有 aapt2 或没有 apk 文件）")
print('  check_live: %s' % ('PASS' if not bad else 'FAIL'))
sys.exit(1 if bad else 0)