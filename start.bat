@echo off
chcp 65001 > nul
title ⚡ TESLA GO V8 — LMDB17

echo.
echo ╔══════════════════════════════════════════════╗
echo ║   ⚡ TESLA GO V8 — Pipeline 100 pourcent Gratuite   ║
echo ║   Port 8369  LMDB17 / etheravolt.fr         ║
echo ║   Tik Tik Tik - Le UN                       ║
echo ╚══════════════════════════════════════════════╝
echo.

:: Charger .env si présent
if exist .env (
    echo Chargement de .env...
    for /f "tokens=1,2 delims==" %%a in (.env) do set %%a=%%b
)

:: Vérifier Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ERREUR : Python non trouvé. Installe Python 3.10+ depuis python.org
    pause & exit /b 1
)

:: Installer les dépendances si besoin
echo Vérification des dépendances...
pip show aiohttp >nul 2>&1
if %errorlevel% neq 0 (
    echo Installation : aiohttp...
    pip install aiohttp
)
pip show gradio_client >nul 2>&1
if %errorlevel% neq 0 (
    echo Installation : gradio_client...
    pip install gradio_client
)

echo.
echo Démarrage du proxy sur http://127.0.0.1:8369
echo.

:: Ouvrir le navigateur après 2 secondes
start "" cmd /c "timeout /t 2 >nul && start http://127.0.0.1:8369"

:: Lancer le proxy
python proxy.py

pause
