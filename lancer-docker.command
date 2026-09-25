#!/bin/bash
# Lancement d'ORSAM sous macOS / Linux (double-clic sur macOS)
cd "$(dirname "$0")" || exit 1
echo "=== ORSAM (Docker) ==="
echo

fin() { echo; read -r -p "Appuyez sur Entree pour fermer..." _; exit "$1"; }

if ! docker info >/dev/null 2>&1; then
    echo "[ERREUR] Docker Desktop n'est pas lance."
    echo "Demarrez Docker Desktop, attendez qu'il indique \"running\", puis relancez ce script."
    fin 1
fi

# -- Migration unique depuis une installation sans Docker --
# Docker lit tout dans data/ ; on y COPIE les donnees existantes a la
# racine (cles, cookies, historique, CSV) sans toucher aux originaux.
if [ ! -d data ] && { [ -f .env ] || [ -f apollo_cookies.json ] || [ -d output ]; }; then
    echo "Reprise des donnees de l'installation existante vers data/ ..."
    mkdir data
    [ -f .env ] && cp .env data/.env
    [ -f apollo_cookies.json ] && cp apollo_cookies.json data/apollo_cookies.json
    if [ -d output ] && ! cp -R output data/output; then
        echo "[ERREUR] Copie de output/ impossible. Fermez l'ancienne version de l'appli puis relancez."
        rm -rf data
        fin 1
    fi
    echo "      - cles, cookies et historique repris (originaux conserves)"
    echo
fi

echo "Construction et demarrage (le premier lancement prend ~5 minutes)..."
if ! docker compose up -d --build; then
    echo "[ERREUR] Le demarrage a echoue. Envoyez le contenu de cette fenetre au support."
    fin 1
fi

echo "Attente du serveur..."
n=0
until curl -sf http://localhost:8000/api/health >/dev/null 2>&1; do
    n=$((n + 1))
    if [ "$n" -ge 60 ]; then
        echo "[ERREUR] Le serveur ne repond pas. Logs :"
        docker compose logs --tail 50
        fin 1
    fi
    sleep 2
done

echo
echo "Application        : http://localhost:8000"
echo "Navigateur Apollo  : http://localhost:6080/vnc.html  (bouton Connect)"
echo "Donnees            : dossier data/"
echo
echo "Pour arreter : double-cliquez sur arreter-docker.command"
open http://localhost:8000 2>/dev/null || xdg-open http://localhost:8000 >/dev/null 2>&1
fin 0
