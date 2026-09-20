# -*- coding: utf-8 -*-
"""发布前自检：抽出页面里的内联脚本，用 node 做语法检查。
有任何语法错误就退出码非 0 —— publish.sh 会据此拒绝发布。"""
import io, os, re, subprocess, sys
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

path = sys.argv[1] if len(sys.argv) > 1 else '宿迁职业技术学院作息时间表.html'
src = io.open(path, encoding='utf-8').read()
blocks = re.findall(r'<script>(.*?)</script>', src, re.S)
print('  内联脚本块: %d 个' % len(blocks))
if not blocks or len(src) < 20000:
    print('  页面不完整（脚本为 0 或体积过小）—— 拒绝')
    sys.exit(1)

fail = 0
for i, code in enumerate(blocks):
    tmp = '_check_tmp.js'
    io.open(tmp, 'w', encoding='utf-8', newline='\n').write(code)
    r = subprocess.run(['node', '--check', tmp], capture_output=True, text=True)
    if r.returncode == 0:
        print('  第 %d 块: 语法 OK (%d 行)' % (i + 1, code.count(chr(10))))
    else:
        fail += 1
        print('  第 %d 块: 语法错误 ✗' % (i + 1))
        err = (r.stderr or '').replace(tmp, path)
        for line in err.strip().split(chr(10))[:6]:
            print('    ' + line)
        # 指出是脚本块里的第几行，方便定位
        mm = re.search(r':(\d+)', err)
        if mm:
            ln = int(mm.group(1))
            lines = code.split(chr(10))
            for k in range(max(0, ln - 3), min(len(lines), ln + 2)):
                mark = '  <<<' if k == ln - 1 else ''
                print('      %4d| %s%s' % (k + 1, lines[k][:100], mark))
    if os.path.exists(tmp):
        os.remove(tmp)

# 顺带检查几个关键元素是否还在（防止误删功能）
for key in ['initSettings', 'checkNotify', 'setTracks', 'aboutCheck', 'SQZY_LATEST']:
    if key not in src:
        print('  ⚠ 页面里找不到关键标识: %s' % key)

print('  self-check: %s' % ('PASS' if fail == 0 else 'FAIL'))
sys.exit(1 if fail else 0)
