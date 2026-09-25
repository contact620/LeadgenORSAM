@echo off
cd /d "%~dp0"
docker compose down
echo ORSAM est arrete. Les donnees restent dans le dossier data\
pause
