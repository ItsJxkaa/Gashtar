@echo off
chcp 65001 >nul
echo ===================================================
echo   GASH.Контроль - Запуск публичного туннеля
echo   Проброс порта http://localhost:8000 в Интернет
echo ===================================================
cd /d "%~dp0"
if not exist "cloudflared.exe" (
    echo [!] Скачиваем cloudflared.exe...
    curl.exe -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe -o cloudflared.exe
)
echo Запуск Cloudflare Tunnel...
echo После подключения найдите строку вида: https://xxxx.trycloudflare.com
echo ===================================================
.\cloudflared.exe tunnel --url http://127.0.0.1:8000
pause
