@echo off
echo ========================================
echo   RAYYON RESTORAN - Ishga tushirilmoqda
echo ========================================
echo.

echo [1/2] Backend ishga tushirilmoqda...
start "Rayyon Backend" python "%~dp0backend\app.py"
timeout /t 3 /nobreak >nul

echo [2/2] Telegram bot ishga tushirilmoqda...
start "Rayyon Bot" python "%~dp0bot\bot.py"
timeout /t 2 /nobreak >nul

echo.
echo ========================================
echo  TAYYOR! Quyidagi manzillarni oching:
echo.
echo  Sayt:        http://localhost:5000
echo  Admin panel: http://localhost:5000/admin/login.html
echo  Admin parol: rayyon2024
echo ========================================
echo.
pause
