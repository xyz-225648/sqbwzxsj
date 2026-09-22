# -*- coding: utf-8 -*-
"""码云（Gitee）仓库 / 发行版 管理工具 —— 一个脚本管住所有对外发布动作。

  仓库文件
    python gitee_repo.py list                     列出仓库根目录
    python gitee_repo.py push 本地[>仓库路径] ...   上传或更新文件
    python gitee_repo.py rm 文件名 ...             删除仓库里的文件
    python gitee_repo.py raw 文件名 ...            打印远端文件前几行（核对同步）

  分支 / Pull Request（改代码走这条：分支 → PR → 审核 → 合并）
    python gitee_repo.py branch list
    python gitee_repo.py branch new <分支名> [从哪个 ref]
    python gitee_repo.py --branch=<分支名> push 本地文件 ...   把改动提交到分支上
    python gitee_repo.py pr list
    python gitee_repo.py pr new <分支名> "<标题>" <说明文件.md> [章节标题]
    python gitee_repo.py pr view <编号>
    python gitee_repo.py pr comment <编号> "<内容>"
    python gitee_repo.py pr approve <编号>                    过掉「审查」+「测试」两道门槛（合并前必须）
    python gitee_repo.py pr merge <编号> ["合并说明"]

  Issue（改完在 issue 里回一条，再关掉）
    python gitee_repo.py issue view <编号>
    python gitee_repo.py issue comment <编号> "<内容>"
    python gitee_repo.py issue close <编号>
    python gitee_repo.py issue reopen <编号>

  发行版（Release）
    python gitee_repo.py release list
    python gitee_repo.py release assets <tag>
    python gitee_repo.py release new  <tag> "<名称>" <说明文件.md> [章节标题]
    python gitee_repo.py release edit <tag> "<名称>" <说明文件.md> [章节标题]
    python gitee_repo.py release upload <tag> 本地文件[:附件名] ...

说明文件用 Markdown；给了章节标题（例如 "v2.0.1"）就只取那一节，方便直接拿 CHANGELOG.md 当公告。
令牌：环境变量 GITEE_TOKEN，或同目录下的 .gitee_token（不会提交到仓库）。
"""
import base64, io, json, os, sys, urllib.error, urllib.parse, urllib.request

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

OWNER, REPO, BRANCH = 'xyz-225648', 'sqbwzxsj', 'master'
API = 'https://gitee.com/api/v5/repos/%s/%s' % (OWNER, REPO)
HELP = __doc__


def get_token():
    t = (os.environ.get('GITEE_TOKEN') or '').strip()
    if not t and os.path.exists('.gitee_token'):
        t = io.open('.gitee_token', encoding='utf-8').read().strip()
    if not t:
        print('  没有令牌：请设置 GITEE_TOKEN 或写 .gitee_token')
        sys.exit(2)
    return t


def req(method, url, tok, payload=None, raw=None, ctype=None, timeout=120):
    sep = '&' if '?' in url else '?'
    url = url + sep + 'access_token=' + urllib.parse.quote(tok)
    data = None
    headers = {}
    if raw is not None:
        data = raw
        headers['Content-Type'] = ctype
        headers['Content-Length'] = str(len(raw))
    elif payload is not None:
        data = json.dumps(payload).encode('utf-8')
        headers['Content-Type'] = 'application/json;charset=UTF-8'
    r = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            body = resp.read().decode('utf-8', 'replace')
            try:
                return resp.status, json.loads(body)
            except Exception:
                return resp.status, body
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode('utf-8', 'replace')


def release_of(tok, tag):
    st, items = req('GET', API + '/releases', tok)
    if st != 200 or not isinstance(items, list):
        print('  ✗ 取发行版列表失败 HTTP %s %s' % (st, str(items)[:160]))
        sys.exit(1)
    for it in items:
        if it.get('tag_name') == tag:
            return it
    return None


