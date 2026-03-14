@echo off
chcp 65001 >nul
setlocal

:: 检查虚拟环境是否存在
if not exist "venv\Scripts\activate.bat" (
    echo [错误] 找不到虚拟环境 venv，请先创建它！
    pause
    exit /b 1
)

echo [信息] 正在激活虚拟环境并启动服务...
call venv\Scripts\activate.bat

:: 启动程序
python main.py

pause
