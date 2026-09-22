# -*- coding: utf-8 -*-
"""Gitee ⇄ GitHub 双向同步（在 GitHub Actions 里跑）。

规则（单向优先，绝不硬覆盖）：
  两边相同            → 什么都不做
  GitHub 领先         → 推给 Gitee（典型场景：GitHub 上合并了 PR）
  Gitee  领先         → 推给 GitHub（典型场景：Gitee 上合并了 PR / 直接提交）
  两边各有新提交      → 先自动合并；合不干净就退出码 2 报错，谁都不动

只由 GitHub 侧发起（Gitee 那边不需要任何配置）；往 Gitee 推需要 Actions secret
GITEE_TOKEN（Gitee 私人令牌）。没有配这个 secret 时，Gitee → GitHub 单向仍然可用。

首次导入 / 救援：把 FORCE_FROM_GITEE 设成 1（工作流手动触发时有这个选项），
就把 GitHub 的 master 直接覆盖成 Gitee 的 master。

用法：
  python mirror_sync.py            真正的同步（Actions 里调用的就是它）
  python mirror_sync.py --selftest 只测「该往哪边推」的判定逻辑，不碰网络
"""
import os, subprocess, sys

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

GITEE_URL = os.environ.get('GITEE_URL', 'https://gitee.com/xyz-225648/sqbwzxsj.git')
GITEE_TOKEN = (os.environ.get('GITEE_TOKEN') or '').strip()
GITEE_USER = os.environ.get('GITEE_USER', 'xyz-225648')
BRANCH = os.environ.get('SYNC_BRANCH', 'master')
FORCE = (os.environ.get('FORCE_FROM_GITEE') or '').strip().lower() in ('1', 'true', 'yes')


def decide(g, h, is_ancestor):
    """纯判定：返回 same / git_wins / gitee_wins / merge / empty

    g = Gitee master 的 sha，h = GitHub master 的 sha（None 表示那一侧还没有）
    is_ancestor(a, b) 表示 a 是 b 的祖先（a 已经被 b 包含）
    """
    if not g and not h:
        return 'empty'
    if g == h:
        return 'same'
    if g and h:
        if is_ancestor(g, h):
            return 'git_wins'          # GitHub 含 Gitee 全部提交 → 推给 Gitee
        if is_ancestor(h, g):
            return 'gitee_wins'        # Gitee 含 GitHub 全部提交 → 推给 GitHub
        return 'merge'                 # 分叉了
    return 'gitee_wins' if g else 'git_wins'


def run(cmd, **kw):
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       env=dict(os.environ, GIT_TERMINAL_PROMPT='0'), **kw)
    return p.returncode, p.stdout.decode('utf-8', 'replace')


def git(*args, **kw):
    return run(['git'] + list(args), **kw)


def sha_of(ref):
    rc, out = git('rev-parse', ref)
    return out.strip() if rc == 0 else None


def is_ancestor(a, b):
    return git('merge-base', '--is-ancestor', a, b)[0] == 0


def gitee_push_url():
    if GITEE_TOKEN:
        return 'https://oauth2:%s@gitee.com/xyz-225648/sqbwzxsj.git' % GITEE_TOKEN
    return None


def say(msg):
    print(msg, flush=True)


