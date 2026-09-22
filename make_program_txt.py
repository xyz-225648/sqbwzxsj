# -*- coding: utf-8 -*-
"""生成 program.txt：程序本体（exe/apk）的版本 + 直链 + sha256。

为什么要带直链和校验值（issue IKHWKA #3）：
    exe 版「一键更新」要自己下载新版再旁路替换。下载地址和校验值写在 program.txt 里，
    页面把它交给 exe 的本地接口 /download，下载完先算 sha256 对不上就不替换 ——
    这样半截下载 / 被篡改的包不会把用户装好的程序弄坏。
"""
import hashlib
import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
BASES = {'exe': '宿迁职业技术学院作息时间表.exe', 'apk': '宿迁职业技术学院作息时间表.apk'}
# apk 还会作为仓库文件提交一份：gitee 附件 CDN 对 apk 固定返回 application/zip（改不了），
# 手机浏览器会按 MIME 改成 .apk.zip；仓库文件走支持 CORS 的代理 CDN，页面 fetch 成 blob
# 后自己命名保存，就能存成 .apk。路径里带版本号，免得代理缓存拿到旧包。
APK_REPO_NAME = 'apk/sqzy-timetable-%s.apk'


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def build(html_path, ver, stamp):
    src = io.open(html_path, encoding='utf-8').read()
    m = re.search(r"var RELEASE_TAG = '([^']+)'", src)
    tag = m.group(1) if m else ver
    base = 'https://gitee.com/xyz-225648/sqbwzxsj/releases/download/%s/' % tag
    info = {'exe': ver, 'apk': ver, 'tag': tag, 't': stamp}
    path = APK_REPO_NAME % tag
    info['apkRepoPath'] = path
    gh = 'https://raw.githubusercontent.com/xyz-225648/sqbwzxsj/' + tag + '/' + path
    info['apkMirror'] = ['https://cdn.jsdelivr.net/gh/xyz-225648/sqbwzxsj@' + tag + '/' + path,
                         'https://fastly.jsdelivr.net/gh/xyz-225648/sqbwzxsj@' + tag + '/' + path,
                         'https://gcore.jsdelivr.net/gh/xyz-225648/sqbwzxsj@' + tag + '/' + path,
                         'https://ghproxy.net/' + gh]
    for kind, name in BASES.items():
        info[kind + 'Url'] = base + name.replace(' ', '%20')
        local = os.path.join(os.path.dirname(os.path.abspath(html_path)), name)
        if os.path.exists(local):
            info[kind + 'Sha256'] = sha256_of(local)
            info[kind + 'Size'] = os.path.getsize(local)
    return info


def main():
    html, out, ver, stamp = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
    info = build(html, ver, stamp)
    os.makedirs(out, exist_ok=True)
    text = 'window.SQZY_PROGRAM=' + json.dumps(info, ensure_ascii=False) + ';' + chr(10)
    io.open(os.path.join(out, 'program.txt'), 'w', encoding='utf-8', newline=chr(10)).write(text)
    print(text.strip())
    for kind in BASES:
        if kind + 'Sha256' in info:
            print('   %s sha256=%s  %d 字节' % (kind, info[kind + 'Sha256'][:16] + '…', info[kind + 'Size']))
        else:
            print('   ⚠ 本地没有 %s，program.txt 里只有版本和直链（一键更新会退回手动下载）' % BASES[kind])


if __name__ == '__main__':
    main()
