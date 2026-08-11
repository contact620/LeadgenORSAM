# Boxcom Lead Generation Pipeline

Outil de generation de leads B2B. Scrape des prospects depuis Apollo.io, les enrichit via Google Search, Dropcontact, IA (Claude), scoring ICP et intelligence business (Perplexity Sonar), puis exporte en CSV. Pipeline en 2 phases : scraping rapide dans des pools, puis enrichissement par batch.

**Deux interfaces disponibles :**
- **Interface web** (recommandee) : formulaire avec barre de progression en temps reel, pools de leads, templates de recherche et theme clair/sombre
- **Ligne de commande (CLI)** : pour les utilisateurs avances

> **Compatibilite :** L'installation automatique (`setup.bat`, `start.bat`, `check.bat`) fonctionne **uniquement sous Windows** pour le moment. Une adaptation Linux/macOS est prevue ulterieurement.

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

# Anthropic API (enrichissement IA + scoring ICP)
ANTHROPIC_API_KEY=sk-ant-votre_cle_ici

# Perplexity API (optionnel - enrichissement maturite digitale, budget, signaux business)
PERPLEXITY_API_KEY=votre_cle_perplexity_ici

# Hunter.io (optionnel - verification des emails retournes par Dropcontact)
HUNTER_API_KEY=votre_cle_hunter_ici