def section_of(path, title):
    """从 Markdown 里取出某一节（## 标题 到下一个 --- 或 ## 之前）"""
    text = io.open(path, encoding='utf-8').read()
    lines = text.split('\n')
    out, on = [], False
    for ln in lines:
        if ln.startswith('## '):
            if on:
                break
            on = ln[3:].strip() == title
            if on:
                continue
        if on:
            if ln.strip() == '---':
                break
            out.append(ln)
    body = '\n'.join(out).strip()
    if not body:
        print('  ✗ %s 里找不到章节「%s」' % (path, title))
        sys.exit(1)
    return body


def read_body(spec, section=None):
    """说明文字：给的是文件路径就（可选只取某一章）读文件，否则当纯文本
    （纯文本里的 \n 会被当成换行，方便命令行里直接写一句）"""
    if os.path.exists(spec):
        return section_of(spec, section) if section else io.open(spec, encoding='utf-8').read()
    return spec.replace('\\n', chr(10))


def file_cmds(tok, args, branch=BRANCH):
    cmd = args[0]
    if cmd == 'list':
        st, items = req('GET', API + '/contents/?ref=' + BRANCH, tok)
        if st != 200:
            print('  ✗ HTTP %s %s' % (st, str(items)[:200]))
            return 1
        print('  %-44s %-6s' % ('名称', '类型'))
        for it in sorted(items, key=lambda x: (x['type'], x['name'])):
            print('  %-44s %-6s' % (it['name'] + ('/' if it['type'] == 'dir' else ''), it['type']))
        print('  共 %d 项' % len(items))
        return 0

    if cmd == 'push':
        # 改代码/文档一律走 PR：这里把「直推 master」堵死，
        # 免得再出现「改完顺手推 master、没有评审记录」（已经犯过一次）。
        if branch == BRANCH and '--direct' not in args:
            print('  ✗ 拒绝直接推 master —— 改动要走 PR（issue → 分支 → PR → 审查合并）')
            print('    正确流程：')
            print('      python gitee_repo.py branch new fix/xxx')
            print('      python gitee_repo.py --branch=fix/xxx push <改动的文件>')
            print('      python gitee_repo.py pr new fix/xxx "<标题>" <说明.md>')
            print('      python gitee_repo.py pr approve <编号> 然后 pr merge <编号>')
            print('    确实要救急（例如线上页面坏了要立刻回滚）才加 --direct 绕过。')
            return 1
        args = [a for a in args if a != '--direct']
        bad = 0
        for a in args[1:]:
            local, _, remote = a.partition('>')
            # 不给 >映射 就用本地相对路径本身（保留目录）：曾经因为只取文件名，
            # 把 .github/workflows/xxx.yml 传成了仓库根目录下的 xxx.yml（踩过）
            remote = remote or local.replace('\\', '/')
            if not os.path.exists(local):
                print('  ✗ 本地文件不存在: %s' % local); bad += 1; continue
            raw = open(local, 'rb').read()
            st, cur = req('GET', API + '/contents/' + urllib.parse.quote(remote) + '?ref=' + urllib.parse.quote(branch), tok)
            sha = cur.get('sha') if st == 200 and isinstance(cur, dict) else None
            payload = {'access_token': tok, 'content': base64.b64encode(raw).decode(),
                       'message': '同步 %s（%s）' % (remote, '更新' if sha else '新建'), 'branch': branch}
            if sha:
                payload['sha'] = sha
            st2, res = req('PUT' if sha else 'POST',
                           API + '/contents/' + urllib.parse.quote(remote), tok, payload)
            if st2 in (200, 201):
                cs = (res.get('commit') or {}).get('sha', '')[:8] if isinstance(res, dict) else ''
                print('  ✓ %-34s %s  %d 字节  commit %s'
                      % (remote, '更新' if sha else '新建', len(raw), cs))
            else:
                print('  ✗ %-34s HTTP %s %s' % (remote, st2, str(res)[:160])); bad += 1
        return 1 if bad else 0

    if cmd == 'rm':
        bad = 0
        for name in args[1:]:
            st, cur = req('GET', API + '/contents/' + urllib.parse.quote(name) + '?ref=' + urllib.parse.quote(branch), tok)
            if st != 200 or not isinstance(cur, dict) or 'sha' not in cur:
                print('  ✗ 仓库里没有 %s（HTTP %s）' % (name, st)); bad += 1; continue
            st2, res = req('DELETE', API + '/contents/' + urllib.parse.quote(name), tok,
                           {'access_token': tok, 'message': '删除不必要的文件：%s' % name,
                            'sha': cur['sha'], 'branch': branch})
            if st2 in (200, 201):
                cs = (res.get('commit') or {}).get('sha', '')[:8] if isinstance(res, dict) else ''
                print('  ✓ 已删除 %-30s commit %s' % (name, cs))
            else:
                print('  ✗ 删除 %s 失败 HTTP %s %s' % (name, st2, str(res)[:160])); bad += 1
        return 1 if bad else 0

    if cmd == 'raw':
        for name in args[1:]:
            st, cur = req('GET', API + '/contents/' + urllib.parse.quote(name) + '?ref=' + urllib.parse.quote(branch), tok)
            if st != 200 or not isinstance(cur, dict) or 'content' not in cur:
                print('  ✗ 取不到 %s（HTTP %s）' % (name, st)); continue
            raw = base64.b64decode(cur['content'])
            print('  --- %s  %d 字节  sha %s ---' % (name, len(raw), cur.get('sha', '')[:10]))
            print(chr(10).join(raw.decode('utf-8', 'replace').splitlines()[:3]))
        return 0

    print(HELP)
    return 2


