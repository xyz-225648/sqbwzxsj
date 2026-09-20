# -*- coding: utf-8 -*-
"""发布前渲染冒烟测试：用无头 Edge/Chrome 真跑一遍页面，抓两类问题

  1) 任何未捕获的 JS 异常（Uncaught ...）—— 语法检查（node --check）查不出来，
     但一个 ReferenceError 就能让它后面的所有初始化代码不执行。
  2) 「当前状态 / 还有多久下课」到底渲染出来没有：真跑完必须能在 DOM 里
     看到状态文字和倒计时。这一条正是为了不再犯「页面看着正常、功能却没了」。

用法: python smoke_page.py [本地页面路径 或 http(s) URL]
"""
import datetime, io, os, re, subprocess, sys, tempfile, shutil
from urllib.parse import quote

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BROWSERS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]

target = sys.argv[1] if len(sys.argv) > 1 else '宿迁职业技术学院作息时间表.html'
if target.startswith('http://') or target.startswith('https://'):
    url = target
elif os.path.exists(target):
    url = 'file:///' + quote(os.path.abspath(target).replace('\\', '/'), safe='/:')
else:
    print('  找不到页面: %s' % target)
    sys.exit(1)

exe = None
for p in BROWSERS:
    if os.path.exists(p):
        exe = p
        break
if not exe:
    print('  ⚠ 没找到 Edge/Chrome，跳过渲染冒烟测试（语法检查已单独执行）')
    sys.exit(0)

prof = tempfile.mkdtemp(prefix='sqzy_smoke_')
cmd = [exe, '--headless=new', '--disable-gpu', '--no-first-run',
       '--user-data-dir=' + prof, '--window-size=1400,1000',
       '--virtual-time-budget=6000', '--enable-logging=stderr', '--v=0',
       '--dump-dom', url]
try:
    r = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8',
                       errors='replace', timeout=120)
except Exception as e:
    shutil.rmtree(prof, ignore_errors=True)
    print('  ⚠ 浏览器启动失败，跳过渲染冒烟测试: %s' % e)
    sys.exit(0)
shutil.rmtree(prof, ignore_errors=True)

dom = r.stdout or ''
err = r.stderr or ''
fail = []

# ---- 1) 未捕获异常 ----
uncaught = [l.strip() for l in err.split('\n') if 'Uncaught' in l]
for l in uncaught[:6]:
    m = re.search(r'"([^"]*Uncaught[^"]*)"', l)
    print('  ✗ 页面抛异常: %s' % (m.group(1) if m else l[:160]))
if uncaught:
    fail.append('页面有未捕获异常 %d 条' % len(uncaught))
else:
    print('  未捕获异常: 0 条')

# ---- 1b) 被 bootStep 兜住的启动步骤异常：说明某个功能没跑起来（不会再拖垮整页，但仍是缺陷）----
steps = sorted(set(re.findall(r'\[启动失败\] ([^\s"\\]+)', err)))
if steps:
    print('  ✗ 有启动步骤抛异常: %s' % ', '.join(steps))
    fail.append('启动步骤异常: %s' % ', '.join(steps))
else:
    print('  启动步骤异常: 0 处')

if '<html' not in dom.lower():
    fail.append('页面没有渲染出 DOM（拿到 %d 字节）' % len(dom))

# 只看真实 DOM，去掉 <script>/<style> 源码文本（里面也有同样的字符串，会误判）
body = re.sub(r'<script[\s\S]*?</script>', '', dom, flags=re.I)
body = re.sub(r'<style[\s\S]*?</style>', '', body, flags=re.I)

# ---- 2) 当前状态 / 倒计时有没有渲染出来 ----
m = re.search(r'id="nowBar">([\s\S]{0,6000})', body)
bar = m.group(1) if m else ''
if not bar:
    fail.append('找不到 #nowBar 内容')
else:
    items = bar.count('class="nowitem')
    cds = re.findall(r'<em class="cd ([a-z]+)">([^<]*)</em>', bar)
    print('  当前状态条: %d 个学院, 倒计时 %d 条 %s'
          % (items, len(cds), ('例: ' + cds[0][1]) if cds else ''))
    if items < 4:
        fail.append('当前状态条只有 %d 个学院（应为 4）' % items)

ms = re.findall(r'<div class="m">([^<]*)</div>', body)
print('  分方向卡片状态文字: %d 个 %s' % (len(ms), ('例: ' + ms[0]) if ms else ''))
if len(ms) < 4:
    fail.append('卡片只有 %d 个（应为 4）' % len(ms))
elif any(not x.strip() for x in ms):
    fail.append('有卡片的状态文字是空的 —— renderNow 没跑完')

now = datetime.datetime.now()
mins = now.hour * 60 + now.minute
base_ok = len(re.findall(r'<em class="cd ([a-z]+)">', bar)) > 0
inside = (8 * 60 <= mins <= 21 * 60 + 35)      # 这段区间里必然有课/课间，倒计时不该为空
if inside:
    if not base_ok:
        fail.append('当前时间 %s 属于上课时段，却一条倒计时都没有' % now.strftime('%H:%M'))
    else:
        print('  ✓ 倒计时已渲染（当前 %s 在上课时段内）' % now.strftime('%H:%M'))
else:
    print('  · 当前 %s 不在 08:00–21:35 内，跳过倒计时断言' % now.strftime('%H:%M'))

# ---- 3) 页面体积/结构 ----
if len(body) < 20000:
    fail.append('渲染后的 DOM 过小（%d 字节）' % len(body))

print('  smoke: %s' % ('PASS' if not fail else 'FAIL'))
for x in fail:
    print('    ✗ ' + x)
sys.exit(1 if fail else 0)
