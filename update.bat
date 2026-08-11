@echo off
REM Expansion retardee : sans elle, %TS% serait developpe a la lecture du
REM bloc parenthese, donc avant que la boucle for ne l'ait renseigne.
setlocal enabledelayedexpansion

echo ============================================================
echo   ORSAM Lead Generation - Mise a jour
echo ============================================================
echo.
echo Ce script prepare la nouvelle version. Vos donnees ne sont
echo jamais touchees : historique, pools, exports, cles API et
echo cookies restent en place.
echo.

REM -- 1. Sauvegarde de la base avant toute chose --
if exist "output\history.db" (
    for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd-HHmmss"') do set TS=%%i
    copy /y "output\history.db" "output\history.db.avant-maj-!TS!" >nul
    if errorlevel 1 (
        echo [ERREUR] Impossible de sauvegarder output\history.db.
        echo Verifiez que l'application est bien fermee, puis relancez.
        pause
        exit /b 1
    )
    echo [1/3] Sauvegarde : output\history.db.avant-maj-!TS!
) else (
    echo [1/3] Pas de base existante, rien a sauvegarder.
)
echo.

REM -- 2. Suppression des restes de l'ancienne version --
REM L'extraction du zip ne supprime pas les fichiers retires de la
REM nouvelle version. frontend\dist est le seul cas critique : le
REM serveur le sert tel quel sur le port 8000, ce qui afficherait
REM l'ancienne interface par-dessus le nouveau moteur.
echo [2/3] Nettoyage de l'ancienne version...
if exist "frontend\dist" (
    rmdir /s /q "frontend\dist"
    echo       - ancienne interface compilee supprimee
)
if exist "enrichers\gpt_enricher.py" (
    del /q "enrichers\gpt_enricher.py"
    echo       - ancien moteur d'enrichissement supprime
)
if exist "prompts" (
    rmdir /s /q "prompts"
    echo       - anciens prompts supprimes
)
for /d /r %%d in (__pycache__) do @if exist "%%d" rmdir /s /q "%%d" 2>nul
echo       - caches Python vides
echo.

REM -- 3. Dependances --
echo [3/3] Installation des dependances...
echo.
REM Chemin explicite : sur les postes ou la resolution depuis le repertoire
REM courant est desactivee, un simple "call setup.bat" echouerait.
call "%~dp0setup.bat"

echo.
echo ============================================================
echo   Mise a jour terminee
echo ============================================================
echo.
echo Prochaines etapes :
echo   1. Lancez start.bat
echo   2. Ouvrez http://localhost:5173
echo   3. Verifiez que l'Historique affiche bien vos runs passes
echo   4. Dans Parametres, reglez HIT_THRESHOLD sur 50
echo.
