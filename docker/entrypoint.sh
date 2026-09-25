#!/bin/sh
set -e

# Dossier de données persistant (volume) : .env, cookies, CSV, history.db
mkdir -p "$OUTPUT_DIR"
[ -f "$ENV_PATH" ] || cp /app/.env.example "$ENV_PATH"

# Écran virtuel pour le Chromium "visible" d'Apollo
rm -f /tmp/.X99-lock
Xvfb :99 -screen 0 1440x900x24 -nolisten tcp &
sleep 1
fluxbox >/dev/null 2>&1 &

# Accès à cet écran depuis le navigateur de l'hôte : http://localhost:6080
x11vnc -display :99 -forever -shared -nopw -quiet -rfbport 5900 >/dev/null 2>&1 &
websockify --web /usr/share/novnc 6080 localhost:5900 >/dev/null 2>&1 &

# Commande explicite (ex. : python main.py --url ...) → on l'exécute à la place du serveur
if [ "$#" -gt 0 ]; then
    exec "$@"
fi

echo "ORSAM prêt : application http://localhost:8000 — navigateur Apollo http://localhost:6080/vnc.html"
exec python -m uvicorn api.server:app --host 0.0.0.0 --port 8000
