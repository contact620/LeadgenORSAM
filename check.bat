@echo off
chcp 65001 >nul 2>&1
setlocal enabledelayedexpansion

echo ============================================================
echo   ORSAM - Verification de la configuration
echo ============================================================
echo.

set ERRORS=0

REM ── Python ─────────────────────────────────────────────────
where python >nul 2>&1
if %errorlevel%==0 (
    for /f "tokens=*" %%v in ('python --version 2^>^&1') do echo [OK] %%v
) else (
    echo [X]  Python non trouve
    set /a ERRORS+=1
)

REM ── Node.js ────────────────────────────────────────────────
where node >nul 2>&1
if %errorlevel%==0 (
    for /f "tokens=*" %%v in ('node --version 2^>^&1') do echo [OK] Node.js %%v
) else (
    echo [X]  Node.js non trouve
    set /a ERRORS+=1
)

REM ── venv ───────────────────────────────────────────────────
if exist "venv\Scripts\activate.bat" (
    echo [OK] Environnement virtuel Python (venv)
) else (
    echo [X]  venv absent - lancez setup.bat
    set /a ERRORS+=1
)

REM ── pip dependencies ───────────────────────────────────────
if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat >nul 2>&1
    python -c "import playwright, pandas, fastapi, anthropic" >nul 2>&1
    if !errorlevel!==0 (
        echo [OK] Dependances Python installees
    ) else (
        echo [X]  Dependances Python manquantes - lancez setup.bat
        set /a ERRORS+=1
    )
)

REM ── node_modules ───────────────────────────────────────────
if exist "frontend\node_modules" (
    echo [OK] Dependances frontend (node_modules)
) else (
    echo [X]  node_modules absent - lancez setup.bat
    set /a ERRORS+=1
)

REM ── .env ───────────────────────────────────────────────────
if exist ".env" (
    echo [OK] Fichier .env present
) else (
    echo [X]  Fichier .env absent - copiez .env.example vers .env
    set /a ERRORS+=1
)

REM ── Check API keys in .env ─────────────────────────────────
if exist ".env" (
    findstr /c:"ANTHROPIC_API_KEY=your_" .env >nul 2>&1
    if !errorlevel!==0 (
        echo [!]  ANTHROPIC_API_KEY non configuree dans .env
        set /a ERRORS+=1
    ) else (
        echo [OK] ANTHROPIC_API_KEY configuree
    )
)

REM ── Cookie files ───────────────────────────────────────────
if exist "apollo_cookies.json" (
    echo [OK] apollo_cookies.json present
) else (
    echo [!]  apollo_cookies.json absent (requis pour le scraping Apollo)
    set /a ERRORS+=1
)

REM ── output dir ─────────────────────────────────────────────
if exist "output" (
    echo [OK] Dossier output/
) else (
    echo [!]  Dossier output/ absent (sera cree automatiquement)
)

echo.
echo ============================================================
if %ERRORS%==0 (
    echo   Tout est OK ! Lancez start.bat pour demarrer.
) else (
    echo   %ERRORS% probleme(s) detecte(s). Corrigez-les avant de lancer.
)
echo ============================================================
pause
