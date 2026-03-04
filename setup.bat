@echo off
chcp 65001 >nul 2>&1
setlocal enabledelayedexpansion

echo ============================================================
echo   ORSAM Lead Generation - Installation
echo ============================================================
echo.

REM ── Check Python ───────────────────────────────────────────
set PYTHON_CMD=
where python >nul 2>&1
if %errorlevel%==0 (
    set PYTHON_CMD=python
) else (
    where py >nul 2>&1
    if %errorlevel%==0 (
        set PYTHON_CMD=py
    )
)

if "%PYTHON_CMD%"=="" (
    echo [ERREUR] Python n'est pas installe.
    echo.
    echo Telechargez Python 3.10+ depuis :
    echo   https://www.python.org/downloads/
    echo.
    echo IMPORTANT : Cochez "Add Python to PATH" pendant l'installation.
    echo Puis relancez setup.bat.
    echo.
    start https://www.python.org/downloads/
    pause
    exit /b 1
)

echo [OK] Python trouve : %PYTHON_CMD%
%PYTHON_CMD% --version

REM ── Check Python version >= 3.10 ──────────────────────────
for /f "tokens=2 delims= " %%v in ('%PYTHON_CMD% --version 2^>^&1') do set PYVER=%%v
for /f "tokens=1,2 delims=." %%a in ("%PYVER%") do (
    if %%a LSS 3 (
        echo [ERREUR] Python 3.10+ requis, version actuelle : %PYVER%
        pause
        exit /b 1
    )
    if %%a==3 if %%b LSS 10 (
        echo [ERREUR] Python 3.10+ requis, version actuelle : %PYVER%
        pause
        exit /b 1
    )
)
echo [OK] Version Python compatible : %PYVER%
echo.

REM ── Check Node.js ──────────────────────────────────────────
where node >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERREUR] Node.js n'est pas installe.
    echo.
    echo Telechargez Node.js 18+ depuis :
    echo   https://nodejs.org/
    echo.
    echo Puis relancez setup.bat.
    echo.
    start https://nodejs.org/
    pause
    exit /b 1
)

echo [OK] Node.js trouve :
node --version
echo.

REM ── Create Python venv ─────────────────────────────────────
if not exist "venv" (
    echo [1/5] Creation de l'environnement virtuel Python...
    %PYTHON_CMD% -m venv venv
    if %errorlevel% neq 0 (
        echo [ERREUR] Impossible de creer le venv.
        pause
        exit /b 1
    )
    echo [OK] venv cree.
) else (
    echo [1/5] venv existe deja, skip.
)
echo.

REM ── Activate venv and install pip dependencies ─────────────
echo [2/5] Installation des dependances Python...
call venv\Scripts\activate.bat
pip install --upgrade pip >nul 2>&1
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo [ERREUR] Echec de pip install. Verifiez requirements.txt.
    pause
    exit /b 1
)
echo [OK] Dependances Python installees.
echo.

REM ── Install Playwright Chromium ────────────────────────────
echo [3/5] Installation du navigateur Playwright (Chromium)...
playwright install chromium
if %errorlevel% neq 0 (
    echo [ERREUR] Echec de l'installation Playwright.
    pause
    exit /b 1
)
echo [OK] Playwright Chromium installe.
echo.

REM ── Install frontend dependencies ──────────────────────────
echo [4/5] Installation des dependances frontend (npm)...
cd frontend
call npm install
if %errorlevel% neq 0 (
    echo [ERREUR] Echec de npm install.
    cd ..
    pause
    exit /b 1
)
cd ..
echo [OK] Dependances frontend installees.
echo.

REM ── Setup .env and output dir ──────────────────────────────
echo [5/5] Configuration...
if not exist ".env" (
    copy .env.example .env >nul
    echo [OK] Fichier .env cree depuis .env.example
) else (
    echo [OK] Fichier .env existe deja.
)

if not exist "output" mkdir output
echo [OK] Dossier output/ pret.
echo.

echo ============================================================
echo   Installation terminee !
echo ============================================================
echo.
echo Prochaines etapes :
echo   1. Editez le fichier .env avec vos cles API
echo   2. Ajoutez votre fichier cookies :
echo      - apollo_cookies.json
echo   3. Lancez l'application avec : start.bat
echo.
echo Consultez le README.md pour plus de details.
echo ============================================================
pause
