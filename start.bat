@echo off
setlocal enabledelayedexpansion
title doubao-2api 启动器

echo ==========================================
echo       doubao-2api 一键启动脚本
echo ==========================================
echo.

:: 1. 检查 Python
echo [1/5] 正在检查 Python 环境...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未找到 Python。请确保已安装 Python 3.10+ 并将其添加到系统 PATH。
    pause
    exit /b 1
)

:: 2. 创建虚拟环境
if not exist .venv (
    echo [2/5] 正在创建虚拟环境 (.venv)...
    python -m venv .venv
    if !errorlevel! neq 0 (
        echo [错误] 虚拟环境创建失败。
        pause
        exit /b 1
    )
) else (
    echo [2/5] 虚拟环境已存在，跳过创建。
)

:: 3. 激活虚拟环境并安装依赖
echo [3/5] 正在安装/更新项目依赖...
call .venv\Scripts\activate

:: 使用清华源加速安装
python -m pip install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

:: 4. Playwright 浏览器 (仅用于 cookie-fetch 等辅助脚本)
echo [4/5] 正在检查 Playwright 浏览器组件 (用于辅助脚本)...
playwright install chromium

:: 4.5 检查本机 Chrome
echo [4.5] 主服务将通过 CDP 连接本机 Chrome 浏览器 (首次使用自动启动)
echo       浏览器数据持久化在 chrome_data 目录，无需每次重新登录。
where chrome >nul 2>&1
if %errorlevel% neq 0 (
    if exist "%ProgramFiles%\Google\Chrome\Application\chrome.exe" (
        echo       [OK] 已找到 Chrome: %ProgramFiles%\Google\Chrome\Application\chrome.exe
    ) else (
        echo       [提示] 未在默认路径找到 Chrome，请确保已安装 Chrome 或在 .env 中设置 CHROME_PATH。
    )
) else (
    echo       [OK] Chrome 已在 PATH 中。
)

:: 5. 配置文件检查
if not exist .env (
    if exist .env.example (
        echo [提示] 未发现 .env 文件，已自动从 .env.example 复制。请记得编辑此文件填入 Cookie。
        copy .env.example .env
    )
)

echo.
echo ==========================================
echo       所有配置已完成，正在启动程序...
echo ==========================================
echo.

python main.py

if %errorlevel% neq 0 (
    echo.
    echo [错误] 程序异常退出。请检查上方日志输出。
    pause
)

pause
