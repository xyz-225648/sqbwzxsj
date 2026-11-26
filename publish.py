# -*- coding: utf-8 -*-
"""一键发布：先过全部自检，再把「可直接上传仓库」的发布包写进 release/。

  1) node verify_schedule.js      作息逻辑断言（周六/周日/放假/优先级）
  2) python check_page.py         页面内联脚本语法（node --check）
  3) python smoke_page.py         无头浏览器渲染冒烟（含三个定时刻断言）
  4) python functest_page.py      无头浏览器 + CDP 交互遍历
  5) python selftest_api.py       桌面版本地接口自检

五项全过才生成 release/{index.html,version.txt,program.txt}；任何一项不过立刻中止，
线上内容不受影响。

为什么有 Python 版：发布机不一定有 bash —— Windows 上 Git Bash 常常没装，
publish.sh 会在第一步就挂掉（实测）。这套闸门本身全是 python/node 脚本，
所以真正的实现放在这里，publish.sh 只做转发，`bash publish.sh` 用法照旧。

用法: python publish.py
"""
import hashlib, io, json, os, re, shutil, subprocess, sys, time

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from update_common import norm_ver

HERE = os.path.dirname(os.path.abspath(__file__))
PAGE_NAMES = ('宿迁职业技术学院作息时间表.html', 'index.html')


def page_file():
    """页面文件名：本地开发用中文名，仓库里是 index.html（两份内容必须一致）"""
    for n in PAGE_NAMES:
        if os.path.exists(os.path.join(HERE, n)):
            return n
    print('  找不到页面文件：%s（请在仓库根目录执行）' % ' 或 '.join(PAGE_NAMES))
    sys.exit(1)


def run_gate(label, cmd):
    """跑一道闸门；命令找不到或返回非 0 都算没通过（不静默放行）"""
    print('  %s ...' % label)
    try:
        p = subprocess.run(cmd, cwd=HERE)
    except FileNotFoundError:
        print(chr(10) + '  ✗ 找不到命令 %s —— 装好再来（node 要单独装，见 requirements.txt）' % cmd[0])
        sys.exit(1)
    if p.returncode != 0:
        print(chr(10) + '  ✗ %s 未通过，已中止发布（线上内容不受影响）。' % label)
        sys.exit(1)


def page_var(src, name, default=None):
    m = re.search(r"var %s = '([^']+)'" % name, src)
    return m.group(1) if m else default


def _token_present():
    for p in (os.path.join(HERE, '.gitee_token'), os.path.expanduser('~/.gitee_token')):
        if os.path.exists(p) and io.open(p, encoding='utf-8').read().strip():
            return True
    return bool(os.environ.get('GITEE_TOKEN'))


