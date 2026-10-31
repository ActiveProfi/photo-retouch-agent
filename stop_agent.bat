@echo off
chcp 65001 >nul
echo Останавливаю ФотоРетушь Агент на порту 8501...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8501" ^| findstr "LISTENING"') do (
    taskkill /PID %%a /F >nul 2>&1
)
echo Готово. Окно можно закрыть.
