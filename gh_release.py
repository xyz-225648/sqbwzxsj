# -*- coding: utf-8 -*-
"""GitHub 发行版（Releases）同步：从 CHANGELOG.md 取说明，上传 exe/apk/截图附件。

用法:
  python gh_release.py sync     建/更新全部发行版，并给最新版上传附件
  python gh_release.py list     列出 GitHub 上的发行版与附件
令牌: 环境变量 GITHUB_TOKEN（GitHub Actions 里自动有），或同目录下的 .github_token
附件来源: 本地有就用本地；本地没有（Actions 环境）就从 Gitee 发行版下载。
"""
import base64, io, json, mimetypes, os, sys, tempfile, time, urllib.error, urllib.parse, urllib.request

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
TOK = (os.environ.get('GITHUB_TOKEN') or '').strip() \
    or io.open('.github_token', encoding='utf-8').read().strip()
OWNER, REPO = 'xyz-225648', 'sqbwzxsj'
TAGS = ['v1.0', 'v2.0.1', 'v2.1.0', 'v2.1.1', 'v2.1.2', 'v2.1.3', 'v2.2.0', 'v2.2.1', 'v2.2.2', 'v2.3.0', 'v2.3.1', 'v2.3.2', 'v2.3.3', 'v2.3.4', 'v2.3.5', 'v2.3.6', 'v2.3.7', 'v2.3.8', 'v2.3.9', 'v2.3.10', 'v2.3.11', 'v2.3.12', 'v2.3.13', 'v2.3.14', 'v2.3.15', 'v2.4.1', 'v2.4.2', 'v2.4.3']   # 最后一个当"最新版"，附件挂在它上面
LATEST = TAGS[-1]
# 附件名用 ASCII：GitHub 会把非 ASCII 名字削成 default.exe / -.png（踩过）
ASSETS = [
    ('宿迁职业技术学院作息时间表.exe', 'sqzy-timetable-%s-windows.exe' % LATEST,
     'https://gitee.com/xyz-225648/sqbwzxsj/releases/download/%s/%%E5%%AE%%BF%%E8%%BF%%81%%E8%%81%%8C%%E4%%B8%%9A%%E6%%8A%%80%%E6%%9C%%AF%%E5%%AD%%A6%%E9%%99%%A2%%E4%%BD%%9C%%E6%%81%%AF%%E6%%97%%B6%%E9%%97%%B4%%E8%%A1%%A8.exe' % LATEST),
    ('宿迁职业技术学院作息时间表.apk', 'sqzy-timetable-%s-android.apk' % LATEST,
     'https://gitee.com/xyz-225648/sqbwzxsj/releases/download/%s/%%E5%%AE%%BF%%E8%%BF%%81%%E8%%81%%8C%%E4%%B8%%9A%%E6%%8A%%80%%E6%%9C%%AF%%E5%%AD%%A6%%E9%%99%%A2%%E4%%BD%%9C%%E6%%81%%AF%%E6%%97%%B6%%E9%%97%%B4%%E8%%A1%%A8.apk' % LATEST),
    ('宿迁职业技术学院作息时间表.png', 'sqzy-timetable-desktop.png', None),
    ('宿迁职业技术学院作息时间表-手机版.png', 'sqzy-timetable-mobile.png', None)]
NOTE = ('> 本仓库是**主仓库**（开发、PR、发行都在这里）；'
        '[Gitee 仓库](https://gitee.com/xyz-225648/sqbwzxsj) 是镜像，两边双向同步。' + chr(10) * 2)


def asset_file(local, url):
    """本地有就直接用；没有（GitHub Actions 环境）就从 Gitee 下载到临时目录。"""
    if os.path.exists(local):
        return local
    if not url:
        return None
    tmp = os.path.join(tempfile.gettempdir(), os.path.basename(local))
    if os.path.exists(tmp):
        return tmp
    print('    · 本地没有 %s，从 Gitee 下载…' % os.path.basename(local))
    try:
        with urllib.request.urlopen(url, timeout=600) as r, open(tmp, 'wb') as f:
            while True:
                chunk = r.read(1 << 16)
                if not chunk:
                    break
                f.write(chunk)
        return tmp
    except Exception as exc:
        print('    ✗ 下载失败 %r' % exc)
        return None


