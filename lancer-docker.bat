@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === ORSAM (Docker) ===
echo.

docker info >nul 2>&1
if errorlevel 1 (
    echo [ERREUR] Docker Desktop n'est pas lance.
    echo Demarrez Docker Desktop, attendez qu'il indique "running", puis relancez ce script.
    pause
    exit /b 1
)

echo Construction et demarrage (le premier lancement prend ~5 minutes)...
docker compose up -d --build
if errorlevel 1 (
    echo [ERREUR] Le demarrage a echoue. Envoyez le contenu de cette fenetre au support.
    pause
    exit /b 1
)

echo Attente du serveur...
set /a n=0
:wait
curl -sf http://localhost:8000/api/health >nul 2>&1 && goto ready
set /a n+=1
if %n% geq 60 (
    echo [ERREUR] Le serveur ne repond pas. Logs :
    docker compose logs --tail 50
    pause
    exit /b 1
)
timeout /t 2 /nobreak >nul
goto wait

:ready
echo.
echo Application        : http://localhost:8000
echo Navigateur Apollo  : http://localhost:6080/vnc.html  (bouton Connect)
echo Donnees            : dossier data\
echo.
echo Pour arreter : double-cliquez sur arreter-docker.bat
start "" http://localhost:8000
pause