def main():
    if '--selftest' in sys.argv:
        return selftest()

    # 只关心 master 这一条线的同步（其它分支/tag 用 --mirror 一次带过去）
    git('remote', 'add', 'gitee', GITEE_URL)
    rc, out = git('fetch', '--prune', 'gitee',
                  '+refs/heads/*:refs/remotes/gitee/*', '+refs/tags/*:refs/tags/*')
    if rc != 0:
        say('拉取 Gitee 失败：' + out.strip()[-400:])
        return 1
    rc, out = git('fetch', '--prune', 'origin')
    if rc != 0:
        say('拉取 GitHub 失败：' + out.strip()[-400:])
        return 1

    g, h = sha_of('refs/remotes/gitee/' + BRANCH), sha_of('refs/remotes/origin/' + BRANCH)
    say('Gitee  %s = %s' % (BRANCH, (g or '无')[:10]))
    say('GitHub %s = %s' % (BRANCH, (h or '无')[:10]))

    if FORCE:
        # 首次导入或救援：两边历史毫无关系（或 GitHub 那边是坏的）时，
        # 直接把 GitHub 的 master 覆盖成 Gitee 的 master。只在本工作流里手动触发时用。
        say('强制模式：把 GitHub 的 %s 覆盖成 Gitee 的 %s' % (BRANCH, BRANCH))
        rc, out = git('push', 'origin', '--force',
                      'refs/remotes/gitee/%s:refs/heads/%s' % (BRANCH, BRANCH))
        say('覆盖结果：%s' % ('成功' if rc == 0 else '失败 ' + out.strip()[-300:]))
        git('push', 'origin', '--tags')
        return 0 if rc == 0 else 1

    action = decide(g, h, is_ancestor)
    say('判定：%s' % action)

    if action in ('same', 'empty'):
        git('push', 'origin', '--tags')
        say('两边一致，只对齐了 tag')
        return 0

    if action == 'merge':
        git('config', 'user.name', 'mirror-bot')
        git('config', 'user.email', 'mirror-bot@users.noreply.github.com')
        git('checkout', '-B', 'mirror-merge', 'refs/remotes/origin/' + BRANCH)
        rc, out = git('merge', '--no-edit', 'refs/remotes/gitee/' + BRANCH)
        if rc != 0:
            say('✗ 两边分叉且合并有冲突，已停下（谁都没动）：')
            for line in out.splitlines():
                if 'CONFLICT' in line or 'Auto-merging' in line:
                    say('   ' + line.strip())
            say('→ 请手动合并后推任意一边，再重跑本工作流')
            return 2
        say('合并干净：%s' % (sha_of('HEAD') or '')[:10])
        ok = True
        gp = gitee_push_url()
        if gp:
            rc, out = git('push', gp, 'refs/heads/mirror-merge:refs/heads/' + BRANCH)
            say('推回 Gitee：%s' % ('成功' if rc == 0 else '失败 ' + out.strip()[-200:]))
            ok = ok and rc == 0
        else:
            say('· 没有 GITEE_TOKEN，跳过推回 Gitee（这次只合并到 GitHub）')
        rc, out = git('push', 'origin', 'refs/heads/mirror-merge:refs/heads/' + BRANCH)
        say('推回 GitHub：%s' % ('成功' if rc == 0 else '失败 ' + out.strip()[-200:]))
        git('push', gp or 'origin', '--tags')
        return 0 if (ok and rc == 0) else 1

    if action == 'git_wins':
        gp = gitee_push_url()
        if not gp:
            say('· GitHub 领先，但没有 GITEE_TOKEN，推不过去（请在仓库 Settings → Secrets 里配好）')
            return 1
        rc, out = git('push', gp, 'refs/remotes/origin/%s:refs/heads/%s' % (BRANCH, BRANCH))
        say('GitHub → Gitee：%s' % ('成功' if rc == 0 else '失败 ' + out.strip()[-300:]))
        git('push', gp, '--tags')
        return 0 if rc == 0 else 1

    rc, out = git('push', 'origin', 'refs/remotes/gitee/%s:refs/heads/%s' % (BRANCH, BRANCH))
    say('Gitee → GitHub：%s' % ('成功' if rc == 0 else '失败 ' + out.strip()[-300:]))
    git('push', 'origin', '--tags')
    return 0 if rc == 0 else 1


def selftest():
    fail = []

    def check(label, got, want):
        ok = got == want
        print('  %s %-46s %s' % ('✓' if ok else '✗', label, got))
        if not ok:
            fail.append(label)

    # 造一个假的祖先关系：A 是 B 的祖先（B 里含 A），D 是 C 的祖先（C 里含 D）
    pairs = {('A', 'B'), ('D', 'C')}

    def anc(a, b):
        return (a, b) in pairs or a == b

    check('两边同一个提交', decide('X', 'X', anc), 'same')
    check('两边都还没有', decide(None, None, anc), 'empty')
    check('GitHub 领先（含 Gitee 全部提交）→ 推给 Gitee', decide('A', 'B', anc), 'git_wins')
    check('Gitee 领先（含 GitHub 全部提交）→ 推给 GitHub', decide('C', 'D', anc), 'gitee_wins')
    check('分叉（各有新提交）→ 合并', decide('A', 'D', anc), 'merge')
    check('只有 Gitee 有 master → 推给 GitHub', decide('A', None, anc), 'gitee_wins')
    check('只有 GitHub 有 master → 推给 Gitee', decide(None, 'B', anc), 'git_wins')
    print('  selftest: %s' % ('PASS' if not fail else 'FAIL'))
    for f in fail:
        print('    ✗ ' + f)
    return 0 if not fail else 1


if __name__ == '__main__':
    sys.exit(main())
