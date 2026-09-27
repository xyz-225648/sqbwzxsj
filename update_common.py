# -*- coding: utf-8 -*-
"""桌面端更新公共模块：远程文件解析（version.txt / program.txt）、页面校验、版本比较、下载与 sha256 校验。

设计约定：
- version.txt / program.txt 保持「JS 赋值」格式（window.SQZY_LATEST={...}）不变 ——
  那是为了绕开浏览器 nosniff / CORS，不能改成纯 JSON；
- 这里负责把该格式**严格**解析成 dict：正则定位 JSON 块 → json.loads → 字段逐项校验，
  任何一步不合格都返回 None，调用方走容错分支，绝不让脏数据把更新流程打崩。
"""
import hashlib
import json
import os
import re
import urllib.parse
import urllib.request

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')

VALID_MARKERS = ('宿迁职业技术学院作息时间表', '<html')
MIN_HTML = 5000

_VER_RE = re.compile(r'v?([0-9]+)\.([0-9]+)\.([0-9]+)$')
_SHA_RE = re.compile(r'^[0-9a-fA-F]{64}$')


def norm_ver(v):
    """v2.4.3 → 20403；非法/缺段返回 -1。纯数字比较，避免字符串比较 2.10 < 2.9 这类坑。"""
    m = _VER_RE.match((v or '').strip())
    if not m:
        return -1
    return int(m.group(1)) * 10000 + int(m.group(2)) * 100 + int(m.group(3))


def page_ver(html):
    """页面里的 APP_VERSION 换算成可比较的数字（用于判断「新不新」）。"""
    m = re.search(r"var APP_VERSION = 'v([0-9]+)\.([0-9]+)\.([0-9]+)'", html or '')
    return (int(m.group(1)) * 10000 + int(m.group(2)) * 100 + int(m.group(3))) if m else -1


def is_valid_page(html):
    return bool(html) and len(html) >= MIN_HTML and all(m in html for m in VALID_MARKERS)


def _extract_json(text, var_prefix):
    """从 window.SQZY_XXX={...}; 里取出 JSON 文本。变量名可能带 _ 或数字后缀。"""
    m = re.search(var_prefix + r'\w*\s*=\s*(\{.*?\})\s*;', text or '', re.S)
    if not m:
        return None
    return m.group(1)


def parse_latest(text):
    """version.txt → {'v': 'v2.4.1', 'h': '...', 't': '...'}；不合格返回 None。"""
    try:
        raw = _extract_json(text, r'window\.SQZY_LATEST')
        if not raw:
            return None
        data = json.loads(raw)
        v = data.get('v')
        h = data.get('h')
        t = data.get('t')
        if not isinstance(v, str) or norm_ver(v) < 0:
            return None
        if not isinstance(h, str) or not re.match(r'^[0-9a-fA-F]{8,64}$', h or ''):
            return None
        if not isinstance(t, str) or not t:
            return None
        return {'v': v, 'h': h, 't': t}
    except Exception:
        return None


def parse_program(text):
    """program.txt → 程序本体更新信息 dict；字段类型/域名/sha256 逐项校验，不合格返回 None。"""
    try:
        raw = _extract_json(text, r'window\.SQZY_PROGRAM')
        if not raw:
            return None
        data = json.loads(raw)
        for key in ('exe', 'apk', 'tag'):
            if not isinstance(data.get(key), str) or norm_ver(data.get(key)) < 0:
                return None
        for key in ('exeUrl', 'apkUrl'):
            u = data.get(key)
            if not isinstance(u, str) or not u.startswith('https://gitee.com/'):
                return None
        for key in ('exeSha256', 'apkSha256'):
            if not isinstance(data.get(key), str) or not _SHA_RE.match(data.get(key)):
                return None
        for key in ('exeSize', 'apkSize'):
            if not isinstance(data.get(key), (int, float)) or data.get(key) < 100000:
                return None
        if not isinstance(data.get('t'), str) or not data.get('t'):
            return None
        mirrors = data.get('apkMirror')
        if not isinstance(mirrors, list) or not all(isinstance(m, str) and m.startswith('https://') for m in mirrors):
            return None
        return data
    except Exception:
        return None


def ascii_safe_url(url):
    """把 URL 里的非 ASCII 字符（比如中文资产名）转义掉再发请求。
    urllib 构造请求行时只接受 ASCII，裸中文会抛 UnicodeEncodeError。"""
    try:
        url.encode('ascii')
        return url
    except Exception:
        return urllib.parse.quote(url, safe=':/?&=%~#+[]@!$&()*,;')


def download_file(url, dest, sha256=None):
    """下载到本地并校验 sha256；返回 (ok, 说明)。"""
    url = ascii_safe_url(url)
    try:
        req = urllib.request.Request(url, headers={'User-Agent': UA})
        with urllib.request.urlopen(req, timeout=120) as r, open(dest, 'wb') as f:
            while True:
                chunk = r.read(1 << 16)
                if not chunk:
                    break
                f.write(chunk)
        size = os.path.getsize(dest)
        if size < 100000:
            return False, '文件太小（%d 字节）' % size
        if sha256:
            h = hashlib.sha256()
            with open(dest, 'rb') as f:
                for chunk in iter(lambda: f.read(1 << 20), b''):
                    h.update(chunk)
            if h.hexdigest().lower() != sha256.lower():
                return False, '校验不通过（下载可能被截断/篡改）'
        return True, '已下载 %d 字节' % size
    except Exception as exc:
        return False, '下载失败：%s' % str(exc)[:120]
