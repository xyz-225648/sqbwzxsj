# -*- coding: utf-8 -*-
"""把本地文件同步到码云仓库（Gitee contents API，逐个文件提交）。

用法:  python gitee_sync.py "本地路径>仓库路径" ...    （省略 >仓库路径 时用文件名）
令牌:  环境变量 GITEE_TOKEN，或同目录下的 .gitee_token 文件（不会提交到仓库）
"""
import base64, io, json, os, sys, urllib.error, urllib.parse, urllib.request

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

OWNER, REPO, BRANCH = 'xyz-225648', 'sqbwzxsj', 'master'

def get_token():
    t = (os.environ.get('GITEE_TOKEN') or '').strip()
    if not t and os.path.exists('.gitee_token'):
        t = io.open('.gitee_token', encoding='utf-8').read().strip()
    if not t:
        print('  没有令牌：请设置 GITEE_TOKEN 或写 .gitee_token')
        sys.exit(2)
    return t

def api(method, path, tok, payload=None):
    url = ('https://gitee.com/api/v5/repos/%s/%s/contents/%s?access_token=%s'
           % (OWNER, REPO, urllib.parse.quote(path), urllib.parse.quote(tok)))
    if method == 'GET':
        req = urllib.request.Request(url + '&ref=' + BRANCH, method='GET')
    else:
        url += '&branch=' + BRANCH
        req = urllib.request.Request(url, method=method, data=json.dumps(payload).encode('utf-8'),
                                     headers={'Content-Type': 'application/json;charset=UTF-8'})
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return r.status, json.loads(r.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', 'replace')
        return e.code, body

def main():
    tok = get_token()
    pairs = []
    for a in sys.argv[1:]:
        local, _, remote = a.partition('>')
        pairs.append((local, remote or os.path.basename(local)))
    bad = 0
    for local, remote in pairs:
        if not os.path.exists(local):
            print('  ✗ 本地文件不存在: %s' % local); bad += 1; continue
        raw = open(local, 'rb').read()
        st, cur = api('GET', remote, tok)
        sha = cur.get('sha') if st == 200 and isinstance(cur, dict) else None
        action = '更新' if sha else '新建'
        msg = '同步 %s（%s）' % (remote, action)
        st2, res = api('PUT' if sha else 'POST', remote, tok,
                       {'access_token': tok, 'content': base64.b64encode(raw).decode(),
                        'message': msg, 'sha': sha, 'branch': BRANCH} if sha else
                       {'access_token': tok, 'content': base64.b64encode(raw).decode(),
                        'message': msg, 'branch': BRANCH})
        if st2 in (200, 201):
            cs = (res.get('commit') or {}).get('sha', '')[:8] if isinstance(res, dict) else ''
            print('  ✓ %-28s %s  %d 字节  commit %s' % (remote, action, len(raw), cs))
        else:
            print('  ✗ %-28s HTTP %s  %s' % (remote, st2, str(res)[:180])); bad += 1
    sys.exit(1 if bad else 0)

main()
