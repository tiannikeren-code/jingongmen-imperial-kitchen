@echo off
rem 金拱门御膳房 —— 一键推送到 GitHub（令牌只进本进程环境变量，不落盘、不进仓库）
rem 用法：双击本文件，按提示粘贴令牌，回车。全程约 10 秒。
rem 令牌获取：https://github.com/settings/personal-access-tokens/new
rem   Expiration: 7 days / Repository access: Only select repositories
rem   -> jingongmen-imperial-kitchen / Permissions: Contents = Read and write

cd /d "C:\Users\tn\WorkBuddy\2026-10-21-18-40-31"

set /p PAT=Paste your GitHub fine-grained token, then press Enter:
set "GITHUB_PAT=%PAT%"

"C:\Users\tn\.workbuddy\binaries\python\versions\3.13.12\python.exe" tools\github_push.py

echo.
echo ============================================
echo 推完了。回对话里告诉我一声，我来核验。
echo ============================================
pause
