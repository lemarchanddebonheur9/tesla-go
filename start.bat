@echo off
chcp 65001 > nul
title TESLA GO V9

cd /d "%~dp0"

echo.
echo  TESLA GO V9 — Console de Production
echo  Port 8369 - LMDB17 / etheravolt.fr
echo  Tik Tik Tik - Le UN
echo.

:: Charger .env
if exist .env (
    for /f "usebackq tokens=1,* delims==" %%a in (".env") do (
        set "%%a=%%b"
    )
    echo .env charge.
) else (
    echo ATTENTION : .env absent - HF_TOKEN non defini.
)

if defined HF_TOKEN (
    echo HF_TOKEN : OK
) else (
    echo HF_TOKEN : absent ^(LTX et Wan2.2 desactives^)
)
echo.

:: Vérifier Python
python --version
if %errorlevel% neq 0 (
    echo ERREUR : Python non trouve !
    pause
    exit /b 1
)

:: Installer deps
pip show aiohttp >nul 2>&1 || pip install aiohttp
pip show gradio_client >nul 2>&1 || pip install gradio_client

echo.
echo Ouverture du navigateur dans 3 secondes...
start "" cmd /c "timeout /t 3 >nul && start http://127.0.0.1:8369"

echo Lancement proxy.py...
echo.
python proxy.py

echo.
echo Le proxy s'est arrete.
pause
