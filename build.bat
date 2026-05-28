@echo off
chcp 65001 >nul
echo ============================================
echo  BOSS直聘自动投递 - 打包工具
echo ============================================
echo.

REM 安装依赖
echo [1/3] 安装依赖...
pip install -r requirements.txt -q
if %errorlevel% neq 0 (
    echo 依赖安装失败
    pause
    exit /b 1
)

REM 清理旧构建
echo [2/3] 清理旧构建...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

REM 打包
echo [3/3] 打包中...
pyinstaller --noconfirm --onefile --windowed ^
    --name "BOSS自动投递" ^
    --add-data "config.yaml;." ^
    --hidden-import=DrissionPage ^
    --hidden-import=DrissionPage._pages.chromium_tab ^
    --hidden-import=yaml ^
    --hidden-import=docx ^
    --hidden-import=fitz ^
    --hidden-import=pdfplumber ^
    --hidden-import=requests ^
    --hidden-import=jieba ^
    --hidden-import=urllib.parse ^
    --collect-all DrissionPage ^
    gui.py

if %errorlevel% equ 0 (
    echo.
    echo ============================================
    echo  打包成功! 输出: dist\BOSS自动投递.exe
    echo ============================================
) else (
    echo 打包失败
)

pause