def _gitee(*args):
    r = subprocess.run([sys.executable, 'gitee_repo.py'] + list(args), cwd=HERE,
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    return r.returncode, (r.stdout or '') + (r.stderr or '')


def release_step(ver, out, html):
    """建同名发行版并把三件资产传上去。

    为什么写进发布链路：漏建发行版时「最新版」标签会停在旧版本，
    安装包也不会出现在最新页（v2.4.10~v2.4.15 就是这么漏的）。
    失败即报错退出，绝不静默跳过 —— 除非没配 token 或显式 --no-release。
    """
    if '--no-release' in sys.argv:
        print('  · 已按 --no-release 跳过发行版')
        return 0
    if not _token_present():
        print('  ! 没找到 .gitee_token / GITEE_TOKEN，跳过发行版（请手动建 %s）' % ver)
        return 0

    code, outtxt = _gitee('release', 'assets', ver)
    exists = code == 0 and ('index.html' in outtxt or '附件' in outtxt)
    if not exists:
        print('  · 发行版 %s 不存在，创建中…' % ver)
        code, outtxt = _gitee('release', 'new', ver, ver, 'CHANGELOG.md', ver)
        if code != 0:
            print(outtxt.strip()[-400:])
            print('  ✗ 发行版 %s 创建失败（发布中止，避免「最新版」标签停在旧版本）' % ver)
            return 1

    have = outtxt if exists else ''
    if not exists:
        code2, have = _gitee('release', 'assets', ver)
        if code2 != 0:
            have = ''
    # 用相对路径：gitee_repo.py 的 "本地:仓库名" 语法按 ':' 切分，绝对路径里的盘符会被当成分隔符
    assets = [('release/index.html', 'index.html')]
    for fname, label in (('宿迁职业技术学院作息时间表.exe', 'exe'), ('宿迁职业技术学院作息时间表.apk', 'apk')):
        local = os.path.join(HERE, fname)
        if not os.path.exists(local):
            print('  · 本地没有 %s，跳过该附件' % fname)
            continue
        if fname in have:
            print('  · 发行版 %s 已有 %s，跳过上传' % (ver, fname))
            continue
        assets.append((fname, fname))
    if assets:
        pairs = ['%s:%s' % (a, b) for a, b in assets]
        code, outtxt = _gitee('release', 'upload', ver, *pairs)
        print('  ' + outtxt.strip().replace(chr(10), chr(10) + '  ')[-600:])
        if code != 0:
            print('  ✗ 发行版 %s 附件上传失败' % ver)
            return 1
    print('  ✓ 发行版 %s 就绪（%s）' % (ver, 'index.html' if not assets else '已上传 %d 件' % len(assets)))
    return 0


def main():
    os.chdir(HERE)
    html = page_file()

    run_gate('逻辑断言（周六/周日/放假/优先级）', ['node', 'verify_schedule.js'])
    run_gate('特殊日表格式校验', [sys.executable, 'check_calendar.py'])
    run_gate('页面语法自检', [sys.executable, 'check_page.py', html])
    run_gate('渲染冒烟测试（无头浏览器）', [sys.executable, 'smoke_page.py', html])
    run_gate('交互遍历测试（无头浏览器 + CDP）', [sys.executable, 'functest_page.py', html])
    run_gate('本地接口自检（源码模式）', [sys.executable, 'selftest_api.py', 'app.py', '19199'])

    out = os.path.join(HERE, 'release')
    shutil.rmtree(out, ignore_errors=True)
    os.makedirs(out)
    shutil.copyfile(os.path.join(HERE, html), os.path.join(out, 'index.html'))

    digest = hashlib.sha256(io.open(os.path.join(out, 'index.html'), 'rb').read()).hexdigest()[:16]
    stamp = time.strftime('%Y-%m-%d %H:%M')
    src = io.open(os.path.join(HERE, html), encoding='utf-8').read()
    ver = page_var(src, 'APP_VERSION', 'v0')      # 版本号只从页面里取，绝不会两边对不上
    if norm_ver(ver) < 0:
        print('  ✗ 页面 APP_VERSION=%r 不是合法版本号（要 v 开头 + 三段数字，如 v2.4.7）—— 拒绝发布' % ver)
        sys.exit(1)

    # version.txt 写成可被 <script> 加载的 JS：网页侧没有跨域限制，手机版也能检测更新
    io.open(os.path.join(out, 'version.txt'), 'w', encoding='utf-8', newline=chr(10)).write(
        'window.SQZY_LATEST=' + json.dumps({'v': ver, 'h': digest, 't': stamp},
                                           ensure_ascii=False) + ';' + chr(10))

    # program.txt：exe/apk 本体的版本、直链、sha256、字节数、镜像线路（一键更新要校验 sha256）
    r = subprocess.run([sys.executable, 'make_program_txt.py', html, out, ver, stamp], cwd=HERE)
    if r.returncode != 0:
        print('  ✗ program.txt 生成失败，发布包不完整')
        sys.exit(1)

    rc = release_step(ver, out, html)
    if rc:
        return rc

    print('=' * 48)
    print(' 发布包已生成： release/')
    print('   index.html   %d KB' % (os.path.getsize(os.path.join(out, 'index.html')) // 1024))
    print('   版本：%s' % ver)
    print('   version.txt  %s' % io.open(os.path.join(out, 'version.txt'), encoding='utf-8').read().strip())
    print('   program.txt  %s' % io.open(os.path.join(out, 'program.txt'), encoding='utf-8').read().strip())
    print('=' * 48)
    print(chr(10) + '下一步：把 release/ 里的三个文件提交到仓库根目录（注意 > 后面的目标名，别漏）')
    print('  走 PR：python gitee_repo.py branch new release/%s' % ver)
    print('        python gitee_repo.py --branch=release/%s push "release/index.html>index.html" "release/version.txt>version.txt" "release/program.txt>program.txt"' % ver)
    print('  页面热更新：上方已自动建好发行版 %s 并传了附件（check_live 会机械校验）' % ver)
    print('  程序本体版本（exe/apk）没升时 program.txt 与上一个版本相同，不用换安装包；')
    print('  升了壳版本时，exe/apk 附件按 program.txt 里的 tag（= 程序本体版本）上传。')
    return 0


sys.exit(main())