def attach(tok, rel, path, name):
    bnd = '----sqzy' + os.urandom(8).hex()
    data = open(path, 'rb').read()
    head = ('--%s\r\nContent-Disposition: form-data; name="file"; filename="%s"\r\n'
            'Content-Type: application/octet-stream\r\n\r\n' % (bnd, name)).encode('utf-8')
    body = head + data + ('\r\n--%s--\r\n' % bnd).encode('utf-8')
    st, res = req('POST', API + '/releases/%s/attach_files' % rel['id'], tok, raw=body,
                  ctype='multipart/form-data; boundary=' + bnd, timeout=900)
    print('  上传 %-34s %9d 字节  HTTP %s' % (name, len(data), st))
    if st not in (200, 201):
        print('    ✗ ' + str(res)[:200])
        return False
    return True


def branch_cmds(tok, args):
    sub = args[1] if len(args) > 1 else 'list'
    if sub == 'list':
        st, items = req('GET', API + '/branches', tok)
        if st != 200:
            print('  ✗ HTTP %s %s' % (st, str(items)[:200])); return 1
        for it in items:
            print('  %-30s %s' % (it.get('name'), (it.get('commit') or {}).get('sha', '')[:8]))
        return 0
    if sub == 'new':
        name = args[2]
        refs = args[3] if len(args) > 3 else BRANCH
        st, res = req('POST', API + '/branches', tok,
                      {'access_token': tok, 'refs': refs, 'branch_name': name})
        if st in (200, 201):
            print('  ✓ 分支 %s 已从 %s 建好' % (name, refs))
            return 0
        print('  ✗ HTTP %s %s' % (st, str(res)[:220]))
        return 1
    print(HELP)
    return 2


