#!/bin/bash
cd "$(dirname "$0")" || exit 1
docker compose down
echo "ORSAM est arrete. Les donnees restent dans le dossier data/"
read -r -p "Appuyez sur Entree pour fermer..." _
