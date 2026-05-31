@echo off
chcp 65001 > nul
title ⚡ TESLA GO V9 — LMDB17

:: Se placer dans le dossier du script (fonctionne peu importe d'où on le lance)
cd /d "%~dp0"

echo.
echo ╔══════════════════════════════════════════════╗
echo ║   ⚡ TESLA GO V9 — Console de Production     ║
echo ║   Port 8369  •  LMDB17 / etheravolt.fr      ║
echo ║   Tik Tik Tik — Le UN ⚡                    ║
echo ╚══════════════════════════════════════════════╝
echo.

:: Charger .env si présent
if exist .env (
    echo Chargement de .env...
    for /f "usebackq tokens=1,* delims==" %%a in (".env") do (
        if not "%%a"=="" if not "%%a:~0,1%"=="#" set "%%a=%%b"
    )
) else (
    echo ATTENTION : fichier .env absent.
    echo Copie .env.example en .env et renseigne ton HF_TOKEN.
    echo.
)

:: Afficher le token chargé (masqué)
if defined HF_TOKEN (
    echo HF_TOKEN detecte : OK
) else (
    echo HF_TOKEN absent — LTX et Wan2.2 desactives.
)
echo.

:: Vérifier Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ERREUR : Python non trouve. Installe Python 3.10+ depuis python.org
    pause & exit /b 1
)

:: Installer les dépendances manquantes
echo Verification des dependances...
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
echo Dependances OK.
echo.

:: Vérifier que proxy.py est présent
if not exist proxy.py (
    echo ERREUR : proxy.py introuvable dans %~dp0
    echo Lance start.bat depuis le dossier tesla-go.
    pause & exit /b 1
)

:: Vérifier que le HTML est présent
if not exist tesla-go-v8.html (
    echo ERREUR : tesla-go-v8.html introuvable dans %~dp0
    echo Fais un git pull pour recuperer tous les fichiers.
    pause & exit /b 1
)

echo Demarrage sur http://127.0.0.1:8369
echo.

:: Ouvrir le navigateur après 3 secondes
start "" cmd /c "timeout /t 3 >nul && start http://127.0.0.1:8369"

:: Lancer le proxy
python proxy.py

pause