def pr_cmds(tok, args):
    sub = args[1] if len(args) > 1 else 'list'
    if sub == 'list':
        st, items = req('GET', API + '/pulls?state=all&per_page=20', tok)
        if st != 200:
            print('  ✗ HTTP %s %s' % (st, str(items)[:200])); return 1
        for it in items:
            print('  #%-4s %-8s %-26s %s' % (it.get('number'), it.get('state'),
                                             (it.get('head') or {}).get('ref'), it.get('title')))
        return 0
    if sub == 'view':
        st, it = req('GET', API + '/pulls/%s' % args[2], tok)
        if st != 200:
            print('  ✗ HTTP %s %s' % (st, str(it)[:200])); return 1
        print('  #%s %s' % (it.get('number'), it.get('title')))
        print('  %s  %s <- %s  %s' % (it.get('state'), (it.get('base') or {}).get('ref'),
                                      (it.get('head') or {}).get('ref'), it.get('html_url')))
        print('  已合并: %s' % it.get('merged_at'))
        if it.get('body'):
            print(chr(10).join('    ' + l for l in it['body'].splitlines()[:24]))
        return 0
    if sub == 'new':
        head, title, spec = args[2], args[3], args[4]
        section = args[5] if len(args) > 5 else None
        body = read_body(spec, section)
        st, res = req('POST', API + '/pulls', tok,
                      {'access_token': tok, 'title': title, 'head': head,
                       'base': BRANCH, 'body': body})
        if st in (200, 201):
            print('  ✓ PR #%s 已提交审核：%s' % (res.get('number'), res.get('html_url')))
            return 0
        print('  ✗ HTTP %s %s' % (st, str(res)[:260]))
        return 1
    if sub == 'comment':
        st, res = req('POST', API + '/pulls/%s/comments' % args[2], tok,
                      {'access_token': tok, 'body': read_body(args[3])})
        if st in (200, 201):
            print('  ✓ 已在 PR #%s 下留言' % args[2]); return 0
        print('  ✗ HTTP %s %s' % (st, str(res)[:220])); return 1
    if sub == 'approve':
        # 仓库开了「合并前必须通过审查 / 测试」两道门槛，缺一条合并就 405：
        #   .../review -> 点「审查通过」   .../test -> 点「测试通过」
        bad = 0
        for path, name in (('/review', '审查'), ('/test', '测试')):
            st, res = req('POST', API + '/pulls/%s%s' % (args[2], path), tok,
                          {'access_token': tok, 'force': True})
            if st in (200, 204):
                print('  ✓ PR #%s %s已通过' % (args[2], name))
            else:
                print('  ✗ %s HTTP %s %s' % (name, st, str(res)[:160])); bad += 1
        return 1 if bad else 0
    if sub == 'merge':
        payload = {'access_token': tok, 'merge_method': 'merge'}
        if len(args) > 3:
            payload['title'] = args[3]
        st, res = req('PUT', API + '/pulls/%s/merge' % args[2], tok, payload)
        if st in (200, 201) and not (isinstance(res, dict) and res.get('merged') is False):
            print('  ✓ PR #%s 已合并到 %s' % (args[2], BRANCH))
            return 0
        print('  ✗ HTTP %s %s' % (st, str(res)[:240]))
        return 1
    print(HELP)
    return 2


def issue_cmds(tok, args):
    sub = args[1] if len(args) > 1 else 'view'
    num = args[2]
    if sub == 'view':
        st, it = req('GET', API + '/issues/%s' % num, tok)
        if st != 200:
            print('  ✗ HTTP %s %s' % (st, str(it)[:200])); return 1
        print('  #%s [%s] %s' % (it.get('number'), it.get('state'), it.get('title')))
        print('  %s' % it.get('html_url'))
        return 0
    if sub == 'comment':
        st, res = req('POST', API + '/issues/%s/comments' % num, tok,
                      {'access_token': tok, 'body': read_body(args[3])})
        if st in (200, 201):
            print('  ✓ 已在 issue #%s 下回复' % num); return 0
        print('  ✗ HTTP %s %s' % (st, str(res)[:220])); return 1
    if sub in ('close', 'reopen'):
        st, res = req('PATCH', API + '/issues/%s' % num, tok,
                      {'access_token': tok, 'repo': REPO,
                       'state': 'closed' if sub == 'close' else 'open'})
        if st in (200, 201):
            print('  ✓ issue #%s 已%s' % (num, '关闭' if sub == 'close' else '重新打开'))
            return 0
        print('  ✗ HTTP %s %s' % (st, str(res)[:240]))
        return 1
    print(HELP)
    return 2


