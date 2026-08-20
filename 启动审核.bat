@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0pipeline"

rem ===== load optional .env.local (DEEPSEEK_API_KEY / PUBLIC_API_BASE) =====
if exist "%~dp0.env.local" (
  for /f "usebackq eol=# tokens=1,* delims==" %%a in ("%~dp0.env.local") do (
    set "%%a=%%b"
  )
)

if not defined DEEPSEEK_API_KEY (
  echo [WARN] DEEPSEEK_API_KEY not set: AI summary/annotations/practice will fail.
  echo        Create %~dp0.env.local with DEEPSEEK_API_KEY=sk-... then restart.
  echo.
)
if not defined PUBLIC_API_BASE (
  echo [INFO] PUBLIC_API_BASE not set, defaulting to https://api.meirishizheng.cn (鏀?.env.local)
  set "PUBLIC_API_BASE=https://api.meirishizheng.cn"
)

if not exist ".venv\Scripts\python.exe" (
  echo First run: creating venv and installing dependencies...
  python -m venv .venv
  .venv\Scripts\python.exe -m pip install -e ".[review]"
)
echo Starting local review service (browser will open automatically)...
.venv\Scripts\python.exe -m kaogong.review
endlocal
pause