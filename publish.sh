#!/usr/bin/env bash
# 一键发布：闸门 + 生成 release/ 里的三个文件。
# 实现在 publish.py —— 发布机不一定有 bash（Windows 上 Git Bash 常常没装），
# 这里只做转发，保证老的 `bash publish.sh` 用法照旧。
set -e
cd "$(dirname "$0")"
if command -v python3 >/dev/null 2>&1; then
  exec python3 publish.py "$@"
fi
exec python publish.py "$@"
