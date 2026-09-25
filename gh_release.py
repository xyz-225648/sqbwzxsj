# -*- coding: utf-8 -*-
"""GitHub 发行版（Releases）镜像：从 CHANGELOG.md 取说明，上传 exe/apk/截图附件。

用法:
  python gh_release.py sync     建/更新 v1.0、v2.0.1、v2.1.0，并给最新版上传附件
  python gh_release.py list     列出 GitHub 上的发行版与附件
令牌: 环境变量 GITHUB_TOKEN，或同目录下的 .github_token
"""
import base64, io, json, mimetypes, os, sys, time, urllib.error, urllib.parse, urllib.request

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
TOK = io.open('.github_token', encoding='utf-8').read().strip()
OWNER, REPO = 'xyz-225648', 'sqbwzxsj'
TAGS = ['v1.0', 'v2.0.1', 'v2.1.0', 'v2.1.1', 'v2.1.2', 'v2.1.3', 'v2.2.0', 'v2.2.1', 'v2.2.2', 'v2.3.0', 'v2.3.1', 'v2.3.2', 'v2.3.3', 'v2.3.4', 'v2.3.5', 'v2.3.6', 'v2.3.7', 'v2.3.8', 'v2.3.9', 'v2.3.10', 'v2.3.11', 'v2.3.12', 'v2.3.13', 'v2.3.14', 'v2.3.15']   # 最后一个当"最新版"，附件挂在它上面
LATEST = TAGS[-1]
# 附件名用 ASCII：GitHub 会把非 ASCII 名字削成 default.exe / -.png（踩过）
ASSETS = [('宿迁职业技术学院作息时间表.exe', 'sqzy-timetable-v2.3.15-windows.exe'),
          ('宿迁职业技术学院作息时间表.apk', 'sqzy-timetable-v2.3.15-android.apk'),
          ('宿迁职业技术学院作息时间表.png', 'sqzy-timetable-desktop.png'),
          ('宿迁职业技术学院作息时间表-手机版.png', 'sqzy-timetable-mobile.png')]
NOTE = ('> 本仓库是 [Gitee 主仓库](https://gitee.com/xyz-225648/sqbwzxsj) 的镜像，'
        '两边双向同步；产品改动在 Gitee 走 PR，这里也能提，合并后会同步回去。' + chr(10) * 2)


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
            for path, label in ASSETS:
                if not os.path.exists(path):
                    print('    · 本地没有 %s，跳过' % path)
                    continue
                if not upload_asset(rel['id'], path, label):
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