def api(method, path, payload=None, timeout=120):
    data = json.dumps(payload).encode('utf-8') if payload is not None else None
    r = urllib.request.Request('https://api.github.com' + path, data=data, method=method, headers={
        'Authorization': 'token ' + TOK, 'Accept': 'application/vnd.github+json',
        'User-Agent': 'sqzy-rel', 'X-GitHub-Api-Version': '2022-11-28',
        'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            b = resp.read().decode('utf-8', 'replace')
            return resp.status, (json.loads(b) if b.strip() else {})
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode('utf-8', 'replace')[:300]


def changelog(tag):
    text = io.open('CHANGELOG.md', encoding='utf-8').read()
    out, on = [], False
    for ln in text.split('\n'):
        if ln.startswith('## '):
            if on:
                break
            on = ln[3:].strip() == tag
            if on:
                continue
        if on:
            if ln.strip() == '---':
                break
            out.append(ln)
    return '\n'.join(out).strip()


def find_release(tag):
    st, items = api('GET', '/repos/%s/%s/releases?per_page=30' % (OWNER, REPO))
    if st == 200:
        for it in items:
            if it.get('tag_name') == tag:
                return it
    return None


def upload_asset(rel_id, path, label):
    name = label if label.endswith(('.exe', '.apk', '.png')) else os.path.basename(path)
    st, olds = api('GET', '/repos/%s/%s/releases/%s/assets' % (OWNER, REPO, rel_id))
    if st == 200:
        for a in olds:
            if a['name'] == name:
                print('    · 附件 %s 已存在（%d 字节），跳过' % (name, a.get('size', 0)))
                return True
    raw = io.open(path, 'rb').read()
    url = ('https://uploads.github.com/repos/%s/%s/releases/%s/assets?name=%s'
           % (OWNER, REPO, rel_id, urllib.parse.quote(name)))
    req = urllib.request.Request(url, data=raw, method='POST', headers={
        'Authorization': 'token ' + TOK, 'Content-Type': 'application/octet-stream',
        'Accept': 'application/vnd.github+json', 'User-Agent': 'sqzy-rel',
        'Content-Length': str(len(raw))})
    try:
        with urllib.request.urlopen(req, timeout=900) as resp:
            print('    ✓ %-34s %9d 字节  HTTP %s' % (name, len(raw), resp.status))
            return True
    except urllib.error.HTTPError as e:
        print('    ✗ %s 上传失败 HTTP %s %s' % (name, e.code, e.read().decode('utf-8', 'replace')[:200]))
        return False


def cmd_sync():
    bad = 0
    for tag in TAGS:
        body = NOTE + changelog(tag)
        if tag != LATEST:
            body += ('\n\n### 附件\n\n本页只作版本记录（安装包请见最新版 **%s**，'
                     '或 [Gitee 发行版](https://gitee.com/xyz-225648/sqbwzxsj/releases)）。' % LATEST)
        else:
            body += '\n\n### 附件\n\n最新安装包见下方 Assets（exe 免安装、apk 直接覆盖安装）。'
        name = '宿迁职业技术学院作息时间表 ' + tag
        rel = find_release(tag)
        if rel:
            st, res = api('PATCH', '/repos/%s/%s/releases/%s' % (OWNER, REPO, rel['id']),
                          {'name': name, 'body': body})
            print('  %s 发行版 %s 已更新（HTTP %s）' % ('✓' if st == 200 else '✗', tag, st))
        else:
            st, res = api('POST', '/repos/%s/%s/releases' % (OWNER, REPO),
                          {'tag_name': tag, 'name': name, 'body': body,
                           'draft': False, 'prerelease': False})
            print('  %s 发行版 %s 已创建（HTTP %s）%s' % ('✓' if st in (200, 201) else '✗', tag, st,
                                                     '' if st in (200, 201) else str(res)[:200]))
            rel = res
        if st not in (200, 201):
            bad += 1
            continue
        if tag == LATEST:
            for path, label, url in ASSETS:
                src = asset_file(path, url)
                if not src:
                    print('    · 拿不到 %s，跳过' % label)
                    continue
                if not upload_asset(rel['id'], src, label):
                    bad += 1
    return 1 if bad else 0


def cmd_list():
    st, items = api('GET', '/repos/%s/%s/releases?per_page=30' % (OWNER, REPO))
    if st != 200:
        print('  ✗ HTTP %s %s' % (st, str(items)[:200])); return 1
    for it in items:
        print('  %-8s %-28s 附件 %d 个' % (it['tag_name'], it.get('name'), len(it.get('assets') or [])))
        for a in it.get('assets') or []:
            print('      %-34s %9d 字节  下载 %d 次' % (a['name'], a['size'], a.get('download_count', 0)))
    return 0


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'sync'
    if cmd == 'sync':
        rc = cmd_sync()
    elif cmd == 'list':
        rc = cmd_list()
    else:
        print(__doc__); rc = 2
    print('  gh_release: %s' % ('OK' if rc == 0 else 'FAIL'))
    sys.exit(rc)