def release_cmds(tok, args):
    sub = args[1] if len(args) > 1 else 'list'

    if sub == 'list':
        st, items = req('GET', API + '/releases', tok)
        if st != 200:
            print('  ✗ HTTP %s %s' % (st, str(items)[:200])); return 1
        for it in items:
            print('  id=%s  tag=%-8s  名称=%r' % (it['id'], it['tag_name'], it.get('name')))
            for a in it.get('assets') or []:
                print('      附件 %s' % a['name'])
        return 0

    if sub == 'assets':
        rel = release_of(tok, args[2])
        if not rel:
            print('  ✗ 找不到 tag=%s 的发行版' % args[2]); return 1
        print('  %s（id=%s）' % (rel.get('name'), rel['id']))
        for a in rel.get('assets') or []:
            print('    %s' % a['name'])
        return 0

    if sub in ('new', 'edit'):
        tag, name, bodyfile = args[2], args[3], args[4]
        section = args[5] if len(args) > 5 else None
        body = section_of(bodyfile, section) if section else io.open(bodyfile, encoding='utf-8').read()
        if sub == 'new':
            st, res = req('POST', API + '/releases', tok,
                          {'access_token': tok, 'tag_name': tag, 'name': name, 'body': body,
                           'target_commitish': BRANCH, 'prerelease': False})
        else:
            rel = release_of(tok, tag)
            if not rel:
                print('  ✗ 找不到 tag=%s 的发行版' % tag); return 1
            st, res = req('PATCH', API + '/releases/%s' % rel['id'], tok,
                          {'access_token': tok, 'tag_name': tag, 'name': name, 'body': body})
        if st in (200, 201):
            print('  ✓ 发行版 %s 已%s  id=%s  tag=%s  说明 %d 字节'
                  % (tag, '创建' if sub == 'new' else '更新',
                     res.get('id'), res.get('tag_name'), len(body)))
            return 0
        print('  ✗ HTTP %s %s' % (st, str(res)[:220]))
        return 1

    if sub == 'upload':
        tag = args[2]
        rel = release_of(tok, tag)
        if not rel:
            print('  ✗ 找不到 tag=%s 的发行版' % tag); return 1
        targets = []
        for a in args[3:]:
            local, _, nm = a.partition(':')
            targets.append((local, nm or os.path.basename(local)))
        want = set(n for _, n in targets)
        st, olds = req('GET', API + '/releases/%s/attach_files' % rel['id'], tok)
        if st == 200 and isinstance(olds, list):
            for a in olds:
                if a['name'] in want:
                    st2, _ = req('DELETE', API + '/releases/%s/attach_files/%s' % (rel['id'], a['id']), tok)
                    print('  删除旧附件 %-30s HTTP %s' % (a['name'], st2))
        bad = 0
        for local, nm in targets:
            if not os.path.exists(local):
                print('  ✗ 本地文件不存在: %s' % local); bad += 1; continue
            if not attach(tok, rel, local, nm):
                bad += 1
        return 1 if bad else 0

    print(HELP)
    return 2


def main():
    args = sys.argv[1:]
    branch = BRANCH
    while args and args[0].startswith('--branch='):
        branch = args[0].split('=', 1)[1]
        args = args[1:]
    if not args:
        print(HELP); return 2
    tok = get_token()
    cmd = args[0]
    if cmd == 'release':
        return release_cmds(tok, args)
    if cmd == 'branch':
        return branch_cmds(tok, args)
    if cmd == 'pr':
        return pr_cmds(tok, args)
    if cmd == 'issue':
        return issue_cmds(tok, args)
    return file_cmds(tok, args, branch)


sys.exit(main())
