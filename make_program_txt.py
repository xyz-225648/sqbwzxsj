# -*- coding: utf-8 -*-
"""生成 program.txt：程序本体（exe/apk）的版本 + 直链 + sha256。

程序本体版本与页面版本分开算：
  - 页面版本（页面里的 APP_VERSION → version.txt）只管「热更新」；
  - 这里的 exe/apk 版本读 app.py 的 SHELL_VERSION 和安卓 AndroidManifest.xml 的
    versionName —— **只有重打安装包时才升**。纯改页面 / calendar.txt 不会动它，
    也就不会提示用户去重下安装包。

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
import urllib.parse

ROOT = os.path.dirname(os.path.abspath(__file__))
BASES = {'exe': '宿迁职业技术学院作息时间表.exe', 'apk': '宿迁职业技术学院作息时间表.apk'}
# apk 还会作为仓库文件提交一份：gitee 附件 CDN 对 apk 固定返回 application/zip（改不了），
# 手机浏览器会按 MIME 改成 .apk.zip；仓库文件走支持 CORS 的代理 CDN，页面 fetch 成 blob
# 后自己命名保存，就能存成 .apk。路径里带版本号，免得代理缓存拿到旧包。
APK_REPO_NAME = 'apk/sqzy-timetable-%s.apk'


def norm_ver(v):
    m = re.search(r'v?(\d+)\.(\d+)\.(\d+)', str(v or ''))
    return ('v%s.%s.%s' % (m.group(1), m.group(2), m.group(3))) if m else ''


def read_text(path):
    try:
        with io.open(path, encoding='utf-8') as f:
            return f.read()
    except Exception:
        return None


def exe_version():
    src = read_text(os.path.join(ROOT, 'app.py'))
    m = re.search(r"SHELL_VERSION = '([^']+)'", src or '')
    return norm_ver(m.group(1) if m else '')


def apk_version():
    src = read_text(os.path.join(ROOT, '.apkbuild', 'app', 'AndroidManifest.xml'))
    m = re.search(r'android:versionName="([^"]+)"', src or '')
    return norm_ver(m.group(1) if m else '')


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def build(html_path, page_ver, stamp):
    """生成 program.txt 信息。page_ver 只用来打印对照，不参与 exe/apk 版本计算。"""
    exe = exe_version()
    apk = apk_version()
    if not exe:
        raise SystemExit('✗ 读不到 app.py 里的 SHELL_VERSION —— 程序本体版本必须明确，不能拿页面版本充数')
    if not apk:
        raise SystemExit('✗ 读不到 .apkbuild/app/AndroidManifest.xml 里的 versionName')
    if exe != apk:
        raise SystemExit('✗ exe 版本 %s 与 apk 版本 %s 不一致：现在一个发行版 tag 同时装两个包，两者必须一起升' % (exe, apk))
    tag = exe
    base = 'https://gitee.com/xyz-225648/sqbwzxsj/releases/download/%s/' % tag
    info = {'exe': exe, 'apk': apk, 'tag': tag, 't': stamp}
    path = APK_REPO_NAME % tag
    info['apkRepoPath'] = path
    # 线路顺序：先用 tag（不可变，最稳），再用 master 兜底。
    # 为什么要 master 兜底：tag 是**建文件之前**打的，tag 的树里永远不会有这个文件
    # （v2.2.1 就踩了这个：@v2.2.1 永久 404，而文件早已在 master 上）。
    # master 会随仓库变，所以页面拿到字节后**必须**核对 apkSha256 —— 校验不过就换下一条线路。
    # ?t=<sha 前 8 位> 是给 CDN 的缓存打散键：新版本换新 URL，免得撞上 12 小时的旧缓存。
    for kind, name in BASES.items():
        info[kind + 'Url'] = base + urllib.parse.quote(name)   # 资产名必须百分号编码，中文名不编码会让壳的请求在 ASCII 编码处炸掉
        local = os.path.join(ROOT, name)
        if os.path.exists(local):
            info[kind + 'Sha256'] = sha256_of(local)
            info[kind + 'Size'] = os.path.getsize(local)
    # 线路要在 sha256 算完之后再拼（?t= 用的是 apk 的 sha 前缀，拼早了就是空的）
    def jd(host, ref):
        return 'https://%s/gh/xyz-225648/sqbwzxsj@%s/%s' % (host, ref, path)
    sha8 = (info.get('apkSha256') or '')[:8]
    info['apkMirror'] = [jd('cdn.jsdelivr.net', tag),
                         jd('fastly.jsdelivr.net', tag),
                         jd('gcore.jsdelivr.net', tag),
                         jd('cdn.jsdelivr.net', 'master') + '?t=' + sha8,
                         jd('fastly.jsdelivr.net', 'master') + '?t=' + sha8,
                         'https://ghproxy.net/https://raw.githubusercontent.com/xyz-225648/sqbwzxsj/master/' + path]
    page = norm_ver(page_ver)
    if page and page != exe:
        print('   · 页面版本 %s 与程序本体版本 %s 分开算：纯页面/数据变更只热更，不提示重下安装包' % (page, exe))
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
