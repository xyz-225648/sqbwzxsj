#!/usr/bin/env bash
# ============================================================
#  一键发布：把最新网页打包成「可直接上传到码云」的 release/ 目录
#  用法：  bash publish.sh
# ============================================================
set -e
cd "$(dirname "$0")"

HTML="宿迁职业技术学院作息时间表.html"
OUT="release"

if [ ! -f "$HTML" ]; then
  echo "找不到 $HTML"
  exit 1
fi

# ---- 发布前强制自检：页面脚本有语法错误就直接拒绝发布 ----
echo "检查页面语法 ..."
if ! python check_page.py "$HTML"; then
  echo
  echo "自检未通过，已中止发布（线上内容不受影响）。"
  exit 1
fi
echo

# ---- 渲染冒烟测试：无头浏览器真跑一遍，抓未捕获异常 + 功能真的渲染出来了没有 ----
echo "渲染冒烟测试（无头浏览器，约 5-10 秒）..."
if ! python smoke_page.py "$HTML"; then
  echo
  echo "冒烟测试未通过，已中止发布（线上内容不受影响）。"
  exit 1
fi
echo

# ---- 交互遍历：真点真滚一遍（悬停/钉住、设置、通知判定、缩放、防调试…） ----
echo "交互遍历测试（无头浏览器 + CDP，约 1 分钟）..."
if ! python functest_page.py "$HTML"; then
  echo
  echo "交互遍历未通过，已中止发布（线上内容不受影响）。"
  exit 1
fi
echo

# ---- 本地接口自检：exe 侧的信箱 / 通知 / 版本接口 ----
echo "本地接口自检（源码模式，几秒）..."
if ! python selftest_api.py app.py 19199; then
  echo
  echo "接口自检未通过，已中止发布（线上内容不受影响）。"
  exit 1
fi
echo

rm -rf "$OUT"
mkdir -p "$OUT"
cp "$HTML" "$OUT/index.html"

HASH=$(python -c "import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest()[:16])" "$OUT/index.html")
STAMP=$(date '+%Y-%m-%d %H:%M')
# 版本号直接取自页面里的 APP_VERSION，绝不会两边对不上
VER=$(python - "$HTML" <<'PYEOF'
import io, re, sys
s = io.open(sys.argv[1], encoding='utf-8').read()
m = re.search(r"var APP_VERSION = '([^']+)'", s)
print(m.group(1) if m else 'v0')
PYEOF
)
# 写成可被 <script> 加载的 JS：网页侧没有跨域限制，手机版也能检测更新
python -c "import io,json,sys; io.open('$OUT/version.txt','w',encoding='utf-8',newline=chr(10)).write('window.SQZY_LATEST='+json.dumps({'v':sys.argv[1],'h':sys.argv[2],'t':sys.argv[3]},ensure_ascii=False)+';'+chr(10))" "$VER" "$HASH" "$STAMP"

# program.txt：程序本体（exe/apk）当前发布的版本。网页能热更新、程序本体不能，
# 页面靠这个文件发现「网页已经是最新，但装着的 exe/apk 老了」并提醒去下载。
TAG=$(python - "$HTML" <<'PYEOF'
import io, re, sys
s = io.open(sys.argv[1], encoding='utf-8').read()
m = re.search(r"var RELEASE_TAG = '([^']+)'", s)
print(m.group(1) if m else 'v0')
PYEOF
)
# 直链和 sha256 由 make_program_txt.py 从本地发行包算出来（exe 版一键更新要用，
# 校验不过就拒绝替换）。发行包还没重新打包时会提示退回手动下载。
python make_program_txt.py "$HTML" "$OUT" "$VER" "$STAMP"
echo "   program.txt  $(cat "$OUT/program.txt")"

echo "================================================"
echo " 发布包已生成： $OUT/"
echo "   index.html   $(du -k "$OUT/index.html" | cut -f1) KB"
echo "   版本:$VER"
echo "   version.txt  $(cat "$OUT/version.txt")"
echo "================================================"
echo
echo "下一步：把 release/ 里的两个文件上传到你的码云仓库（覆盖同名文件）"
echo "  码云仓库页 -> 「上传文件」-> 拖入 index.html 和 version.txt -> 提交"
echo
echo "提交完成后，所有人下次打开 exe / apk 就会自动换成最新课表（无需重装）。"
