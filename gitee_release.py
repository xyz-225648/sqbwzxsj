# -*- coding: utf-8 -*-
"""替换码云发行版里的附件（APK / EXE）。
用法: python gitee_release.py 本地文件[:附件名] [本地文件2 ...]"""
import hashlib, io, os, sys, urllib.error, urllib.parse, urllib.request

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

OWNER, REPO, REL = 'xyz-225648', 'sqbwzxsj', '1151710'
TOK = io.open('.gitee_token', encoding='utf-8').read().strip()
API = 'https://gitee.com/api/v5/repos/%s/%s/releases/%s/attach_files' % (OWNER, REPO, REL)

def md5(path):
    h = hashlib.md5()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()

def post_file(path, name):
    bnd = '----sqzy' + os.urandom(8).hex()
    data = open(path, 'rb').read()
    head = ('--%s\r\nContent-Disposition: form-data; name="file"; filename="%s"\r\n'
            'Content-Type: application/octet-stream\r\n\r\n' % (bnd, name)).encode('utf-8')
    body = head + data + ('\r\n--%s--\r\n' % bnd).encode('utf-8')
    req = urllib.request.Request(API + '?access_token=' + urllib.parse.quote(TOK), data=body, method='POST',
                                 headers={'Content-Type': 'multipart/form-data; boundary=' + bnd,
                                          'Content-Length': str(len(body))})
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            return r.status, r.read().decode('utf-8', 'replace')
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode('utf-8', 'replace')

targets = []
for a in sys.argv[1:]:
    local, _, name = a.partition(':')
    targets.append((local, name or os.path.basename(local)))

# 先删掉同名旧附件，再上传新的
with urllib.request.urlopen(API + '?access_token=' + urllib.parse.quote(TOK), timeout=60) as r:
    import json
    old = json.loads(r.read().decode('utf-8'))
want = set(n for _, n in targets)
for a in old:
    if a['name'] in want:
        durl = 'https://gitee.com/api/v5/repos/%s/%s/releases/%s/attach_files/%s?access_token=%s' % (
            OWNER, REPO, REL, a['id'], urllib.parse.quote(TOK))
        try:
            req = urllib.request.Request(durl, method='DELETE')
            with urllib.request.urlopen(req, timeout=60) as r:
                print('  删除旧附件 %s (id=%s) HTTP %s' % (a['name'], a['id'], r.status))
        except urllib.error.HTTPError as e:
            print('  ✗ 删除 %s 失败 HTTP %s %s' % (a['name'], e.code, e.read().decode('utf-8', 'replace')[:120]))

bad = 0
for local, name in targets:
    st, body = post_file(local, name)
    print('  上传 %s  %d 字节  md5=%s  HTTP %s' % (name, os.path.getsize(local), md5(local)[:10], st))
    if st not in (200, 201):
        print('    ✗ ' + body[:200]); bad += 1
sys.exit(1 if bad else 0)
