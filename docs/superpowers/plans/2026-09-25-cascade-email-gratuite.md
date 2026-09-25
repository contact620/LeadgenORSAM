# Cascade email gratuite et scoring en deux passes — Plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Supprimer Dropcontact et toute dépense obligatoire, remplacer l'acquisition de contacts par une cascade gratuite (site web → patterns vérifiés → trois finders freemium sous quota), et remplacer le hit score de joignabilité par un score de cohérence ICP calculé en deux passes.

**Architecture :** Le scoring et la dépense sont désormais pilotés par la pertinence, pas par la joignabilité. Une passe 1 gratuite (colonnes Apollo + page d'accueil déjà téléchargée pour le contrôle de cohérence) produit un score ICP provisoire qui sert uniquement à ordonner la file de dépense. Une passe 2 (Perplexity + Claude sur faits sourcés) écrase ce score sur les leads retenus et reste la seule valeur exportée comme verdict. La joignabilité devient un booléen : un lead a une route de contact ou n'en a pas. L'acquisition d'email suit une cascade à arrêt au premier succès — email nominatif trouvé sur le site, puis pattern généré et vérifié, puis finders payants réservés aux leads en tête de file — avec un gestionnaire de quota qui ne décrémente que sur résultat réellement facturé.

**Tech Stack :** Python 3.10+, FastAPI, Pydantic v2, pandas, requests, anthropic SDK, sqlite3, pytest. Nouvelles dépendances runtime : `phonenumbers`, `dnspython`. Frontend React 19 + TypeScript 5.9 + Tailwind 4.

**Spec :** Ce plan implémente la spécification transmise en conversation le 2026-09-25 (§1 à §12), amendée par les sept décisions d'architecture validées et reportées ci-dessous. En cas de contradiction entre le §6/§7/§8 d'origine et la section « Décisions d'architecture validées », **cette dernière fait foi**.

---

## Global Constraints

- **Aucun appel payant en dehors de la cascade finders.** Règle absolue du client. Tout nouvel appel réseau doit être soit gratuit et documenté comme tel, soit passer par le gestionnaire de quota du Lot 2. Aucune exception.
- **Un commit par tâche.** Ne jamais pousser (`git push` interdit), ne jamais créer de branche supplémentaire. Le travail se fait sur `feat/cascade-email-gratuite`, dont la baseline est le commit `3a2d5ba`. Message de commit au format conventionnel, en français, terminé par la ligne `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`.
- **Ne jamais ajouter `docs/` à un commit.** Le `git add` porte uniquement sur les fichiers de la tâche en cours. Un `git add .` est interdit.
- **Plateforme Windows, shell PowerShell 5.1.** Les commandes de test s'écrivent `python -m pytest ...`. `&&` n'existe pas : une commande par ligne.
- **Langue.** Docstrings, noms de symboles et logs techniques en anglais, comme tout le code existant. Messages destinés à l'opérateur — événements SSE, `icp_rationale`, `disqualification_reason`, motifs de statut email, erreurs remontées à l'UI — en français.
- **Modèles Anthropic.** Extraction factuelle : `claude-haiku-4-5-20251001`. Rédaction de l'angle : `config.LLM_MODEL`. Ne jamais coder en dur un identifiant de modèle ailleurs que dans ces deux modules. Ce plan n'en introduit aucun nouveau.
- **Aucune valeur de quota en dur dans le code de production.** Les allocations Prospeo / Hunter / GetProspect vivent dans `config.py`, alimentées par `.env`. Aucun module ne réécrit `100` ou `50` en dur. **Côté tests, la règle est différente et tout aussi stricte** : un test ne doit jamais dépendre des défauts de production, parce que ceux-ci viennent de `.env` et changent d'une machine à l'autre. Un test qui a besoin d'une allocation la fixe lui-même (`monkeypatch.setitem(config.PROVIDER_ALLOCATIONS, ...)`) puis assert une valeur littérale lisible. Un test qui écrit `assert remaining == 80.0` en s'appuyant sur le fait que GetProspect vaut 50 par défaut casse dès que l'opérateur édite son `.env`.
- **Pas de régression sur les pools existants.** `api/leads_db.py` doit continuer à lire les pools créés avant la refonte : les colonnes absentes ressortent à `None`, jamais une exception. Toute nouvelle colonne passe par `_LEAD_POOL_ADDED_COLUMNS`.
- **Les données Apollo ne sont pas sourcées.** Le score de passe 1 ne sort jamais dans le CSV comme verdict, n'alimente jamais `icp_tier`, et ne produit jamais de disqualification. Il vit dans une colonne `prescore` distincte, documentée comme outil d'arbitrage de dépense.
- **Aucun statut inconnu ne doit faire planter un client.** Les trois fournisseurs ont des énumérations de statut incomplètement documentées. Tout statut non reconnu se traite comme « non envoyable », jamais comme une exception.

---

## Décisions d'architecture validées (2026-09-25)

Ces sept décisions amendent la spécification d'origine. Elles sont normatives.

| # | Décision | Effet sur le spec |
|---|---|---|
| 1 | **Mobile depuis le site uniquement.** `enrich_mobile: false` en dur chez Prospeo. | Un mobile coûte 10 crédits Prospeo, soit 10 % de l'allocation mensuelle par lead. Les téléphones viennent exclusivement de `phone_extractor`. |
| 2 | **Europe pertinente mais secondaire.** France 20, Belgique/Suisse/Luxembourg/Canada 10, reste de l'Afrique 70. | Amende §8 : plus de disqualification géographique sur l'Europe. Seuls les pays hors de toutes les zones sont disqualifiés. |
| 3 | **La passe 1 ne fait que trier.** Aucune disqualification dure avant les faits sourcés. | Amende §7 : la ligne « Disqualifications dures appliquées dès ici » est supprimée. Un lead mal classé par Apollo perd sa place dans la file, jamais son existence. |
| 4 | **Pas de `domain-search` Hunter.** Le champ `data.pattern` n'est pas utilisé. | Le format d'entreprise se déduit exclusivement d'un `nominatif_autre` trouvé sur le site. Économise les crédits et évite le plafond `limit+offset > 10` du plan gratuit. |
| 5 | **Score ICP en deux passes, joignabilité booléenne.** | **Remplace intégralement §6.** Le hit score disparaît. Voir « Le nouveau modèle de scoring » ci-dessous. |
| 6 | **Cache `email_lookup_cache` expirant à 90 jours.** | Aligné sur la fenêtre de déduplication gratuite de Prospeo : au-delà, le fournisseur refacture, donc notre cache doit aussi réinterroger. |
| 7 | **Ordre des vérificateurs : GetProspect, puis Hunter.** | Confirme §5c. GetProspect dispose d'un quota de vérification séparé (100/mois) qui ne sert à rien d'autre ; Hunter puise dans un pool unifié partagé avec ses recherches. |

### Le nouveau modèle de scoring

Le hit score mesurait la joignabilité et servait de vanne pour les étapes coûteuses. Il est supprimé. À sa place :

**`prescore` (passe 1, gratuit, non sourcé).** Calculé sur les axes secteur, taille et localisation à partir des colonnes Apollo et du texte de la page d'accueil, avec les tables existantes de `config/icp_rules.json`. Une donnée absente vaut 0 sur son axe et ne disqualifie jamais. Sert **uniquement** à ordonner la file de dépense — crédits finders et enrichissement Perplexity/Claude vont aux leads par `prescore` décroissant. N'apparaît jamais dans `icp_tier`.

**`icp_score` (passe 2, sourcé).** Inchangé dans son principe : `processors/icp_scorer.py` sur les faits validés de `enrichers/fact_extractor.py`. Écrase toute notion de classement provisoire. Reste la seule valeur que l'opérateur lit comme verdict.

**`reachable` (booléen).** Vrai dès qu'il existe au moins une route de contact exploitable : un email de statut `valid_nominatif`, `valid_generique` ou `catch_all`, ou un téléphone, ou un lien WhatsApp affiché par l'entreprise. Un LinkedIn seul ne suffit pas — ce n'est pas une route de contact directe. Un lead non joignable est exporté mais ne consomme ni crédit ni enrichissement.

**`pending_quota`.** N'est ni joignable ni non joignable : son statut est indéterminé faute de quota. Il n'est jamais écarté, part dans son propre CSV, et remonte en tête de la première file après le reset mensuel.

Conséquence sur le flux :

```
GRATUIT — tous les leads
  Apollo (nom, poste, société, lieu, employés, secteur)
  -> LinkedIn (Serper / DuckDuckGo)
  -> site candidat (Clearbit / Serper / DuckDuckGo)
  -> fetch page d'accueil + controle de coherence     <-- un seul fetch
  -> crawl <=5 pages contact + extraction emails/tels/WhatsApp/reseaux
  -> MX du domaine
  -> PRESCORE (secteur / taille / localisation)       <-- ordonne la file
  -> liste de suppression + dedoublonnage
        |
        v  par prescore decroissant, dans la limite du quota
PAYANT (sous quota, jamais bloquant)
  catch-all du domaine (cache par domaine)
  -> cascade email : site -> pattern -> verification -> finders
  -> Perplexity + Claude faits sources
  -> ICP_SCORE passe 2 (ecrase le prescore comme verdict)
  -> angles commerciaux
```

---

## Structure des fichiers

### Créés

| Fichier | Responsabilité |
|---|---|
| `api/quota_db.py` | Tables `provider_quota` et `email_lookup_cache`, lecture/réservation/décrément |
| `api/suppression_db.py` | Table `suppression_list`, vérification et import CSV |
| `api/routes/suppression.py` | Routes CRUD et upload CSV de la liste de suppression |
| `enrichers/providers/__init__.py` | Paquet des clients fournisseurs |
| `enrichers/providers/base.py` | `EmailResult`, `ProviderOutcome`, protocole commun aux trois clients |
| `enrichers/providers/prospeo.py` | Client `POST /enrich-person` |
| `enrichers/providers/getprospect.py` | Client `POST /v2/email/find` et `/v2/email/verify` |
| `enrichers/providers/hunter.py` | Client `/v2/email-finder`, `/v2/email-verifier`, `/v2/account` |
| `enrichers/providers/quota_sync.py` | Synchronisation des quotas, modes *pull* et *piggyback* |
| `enrichers/contact_extractor.py` | Crawl des pages contact, extraction et classement des emails, WhatsApp, réseaux |
| `enrichers/phone_extractor.py` | Extraction et typage des téléphones via `phonenumbers` |
| `enrichers/domain_intel.py` | MX, fournisseur mail, détection catch-all avec cache par domaine |
| `enrichers/email_patterns.py` | Génération de candidats email, déduction de format, particules |
| `enrichers/email_cascade.py` | Orchestration a→b→c→d→e de la cascade |
| `processors/prescore.py` | Score ICP de passe 1 sur données gratuites |
| `processors/reachability.py` | Calcul du booléen `reachable` et du meilleur niveau de contact |
| `tests/test_quota_db.py` | Réservation, décrément sur facturé, reset, report plafonné |
| `tests/test_quota_sync.py` | Modes pull et piggyback, tolérance aux champs absents |
| `tests/test_contact_extractor.py` | Masquages, Cloudflare, faux positifs, classement |
| `tests/test_phone_extractor.py` | Numéros marocains et africains, mobile vs fixe |
| `tests/test_domain_intel.py` | MX absent, catch-all, réutilisation du cache |
| `tests/test_email_patterns.py` | Particules, noms composés, déduction depuis un autre email |
| `tests/test_email_cascade.py` | Ordre, arrêt au premier succès, `pending_quota` |
| `tests/test_prescore.py` | Donnée absente sans disqualification, ordonnancement |
| `tests/test_reachability.py` | Booléen et niveaux de contact |
| `tests/test_provider_prospeo.py` | Réponses figées de la doc Prospeo |
| `tests/test_provider_getprospect.py` | Enveloppe `success`, 200 sur non-trouvé, 402 |
| `tests/test_provider_hunter.py` | 202, 222, 403 vs 429, énumérations distinctes |
| `tests/test_suppression.py` | Vérification avant enrichissement, import CSV |

### Modifiés

| Fichier | Nature de la modification |
|---|---|
| `requirements.txt` | Ajout `phonenumbers`, `dnspython` |
| `.env.example` | `DROPCONTACT_*` retirés ; clés et allocations des trois fournisseurs |
| `config.py` | Idem, plus les constantes d'allocation et le retrait des `SCORE_*` |
| `config/icp_rules.json` | Zone `reste_afrique`, repondération Europe |
| `lead_schema.py` | Douze colonnes ajoutées, `hit_score`/`is_hit` retirées |
| `enrichers/retry.py` | Exceptions distinctes pour quota, rate limit, échec rejouable |
| `enrichers/google_search.py` | `verify_website()` retourne le HTML récupéré |
| `enrichers/hunter_verifier.py` | **Absorbé par `enrichers/providers/hunter.py`, puis supprimé** |
| `enrichers/evidence_collector.py` | Réutilise le texte de page déjà extrait |
| `scrapers/website_scraper.py` | Consomme le HTML mis en cache plutôt que de refetcher |
| `scrapers/apollo_scraper.py` | `_JS_EXTRACT` : colonnes employés et secteur |
| `processors/hit_calculator.py` | **Vidé de son barème**, devient l'appelant de `reachability` |
| `processors/icp_scorer.py` | Aucun changement de logique ; tests étendus à la nouvelle géographie |
| `api/provider_status.py` | `PROVIDER_GROUPS` en remplacement de `CRITICAL_PROVIDERS` |
| `api/leads_db.py` | Clés de dédoublonnage de repli, nouvelles colonnes de pool |
| `api/models.py` | `JobStats` et `LeadRecord` alignés sur le nouveau schéma |
| `api/pipeline_runner.py` | Trois runners, `STEP_PATTERNS`, `STEP_WEIGHTS`, stats, résumé |
| `api/routes/config.py` | Clés Prospeo/GetProspect, `validate-key`, exposition des quotas |
| `api/routes/pipeline.py` | Tri par `prescore`, CSV `pending_quota` |
| `api/server.py` | Enregistrement des nouvelles tables et du routeur suppression |
| `main.py` | CLI alignée sur la nouvelle cascade |
| `frontend/src/lib/api.ts` | Nouveaux endpoints et champs |
| `frontend/src/components/Settings.tsx` | Clés, panneau quotas, import suppression |
| `frontend/src/components/ResultsTable.tsx` | Colonnes email/téléphone/prescore, onglet `pending_quota` |
| `frontend/src/components/LeadDetailModal.tsx` | Source du contact, URL de provenance, statut de domaine |
| `frontend/src/components/StatsBar.tsx` | Taux par source, mobile, WhatsApp, crédits |
| `tests/test_hit_calculator.py` | Réécrit autour de `reachability` |
| `tests/test_icp_scorer.py` | Cas de la nouvelle géographie |
| `tests/test_provider_status.py` | Groupes de fournisseurs |
| `tests/test_lead_schema.py` | Nouvelles colonnes |

### Supprimés

| Fichier | Raison |
|---|---|
| `enrichers/dropcontact.py` | Fournisseur payant retiré |
| `tests/test_dropcontact.py` | Idem |
| `enrichers/hunter_verifier.py` | Absorbé par `enrichers/providers/hunter.py` |

---

## Référence API — valeurs vérifiées dans la documentation officielle

Cette section est normative. Elle a été établie par lecture directe des docs le 2026-09-25. **Ne pas deviner au-delà de ce tableau ; les points marqués NON DOCUMENTÉ exigent un traitement défensif.**

### Prospeo — `https://api.prospeo.io`

L'ancien `/email-finder` **n'existe plus** et n'a plus de page de documentation. L'équivalent fonctionnel est `/enrich-person`. Prospeo **n'a aucun endpoint de vérification d'email**.

| Élément | Valeur |
|---|---|
| Recherche | `POST /enrich-person` |
| Compte | `GET /account-information` — **gratuit** |
| Auth | Header `X-KEY: <clé>` (pas de `Bearer`), plus `Content-Type: application/json` obligatoire |
| Corps | `{"only_verified_email": true, "enrich_mobile": false, "data": {"first_name", "last_name", "company_website"}}` |
| Email dans la réponse | `person.email.{status, revealed, email, verification_method, email_mx_provider}` |
| `person.email.status` | `VERIFIED` \| `UNAVAILABLE` — deux valeurs seulement |
| Signal de facturation | `free_enrichment` (racine, booléen) — `true` = **non débité** |
| Quota épuisé | `HTTP 400` + `{"error": true, "error_code": "INSUFFICIENT_CREDITS"}` |
| Clé invalide | `HTTP 400` + `error_code: "INVALID_API_KEY"` |
| Aucun résultat | `HTTP 400` + `error_code: "NO_MATCH"` — **non facturé** |
| Compte : champs | `response.{remaining_credits, used_credits, next_quota_renewal_date}` — imbriqués sous `response`, contrairement à `/enrich-person` |

**Piège** : Prospeo répond `400` pour *toutes* les erreurs métier, y compris « aucun résultat ». Le code HTTP seul ne dit rien — parser `error_code` avant tout.

**Facturation** : 1 crédit par email trouvé. Pas de débit sans résultat. Ré-enrichir le même contact dans les 90 jours est gratuit (`free_enrichment: true`). `only_verified_email: true` renvoie `NO_MATCH` sans débit si le lead n'a pas d'email vérifié — c'est un filtre gratuit, on l'utilise systématiquement.

**Allocation du plan gratuit : NON DOCUMENTÉ dans la doc API.** Défaut de configuration à 100, corrigé au premier run par `/account-information`.

### GetProspect — `https://api.getprospect.com`

⚠️ `getprospect.readme.io` est une doc **périmée** (en-tête `apiKey`, requêtes GET). La référence est `getprospect.com/api-docs` (API v2). **Ne pas coder contre readme.io.**

| Élément | Valeur |
|---|---|
| Recherche | `POST /v2/email/find` — corps `{"data": {"first_name", "last_name", "domain"}}` |
| Vérification | `POST /v2/email/verify` — corps `{"data": {"email"}}` |
| Compte | **N'existe pas** |
| Auth | Header `x-api-key: <clé>` |
| Réponse | Enveloppe `{success, data, metadata, errors}` |
| Données | `data.{email, status, account, domain, domain_status, smtp_provider, free_email}` |
| Solde | `metadata.credits.{email_search, email_verification, reset_at}` — présent sur **chaque** réponse réussie |
| Quota épuisé | `HTTP 402` + `errors[0].name == "PAYMENT_REQUIRED"`, en-têtes `X-Limit-Reached: true`, `X-Limit-Type: credits` |
| Clé invalide | `HTTP 401` + `errors[0].name == "UNAUTHORIZED"` |
| Timeout rejouable | `HTTP 408` + `errors[0].name == "TIMEOUT"` |
| Aucun résultat | **`HTTP 200`** + `success: false` + `errors[0].name == "NOT_FOUND"` |

**Piège majeur** : « aucun résultat » est un `HTTP 200`. Le prédicat est `payload["success"]` et `errors[0]["name"]`, **jamais** le code HTTP.

**Statuts** : `valid`, `not_found`, `accept_all` sont attestés. L'OpenAPI déclare `status` en `"type": "string"` **sans `enum`** — `invalid` et `unknown` ne sont attestés qu'au niveau produit. **Traiter tout statut inconnu comme non envoyable.** L'Email Finder ne renvoie jamais `accept_all` : il le convertit en `not_found` avec `domain_status: "accept_all"`, et rembourse le crédit.

**Facturation** : 1 crédit email par email trouvé, 1 crédit vérification par vérification. Trois compteurs indépendants. Pas de débit sans résultat ; `not_found` et `accept_all` sont remboursés automatiquement. Les emails trouvés par recherche sont vérifiés d'office et ne consomment **pas** le quota de vérification.

**Plan gratuit** : 50 emails valides + 100 vérifications par mois, report plafonné à une allocation mensuelle.

**Rate limits** : aucun sur les clés réelles aujourd'hui (seul le compte de démonstration est plafonné). Garder une concurrence modeste.

### Hunter — `https://api.hunter.io/v2`

| Élément | Valeur |
|---|---|
| Recherche | `GET /v2/email-finder` — `first_name`, `last_name`, `domain`, `max_duration` (3-20, défaut 10) |
| Vérification | `GET /v2/email-verifier` — `email` |
| Compte | `GET /v2/account` — **gratuit** |
| Auth | Paramètre `api_key`, ou header `X-API-KEY`, ou `Authorization: Bearer` |
| Finder : statut | `data.verification.status` ∈ `valid` \| `accept_all` \| `unknown` — **3 valeurs** |
| Verifier : statut | `data.status` ∈ `valid` \| `invalid` \| `accept_all` \| `webmail` \| `disposable` \| `unknown` — **6 valeurs** |
| Solde | `data.requests.{credits, searches, verifications}.{used, available, remaining}` — **type `number`, pas entier** |
| Reset | `data.reset_date`, chaîne `"YYYY-MM-DD"` |
| **403** | **Rate limit dépassé — rejouable avec backoff** |
| **429** | **Quota mensuel épuisé — arrêt, pas de retry** |
| **202** | Vérification en cours — repoller le même endpoint, **facturé une seule fois** |
| **222** | Échec SMTP distant — dans la plage 2xx mais **c'est un échec**, à réessayer plus tard |
| Aucun résultat | **NON DOCUMENTÉ.** L'OpenAPI garantit `data.email` présent et *nullable*. Tester une valeur falsy, et gérer un `404` possible |

**Pièges** :
- `403` et `429` sont **inversés** par rapport à la convention HTTP. Le code actuel de `enrichers/retry.py` lève `AuthError` sur un `403`, ce qui désactive Hunter pour tout le run sur un simple pic de débit. **C'est un bug en production, corrigé au Lot 2.**
- `222` passe `raise_for_status()` sans erreur et serait lu comme un succès.
- Crédits en flottants : 0,5 par vérification donne `used: 550.0`. Le schéma SQLite doit être `REAL`.
- `requests.credits` n'est présent **que** sur un pool unifié. Absent, il faut lire `searches` et `verifications` séparément. C'est la règle de détection programmatique du modèle de crédits.

**Facturation** : 1 crédit par email trouvé, 0,5 par vérification, pool unifié de 50 crédits sur le plan gratuit. Pas de débit sans résultat. Les requêtes dupliquées dans la même période de facturation ne reconsomment pas de crédit.

**Rate limits documentés** : email-finder 15 req/s et 500 req/min ; email-verifier 10 req/s et 300 req/min.

**Plan gratuit** : 50 crédits unifiés par mois. Contrainte annexe : `limit + offset > 10` sur `domain-search` renvoie `400` — sans effet ici, décision 4 écartant cet endpoint.

---

## Tâches

### Task 1 : Retrait de Dropcontact

**Files:**
- Delete: `enrichers/dropcontact.py`, `tests/test_dropcontact.py`
- Modify: `config.py`, `.env.example`, `main.py:36,178-181`, `api/pipeline_runner.py:308-320,353-355,697-706,723-725`, `api/routes/config.py`, `api/provider_status.py:11`
- Test: `tests/test_provider_status.py`

**Interfaces:**
- Consomme : rien.
- Produit : une base sans fournisseur payant obligatoire. `config.DROPCONTACT_API_KEY` et `config.DROPCONTACT_BATCH_SIZE` n'existent plus ; tout import de `enrichers.dropcontact` casse à l'import, ce qui est voulu — aucun appel résiduel ne doit survivre.

- [ ] **Step 1 : Écrire le test qui échoue**

Dans `tests/test_provider_status.py`, ajouter :

```python
def test_dropcontact_is_no_longer_a_provider():
    """Dropcontact must be gone from the codebase entirely."""
    import importlib
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("enrichers.dropcontact")


def test_no_dropcontact_reference_in_config():
    import config
    assert not hasattr(config, "DROPCONTACT_API_KEY")
    assert not hasattr(config, "DROPCONTACT_BATCH_SIZE")
```

- [ ] **Step 2 : Lancer le test pour vérifier qu'il échoue**

Run : `python -m pytest tests/test_provider_status.py -v -k dropcontact`
Expected : FAIL — le module s'importe encore, `config.DROPCONTACT_API_KEY` existe.

- [ ] **Step 3 : Supprimer les fichiers**

```bash
git rm enrichers/dropcontact.py tests/test_dropcontact.py
```

- [ ] **Step 4 : Nettoyer `config.py`**

Retirer les deux lignes :

```python
DROPCONTACT_API_KEY = os.getenv("DROPCONTACT_API_KEY", "")
DROPCONTACT_BATCH_SIZE = int(os.getenv("DROPCONTACT_BATCH_SIZE", "50"))
```

Retirer aussi les quatre constantes de barème devenues mortes — le scoring de joignabilité disparaît (décision 5) :

```python
SCORE_EMAIL = 40
SCORE_LINKEDIN = 30
SCORE_PHONE = 20
SCORE_WEBSITE = 10
```

- [ ] **Step 5 : Nettoyer `.env.example`**

Supprimer le bloc `DROPCONTACT_API_KEY` et la ligne `DROPCONTACT_BATCH_SIZE=50`.

- [ ] **Step 6 : Nettoyer les trois runners et le CLI**

Dans `api/pipeline_runner.py`, retirer de `_run_pipeline_sync` et `_run_scrape_only_sync` :
- l'import `from enrichers.dropcontact import _reset_state as _reset_dc` et l'appel `_reset_dc()`
- le bloc `# ── Step 3b: Dropcontact enrichment ───` et son `set_explicit_progress`

Retirer `"dropcontact"` de `_PROVIDER_LABELS` (`api/pipeline_runner.py:181`).

Dans `main.py`, retirer l'import ligne 36 et le bloc `# ── Step 3b` lignes 178-181, ainsi que l'entrée `"dropcontact"` de `PROVIDER_LABELS`.

Dans `api/routes/config.py`, retirer `dropcontact_api_key` de `ConfigUpdate`, du dictionnaire retourné par `get_config()` et du bloc d'écriture de `update_config()`.

- [ ] **Step 7 : Neutraliser temporairement `CRITICAL_PROVIDERS`**

Dans `api/provider_status.py`, remplacer :

```python
CRITICAL_PROVIDERS = frozenset({"dropcontact"})
```

par :

```python
# Remplacé par PROVIDER_GROUPS en Task 3. Vide dans l'intervalle : plus aucun
# fournisseur n'est critique à lui seul depuis le retrait de Dropcontact.
CRITICAL_PROVIDERS = frozenset()
```

- [ ] **Step 8 : Lancer la suite complète**

Run : `python -m pytest tests/ -v`
Expected : PASS. Aucun `ImportError`. Si un test échoue sur un import de `enrichers.dropcontact`, c'est une référence résiduelle à supprimer.

- [ ] **Step 9 : Commit**

```bash
git add enrichers/dropcontact.py tests/test_dropcontact.py config.py .env.example main.py api/pipeline_runner.py api/routes/config.py api/provider_status.py tests/test_provider_status.py
git commit -m "feat: retirer Dropcontact et le barème de joignabilité"
```

---

### Task 2 : Exceptions réseau — corriger le bug 403 et gérer 222/402/408/429

**Files:**
- Modify: `enrichers/retry.py`
- Test: `tests/test_retry.py` (créé)

**Interfaces:**
- Consomme : rien.
- Produit : `QuotaExhausted(message)`, `RateLimited(message)`, `RetryableRemoteFailure(message)`, et `AuthError` (existant, resserré sur 401 seul). `retry_api_call(fn, max_retries, base_delay, operation_name)` conserve sa signature. Les trois clients du Lot 6 lèvent ces exceptions ; `enrichers/email_cascade.py` les distingue pour décider entre « fournisseur suivant » et « arrêt du fournisseur ».

**Contexte.** `enrichers/retry.py:47-52` lève `AuthError` sur un `403`. Hunter utilise `403` pour le rate limit et `429` pour le quota épuisé — l'inverse de la convention. Aujourd'hui, un pic de débit sur Hunter désactive le fournisseur pour tout le run. C'est un bug existant en production, pas une régression introduite ici.

- [ ] **Step 1 : Écrire les tests qui échouent**

Créer `tests/test_retry.py` :

```python
import pytest
import requests

from enrichers.retry import (
    AuthError,
    QuotaExhausted,
    RateLimited,
    RetryableRemoteFailure,
    retry_api_call,
)


def _http_error(status: int) -> requests.exceptions.HTTPError:
    response = requests.Response()
    response.status_code = status
    return requests.exceptions.HTTPError(response=response)


def test_401_raises_auth_error():
    def fn():
        raise _http_error(401)
    with pytest.raises(AuthError):
        retry_api_call(fn, max_retries=0, operation_name="test")


def test_403_is_a_rate_limit_not_an_auth_error():
    """Hunter uses 403 for rate limiting. Treating it as auth kills the
    provider for the whole run on a transient throughput spike."""
    def fn():
        raise _http_error(403)
    with pytest.raises(RateLimited):
        retry_api_call(fn, max_retries=0, base_delay=0, operation_name="test")


def test_429_is_quota_exhausted_and_never_retried():
    calls = []

    def fn():
        calls.append(1)
        raise _http_error(429)

    with pytest.raises(QuotaExhausted):
        retry_api_call(fn, max_retries=3, base_delay=0, operation_name="test")
    assert len(calls) == 1, "un quota épuisé ne doit jamais être réessayé"


def test_402_is_quota_exhausted():
    """GetProspect signals an exhausted credit balance with 402."""
    def fn():
        raise _http_error(402)
    with pytest.raises(QuotaExhausted):
        retry_api_call(fn, max_retries=0, operation_name="test")


def test_408_is_retryable():
    def fn():
        raise _http_error(408)
    with pytest.raises(RetryableRemoteFailure):
        retry_api_call(fn, max_retries=0, base_delay=0, operation_name="test")


def test_222_is_retryable():
    """Hunter's non-standard 222 sits inside the 2xx range but is a failure:
    the remote SMTP server misbehaved."""
    def fn():
        raise _http_error(222)
    with pytest.raises(RetryableRemoteFailure):
        retry_api_call(fn, max_retries=0, base_delay=0, operation_name="test")


def test_retryable_failure_is_actually_retried_then_succeeds():
    attempts = []

    def fn():
        attempts.append(1)
        if len(attempts) < 3:
            raise _http_error(503)
        return "ok"

    assert retry_api_call(fn, max_retries=3, base_delay=0, operation_name="test") == "ok"
    assert len(attempts) == 3
```

- [ ] **Step 2 : Lancer les tests pour vérifier qu'ils échouent**

Run : `python -m pytest tests/test_retry.py -v`
Expected : FAIL — `ImportError: cannot import name 'QuotaExhausted'`.

- [ ] **Step 3 : Implémenter**

Dans `enrichers/retry.py`, ajouter les exceptions au-dessus de `retry_api_call` :

```python
class QuotaExhausted(Exception):
    """Monthly allowance spent. Never retried: the balance will not come back
    within this run. Hunter signals it with 429, GetProspect with 402."""


class RateLimited(Exception):
    """Throughput ceiling hit. Retried with backoff — this is transient.

    Hunter returns 403 here, not 429: the two are inverted relative to the
    usual HTTP convention. Reading 403 as an auth failure (as this module
    did until 2026-09-25) disabled the provider for the whole run on a
    transient spike.
    """


class RetryableRemoteFailure(Exception):
    """The remote side failed in a way that may not repeat: 408 timeout,
    Hunter's non-standard 222 (remote SMTP server misbehaved), or any 5xx."""


_QUOTA_STATUSES = frozenset({402, 429})
_RATE_LIMIT_STATUSES = frozenset({403})
_RETRYABLE_STATUSES = frozenset({222, 408})
```

Puis, dans `retry_api_call`, remplacer intégralement le bloc `except requests.exceptions.HTTPError as e:` :

```python
        except requests.exceptions.HTTPError as e:
            resp = e.response
            status = resp.status_code if resp is not None else None
            if status == 401:
                raise AuthError(
                    f"{operation_name}: authentication failed (HTTP 401). "
                    f"Check your API key."
                ) from e
            if status in _QUOTA_STATUSES:
                raise QuotaExhausted(
                    f"{operation_name}: provider quota exhausted (HTTP {status})."
                ) from e
            if status in _RATE_LIMIT_STATUSES:
                last_exc = RateLimited(f"{operation_name}: rate limited (HTTP {status}).")
            elif status is not None and (status in _RETRYABLE_STATUSES or status >= 500):
                last_exc = RetryableRemoteFailure(
                    f"{operation_name}: remote failure (HTTP {status})."
                )
            else:
                last_exc = e
```

- [ ] **Step 4 : Lancer les tests pour vérifier qu'ils passent**

Run : `python -m pytest tests/test_retry.py -v`
Expected : PASS — 7 tests.

- [ ] **Step 5 : Vérifier la non-régression**

Run : `python -m pytest tests/ -v`
Expected : PASS. `tests/test_hunter_verifier.py` et `tests/test_google_search.py` reposent sur `AuthError` pour le 401 — ce comportement est inchangé.

- [ ] **Step 6 : Commit**

```bash
git add enrichers/retry.py tests/test_retry.py
git commit -m "fix: 403 est un rate limit chez Hunter, pas une erreur d'authentification"
```

---

### Task 3 : Groupes de fournisseurs dans le registre

**Files:**
- Modify: `api/provider_status.py`
- Test: `tests/test_provider_status.py`

**Interfaces:**
- Consomme : `StepOutcome`, `ProviderRegistry` (existants).
- Produit : `PROVIDER_GROUPS: dict[str, frozenset[str]]`, `CRITICAL_GROUPS: frozenset[str]`, `ProviderRegistry.group_status(group) -> str` renvoyant `"ok" | "degraded" | "failed" | "skipped"`, `ProviderRegistry.impaired_groups() -> dict[str, str]`, et `has_critical_failure()` conservée mais redéfinie sur les groupes. `api/pipeline_runner.py` (Task 22) l'utilise pour choisir entre `done`, `completed_with_errors` et `error`.

**Contexte.** Plus aucun fournisseur email n'est critique à lui seul (§1 du spec). Le run passe en `completed_with_errors` si **un** membre du groupe email est `failed` ou `degraded`, et en `error` seulement si **tous** le sont.

- [ ] **Step 1 : Écrire les tests qui échouent**

Ajouter à `tests/test_provider_status.py` :

```python
from api.provider_status import PROVIDER_GROUPS, ProviderRegistry, StepOutcome


def test_email_group_is_ok_when_every_member_answers():
    registry = ProviderRegistry()
    for name in PROVIDER_GROUPS["email"]:
        registry.record(StepOutcome(name, "ok", None, 5))
    assert registry.group_status("email") == "ok"


def test_email_group_is_degraded_when_one_member_fails():
    registry = ProviderRegistry()
    members = sorted(PROVIDER_GROUPS["email"])
    registry.record(StepOutcome(members[0], "failed", "clé rejetée", 3))
    for name in members[1:]:
        registry.record(StepOutcome(name, "ok", None, 5))
    assert registry.group_status("email") == "degraded"
    assert registry.has_critical_failure() is False


def test_email_group_fails_only_when_every_member_is_down():
    registry = ProviderRegistry()
    for name in PROVIDER_GROUPS["email"]:
        registry.record(StepOutcome(name, "failed", "quota épuisé", 10))
    assert registry.group_status("email") == "failed"
    assert registry.has_critical_failure() is True


def test_a_skipped_member_does_not_count_as_a_failure():
    """An operator who never configured GetProspect has not suffered an outage."""
    registry = ProviderRegistry()
    members = sorted(PROVIDER_GROUPS["email"])
    registry.record(StepOutcome(members[0], "skipped", "clé API absente", 0))
    for name in members[1:]:
        registry.record(StepOutcome(name, "ok", None, 5))
    assert registry.group_status("email") == "ok"


def test_group_status_is_skipped_when_no_member_was_configured():
    registry = ProviderRegistry()
    for name in PROVIDER_GROUPS["email"]:
        registry.record(StepOutcome(name, "skipped", "clé API absente", 0))
    assert registry.group_status("email") == "skipped"
    assert registry.has_critical_failure() is False


def test_unreported_members_are_ignored():
    """A provider the run never reached says nothing about the group's health."""
    registry = ProviderRegistry()
    registry.record(StepOutcome("prospeo", "ok", None, 2))
    assert registry.group_status("email") == "ok"


def test_impaired_groups_lists_only_what_is_worth_reporting():
    registry = ProviderRegistry()
    members = sorted(PROVIDER_GROUPS["email"])
    registry.record(StepOutcome(members[0], "degraded", "quota épuisé", 4))
    for name in members[1:]:
        registry.record(StepOutcome(name, "ok", None, 5))
    assert registry.impaired_groups() == {"email": "degraded"}
```

- [ ] **Step 2 : Lancer les tests pour vérifier qu'ils échouent**

Run : `python -m pytest tests/test_provider_status.py -v`
Expected : FAIL — `ImportError: cannot import name 'PROVIDER_GROUPS'`.

- [ ] **Step 3 : Implémenter**

Dans `api/provider_status.py`, remplacer `CRITICAL_PROVIDERS` :

```python
# Providers grouped by the deliverable they serve. A group degrades when one
# member is impaired and fails only when every configured member is down:
# since Dropcontact was removed, no single email provider is load-bearing,
# and reporting a run as failed because one of three finders lost its key
# would be as misleading as reporting it green.
PROVIDER_GROUPS: dict[str, frozenset[str]] = {
    "email": frozenset({"prospeo", "getprospect", "hunter"}),
}

# Groups whose total failure invalidates the run's core deliverable.
CRITICAL_GROUPS = frozenset({"email"})
```

Ajouter à `ProviderRegistry` :

```python
    def group_status(self, group: str) -> str:
        """Aggregate one group's outcomes into a single status.

        "skipped" members are excluded from the health verdict: a provider the
        operator never configured is not an outage. A group where every member
        is skipped is itself "skipped", not "failed" — nothing broke, nothing
        was ever asked to work.
        """
        members = PROVIDER_GROUPS.get(group, frozenset())
        reported = [self._outcomes[name] for name in members if name in self._outcomes]
        if not reported:
            return "skipped"

        active = [o for o in reported if o.status != "skipped"]
        if not active:
            return "skipped"
        # "failed" requires the whole group to have been heard from. The
        # cascade stops at its first success, so unreported members are the
        # normal case, not an anomaly: concluding total failure from the one
        # member that happened to report would make that member load-bearing
        # again — exactly what removing Dropcontact was meant to end.
        if len(reported) == len(members) and all(
            o.status in ("failed", "degraded") for o in active
        ):
            return "failed"
        if any(o.status in ("failed", "degraded") for o in active):
            return "degraded"
        return "ok"

    def has_critical_failure(self) -> bool:
        """True when a critical group lost every one of its active members."""
        return any(self.group_status(g) == "failed" for g in CRITICAL_GROUPS)

    def impaired_groups(self) -> dict[str, str]:
        """Groups worth reporting to the operator, with their status."""
        return {
            group: status
            for group in PROVIDER_GROUPS
            if (status := self.group_status(group)) in ("degraded", "failed")
        }
```

- [ ] **Step 4 : Lancer les tests pour vérifier qu'ils passent**

Run : `python -m pytest tests/test_provider_status.py -v`
Expected : PASS.

- [ ] **Step 5 : Commit**

```bash
git add api/provider_status.py tests/test_provider_status.py
git commit -m "feat: statut de fournisseurs par groupe, plus de fournisseur critique isolé"
```

---

### Task 4 : Table `provider_quota` et gestionnaire de quota

**Files:**
- Create: `api/quota_db.py`, `tests/test_quota_db.py`
- Modify: `config.py`, `.env.example`, `api/server.py`

**Interfaces:**
- Consomme : `config.OUTPUT_DIR`, `config.PROVIDER_ALLOCATIONS`, `config.PROVIDER_ROLLOVER_CAP`.
- Produit :
  - `init_quota_tables() -> None`
  - `get_quota(provider: str) -> dict` → `{provider, allocation, consumed, remaining, reset_date, rollover_cap}`
  - `can_spend(provider: str, cost: float = 1.0) -> bool`
  - `record_spend(provider: str, cost: float, billed: bool) -> None` — **ne décrémente que si `billed` est vrai**
  - `sync_remaining(provider: str, remaining: float, reset_date: str | None) -> None`
  - `apply_monthly_reset(provider: str, today: date | None = None) -> None`
  Consommés par `enrichers/email_cascade.py` (Task 17) et `enrichers/providers/quota_sync.py` (Task 6).

- [ ] **Step 1 : Écrire les tests qui échouent**

Créer `tests/test_quota_db.py` :

```python
from datetime import date

import pytest

from api import quota_db


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(quota_db, "_DB_PATH", str(tmp_path / "quota.db"))
    quota_db.init_quota_tables()


def test_spending_a_billed_result_decrements():
    quota_db.sync_remaining("prospeo", 100.0, "2026-10-01")
    quota_db.record_spend("prospeo", cost=1.0, billed=True)
    assert quota_db.get_quota("prospeo")["remaining"] == 99.0


def test_an_unbilled_result_never_decrements():
    """Prospeo returns free_enrichment=true, GetProspect refunds not_found,
    Hunter charges nothing when no email is found. None of these may cost us
    a unit of local budget, or the counter drifts below the provider's."""
    quota_db.sync_remaining("prospeo", 100.0, "2026-10-01")
    quota_db.record_spend("prospeo", cost=1.0, billed=False)
    assert quota_db.get_quota("prospeo")["remaining"] == 100.0


def test_fractional_cost_is_preserved():
    """Hunter charges 0.5 credit per verification: an integer column would
    silently round every verification to zero or one."""
    quota_db.sync_remaining("hunter", 50.0, "2026-10-01")
    quota_db.record_spend("hunter", cost=0.5, billed=True)
    quota_db.record_spend("hunter", cost=0.5, billed=True)
    assert quota_db.get_quota("hunter")["remaining"] == 49.0


def test_can_spend_is_false_when_remaining_is_below_cost():
    quota_db.sync_remaining("hunter", 0.4, "2026-10-01")
    assert quota_db.can_spend("hunter", cost=0.5) is False
    assert quota_db.can_spend("hunter", cost=0.4) is True


def test_sync_overrides_the_local_counter():
    """The provider is always right: a local counter that drifted must yield."""
    quota_db.sync_remaining("getprospect", 50.0, "2026-10-01")
    quota_db.record_spend("getprospect", cost=1.0, billed=True)
    quota_db.sync_remaining("getprospect", 12.0, "2026-10-01")
    assert quota_db.get_quota("getprospect")["remaining"] == 12.0


def test_reset_restores_the_allocation_plus_capped_rollover():
    """GetProspect carries unused credits forward, capped at one allowance."""
    quota_db.sync_remaining("getprospect", 30.0, "2026-09-01")
    quota_db.apply_monthly_reset("getprospect", today=date(2026, 10, 1))
    quota = quota_db.get_quota("getprospect")
    assert quota["remaining"] == 80.0  # 50 allocation + 30 reportés
    assert quota["reset_date"] == "2026-11-01"


def test_rollover_is_capped_at_one_allowance():
    quota_db.sync_remaining("getprospect", 90.0, "2026-09-01")
    quota_db.apply_monthly_reset("getprospect", today=date(2026, 10, 1))
    assert quota_db.get_quota("getprospect")["remaining"] == 100.0  # 50 + 50 max


def test_provider_without_rollover_starts_from_scratch():
    """Prospeo credits do not carry over."""
    quota_db.sync_remaining("prospeo", 40.0, "2026-09-01")
    quota_db.apply_monthly_reset("prospeo", today=date(2026, 10, 1))
    assert quota_db.get_quota("prospeo")["remaining"] == 100.0


def test_reset_is_a_no_op_before_the_reset_date():
    quota_db.sync_remaining("prospeo", 40.0, "2026-10-01")
    quota_db.apply_monthly_reset("prospeo", today=date(2026, 9, 25))
    assert quota_db.get_quota("prospeo")["remaining"] == 40.0


def test_unknown_provider_reads_its_configured_allocation():
    assert quota_db.get_quota("hunter")["allocation"] == 50.0
```

- [ ] **Step 2 : Lancer les tests pour vérifier qu'ils échouent**

Run : `python -m pytest tests/test_quota_db.py -v`
Expected : FAIL — `ModuleNotFoundError: No module named 'api.quota_db'`.

- [ ] **Step 3 : Ajouter les allocations dans `config.py`**

```python
# ── Provider quotas ───────────────────────────────────────────────────────────
# Free-tier defaults per provider, corrected at the start of every run by
# enrichers/providers/quota_sync.py wherever the provider exposes its balance.
# Never hardcoded anywhere else.
PROVIDER_ALLOCATIONS: dict[str, float] = {
    "prospeo": float(os.getenv("PROSPEO_MONTHLY_ALLOCATION", "100")),
    "hunter": float(os.getenv("HUNTER_MONTHLY_ALLOCATION", "50")),
    "getprospect": float(os.getenv("GETPROSPECT_MONTHLY_ALLOCATION", "50")),
    "getprospect_verify": float(os.getenv("GETPROSPECT_VERIFY_ALLOCATION", "100")),
}

# Carry-over of unspent credits, expressed as a multiple of the allowance.
# 0.0 = no carry-over. GetProspect carries up to one month's allowance.
PROVIDER_ROLLOVER_CAP: dict[str, float] = {
    "prospeo": float(os.getenv("PROSPEO_ROLLOVER_CAP", "0")),
    "hunter": float(os.getenv("HUNTER_ROLLOVER_CAP", "0")),
    "getprospect": float(os.getenv("GETPROSPECT_ROLLOVER_CAP", "1")),
    "getprospect_verify": float(os.getenv("GETPROSPECT_VERIFY_ROLLOVER_CAP", "1")),
}

PROSPEO_API_KEY = os.getenv("PROSPEO_API_KEY", "")
GETPROSPECT_API_KEY = os.getenv("GETPROSPECT_API_KEY", "")
```

Ajouter les entrées correspondantes dans `.env.example`, avec un commentaire indiquant que les allocations sont synchronisées automatiquement quand le fournisseur le permet.

- [ ] **Step 4 : Implémenter `api/quota_db.py`**

```python
"""
Per-provider quota accounting.

The pipeline runs entirely on free tiers: 50 to 100 lookups a month across
three providers. A counter that drifts above the provider's real balance
spends credits the run does not have and fails mid-cascade; one that drifts
below leaves paid-for lookups unused. Both are silent, so the provider's own
number always wins (see sync_remaining) and the local counter only moves on a
result the provider actually billed.
"""
import os
import sqlite3
from datetime import date
from typing import Optional

import config as pipeline_config

_DB_PATH = os.path.join(pipeline_config.OUTPUT_DIR, "history.db")

_CREATE_PROVIDER_QUOTA = """
CREATE TABLE IF NOT EXISTS provider_quota (
    provider     TEXT PRIMARY KEY,
    allocation   REAL NOT NULL,
    consumed     REAL NOT NULL DEFAULT 0,
    remaining    REAL NOT NULL,
    reset_date   TEXT,
    rollover_cap REAL NOT NULL DEFAULT 0,
    synced_at    TEXT
)
"""


def _conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(_DB_PATH), exist_ok=True)
    con = sqlite3.connect(_DB_PATH, timeout=5)
    con.row_factory = sqlite3.Row
    return con


def init_quota_tables() -> None:
    with _conn() as con:
        con.execute(_CREATE_PROVIDER_QUOTA)
        for provider, allocation in pipeline_config.PROVIDER_ALLOCATIONS.items():
            cap = pipeline_config.PROVIDER_ROLLOVER_CAP.get(provider, 0.0)
            # allocation and rollover_cap belong to config, so they are
            # re-asserted on every start: editing .env has to actually take
            # effect, and the free-tier numbers this pipeline runs on are not
            # all documented (Prospeo publishes none), so the operator will
            # correct them. remaining, consumed and reset_date are runtime
            # state and are left alone — raising an allowance must never hand
            # out credits, it only changes what the next reset restores to.
            con.execute(
                """INSERT INTO provider_quota
                   (provider, allocation, consumed, remaining, rollover_cap)
                   VALUES (?, ?, 0, ?, ?)
                   ON CONFLICT(provider) DO UPDATE SET
                     allocation = excluded.allocation,
                     rollover_cap = excluded.rollover_cap""",
                (provider, allocation, allocation, cap),
            )


def get_quota(provider: str) -> dict:
    with _conn() as con:
        row = con.execute(
            "SELECT * FROM provider_quota WHERE provider = ?", (provider,)
        ).fetchone()
    if row is None:
        allocation = pipeline_config.PROVIDER_ALLOCATIONS.get(provider, 0.0)
        return {
            "provider": provider, "allocation": allocation, "consumed": 0.0,
            "remaining": allocation, "reset_date": None,
            "rollover_cap": pipeline_config.PROVIDER_ROLLOVER_CAP.get(provider, 0.0),
        }
    return dict(row)


def can_spend(provider: str, cost: float = 1.0) -> bool:
    return get_quota(provider)["remaining"] >= cost


def record_spend(provider: str, cost: float, billed: bool) -> None:
    """Decrement only when the provider actually charged us.

    All three providers return results they do not bill: Prospeo's 90-day
    re-enrichment (free_enrichment=true), GetProspect's automatic refund on
    not_found and accept_all, and every provider's "no result, no charge".
    Decrementing on those would exhaust a 50-credit month in a fraction of
    the lookups it can really afford.
    """
    if not billed:
        return
    with _conn() as con:
        con.execute(
            """UPDATE provider_quota
               SET consumed = consumed + ?, remaining = MAX(0, remaining - ?)
               WHERE provider = ?""",
            (cost, cost, provider),
        )


def sync_remaining(provider: str, remaining: float, reset_date: Optional[str]) -> None:
    """Adopt the provider's own balance, which always supersedes ours."""
    allocation = pipeline_config.PROVIDER_ALLOCATIONS.get(provider, remaining)
    cap = pipeline_config.PROVIDER_ROLLOVER_CAP.get(provider, 0.0)
    with _conn() as con:
        con.execute(
            """INSERT INTO provider_quota
               (provider, allocation, consumed, remaining, reset_date, rollover_cap, synced_at)
               VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
               ON CONFLICT(provider) DO UPDATE SET
                 remaining = excluded.remaining,
                 consumed = MAX(0, provider_quota.allocation - excluded.remaining),
                 reset_date = COALESCE(excluded.reset_date, provider_quota.reset_date),
                 synced_at = excluded.synced_at""",
            (provider, allocation, max(0.0, allocation - remaining), remaining,
             reset_date, cap),
        )


def _next_month(today: date) -> date:
    return date(today.year + (today.month == 12), (today.month % 12) + 1, 1)


def apply_monthly_reset(provider: str, today: Optional[date] = None) -> None:
    """Restore the allowance when the reset date has passed.

    Rollover is expressed as a multiple of the allowance, so a provider that
    does not carry credits forward (Prospeo, Hunter) simply has a cap of 0
    and starts the month at exactly its allocation.
    """
    today = today or date.today()
    quota = get_quota(provider)
    reset_date = quota.get("reset_date")
    if not reset_date:
        return
    try:
        due = date.fromisoformat(str(reset_date)[:10])
    except ValueError:
        return
    if today < due:
        return

    allocation = quota["allocation"]
    carried = min(quota["remaining"], allocation * quota["rollover_cap"])
    with _conn() as con:
        con.execute(
            """UPDATE provider_quota
               SET remaining = ?, consumed = 0, reset_date = ?
               WHERE provider = ?""",
            (allocation + carried, _next_month(today).isoformat(), provider),
        )
```

- [ ] **Step 5 : Lancer les tests pour vérifier qu'ils passent**

Run : `python -m pytest tests/test_quota_db.py -v`
Expected : PASS — 10 tests.

- [ ] **Step 6 : Brancher l'initialisation**

Dans `api/server.py`, après `leads_db.init_leads_table()` :

```python
from api import quota_db
quota_db.init_quota_tables()
```

- [ ] **Step 7 : Commit**

```bash
git add api/quota_db.py tests/test_quota_db.py config.py .env.example api/server.py
git commit -m "feat: table provider_quota, décrément sur résultat facturé uniquement"
```

---

### Task 5 : Cache de recherche d'email

**Files:**
- Modify: `api/quota_db.py`, `tests/test_quota_db.py`

**Interfaces:**
- Consomme : `_conn()` de Task 4.
- Produit :
  - `normalize_name(value: str) -> str`
  - `cache_lookup(first: str, last: str, domain: str, provider: str) -> dict | None` — renvoie `{"result": <payload ou None>}` sur un hit, `None` sur un miss
  - `cache_store(first, last, domain, provider, result: dict | None) -> None`
  - `CACHE_TTL_DAYS = 90`
  `enrichers/email_cascade.py` (Task 17) consulte le cache **avant** tout appel réseau.

**Contexte.** Décision 6 : expiration à 90 jours, alignée sur la fenêtre de déduplication gratuite de Prospeo. Un résultat négatif est mis en cache comme un positif — c'est justement celui qu'on ne veut pas repayer.

- [ ] **Step 1 : Écrire les tests qui échouent**

Ajouter à `tests/test_quota_db.py` :

```python
from datetime import datetime, timedelta, timezone


def test_a_found_email_is_cached_and_read_back():
    quota_db.cache_store("Karim", "El Amrani", "acme.ma", "prospeo",
                         {"email": "k.elamrani@acme.ma", "status": "valid"})
    hit = quota_db.cache_lookup("Karim", "El Amrani", "acme.ma", "prospeo")
    assert hit["result"]["email"] == "k.elamrani@acme.ma"


def test_a_miss_is_cached_too():
    """A lookup that found nothing cost a call. Repeating it costs another."""
    quota_db.cache_store("Karim", "El Amrani", "acme.ma", "hunter", None)
    hit = quota_db.cache_lookup("Karim", "El Amrani", "acme.ma", "hunter")
    assert hit is not None
    assert hit["result"] is None


def test_names_are_normalized_before_matching():
    quota_db.cache_store("Karim", "El Amrani", "acme.ma", "prospeo",
                         {"email": "k@acme.ma"})
    assert quota_db.cache_lookup("  KARIM ", "el amrani", "ACME.MA", "prospeo") is not None


def test_accents_are_folded():
    quota_db.cache_store("Aïcha", "Benîtez", "acme.ma", "prospeo", {"email": "a@acme.ma"})
    assert quota_db.cache_lookup("Aicha", "Benitez", "acme.ma", "prospeo") is not None


def test_cache_is_scoped_per_provider():
    """Prospeo finding nothing says nothing about what Hunter would find."""
    quota_db.cache_store("Karim", "El Amrani", "acme.ma", "prospeo", None)
    assert quota_db.cache_lookup("Karim", "El Amrani", "acme.ma", "hunter") is None


def test_an_entry_older_than_ninety_days_is_a_miss():
    """Prospeo re-bills after 90 days, so our cache must re-ask at 90 days too."""
    quota_db.cache_store("Karim", "El Amrani", "acme.ma", "prospeo", {"email": "k@acme.ma"})
    stale = (datetime.now(timezone.utc) - timedelta(days=91)).isoformat()
    with quota_db._conn() as con:
        con.execute("UPDATE email_lookup_cache SET looked_up_at = ?", (stale,))
    assert quota_db.cache_lookup("Karim", "El Amrani", "acme.ma", "prospeo") is None


def test_an_entry_at_eighty_nine_days_is_still_a_hit():
    quota_db.cache_store("Karim", "El Amrani", "acme.ma", "prospeo", {"email": "k@acme.ma"})
    fresh = (datetime.now(timezone.utc) - timedelta(days=89)).isoformat()
    with quota_db._conn() as con:
        con.execute("UPDATE email_lookup_cache SET looked_up_at = ?", (fresh,))
    assert quota_db.cache_lookup("Karim", "El Amrani", "acme.ma", "prospeo") is not None


def test_storing_twice_replaces_rather_than_duplicates():
    quota_db.cache_store("Karim", "El Amrani", "acme.ma", "prospeo", None)
    quota_db.cache_store("Karim", "El Amrani", "acme.ma", "prospeo", {"email": "k@acme.ma"})
    hit = quota_db.cache_lookup("Karim", "El Amrani", "acme.ma", "prospeo")
    assert hit["result"]["email"] == "k@acme.ma"
```

- [ ] **Step 2 : Lancer les tests pour vérifier qu'ils échouent**

Run : `python -m pytest tests/test_quota_db.py -v -k cache`
Expected : FAIL — `AttributeError: module 'api.quota_db' has no attribute 'cache_store'`.

- [ ] **Step 3 : Implémenter**

Ajouter à `api/quota_db.py` :

```python
import json
import re
import unicodedata
from datetime import datetime, timedelta, timezone

# Aligned on Prospeo's 90-day free re-enrichment window: past it the provider
# bills again, so a cache entry that outlived the window would keep us from
# re-asking a question that is now worth asking.
CACHE_TTL_DAYS = 90

_CREATE_EMAIL_CACHE = """
CREATE TABLE IF NOT EXISTS email_lookup_cache (
    first_name   TEXT NOT NULL,
    last_name    TEXT NOT NULL,
    domain       TEXT NOT NULL,
    provider     TEXT NOT NULL,
    result       TEXT,
    looked_up_at TEXT NOT NULL,
    PRIMARY KEY (first_name, last_name, domain, provider)
)
"""

_NON_WORD_RE = re.compile(r"[^a-z0-9]+")


def normalize_name(value: str) -> str:
    """Lowercase, strip accents and punctuation. Shared by cache keys so that
    "Aïcha" and "Aicha" never pay for the same lookup twice."""
    if not value:
        return ""
    decomposed = unicodedata.normalize("NFKD", str(value))
    deaccented = "".join(c for c in decomposed if not unicodedata.combining(c))
    return _NON_WORD_RE.sub(" ", deaccented.lower()).strip()


def normalize_domain(value: str) -> str:
    """Fold a domain to a stable cache key.

    Deliberately NOT normalize_name. That function collapses every run of
    non-alphanumeric characters to a single space, so "groupe-atlas.ma" and
    "groupe.atlas.ma" — a hyphenated domain and a subdomain of an unrelated
    company — would share one key. The cache would then hand one company's
    address back for the other's lookup, and a wrong contact in the export is
    worse than a wasted credit: the operator cannot tell it is wrong.
    """
    return (value or "").strip().lower().removeprefix("www.")


def cache_lookup(first: str, last: str, domain: str, provider: str) -> Optional[dict]:
    """Return {"result": <payload or None>} on a fresh hit, None on a miss.

    The two-level shape matters: a cached miss is a hit on the cache (we asked,
    the provider said no) and must not trigger another paid call, while None
    means we never asked.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=CACHE_TTL_DAYS)).isoformat()
    with _conn() as con:
        row = con.execute(
            """SELECT result FROM email_lookup_cache
               WHERE first_name = ? AND last_name = ? AND domain = ?
                 AND provider = ? AND looked_up_at >= ?""",
            (normalize_name(first), normalize_name(last),
             normalize_domain(domain), provider, cutoff),
        ).fetchone()
    if row is None:
        return None
    return {"result": json.loads(row["result"]) if row["result"] else None}


def cache_store(first: str, last: str, domain: str, provider: str,
                result: Optional[dict]) -> None:
    with _conn() as con:
        con.execute(
            """INSERT INTO email_lookup_cache
               (first_name, last_name, domain, provider, result, looked_up_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(first_name, last_name, domain, provider) DO UPDATE SET
                 result = excluded.result, looked_up_at = excluded.looked_up_at""",
            (normalize_name(first), normalize_name(last), normalize_domain(domain),
             provider, json.dumps(result, ensure_ascii=False) if result is not None else None,
             datetime.now(timezone.utc).isoformat()),
        )
```

Ajouter `con.execute(_CREATE_EMAIL_CACHE)` dans `init_quota_tables()`.

- [ ] **Step 4 : Lancer les tests pour vérifier qu'ils passent**

Run : `python -m pytest tests/test_quota_db.py -v`
Expected : PASS — 18 tests.

- [ ] **Step 5 : Commit**

```bash
git add api/quota_db.py tests/test_quota_db.py
git commit -m "feat: cache de recherche d'email expirant à 90 jours"
```

---

### Task 6 : Synchronisation des quotas — modes *pull* et *piggyback*

**Files:**
- Create: `enrichers/providers/__init__.py`, `enrichers/providers/quota_sync.py`, `tests/test_quota_sync.py`

**Interfaces:**
- Consomme : `api.quota_db.sync_remaining`, `api.quota_db.apply_monthly_reset`, `config.PROSPEO_API_KEY`, `config.HUNTER_API_KEY`.
- Produit :
  - `sync_all(registry=None) -> dict[str, str]` — appelé une fois au démarrage de chaque run, renvoie `{provider: "synced" | "skipped" | "unreachable"}`
  - `absorb_getprospect_metadata(metadata: dict) -> None` — mode *piggyback*, appelé par le client GetProspect après chaque réponse réussie
  `api/pipeline_runner.py` (Task 22) appelle `sync_all()` avant la cascade.

**Contexte.** Les trois fournisseurs n'exposent pas leur solde de la même façon. Prospeo et Hunter ont un endpoint compte **gratuit** (*pull*). GetProspect n'en a aucun : le solde arrive dans `metadata.credits` de chaque réponse réussie (*piggyback*). Un mode unique ne peut pas couvrir les deux.

- [ ] **Step 1 : Écrire les tests qui échouent**

Créer `tests/test_quota_sync.py` :

```python
import pytest

from api import quota_db
from enrichers.providers import quota_sync


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(quota_db, "_DB_PATH", str(tmp_path / "quota.db"))
    quota_db.init_quota_tables()


def test_prospeo_pull_reads_the_nested_response_key():
    """Prospeo nests account data under "response", unlike /enrich-person
    which is flat. Reading the root would silently sync nothing."""
    payload = {
        "error": False,
        "response": {
            "current_plan": "FREE",
            "remaining_credits": 87,
            "used_credits": 13,
            "next_quota_renewal_days": 25,
            "next_quota_renewal_date": "2026-10-18 20:52:28+00:00",
        },
    }
    quota_sync._absorb_prospeo(payload)
    quota = quota_db.get_quota("prospeo")
    assert quota["remaining"] == 87.0
    assert quota["reset_date"] == "2026-10-18"


def test_prospeo_error_payload_is_ignored(monkeypatch):
    """An error payload writes nothing, so the seeded allowance stands.

    The allowance is pinned here rather than read from config: this test
    asserts that nothing changed, and "nothing" is only legible against a
    known starting value. Left to the shipped default it would break on any
    machine whose .env raises PROSPEO_MONTHLY_ALLOCATION.
    """
    monkeypatch.setitem(config.PROVIDER_ALLOCATIONS, "prospeo", 100.0)
    # sync_remaining, not init_quota_tables: the latter's ON CONFLICT updates
    # allocation and rollover_cap only, never remaining — by design, since a
    # restart must not hand out credits. The fixture already seeded the row
    # with whatever the ambient .env held, so planting `remaining` explicitly
    # is the only way to give this test a known starting value.
    quota_db.sync_remaining("prospeo", 100.0, None)
    quota_sync._absorb_prospeo({"error": True, "error_code": "INVALID_API_KEY"})
    assert quota_db.get_quota("prospeo")["remaining"] == 100.0


def test_hunter_pull_prefers_the_unified_credits_bucket():
    """requests.credits is present only on a unified bucket; when it is there
    it is the authoritative balance, not searches/verifications."""
    payload = {
        "data": {
            "plan_name": "Free",
            "reset_date": "2026-10-03",
            "requests": {
                "credits": {"used": 12.5, "available": 50.0, "remaining": 37.5},
                "searches": {"used": 10, "available": 50, "remaining": 40},
                "verifications": {"used": 5, "available": 50, "remaining": 45},
            },
        }
    }
    quota_sync._absorb_hunter(payload)
    assert quota_db.get_quota("hunter")["remaining"] == 37.5


def test_hunter_falls_back_to_searches_when_credits_is_absent():
    """Data Platform plans expose separate buckets and no unified one."""
    payload = {
        "data": {
            "reset_date": "2026-10-03",
            "requests": {
                "searches": {"used": 10, "available": 50, "remaining": 40},
                "verifications": {"used": 5, "available": 100, "remaining": 95},
            },
        }
    }
    quota_sync._absorb_hunter(payload)
    assert quota_db.get_quota("hunter")["remaining"] == 40.0


def test_hunter_fractional_credits_survive():
    payload = {"data": {"reset_date": "2026-10-03",
                        "requests": {"credits": {"used": 0.5, "available": 50.0,
                                                 "remaining": 49.5}}}}
    quota_sync._absorb_hunter(payload)
    assert quota_db.get_quota("hunter")["remaining"] == 49.5


def test_getprospect_piggyback_updates_both_counters():
    """GetProspect has no account endpoint: the balance rides along in
    metadata.credits on every successful response."""
    metadata = {
        "timestamp": "2026-09-25T14:07:55.000Z",
        "credits": {"email_search": 42, "email_verification": 98,
                    "reset_at": "2026-10-01T00:00:00.000Z"},
    }
    quota_sync.absorb_getprospect_metadata(metadata)
    assert quota_db.get_quota("getprospect")["remaining"] == 42.0
    assert quota_db.get_quota("getprospect_verify")["remaining"] == 98.0
    assert quota_db.get_quota("getprospect")["reset_date"] == "2026-10-01"


def test_getprospect_metadata_without_credits_is_a_no_op(monkeypatch):
    """Same reasoning as test_prospeo_error_payload_is_ignored: the allowance
    is pinned so that "unchanged" has a fixed reference."""
    monkeypatch.setitem(config.PROVIDER_ALLOCATIONS, "getprospect", 50.0)
    quota_db.sync_remaining("getprospect", 50.0, None)
    quota_sync.absorb_getprospect_metadata({"timestamp": "2026-09-25T14:07:55.000Z"})
    assert quota_db.get_quota("getprospect")["remaining"] == 50.0


def test_absorbing_a_malformed_payload_never_raises():
    """A provider that changes its response shape must degrade the sync, not
    kill the run before a single lead is processed."""
    for payload in (None, [], "oops", {"data": None}, {"response": 42}):
        quota_sync._absorb_prospeo(payload)
        quota_sync._absorb_hunter(payload)
        quota_sync.absorb_getprospect_metadata(payload)


def test_sync_all_skips_providers_without_a_key(monkeypatch):
    monkeypatch.setattr("config.PROSPEO_API_KEY", "your_prospeo_api_key_here")
    monkeypatch.setattr("config.HUNTER_API_KEY", "")
    assert quota_sync.sync_all() == {"prospeo": "skipped", "hunter": "skipped"}
```

- [ ] **Step 2 : Lancer les tests pour vérifier qu'ils échouent**

Run : `python -m pytest tests/test_quota_sync.py -v`
Expected : FAIL — `ModuleNotFoundError: No module named 'enrichers.providers'`.

- [ ] **Step 3 : Implémenter**

Créer `enrichers/providers/__init__.py` vide, puis `enrichers/providers/quota_sync.py` :

```python
"""
Quota synchronisation across three providers that expose their balance three
different ways.

Prospeo and Hunter each have a free account endpoint we can poll (pull mode).
GetProspect has none: its balance rides along in metadata.credits on every
successful response (piggyback mode). A single mode cannot cover both, and
guessing a balance we cannot read is exactly how a run spends credits it does
not have.
"""
import logging
from typing import Optional

import requests

import config
from api import quota_db
from api.provider_status import StepOutcome

logger = logging.getLogger(__name__)

PROSPEO_ACCOUNT_URL = "https://api.prospeo.io/account-information"
HUNTER_ACCOUNT_URL = "https://api.hunter.io/v2/account"


def _as_float(value) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _absorb_prospeo(payload) -> bool:
    """Read Prospeo's balance. Data sits under "response", not at the root."""
    if not isinstance(payload, dict) or payload.get("error"):
        return False
    response = payload.get("response")
    if not isinstance(response, dict):
        return False
    remaining = _as_float(response.get("remaining_credits"))
    if remaining is None:
        return False
    # "2023-06-18 20:52:28+00:00" — space separator, not ISO T.
    raw_date = response.get("next_quota_renewal_date")
    reset_date = str(raw_date)[:10] if raw_date else None
    quota_db.sync_remaining("prospeo", remaining, reset_date)
    return True


def _absorb_hunter(payload) -> bool:
    """Read Hunter's balance.

    requests.credits is present only on a unified bucket (the free plan's
    case); otherwise searches and verifications are tracked separately and
    the search bucket is the binding one for the cascade.
    """
    if not isinstance(payload, dict):
        return False
    data = payload.get("data")
    if not isinstance(data, dict):
        return False
    requests_block = data.get("requests")
    if not isinstance(requests_block, dict):
        return False

    bucket = requests_block.get("credits") or requests_block.get("searches")
    if not isinstance(bucket, dict):
        return False
    remaining = _as_float(bucket.get("remaining"))
    if remaining is None:
        return False
    reset_date = data.get("reset_date")
    quota_db.sync_remaining("hunter", remaining, str(reset_date)[:10] if reset_date else None)
    return True


def absorb_getprospect_metadata(metadata) -> bool:
    """Piggyback mode — called after every successful GetProspect response."""
    if not isinstance(metadata, dict):
        return False
    credits = metadata.get("credits")
    if not isinstance(credits, dict):
        return False
    raw_reset = credits.get("reset_at")
    reset_date = str(raw_reset)[:10] if raw_reset else None

    absorbed = False
    search = _as_float(credits.get("email_search"))
    if search is not None:
        quota_db.sync_remaining("getprospect", search, reset_date)
        absorbed = True
    verify = _as_float(credits.get("email_verification"))
    if verify is not None:
        quota_db.sync_remaining("getprospect_verify", verify, reset_date)
        absorbed = True
    return absorbed


def _pull(provider: str, url: str, headers: dict, params: dict, absorber) -> str:
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=10)
        resp.raise_for_status()
        payload = resp.json()
    except Exception as exc:
        logger.warning(f"Quota sync unreachable for {provider}: {exc}")
        return "unreachable"

    if absorber(payload):
        return "synced"
    # Reachable but unreadable: the provider answered 200 with a body whose
    # shape we do not recognise. That is not an outage — it is the provider
    # having changed its API, which is the single scenario this module exists
    # to survive. Logging it distinctly is what lets an operator tell the two
    # apart, since both end up as the same "unreachable" status.
    logger.warning(
        f"Quota sync for {provider}: response did not match the expected "
        f"shape; keeping the local counter."
    )
    return "unreachable"


def sync_all(registry=None) -> dict[str, str]:
    """Refresh every pullable balance, then apply any due monthly reset.

    Both account endpoints are documented as free, so this costs nothing and
    runs unconditionally at the start of a run. A provider we cannot reach
    keeps its local counter rather than blocking the run.
    """
    outcomes: dict[str, str] = {}

    if config._is_placeholder(config.PROSPEO_API_KEY):
        outcomes["prospeo"] = "skipped"
    else:
        outcomes["prospeo"] = _pull(
            "prospeo", PROSPEO_ACCOUNT_URL,
            {"X-KEY": config.PROSPEO_API_KEY}, {}, _absorb_prospeo,
        )

    if config._is_placeholder(config.HUNTER_API_KEY):
        outcomes["hunter"] = "skipped"
    else:
        outcomes["hunter"] = _pull(
            "hunter", HUNTER_ACCOUNT_URL, {},
            {"api_key": config.HUNTER_API_KEY}, _absorb_hunter,
        )

    for provider in config.PROVIDER_ALLOCATIONS:
        quota_db.apply_monthly_reset(provider)

    if registry is not None:
        for provider, state in outcomes.items():
            if state == "unreachable":
                registry.record(StepOutcome(
                    provider, "degraded",
                    "solde non synchronisé — compteur local utilisé", 0,
                ))
    return outcomes
```

- [ ] **Step 4 : Lancer les tests pour vérifier qu'ils passent**

Run : `python -m pytest tests/test_quota_sync.py -v`
Expected : PASS — 9 tests.

- [ ] **Step 5 : Commit**

```bash
git add enrichers/providers/__init__.py enrichers/providers/quota_sync.py tests/test_quota_sync.py
git commit -m "feat: synchronisation des quotas en modes pull et piggyback"
```

---

### Task 7 : Réutiliser le fetch de cohérence au lieu de retélécharger

**Files:**
- Modify: `enrichers/google_search.py:206-238`, `scrapers/website_scraper.py`
- Test: `tests/test_google_search.py`, `tests/test_website_scraper.py`

**Interfaces:**
- Consomme : `processors.coherence.check_site_coherence` (inchangé).
- Produit : `verify_website(url, company) -> tuple[CoherenceResult, PageFetch]` où `PageFetch` est un dataclass `{url, html, text, title, unreachable}`. `find_linkedin_and_website()` stocke le résultat dans `lead["_page_fetch"]`. `enrichers/contact_extractor.py` (Task 8) et `scrapers/website_scraper.py` le consomment sans refaire de requête.

**Contexte.** §3 du spec : « L'étape 3a′ télécharge déjà la page d'accueil pour la cohérence : réutiliser ce fetch au lieu de refaire une requête. » Aujourd'hui, `verify_website()` télécharge la page puis jette le HTML, et `scrapers/website_scraper.py` la retélécharge à l'étape 5. Deux requêtes pour la même page.

- [ ] **Step 1 : Écrire le test qui échoue**

Ajouter à `tests/test_google_search.py` :

```python
from enrichers.google_search import PageFetch, verify_website


def test_verify_website_returns_the_fetched_page(monkeypatch):
    html = "<html><head><title>Acme Maroc</title></head><body>" + "Acme Maroc " * 40 + "</body></html>"

    class _Resp:
        text = html
        def raise_for_status(self): pass

    monkeypatch.setattr("enrichers.google_search.requests.get", lambda *a, **k: _Resp())
    result, page = verify_website("https://acme.ma", "Acme Maroc")

    assert result.coherent is True
    assert isinstance(page, PageFetch)
    assert page.html == html
    assert page.title == "Acme Maroc"
    assert page.unreachable is False
    assert "Acme Maroc" in page.text


def test_an_unreachable_site_yields_an_empty_marked_fetch(monkeypatch):
    def _boom(*a, **k):
        raise requests.exceptions.ConnectionError("dns")

    monkeypatch.setattr("enrichers.google_search.requests.get", _boom)
    result, page = verify_website("https://nope.invalid", "Acme")

    assert result.coherent is True and result.verified is False
    assert page.unreachable is True
    assert page.html == ""


def test_no_url_is_neither_reachable_nor_unreachable():
    result, page = verify_website("", "Acme")
    assert page.unreachable is False
    assert page.html == ""
```

- [ ] **Step 2 : Lancer le test pour vérifier qu'il échoue**

Run : `python -m pytest tests/test_google_search.py -v -k verify_website`
Expected : FAIL — `ImportError: cannot import name 'PageFetch'`.

- [ ] **Step 3 : Implémenter**

Dans `enrichers/google_search.py`, ajouter au-dessus de `verify_website` :

```python
@dataclass(frozen=True)
class PageFetch:
    """One homepage fetch, kept for every downstream consumer.

    The coherence check (step 3a') already downloads this page. Contact
    extraction (step 3d) and evidence collection (step 5) used to download it
    again — three requests per lead for one document, three chances to be rate
    limited or to read a different version of the page than the one we scored.
    """
    url: str = ""
    html: str = ""
    text: str = ""
    title: str = ""
    unreachable: bool = False
```

Puis réécrire `verify_website` pour retourner le couple :

```python
def verify_website(url: str, company: str) -> tuple[CoherenceResult, PageFetch]:
    if not url:
        return (CoherenceResult(coherent=True, verified=False, reason="aucun site à vérifier"),
                PageFetch())
    try:
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"},
                            timeout=8, allow_redirects=True)
        resp.raise_for_status()
        html = resp.text
        title, text = _light_page_text(html)
    except Exception as e:
        logger.debug(f"Light website check failed for {url}: {e}")
        return (CoherenceResult(coherent=True, verified=False, reason="site injoignable"),
                PageFetch(url=url, unreachable=True))

    return (check_site_coherence(company, title, text),
            PageFetch(url=url, html=html, text=text, title=title, unreachable=False))
```

Dans `find_linkedin_and_website()`, adapter l'appel et stocker le fetch :

```python
        if candidate:
            check, page = verify_website(candidate, company)
            lead["_page_fetch"] = page
            lead["website_unreachable"] = page.unreachable
            lead["website_coherent"] = check.coherent
            lead["website_check_reason"] = check.reason
```

- [ ] **Step 4 : Faire consommer le cache par `website_scraper`**

Dans `scrapers/website_scraper.py`, en tête de `scrape_hit_leads`, court-circuiter le refetch :

```python
        cached = lead.get("_page_fetch")
        # lead["website"] is the acceptance gate, and it is load-bearing.
        # find_linkedin_and_website stores _page_fetch before the coherence
        # verdict, so a site that answered but was rejected as belonging to a
        # different company still has its HTML sitting in the cache. Before
        # this refactor the gate was implicit: rejection nulled lead["website"]
        # and _scrape_website(None) returned "". Reusing the cache without it
        # feeds another company's page to the fact extractor — reopening
        # exactly the association the 2026-08-10 coherence check was built to
        # prevent, and silently, since evidence_level stays correct while the
        # facts underneath it are wrong.
        if cached is not None and lead.get("website") and (cached.html or cached.unreachable):
            # Reuse the page fetched during the coherence check rather than
            # asking the site for the same document a second time — but
            # re-derive the text from its HTML with this module's own rules.
            # google_search's _light_page_text leaves <noscript> blocks and
            # HTML comments in place; reusing cached.text directly would feed
            # the fact extractor different text depending on which path ran.
            lead["website_text"] = _html_to_text(cached.html)[:MAX_WEBSITE_TEXT]
            lead["website_unreachable"] = cached.unreachable
            lead["linkedin_text"] = ""
            continue
```

- [ ] **Step 5 : Lancer les tests**

Run : `python -m pytest tests/test_google_search.py tests/test_website_scraper.py -v`
Expected : PASS. Adapter les tests existants de `test_google_search.py` qui appellent `verify_website()` et attendaient un `CoherenceResult` seul.

- [ ] **Step 6 : Commit**

```bash
git add enrichers/google_search.py scrapers/website_scraper.py tests/test_google_search.py tests/test_website_scraper.py
git commit -m "perf: un seul téléchargement de la page d'accueil par lead"
```

---

### Task 8 : Extraction des emails depuis le site

**Files:**
- Create: `enrichers/contact_extractor.py`, `tests/test_contact_extractor.py`

**Interfaces:**
- Consomme : `enrichers.google_search.PageFetch`.
- Produit :
  - `EXTRACTION_SLUGS: tuple[str, ...]`
  - `extract_emails(html: str, source_url: str) -> list[ExtractedEmail]`
  - `classify_email(email: str, first_name: str, last_name: str, domain: str) -> str` → `"nominatif_lead" | "nominatif_autre" | "generique" | "webmail"`
  - `decode_cloudflare(html: str) -> str`
  - dataclass `ExtractedEmail{value, kind, source_url}`
  `enrichers/email_cascade.py` (Task 17) consomme la liste ; `enrichers/email_patterns.py` (Task 11) déduit le format d'entreprise d'un `nominatif_autre`.

- [ ] **Step 1 : Écrire les tests qui échouent**

Créer `tests/test_contact_extractor.py` :

```python
import pytest

from enrichers.contact_extractor import (
    classify_email,
    decode_cloudflare,
    extract_emails,
)


def _values(html, url="https://acme.ma/contact"):
    return {e.value for e in extract_emails(html, url)}


def test_plain_text_email_is_found():
    assert "karim@acme.ma" in _values("<p>Contact : karim@acme.ma</p>")


def test_mailto_is_found():
    assert "karim@acme.ma" in _values('<a href="mailto:karim@acme.ma?subject=Hi">Écrire</a>')


@pytest.mark.parametrize("masked,expected", [
    ("karim[at]acme.ma", "karim@acme.ma"),
    ("karim(at)acme.ma", "karim@acme.ma"),
    ("karim at acme.ma", "karim@acme.ma"),
    ("karim [AT] acme [DOT] ma", "karim@acme.ma"),
    ("karim(at)acme(dot)ma", "karim@acme.ma"),
])
def test_masked_forms_are_recovered(masked, expected):
    assert expected in _values(f"<p>{masked}</p>")


def test_cloudflare_protected_email_is_decoded():
    """Cloudflare replaces the address with a hex blob XOR'd against its first
    byte. Without decoding, a protected contact page yields nothing at all."""
    # "karim@acme.ma" encoded with key 0x7a
    encoded = "7a110f13176f5a1917190f341917"
    html = f'<a href="/cdn-cgi/l/email-protection#{encoded}" class="__cf_email__" data-cfemail="{encoded}">[email&#160;protected]</a>'
    decoded = decode_cloudflare(html)
    assert "karim@acme.ma" in decoded


def test_image_filenames_are_not_emails():
    """logo@2x.png is a retina asset, not a contact."""
    assert _values('<img src="logo@2x.png"><img src="hero@3x.jpg">') == set()


@pytest.mark.parametrize("address", [
    "noreply@acme.ma", "no-reply@acme.ma", "donotreply@acme.ma",
    "webmaster@acme.ma", "postmaster@acme.ma", "abuse@acme.ma",
])
def test_technical_addresses_are_rejected(address):
    assert _values(f"<p>{address}</p>") == set()


def test_the_web_agency_address_is_rejected():
    """Agencies sign their work in the footer. Their address is not the
    prospect's, and mailing it wastes a contact attempt."""
    html = '<footer>Site réalisé par Studio Digital — contact@studiodigital.ma</footer><p>info@acme.ma</p>'
    values = {e.value for e in extract_emails(html, "https://acme.ma/", company_domain="acme.ma")}
    assert values == {"info@acme.ma"}


def test_source_url_is_recorded():
    extracted = extract_emails("<p>karim@acme.ma</p>", "https://acme.ma/contact")
    assert extracted[0].source_url == "https://acme.ma/contact"


def test_duplicates_are_collapsed_case_insensitively():
    html = "<p>Karim@Acme.ma</p><p>karim@acme.ma</p>"
    assert len(extract_emails(html, "https://acme.ma/")) == 1


# ── Classement ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("address", [
    "karim.elamrani@acme.ma", "k.elamrani@acme.ma", "karim@acme.ma",
    "kelamrani@acme.ma", "elamrani.karim@acme.ma",
])
def test_the_lead_own_address_is_nominatif_lead(address):
    assert classify_email(address, "Karim", "El Amrani", "acme.ma") == "nominatif_lead"


def test_another_person_address_is_nominatif_autre():
    assert classify_email("sara.bennani@acme.ma", "Karim", "El Amrani", "acme.ma") == "nominatif_autre"


@pytest.mark.parametrize("address", [
    "contact@acme.ma", "info@acme.ma", "commercial@acme.ma",
    "hello@acme.ma", "bonjour@acme.ma", "sales@acme.ma", "rh@acme.ma",
])
def test_role_addresses_are_generique(address):
    assert classify_email(address, "Karim", "El Amrani", "acme.ma") == "generique"


@pytest.mark.parametrize("address", [
    "karim.elamrani@gmail.com", "karim@hotmail.fr",
    "karim@yahoo.fr", "karim@outlook.com",
])
def test_free_providers_are_webmail(address):
    assert classify_email(address, "Karim", "El Amrani", "acme.ma") == "webmail"


def test_webmail_wins_over_nominatif():
    """A personal Gmail is a webmail first: it is not the company mailbox and
    must not be treated as a corporate nominative address."""
    assert classify_email("karim.elamrani@gmail.com", "Karim", "El Amrani", "acme.ma") == "webmail"


def test_accented_lead_name_still_matches():
    assert classify_email("aicha.benitez@acme.ma", "Aïcha", "Benîtez", "acme.ma") == "nominatif_lead"
```

- [ ] **Step 2 : Lancer les tests pour vérifier qu'ils échouent**

Run : `python -m pytest tests/test_contact_extractor.py -v`
Expected : FAIL — `ModuleNotFoundError: No module named 'enrichers.contact_extractor'`.

- [ ] **Step 3 : Implémenter l'extraction**

Créer `enrichers/contact_extractor.py` :

```python
"""
Step 3d — Contact extraction from the prospect's own website.

Every address found here is free and already verified by the fact that the
company published it. The cascade tries this before spending a single credit,
so the quality of this module decides how much of a 50-credit month survives.
"""
import logging
import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

from api.quota_db import normalize_name

logger = logging.getLogger(__name__)

# Slugs of pages worth following, in FR, EN and transliterated AR.
EXTRACTION_SLUGS: tuple[str, ...] = (
    "contact", "contactez", "contactez-nous", "contact-us", "nous-contacter",
    "a-propos", "apropos", "about", "about-us", "qui-sommes-nous",
    "equipe", "team", "notre-equipe", "our-team",
    "mentions-legales", "legal", "impressum",
    "carriere", "carrieres", "careers", "jobs", "recrutement",
    "ittasal", "ittasal-bina", "man-nahnu", "fariq",
)

MAX_PAGES = 5
PAGE_TIMEOUT = 8

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_MAILTO_RE = re.compile(r'mailto:([^"\'?>\s]+)', re.IGNORECASE)
_CF_RE = re.compile(r'data-cfemail="([0-9a-fA-F]+)"')

# Image assets whose "@2x" suffix parses as an email local part.
_IMAGE_EXT = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico", ".bmp")

_TECHNICAL_LOCALS = frozenset({
    "noreply", "no-reply", "donotreply", "do-not-reply", "nepasrepondre",
    "webmaster", "postmaster", "hostmaster", "abuse", "mailer-daemon",
    "bounce", "bounces", "notification", "notifications", "automated",
})

_GENERIC_LOCALS = frozenset({
    "contact", "contacts", "info", "infos", "information", "hello", "bonjour",
    "commercial", "sales", "vente", "ventes", "support", "service", "sav",
    "admin", "administration", "direction", "secretariat", "accueil",
    "rh", "hr", "recrutement", "jobs", "emploi", "compta", "comptabilite",
    "facturation", "billing", "devis", "marketing", "presse", "press",
})

_WEBMAIL_DOMAINS = frozenset({
    "gmail.com", "googlemail.com", "hotmail.com", "hotmail.fr", "outlook.com",
    "outlook.fr", "live.com", "live.fr", "msn.com", "yahoo.com", "yahoo.fr",
    "ymail.com", "aol.com", "icloud.com", "me.com", "protonmail.com",
    "proton.me", "gmx.com", "gmx.fr", "orange.fr", "wanadoo.fr", "free.fr",
    "sfr.fr", "laposte.net", "menara.ma", "iam.net.ma",
})


@dataclass(frozen=True)
class ExtractedEmail:
    value: str
    kind: str          # nominatif_lead | nominatif_autre | generique | webmail
    source_url: str


def decode_cloudflare(html: str) -> str:
    """Replace Cloudflare-obfuscated addresses with their plaintext form.

    Cloudflare hex-encodes the address XOR'd against its own first byte. A
    contact page behind this protection contains no readable address at all,
    so skipping the decode silently turns a perfectly good free lookup into a
    paid one.
    """
    def _decode(match: re.Match) -> str:
        blob = match.group(1)
        try:
            key = int(blob[:2], 16)
            decoded = "".join(
                chr(int(blob[i:i + 2], 16) ^ key) for i in range(2, len(blob), 2)
            )
        except ValueError:
            return match.group(0)
        return f'data-cfemail="{blob}">{decoded}<'

    return _CF_RE.sub(_decode, html)


def _is_plausible(address: str) -> bool:
    lowered = address.lower()
    if lowered.endswith(_IMAGE_EXT):
        return False
    local, _, domain = lowered.partition("@")
    if not local or not domain or "." not in domain:
        return False
    if local in _TECHNICAL_LOCALS:
        return False
    # "logo@2x" and friends: a purely numeric local part is never a mailbox.
    if local.isdigit() or re.fullmatch(r"\d+x", local):
        return False
    return True


def _unmask(text: str) -> str:
    """Rewrite [at] / (at) / " at " and their dot equivalents into a real address."""
    unmasked = re.sub(r"\s*[\[\(]\s*at\s*[\]\)]\s*", "@", text, flags=re.IGNORECASE)
    unmasked = re.sub(r"\s+at\s+(?=[A-Za-z0-9.\-]+\.[A-Za-z]{2,})", "@", unmasked, flags=re.IGNORECASE)
    unmasked = re.sub(r"\s*[\[\(]\s*dot\s*[\]\)]\s*", ".", unmasked, flags=re.IGNORECASE)
    return re.sub(r"\s+dot\s+", ".", unmasked, flags=re.IGNORECASE)


def extract_emails(html: str, source_url: str,
                   company_domain: str = "") -> list[ExtractedEmail]:
    """Collect every plausible address on one page, deduplicated.

    `company_domain` filters out the web agency that built the site: agencies
    sign their work in the footer, and their address is a dead end that costs
    a contact attempt. When it is empty every domain is kept — the caller has
    not told us which one is the prospect's.
    """
    if not html:
        return []

    decoded = decode_cloudflare(html)
    haystack = _unmask(decoded)

    candidates: list[str] = _MAILTO_RE.findall(haystack)
    candidates += _EMAIL_RE.findall(haystack)

    wanted = normalize_name(company_domain).replace(" ", "")
    seen: set[str] = set()
    found: list[ExtractedEmail] = []
    for raw in candidates:
        address = raw.strip().strip(".,;:").lower()
        if address in seen or not _is_plausible(address):
            continue
        if wanted and address.partition("@")[2] != company_domain.lower():
            if address.partition("@")[2] not in _WEBMAIL_DOMAINS:
                continue
        seen.add(address)
        found.append(ExtractedEmail(value=address, kind="", source_url=source_url))
    return found


def classify_email(email: str, first_name: str, last_name: str, domain: str) -> str:
    """Sort one address into the four buckets the cascade branches on.

    Order matters: webmail is checked first because a personal Gmail belonging
    to the lead is still not the corporate mailbox, and treating it as a
    nominative company address would send mail to the wrong place.
    """
    local, _, mail_domain = (email or "").lower().partition("@")
    if mail_domain in _WEBMAIL_DOMAINS:
        return "webmail"
    if local in _GENERIC_LOCALS:
        return "generique"

    first = normalize_name(first_name).replace(" ", "")
    last = normalize_name(last_name).replace(" ", "")
    stripped = re.sub(r"[^a-z0-9]", "", local)
    if not first and not last:
        return "nominatif_autre"

    # A local part that contains the surname, or the initial plus the surname,
    # or both given and family name in either order, belongs to this lead.
    matches = (
        (first and last and first in stripped and last in stripped)
        or (last and stripped == last)
        or (first and stripped == first)
        or (last and first and stripped == f"{first[0]}{last}")
        or (last and first and stripped == f"{last}{first[0]}")
    )
    return "nominatif_lead" if matches else "nominatif_autre"
```

- [ ] **Step 4 : Lancer les tests pour vérifier qu'ils passent**

Run : `python -m pytest tests/test_contact_extractor.py -v`
Expected : PASS.

- [ ] **Step 5 : Commit**

```bash
git add enrichers/contact_extractor.py tests/test_contact_extractor.py
git commit -m "feat: extraction et classement des emails depuis le site du prospect"
```

---

### Task 9 : Crawl des pages contact, WhatsApp et réseaux sociaux

**Files:**
- Modify: `enrichers/contact_extractor.py`, `tests/test_contact_extractor.py`

**Interfaces:**
- Consomme : `extract_emails`, `classify_email`, `EXTRACTION_SLUGS` (Task 8), `PageFetch` (Task 7).
- Produit :
  - `internal_contact_links(html: str, base_url: str) -> list[str]` — au plus `MAX_PAGES`
  - `extract_social(html: str) -> dict` → `{whatsapp, facebook_url, instagram_url, linkedin_company_url}`
  - `harvest_contacts(lead: dict, page: PageFetch) -> dict` — point d'entrée unique, respecte `robots.txt`
  `enrichers/email_cascade.py` (Task 17) appelle `harvest_contacts`.

- [ ] **Step 1 : Écrire les tests qui échouent**

Ajouter à `tests/test_contact_extractor.py` :

```python
from enrichers.contact_extractor import (
    MAX_PAGES, extract_social, internal_contact_links,
)


def test_contact_pages_are_followed():
    html = """
      <a href="/contact">Contact</a>
      <a href="/a-propos">À propos</a>
      <a href="/notre-equipe">Équipe</a>
      <a href="/blog/article-42">Blog</a>
      <a href="/produits">Produits</a>
    """
    links = internal_contact_links(html, "https://acme.ma/")
    assert "https://acme.ma/contact" in links
    assert "https://acme.ma/a-propos" in links
    assert "https://acme.ma/notre-equipe" in links
    assert not any("blog" in l or "produits" in l for l in links)


def test_transliterated_arabic_slugs_are_followed():
    links = internal_contact_links('<a href="/ittasal-bina">اتصل بنا</a>', "https://acme.ma/")
    assert "https://acme.ma/ittasal-bina" in links


def test_external_links_are_never_followed():
    html = '<a href="https://autre-site.ma/contact">Contact</a>'
    assert internal_contact_links(html, "https://acme.ma/") == []


def test_at_most_five_pages_are_followed():
    html = "".join(f'<a href="/contact-{i}">c</a>' for i in range(30))
    assert len(internal_contact_links(html, "https://acme.ma/")) <= MAX_PAGES


def test_the_same_page_is_not_queued_twice():
    html = '<a href="/contact">A</a><a href="/contact">B</a><a href="/contact/">C</a>'
    assert len(internal_contact_links(html, "https://acme.ma/")) == 1


# ── WhatsApp et réseaux ───────────────────────────────────────────────────────

@pytest.mark.parametrize("href", [
    "https://wa.me/212600000000",
    "https://api.whatsapp.com/send?phone=212600000000",
    "https://web.whatsapp.com/send?phone=212600000000",
])
def test_whatsapp_link_published_by_the_company_is_detected(href):
    assert extract_social(f'<a href="{href}">WhatsApp</a>')["whatsapp"] is True


def test_no_whatsapp_link_means_false_not_a_probe():
    """We never test whether a number is registered on WhatsApp: that probes a
    third party's account. Only a link the company published itself counts."""
    assert extract_social("<p>+212 6 00 00 00 00</p>")["whatsapp"] is False


def test_social_profiles_are_extracted():
    html = """
      <a href="https://www.facebook.com/acme.maroc">FB</a>
      <a href="https://instagram.com/acme_maroc">IG</a>
      <a href="https://www.linkedin.com/company/acme-maroc">LI</a>
    """
    social = extract_social(html)
    assert social["facebook_url"] == "https://www.facebook.com/acme.maroc"
    assert social["instagram_url"] == "https://instagram.com/acme_maroc"
    assert social["linkedin_company_url"] == "https://www.linkedin.com/company/acme-maroc"


def test_a_personal_linkedin_profile_is_not_the_company_page():
    html = '<a href="https://www.linkedin.com/in/karim-elamrani">Karim</a>'
    assert extract_social(html)["linkedin_company_url"] is None


def test_share_widgets_are_not_company_profiles():
    """Share buttons point at facebook.com/sharer, not at a page we can use."""
    html = '<a href="https://www.facebook.com/sharer/sharer.php?u=https://acme.ma">Partager</a>'
    assert extract_social(html)["facebook_url"] is None
```

- [ ] **Step 2 : Lancer les tests pour vérifier qu'ils échouent**

Run : `python -m pytest tests/test_contact_extractor.py -v -k "links or social or whatsapp"`
Expected : FAIL — `ImportError: cannot import name 'internal_contact_links'`.

- [ ] **Step 3 : Implémenter**

Ajouter à `enrichers/contact_extractor.py` :

```python
import time
import urllib.robotparser
from urllib.parse import urlparse

import requests

import config

_HREF_RE = re.compile(r'href=["\']([^"\']+)["\']', re.IGNORECASE)
_WHATSAPP_RE = re.compile(r"https?://(?:wa\.me|api\.whatsapp\.com|web\.whatsapp\.com)/", re.I)
_FACEBOOK_RE = re.compile(r"https?://(?:www\.)?facebook\.com/(?!sharer|share\.php)[A-Za-z0-9._\-]+/?", re.I)
_INSTAGRAM_RE = re.compile(r"https?://(?:www\.)?instagram\.com/(?!p/|explore/)[A-Za-z0-9._\-]+/?", re.I)
_LINKEDIN_COMPANY_RE = re.compile(r"https?://(?:[a-z]{2,3}\.)?linkedin\.com/company/[A-Za-z0-9._\-]+/?", re.I)

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


def internal_contact_links(html: str, base_url: str) -> list[str]:
    """Same-host links whose path matches a contact-page slug, capped at MAX_PAGES."""
    if not html:
        return []
    base_host = urlparse(base_url).netloc.lower().removeprefix("www.")
    seen: set[str] = set()
    links: list[str] = []
    for href in _HREF_RE.findall(html):
        absolute = urljoin(base_url, href.strip())
        parsed = urlparse(absolute)
        if parsed.scheme not in ("http", "https"):
            continue
        if parsed.netloc.lower().removeprefix("www.") != base_host:
            continue
        path = parsed.path.rstrip("/").lower()
        slug = path.rsplit("/", 1)[-1]
        if not slug or not any(slug.startswith(s) for s in EXTRACTION_SLUGS):
            continue
        canonical = f"{parsed.scheme}://{parsed.netloc}{path}"
        if canonical in seen:
            continue
        seen.add(canonical)
        links.append(canonical)
        if len(links) >= MAX_PAGES:
            break
    return links


def _first(pattern: re.Pattern, html: str):
    match = pattern.search(html or "")
    return match.group(0).rstrip("/") if match else None


def extract_social(html: str) -> dict:
    """Social handles and, crucially, whether the company publishes a WhatsApp link.

    whatsapp is true only when the company put the link on its own site. We
    never probe whether a number is registered on WhatsApp: that queries a
    third party's account without their knowledge, for a signal the company
    would have advertised if it wanted to be reached that way.
    """
    return {
        "whatsapp": bool(_WHATSAPP_RE.search(html or "")),
        "facebook_url": _first(_FACEBOOK_RE, html),
        "instagram_url": _first(_INSTAGRAM_RE, html),
        "linkedin_company_url": _first(_LINKEDIN_COMPANY_RE, html),
    }


def _robots_allows(base_url: str, path: str) -> bool:
    """Honour robots.txt. A site that cannot be reached for its robots file is
    treated as permissive — the same default a browser applies."""
    parsed = urlparse(base_url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    try:
        parser = urllib.robotparser.RobotFileParser()
        parser.set_url(robots_url)
        parser.read()
        return parser.can_fetch(_UA, path)
    except Exception:
        return True


def harvest_contacts(lead: dict, page) -> dict:
    """Walk the homepage plus up to MAX_PAGES contact pages and collect everything.

    Returns emails already classified, social handles and the source URL of
    each find. Never raises: a site that blocks us costs the lead its free
    contact route, not the run.
    """
    website = lead.get("website") or ""
    if not website or page is None or not getattr(page, "html", ""):
        return {"emails": [], "social": extract_social(""), "pages_crawled": 0}

    domain = urlparse(website).netloc.lower().removeprefix("www.")
    first = (lead.get("first_name") or "")
    last = (lead.get("last_name") or "")

    collected: dict[str, ExtractedEmail] = {}
    social = extract_social(page.html)
    for found in extract_emails(page.html, page.url or website, company_domain=domain):
        collected[found.value] = found

    pages = 0
    for url in internal_contact_links(page.html, website):
        if not _robots_allows(website, urlparse(url).path):
            logger.debug(f"robots.txt disallows {url}")
            continue
        try:
            resp = requests.get(url, headers={"User-Agent": _UA},
                                timeout=PAGE_TIMEOUT, allow_redirects=True)
            resp.raise_for_status()
        except Exception as exc:
            logger.debug(f"Contact page unreachable {url}: {exc}")
            continue
        pages += 1
        for found in extract_emails(resp.text, url, company_domain=domain):
            collected.setdefault(found.value, found)
        for key, value in extract_social(resp.text).items():
            if key == "whatsapp":
                social[key] = social[key] or value
            elif not social.get(key):
                social[key] = value
        time.sleep(config.REQUEST_DELAY / 2)

    classified = [
        ExtractedEmail(value=e.value,
                       kind=classify_email(e.value, first, last, domain),
                       source_url=e.source_url)
        for e in collected.values()
    ]
    return {"emails": classified, "social": social, "pages_crawled": pages}
```

- [ ] **Step 4 : Lancer les tests pour vérifier qu'ils passent**

Run : `python -m pytest tests/test_contact_extractor.py -v`
Expected : PASS.

- [ ] **Step 5 : Commit**

```bash
git add enrichers/contact_extractor.py tests/test_contact_extractor.py
git commit -m "feat: crawl des pages contact, WhatsApp et réseaux sociaux"
```

---

### Task 10 : Extraction et typage des téléphones

**Files:**
- Create: `enrichers/phone_extractor.py`, `tests/test_phone_extractor.py`
- Modify: `requirements.txt`

**Interfaces:**
- Consomme : `phonenumbers` (nouvelle dépendance).
- Produit :
  - `COUNTRY_HINTS: dict[str, str]` — pays lisible → code ISO 3166-1 alpha-2
  - `country_hint(location: str) -> str | None`
  - `extract_phones(html: str, location: str) -> list[ExtractedPhone]`
  - dataclass `ExtractedPhone{e164, kind, source_url}` où `kind` ∈ `"mobile" | "fixe"`
  - `best_phone(phones) -> ExtractedPhone | None` — le mobile l'emporte sur le fixe
  `enrichers/email_cascade.py` (Task 16) et `processors/reachability.py` (Task 20) les consomment.

**Contexte.** Décision 1 : plus aucun téléphone acheté. Tout vient d'ici. `phonenumbers` gère nativement tous les indicatifs africains, ce qu'une regex maison ne ferait pas de manière fiable (le Maroc a des mobiles en 06 et 07, la Côte d'Ivoire a renuméroté en 2021).

- [ ] **Step 1 : Écrire les tests qui échouent**

Créer `tests/test_phone_extractor.py` :

```python
import pytest

from enrichers.phone_extractor import (
    best_phone, country_hint, extract_phones,
)


def _kinds(html, location):
    return {(p.e164, p.kind) for p in extract_phones(html, location)}


# ── Maroc ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw", [
    "+212 6 61 23 45 67", "0661234567", "06 61 23 45 67", "+212661234567",
])
def test_moroccan_mobile_is_normalized_and_typed(raw):
    assert ("+212661234567", "mobile") in _kinds(f"<p>{raw}</p>", "Casablanca, Maroc")


def test_moroccan_07_prefix_is_also_mobile():
    """Morocco opened the 07 range for mobiles in 2015; a hand-rolled regex
    keyed on 06 alone would type half the country's mobiles as landlines."""
    assert ("+212701234567", "mobile") in _kinds("<p>07 01 23 45 67</p>", "Rabat, Maroc")


def test_moroccan_landline_is_typed_fixe():
    assert ("+212522123456", "fixe") in _kinds("<p>05 22 12 34 56</p>", "Casablanca, Maroc")


# ── Autres pays africains ─────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,location,expected", [
    ("+225 07 12 34 56 78", "Abidjan, Côte d'Ivoire", "+2250712345678"),
    ("+221 77 123 45 67", "Dakar, Sénégal", "+221771234567"),
    ("+237 6 71 23 45 67", "Douala, Cameroun", "+237671234567"),
    ("+216 20 123 456", "Tunis, Tunisie", "+21620123456"),
    ("+213 5 51 23 45 67", "Alger, Algérie", "+213551234567"),
])
def test_african_mobiles_are_recognized(raw, location, expected):
    assert ("mobile") in {k for _, k in _kinds(f"<p>{raw}</p>", location)}
    assert expected in {e for e, _ in _kinds(f"<p>{raw}</p>", location)}


def test_international_format_works_without_a_location():
    """A +212 number carries its own country: no hint needed."""
    assert ("+212661234567", "mobile") in _kinds("<p>+212661234567</p>", "")


def test_a_national_number_without_a_location_hint_is_dropped():
    """0661234567 is Moroccan, French or Ivorian depending on where you are.
    Guessing would mint a plausible but wrong E.164."""
    assert _kinds("<p>0661234567</p>", "") == set()


# ── Faux positifs ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("noise", [
    "<p>SIRET 12345678901234</p>",
    "<p>RC 123456</p>",
    "<p>2024 2025 2026</p>",
    '<img src="banner-1200x628.png">',
])
def test_identifiers_are_not_phone_numbers(noise):
    assert _kinds(noise, "Casablanca, Maroc") == set()


def test_duplicates_across_formats_collapse():
    html = "<p>+212 661 23 45 67</p><p>0661234567</p>"
    assert len(extract_phones(html, "Casablanca, Maroc")) == 1


# ── Indices pays ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("location,code", [
    ("Casablanca, Maroc", "MA"), ("Morocco", "MA"), ("Rabat", "MA"),
    ("Abidjan, Côte d'Ivoire", "CI"), ("Dakar, Senegal", "SN"),
    ("Paris, France", "FR"), ("", None), ("Zzz", None),
])
def test_country_hint_resolves_locations(location, code):
    assert country_hint(location) == code


# ── Meilleur numéro ───────────────────────────────────────────────────────────

def test_mobile_beats_landline():
    phones = extract_phones("<p>05 22 12 34 56</p><p>06 61 23 45 67</p>", "Casablanca, Maroc")
    assert best_phone(phones).kind == "mobile"


def test_best_phone_of_nothing_is_none():
    assert best_phone([]) is None
```

- [ ] **Step 2 : Lancer les tests pour vérifier qu'ils échouent**

Run : `python -m pytest tests/test_phone_extractor.py -v`
Expected : FAIL — `ModuleNotFoundError: No module named 'enrichers.phone_extractor'`.

- [ ] **Step 3 : Ajouter la dépendance**

Dans `requirements.txt`, ajouter `phonenumbers>=8.13.0`.

Run : `python -m pip install -r requirements.txt`

- [ ] **Step 4 : Implémenter**

Créer `enrichers/phone_extractor.py` :

```python
"""
Phone extraction from the prospect's own website.

Since no mobile is ever purchased (a Prospeo mobile costs 10 credits, a tenth
of the monthly allowance), every phone in the export comes from here.
Typing mobile vs landline matters: the two carry different weight in
reachability, and only phonenumbers knows that Morocco's 07 range is mobile
or that Côte d'Ivoire renumbered in 2021.
"""
import logging
import re
from dataclasses import dataclass
from typing import Optional

import phonenumbers
from phonenumbers import PhoneNumberType

from processors.icp_rules import normalize_label

logger = logging.getLogger(__name__)

# Country hints, keyed on what an Apollo "location" column actually contains:
# a city, a country, or "City, Country". Kept deliberately small and focused
# on the target markets; an unknown location yields None, which drops national
# numbers rather than minting a wrong E.164 (see _parse).
COUNTRY_HINTS: dict[str, str] = {
    "maroc": "MA", "morocco": "MA", "casablanca": "MA", "rabat": "MA",
    "marrakech": "MA", "tanger": "MA", "tangier": "MA", "fes": "MA",
    "agadir": "MA", "kenitra": "MA", "oujda": "MA", "tetouan": "MA",
    "algerie": "DZ", "algeria": "DZ", "alger": "DZ", "algiers": "DZ", "oran": "DZ",
    "tunisie": "TN", "tunisia": "TN", "tunis": "TN", "sfax": "TN",
    "senegal": "SN", "dakar": "SN",
    "cote d ivoire": "CI", "ivory coast": "CI", "abidjan": "CI", "yamoussoukro": "CI",
    "cameroun": "CM", "cameroon": "CM", "douala": "CM", "yaounde": "CM",
    "gabon": "GA", "libreville": "GA",
    "benin": "BJ", "cotonou": "BJ",
    "burkina faso": "BF", "ouagadougou": "BF",
    "mali": "ML", "bamako": "ML",
    "niger": "NE", "niamey": "NE",
    "togo": "TG", "lome": "TG",
    "guinee": "GN", "guinea": "GN", "conakry": "GN",
    "congo": "CG", "brazzaville": "CG",
    "rdc": "CD", "drc": "CD", "kinshasa": "CD",
    "madagascar": "MG", "antananarivo": "MG",
    "mauritanie": "MR", "mauritania": "MR", "nouakchott": "MR",
    "tchad": "TD", "chad": "TD", "ndjamena": "TD",
    "nigeria": "NG", "lagos": "NG", "abuja": "NG",
    "ghana": "GH", "accra": "GH",
    "kenya": "KE", "nairobi": "KE",
    "egypte": "EG", "egypt": "EG", "le caire": "EG", "cairo": "EG",
    "afrique du sud": "ZA", "south africa": "ZA", "johannesburg": "ZA",
    "france": "FR", "paris": "FR", "lyon": "FR", "marseille": "FR",
    "belgique": "BE", "belgium": "BE", "bruxelles": "BE", "brussels": "BE",
    "suisse": "CH", "switzerland": "CH", "geneve": "CH", "geneva": "CH",
    "luxembourg": "LU",
    "canada": "CA", "montreal": "CA", "quebec": "CA", "toronto": "CA",
}

_MOBILE_TYPES = frozenset({
    PhoneNumberType.MOBILE, PhoneNumberType.FIXED_LINE_OR_MOBILE,
})

# Runs of digits long enough to be company identifiers rather than phones.
_TOO_LONG_RE = re.compile(r"\d{15,}")
_TAG_RE = re.compile(r"<[^>]+>")


@dataclass(frozen=True)
class ExtractedPhone:
    e164: str
    kind: str          # "mobile" | "fixe"
    source_url: str = ""


def country_hint(location: str) -> Optional[str]:
    """Resolve an Apollo location string to an ISO alpha-2 code, or None.

    The longest matching key wins so that "Congo Kinshasa" resolves to CD
    rather than CG, mirroring the tie-break rule in processors/icp_rules.py.
    """
    normalized = normalize_label(location or "")
    if not normalized:
        return None
    best_key, best_len = None, 0
    for key, code in COUNTRY_HINTS.items():
        if key in normalized and len(key) > best_len:
            best_key, best_len = code, len(key)
    return best_key


def _kind(number) -> Optional[str]:
    number_type = phonenumbers.number_type(number)
    if number_type in _MOBILE_TYPES:
        return "mobile"
    if number_type == PhoneNumberType.FIXED_LINE:
        return "fixe"
    return None


def extract_phones(html: str, location: str, source_url: str = "") -> list[ExtractedPhone]:
    """Collect valid phone numbers from a page, normalized to E.164.

    A national-format number without a country hint is dropped, not guessed:
    "0661234567" is a Moroccan mobile, a French mobile or an Ivorian landline
    depending on where you stand, and an invented +212 would look exactly as
    trustworthy as a real one in the export.
    """
    if not html:
        return []
    text = _TAG_RE.sub(" ", html)
    text = _TOO_LONG_RE.sub(" ", text)
    region = country_hint(location)

    seen: set[str] = set()
    found: list[ExtractedPhone] = []
    for region_hint in (region, None):
        if region_hint is None and region is not None:
            continue
        for match in phonenumbers.PhoneNumberMatcher(
            text, region_hint, leniency=phonenumbers.Leniency.VALID
        ):
            e164 = phonenumbers.format_number(
                match.number, phonenumbers.PhoneNumberFormat.E164
            )
            if e164 in seen:
                continue
            kind = _kind(match.number)
            if kind is None:
                continue
            seen.add(e164)
            found.append(ExtractedPhone(e164=e164, kind=kind, source_url=source_url))
    return found


def best_phone(phones: list[ExtractedPhone]) -> Optional[ExtractedPhone]:
    """A mobile always beats a landline: it reaches a person, not a switchboard."""
    if not phones:
        return None
    return next((p for p in phones if p.kind == "mobile"), phones[0])
```

- [ ] **Step 5 : Lancer les tests pour vérifier qu'ils passent**

Run : `python -m pytest tests/test_phone_extractor.py -v`
Expected : PASS.

- [ ] **Step 6 : Brancher sur le crawl**

Dans `harvest_contacts` (`enrichers/contact_extractor.py`), collecter aussi les téléphones de la page d'accueil et de chaque page contact, et les renvoyer sous la clé `"phones"`.

- [ ] **Step 7 : Commit**

```bash
git add enrichers/phone_extractor.py enrichers/contact_extractor.py tests/test_phone_extractor.py requirements.txt
git commit -m "feat: extraction des téléphones avec typage mobile/fixe via phonenumbers"
```

---

### Task 11 : MX et détection catch-all

**Files:**
- Create: `enrichers/domain_intel.py`, `tests/test_domain_intel.py`
- Modify: `requirements.txt`

**Interfaces:**
- Consomme : `dnspython` (nouvelle dépendance), le vérificateur GetProspect/Hunter injecté par le Lot 6.
- Produit :
  - `lookup_mx(domain: str) -> MxInfo` — dataclass `{has_mx, provider}` où `provider` ∈ `"google" | "microsoft" | "autre" | None`
  - `is_catch_all(domain: str, verify_fn) -> bool | None` — `None` quand indéterminable
  - `reset_caches() -> None`
  `enrichers/email_cascade.py` (Task 16) l'appelle avant toute génération de pattern.

**Contexte.** §4 du spec. Un domaine sans MX ne reçoit pas de mail : générer un pattern serait dépenser une vérification pour rien. Le catch-all se teste une seule fois par domaine, avec une adresse aléatoire inexistante, et le résultat sert à tous les leads de ce domaine.

- [ ] **Step 1 : Écrire les tests qui échouent**

Créer `tests/test_domain_intel.py` :

```python
import pytest

from enrichers import domain_intel


@pytest.fixture(autouse=True)
def clear_caches():
    domain_intel.reset_caches()
    yield
    domain_intel.reset_caches()


def _fake_mx(monkeypatch, hosts):
    class _Rec:
        def __init__(self, host): self.exchange = host
        def __str__(self): return self.exchange

    def _resolve(domain, record_type):
        if hosts is None:
            import dns.resolver
            raise dns.resolver.NoAnswer()
        return [_Rec(h) for h in hosts]

    monkeypatch.setattr(domain_intel.dns.resolver, "resolve", _resolve)


def test_google_workspace_is_detected(monkeypatch):
    _fake_mx(monkeypatch, ["aspmx.l.google.com.", "alt1.aspmx.l.google.com."])
    info = domain_intel.lookup_mx("acme.ma")
    assert info.has_mx is True
    assert info.provider == "google"


def test_microsoft_365_is_detected(monkeypatch):
    _fake_mx(monkeypatch, ["acme-ma.mail.protection.outlook.com."])
    assert domain_intel.lookup_mx("acme.ma").provider == "microsoft"


def test_an_unknown_host_is_autre(monkeypatch):
    _fake_mx(monkeypatch, ["mail.ovh.net."])
    assert domain_intel.lookup_mx("acme.ma").provider == "autre"


def test_a_domain_without_mx_is_flagged(monkeypatch):
    _fake_mx(monkeypatch, None)
    info = domain_intel.lookup_mx("acme.ma")
    assert info.has_mx is False
    assert info.provider is None


def test_mx_result_is_cached_per_domain(monkeypatch):
    calls = []

    class _Rec:
        exchange = "aspmx.l.google.com."
        def __str__(self): return self.exchange

    def _resolve(domain, record_type):
        calls.append(domain)
        return [_Rec()]

    monkeypatch.setattr(domain_intel.dns.resolver, "resolve", _resolve)
    domain_intel.lookup_mx("acme.ma")
    domain_intel.lookup_mx("acme.ma")
    assert len(calls) == 1


# ── Catch-all ─────────────────────────────────────────────────────────────────

def test_a_domain_accepting_a_random_address_is_catch_all():
    probes = []

    def verify(email):
        probes.append(email)
        return "valid"

    assert domain_intel.is_catch_all("acme.ma", verify) is True
    assert probes[0].endswith("@acme.ma")
    assert len(probes) == 1


def test_a_domain_rejecting_a_random_address_is_not_catch_all():
    assert domain_intel.is_catch_all("acme.ma", lambda e: "invalid") is False


def test_an_inconclusive_probe_yields_none():
    """Unknown means we could not tell. Recording it as False would send the
    cascade spending verifications on a domain that answers yes to everything."""
    assert domain_intel.is_catch_all("acme.ma", lambda e: "unknown") is None


def test_the_probe_runs_once_per_domain():
    probes = []

    def verify(email):
        probes.append(email)
        return "valid"

    domain_intel.is_catch_all("acme.ma", verify)
    domain_intel.is_catch_all("acme.ma", verify)
    domain_intel.is_catch_all("acme.ma", verify)
    assert len(probes) == 1, "un domaine se teste une fois, pas une fois par lead"


def test_different_domains_are_probed_separately():
    probes = []
    domain_intel.is_catch_all("acme.ma", lambda e: probes.append(e) or "valid")
    domain_intel.is_catch_all("other.ma", lambda e: probes.append(e) or "valid")
    assert len(probes) == 2


def test_a_verifier_that_raises_never_propagates():
    def boom(email):
        raise RuntimeError("quota")

    assert domain_intel.is_catch_all("acme.ma", boom) is None


def test_the_probe_address_is_random_enough_to_not_exist():
    seen = set()
    for domain in (f"d{i}.ma" for i in range(20)):
        domain_intel.is_catch_all(domain, lambda e: seen.add(e.split("@")[0]) or "invalid")
    assert len(seen) == 20
```

- [ ] **Step 2 : Lancer les tests pour vérifier qu'ils échouent**

Run : `python -m pytest tests/test_domain_intel.py -v`
Expected : FAIL — `ModuleNotFoundError: No module named 'enrichers.domain_intel'`.

- [ ] **Step 3 : Ajouter la dépendance**

Dans `requirements.txt`, ajouter `dnspython>=2.6.0`.

- [ ] **Step 4 : Implémenter**

Créer `enrichers/domain_intel.py` :

```python
"""
Step 4 — Domain-level checks that gate pattern generation.

Two questions decide whether generating an email candidate is worth a paid
verification: does the domain receive mail at all, and does it accept every
address thrown at it. Both are properties of the domain, not of the lead, so
both are answered once and reused for every lead sharing it — a company with
twelve contacts would otherwise pay twelve times for the same answer.
"""
import logging
import secrets
from dataclasses import dataclass
from typing import Callable, Optional

import dns.resolver

logger = logging.getLogger(__name__)

_MX_PROVIDERS = (
    ("google", ("google.com", "googlemail.com", "aspmx")),
    ("microsoft", ("outlook.com", "protection.outlook", "office365")),
)

_mx_cache: dict[str, "MxInfo"] = {}
_catch_all_cache: dict[str, Optional[bool]] = {}


@dataclass(frozen=True)
class MxInfo:
    has_mx: bool
    provider: Optional[str]     # "google" | "microsoft" | "autre" | None


def reset_caches() -> None:
    """Clear per-run domain caches. Called alongside the enricher resets."""
    _mx_cache.clear()
    _catch_all_cache.clear()


def lookup_mx(domain: str) -> MxInfo:
    """Resolve a domain's MX records once, then serve every later lead from cache."""
    key = (domain or "").strip().lower()
    if not key:
        return MxInfo(has_mx=False, provider=None)
    if key in _mx_cache:
        return _mx_cache[key]

    try:
        answers = dns.resolver.resolve(key, "MX")
        hosts = [str(getattr(r, "exchange", r)).lower() for r in answers]
    except Exception as exc:
        logger.debug(f"No MX for {key}: {exc}")
        info = MxInfo(has_mx=False, provider=None)
        _mx_cache[key] = info
        return info

    provider = "autre"
    for name, needles in _MX_PROVIDERS:
        if any(needle in host for host in hosts for needle in needles):
            provider = name
            break

    info = MxInfo(has_mx=bool(hosts), provider=provider if hosts else None)
    _mx_cache[key] = info
    return info


def is_catch_all(domain: str, verify_fn: Callable[[str], str]) -> Optional[bool]:
    """Probe one random, certainly-nonexistent address on the domain.

    Returns True (accepts anything), False (rejects unknown mailboxes) or None
    (the verifier could not tell). None is not False: recording an
    inconclusive probe as "not catch-all" would send the cascade paying to
    verify candidates on a domain that says yes to every one of them.
    """
    key = (domain or "").strip().lower()
    if not key:
        return None
    if key in _catch_all_cache:
        return _catch_all_cache[key]

    probe = f"zz{secrets.token_hex(8)}@{key}"
    try:
        status = (verify_fn(probe) or "").strip().lower()
    except Exception as exc:
        logger.debug(f"Catch-all probe failed for {key}: {exc}")
        _catch_all_cache[key] = None
        return None

    if status == "valid":
        result: Optional[bool] = True
    elif status in ("invalid", "not_found"):
        result = False
    else:
        result = None

    _catch_all_cache[key] = result
    return result
```

- [ ] **Step 5 : Lancer les tests pour vérifier qu'ils passent**

Run : `python -m pytest tests/test_domain_intel.py -v`
Expected : PASS.

- [ ] **Step 6 : Commit**

```bash
git add enrichers/domain_intel.py tests/test_domain_intel.py requirements.txt
git commit -m "feat: lecture des MX et détection catch-all mise en cache par domaine"
```

---

### Task 12 : Génération de candidats email

**Files:**
- Create: `enrichers/email_patterns.py`, `tests/test_email_patterns.py`

**Interfaces:**
- Consomme : `api.quota_db.normalize_name`.
- Produit :
  - `DEFAULT_ORDER: tuple[str, ...]` — `("prenom.nom", "pnom", "prenom", "nom.prenom", "prenomnom", "p.nom")`
  - `MAX_CANDIDATES = 3`
  - `split_name(first: str, last: str) -> tuple[str, str]` — particules et noms composés
  - `infer_format(known_email: str, known_first: str, known_last: str) -> str | None`
  - `generate(first, last, domain, known_email=None, known_first=None, known_last=None) -> list[str]`

**Contexte.** §5b. Un `nominatif_autre` trouvé sur le site révèle le format de l'entreprise — on génère alors **un seul** candidat au lieu de trois, et on économise deux vérifications. Sinon on suit l'ordre par défaut, plafonné à trois. Jamais de variante orthographique inventée : l'orthographe Apollo fait foi.

- [ ] **Step 1 : Écrire les tests qui échouent**

Créer `tests/test_email_patterns.py` :

```python
import pytest

from enrichers.email_patterns import (
    MAX_CANDIDATES, generate, infer_format, split_name,
)


# ── Normalisation des noms ────────────────────────────────────────────────────

@pytest.mark.parametrize("first,last,expected", [
    ("Karim", "El Amrani", ("karim", "elamrani")),
    ("Fatima", "Ben Ali", ("fatima", "benali")),
    ("Mohamed", "Ait Bella", ("mohamed", "aitbella")),
    ("Ahmed", "Ould Cheikh", ("ahmed", "ouldcheikh")),
    ("Jean-Pierre", "Dupont", ("jeanpierre", "dupont")),
    ("Marie", "Durand-Martin", ("marie", "durandmartin")),
    ("Aïcha", "Benîtez", ("aicha", "benitez")),
    ("  KARIM  ", " el amrani ", ("karim", "elamrani")),
])
def test_particles_and_compounds_are_folded(first, last, expected):
    assert split_name(first, last) == expected


# ── Ordre par défaut ──────────────────────────────────────────────────────────

def test_default_order_is_respected_and_capped():
    candidates = generate("Karim", "El Amrani", "acme.ma")
    assert candidates == [
        "karim.elamrani@acme.ma",
        "kelamrani@acme.ma",
        "karim@acme.ma",
    ]
    assert len(candidates) <= MAX_CANDIDATES


def test_no_duplicate_candidates():
    """When first and last collapse to the same string, several patterns
    produce one address. Verifying it twice would waste a credit."""
    assert len(generate("Ali", "Ali", "acme.ma")) == len(set(generate("Ali", "Ali", "acme.ma")))


def test_a_missing_name_yields_nothing():
    assert generate("", "El Amrani", "acme.ma") == []
    assert generate("Karim", "", "acme.ma") == []
    assert generate("Karim", "El Amrani", "") == []


def test_apollo_spelling_is_used_verbatim():
    """We never invent "Mohammed" from "Mohamed" or vice versa: a plausible
    variant costs a verification and lands on a mailbox that does not exist."""
    assert all("mohamed" in c for c in generate("Mohamed", "Alaoui", "acme.ma"))


# ── Déduction du format d'entreprise ──────────────────────────────────────────

@pytest.mark.parametrize("email,first,last,expected", [
    ("sara.bennani@acme.ma", "Sara", "Bennani", "prenom.nom"),
    ("sbennani@acme.ma", "Sara", "Bennani", "pnom"),
    ("sara@acme.ma", "Sara", "Bennani", "prenom"),
    ("bennani.sara@acme.ma", "Sara", "Bennani", "nom.prenom"),
    ("sarabennani@acme.ma", "Sara", "Bennani", "prenomnom"),
    ("s.bennani@acme.ma", "Sara", "Bennani", "p.nom"),
])
def test_format_is_inferred_from_a_colleague_address(email, first, last, expected):
    assert infer_format(email, first, last) == expected


def test_an_unrecognized_shape_yields_no_format():
    assert infer_format("sb2024@acme.ma", "Sara", "Bennani") is None


def test_an_inferred_format_produces_exactly_one_candidate():
    """Knowing the company format turns three paid verifications into one."""
    candidates = generate(
        "Karim", "El Amrani", "acme.ma",
        known_email="sbennani@acme.ma", known_first="Sara", known_last="Bennani",
    )
    assert candidates == ["kelamrani@acme.ma"]


def test_an_uninferable_colleague_address_falls_back_to_the_default_order():
    candidates = generate(
        "Karim", "El Amrani", "acme.ma",
        known_email="sb2024@acme.ma", known_first="Sara", known_last="Bennani",
    )
    assert candidates[0] == "karim.elamrani@acme.ma"
    assert len(candidates) == MAX_CANDIDATES


def test_inference_handles_a_colleague_with_a_particle():
    assert infer_format("y.elidrissi@acme.ma", "Youssef", "El Idrissi") == "p.nom"
```

- [ ] **Step 2 : Lancer les tests pour vérifier qu'ils échouent**

Run : `python -m pytest tests/test_email_patterns.py -v`
Expected : FAIL — `ModuleNotFoundError: No module named 'enrichers.email_patterns'`.

- [ ] **Step 3 : Implémenter**

Créer `enrichers/email_patterns.py` :

```python
"""
Step 5b — Email candidate generation.

Every candidate costs a verification credit, so the module is built to emit as
few as possible: one when a colleague's address on the site reveals the
company format, at most three otherwise. It never invents a spelling variant —
"Mohammed" for "Mohamed" doubles the cost for a mailbox that probably does not
exist, and the Apollo spelling is the only one we have any evidence for.
"""
import re
from typing import Optional

from api.quota_db import normalize_name

MAX_CANDIDATES = 3

DEFAULT_ORDER: tuple[str, ...] = (
    "prenom.nom", "pnom", "prenom", "nom.prenom", "prenomnom", "p.nom",
)

_BUILDERS = {
    "prenom.nom": lambda f, l: f"{f}.{l}",
    "pnom": lambda f, l: f"{f[0]}{l}",
    "prenom": lambda f, l: f,
    "nom.prenom": lambda f, l: f"{l}.{f}",
    "prenomnom": lambda f, l: f"{f}{l}",
    "p.nom": lambda f, l: f"{f[0]}.{l}",
}


def split_name(first: str, last: str) -> tuple[str, str]:
    """Fold a name into its email-safe form.

    Particles are joined rather than dropped: "El Amrani" becomes "elamrani",
    which is how Moroccan and Maghrebi mailboxes are actually spelled. Dropping
    the particle ("amrani") would generate an address for a different person.
    """
    def _fold(value: str) -> str:
        return re.sub(r"[^a-z0-9]", "", normalize_name(value))

    return _fold(first), _fold(last)


def infer_format(known_email: str, known_first: str, known_last: str) -> Optional[str]:
    """Recover the company's email format from one colleague's address.

    Returns a key of DEFAULT_ORDER, or None when the local part matches none
    of them — an address like "sb2024@" tells us nothing transferable.
    """
    if not known_email or "@" not in known_email:
        return None
    local = known_email.split("@", 1)[0].strip().lower()
    first, last = split_name(known_first, known_last)
    if not first or not last:
        return None
    for name in DEFAULT_ORDER:
        if _BUILDERS[name](first, last) == local:
            return name
    return None


def generate(first: str, last: str, domain: str,
             known_email: Optional[str] = None,
             known_first: Optional[str] = None,
             known_last: Optional[str] = None) -> list[str]:
    """Produce at most MAX_CANDIDATES addresses, best first.

    A recognised company format collapses the list to a single candidate,
    turning three paid verifications into one.
    """
    folded_first, folded_last = split_name(first, last)
    clean_domain = (domain or "").strip().lower().removeprefix("www.")
    if not folded_first or not folded_last or not clean_domain:
        return []

    inferred = infer_format(known_email or "", known_first or "", known_last or "")
    order = (inferred,) if inferred else DEFAULT_ORDER

    candidates: list[str] = []
    for name in order:
        address = f"{_BUILDERS[name](folded_first, folded_last)}@{clean_domain}"
        if address not in candidates:
            candidates.append(address)
        if len(candidates) >= (1 if inferred else MAX_CANDIDATES):
            break
    return candidates
```

- [ ] **Step 4 : Lancer les tests pour vérifier qu'ils passent**

Run : `python -m pytest tests/test_email_patterns.py -v`
Expected : PASS.

- [ ] **Step 5 : Commit**

```bash
git add enrichers/email_patterns.py tests/test_email_patterns.py
git commit -m "feat: génération de candidats email avec déduction du format d'entreprise"
```

---

### Task 13 : Socle commun des fournisseurs et client Prospeo

**Files:**
- Create: `enrichers/providers/base.py`, `enrichers/providers/prospeo.py`, `tests/test_provider_prospeo.py`

**Interfaces:**
- Consomme : `api.quota_db`, `enrichers.retry`, `enrichers.providers.quota_sync`.
- Produit :
  - dataclass `EmailResult{email, status, provider, billed, cost, raw_status, domain_mismatch}` où `status` ∈ `"valid" | "accept_all" | "unknown" | "not_found"`
  - `NOT_FOUND: EmailResult` — singleton pour « le fournisseur a répondu, il n'a rien »
  - `find_email(first, last, domain) -> EmailResult` dans chaque client
  - `prospeo.COST_PER_EMAIL = 1.0`
  `enrichers/email_cascade.py` (Task 16) programme contre ce seul contrat.

**Contexte.** `/email-finder` n'existe plus chez Prospeo ; l'équivalent est `POST /enrich-person`. Prospeo n'a **aucun** vérificateur, donc ce client n'implémente que `find_email`.

- [ ] **Step 1 : Écrire les tests qui échouent**

Créer `tests/test_provider_prospeo.py` :

```python
import pytest
import requests

from api import quota_db
from enrichers.providers import prospeo
from enrichers.retry import AuthError, QuotaExhausted


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(quota_db, "_DB_PATH", str(tmp_path / "q.db"))
    quota_db.init_quota_tables()
    monkeypatch.setattr("config.PROSPEO_API_KEY", "real-key")


def _respond(monkeypatch, payload, status=200):
    class _Resp:
        status_code = status
        def json(self): return payload
        def raise_for_status(self):
            if status >= 400:
                raise requests.exceptions.HTTPError(response=self)

    monkeypatch.setattr(prospeo.requests, "post", lambda *a, **k: _Resp())


# ── Succès ────────────────────────────────────────────────────────────────────

_FOUND = {
    "error": False,
    "free_enrichment": False,
    "person": {
        "first_name": "Karim", "last_name": "El Amrani",
        "email": {
            "status": "VERIFIED", "revealed": True,
            "email": "karim.elamrani@acme.ma",
            "verification_method": "SMTP", "email_mx_provider": "Google",
        },
    },
    "company": {"domain": "acme.ma"},
}


def test_a_verified_email_is_returned_as_valid(monkeypatch):
    _respond(monkeypatch, _FOUND)
    result = prospeo.find_email("Karim", "El Amrani", "acme.ma")
    assert result.email == "karim.elamrani@acme.ma"
    assert result.status == "valid"
    assert result.billed is True


def test_free_enrichment_marks_the_result_unbilled(monkeypatch):
    """Re-enriching the same record within 90 days costs nothing. Decrementing
    the local counter anyway would end the month early for no reason."""
    _respond(monkeypatch, {**_FOUND, "free_enrichment": True})
    assert prospeo.find_email("Karim", "El Amrani", "acme.ma").billed is False


def test_an_unrevealed_email_is_not_usable(monkeypatch):
    payload = {**_FOUND, "person": {"email": {"status": "VERIFIED", "revealed": False,
                                              "email": "karim.*****@acme.ma"}}}
    _respond(monkeypatch, payload)
    assert prospeo.find_email("Karim", "El Amrani", "acme.ma").status == "not_found"


def test_an_unavailable_status_is_not_usable(monkeypatch):
    payload = {**_FOUND, "person": {"email": {"status": "UNAVAILABLE", "revealed": False,
                                              "email": None}}}
    _respond(monkeypatch, payload)
    assert prospeo.find_email("Karim", "El Amrani", "acme.ma").status == "not_found"


def test_a_null_person_never_raises(monkeypatch):
    """Prospeo documents that any property can be null, including top-level
    objects. Reaching into person.email without a guard crashes the run."""
    _respond(monkeypatch, {"error": False, "free_enrichment": False,
                           "person": None, "company": None})
    assert prospeo.find_email("Karim", "El Amrani", "acme.ma").status == "not_found"


# ── Erreurs ───────────────────────────────────────────────────────────────────

def test_no_match_is_a_miss_not_an_error(monkeypatch):
    """Prospeo answers HTTP 400 for "found nothing". Treating the status code
    as the signal would mark a perfectly healthy provider as failed."""
    _respond(monkeypatch, {"error": True, "error_code": "NO_MATCH"}, status=400)
    result = prospeo.find_email("Karim", "El Amrani", "acme.ma")
    assert result.status == "not_found"
    assert result.billed is False


def test_insufficient_credits_raises_quota_exhausted(monkeypatch):
    _respond(monkeypatch, {"error": True, "error_code": "INSUFFICIENT_CREDITS"}, status=400)
    with pytest.raises(QuotaExhausted):
        prospeo.find_email("Karim", "El Amrani", "acme.ma")


def test_invalid_api_key_raises_auth_error(monkeypatch):
    _respond(monkeypatch, {"error": True, "error_code": "INVALID_API_KEY"}, status=400)
    with pytest.raises(AuthError):
        prospeo.find_email("Karim", "El Amrani", "acme.ma")


# ── Requête ───────────────────────────────────────────────────────────────────

def test_the_request_shape_matches_the_documentation(monkeypatch):
    captured = {}

    class _Resp:
        status_code = 200
        def json(self): return _FOUND
        def raise_for_status(self): pass

    def _post(url, json=None, headers=None, timeout=None):
        captured.update({"url": url, "json": json, "headers": headers})
        return _Resp()

    monkeypatch.setattr(prospeo.requests, "post", _post)
    prospeo.find_email("Karim", "El Amrani", "acme.ma")

    assert captured["url"] == "https://api.prospeo.io/enrich-person"
    assert captured["headers"]["X-KEY"] == "real-key"
    assert captured["headers"]["Content-Type"] == "application/json"
    assert captured["json"]["only_verified_email"] is True
    assert captured["json"]["enrich_mobile"] is False, "un mobile coûte 10 crédits"
    assert captured["json"]["data"] == {
        "first_name": "Karim", "last_name": "El Amrani", "company_website": "acme.ma",
    }


def test_a_missing_key_skips_the_call_entirely(monkeypatch):
    monkeypatch.setattr("config.PROSPEO_API_KEY", "")
    def _boom(*a, **k):
        raise AssertionError("aucun appel ne doit partir sans clé")
    monkeypatch.setattr(prospeo.requests, "post", _boom)
    assert prospeo.find_email("Karim", "El Amrani", "acme.ma").status == "not_found"
```

- [ ] **Step 2 : Lancer les tests pour vérifier qu'ils échouent**

Run : `python -m pytest tests/test_provider_prospeo.py -v`
Expected : FAIL — `ImportError: cannot import name 'prospeo'`.

- [ ] **Step 3 : Implémenter le socle**

Créer `enrichers/providers/base.py` :

```python
"""
Common contract for the three email providers.

They disagree on everything — Prospeo nests results under "person" and answers
400 for "nothing found", GetProspect wraps everything in a success envelope
and answers 200 for the same case, Hunter returns a flat payload and inverts
403/429. The cascade must not know any of that, so each client normalises into
EmailResult and nothing else escapes.
"""
from dataclasses import dataclass
from typing import Optional

# Statuses the cascade branches on. Deliberately narrower than any provider's
# own vocabulary: an unrecognised provider status maps to "unknown", never to
# an exception and never optimistically to "valid".
VALID = "valid"
ACCEPT_ALL = "accept_all"
UNKNOWN = "unknown"
NOT_FOUND = "not_found"


@dataclass(frozen=True)
class EmailResult:
    email: Optional[str] = None
    status: str = NOT_FOUND
    provider: Optional[str] = None
    billed: bool = False
    cost: float = 0.0
    raw_status: Optional[str] = None
    domain_mismatch: bool = False


def miss(provider: str) -> EmailResult:
    """The provider answered and had nothing. Never billed."""
    return EmailResult(status=NOT_FOUND, provider=provider, billed=False, cost=0.0)


def check_domain(email: Optional[str], expected_domain: str) -> bool:
    """True when the returned address does not belong to the company.

    A finder matching the wrong person returns a real, verifiable address on
    someone else's domain. Exporting it as this lead's contact is worse than
    returning nothing, so the mismatch travels with the result.
    """
    if not email or "@" not in email or not expected_domain:
        return False
    returned = email.rsplit("@", 1)[1].strip().lower().removeprefix("www.")
    return returned != expected_domain.strip().lower().removeprefix("www.")
```

- [ ] **Step 4 : Implémenter le client Prospeo**

Créer `enrichers/providers/prospeo.py` :

```python
"""
Prospeo client — POST /enrich-person.

The documented /email-finder endpoint no longer exists; /enrich-person is its
functional replacement. Prospeo has no email-verification endpoint at all, so
this client only ever finds.
"""
import logging
from typing import Optional

import requests

import config
from enrichers.providers.base import (
    ACCEPT_ALL, NOT_FOUND, UNKNOWN, VALID, EmailResult, check_domain, miss,
)
from enrichers.retry import AuthError, QuotaExhausted, RetryableRemoteFailure, retry_api_call

logger = logging.getLogger(__name__)

PROVIDER = "prospeo"
ENRICH_URL = "https://api.prospeo.io/enrich-person"
COST_PER_EMAIL = 1.0

# Prospeo answers HTTP 400 for every business outcome, "found nothing"
# included, so error_code is the only usable signal.
_QUOTA_CODES = frozenset({"INSUFFICIENT_CREDITS"})
_AUTH_CODES = frozenset({"INVALID_API_KEY"})
_MISS_CODES = frozenset({"NO_MATCH", "INVALID_DATAPOINTS"})


def find_email(first: str, last: str, domain: str) -> EmailResult:
    """Look one person up. Returns a miss rather than raising when nothing matches."""
    if config._is_placeholder(config.PROSPEO_API_KEY):
        return miss(PROVIDER)
    if not first or not last or not domain:
        return miss(PROVIDER)

    payload = {
        "only_verified_email": True,   # free filter: NO_MATCH instead of a charge
        "enrich_mobile": False,        # a mobile costs 10 credits — décision 1
        "data": {
            "first_name": first,
            "last_name": last,
            "company_website": domain,
        },
    }
    headers = {"Content-Type": "application/json", "X-KEY": config.PROSPEO_API_KEY}

    def _request():
        resp = requests.post(ENRICH_URL, json=payload, headers=headers, timeout=30)
        try:
            body = resp.json()
        except ValueError:
            resp.raise_for_status()
            raise RetryableRemoteFailure(f"{PROVIDER}: non-JSON response")

        if isinstance(body, dict) and body.get("error"):
            code = str(body.get("error_code") or "")
            if code in _AUTH_CODES:
                raise AuthError(f"{PROVIDER}: {code}")
            if code in _QUOTA_CODES:
                raise QuotaExhausted(f"{PROVIDER}: {code}")
            if code in _MISS_CODES:
                return miss(PROVIDER)
            raise RetryableRemoteFailure(f"{PROVIDER}: {code or 'unknown error'}")

        resp.raise_for_status()
        return _parse(body, domain)

    return retry_api_call(_request, max_retries=2, operation_name=f"Prospeo ({domain})")


def _parse(body: dict, domain: str) -> EmailResult:
    """Normalise a success payload. Every nested object may be null."""
    person = (body or {}).get("person") or {}
    email_block = person.get("email") or {}

    address = email_block.get("email")
    revealed = bool(email_block.get("revealed"))
    raw_status = str(email_block.get("status") or "")

    # An unrevealed address is masked ("karim.*****@acme.ma") and unusable;
    # UNAVAILABLE means Prospeo has no verified address for this person.
    if not address or not revealed or raw_status.upper() != "VERIFIED":
        return miss(PROVIDER)

    billed = not bool(body.get("free_enrichment"))
    return EmailResult(
        email=address.strip().lower(),
        status=VALID,
        provider=PROVIDER,
        billed=billed,
        cost=COST_PER_EMAIL if billed else 0.0,
        raw_status=raw_status,
        domain_mismatch=check_domain(address, domain),
    )
```

- [ ] **Step 5 : Lancer les tests pour vérifier qu'ils passent**

Run : `python -m pytest tests/test_provider_prospeo.py -v`
Expected : PASS.

- [ ] **Step 6 : Commit**

```bash
git add enrichers/providers/base.py enrichers/providers/prospeo.py tests/test_provider_prospeo.py
git commit -m "feat: client Prospeo sur /enrich-person, mobile désactivé"
```

---

### Task 14 : Client GetProspect — recherche et vérification

**Files:**
- Create: `enrichers/providers/getprospect.py`, `tests/test_provider_getprospect.py`

**Interfaces:**
- Consomme : `base`, `quota_sync.absorb_getprospect_metadata`, `enrichers.retry`.
- Produit :
  - `find_email(first, last, domain) -> EmailResult`
  - `verify_email(email) -> EmailResult`
  - `COST_PER_EMAIL = 1.0`, `COST_PER_VERIFICATION = 1.0`

**Contexte.** API v2 sur `getprospect.com/api-docs`, en-tête `x-api-key`, POST. **« Aucun résultat » est un HTTP 200** avec `success: false` — le prédicat porte sur l'enveloppe, jamais sur le code HTTP. Le solde arrive dans `metadata.credits` à chaque réponse : le client l'absorbe systématiquement.

- [ ] **Step 1 : Écrire les tests qui échouent**

Créer `tests/test_provider_getprospect.py` :

```python
import pytest
import requests

from api import quota_db
from enrichers.providers import getprospect
from enrichers.providers.base import ACCEPT_ALL, NOT_FOUND, UNKNOWN, VALID
from enrichers.retry import AuthError, QuotaExhausted, RetryableRemoteFailure


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(quota_db, "_DB_PATH", str(tmp_path / "q.db"))
    quota_db.init_quota_tables()
    monkeypatch.setattr("config.GETPROSPECT_API_KEY", "real-key")


def _respond(monkeypatch, payload, status=200):
    class _Resp:
        status_code = status
        def json(self): return payload
        def raise_for_status(self):
            if status >= 400:
                raise requests.exceptions.HTTPError(response=self)

    monkeypatch.setattr(getprospect.requests, "post", lambda *a, **k: _Resp())


_CREDITS = {"email_search": 42, "email_verification": 98,
            "reset_at": "2026-10-01T00:00:00.000Z"}

_FOUND = {
    "success": True,
    "data": {"email": "karim.elamrani@acme.ma", "status": "valid",
             "account": "karim.elamrani", "domain": "acme.ma",
             "domain_status": "valid", "smtp_provider": "google",
             "free_email": False},
    "metadata": {"timestamp": "2026-09-25T14:07:55.000Z", "credits": _CREDITS},
}


def test_a_valid_email_is_returned(monkeypatch):
    _respond(monkeypatch, _FOUND)
    result = getprospect.find_email("Karim", "El Amrani", "acme.ma")
    assert result.email == "karim.elamrani@acme.ma"
    assert result.status == VALID
    assert result.billed is True


def test_not_found_is_http_200_with_success_false(monkeypatch):
    """The documentation is explicit: check success and errors, not the
    status code. A 404-based predicate would never fire."""
    _respond(monkeypatch, {
        "success": False,
        "data": {"email": None, "domain": "acme.ma", "domain_status": "valid"},
        "metadata": {"credits": _CREDITS},
        "errors": [{"name": "NOT_FOUND", "message": "No email found"}],
    }, status=200)
    result = getprospect.find_email("Karim", "El Amrani", "acme.ma")
    assert result.status == NOT_FOUND
    assert result.billed is False, "not_found est remboursé automatiquement"


def test_accept_all_from_the_finder_is_refunded(monkeypatch):
    """The finder converts accept_all into not_found with domain_status
    accept_all, and refunds the credit."""
    _respond(monkeypatch, {
        "success": False,
        "data": {"email": None, "domain": "acme.ma", "domain_status": "accept_all"},
        "metadata": {"credits": _CREDITS},
        "errors": [{"name": "NOT_FOUND", "message": "accept-all"}],
    })
    result = getprospect.find_email("Karim", "El Amrani", "acme.ma")
    assert result.billed is False


def test_the_balance_is_absorbed_from_every_response(monkeypatch):
    """GetProspect has no account endpoint: this is the only sync channel."""
    _respond(monkeypatch, _FOUND)
    getprospect.find_email("Karim", "El Amrani", "acme.ma")
    assert quota_db.get_quota("getprospect")["remaining"] == 42.0
    assert quota_db.get_quota("getprospect_verify")["remaining"] == 98.0


def test_402_raises_quota_exhausted(monkeypatch):
    _respond(monkeypatch, {
        "success": False, "data": None, "metadata": {},
        "errors": [{"name": "PAYMENT_REQUIRED",
                    "message": "Insufficient email credits: have 0, need 1"}],
    }, status=402)
    with pytest.raises(QuotaExhausted):
        getprospect.find_email("Karim", "El Amrani", "acme.ma")


def test_401_raises_auth_error(monkeypatch):
    _respond(monkeypatch, {"success": False, "data": None,
                           "errors": [{"name": "UNAUTHORIZED", "message": "Unauthorized"}]},
             status=401)
    with pytest.raises(AuthError):
        getprospect.find_email("Karim", "El Amrani", "acme.ma")


def test_408_is_retryable(monkeypatch):
    _respond(monkeypatch, {"success": False, "data": None,
                           "errors": [{"name": "TIMEOUT", "message": "retry later"}]},
             status=408)
    with pytest.raises(RetryableRemoteFailure):
        getprospect.find_email("Karim", "El Amrani", "acme.ma")


# ── Vérification ──────────────────────────────────────────────────────────────

def test_verification_maps_valid(monkeypatch):
    _respond(monkeypatch, {**_FOUND, "data": {**_FOUND["data"], "status": "valid"}})
    assert getprospect.verify_email("karim@acme.ma").status == VALID


@pytest.mark.parametrize("raw,expected", [
    ("valid", VALID),
    ("accept_all", ACCEPT_ALL),
    ("invalid", NOT_FOUND),
    ("not_found", NOT_FOUND),
])
def test_known_verification_statuses_map(monkeypatch, raw, expected):
    _respond(monkeypatch, {"success": True, "data": {"email": "k@acme.ma", "status": raw},
                           "metadata": {"credits": _CREDITS}})
    assert getprospect.verify_email("k@acme.ma").status == expected


def test_an_undocumented_status_degrades_to_unknown(monkeypatch):
    """The OpenAPI declares status as a bare string with no enum. A value we
    have never seen must not be read as sendable, and must not crash."""
    _respond(monkeypatch, {"success": True, "data": {"email": "k@acme.ma", "status": "greylisted"},
                           "metadata": {"credits": _CREDITS}})
    result = getprospect.verify_email("k@acme.ma")
    assert result.status == UNKNOWN
    assert result.raw_status == "greylisted"


def test_the_request_shape_matches_the_v2_documentation(monkeypatch):
    captured = {}

    class _Resp:
        status_code = 200
        def json(self): return _FOUND
        def raise_for_status(self): pass

    def _post(url, json=None, headers=None, timeout=None):
        captured.update({"url": url, "json": json, "headers": headers})
        return _Resp()

    monkeypatch.setattr(getprospect.requests, "post", _post)
    getprospect.find_email("Karim", "El Amrani", "acme.ma")

    assert captured["url"] == "https://api.getprospect.com/v2/email/find"
    assert captured["headers"]["x-api-key"] == "real-key"
    assert captured["json"] == {"data": {"first_name": "Karim",
                                         "last_name": "El Amrani",
                                         "domain": "acme.ma"}}
```

- [ ] **Step 2 : Lancer les tests pour vérifier qu'ils échouent**

Run : `python -m pytest tests/test_provider_getprospect.py -v`
Expected : FAIL — `ImportError: cannot import name 'getprospect'`.

- [ ] **Step 3 : Implémenter**

Créer `enrichers/providers/getprospect.py` :

```python
"""
GetProspect client — API v2.

Built against getprospect.com/api-docs, not getprospect.readme.io: the latter
documents an older generation with a different auth header and GET verbs.

Two things shape this client. "No result" is an HTTP 200 with success:false,
so the status code is never the predicate. And there is no account endpoint —
the balance rides along in metadata.credits, which is why every response,
successful or not, goes through _absorb before anything else.
"""
import logging
from typing import Optional

import requests

import config
from enrichers.providers.base import (
    ACCEPT_ALL, NOT_FOUND, UNKNOWN, VALID, EmailResult, check_domain, miss,
)
from enrichers.providers.quota_sync import absorb_getprospect_metadata
from enrichers.retry import (
    AuthError, QuotaExhausted, RetryableRemoteFailure, retry_api_call,
)

logger = logging.getLogger(__name__)

PROVIDER = "getprospect"
FIND_URL = "https://api.getprospect.com/v2/email/find"
VERIFY_URL = "https://api.getprospect.com/v2/email/verify"
COST_PER_EMAIL = 1.0
COST_PER_VERIFICATION = 1.0

# Statuses attested in the documentation. Anything else degrades to UNKNOWN:
# the OpenAPI declares status as a bare string with no enum, so the list is
# known to be incomplete and must never be treated as exhaustive.
_STATUS_MAP = {
    "valid": VALID,
    "accept_all": ACCEPT_ALL,
    "invalid": NOT_FOUND,
    "not_found": NOT_FOUND,
}

_ERROR_NAMES_MISS = frozenset({"NOT_FOUND"})


def _post(url: str, payload: dict, label: str) -> dict:
    """Send one request, absorb the balance, and translate the envelope.

    Raises on auth, quota and retryable failures; returns the parsed body
    otherwise, including the success:false / NOT_FOUND case which is a normal
    answer rather than an error.
    """
    headers = {"Content-Type": "application/json", "x-api-key": config.GETPROSPECT_API_KEY}
    resp = requests.post(url, json=payload, headers=headers, timeout=60)
    try:
        body = resp.json()
    except ValueError:
        resp.raise_for_status()
        raise RetryableRemoteFailure(f"{PROVIDER}: non-JSON response")

    if isinstance(body, dict):
        absorb_getprospect_metadata(body.get("metadata"))

    status = resp.status_code
    if status == 401:
        raise AuthError(f"{PROVIDER}: unauthorized ({label})")
    if status == 402:
        raise QuotaExhausted(f"{PROVIDER}: credit limit reached ({label})")
    if status == 408 or status >= 500:
        raise RetryableRemoteFailure(f"{PROVIDER}: HTTP {status} ({label})")
    resp.raise_for_status()
    return body if isinstance(body, dict) else {}


def _errors_are_a_miss(body: dict) -> bool:
    errors = body.get("errors")
    if not isinstance(errors, list):
        return False
    return any(
        isinstance(e, dict) and str(e.get("name", "")).upper() in _ERROR_NAMES_MISS
        for e in errors
    )


def find_email(first: str, last: str, domain: str) -> EmailResult:
    if config._is_placeholder(config.GETPROSPECT_API_KEY):
        return miss(PROVIDER)
    if not first or not last or not domain:
        return miss(PROVIDER)

    payload = {"data": {"first_name": first, "last_name": last, "domain": domain}}

    def _request():
        body = _post(FIND_URL, payload, f"find {domain}")
        if not body.get("success") or _errors_are_a_miss(body):
            # not_found and accept_all are both refunded automatically.
            return miss(PROVIDER)

        data = body.get("data") or {}
        address = data.get("email")
        if not address:
            return miss(PROVIDER)

        raw = str(data.get("status") or "").strip().lower()
        status = _STATUS_MAP.get(raw, UNKNOWN)
        billed = status == VALID
        return EmailResult(
            email=address.strip().lower(), status=status, provider=PROVIDER,
            billed=billed, cost=COST_PER_EMAIL if billed else 0.0,
            raw_status=raw or None, domain_mismatch=check_domain(address, domain),
        )

    return retry_api_call(_request, max_retries=2, operation_name=f"GetProspect find ({domain})")


def verify_email(email: str) -> EmailResult:
    """Verify one address. Draws on the verification quota, not the search one."""
    if config._is_placeholder(config.GETPROSPECT_API_KEY) or not email:
        return miss(PROVIDER)

    def _request():
        body = _post(VERIFY_URL, {"data": {"email": email}}, f"verify {email}")
        if not body.get("success"):
            return miss(PROVIDER)
        data = body.get("data") or {}
        raw = str(data.get("status") or "").strip().lower()
        return EmailResult(
            email=email.strip().lower(),
            status=_STATUS_MAP.get(raw, UNKNOWN),
            provider=PROVIDER, billed=True, cost=COST_PER_VERIFICATION,
            raw_status=raw or None,
        )

    return retry_api_call(_request, max_retries=2, operation_name=f"GetProspect verify ({email})")
```

- [ ] **Step 4 : Lancer les tests pour vérifier qu'ils passent**

Run : `python -m pytest tests/test_provider_getprospect.py -v`
Expected : PASS.

- [ ] **Step 5 : Commit**

```bash
git add enrichers/providers/getprospect.py tests/test_provider_getprospect.py
git commit -m "feat: client GetProspect v2, solde absorbé depuis metadata.credits"
```

---

### Task 15 : Client Hunter — recherche, vérification, 202/222

**Files:**
- Create: `enrichers/providers/hunter.py`, `tests/test_provider_hunter.py`
- Delete: `enrichers/hunter_verifier.py`, `tests/test_hunter_verifier.py`
- Modify: `main.py`, `api/pipeline_runner.py` (imports de `hunter_verifier`)

**Interfaces:**
- Consomme : `base`, `enrichers.retry`.
- Produit :
  - `find_email(first, last, domain) -> EmailResult`
  - `verify_email(email) -> EmailResult`
  - `COST_PER_EMAIL = 1.0`, `COST_PER_VERIFICATION = 0.5`
  - `VERIFY_POLL_ATTEMPTS`, `VERIFY_POLL_DELAY`

**Contexte.** Trois pièges documentés : `403` est un rate limit et `429` un quota épuisé (traités au Lot 2) ; `202` demande un repoll du même endpoint et n'est facturé qu'une fois ; `222` est dans la plage 2xx mais signale un échec SMTP distant. Les énumérations du finder (3 valeurs) et du verifier (6 valeurs) sont distinctes.

- [ ] **Step 1 : Écrire les tests qui échouent**

Créer `tests/test_provider_hunter.py` :

```python
import pytest
import requests

from enrichers.providers import hunter
from enrichers.providers.base import ACCEPT_ALL, NOT_FOUND, UNKNOWN, VALID
from enrichers.retry import AuthError, QuotaExhausted, RetryableRemoteFailure


@pytest.fixture(autouse=True)
def key(monkeypatch):
    monkeypatch.setattr("config.HUNTER_API_KEY", "real-key")
    monkeypatch.setattr(hunter, "VERIFY_POLL_DELAY", 0)


def _respond(monkeypatch, payload, status=200):
    class _Resp:
        status_code = status
        def json(self): return payload
        def raise_for_status(self):
            if status >= 400:
                raise requests.exceptions.HTTPError(response=self)

    monkeypatch.setattr(hunter.requests, "get", lambda *a, **k: _Resp())


# ── Finder ────────────────────────────────────────────────────────────────────

def test_a_found_email_is_valid(monkeypatch):
    _respond(monkeypatch, {"data": {"email": "karim@acme.ma", "score": 97,
                                    "domain": "acme.ma", "accept_all": False,
                                    "verification": {"date": "2026-09-01", "status": "valid"}},
                           "meta": {"params": {}}})
    result = hunter.find_email("Karim", "El Amrani", "acme.ma")
    assert result.email == "karim@acme.ma"
    assert result.status == VALID
    assert result.billed is True


def test_a_null_email_is_a_miss_and_is_not_billed(monkeypatch):
    """Hunter does not document the no-result body; the OpenAPI only
    guarantees data.email is present and nullable. Test the falsy value."""
    _respond(monkeypatch, {"data": {"email": None, "score": None,
                                    "verification": {"date": None, "status": None}},
                           "meta": {"params": {}}})
    result = hunter.find_email("Karim", "El Amrani", "acme.ma")
    assert result.status == NOT_FOUND
    assert result.billed is False


def test_a_404_is_a_miss_not_a_failure(monkeypatch):
    _respond(monkeypatch, {"errors": [{"id": "not_found", "code": 404, "details": "x"}]},
             status=404)
    assert hunter.find_email("Karim", "El Amrani", "acme.ma").status == NOT_FOUND


@pytest.mark.parametrize("raw,expected", [
    ("valid", VALID), ("accept_all", ACCEPT_ALL), ("unknown", UNKNOWN),
])
def test_finder_uses_its_own_three_value_enum(monkeypatch, raw, expected):
    """The finder's verification.status has three values; the verifier's has
    six. Sharing one map would mis-read one of the two."""
    _respond(monkeypatch, {"data": {"email": "k@acme.ma",
                                    "verification": {"date": "2026-09-01", "status": raw}},
                           "meta": {}})
    assert hunter.find_email("Karim", "El Amrani", "acme.ma").status == expected


# ── Verifier ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("valid", VALID), ("invalid", NOT_FOUND), ("accept_all", ACCEPT_ALL),
    ("webmail", UNKNOWN), ("disposable", NOT_FOUND), ("unknown", UNKNOWN),
])
def test_verifier_maps_all_six_documented_statuses(monkeypatch, raw, expected):
    _respond(monkeypatch, {"data": {"status": raw, "score": 90, "email": "k@acme.ma"},
                           "meta": {}})
    assert hunter.verify_email("k@acme.ma").status == expected


def test_a_verification_costs_half_a_credit(monkeypatch):
    _respond(monkeypatch, {"data": {"status": "valid", "email": "k@acme.ma"}, "meta": {}})
    assert hunter.verify_email("k@acme.ma").cost == 0.5


def test_202_is_polled_until_the_result_arrives(monkeypatch):
    """A 202 means the verification is still running. Polling the same
    endpoint is free — the request is billed only once."""
    responses = [
        (202, {"data": {}, "meta": {"params": {}, "message": "pending"}}),
        (202, {"data": {}, "meta": {"params": {}, "message": "pending"}}),
        (200, {"data": {"status": "valid", "email": "k@acme.ma"}, "meta": {}}),
    ]
    calls = []

    class _Resp:
        def __init__(self, status, payload):
            self.status_code, self._p = status, payload
        def json(self): return self._p
        def raise_for_status(self): pass

    def _get(*a, **k):
        status, payload = responses[len(calls)]
        calls.append(1)
        return _Resp(status, payload)

    monkeypatch.setattr(hunter.requests, "get", _get)
    result = hunter.verify_email("k@acme.ma")
    assert result.status == VALID
    assert len(calls) == 3
    assert result.cost == 0.5, "un 202 repollé reste facturé une seule fois"


def test_222_is_a_retryable_failure_despite_being_2xx(monkeypatch):
    """222 sits inside the success range but means the remote SMTP server
    misbehaved. A client reading it as 2xx would export a bogus verdict."""
    _respond(monkeypatch, {"errors": [{"id": "smtp", "code": 222, "details": "x"}]},
             status=222)
    with pytest.raises(RetryableRemoteFailure):
        hunter.verify_email("k@acme.ma")


def test_403_is_a_rate_limit_and_429_is_a_quota(monkeypatch):
    _respond(monkeypatch, {"errors": []}, status=429)
    with pytest.raises(QuotaExhausted):
        hunter.verify_email("k@acme.ma")


def test_401_raises_auth_error(monkeypatch):
    _respond(monkeypatch, {"errors": []}, status=401)
    with pytest.raises(AuthError):
        hunter.verify_email("k@acme.ma")


def test_request_shape(monkeypatch):
    captured = {}

    class _Resp:
        status_code = 200
        def json(self): return {"data": {"email": "k@acme.ma",
                                         "verification": {"status": "valid"}}, "meta": {}}
        def raise_for_status(self): pass

    def _get(url, params=None, timeout=None):
        captured.update({"url": url, "params": params})
        return _Resp()

    monkeypatch.setattr(hunter.requests, "get", _get)
    hunter.find_email("Karim", "El Amrani", "acme.ma")

    assert captured["url"] == "https://api.hunter.io/v2/email-finder"
    assert captured["params"]["first_name"] == "Karim"
    assert captured["params"]["last_name"] == "El Amrani"
    assert captured["params"]["domain"] == "acme.ma"
    assert captured["params"]["api_key"] == "real-key"
```

- [ ] **Step 2 : Lancer les tests pour vérifier qu'ils échouent**

Run : `python -m pytest tests/test_provider_hunter.py -v`
Expected : FAIL — `ImportError: cannot import name 'hunter'`.

- [ ] **Step 3 : Implémenter**

Créer `enrichers/providers/hunter.py` :

```python
"""
Hunter client — /v2/email-finder and /v2/email-verifier.

Three documented quirks drive this module:
  - 403 is a rate limit and 429 is an exhausted quota, the inverse of the
    usual convention (handled in enrichers/retry.py).
  - 202 means the verification is still running: poll the same endpoint, and
    the whole exchange is billed once.
  - 222 lives in the 2xx range but reports a remote SMTP failure, so
    raise_for_status() would wave it through as a success.

The finder and the verifier also expose different status vocabularies — three
values against six — so they get separate maps rather than a shared one.
"""
import logging
import time
from typing import Optional

import requests

import config
from enrichers.providers.base import (
    ACCEPT_ALL, NOT_FOUND, UNKNOWN, VALID, EmailResult, check_domain, miss,
)
from enrichers.retry import (
    AuthError, QuotaExhausted, RetryableRemoteFailure, retry_api_call,
)

logger = logging.getLogger(__name__)

PROVIDER = "hunter"
FIND_URL = "https://api.hunter.io/v2/email-finder"
VERIFY_URL = "https://api.hunter.io/v2/email-verifier"
ACCOUNT_URL = "https://api.hunter.io/v2/account"

COST_PER_EMAIL = 1.0
COST_PER_VERIFICATION = 0.5

VERIFY_POLL_ATTEMPTS = 6
VERIFY_POLL_DELAY = 5.0

# email-finder: verification.status has exactly three documented values.
_FINDER_STATUS = {"valid": VALID, "accept_all": ACCEPT_ALL, "unknown": UNKNOWN}

# email-verifier: status has exactly six. webmail is mapped to UNKNOWN rather
# than VALID — a personal mailbox at a free provider is deliverable but is not
# the corporate address the cascade is looking for.
_VERIFIER_STATUS = {
    "valid": VALID, "invalid": NOT_FOUND, "accept_all": ACCEPT_ALL,
    "webmail": UNKNOWN, "disposable": NOT_FOUND, "unknown": UNKNOWN,
}


def _raise_for_business_status(status: int, label: str) -> None:
    if status == 401:
        raise AuthError(f"{PROVIDER}: invalid API key ({label})")
    if status == 429:
        raise QuotaExhausted(f"{PROVIDER}: monthly quota exhausted ({label})")
    if status == 403:
        raise RetryableRemoteFailure(f"{PROVIDER}: rate limited ({label})")
    if status == 222:
        raise RetryableRemoteFailure(f"{PROVIDER}: remote SMTP failure ({label})")
    if status >= 500:
        raise RetryableRemoteFailure(f"{PROVIDER}: HTTP {status} ({label})")


def find_email(first: str, last: str, domain: str) -> EmailResult:
    if config._is_placeholder(config.HUNTER_API_KEY):
        return miss(PROVIDER)
    if not first or not last or not domain:
        return miss(PROVIDER)

    params = {
        "first_name": first, "last_name": last, "domain": domain,
        "api_key": config.HUNTER_API_KEY, "max_duration": 10,
    }

    def _request():
        resp = requests.get(FIND_URL, params=params, timeout=30)
        if resp.status_code == 404:
            # No profile matches — a normal answer, not an outage.
            return miss(PROVIDER)
        _raise_for_business_status(resp.status_code, f"find {domain}")
        resp.raise_for_status()

        data = (resp.json() or {}).get("data") or {}
        address = data.get("email")
        if not address:
            return miss(PROVIDER)

        verification = data.get("verification") or {}
        raw = str(verification.get("status") or "").strip().lower()
        return EmailResult(
            email=address.strip().lower(),
            status=_FINDER_STATUS.get(raw, UNKNOWN),
            provider=PROVIDER, billed=True, cost=COST_PER_EMAIL,
            raw_status=raw or None, domain_mismatch=check_domain(address, domain),
        )

    return retry_api_call(_request, max_retries=2, operation_name=f"Hunter find ({domain})")


def verify_email(email: str) -> EmailResult:
    """Verify one address, polling through any 202 the API returns."""
    if config._is_placeholder(config.HUNTER_API_KEY) or not email:
        return miss(PROVIDER)

    params = {"email": email, "api_key": config.HUNTER_API_KEY}

    def _request():
        for attempt in range(VERIFY_POLL_ATTEMPTS):
            resp = requests.get(VERIFY_URL, params=params, timeout=30)
            _raise_for_business_status(resp.status_code, f"verify {email}")
            if resp.status_code == 202:
                # Still running. Polling the same endpoint is free: the whole
                # exchange counts as one billed request.
                time.sleep(VERIFY_POLL_DELAY)
                continue
            resp.raise_for_status()

            data = (resp.json() or {}).get("data") or {}
            raw = str(data.get("status") or "").strip().lower()
            return EmailResult(
                email=email.strip().lower(),
                status=_VERIFIER_STATUS.get(raw, UNKNOWN),
                provider=PROVIDER, billed=True, cost=COST_PER_VERIFICATION,
                raw_status=raw or None,
            )
        raise RetryableRemoteFailure(f"{PROVIDER}: verification still pending for {email}")

    return retry_api_call(_request, max_retries=1, operation_name=f"Hunter verify ({email})")
```

- [ ] **Step 4 : Retirer l'ancien module**

```bash
git rm enrichers/hunter_verifier.py tests/test_hunter_verifier.py
```

Retirer les imports de `enrichers.hunter_verifier` dans `main.py` et `api/pipeline_runner.py` (trois runners). L'appel de vérification en masse disparaît : la vérification devient un pas de la cascade (Task 16), pas une étape de pipeline.

- [ ] **Step 5 : Lancer la suite**

Run : `python -m pytest tests/ -v`
Expected : PASS.

- [ ] **Step 6 : Commit**

```bash
git add enrichers/providers/hunter.py tests/test_provider_hunter.py enrichers/hunter_verifier.py tests/test_hunter_verifier.py main.py api/pipeline_runner.py
git commit -m "feat: client Hunter unifié, gestion du 202, du 222 et du 403/429"
```

---

### Task 16 : La cascade email

**Files:**
- Create: `enrichers/email_cascade.py`, `tests/test_email_cascade.py`

**Interfaces:**
- Consomme : `contact_extractor.harvest_contacts`, `email_patterns.generate`, `domain_intel.lookup_mx/is_catch_all`, les trois clients, `api.quota_db`.
- Produit :
  - `resolve_email(lead: dict, is_priority: bool, registry=None) -> dict` — pose `email`, `email_status`, `email_source`, `email_type`, `domain_catch_all`, `domain_mx_provider`, `domain_mismatch`
  - `VERIFIER_ORDER`, `FINDER_ORDER`
  - `EMAIL_STATUSES: frozenset[str]`

**Contexte.** §5 du spec, dans l'ordre a→b→c→d→e avec arrêt au premier succès. Décision 7 : vérificateurs GetProspect puis Hunter. Décision 4 : pas de `domain-search`. Les finders ne sont sollicités que pour un lead prioritaire (`is_priority`, issu du tri par `prescore` — Task 18).

- [ ] **Step 1 : Écrire les tests qui échouent**

Créer `tests/test_email_cascade.py` :

```python
import pytest

from api import quota_db
from enrichers import email_cascade
from enrichers.contact_extractor import ExtractedEmail
from enrichers.providers.base import ACCEPT_ALL, NOT_FOUND, UNKNOWN, VALID, EmailResult
from enrichers.retry import QuotaExhausted


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(quota_db, "_DB_PATH", str(tmp_path / "q.db"))
    quota_db.init_quota_tables()
    monkeypatch.setattr(email_cascade.domain_intel, "lookup_mx",
                        lambda d: email_cascade.domain_intel.MxInfo(True, "google"))
    monkeypatch.setattr(email_cascade.domain_intel, "is_catch_all", lambda d, fn: False)
    yield
    email_cascade.domain_intel.reset_caches()


def _lead(**over):
    base = {"first_name": "Karim", "last_name": "El Amrani",
            "company": "Acme", "website": "https://acme.ma",
            "location": "Casablanca, Maroc", "_site_contacts": {"emails": [], "phones": []}}
    base.update(over)
    return base


def _site(*emails):
    return {"emails": [ExtractedEmail(v, k, "https://acme.ma/contact") for v, k in emails],
            "phones": []}


# ── a. Email nominatif trouvé sur le site ─────────────────────────────────────

def test_a_nominative_site_email_wins_without_spending(monkeypatch):
    monkeypatch.setattr(email_cascade.getprospect, "verify_email",
                        lambda e: EmailResult(email=e, status=VALID, provider="getprospect",
                                              billed=True, cost=1.0))
    def _never(*a, **k):
        raise AssertionError("aucun finder ne doit être appelé")
    monkeypatch.setattr(email_cascade.prospeo, "find_email", _never)

    lead = _lead(_site_contacts=_site(("karim.elamrani@acme.ma", "nominatif_lead")))
    email_cascade.resolve_email(lead, is_priority=True)

    assert lead["email"] == "karim.elamrani@acme.ma"
    assert lead["email_status"] == "valid_nominatif"
    assert lead["email_source"] == "website"


def test_a_generic_site_email_is_kept_but_marked_generique(monkeypatch):
    monkeypatch.setattr(email_cascade.getprospect, "verify_email",
                        lambda e: EmailResult(email=e, status=VALID, provider="getprospect",
                                              billed=True, cost=1.0))
    monkeypatch.setattr(email_cascade.prospeo, "find_email",
                        lambda *a: EmailResult(status=NOT_FOUND, provider="prospeo"))
    monkeypatch.setattr(email_cascade.getprospect, "find_email",
                        lambda *a: EmailResult(status=NOT_FOUND, provider="getprospect"))
    monkeypatch.setattr(email_cascade.hunter, "find_email",
                        lambda *a: EmailResult(status=NOT_FOUND, provider="hunter"))

    lead = _lead(_site_contacts=_site(("contact@acme.ma", "generique")))
    email_cascade.resolve_email(lead, is_priority=True)
    assert lead["email"] == "contact@acme.ma"
    assert lead["email_status"] == "valid_generique"


def test_a_webmail_on_the_site_is_never_used_as_the_company_address(monkeypatch):
    monkeypatch.setattr(email_cascade.prospeo, "find_email",
                        lambda *a: EmailResult(status=NOT_FOUND, provider="prospeo"))
    monkeypatch.setattr(email_cascade.getprospect, "find_email",
                        lambda *a: EmailResult(status=NOT_FOUND, provider="getprospect"))
    monkeypatch.setattr(email_cascade.hunter, "find_email",
                        lambda *a: EmailResult(status=NOT_FOUND, provider="hunter"))
    monkeypatch.setattr(email_cascade.getprospect, "verify_email",
                        lambda e: EmailResult(email=e, status=NOT_FOUND, provider="getprospect",
                                              billed=True, cost=1.0))

    lead = _lead(_site_contacts=_site(("karim@gmail.com", "webmail")))
    email_cascade.resolve_email(lead, is_priority=True)
    assert lead["email_status"] == "not_found"


# ── b/c. Pattern et vérification ──────────────────────────────────────────────

def test_a_pattern_candidate_is_verified_and_kept(monkeypatch):
    seen = []

    def _verify(email):
        seen.append(email)
        status = VALID if email == "kelamrani@acme.ma" else NOT_FOUND
        return EmailResult(email=email, status=status, provider="getprospect",
                           billed=True, cost=1.0)

    monkeypatch.setattr(email_cascade.getprospect, "verify_email", _verify)
    lead = _lead()
    email_cascade.resolve_email(lead, is_priority=True)

    assert lead["email"] == "kelamrani@acme.ma"
    assert lead["email_source"] == "pattern_verified"
    assert seen == ["karim.elamrani@acme.ma", "kelamrani@acme.ma"], "arrêt au premier valid"


def test_unknown_moves_to_the_next_candidate_rather_than_stopping(monkeypatch):
    def _verify(email):
        status = UNKNOWN if email == "karim.elamrani@acme.ma" else VALID
        return EmailResult(email=email, status=status, provider="getprospect",
                           billed=True, cost=1.0)

    monkeypatch.setattr(email_cascade.getprospect, "verify_email", _verify)
    lead = _lead()
    email_cascade.resolve_email(lead, is_priority=True)
    assert lead["email"] == "kelamrani@acme.ma"


def test_hunter_verifies_only_after_getprospect(monkeypatch):
    """Décision 7: GetProspect's verification quota serves nothing else,
    Hunter's is shared with its searches."""
    order = []
    monkeypatch.setattr(email_cascade.getprospect, "verify_email",
                        lambda e: order.append("getprospect") or
                        EmailResult(email=e, status=UNKNOWN, provider="getprospect",
                                    billed=True, cost=1.0))
    monkeypatch.setattr(email_cascade.hunter, "verify_email",
                        lambda e: order.append("hunter") or
                        EmailResult(email=e, status=VALID, provider="hunter",
                                    billed=True, cost=0.5))
    lead = _lead()
    email_cascade.resolve_email(lead, is_priority=True)
    assert order[0] == "getprospect"
    assert "hunter" in order


def test_a_domain_without_mx_skips_pattern_generation(monkeypatch):
    monkeypatch.setattr(email_cascade.domain_intel, "lookup_mx",
                        lambda d: email_cascade.domain_intel.MxInfo(False, None))
    def _never(*a, **k):
        raise AssertionError("pas de MX = pas de vérification")
    monkeypatch.setattr(email_cascade.getprospect, "verify_email", _never)
    monkeypatch.setattr(email_cascade.prospeo, "find_email",
                        lambda *a: EmailResult(status=NOT_FOUND, provider="prospeo"))
    monkeypatch.setattr(email_cascade.getprospect, "find_email",
                        lambda *a: EmailResult(status=NOT_FOUND, provider="getprospect"))
    monkeypatch.setattr(email_cascade.hunter, "find_email",
                        lambda *a: EmailResult(status=NOT_FOUND, provider="hunter"))

    lead = _lead()
    email_cascade.resolve_email(lead, is_priority=True)
    assert lead["email_status"] == "not_found"


def test_a_catch_all_domain_spends_nothing_and_reports_catch_all(monkeypatch):
    """Verifying against a domain that accepts everything buys no information."""
    monkeypatch.setattr(email_cascade.domain_intel, "is_catch_all", lambda d, fn: True)
    def _never(*a, **k):
        raise AssertionError("un domaine catch-all ne se vérifie pas")
    monkeypatch.setattr(email_cascade.getprospect, "verify_email", _never)
    monkeypatch.setattr(email_cascade.hunter, "verify_email", _never)

    lead = _lead()
    email_cascade.resolve_email(lead, is_priority=True)
    assert lead["email_status"] == "catch_all"
    assert lead["domain_catch_all"] is True
    assert lead["email"] == "karim.elamrani@acme.ma"


def test_the_company_format_is_inferred_from_a_colleague(monkeypatch):
    """One nominatif_autre on the site collapses three verifications to one."""
    seen = []
    monkeypatch.setattr(email_cascade.getprospect, "verify_email",
                        lambda e: seen.append(e) or
                        EmailResult(email=e, status=VALID, provider="getprospect",
                                    billed=True, cost=1.0))
    lead = _lead(_site_contacts=_site(("s.bennani@acme.ma", "nominatif_autre")))
    lead["_site_colleague"] = {"email": "s.bennani@acme.ma",
                               "first_name": "Sara", "last_name": "Bennani"}
    email_cascade.resolve_email(lead, is_priority=True)
    assert seen == ["k.elamrani@acme.ma"]


# ── d. Finders ────────────────────────────────────────────────────────────────

def test_finders_run_in_order_and_stop_at_the_first_hit(monkeypatch):
    calls = []
    monkeypatch.setattr(email_cascade.getprospect, "verify_email",
                        lambda e: EmailResult(email=e, status=NOT_FOUND,
                                              provider="getprospect", billed=True, cost=1.0))
    monkeypatch.setattr(email_cascade.hunter, "verify_email",
                        lambda e: EmailResult(email=e, status=NOT_FOUND,
                                              provider="hunter", billed=True, cost=0.5))
    monkeypatch.setattr(email_cascade.prospeo, "find_email",
                        lambda *a: calls.append("prospeo") or
                        EmailResult(status=NOT_FOUND, provider="prospeo"))
    monkeypatch.setattr(email_cascade.getprospect, "find_email",
                        lambda *a: calls.append("getprospect") or
                        EmailResult(email="k@acme.ma", status=VALID,
                                    provider="getprospect", billed=True, cost=1.0))
    monkeypatch.setattr(email_cascade.hunter, "find_email",
                        lambda *a: calls.append("hunter") or
                        EmailResult(status=NOT_FOUND, provider="hunter"))

    lead = _lead()
    email_cascade.resolve_email(lead, is_priority=True)
    assert calls == ["prospeo", "getprospect"], "Hunter n'est jamais atteint"
    assert lead["email_source"] == "getprospect"


def test_a_non_priority_lead_never_reaches_the_finders(monkeypatch):
    """Finder credits go to the top of the prescore queue (§7)."""
    monkeypatch.setattr(email_cascade.getprospect, "verify_email",
                        lambda e: EmailResult(email=e, status=NOT_FOUND,
                                              provider="getprospect", billed=True, cost=1.0))
    def _never(*a, **k):
        raise AssertionError("un lead non prioritaire ne consomme pas de crédit finder")
    monkeypatch.setattr(email_cascade.prospeo, "find_email", _never)

    lead = _lead()
    email_cascade.resolve_email(lead, is_priority=False)
    assert lead["email_status"] == "not_found"


def test_a_finder_returning_another_domain_is_flagged(monkeypatch):
    monkeypatch.setattr(email_cascade.getprospect, "verify_email",
                        lambda e: EmailResult(email=e, status=NOT_FOUND,
                                              provider="getprospect", billed=True, cost=1.0))
    monkeypatch.setattr(email_cascade.prospeo, "find_email",
                        lambda *a: EmailResult(email="karim@autre.ma", status=VALID,
                                               provider="prospeo", billed=True, cost=1.0,
                                               domain_mismatch=True))
    lead = _lead()
    email_cascade.resolve_email(lead, is_priority=True)
    assert lead["domain_mismatch"] is True


# ── e. Quota ──────────────────────────────────────────────────────────────────

def test_an_exhausted_quota_everywhere_yields_pending_quota(monkeypatch):
    """The lead is not discarded: it goes back in the queue for next month."""
    for provider in ("prospeo", "getprospect", "hunter", "getprospect_verify"):
        quota_db.sync_remaining(provider, 0.0, "2026-10-01")

    def _never(*a, **k):
        raise AssertionError("aucun appel ne part sans quota")
    monkeypatch.setattr(email_cascade.prospeo, "find_email", _never)
    monkeypatch.setattr(email_cascade.getprospect, "verify_email", _never)

    lead = _lead()
    email_cascade.resolve_email(lead, is_priority=True)
    assert lead["email_status"] == "pending_quota"
    assert lead.get("email") is None


def test_a_provider_raising_quota_exhausted_falls_through_to_the_next(monkeypatch):
    monkeypatch.setattr(email_cascade.getprospect, "verify_email",
                        lambda e: EmailResult(email=e, status=NOT_FOUND,
                                              provider="getprospect", billed=True, cost=1.0))
    def _boom(*a, **k):
        raise QuotaExhausted("prospeo: INSUFFICIENT_CREDITS")
    monkeypatch.setattr(email_cascade.prospeo, "find_email", _boom)
    monkeypatch.setattr(email_cascade.getprospect, "find_email",
                        lambda *a: EmailResult(email="k@acme.ma", status=VALID,
                                               provider="getprospect", billed=True, cost=1.0))
    lead = _lead()
    email_cascade.resolve_email(lead, is_priority=True)
    assert lead["email_source"] == "getprospect"


def test_the_cache_short_circuits_a_repeat_lookup(monkeypatch):
    quota_db.cache_store("Karim", "El Amrani", "acme.ma", "prospeo",
                         {"email": "karim@acme.ma", "status": "valid"})
    monkeypatch.setattr(email_cascade.getprospect, "verify_email",
                        lambda e: EmailResult(email=e, status=NOT_FOUND,
                                              provider="getprospect", billed=True, cost=1.0))
    def _never(*a, **k):
        raise AssertionError("le cache doit éviter l'appel réseau")
    monkeypatch.setattr(email_cascade.prospeo, "find_email", _never)

    lead = _lead()
    email_cascade.resolve_email(lead, is_priority=True)
    assert lead["email"] == "karim@acme.ma"
```

- [ ] **Step 2 : Lancer les tests pour vérifier qu'ils échouent**

Run : `python -m pytest tests/test_email_cascade.py -v`
Expected : FAIL — `ModuleNotFoundError: No module named 'enrichers.email_cascade'`.

- [ ] **Step 3 : Implémenter**

Créer `enrichers/email_cascade.py` :

```python
"""
Step 5 — Email acquisition cascade (replaces Dropcontact).

Ordered cheapest-first and stopping at the first success, because the whole
month's budget is 50 to 100 lookups:

  a. an address the company already published on its own site  — free
  b. a candidate generated from the company's format           — free to build
  c. verification of that candidate                            — 0.5 to 1 credit
  d. a finder, priority leads only                             — 1 credit
  e. nothing left to spend                                     — pending_quota

Every branch records what it cost so api/quota_db.py only ever decrements on
a result the provider actually billed.
"""
import logging
from typing import Callable, Optional
from urllib.parse import urlparse

from api import quota_db
from api.provider_status import StepOutcome
from enrichers import domain_intel, email_patterns
from enrichers.providers import getprospect, hunter, prospeo
from enrichers.providers.base import ACCEPT_ALL, NOT_FOUND, UNKNOWN, VALID, EmailResult
from enrichers.retry import AuthError, QuotaExhausted, RateLimited, RetryableRemoteFailure

logger = logging.getLogger(__name__)

# Décision 7: GetProspect first — its verification quota (100/month) serves
# nothing else, while Hunter draws on a unified pool shared with its searches.
VERIFIER_ORDER = (
    ("getprospect_verify", getprospect.verify_email, getprospect.COST_PER_VERIFICATION),
    ("hunter", hunter.verify_email, hunter.COST_PER_VERIFICATION),
)

FINDER_ORDER = (
    ("prospeo", prospeo.find_email, prospeo.COST_PER_EMAIL),
    ("getprospect", getprospect.find_email, getprospect.COST_PER_EMAIL),
    ("hunter", hunter.find_email, hunter.COST_PER_EMAIL),
)

EMAIL_STATUSES = frozenset({
    "valid_nominatif", "valid_generique", "catch_all",
    "unverified", "not_found", "pending_quota", "provider_failure",
})


def _domain_of(lead: dict) -> str:
    website = lead.get("website") or ""
    return urlparse(website).netloc.lower().removeprefix("www.")


def _set(lead: dict, *, email=None, status="not_found", source=None,
         email_type=None, mismatch=False) -> None:
    lead["email"] = email
    lead["email_status"] = status
    lead["email_source"] = source
    lead["email_type"] = email_type
    lead["domain_mismatch"] = mismatch


def _call(provider: str, fn: Callable, *args) -> Optional[EmailResult]:
    """Run one provider call, charging the local counter only when billed.

    A quota or auth failure returns None so the caller moves to the next
    provider: since Dropcontact was removed, no single provider is allowed to
    end the cascade on its own.
    """
    try:
        result = fn(*args)
    except (QuotaExhausted, AuthError) as exc:
        logger.warning(f"{provider} unavailable: {exc}")
        return None
    except (RateLimited, RetryableRemoteFailure) as exc:
        logger.warning(f"{provider} failed: {exc}")
        return None
    if result is not None and result.billed:
        quota_db.record_spend(provider, cost=result.cost, billed=True)
    return result


def _verify(candidate: str) -> Optional[EmailResult]:
    """Try each verifier in order until one gives a usable verdict."""
    for provider, fn, cost in VERIFIER_ORDER:
        if not quota_db.can_spend(provider, cost):
            continue
        result = _call(provider, fn, candidate)
        if result is not None and result.status in (VALID, ACCEPT_ALL, NOT_FOUND):
            return result
    return None


def resolve_email(lead: dict, is_priority: bool, registry=None) -> dict:
    """Run the cascade for one lead, writing its outcome onto the lead dict."""
    domain = _domain_of(lead)
    first = lead.get("first_name") or ""
    last = lead.get("last_name") or ""
    contacts = lead.get("_site_contacts") or {}
    site_emails = contacts.get("emails") or []

    mx = domain_intel.lookup_mx(domain)
    lead["domain_mx_provider"] = mx.provider
    lead["domain_catch_all"] = None
    _set(lead)

    # ── a. An address the company published itself ────────────────────────────
    for kind, status in (("nominatif_lead", "valid_nominatif"),
                         ("generique", "valid_generique")):
        found = next((e for e in site_emails if e.kind == kind), None)
        if found:
            _set(lead, email=found.value, status=status, source="website",
                 email_type=kind)
            lead["contact_source_url"] = found.source_url
            return lead

    if not domain or not mx.has_mx:
        # No MX means the domain receives no mail at all: generating a pattern
        # would spend a verification on an address that cannot exist.
        return _finders(lead, first, last, domain, is_priority, registry)

    # ── b. Candidates, collapsed to one when a colleague reveals the format ──
    colleague = lead.get("_site_colleague") or {}
    candidates = email_patterns.generate(
        first, last, domain,
        known_email=colleague.get("email"),
        known_first=colleague.get("first_name"),
        known_last=colleague.get("last_name"),
    )
    if not candidates:
        return _finders(lead, first, last, domain, is_priority, registry)

    # ── c. Verification, unless the domain accepts everything ────────────────
    catch_all = domain_intel.is_catch_all(domain, _probe_verifier())
    lead["domain_catch_all"] = catch_all
    if catch_all is True:
        # Verifying here buys no information: the domain says yes to anything.
        _set(lead, email=candidates[0], status="catch_all",
             source="pattern_verified", email_type="nominatif_lead")
        return lead

    for candidate in candidates:
        result = _verify(candidate)
        if result is None:
            break
        if result.status == VALID:
            _set(lead, email=candidate, status="valid_nominatif",
                 source="pattern_verified", email_type="nominatif_lead")
            return lead
        if result.status == ACCEPT_ALL:
            _set(lead, email=candidate, status="catch_all",
                 source="pattern_verified", email_type="nominatif_lead")
            return lead

    return _finders(lead, first, last, domain, is_priority, registry)


def _probe_verifier() -> Callable[[str], str]:
    """Adapter handing domain_intel a plain status string."""
    def _probe(email: str) -> str:
        result = _verify(email)
        return result.status if result is not None else "unknown"
    return _probe


def _finders(lead: dict, first: str, last: str, domain: str,
             is_priority: bool, registry=None) -> dict:
    """Step d, then e. Finder credits are reserved for priority leads (§7)."""
    if not is_priority or not domain:
        return lead

    quota_seen = False
    for provider, fn, cost in FINDER_ORDER:
        cached = quota_db.cache_lookup(first, last, domain, provider)
        if cached is not None:
            payload = cached["result"]
            if payload and payload.get("email"):
                _set(lead, email=payload["email"], status="valid_nominatif",
                     source=provider, email_type="nominatif_lead")
                return lead
            continue

        if not quota_db.can_spend(provider, cost):
            quota_seen = True
            continue

        result = _call(provider, fn, first, last, domain)
        if result is None:
            quota_seen = True
            continue

        quota_db.cache_store(
            first, last, domain, provider,
            {"email": result.email, "status": result.status} if result.email else None,
        )
        if registry is not None:
            registry.record(StepOutcome(provider, "ok", None, 1 if result.email else 0))
        if result.email and result.status in (VALID, ACCEPT_ALL):
            _set(lead, email=result.email,
                 status="valid_nominatif" if result.status == VALID else "catch_all",
                 source=provider, email_type="nominatif_lead",
                 mismatch=result.domain_mismatch)
            return lead

    if quota_seen and not lead.get("email"):
        # Not discarded — requeued at the head of the first batch after reset.
        _set(lead, status="pending_quota")
    return lead
```

- [ ] **Step 4 : Lancer les tests pour vérifier qu'ils passent**

Run : `python -m pytest tests/test_email_cascade.py -v`
Expected : PASS.

- [ ] **Step 5 : Commit**

```bash
git add enrichers/email_cascade.py tests/test_email_cascade.py
git commit -m "feat: cascade email site → pattern → vérification → finders"
```

---

### Task 17 : Colonnes employés et secteur dans l'extraction Apollo

**Files:**
- Modify: `scrapers/apollo_scraper.py` (`_JS_EXTRACT`, stratégie 1)
- Test: `tests/test_apollo_extraction.py` (créé)

**Interfaces:**
- Consomme : rien.
- Produit : deux clés supplémentaires sur chaque lead scrapé — `employee_count: int | None` et `apollo_industry: str | None`. `processors/prescore.py` (Task 18) les consomme.

**Contexte.** §7 du spec. Ces colonnes ne sont présentes que si l'opérateur les a affichées dans sa vue Apollo — l'absence est normale et ne doit jamais bloquer (décision 3).

- [ ] **Step 1 : Écrire le test qui échoue**

Créer `tests/test_apollo_extraction.py`. Le bloc `_JS_EXTRACT` étant du JavaScript exécuté dans le navigateur, on teste la fonction de normalisation Python qui le suit :

```python
import pytest

from scrapers.apollo_scraper import parse_employee_count


@pytest.mark.parametrize("raw,expected", [
    ("45", 45), ("1,250", 1250), ("1 250", 1250),
    ("11-50", 30), ("50-200", 125), ("1001-5000", 3000),
    ("11 - 50", 30), ("10,001+", 10001), ("5000+", 5000),
])
def test_headcount_formats_are_parsed(raw, expected):
    assert parse_employee_count(raw) == expected


@pytest.mark.parametrize("raw", ["", None, "—", "N/A", "unknown", "Access", "abc"])
def test_unreadable_headcount_is_none_not_zero(raw):
    """Zero would read as a micro-company and skew the prescore downward;
    None correctly means "Apollo did not show this column"."""
    assert parse_employee_count(raw) is None


def test_a_range_is_folded_to_its_rounded_midpoint():
    """Same convention as enrichers/fact_extractor.py, so a lead scored from
    Apollo and the same lead scored from sourced facts land on one scale."""
    assert parse_employee_count("11-50") == 30
```

- [ ] **Step 2 : Lancer le test pour vérifier qu'il échoue**

Run : `python -m pytest tests/test_apollo_extraction.py -v`
Expected : FAIL — `ImportError: cannot import name 'parse_employee_count'`.

- [ ] **Step 3 : Implémenter la normalisation Python**

Ajouter à `scrapers/apollo_scraper.py` :

```python
import re

_RANGE_RE = re.compile(r"^\s*(\d[\d\s,]*)\s*-\s*(\d[\d\s,]*)\s*$")
_PLUS_RE = re.compile(r"^\s*(\d[\d\s,]*)\s*\+\s*$")
_PLAIN_RE = re.compile(r"^\s*(\d[\d\s,]*)\s*$")


def _digits(value: str) -> int:
    return int(re.sub(r"[^\d]", "", value))


def parse_employee_count(raw) -> int | None:
    """Normalise Apollo's headcount cell to a single integer, or None.

    Ranges fold to their rounded-down midpoint, matching the convention the
    fact extractor already applies to Perplexity's "11-50 employees", so a
    lead prescored from Apollo and later scored from sourced facts sit on the
    same scale. None means the column was absent or unreadable — never 0,
    which would read as a micro-company and push the lead down the queue for
    a value we never had.
    """
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None

    match = _RANGE_RE.match(text)
    if match:
        low, high = _digits(match.group(1)), _digits(match.group(2))
        return (low + high) // 2

    match = _PLUS_RE.match(text)
    if match:
        return _digits(match.group(1))

    match = _PLAIN_RE.match(text)
    if match:
        return _digits(match.group(1))

    return None
```

- [ ] **Step 4 : Étendre le bloc JavaScript**

Dans `_JS_EXTRACT`, à l'intérieur du bloc `if (headers.length > 0)`, ajouter après `lead.job_title` :

```javascript
                lead.employee_count_raw = findByHeader('employee', 'employees', 'size', 'headcount', 'effectif');
                lead.apollo_industry    = findByHeader('industry', 'sector', 'secteur');
```

Ajouter les deux clés à l'initialisation de `lead` (`employee_count_raw: ''`, `apollo_industry: ''`) pour que leur absence reste une chaîne vide plutôt qu'un `undefined`.

- [ ] **Step 5 : Normaliser après extraction**

Dans `_scrape_page`, après `leads = await page.evaluate(_JS_EXTRACT)` :

```python
        for lead in leads:
            lead["employee_count"] = parse_employee_count(lead.pop("employee_count_raw", None))
            lead["apollo_industry"] = (lead.get("apollo_industry") or "").strip() or None
```

- [ ] **Step 6 : Lancer les tests**

Run : `python -m pytest tests/test_apollo_extraction.py -v`
Expected : PASS.

- [ ] **Step 7 : Commit**

```bash
git add scrapers/apollo_scraper.py tests/test_apollo_extraction.py
git commit -m "feat: récupérer les colonnes effectif et secteur depuis la vue Apollo"
```

---

### Task 18 : Pré-score ICP (passe 1)

**Files:**
- Create: `processors/prescore.py`, `tests/test_prescore.py`

**Interfaces:**
- Consomme : `processors.icp_rules.load_rules`, `IcpRules.canonical_sector`, `country_zone`.
- Produit :
  - `compute_prescore(lead: dict, rules: IcpRules | None = None) -> int` — 0 à 100
  - `rank_for_spending(leads: list[dict], rules=None) -> list[dict]` — copie triée par `prescore` décroissant
  - `apply_prescores(leads: list[dict], rules=None) -> list[dict]` — pose `lead["prescore"]` en place

**Contexte.** Décision 3 : **aucune disqualification**. Décision 5 : c'est ce score qui ordonne la file de dépense, et lui seul. Il n'alimente jamais `icp_tier` ni `icp_score`, et n'est jamais lu comme un verdict.

- [ ] **Step 1 : Écrire les tests qui échouent**

Créer `tests/test_prescore.py` :

```python
import pytest

from processors.icp_rules import load_rules
from processors.prescore import apply_prescores, compute_prescore, rank_for_spending


@pytest.fixture
def rules():
    return load_rules()


def _lead(**over):
    base = {"first_name": "Karim", "last_name": "El Amrani",
            "company": "Acme", "location": "Casablanca, Maroc",
            "employee_count": 45, "apollo_industry": "e-commerce"}
    base.update(over)
    return base


def test_a_perfect_lead_scores_high(rules):
    assert compute_prescore(_lead(), rules) >= 70


def test_a_missing_field_costs_its_axis_but_never_disqualifies(rules):
    """Décision 3: the prescore only sorts. A lead Apollo described poorly
    loses its place in the queue, never its existence."""
    score = compute_prescore(_lead(employee_count=None), rules)
    assert 0 < score < compute_prescore(_lead(), rules)


def test_every_field_missing_scores_zero_and_still_returns_a_lead(rules):
    lead = _lead(location=None, employee_count=None, apollo_industry=None)
    assert compute_prescore(lead, rules) == 0


def test_an_excluded_sector_scores_low_but_is_not_removed(rules):
    """The sourced pass may still rehabilitate it: Apollo's industry label is
    not evidence, and a verdict we cannot substantiate is not a verdict."""
    lead = _lead(apollo_industry="industrie lourde")
    score = compute_prescore(lead, rules)
    assert score >= 0
    assert "disqualified" not in str(lead.get("icp_tier", ""))


def test_a_huge_company_scores_low_but_is_not_removed(rules):
    assert compute_prescore(_lead(employee_count=50000), rules) >= 0


def test_the_prescore_never_writes_icp_fields(rules):
    """Contamination guard: the sourced score is the only verdict, and an
    unsourced prescore leaking into icp_tier would restore exactly the
    "score inversely correlated with knowledge" problem the 2026-08 rework
    removed."""
    lead = _lead()
    apply_prescores([lead], rules)
    assert lead["prescore"] > 0
    assert "icp_score" not in lead
    assert "icp_tier" not in lead
    assert "disqualification_reason" not in lead


# ── Géographie (décision 2) ───────────────────────────────────────────────────

@pytest.mark.parametrize("location,expected_zone_points", [
    ("Casablanca, Maroc", 100), ("Dakar, Sénégal", 90),
    ("Lagos, Nigeria", 70), ("Paris, France", 20),
    ("Bruxelles, Belgique", 10), ("Montréal, Canada", 10),
])
def test_zone_points_follow_the_validated_geography(rules, location, expected_zone_points):
    lead = _lead(location=location, employee_count=None, apollo_industry=None)
    # Localisation weighs 20% and is the only axis scoring here.
    assert compute_prescore(lead, rules) == round(expected_zone_points * 0.20)


def test_an_unrecognized_country_scores_zero_on_its_axis(rules):
    lead = _lead(location="Zzz", employee_count=None, apollo_industry=None)
    assert compute_prescore(lead, rules) == 0


# ── Tri ───────────────────────────────────────────────────────────────────────

def test_ranking_is_descending_and_stable(rules):
    leads = [
        _lead(company="Faible", location="Paris, France", employee_count=None,
              apollo_industry=None),
        _lead(company="Fort", location="Casablanca, Maroc"),
        _lead(company="Moyen", location="Dakar, Sénégal", employee_count=None),
    ]
    ranked = rank_for_spending(leads, rules)
    assert [l["company"] for l in ranked] == ["Fort", "Moyen", "Faible"]


def test_ranking_does_not_mutate_the_input_order(rules):
    leads = [_lead(company="A", location="Paris, France"),
             _lead(company="B", location="Casablanca, Maroc")]
    rank_for_spending(leads, rules)
    assert [l["company"] for l in leads] == ["A", "B"]
```

- [ ] **Step 2 : Lancer les tests pour vérifier qu'ils échouent**

Run : `python -m pytest tests/test_prescore.py -v`
Expected : FAIL — `ModuleNotFoundError: No module named 'processors.prescore'`.

- [ ] **Step 3 : Implémenter**

Créer `processors/prescore.py` :

```python
"""
Pass 1 — free, unsourced ICP prescore.

This exists to answer one question: of the leads we have, which ones deserve
the month's 50 to 100 paid lookups and the Perplexity/Claude enrichment. It
answers it from what Apollo displayed and nothing else.

Two rules make it safe to build a score on unsourced data:

  1. It never disqualifies (décision 3). A missing or wrong Apollo cell costs
     a lead its place in the queue, never its existence — the sourced pass
     can still rehabilitate it.
  2. It never touches icp_score, icp_tier or disqualification_reason. Those
     belong to processors/icp_scorer.py, which reads validated facts. Letting
     an unsourced number reach them would restore exactly the inversion the
     2026-08 rework removed: an unknown company scoring well on generous
     defaults, a known one scoring badly on real criteria.
"""
import logging
from typing import Optional

from processors.icp_rules import IcpRules, load_rules

logger = logging.getLogger(__name__)

# Only the three axes we can populate without spending anything. "signaux"
# (40% of the real score) needs Perplexity, so it is absent here — which is
# why a prescore is never comparable to an icp_score and never exported as one.
PRESCORE_AXES = ("secteur", "taille", "localisation")


def _sector_points(lead: dict, rules: IcpRules) -> int:
    label = lead.get("apollo_industry")
    if not label:
        return 0
    canonical = rules.canonical_sector(str(label))
    if canonical is not None and canonical in rules.high_value_sectors:
        return rules.sector_points.get("high_value", 100)
    if canonical is not None and canonical in rules.excluded_sectors:
        # Scored low rather than disqualified: Apollo's label is not evidence.
        return 0
    return rules.sector_points.get("other", 50)


def _size_points(lead: dict, rules: IcpRules) -> int:
    headcount = lead.get("employee_count")
    if not isinstance(headcount, (int, float)) or headcount <= 0:
        return 0
    for band in rules.size_bands:
        if band["min"] <= headcount <= band["max"]:
            return band["points"]
    return 0


def _location_points(lead: dict, rules: IcpRules) -> int:
    zone = rules.country_zone(str(lead.get("location") or ""))
    if zone is None:
        return 0
    return rules.zone_points.get(zone, 0)


def compute_prescore(lead: dict, rules: Optional[IcpRules] = None) -> int:
    """Weighted 0-100 score on the three free axes. Never raises."""
    active = rules or load_rules()
    points = {
        "secteur": _sector_points(lead, active),
        "taille": _size_points(lead, active),
        "localisation": _location_points(lead, active),
    }
    return round(sum(points[axis] * active.weights[axis] for axis in PRESCORE_AXES))


def apply_prescores(leads: list[dict], rules: Optional[IcpRules] = None) -> list[dict]:
    """Write lead["prescore"] in place. Writes nothing else."""
    active = rules or load_rules()
    for lead in leads:
        lead["prescore"] = compute_prescore(lead, active)
    return leads


def rank_for_spending(leads: list[dict], rules: Optional[IcpRules] = None) -> list[dict]:
    """Return a new list ordered by prescore descending, input order preserved.

    Python's sort is stable, so leads tied on prescore keep their scrape order
    rather than being reshuffled between runs.
    """
    active = rules or load_rules()
    scored = apply_prescores(list(leads), active)
    return sorted(scored, key=lambda l: l.get("prescore", 0), reverse=True)
```

- [ ] **Step 4 : Lancer les tests pour vérifier qu'ils passent**

Run : `python -m pytest tests/test_prescore.py -v`
Expected : PASS — l'intégralité du fichier, tests de géographie compris.

> **Prérequis.** Task 19 doit être livrée avant celle-ci (ruling de pré-vol du 2026-09-25) : les tests `test_zone_points_follow_the_validated_geography` et `test_an_unrecognized_country_scores_zero_on_its_axis` lisent la zone `reste_afrique` et le barème Europe que Task 19 installe dans `config/icp_rules.json`.

- [ ] **Step 5 : Commit**

```bash
git add processors/prescore.py tests/test_prescore.py
git commit -m "feat: pré-score ICP sur données gratuites, sans disqualification"
```

---

### Task 19 : Géographie ICP — Afrique élargie, Europe secondaire

**Files:**
- Modify: `config/icp_rules.json`
- Test: `tests/test_icp_rules.py`, `tests/test_icp_scorer.py`, `tests/test_prescore.py`

**Interfaces:**
- Consomme : rien (fichier de données).
- Produit : zone `reste_afrique`, repondération de `zone_points`. `processors/prescore.py` (Task 18) et `processors/icp_scorer.py` lisent les nouvelles valeurs sans modification de code.

**Contexte.** Décision 2. Le barème devient Maroc 100, Afrique francophone 90, reste de l'Afrique 70, France 20, Belgique/Suisse/Luxembourg/Canada 10. **Plus aucune disqualification géographique sur l'Europe** : seuls les pays hors de toutes les zones sont disqualifiés par `_disqualification_reason`, et uniquement sur fait sourcé.

- [ ] **Step 1 : Écrire les tests qui échouent**

Ajouter à `tests/test_icp_rules.py` :

```python
import pytest

from processors.icp_rules import load_rules


@pytest.fixture
def rules():
    return load_rules()


@pytest.mark.parametrize("country,zone", [
    ("Maroc", "maroc"), ("Morocco", "maroc"), ("Casablanca", "maroc"),
    ("Sénégal", "afrique_francophone"), ("Côte d'Ivoire", "afrique_francophone"),
    ("Nigeria", "reste_afrique"), ("Ghana", "reste_afrique"),
    ("Kenya", "reste_afrique"), ("Égypte", "reste_afrique"),
    ("Afrique du Sud", "reste_afrique"), ("Ethiopie", "reste_afrique"),
    ("France", "france"), ("Belgique", "francophonie_elargie"),
    ("Canada", "francophonie_elargie"),
])
def test_countries_land_in_the_expected_zone(rules, country, zone):
    assert rules.country_zone(country) == zone


@pytest.mark.parametrize("zone,points", [
    ("maroc", 100), ("afrique_francophone", 90), ("reste_afrique", 70),
    ("france", 20), ("francophonie_elargie", 10),
])
def test_zone_points_match_the_validated_scale(rules, zone, points):
    assert rules.zone_points[zone] == points


def test_europe_is_no_longer_out_of_zone(rules):
    """Décision 2: Europe stays relevant but secondary. It must resolve to a
    zone — an unrecognised country is what triggers disqualification."""
    for country in ("France", "Belgique", "Suisse", "Luxembourg", "Canada"):
        assert rules.country_zone(country) is not None


def test_a_country_outside_every_zone_still_resolves_to_none(rules):
    assert rules.country_zone("Japon") is None
    assert rules.country_zone("Zzz") is None


def test_the_african_floor_stays_above_the_european_ceiling(rules):
    """The client targets Africa first: no European zone may outrank the
    weakest African one."""
    african = min(rules.zone_points[z] for z in
                  ("maroc", "afrique_francophone", "reste_afrique"))
    european = max(rules.zone_points[z] for z in ("france", "francophonie_elargie"))
    assert african > european
```

Ajouter à `tests/test_icp_scorer.py` :

```python
from datetime import date

from processors.icp_rules import load_rules
from processors.icp_scorer import score_lead


def _facts(country):
    return {
        "identite_confirmee": True,
        "pays": {"value": country, "source": "website"},
        "secteur": {"value": "e-commerce", "source": "website"},
        "effectif": {"value": 45, "source": "perplexity"},
        "est_concurrent": None,
        "maturite_digitale": {"value": 3, "source": "perplexity"},
        "signaux": [{"type": "recrutement", "date": "2026-08", "source": "perplexity",
                     "citation": "x"}],
    }


def test_a_french_lead_is_scored_not_disqualified():
    result = score_lead(_facts("France"), "sufficient", load_rules(), date(2026, 9, 25))
    assert result.icp_tier != "disqualified"
    assert result.disqualification_reason is None


def test_a_nigerian_lead_scores_on_the_reste_afrique_zone():
    result = score_lead(_facts("Nigeria"), "sufficient", load_rules(), date(2026, 9, 25))
    assert result.icp_tier in ("hot", "warm")


def test_a_country_outside_every_zone_is_still_disqualified():
    result = score_lead(_facts("Japon"), "sufficient", load_rules(), date(2026, 9, 25))
    assert result.icp_tier == "disqualified"
    assert "hors zone" in result.disqualification_reason


def test_a_moroccan_lead_outranks_an_identical_french_one():
    rules, today = load_rules(), date(2026, 9, 25)
    assert (score_lead(_facts("Maroc"), "sufficient", rules, today).icp_score
            > score_lead(_facts("France"), "sufficient", rules, today).icp_score)
```

- [ ] **Step 2 : Lancer les tests pour vérifier qu'ils échouent**

Run : `python -m pytest tests/test_icp_rules.py tests/test_icp_scorer.py -v`
Expected : FAIL — `reste_afrique` n'existe pas, `zone_points["france"]` vaut encore 80.

- [ ] **Step 3 : Étendre `country_aliases`**

Dans `config/icp_rules.json`, ajouter les pays africains non encore listés au bloc `country_aliases` :

```json
    "Éthiopie": ["ethiopie", "ethiopia", "addis abeba", "addis ababa"],
    "Tanzanie": ["tanzania", "tanzanie", "dar es salaam", "dodoma"],
    "Ouganda": ["uganda", "ouganda", "kampala"],
    "Rwanda": ["rwanda", "kigali"],
    "Burundi": ["burundi", "bujumbura"],
    "Zambie": ["zambia", "zambie", "lusaka"],
    "Zimbabwe": ["zimbabwe", "harare"],
    "Mozambique": ["mozambique", "maputo"],
    "Angola": ["angola", "luanda"],
    "Namibie": ["namibia", "namibie", "windhoek"],
    "Botswana": ["botswana", "gaborone"],
    "Libye": ["libya", "libye", "tripoli"],
    "Soudan": ["sudan", "soudan", "khartoum"],
    "Somalie": ["somalia", "somalie", "mogadiscio", "mogadishu"],
    "Djibouti": ["djibouti"],
    "Érythrée": ["eritrea", "erythree", "asmara"],
    "Malawi": ["malawi", "lilongwe"],
    "Lesotho": ["lesotho", "maseru"],
    "Eswatini": ["eswatini", "swaziland", "mbabane"],
    "Maurice": ["maurice", "mauritius", "port louis"],
    "Seychelles": ["seychelles", "victoria"],
    "Cap-Vert": ["cap vert", "cabo verde", "cape verde", "praia"],
    "Guinée-Bissau": ["guinee bissau", "guinea bissau", "bissau"],
    "Guinée équatoriale": ["guinee equatoriale", "equatorial guinea", "malabo"],
    "Sierra Leone": ["sierra leone", "freetown"],
    "Liberia": ["liberia", "monrovia"],
    "Gambie": ["gambie", "gambia", "banjul"],
    "Comores": ["comores", "comoros", "moroni"],
    "Sao Tomé-et-Principe": ["sao tome", "sao tome et principe"],
    "Centrafrique": ["centrafrique", "republique centrafricaine",
                     "central african republic", "bangui"],
    "Soudan du Sud": ["soudan du sud", "south sudan", "juba"],
```

- [ ] **Step 4 : Réécrire `zone_countries` et `zone_points`**

```json
  "zone_countries": {
    "maroc": ["Maroc"],
    "afrique_francophone": [
      "Algérie", "Tunisie", "Sénégal", "Côte d'Ivoire", "Cameroun", "Gabon",
      "Bénin", "Burkina Faso", "Mali", "Niger", "Togo", "Guinée", "Congo",
      "RDC", "Madagascar", "Mauritanie", "Tchad", "Centrafrique", "Djibouti",
      "Comores", "Guinée équatoriale"
    ],
    "reste_afrique": [
      "Nigeria", "Ghana", "Kenya", "Égypte", "Afrique du Sud", "Éthiopie",
      "Tanzanie", "Ouganda", "Rwanda", "Burundi", "Zambie", "Zimbabwe",
      "Mozambique", "Angola", "Namibie", "Botswana", "Libye", "Soudan",
      "Somalie", "Érythrée", "Malawi", "Lesotho", "Eswatini", "Maurice",
      "Seychelles", "Cap-Vert", "Guinée-Bissau", "Sierra Leone", "Liberia",
      "Gambie", "Sao Tomé-et-Principe", "Soudan du Sud"
    ],
    "france": ["France"],
    "francophonie_elargie": ["Belgique", "Suisse", "Luxembourg", "Canada"]
  },
  "zone_points": {
    "maroc": 100,
    "afrique_francophone": 90,
    "reste_afrique": 70,
    "france": 20,
    "francophonie_elargie": 10
  },
```

> **Note pour l'exécutant.** Ne pas toucher à `processors/coherence.py`. Son contrôle de contradiction de pays a été retiré le 2026-08-10 avec une consigne explicite de ne pas le réintroduire, et rien ici ne le remet en cause : la géographie est arbitrée par le scorer sur fait sourcé, jamais par la détection de pays dans du texte libre.

- [ ] **Step 5 : Lancer les tests**

Run : `python -m pytest tests/test_icp_rules.py tests/test_icp_scorer.py -v`
Expected : PASS.

> **Ordre d'exécution.** Cette tâche passe **avant** Task 18 (ruling de pré-vol du 2026-09-25) : elle n'a aucune dépendance vers le pré-score, et l'exécuter d'abord évite de committer les tests de géographie de Task 18 à l'état rouge. `tests/test_prescore.py` n'existe pas encore à ce stade — ne pas l'ajouter à la commande.

- [ ] **Step 6 : Commit**

```bash
git add config/icp_rules.json tests/test_icp_rules.py tests/test_icp_scorer.py
git commit -m "feat: zone reste_afrique, Europe repondérée en secondaire"
```

---

### Task 20 : Joignabilité booléenne, retrait du hit score, schéma d'export

**Files:**
- Create: `processors/reachability.py`, `tests/test_reachability.py`
- Modify: `processors/hit_calculator.py`, `lead_schema.py`, `api/models.py`
- Test: `tests/test_hit_calculator.py` (réécrit), `tests/test_lead_schema.py`

**Interfaces:**
- Consomme : les champs posés par `email_cascade` et `phone_extractor`.
- Produit :
  - `REACHABLE_EMAIL_STATUSES: frozenset[str]`
  - `is_reachable(lead: dict) -> bool`
  - `contact_level(lead: dict) -> str` — `"direct" | "indirect" | "aucun" | "indetermine"`
  - `apply_reachability(leads) -> tuple[list, list, list]` → `(reachable, unreachable, pending)`
  `processors/hit_calculator.py` devient un mince adaptateur ; `api/pipeline_runner.py` (Task 22) consomme le triplet.

**Contexte.** Décision 5. Le barème de `hit_calculator.py` disparaît intégralement. Un `pending_quota` n'est **jamais** classé non joignable.

- [ ] **Step 1 : Écrire les tests qui échouent**

Créer `tests/test_reachability.py` :

```python
import pytest

from processors.reachability import apply_reachability, contact_level, is_reachable


def _lead(**over):
    base = {"email": None, "email_status": "not_found", "phone": None,
            "phone_type": None, "whatsapp": False, "linkedin_url": None}
    base.update(over)
    return base


@pytest.mark.parametrize("status", ["valid_nominatif", "valid_generique", "catch_all"])
def test_a_usable_email_makes_a_lead_reachable(status):
    assert is_reachable(_lead(email="k@acme.ma", email_status=status)) is True


@pytest.mark.parametrize("status", ["not_found", "unverified", "provider_failure"])
def test_an_unusable_email_does_not(status):
    assert is_reachable(_lead(email="k@acme.ma", email_status=status)) is False


def test_a_phone_alone_is_enough():
    assert is_reachable(_lead(phone="+212661234567", phone_type="mobile")) is True


def test_a_company_published_whatsapp_link_is_enough():
    assert is_reachable(_lead(whatsapp=True)) is True


def test_linkedin_alone_is_not_a_contact_route():
    """A LinkedIn profile is not a direct route: reaching the person still
    requires a connection request they may never accept."""
    assert is_reachable(_lead(linkedin_url="https://linkedin.com/in/karim")) is False


def test_a_pending_quota_lead_is_neither_reachable_nor_unreachable():
    lead = _lead(email_status="pending_quota")
    assert is_reachable(lead) is False
    assert contact_level(lead) == "indetermine"


@pytest.mark.parametrize("lead,level", [
    (_lead(email="k@acme.ma", email_status="valid_nominatif"), "direct"),
    (_lead(phone="+212661234567", phone_type="mobile"), "direct"),
    (_lead(whatsapp=True), "direct"),
    (_lead(email="contact@acme.ma", email_status="valid_generique"), "indirect"),
    (_lead(phone="+212522123456", phone_type="fixe"), "indirect"),
    (_lead(email="k@acme.ma", email_status="catch_all"), "indirect"),
    (_lead(), "aucun"),
])
def test_contact_level_grades_the_best_available_route(lead, level):
    assert contact_level(lead) == level


def test_the_best_route_wins_over_a_weaker_one():
    lead = _lead(email="contact@acme.ma", email_status="valid_generique",
                 phone="+212661234567", phone_type="mobile")
    assert contact_level(lead) == "direct"


def test_splitting_returns_three_disjoint_groups():
    leads = [
        _lead(email="a@acme.ma", email_status="valid_nominatif"),
        _lead(),
        _lead(email_status="pending_quota"),
    ]
    reachable, unreachable, pending = apply_reachability(leads)
    assert len(reachable) == 1 and len(unreachable) == 1 and len(pending) == 1
    assert leads[0]["reachable"] is True
    assert leads[1]["reachable"] is False
    assert leads[2]["reachable"] is None


def test_a_pending_lead_is_never_placed_in_the_unreachable_group():
    """§6: a pending_quota lead is never classed no-hit — it is requeued."""
    _, unreachable, pending = apply_reachability([_lead(email_status="pending_quota")])
    assert unreachable == []
    assert len(pending) == 1
```

- [ ] **Step 2 : Lancer les tests pour vérifier qu'ils échouent**

Run : `python -m pytest tests/test_reachability.py -v`
Expected : FAIL — `ModuleNotFoundError: No module named 'processors.reachability'`.

- [ ] **Step 3 : Implémenter**

Créer `processors/reachability.py` :

```python
"""
Reachability — a boolean, not a score.

Until 2026-09-25 contact data earned points: an email was worth 40, a phone
20, a LinkedIn 30, and the total gated the expensive steps. That conflated two
unrelated questions — can we reach this person, and is this person worth
reaching — and let a perfectly irrelevant but well-documented lead outrank a
prime target whose email we simply had not found yet.

Relevance is now scored by processors/prescore.py and processors/icp_scorer.py.
Reachability is what remains: a lead either has a route to a human or it does
not. A pending_quota lead has neither answer yet, so it is None — not False.
"""
from typing import Optional

# Email statuses that actually let someone send mail. "unverified" is absent
# on purpose: the legacy "no verification ran, assume it works" fallback was
# removed with the hit score, because assuming is how invented contacts reach
# a CSV that looks exactly like a real one.
REACHABLE_EMAIL_STATUSES = frozenset({"valid_nominatif", "valid_generique", "catch_all"})

_DIRECT_EMAIL_STATUSES = frozenset({"valid_nominatif"})
_PENDING = "pending_quota"


def _has_email(lead: dict) -> bool:
    return bool(lead.get("email")) and lead.get("email_status") in REACHABLE_EMAIL_STATUSES


def is_reachable(lead: dict) -> bool:
    """True when at least one direct route to a human exists.

    LinkedIn is deliberately excluded: a profile URL is not a channel we can
    open on our own, and counting it would mark as reachable a lead nobody can
    actually contact.
    """
    if lead.get("email_status") == _PENDING:
        return False
    return _has_email(lead) or bool(lead.get("phone")) or bool(lead.get("whatsapp"))


def contact_level(lead: dict) -> str:
    """Grade the best available route: direct | indirect | aucun | indetermine."""
    if lead.get("email_status") == _PENDING:
        return "indetermine"
    if (lead.get("email_status") in _DIRECT_EMAIL_STATUSES and lead.get("email")) \
            or lead.get("phone_type") == "mobile" or lead.get("whatsapp"):
        return "direct"
    if _has_email(lead) or lead.get("phone"):
        return "indirect"
    return "aucun"


def apply_reachability(leads: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    """Annotate every lead and split into (reachable, unreachable, pending).

    Pending leads form their own group rather than falling into unreachable:
    they were never asked the question, and burying them among the failures
    would lose them at the next monthly reset.
    """
    reachable: list[dict] = []
    unreachable: list[dict] = []
    pending: list[dict] = []

    for lead in leads:
        level = contact_level(lead)
        lead["contact_level"] = level
        if level == "indetermine":
            lead["reachable"] = None
            pending.append(lead)
        elif is_reachable(lead):
            lead["reachable"] = True
            reachable.append(lead)
        else:
            lead["reachable"] = False
            unreachable.append(lead)

    return reachable, unreachable, pending
```

- [ ] **Step 4 : Vider `hit_calculator.py`**

Remplacer intégralement le contenu de `processors/hit_calculator.py` :

```python
"""
Compatibility shim over processors/reachability.py.

The hit score it used to compute is gone (see reachability's module docstring).
This module survives only so the three runners keep one import path while they
are migrated in Task 22; it adds no logic of its own.
"""
import logging

from processors.reachability import apply_reachability

logger = logging.getLogger(__name__)


def score_all_leads(leads: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    """Split leads into (reachable, unreachable, pending)."""
    reachable, unreachable, pending = apply_reachability(leads)
    logger.info(
        f"Reachability: {len(reachable)} reachable / {len(unreachable)} unreachable "
        f"/ {len(pending)} pending quota"
    )
    return reachable, unreachable, pending
```

Réécrire `tests/test_hit_calculator.py` pour n'exercer que ce découpage à trois groupes.

- [ ] **Step 5 : Mettre à jour le schéma d'export**

Dans `lead_schema.py`, retirer `"hit_score"` et `"is_hit"`, et ajouter :

```python
    # Reachability — a boolean and its best route, never a score (2026-09-25).
    "reachable", "contact_level",
    # Email acquisition — which branch of the cascade produced this address.
    "email_source", "email_type", "contact_source_url",
    # Domain-level facts, shared by every lead on the same domain.
    "domain_catch_all", "domain_mx_provider", "domain_mismatch",
    # Phones and social, all extracted from the company's own site.
    "phone_type", "phone_source", "whatsapp",
    "facebook_url", "instagram_url", "linkedin_company_url",
    # Pass-1 spending prioritisation. NEVER a verdict — see processors/prescore.py.
    "prescore",
```

Ajouter les mêmes champs à `LeadRecord` dans `api/models.py`, et remplacer `hit_score` / `is_hit` par `reachable: Optional[bool]` et `contact_level: Optional[str]`.

- [ ] **Step 6 : Lancer la suite**

Run : `python -m pytest tests/ -v`
Expected : PASS.

- [ ] **Step 7 : Commit**

```bash
git add processors/reachability.py processors/hit_calculator.py lead_schema.py api/models.py tests/test_reachability.py tests/test_hit_calculator.py tests/test_lead_schema.py
git commit -m "feat: joignabilité booléenne en remplacement du hit score"
```

---

### Task 21 : Dédoublonnage multi-clés et liste de suppression

**Files:**
- Create: `api/suppression_db.py`, `api/routes/suppression.py`, `tests/test_suppression.py`
- Modify: `api/leads_db.py`, `api/server.py`

**Interfaces:**
- Consomme : `api.quota_db.normalize_name`.
- Produit :
  - `leads_db.dedupe_key(lead) -> tuple[str, str]` — `(kind, value)` avec `kind` ∈ `"email" | "linkedin" | "name_domain"`
  - `leads_db.check_duplicates(leads) -> dict[tuple, dict]`
  - `suppression_db.init_suppression_table()`, `is_suppressed(lead) -> str | None`, `add_entry(...)`, `import_csv(text) -> dict`, `list_entries()`, `delete_entry(row_id)`
  `api/pipeline_runner.py` (Task 22) filtre **avant tout enrichissement**.

**Contexte.** §9. Beaucoup de leads n'auront plus d'email — la clé primaire actuelle de `known_leads` les rendrait tous « nouveaux ». La liste de suppression protège les clients existants et les opt-out.

- [ ] **Step 1 : Écrire les tests qui échouent**

Créer `tests/test_suppression.py` :

```python
import pytest

from api import leads_db, suppression_db


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    path = str(tmp_path / "h.db")
    monkeypatch.setattr(leads_db, "_DB_PATH", path)
    monkeypatch.setattr(suppression_db, "_DB_PATH", path)
    leads_db.init_leads_table()
    suppression_db.init_suppression_table()


def _lead(**over):
    base = {"first_name": "Karim", "last_name": "El Amrani",
            "email": "karim@acme.ma", "linkedin_url": "https://linkedin.com/in/karim",
            "website": "https://acme.ma"}
    base.update(over)
    return base


# ── Clés de dédoublonnage ─────────────────────────────────────────────────────

def test_email_is_the_primary_key():
    assert leads_db.dedupe_key(_lead())[0] == "email"


def test_linkedin_is_the_first_fallback():
    assert leads_db.dedupe_key(_lead(email=None))[0] == "linkedin"


def test_name_plus_domain_is_the_last_fallback():
    """Most leads will now have no email at all: without this the dedupe table
    would report every one of them as new, forever."""
    kind, value = leads_db.dedupe_key(_lead(email=None, linkedin_url=None))
    assert kind == "name_domain"
    assert "acme.ma" in value


def test_a_lead_with_no_identifier_at_all_has_no_key():
    assert leads_db.dedupe_key({"first_name": "", "last_name": ""}) == ("", "")


def test_keys_are_normalized():
    a = leads_db.dedupe_key(_lead(email="  KARIM@ACME.MA "))
    b = leads_db.dedupe_key(_lead(email="karim@acme.ma"))
    assert a == b


def test_a_lead_seen_by_linkedin_is_recognized_on_a_later_run():
    leads_db.register_leads("job-1", [_lead(email=None)])
    known = leads_db.check_duplicates([_lead(email=None)])
    assert leads_db.dedupe_key(_lead(email=None)) in known


# ── Liste de suppression ──────────────────────────────────────────────────────

def test_a_suppressed_email_is_detected():
    suppression_db.add_entry(email="karim@acme.ma", motif="client existant")
    assert suppression_db.is_suppressed(_lead()) == "client existant"


def test_a_suppressed_linkedin_is_detected():
    suppression_db.add_entry(linkedin_url="https://linkedin.com/in/karim", motif="opt-out")
    assert suppression_db.is_suppressed(_lead(email=None)) == "opt-out"


def test_a_suppressed_domain_covers_every_lead_of_that_company():
    """Blacklisting a client company must cover colleagues we have never seen."""
    suppression_db.add_entry(domaine="acme.ma", motif="client BoxCom")
    assert suppression_db.is_suppressed(_lead(email=None, linkedin_url=None)) == "client BoxCom"
    assert suppression_db.is_suppressed(
        _lead(first_name="Sara", last_name="Bennani", email="sara@acme.ma")
    ) == "client BoxCom"


def test_an_unlisted_lead_is_not_suppressed():
    suppression_db.add_entry(email="autre@ailleurs.ma", motif="opt-out")
    assert suppression_db.is_suppressed(_lead()) is None


def test_matching_is_case_and_space_insensitive():
    suppression_db.add_entry(email="  KARIM@ACME.MA  ", motif="opt-out")
    assert suppression_db.is_suppressed(_lead()) == "opt-out"


# ── Import CSV ────────────────────────────────────────────────────────────────

def test_csv_import_reads_the_documented_columns():
    csv_text = (
        "email,linkedin_url,domaine,motif\n"
        "a@acme.ma,,,client existant\n"
        ",https://linkedin.com/in/b,,opt-out\n"
        ",,concurrent.ma,concurrent\n"
    )
    report = suppression_db.import_csv(csv_text)
    assert report["imported"] == 3
    assert len(suppression_db.list_entries()) == 3


def test_csv_import_skips_rows_with_no_identifier():
    report = suppression_db.import_csv("email,linkedin_url,domaine,motif\n,,,rien\n")
    assert report["imported"] == 0
    assert report["skipped"] == 1


def test_csv_import_is_idempotent():
    csv_text = "email,motif\na@acme.ma,client\n"
    suppression_db.import_csv(csv_text)
    suppression_db.import_csv(csv_text)
    assert len(suppression_db.list_entries()) == 1


def test_a_missing_motif_column_defaults_rather_than_failing():
    report = suppression_db.import_csv("email\na@acme.ma\n")
    assert report["imported"] == 1
```

- [ ] **Step 2 : Lancer les tests pour vérifier qu'ils échouent**

Run : `python -m pytest tests/test_suppression.py -v`
Expected : FAIL — `ModuleNotFoundError: No module named 'api.suppression_db'`.

- [ ] **Step 3 : Implémenter les clés de dédoublonnage**

Dans `api/leads_db.py`, ajouter la colonne `dedupe_kind` / `dedupe_value` à `known_leads` via une migration analogue à `_migrate_lead_pool`, puis :

```python
from urllib.parse import urlparse

from api.quota_db import normalize_name


def dedupe_key(lead: dict) -> tuple[str, str]:
    """Identify a lead across runs, degrading through three fallbacks.

    Email first, as before. But the free cascade leaves many leads without one,
    and a key that is absent for most rows identifies nothing: every run would
    re-report the same people as new. LinkedIn comes next, then the weakest but
    always-available pair of name and company domain.
    """
    email = normalize_name(lead.get("email") or "").replace(" ", "")
    if email:
        return ("email", email)

    linkedin = (lead.get("linkedin_url") or "").strip().lower().split("?")[0].rstrip("/")
    if linkedin:
        return ("linkedin", linkedin)

    first = normalize_name(lead.get("first_name") or "").replace(" ", "")
    last = normalize_name(lead.get("last_name") or "").replace(" ", "")
    domain = urlparse(lead.get("website") or "").netloc.lower().removeprefix("www.")
    if first and last and domain:
        return ("name_domain", f"{first}.{last}@{domain}")

    return ("", "")
```

Réécrire `check_duplicates` et `register_leads` pour travailler sur `(dedupe_kind, dedupe_value)` plutôt que sur l'email seul, en conservant la colonne `email` pour l'affichage.

- [ ] **Step 4 : Implémenter `api/suppression_db.py`**

```python
"""
Suppression list — checked before any enrichment, paid or free.

Existing BoxCom clients, people already contacted and opt-outs must never
reach a finder: contacting them is at best wasteful and at worst a breach of
an explicit request. The check therefore sits ahead of the cascade, not at
export time, so a suppressed lead costs nothing at all.
"""
import csv
import io
import os
import sqlite3
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

import config as pipeline_config
from api.quota_db import normalize_name

_DB_PATH = os.path.join(pipeline_config.OUTPUT_DIR, "history.db")

_CREATE_SUPPRESSION = """
CREATE TABLE IF NOT EXISTS suppression_list (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    email        TEXT,
    linkedin_url TEXT,
    domaine      TEXT,
    motif        TEXT NOT NULL DEFAULT 'non précisé',
    added_at     TEXT NOT NULL,
    UNIQUE (email, linkedin_url, domaine)
)
"""


def _conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(_DB_PATH), exist_ok=True)
    con = sqlite3.connect(_DB_PATH, timeout=5)
    con.row_factory = sqlite3.Row
    return con


def init_suppression_table() -> None:
    with _conn() as con:
        con.execute(_CREATE_SUPPRESSION)


def _norm(value: Optional[str]) -> Optional[str]:
    cleaned = (value or "").strip().lower().rstrip("/")
    return cleaned or None


def add_entry(email=None, linkedin_url=None, domaine=None, motif="non précisé") -> bool:
    email, linkedin_url, domaine = _norm(email), _norm(linkedin_url), _norm(domaine)
    if not (email or linkedin_url or domaine):
        return False
    with _conn() as con:
        con.execute(
            """INSERT OR IGNORE INTO suppression_list
               (email, linkedin_url, domaine, motif, added_at) VALUES (?,?,?,?,?)""",
            (email, linkedin_url, domaine, motif or "non précisé",
             datetime.now(timezone.utc).isoformat()),
        )
    return True


def is_suppressed(lead: dict) -> Optional[str]:
    """Return the suppression reason, or None. Domain matches cover colleagues."""
    email = _norm(lead.get("email"))
    linkedin = _norm((lead.get("linkedin_url") or "").split("?")[0])
    domain = _norm(urlparse(lead.get("website") or "").netloc.removeprefix("www."))
    if not domain and email and "@" in email:
        domain = email.rsplit("@", 1)[1]

    with _conn() as con:
        row = con.execute(
            """SELECT motif FROM suppression_list
               WHERE (email IS NOT NULL AND email = ?)
                  OR (linkedin_url IS NOT NULL AND linkedin_url = ?)
                  OR (domaine IS NOT NULL AND domaine = ?)
               LIMIT 1""",
            (email, linkedin, domain),
        ).fetchone()
    return row["motif"] if row else None


def import_csv(text: str) -> dict:
    """Import rows with columns email, linkedin_url, domaine, motif (all optional)."""
    reader = csv.DictReader(io.StringIO(text))
    imported = skipped = 0
    for row in reader:
        normalized = {(k or "").strip().lower(): v for k, v in row.items()}
        added = add_entry(
            email=normalized.get("email"),
            linkedin_url=normalized.get("linkedin_url"),
            domaine=normalized.get("domaine") or normalized.get("domain"),
            motif=normalized.get("motif") or normalized.get("reason") or "import CSV",
        )
        imported += int(added)
        skipped += int(not added)
    return {"imported": imported, "skipped": skipped}


def list_entries() -> list[dict]:
    with _conn() as con:
        return [dict(r) for r in con.execute(
            "SELECT * FROM suppression_list ORDER BY added_at DESC"
        ).fetchall()]


def delete_entry(row_id: int) -> bool:
    with _conn() as con:
        cur = con.execute("DELETE FROM suppression_list WHERE id = ?", (row_id,))
    return cur.rowcount > 0
```

- [ ] **Step 5 : Exposer les routes**

Créer `api/routes/suppression.py` avec `GET /suppression`, `POST /suppression`, `DELETE /suppression/{id}` et `POST /suppression/import` (UploadFile CSV, décodé en UTF-8 avec repli latin-1). Enregistrer le routeur et `init_suppression_table()` dans `api/server.py`.

- [ ] **Step 6 : Lancer les tests**

Run : `python -m pytest tests/test_suppression.py -v`
Expected : PASS.

- [ ] **Step 7 : Commit**

```bash
git add api/suppression_db.py api/routes/suppression.py api/leads_db.py api/server.py tests/test_suppression.py
git commit -m "feat: dédoublonnage multi-clés et liste de suppression"
```

---

### Task 22 : Pools — migration des colonnes et sélection par pré-score

**Files:**
- Modify: `api/leads_db.py`
- Test: `tests/test_leads_db_pools.py` (créé)

**Interfaces:**
- Consomme : `processors.prescore.rank_for_spending`.
- Produit :
  - `_LEAD_POOL_ADDED_COLUMNS` étendu de 15 colonnes
  - `get_pool_leads(pool_id, only_reachable=False, only_unenriched=False, limit=0, order_by="prescore")`
  - `count_pending_quota(pool_id) -> int`
  `api/routes/pipeline.py` et `api/pipeline_runner.py` (Task 23) les consomment.

**Contexte.** §10. L'ordre de sélection passe de `hit_score DESC` à `prescore DESC`, et les leads `pending_quota` remontent en tête après le reset mensuel.

- [ ] **Step 1 : Écrire les tests qui échouent**

Créer `tests/test_leads_db_pools.py` :

```python
import pytest

from api import leads_db


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(leads_db, "_DB_PATH", str(tmp_path / "h.db"))
    leads_db.init_leads_table()


def _lead(**over):
    base = {"first_name": "Karim", "last_name": "El Amrani", "company": "Acme",
            "website": "https://acme.ma", "email": "k@acme.ma",
            "email_status": "valid_nominatif", "email_source": "website",
            "prescore": 50, "reachable": True, "contact_level": "direct",
            "whatsapp": False, "domain_catch_all": False}
    base.update(over)
    return base


def test_new_columns_survive_a_round_trip():
    pool_id = leads_db.create_pool("P", "url", "job-1", [_lead(
        email_source="prospeo", email_type="nominatif_lead", phone_type="mobile",
        whatsapp=True, domain_mx_provider="google", domain_mismatch=False,
        prescore=73, contact_source_url="https://acme.ma/contact",
    )])
    stored = leads_db.get_pool_leads(pool_id)[0]
    assert stored["email_source"] == "prospeo"
    assert stored["phone_type"] == "mobile"
    assert stored["whatsapp"] is True
    assert stored["domain_mx_provider"] == "google"
    assert stored["prescore"] == 73
    assert stored["contact_source_url"] == "https://acme.ma/contact"


def test_a_pool_created_before_the_migration_still_loads(monkeypatch):
    """Pools predating this refactor must keep opening: missing columns come
    back as None, never as an exception."""
    with leads_db._conn() as con:
        con.execute("DROP TABLE lead_pool")
        con.execute("""CREATE TABLE lead_pool (
            id INTEGER PRIMARY KEY AUTOINCREMENT, pool_id TEXT NOT NULL,
            first_name TEXT, last_name TEXT, company TEXT, hit_score REAL,
            is_hit INTEGER DEFAULT 0, enriched INTEGER DEFAULT 0)""")
        con.execute("INSERT INTO lead_pool (pool_id, first_name) VALUES ('old', 'Ancien')")
    rows = leads_db.get_pool_leads("old")
    assert rows[0]["first_name"] == "Ancien"
    assert rows[0]["prescore"] is None
    assert rows[0]["email_source"] is None


def test_selection_is_ordered_by_prescore_descending():
    pool_id = leads_db.create_pool("P", "url", "job-1", [
        _lead(company="Faible", prescore=10),
        _lead(company="Fort", prescore=90),
        _lead(company="Moyen", prescore=50),
    ])
    assert [l["company"] for l in leads_db.get_pool_leads(pool_id)] == \
        ["Fort", "Moyen", "Faible"]


def test_pending_quota_leads_come_first_after_a_reset():
    """§10: they were never asked the question — they get the next batch."""
    pool_id = leads_db.create_pool("P", "url", "job-1", [
        _lead(company="Fort", prescore=90, email_status="valid_nominatif"),
        _lead(company="EnAttente", prescore=20, email_status="pending_quota"),
    ])
    batch = leads_db.get_pool_leads(pool_id, only_unenriched=True, limit=2)
    assert batch[0]["company"] == "EnAttente"


def test_only_reachable_filters_out_the_unreachable_but_keeps_pending():
    pool_id = leads_db.create_pool("P", "url", "job-1", [
        _lead(company="Joignable", reachable=True),
        _lead(company="Non", reachable=False, email=None, email_status="not_found"),
        _lead(company="Attente", reachable=None, email_status="pending_quota"),
    ])
    names = {l["company"] for l in leads_db.get_pool_leads(pool_id, only_reachable=True)}
    assert names == {"Joignable", "Attente"}


def test_pending_quota_are_counted():
    pool_id = leads_db.create_pool("P", "url", "job-1", [
        _lead(email_status="pending_quota"), _lead(email_status="valid_nominatif"),
    ])
    assert leads_db.count_pending_quota(pool_id) == 1
```

- [ ] **Step 2 : Lancer les tests pour vérifier qu'ils échouent**

Run : `python -m pytest tests/test_leads_db_pools.py -v`
Expected : FAIL — colonnes absentes, `count_pending_quota` inexistant.

- [ ] **Step 3 : Étendre la migration**

Dans `api/leads_db.py` :

```python
# Columns added by the 2026-09-25 free-cascade rework. CREATE TABLE IF NOT
# EXISTS leaves an existing table untouched, so a pool created before this
# date would silently drop every one of these on insert.
_LEAD_POOL_ADDED_COLUMNS = {
    "website_coherent": "INTEGER",
    "website_rejected": "TEXT",
    "website_check_reason": "TEXT",
    "email_status": "TEXT",
    "email_confidence": "INTEGER",
    # ── Cascade email gratuite ────────────────────────────────────────────
    "email_source": "TEXT",
    "email_type": "TEXT",
    "contact_source_url": "TEXT",
    "domain_catch_all": "INTEGER",
    "domain_mx_provider": "TEXT",
    "domain_mismatch": "INTEGER",
    "phone_type": "TEXT",
    "phone_source": "TEXT",
    "whatsapp": "INTEGER",
    "facebook_url": "TEXT",
    "instagram_url": "TEXT",
    "linkedin_company_url": "TEXT",
    "prescore": "REAL",
    "reachable": "INTEGER",
    "contact_level": "TEXT",
}
```

Étendre l'`INSERT` de `create_pool` aux nouvelles colonnes, et convertir les booléens comme `website_coherent` l'est déjà (`None if x is None else int(bool(x))`, pour distinguer « non renseigné » de « faux »).

- [ ] **Step 4 : Réécrire la sélection**

```python
def get_pool_leads(pool_id: str, only_reachable: bool = False,
                   only_unenriched: bool = False, limit: int = 0,
                   order_by: str = "prescore") -> list[dict]:
    """Read leads from a pool, ordered for spending.

    pending_quota leads sort first: they never got their question asked, and
    the monthly reset is precisely when they should. Everything else follows
    by prescore descending — the free relevance estimate that decides where
    the month's credits go (see processors/prescore.py).
    """
    query = "SELECT * FROM lead_pool WHERE pool_id = ?"
    params: list = [pool_id]

    if only_reachable:
        # reachable IS NULL is pending_quota: undetermined, never excluded.
        query += " AND (reachable = 1 OR reachable IS NULL)"
    if only_unenriched:
        query += " AND enriched = 0"

    query += (" ORDER BY CASE WHEN email_status = 'pending_quota' THEN 0 ELSE 1 END, "
              "COALESCE(prescore, 0) DESC, id ASC")
    if limit > 0:
        query += " LIMIT ?"
        params.append(limit)
    ...
```

Convertir les entiers en booléens au retour (`whatsapp`, `reachable`, `domain_catch_all`, `domain_mismatch`), en préservant `None`. Ajouter :

```python
def count_pending_quota(pool_id: str) -> int:
    with _conn() as con:
        _migrate_lead_pool(con)
        row = con.execute(
            "SELECT COUNT(*) AS cnt FROM lead_pool WHERE pool_id = ? "
            "AND email_status = 'pending_quota'", (pool_id,)
        ).fetchone()
    return row["cnt"] if row else 0
```

- [ ] **Step 5 : Lancer les tests**

Run : `python -m pytest tests/test_leads_db_pools.py tests/ -v`
Expected : PASS.

- [ ] **Step 6 : Commit**

```bash
git add api/leads_db.py tests/test_leads_db_pools.py
git commit -m "feat: colonnes de cascade dans les pools, sélection par pré-score"
```

---

### Task 23 : Runners, progression SSE, statistiques et résumé

**Files:**
- Modify: `api/pipeline_runner.py`, `api/routes/pipeline.py`, `main.py`
- Test: `tests/test_summary_prompt.py`, `tests/test_pipeline_stats.py` (créé)

**Interfaces:**
- Consomme : tout ce qui précède.
- Produit : `STEP_NAMES`/`STEP_WEIGHTS`/`STEP_PATTERNS` refaits, `compute_stats(leads) -> JobStats`, `_build_summary_prompt(...)` étendu, trois runners alignés.

**Contexte.** §10 et §11. Le découpage gratuit/payant devient la frontière entre `/api/scrape` et `/api/enrich`.

- [ ] **Step 1 : Écrire les tests qui échouent**

Créer `tests/test_pipeline_stats.py` :

```python
import pytest

from api.pipeline_runner import STEP_NAMES, STEP_PATTERNS, STEP_WEIGHTS, compute_stats


def _lead(**over):
    base = {"email": None, "email_status": "not_found", "email_source": None,
            "phone": None, "phone_type": None, "whatsapp": False,
            "reachable": False, "prescore": 0}
    base.update(over)
    return base


def test_step_weights_sum_to_one():
    assert round(sum(STEP_WEIGHTS.values()), 6) == 1.0


def test_every_weighted_step_has_a_name_and_a_pattern():
    assert set(STEP_WEIGHTS) == set(STEP_NAMES)
    covered = {step for step, _ in STEP_PATTERNS}
    assert covered.issubset(set(STEP_WEIGHTS))


def test_find_rate_is_broken_down_by_source():
    leads = [
        _lead(email="a@x.ma", email_status="valid_nominatif", email_source="website"),
        _lead(email="b@x.ma", email_status="valid_nominatif", email_source="website"),
        _lead(email="c@x.ma", email_status="valid_nominatif", email_source="pattern_verified"),
        _lead(email="d@x.ma", email_status="valid_nominatif", email_source="prospeo"),
        _lead(),
    ]
    stats = compute_stats(leads)
    assert stats.email_by_source["website"] == 2
    assert stats.email_by_source["pattern_verified"] == 1
    assert stats.email_by_source["prospeo"] == 1


def test_mobile_and_whatsapp_rates_are_reported():
    leads = [_lead(phone="+212661234567", phone_type="mobile"),
             _lead(phone="+212522123456", phone_type="fixe"),
             _lead(whatsapp=True), _lead()]
    stats = compute_stats(leads)
    assert stats.mobile_count == 1
    assert stats.whatsapp_count == 1


def test_pending_quota_leads_are_counted_separately():
    stats = compute_stats([_lead(email_status="pending_quota"), _lead()])
    assert stats.pending_quota_count == 1


def test_stats_on_an_empty_run_do_not_divide_by_zero():
    stats = compute_stats([])
    assert stats.email_pct == 0.0
```

Ajouter à `tests/test_summary_prompt.py` :

```python
def test_the_summary_prompt_names_pending_quota_leads():
    """A run that left 40 leads unqueried because the month ran out must say
    so: the numbers otherwise read as a poor find rate."""
    leads = [{"email_status": "pending_quota"} for _ in range(40)]
    prompt = _build_summary_prompt(leads=leads, reachable_count=0, unreachable_count=0,
                                   pending_count=40, stats=JobStats(),
                                   provider_status={})
    assert "40" in prompt
    assert "quota" in prompt.lower()


def test_the_summary_prompt_reports_a_degraded_provider_group():
    prompt = _build_summary_prompt(
        leads=[], reachable_count=0, unreachable_count=0, pending_count=0,
        stats=JobStats(),
        provider_status={"prospeo": {"status": "failed", "reason": "clé rejetée",
                                     "leads_affected": 12}},
    )
    assert "Prospeo" in prompt or "prospeo" in prompt
    assert "dégradé" in prompt or "en échec" in prompt
```

- [ ] **Step 2 : Lancer les tests pour vérifier qu'ils échouent**

Run : `python -m pytest tests/test_pipeline_stats.py tests/test_summary_prompt.py -v`
Expected : FAIL — `compute_stats` inexistant, signature de `_build_summary_prompt` différente.

- [ ] **Step 3 : Refaire la carte des étapes**

Dans `api/pipeline_runner.py` :

```python
# Rebalanced for the free cascade: Apollo and the site crawl now carry most of
# the work, while the former "Dropcontact batch" step is gone. Weights reflect
# observed wall-clock, not importance.
STEP_WEIGHTS = {1: 0.03, 2: 0.17, 3: 0.12, 4: 0.18, 5: 0.05, 6: 0.15,
                7: 0.18, 8: 0.05, 9: 0.07}
STEP_NAMES = {
    1: "Entrée Apollo",
    2: "Scraping Apollo",
    3: "LinkedIn et site web",
    4: "Extraction des contacts du site",
    5: "Pré-score et priorisation",
    6: "Cascade email",
    7: "Collecte de preuves (site + Perplexity)",
    8: "Extraction de faits et scoring ICP",
    9: "Rédaction des angles commerciaux",
}

STEP_PATTERNS = [
    (2, re.compile(r"Step 2|Scraping Apollo|apollo|page \d+", re.I)),
    (3, re.compile(r"Step 3|Google enrichment|LinkedIn|website|Clearbit|Serper", re.I)),
    (4, re.compile(r"Step 4|Contact extraction|harvest|contact page|robots", re.I)),
    (5, re.compile(r"Step 5|[Pp]rescore|priorisation|ranking", re.I)),
    (6, re.compile(r"Step 6|cascade|Prospeo|GetProspect|Hunter|catch-all|MX|pattern", re.I)),
    (7, re.compile(r"Step 7|Evidence|Perplexity|Scraping hit lead", re.I)),
    (8, re.compile(r"Step 8|Fact extraction|ICP scoring", re.I)),
    (9, re.compile(r"Step 9|Angle writing", re.I)),
]
```

- [ ] **Step 4 : Implémenter `compute_stats`**

Étendre `JobStats` dans `api/models.py` (`email_by_source: dict[str, int] = {}`, `mobile_count`, `whatsapp_count`, `pending_quota_count`, `reachable_count`, `provider_credits: dict[str, dict] = {}`), puis :

```python
def compute_stats(leads: list[dict]) -> JobStats:
    """Aggregate one run's outcome, including where each email came from.

    The per-source breakdown is what tells the operator whether the free
    branches are carrying their weight: a month where everything came from
    finders means the site crawl or the pattern generator has regressed, and
    the credits will run out long before the leads do.
    """
    total = len(leads)
    if not total:
        return JobStats()

    def pct(field):
        return round(100 * sum(1 for l in leads if l.get(field)) / total, 1)

    by_source: dict[str, int] = {}
    for lead in leads:
        source = lead.get("email_source")
        if source and lead.get("email"):
            by_source[source] = by_source.get(source, 0) + 1

    quotas = {
        name: {"remaining": quota_db.get_quota(name)["remaining"],
               "allocation": quota_db.get_quota(name)["allocation"]}
        for name in pipeline_config.PROVIDER_ALLOCATIONS
    }

    return JobStats(
        email_pct=pct("email"), linkedin_pct=pct("linkedin_url"),
        phone_pct=pct("phone"), website_pct=pct("website"),
        email_count=sum(1 for l in leads if l.get("email")),
        linkedin_count=sum(1 for l in leads if l.get("linkedin_url")),
        phone_count=sum(1 for l in leads if l.get("phone")),
        website_count=sum(1 for l in leads if l.get("website")),
        email_by_source=by_source,
        mobile_count=sum(1 for l in leads if l.get("phone_type") == "mobile"),
        whatsapp_count=sum(1 for l in leads if l.get("whatsapp")),
        pending_quota_count=sum(1 for l in leads if l.get("email_status") == "pending_quota"),
        reachable_count=sum(1 for l in leads if l.get("reachable") is True),
        avg_score=round(sum(l.get("prescore") or 0 for l in leads) / total, 1),
        icp_hot_count=sum(1 for l in leads if l.get("icp_tier") == "hot"),
        icp_warm_count=sum(1 for l in leads if l.get("icp_tier") == "warm"),
        icp_cold_count=sum(1 for l in leads if l.get("icp_tier") == "cold"),
        icp_disqualified_count=sum(1 for l in leads if l.get("icp_tier") == "disqualified"),
        provider_credits=quotas,
    )
```

- [ ] **Step 5 : Étendre le prompt de résumé**

Dans `_build_summary_prompt`, remplacer les paramètres `hit_count`/`nohit_count` par `reachable_count`/`unreachable_count`/`pending_count`, et ajouter deux lignes de données :

```python
    if pending_count:
        data_lines.append(
            f"- {pending_count} leads en attente de quota : aucun fournisseur "
            f"n'avait de crédit disponible. Ils ne sont pas écartés et repasseront "
            f"en priorité au prochain reset mensuel."
        )
    if stats.email_by_source:
        described = ", ".join(f"{src} : {n}" for src, n in sorted(
            stats.email_by_source.items(), key=lambda kv: -kv[1]))
        data_lines.append(f"- Emails trouvés par source — {described}")
```

Et dans les instructions de rédaction :

```python
    pending_writing_instruction = (
        " Mentionne explicitement les leads en attente de quota : ils ne sont ni "
        "qualifiés ni disqualifiés, et les taux ci-dessus ne les comptent pas."
        if pending_count else ""
    )
```

- [ ] **Step 6 : Redécouper les trois runners**

`_run_scrape_only_sync` — **uniquement du gratuit** (§10) : Apollo → `enrich_leads_google` → `harvest_contacts` → `lookup_mx` → `apply_prescores` → suppression + dédoublonnage → `create_pool`. Aucun appel à la cascade.

`_run_enrich_only_sync` — **le payant** : `quota_sync.sync_all(registry)`, puis lot trié par `get_pool_leads(..., limit=batch_size)`, `resolve_email(lead, is_priority=True, registry)`, `apply_reachability`, puis étapes 7 à 9 inchangées.

`_run_pipeline_sync` — l'enchaînement des deux, avec `rank_for_spending` entre les deux et `is_priority` calculé sur la position dans la file :

```python
        # Finder credits go to the head of the queue, not to whoever happens
        # to be scraped first (§7).
        ranked = rank_for_spending(leads)
        budget = sum(quota_db.get_quota(p)["remaining"]
                     for p in ("prospeo", "getprospect", "hunter"))
        for position, lead in enumerate(ranked):
            _check_cancelled(job_id)
            resolve_email(lead, is_priority=position < budget, registry=registry)
```

Ajouter le filtre de suppression **avant** la cascade dans les trois :

```python
        from api.suppression_db import is_suppressed
        for lead in leads:
            motif = is_suppressed(lead)
            if motif:
                lead["email_status"] = "not_found"
                lead["suppression_reason"] = motif
        leads = [l for l in leads if not l.get("suppression_reason")]
```

- [ ] **Step 7 : CSV séparé pour les `pending_quota`**

Après l'export final, comme pour les no-hit :

```python
        if pending_leads:
            pending_path = export_csv(pending_leads, f"leads_pending_quota_{ts}.csv")
            logger.info(f"Pending-quota CSV saved: {pending_path}")
```

- [ ] **Step 8 : Lancer la suite complète**

Run : `python -m pytest tests/ -v`
Expected : PASS.

- [ ] **Step 9 : Commit**

```bash
git add api/pipeline_runner.py api/routes/pipeline.py api/models.py main.py tests/test_pipeline_stats.py tests/test_summary_prompt.py
git commit -m "feat: runners gratuits/payants, statistiques par source, CSV pending_quota"
```

---

### Task 24 : Configuration et interface

**Files:**
- Modify: `api/routes/config.py`, `frontend/src/lib/api.ts`, `frontend/src/components/Settings.tsx`, `ResultsTable.tsx`, `LeadDetailModal.tsx`, `StatsBar.tsx`
- Test: `tests/test_routes_config.py` (créé)

**Interfaces:**
- Consomme : `api.quota_db.get_quota`, `api.suppression_db`.
- Produit : `GET /api/config` exposant `prospeo_api_key`, `getprospect_api_key` et `quotas` ; `POST /api/config/validate-key` couvrant les deux nouveaux fournisseurs.

- [ ] **Step 1 : Écrire les tests qui échouent**

Créer `tests/test_routes_config.py` :

```python
import pytest
from fastapi.testclient import TestClient

from api.server import app


@pytest.fixture
def client():
    return TestClient(app)


def test_config_exposes_the_two_new_providers(client):
    body = client.get("/api/config").json()
    assert "prospeo_api_key" in body
    assert "getprospect_api_key" in body


def test_dropcontact_is_gone_from_the_config_payload(client):
    assert "dropcontact_api_key" not in client.get("/api/config").json()


def test_config_reports_quota_balances(client):
    quotas = client.get("/api/config").json()["quotas"]
    for provider in ("prospeo", "hunter", "getprospect"):
        assert "remaining" in quotas[provider]
        assert "allocation" in quotas[provider]


def test_validating_an_empty_key_is_refused_without_a_network_call(client):
    body = client.post("/api/config/validate-key",
                       json={"type": "prospeo", "value": ""}).json()
    assert body["valid"] is False
```

- [ ] **Step 2 : Lancer les tests pour vérifier qu'ils échouent**

Run : `python -m pytest tests/test_routes_config.py -v`
Expected : FAIL — clés absentes du payload.

- [ ] **Step 3 : Étendre les routes**

Dans `api/routes/config.py` : ajouter `prospeo_api_key` et `getprospect_api_key` à `ConfigUpdate`, au rechargement de `get_config()`/`update_config()`, et exposer les quotas :

```python
    from api import quota_db
    quotas = {
        name: {
            "remaining": quota_db.get_quota(name)["remaining"],
            "allocation": quota_db.get_quota(name)["allocation"],
            "reset_date": quota_db.get_quota(name)["reset_date"],
        }
        for name in pipeline_config.PROVIDER_ALLOCATIONS
    }
```

Ajouter deux branches à `validate_api_key`, en utilisant les endpoints **gratuits** :

```python
        elif key_type == "prospeo":
            # /account-information is documented as free.
            resp = requests.get("https://api.prospeo.io/account-information",
                                headers={"X-KEY": key_value}, timeout=10)
            body = resp.json() if resp.content else {}
            if body.get("error") and body.get("error_code") == "INVALID_API_KEY":
                return {"valid": False, "error": "Clé invalide"}
            return {"valid": True}

        elif key_type == "getprospect":
            # No account endpoint exists: a minimal find against a domain that
            # yields nothing is refunded, so this costs no credit.
            resp = requests.post(
                "https://api.getprospect.com/v2/email/find",
                headers={"x-api-key": key_value, "Content-Type": "application/json"},
                json={"data": {"first_name": "Zzqx", "last_name": "Vbnm",
                               "domain": "example.com"}},
                timeout=15,
            )
            if resp.status_code == 401:
                return {"valid": False, "error": "Clé invalide"}
            return {"valid": True}
```

- [ ] **Step 4 : Mettre à jour le frontend**

`frontend/src/components/Settings.tsx` :
- retirer `dropcontact` des trois états (`keys`, `showKey`, `saveConfig`) et de `KEY_FIELDS`
- ajouter deux entrées :

```tsx
    { id: 'prospeo',     label: 'PROSPEO_API_KEY',     required: false, configKey: 'prospeo_api_key',     hint: 'Optionnel — 100 recherches/mois en plan gratuit' },
    { id: 'getprospect', label: 'GETPROSPECT_API_KEY', required: false, configKey: 'getprospect_api_key', hint: 'Optionnel — 50 emails + 100 vérifications/mois' },
```

- ajouter un panneau **Quotas** listant, par fournisseur, `remaining / allocation` avec une barre de progression et la date de reset
- ajouter un bloc **Liste de suppression** : upload CSV (`POST /api/suppression/import`), compteur d'entrées, suppression unitaire

`frontend/src/lib/api.ts` : ajouter `getSuppressionList()`, `importSuppressionCsv(file)`, `deleteSuppressionEntry(id)`, et étendre les types `Config` et `JobStats`.

`ResultsTable.tsx` :
- remplacer la colonne « Score » (hit) par **Pré-score** avec barre visuelle
- remplacer le badge « Hit » par **Joignable** (`direct` vert / `indirect` ambre / `aucun` gris / `indetermine` bleu)
- ajouter une colonne **Source** (icône par `email_source`)
- remplacer l'onglet « No-hit » par trois onglets : **Joignables / Non joignables / En attente de quota**

`LeadDetailModal.tsx` : ajouter un bloc « Contact » avec `email_source`, `email_type`, `contact_source_url` (lien cliquable vers la page où l'adresse a été trouvée), `domain_mx_provider`, `domain_catch_all`, et un avertissement visible si `domain_mismatch`.

`StatsBar.tsx` : remplacer la carte « Score moyen » par **Pré-score moyen**, et ajouter des cartes **Emails par source**, **Mobiles**, **WhatsApp**, **Crédits restants**.

- [ ] **Step 5 : Vérifier le build**

Run : `npm --prefix frontend run build`
Expected : build réussi, aucune erreur TypeScript.

Run : `python -m pytest tests/ -v`
Expected : PASS.

- [ ] **Step 6 : Commit**

```bash
git add api/routes/config.py frontend/src tests/test_routes_config.py
git commit -m "feat: clés Prospeo/GetProspect, panneau quotas, liste de suppression dans l'UI"
```

---

## Auto-revue

Relecture du plan contre la spécification et les sept décisions.

**Couverture du spec**

| Section | Tâches | État |
|---|---|---|
| §1 Suppression de Dropcontact | 1, 3 | ✅ |
| §2 Clés, quotas, cache | 4, 5, 6, 24 | ✅ |
| §3 Extraction depuis le site | 7, 8, 9, 10 | ✅ |
| §4 Contrôle du domaine | 11 | ✅ |
| §5 Cascade email | 12, 13, 14, 15, 16 | ✅ |
| §6 Hit score | 20 | ⚠️ **Remplacé** par la joignabilité booléenne (décision 5) |
| §7 Priorisation des crédits | 17, 18 | ⚠️ **Sans disqualification** (décision 3) |
| §8 Géographie ICP | 19 | ⚠️ **Europe conservée** en zone basse (décision 2) |
| §9 Dédoublonnage et suppression | 21 | ✅ |
| §10 Pools | 22, 23 | ✅ |
| §11 Export, suivi, résumé | 20, 23 | ✅ |
| §12 Tests | toutes | ✅ — 13 fichiers de tests créés, 4 réécrits |

**Cohérence des types entre tâches**

- `EmailResult` (Task 13) est le seul type traversant les clients (13, 14, 15) et la cascade (16). Champs identiques partout.
- `PageFetch` (Task 7) est produit par `verify_website` et consommé par `harvest_contacts` (9) et `scrape_hit_leads` (7).
- `ExtractedEmail{value, kind, source_url}` (8) est consommé tel quel par la cascade (16) et les pools (22).
- `normalize_name` est défini une fois dans `api/quota_db.py` (5) et réutilisé par 8, 12 et 21 — jamais redéfini.
- `prescore` est écrit par `apply_prescores` (18), lu par `rank_for_spending` (18), stocké par les pools (22), exporté par le schéma (20).
- `email_status` a exactement sept valeurs, déclarées dans `EMAIL_STATUSES` (16) et consommées par `REACHABLE_EMAIL_STATUSES` (20).

**Dépendance circulaire signalée.** Task 18 (`test_prescore.py`) contient des tests de géographie qui ne passent qu'après Task 19. C'est explicite dans le Step 4 de la tâche 18 — l'exécutant commit un test rouge documenté, puis Task 19 le fait passer. Alternative si l'exécutant préfère un vert permanent : déplacer les six tests `test_zone_points_follow_the_validated_geography` dans Task 19.

---

## Exécution

Plan complet et enregistré dans `docs/superpowers/plans/2026-09-25-cascade-email-gratuite.md`. Deux options d'exécution :

**1. Subagent-Driven (recommandé)** — un sous-agent neuf par tâche, revue entre chaque, itération rapide. Adapté ici : 24 tâches, la plupart indépendantes une fois leur prédécesseur livré.

**2. Inline Execution** — exécution des tâches dans la session courante, par lots avec points de contrôle.

Ordre de dépendance à respecter dans les deux cas :

```
1 -> 2 -> 3                      (socle : suppression, exceptions, groupes)
     4 -> 5 -> 6                 (quota et cache)
7 -> 8 -> 9 -> 10                (extraction site)
11, 12                           (domaine, patterns — parallélisables)
13 -> 14, 15                     (clients — 14 et 15 parallélisables)
16                               (cascade — exige 5, 11, 12, 13, 14, 15)
17 -> 19 -> 18                   (Apollo, géographie, pré-score)
20                               (joignabilité et schéma — exige 16)
21 -> 22                         (persistance — les deux modifient leads_db.py)
23                               (orchestration — exige tout ce qui précède)
24                               (UI — exige 23)
```
