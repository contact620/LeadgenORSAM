# ORSAM Lead Generation Pipeline

Outil de generation de leads B2B. Scrape des prospects depuis Apollo.io, les enrichit via Google Search, Dropcontact et IA (Claude), puis exporte en CSV.

**Deux interfaces disponibles :**
- **Interface web** (recommandee) : formulaire simple avec barre de progression en temps reel
- **Ligne de commande (CLI)** : pour les utilisateurs avances

---

## Prerequis

Avant de commencer, installez ces deux logiciels :

| Logiciel | Version minimum | Lien de telechargement |
|----------|----------------|----------------------|
| **Python** | 3.10+ | [python.org/downloads](https://www.python.org/downloads/) |
| **Node.js** | 18+ | [nodejs.org](https://nodejs.org/) |

> **Important pour Python :** Lors de l'installation, cochez la case **"Add Python to PATH"**.

---

## Installation rapide

1. **Extraire le zip** dans un dossier de votre choix
2. **Double-cliquer sur `setup.bat`** — le script installe tout automatiquement
3. **Configurer les cles API** dans le fichier `.env` (voir section ci-dessous) ou directement depuis l'interface web (page Parametres)
4. **Ajouter les fichiers cookies** via le fichier `apollo_cookies.json` ou directement depuis l'interface web (page Parametres)
5. **Verifier** en lancant `check.bat`
6. **Demarrer** en lancant `start.bat`

L'interface web s'ouvre sur : **http://localhost:5173**

---

## Configuration du fichier `.env`

Le fichier `.env` est cree automatiquement par `setup.bat`. Vous pouvez le remplir manuellement avec un editeur de texte, ou **configurer vos cles directement depuis l'interface web** (page Parametres) sans toucher au fichier :

```env
# Serper.dev API (recherche LinkedIn via Google)
SERPER_API_KEY=votre_cle_serper_ici

# Dropcontact API (optionnel - enrichissement email/telephone)
DROPCONTACT_API_KEY=votre_cle_dropcontact_ici

# Anthropic API (enrichissement IA)
ANTHROPIC_API_KEY=sk-ant-votre_cle_ici
```

### Comment obtenir les cles API

| Service | Utilite | Lien |
|---------|---------|------|
| **Serper.dev** | Trouver les profils LinkedIn (2500 requetes/mois gratuites) | [serper.dev](https://serper.dev) |
| **Dropcontact** | Trouver emails et telephones | [dropcontact.com](https://www.dropcontact.com/) |
| **Anthropic** | Enrichissement IA des leads | [console.anthropic.com](https://console.anthropic.com/settings/keys) |

---

## Ajouter les fichiers cookies

Les cookies permettent au scraper de se connecter a Apollo.io avec votre session.

### Etape par etape

1. Installez l'extension **Cookie Editor** sur votre navigateur :
   - [Chrome](https://chromewebstore.google.com/detail/cookie-editor/hlkenndednhfkekhgcdicdfddnkalmdm)
   - [Firefox](https://addons.mozilla.org/fr/firefox/addon/cookie-editor/)

2. **Pour Apollo :**
   - Connectez-vous a [app.apollo.io](https://app.apollo.io)
   - Cliquez sur l'icone Cookie Editor dans la barre d'extensions
   - Cliquez sur **"Export"** (format JSON)
   - Sauvegardez le contenu dans un fichier nomme **`apollo_cookies.json`** a la racine du projet

> **Note :** Les cookies expirent periodiquement (quelques semaines). Si le scraping echoue, re-exportez vos cookies.

---

## Utilisation

### Interface web (recommandee)

1. Lancez `start.bat` (double-clic)
2. Ouvrez **http://localhost:5173** dans votre navigateur

L'interface web offre une experience complete en 4 sections :

#### Lancer un pipeline

- **Coller une URL Apollo.io** dans le champ principal
- **Parametres avances** (section depliable) :
  - Nombre max de leads a scraper (1 a 5000, defaut 200)
  - Option pour desactiver l'enrichissement IA (pipeline plus rapide)
- **Indicateur de statut** : bandeau vert "Systeme operationnel" si tout est configure, ou bandeau jaune listant les elements manquants (cles API, cookies) avec lien direct vers les Parametres
- **Grille des 5 etapes** du pipeline affichee sous le formulaire : Scraping Apollo, LinkedIn URL, Email+Tel, Score & Filtre, Enrichissement IA

#### Suivi en temps reel

Une fois le pipeline lance :

- **Barre de progression globale** avec pourcentage mis a jour en continu (via SSE)
- **Checklist 5 etapes** avec statut en direct : en attente (cercle gris), en cours (spinner bleu + message live), termine (check vert)
- **Journal de logs** : les 20 derniers messages du pipeline affiches en temps reel dans une zone defilante

#### Resultats et export

A la fin du pipeline :

- **Dashboard de stats** — 6 cartes resumant le run :

| Carte | Contenu |
|-------|---------|
| Leads totaux | Nombre total de leads scrapes |
| Leads hit | Nombre + pourcentage du total |
| No-hit | Nombre + pourcentage |
| Emails trouves | Pourcentage + compte absolu |
| LinkedIn | Pourcentage + compte absolu |
| Telephones | Pourcentage + compte absolu (+ sites web) |

- **Barre de score moyen** avec legende du scoring : email +40, linkedin +30, phone +20, web +10, seuil hit : 50
- **Tableau de leads** complet :
  - Filtres par onglets : Tous / Hits / No-hit
  - Recherche textuelle (nom, entreprise, poste, email)
  - Colonnes : Nom, Poste, Entreprise (lien vers site web), Email (lien mailto), LinkedIn (lien externe), Score (barre visuelle), Hit (badge colore), Angle IA
  - Clic sur une ligne pour deplier le detail IA : resume d'activite + angle de conversion generes par Claude
  - Pagination (10 leads par page)
- **Telechargement CSV** en un clic

#### Historique des pipelines

Accessible via le bouton **Historique** dans la barre de navigation :

- **Liste de tous les runs passes** avec : date, duree, URL Apollo, nombre de leads (effectif / max), nombre de hits + pourcentage, score moyen, statut (Termine / Erreur)
- **Consulter un run passe** : cliquer sur l'icone oeil pour retrouver le dashboard de stats complet + le tableau de leads (memes fonctionnalites que les resultats en direct)
- **Telecharger le CSV** d'un ancien run directement depuis la liste
- **Supprimer une entree** avec confirmation

#### Parametres (page dediee)

Accessible via le bouton **Parametres** dans la barre de navigation. Permet de tout configurer sans editer de fichier :

**Cles API** — saisir ou modifier les cles directement depuis l'interface :
- `SERPER_API_KEY` (obligatoire) — recherche LinkedIn via Google
- `DROPCONTACT_API_KEY` (optionnel) — enrichissement email/telephone ignore si absent
- `ANTHROPIC_API_KEY` (obligatoire) — enrichissement IA
- Chaque cle affiche un badge de statut (vert "Configure" / rouge "Manquant")
- Bouton oeil pour afficher/masquer la valeur
- Bouton "Sauvegarder les cles" pour enregistrer

**Cookies de session Apollo** — deux methodes disponibles :
- **Upload fichier** : glisser-deposer ou parcourir un fichier `.json`
- **Coller le JSON** : copier-coller le contenu directement dans un champ texte
- Badge de statut indiquant si les cookies sont presents ou absents

**Parametres du pipeline** :
- Seuil de hit score (0-100, defaut 50) — score minimum pour qu'un lead soit considere comme "hit"

### Ligne de commande (CLI)

```bash
# Activer l'environnement virtuel
venv\Scripts\activate

# Lancer le pipeline
python main.py --url "https://app.apollo.io/#/people?..." --max-leads 100

# Options disponibles
python main.py --url "URL" --max-leads 100 --skip-gpt --log-level DEBUG
```

| Option | Description | Defaut |
|--------|-------------|--------|
| `--url` | URL de recherche Apollo (obligatoire) | - |
| `--max-leads` | Nombre max de leads a scraper | 500 |
| `--skip-gpt` | Desactiver l'enrichissement IA | Non |
| `--log-level` | Niveau de log : DEBUG, INFO, WARNING | INFO |

---

## Fichiers de sortie

Les resultats sont sauvegardes dans le dossier **`output/`** au format CSV.

### Colonnes du CSV

| Colonne | Description |
|---------|-------------|
| `first_name`, `last_name` | Prenom et nom |
| `company` | Entreprise |
| `job_title` | Poste |
| `location` | Localisation |
| `email` | Email (via Dropcontact) |
| `phone` | Telephone (via Dropcontact) |
| `linkedin_url` | URL du profil LinkedIn |
| `website` | Site web de l'entreprise |
| `hit_score` | Score de qualite 0-100 |
| `is_hit` | `True` si score >= 50 |
| `activity_summary` | Resume d'activite genere par IA |
| `conversion_angle` | Angle d'approche suggere par IA |

---

## Depannage

### "Python n'est pas reconnu"
Reinstallez Python en cochant **"Add Python to PATH"**, puis fermez et rouvrez votre terminal.

### "Node.js n'est pas reconnu"
Reinstallez Node.js depuis [nodejs.org](https://nodejs.org/), puis fermez et rouvrez votre terminal.

### Le scraping Apollo ne fonctionne pas
- Verifiez que `apollo_cookies.json` est present a la racine
- Re-exportez vos cookies Apollo (ils expirent)

### Erreur "ANTHROPIC_API_KEY manquante"
- Ouvrez `.env` et verifiez que la cle commence par `sk-ant-`
- Verifiez votre solde sur [console.anthropic.com](https://console.anthropic.com/)

### Le frontend ne se charge pas
- Verifiez que le backend tourne (fenetre "ORSAM API")
- L'API doit repondre sur http://localhost:8000/api/health

### Reinstallation complete
Supprimez les dossiers `venv` et `frontend\node_modules`, puis relancez `setup.bat`.

---

## Structure des fichiers

```
LeadgenORSAM/
├── setup.bat              <- Installation automatique
├── start.bat              <- Lancer l'application
├── check.bat              <- Verifier la configuration
├── .env                   <- Vos cles API (a configurer)
├── .env.example           <- Modele du fichier .env
├── apollo_cookies.json    <- Cookies Apollo (a ajouter)
├── requirements.txt       <- Dependances Python
├── main.py                <- Point d'entree CLI
├── config.py              <- Configuration
├── api/                   <- Serveur FastAPI
├── scrapers/              <- Scraping Apollo + websites
├── enrichers/             <- Google, Dropcontact, IA
├── processors/            <- Calcul hit score
├── frontend/              <- Interface web React
└── output/                <- Fichiers CSV generes
```