# Modele LLM utilise pour l'enrichissement IA (defaut: claude-sonnet-4-6)
# Autres choix : claude-haiku-4-5-20251001 (moins cher), claude-opus-4-7 (qualite max)
LLM_MODEL=claude-sonnet-4-6
```

### Comment obtenir les cles API

| Service | Utilite | Lien |
|---------|---------|------|
| **Serper.dev** | Trouver les profils LinkedIn (2500 requetes/mois gratuites) | [serper.dev](https://serper.dev) |
| **Dropcontact** | Trouver emails et telephones | [dropcontact.com](https://www.dropcontact.com/) |
| **Hunter.io** | Verification des emails retournes par Dropcontact (~$0.01 / verif) | [hunter.io/api-keys](https://hunter.io/api-keys) |
| **Anthropic** | Enrichissement IA + scoring ICP des leads | [console.anthropic.com](https://console.anthropic.com/settings/keys) |
| **Perplexity** | Maturite digitale, budget estime, signaux business | [perplexity.ai](https://www.perplexity.ai/settings/api) |

> **Cout Hunter.io :** environ **$0.01 par email verifie**. Pour un run de 500 leads avec ~250 emails Dropcontact, compter ~**$2.50** de verification.

> **Modele LLM :** L'enrichissement IA utilise **Claude Sonnet 4.6** par defaut (meilleur raisonnement que Haiku pour l'analyse B2B). Vous pouvez basculer sur Haiku (moins cher) ou Opus (qualite max) en changeant la variable `LLM_MODEL` dans `.env`.

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

## Mise a jour du projet

Lorsque vous recevez une nouvelle version du projet, **vos donnees locales doivent etre preservees**. Elles vivent toutes dans 3 endroits :

| Fichier / dossier | Contenu |
|-------------------|---------|
| `output/history.db` | Base SQLite : historique des runs, pools de leads, templates de recherche |
| `output/*.csv` | Vos exports CSV passes |
| `.env` | Vos cles API |
| `apollo_cookies.json` | Vos cookies de session Apollo |

### Methode A — Via Git (recommandee)

Si vous avez clone le projet avec Git, la mise a jour est instantanee :

1. Ouvrez un terminal a la racine du projet
2. Lancez :
   ```bash
   git pull
   ```
3. Si l'application tourne, rechargez la page dans le navigateur (`F5`). Sinon, relancez `start.bat`

Git ne touche jamais aux fichiers ignores (`output/`, `.env`, `apollo_cookies.json`, `venv/`, `node_modules/`) — vos donnees et votre configuration sont automatiquement preservees.

> Si une nouvelle dependance Python ou Node a ete ajoutee, relancez `setup.bat` apres le `git pull`.

### Methode B — Nouvelle version complete (zip)

Si on vous envoie un nouveau zip :

1. Extrayez-le **dans le dossier du projet**, en ecrasant les fichiers existants
2. Double-cliquez sur `update.bat`
3. Lancez `start.bat`

`update.bat` sauvegarde votre base sous `output\history.db.avant-maj-<date>`, supprime les
restes de l'ancienne version, puis appelle `setup.bat` pour les dependances. Rien d'autre
n'est a faire.

> **Vos donnees ne peuvent pas etre ecrasees.** Le zip est genere avec `git archive` : il ne
> contient que les fichiers versionnes. `output/`, `.env` et `apollo_cookies.json` etant
> ignores par git, ils en sont structurellement absents. Il n'y a donc rien a deplacer avant
> d'extraire.

**Pourquoi `update.bat` est necessaire.** Extraire un zip ajoute et remplace des fichiers,
mais ne supprime jamais ceux qui ont disparu de la nouvelle version. Le cas critique est
`frontend/dist` : ce dossier est ignore par git, donc absent du zip, donc jamais mis a jour —
et le serveur le sert tel quel sur le port 8000. Sans nettoyage, vous verriez l'ancienne
interface par-dessus le nouveau moteur.

**Pour generer le zip** (cote prestataire, depuis un tag) :

```bash
git archive --format=zip -o leadgen-<date>.zip <tag>
```

---

## Utilisation

### Interface web (recommandee)

1. Lancez `start.bat` (double-clic)
2. Ouvrez **http://localhost:5173** dans votre navigateur

L'interface web offre une experience complete en 6 sections :

#### Lancer un pipeline

- **Coller une URL Apollo.io** dans le champ principal
- **Parametres avances** (section depliable) :
  - Nombre max de leads a scraper (1 a 5000, defaut 200)
  - Option pour desactiver l'enrichissement IA (pipeline plus rapide)
  - **Services cibles** : checkboxes pour selectionner les services pertinents a la campagne (oriente l'enrichissement IA)
  - **Signaux personnalises** : champ texte libre pour preciser les declencheurs a rechercher
- **Scrape-only (pool)** : possibilite de ne scraper que les leads sans enrichissement, pour les stocker dans un pool et les enrichir plus tard par batch
- **Indicateur de statut** : bandeau vert "Systeme operationnel" si tout est configure, ou bandeau jaune listant les elements manquants (cles API, cookies) avec lien direct vers les Parametres
- **Grille des etapes** du pipeline affichee sous le formulaire : Scraping Apollo, LinkedIn URL, Email+Tel, Score & Filtre, Scoring ICP, Enrichissement IA+Perplexity

#### Suivi en temps reel

Une fois le pipeline lance :

- **Barre de progression globale** avec pourcentage mis a jour en continu (via SSE)
- **Checklist des etapes** avec statut en direct : en attente (cercle gris), en cours (spinner bleu + message live), termine (check vert)
- **Journal de logs** : les 20 derniers messages du pipeline affiches en temps reel dans une zone defilante
- **Resume executif** genere automatiquement a la fin du pipeline

#### Resultats et export

A la fin du pipeline :

- **Dashboard de stats** — cartes resumant le run :

| Carte | Contenu |
|-------|---------|
| Leads totaux | Nombre total de leads scrapes |
| Leads hit | Nombre + pourcentage du total |
| No-hit | Nombre + pourcentage |
| Emails trouves | Pourcentage + compte absolu |
| LinkedIn | Pourcentage + compte absolu |
| Telephones | Pourcentage + compte absolu (+ sites web) |

- **Barre de score moyen** avec legende du scoring : email +40, linkedin +30, phone +20, web +10, seuil hit : 50
- **Distribution ICP** : repartition des leads par tier — Hot, Warm, Cold avec barre visuelle
- **Tableau de leads** complet :
  - Filtres par onglets : Tous / Hits / No-hit
  - **Filtre ICP** par tier (Hot, Warm, Cold)
  - **Tri** par score, nom, entreprise
  - Recherche textuelle (nom, entreprise, poste, email)
  - Colonnes : Nom, Poste, Entreprise (lien vers site web), Email (lien mailto), LinkedIn (lien externe), Score (barre visuelle), Hit (badge colore), ICP (score + badge tier), Angle IA
  - **Clic sur un lead** pour ouvrir une modale de detail :
    - **Scoring ICP** : tier, score, justification + detail par axe (Secteur, Taille, Localisation, Signaux)
    - **Resume d'activite** + **Angle de conversion** generes par Claude
    - **Maturite digitale** : score /10 + justification (Perplexity)
    - **Budget estime** : taille entreprise, CA, financements (Perplexity)
    - **Signaux business** : activites recentes de l'entreprise (Perplexity)
    - Informations de contact (email, telephone, LinkedIn)
  - Pagination (10 leads par page)
- **Telechargement CSV** en un clic

#### Pools de leads

Accessible via le bouton **Pools** dans la barre de navigation. Pipeline en 2 phases :

- **Phase 1 — Scrape-only** : scraper des leads Apollo sans enrichissement et les stocker dans un pool
- **Phase 2 — Enrichissement par batch** : selectionner un pool et lancer l'enrichissement sur un lot de 10, 25, 50 ou 100 leads
- **Liste des pools** avec nombre de leads, date de creation
- **Detail d'un pool** : voir les leads stockes, cliquer sur un lead pour afficher la modale de detail
- **Suppression** d'un pool avec confirmation

#### Templates de recherche

Accessible via le bouton **Templates** dans la barre de navigation :

- **Sauvegarder une recherche Apollo** (nom, URL, max leads, option skip IA) comme template reutilisable
- **Relancer un template** en un clic — lance directement le pipeline avec les parametres sauvegardes
- **CRUD complet** : creer, lister, supprimer des templates

#### Historique des pipelines

Accessible via le bouton **Historique** dans la barre de navigation :

- **Liste de tous les runs passes** avec : date, duree, URL Apollo, nombre de leads (effectif / max), nombre de hits + pourcentage, score moyen, statut (Termine / Erreur)
- **Dashboard de stats** avec cartes KPI directement dans la liste
- **Consulter un run passe** : cliquer sur l'icone oeil pour retrouver le dashboard de stats complet + le tableau de leads (memes fonctionnalites que les resultats en direct)
- **Telecharger le CSV** d'un ancien run directement depuis la liste
- **Supprimer une entree** avec confirmation

#### Parametres (page dediee)

Accessible via le bouton **Parametres** dans la barre de navigation. Permet de tout configurer sans editer de fichier :

**Cles API** — saisir ou modifier les cles directement depuis l'interface :
- `SERPER_API_KEY` (obligatoire) — recherche LinkedIn via Google
- `DROPCONTACT_API_KEY` (optionnel) — enrichissement email/telephone ignore si absent
- `ANTHROPIC_API_KEY` (obligatoire) — enrichissement IA + scoring ICP
- `PERPLEXITY_API_KEY` (optionnel) — enrichissement Perplexity Sonar ignore si absent
- Chaque cle affiche un badge de statut (vert "Configure" / rouge "Manquant")
- Bouton oeil pour afficher/masquer la valeur
- Bouton "Sauvegarder les cles" pour enregistrer

**Cookies de session Apollo** — deux methodes disponibles :
- **Upload fichier** : glisser-deposer ou parcourir un fichier `.json`
- **Coller le JSON** : copier-coller le contenu directement dans un champ texte
- Badge de statut indiquant si les cookies sont presents ou absents

**Services de l'agence** :
- Liste de services configurables (persistee dans le `.env`)
- Ces services apparaissent comme checkboxes dans le formulaire de lancement pour orienter l'enrichissement IA

**Parametres du pipeline** :
- Seuil de hit score (0-100, defaut 50) — score minimum pour qu'un lead soit considere comme "hit"

#### Theme clair / sombre

Bouton de bascule dans la barre de navigation pour alterner entre le theme clair et le theme sombre. Le choix est persiste dans le navigateur.

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
| `email_status` | Statut de verification Hunter.io : `valid`, `invalid`, `accept_all`, `webmail`, `disposable`, `unknown` |
| `email_confidence` | Score de confiance Hunter.io (0-100) |
| `phone` | Telephone (via Dropcontact) |
| `linkedin_url` | URL du profil LinkedIn |
| `website` | Site web de l'entreprise |
| `hit_score` | Score de qualite 0-100 (email valide = +40, autres statuts = +20 ou 0) |
| `is_hit` | `True` si score >= 50 |
| `icp_score` | Score ICP 0-100 (adequation profil client ideal) |
| `icp_tier` | Classification : `hot` (>70), `warm` (40-70), `cold` (<40) |
| `icp_rationale` | Justification du score ICP par l'IA |
| `icp_scores_detail` | Detail des scores par axe (JSON) |
| `activity_summary` | Resume d'activite genere par IA |
| `conversion_angle` | Angle d'approche suggere par IA |
| `inconsistency_detected` | `True` si l'IA detecte une incoherence Apollo <-> source scrapee (cas d'homonymie d'entreprise) |
| `inconsistency_reason` | Explication courte de l'incoherence detectee |
| `llm_confidence` | Confiance du modele IA : `high`, `medium`, `low` |
| `digital_maturity` | Maturite digitale : score /10 + justification (Perplexity) |
| `estimated_budget` | Budget estime : taille, CA, financements (Perplexity) |
| `business_signals` | Signaux business recents de l'entreprise (Perplexity) |

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
- Verifiez que le backend tourne (fenetre "Boxcom API")
- L'API doit repondre sur http://localhost:8000/api/health

### Reinstallation complete
Supprimez les dossiers `venv` et `frontend\node_modules`, puis relancez `setup.bat`.

---

## Pipeline en 2 phases

### Phase 1 — Scrape-only (optionnel)

Scrape les leads Apollo sans enrichissement et les stocke dans un **pool**. Permet d'accumuler des leads et de les enrichir plus tard par batch (10, 25, 50 ou 100 leads a la fois).

### Phase 2 — Pipeline complet (7 etapes)

Le pipeline execute les etapes suivantes de maniere sequentielle :

| Etape | Nom | Description |
|-------|-----|-------------|
| 1 | **Scraping Apollo** | Extraction des leads depuis une recherche Apollo.io (Playwright + cookies) |
| 2 | **Recherche LinkedIn** | Recherche des profils LinkedIn via Serper.dev + site web via DuckDuckGo |
| 3a | **Email + Telephone** | Enrichissement via Dropcontact (batches de 50, polling asynchrone) |
| 3b | **Verification email** | Verification Hunter.io de chaque email Dropcontact : statut + score de confiance. Pondere le hit score selon validite |
| 4 | **Score & Filtre** | Calcul du hit score (email valide +40, statut incertain +20, invalide 0 ; linkedin +30, phone +20, web +10). Leads >= seuil = "hit" |
| 5 | **Scoring ICP** | Evaluation par IA (Claude) de l'adequation au profil client ideal sur 4 axes : secteur (20%), taille (20%), localisation (20%), signaux business (40%). Classification en tiers : hot (>70), warm (40-70), cold (<40) |
| 6 | **Enrichissement IA** | Scraping du site web puis appel **Claude Sonnet 4.6** (modele configurable) : resume d'activite, angle de conversion, et **detection d'incoherence** entre Apollo et la source scrapee (cas d'homonymie d'entreprise) |
| 7 | **Enrichissement Perplexity** | Recherche Perplexity Sonar sur les leads hit : maturite digitale (score /10), budget estime, signaux business recents |

Les etapes 5 a 7 ne s'executent que sur les leads "hit" pour optimiser les couts API. Si une cle API est absente, l'etape correspondante est ignoree.

L'enrichissement IA (etapes 5-7) prend en compte les **enrich_instructions** : services cibles et signaux personnalises configures au lancement pour orienter les analyses.

Un **resume executif** est genere automatiquement a la fin du pipeline.

---

## Structure des fichiers

```
LeadgenORSAM/
├── setup.bat              <- Installation automatique (Windows uniquement)
├── start.bat              <- Lancer l'application (Windows uniquement)
├── check.bat              <- Verifier la configuration (Windows uniquement)
├── .env                   <- Vos cles API (a configurer)
├── .env.example           <- Modele du fichier .env
├── apollo_cookies.json    <- Cookies Apollo (a ajouter)
├── requirements.txt       <- Dependances Python
├── main.py                <- Point d'entree CLI
├── config.py              <- Configuration
├── api/
│   ├── server.py          <- Serveur FastAPI
│   ├── pipeline_runner.py <- Orchestrateur pipeline (2 phases)
│   ├── leads_db.py        <- Gestion pools de leads (SQLite)
│   ├── templates.py       <- Gestion templates de recherche
│   └── routes/            <- Endpoints API (pipeline, templates, config, health)
├── scrapers/              <- Scraping Apollo + websites
├── enrichers/             <- Google, Dropcontact, IA, Perplexity Sonar
├── processors/            <- Calcul hit score + scoring ICP
├── prompts/               <- Prompts personnalisables (scoring ICP)
├── frontend/
│   └── src/
│       ├── App.tsx            <- Navigation principale (5 pages)
│       ├── contexts/          <- ThemeContext (clair/sombre)
│       ├── hooks/             <- usePipeline (SSE, state machine)
│       ├── lib/               <- api.ts (fetch wrappers)
│       └── components/
│           ├── ApolloForm.tsx       <- Formulaire + services + scrape-only
│           ├── ResultsTable.tsx     <- Tableau leads + filtres ICP + tri
│           ├── LeadDetailModal.tsx  <- Modale detail lead (ICP, IA, Perplexity)
│           ├── LeadPools.tsx        <- Gestion pools + enrichissement batch
│           ├── Templates.tsx        <- Templates de recherche CRUD
│           ├── History.tsx          <- Historique + stats cards
│           ├── Settings.tsx         <- Configuration (cles, cookies, services)
│           └── ThemeToggle.tsx      <- Bascule theme clair/sombre
└── output/                <- Fichiers CSV generes
```
