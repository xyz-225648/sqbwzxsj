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

rm -rf "$OUT"
mkdir -p "$OUT"
cp "$HTML" "$OUT/index.html"

HASH=$(python -c "import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest()[:16])" "$OUT/index.html")
STAMP=$(date '+%Y-%m-%d %H:%M')
printf '%s  %s\n' "$HASH" "$STAMP" > "$OUT/version.txt"

echo "================================================"
echo " 发布包已生成： $OUT/"
echo "   index.html   $(du -k "$OUT/index.html" | cut -f1) KB"
echo "   version.txt  $(cat "$OUT/version.txt")"
echo "================================================"
echo
echo "下一步：把 release/ 里的两个文件上传到你的码云仓库（覆盖同名文件）"
echo "  码云仓库页 -> 「上传文件」-> 拖入 index.html 和 version.txt -> 提交"
echo
echo "提交完成后，所有人下次打开 exe / apk 就会自动换成最新课表（无需重装）。"
