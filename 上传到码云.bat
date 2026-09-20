@echo off
chcp 65001 >nul
title 上传到码云仓库
cd /d "%~dp0"

echo ============================================================
echo   宿迁职业技术学院作息时间表  ^-^>  上传到码云
echo   仓库: https://gitee.com/xyz-225648/sqbwzxsj
echo ============================================================
echo.
echo 需要你的「码云私人令牌」（不是登录密码）：
echo   1. 打开 https://gitee.com/profile/personal_access_tokens
echo   2. 点「生成新令牌」，勾选 projects 权限，提交
echo   3. 复制那串令牌，粘贴到下面（粘贴后屏幕不显示，这是正常的）
echo.
set /p TOKEN=请粘贴令牌后按回车:

if "%TOKEN%"=="" (
  echo 没有输入令牌，已取消。
  pause
  exit /b 1
)

where git >nul 2>nul
if errorlevel 1 (
  echo 找不到 git，请先安装 Git for Windows。
  pause
  exit /b 1
)

echo.
echo [1/5] 准备发布文件 ...
if not exist "release\index.html" (
  echo 缺少 release\index.html，请先运行 publish.sh
  pause
  exit /b 1
)

if exist "_gitee_tmp" rmdir /s /q "_gitee_tmp"

echo [2/5] 克隆仓库 ...
git clone --depth 1 "https://oauth2:%TOKEN%@gitee.com/xyz-225648/sqbwzxsj.git" _gitee_tmp
if errorlevel 1 (
  echo.
  echo 克隆失败。常见原因：令牌复制不全、令牌没勾 projects 权限、仓库地址写错。
  pause
  exit /b 1
)

echo [3/5] 复制文件 ...
copy /Y "release\index.html" "_gitee_tmp\" >nul
copy /Y "release\version.txt" "_gitee_tmp\" >nul
copy /Y *.exe "_gitee_tmp\" >nul
copy /Y *.apk "_gitee_tmp\" >nul
copy /Y *.png "_gitee_tmp\" >nul
copy /Y *.md  "_gitee_tmp\" >nul
copy /Y app.py "_gitee_tmp\" >nul
copy /Y publish.sh "_gitee_tmp\" >nul
copy /Y check_page.py "_gitee_tmp\" >nul
copy /Y smoke_page.py "_gitee_tmp\" >nul
copy /Y set-update-url.sh "_gitee_tmp\" >nul

echo [4/5] 提交 ...
cd _gitee_tmp
git config user.name "sqzy-timetable"
git config user.email "sqzy-timetable@local"
git add -A
git commit -m "上传作息时间表（网页/Windows/安卓 三端）" >nul

echo [5/5] 推送 ...
git push origin master
if errorlevel 1 (
  echo.
  echo 推送失败，试试改成 main 分支：
  git push origin HEAD:main
)
cd ..

echo.
echo ============================================================
echo   完成！打开仓库看看： https://gitee.com/xyz-225648/sqbwzxsj
echo   记得：用完可以去 https://gitee.com/profile/personal_access_tokens
echo         把这个令牌删掉（更安全）
echo ============================================================
pause
