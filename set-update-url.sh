#!/usr/bin/env bash
# ============================================================
#  设置自动更新地址（码云 raw 地址），并重新打包 exe + apk
#  用法：  bash set-update-url.sh https://gitee.com/用户名/仓库名/raw/master/
#  想关闭自动更新： bash set-update-url.sh ""
# ============================================================
set -e
cd "$(dirname "$0")"

URL="$1"
if [ $# -eq 0 ]; then
  echo "用法: bash set-update-url.sh https://gitee.com/用户名/仓库名/raw/master/"
  echo "      bash set-update-url.sh \"\"        # 关闭自动更新"
  exit 1
fi
if [ -n "$URL" ]; then
  case "$URL" in
    */) ;;
    *) URL="$URL/" ;;
  esac
fi

python - "$URL" <<'PYEOF'
import io, re, sys
url = sys.argv[1]

targets = [
    ('app.py',
     r"^UPDATE_BASE = '.*?'",
     "UPDATE_BASE = '%s'" % url),
    ('.apkbuild/app/java/com/sqzytc/timetable/MainActivity.java',
     r'^\s*private static final String UPDATE_BASE = ".*?"',
     'private static final String UPDATE_BASE = "%s"' % url),
]

for path, pat, new in targets:
    s = io.open(path, encoding='utf-8').read()
    s2, n = re.subn(pat, new, s, count=1, flags=re.M)
    assert n == 1, '没找到目标行: ' + path
    io.open(path, 'w', encoding='utf-8', newline='\n').write(s2)
    print('  已更新', path)

print('  更新地址 =', url if url else '(已关闭自动更新)')
PYEOF

echo
echo "重新打包 exe ..."
rm -rf build dist
python -m PyInstaller --noconfirm --clean --onefile --windowed \
  --name sqzy_schedule --icon app.ico \
  --add-data "宿迁职业技术学院作息时间表.html;." \
  --hidden-import webview.platforms.edgechromium \
  app.py > /dev/null 2>&1
mv -f dist/sqzy_schedule.exe "宿迁职业技术学院作息时间表.exe"
rm -rf dist build __pycache__

echo "重新打包 apk ..."
bash .apkbuild/build_apk.sh > /dev/null 2>&1
rm -f "宿迁职业技术学院作息时间表.apk.idsig"

echo
echo "完成。"
