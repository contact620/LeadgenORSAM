# Refonte du scoring ICP et fiabilisation du pipeline

**Date :** 2026-08-10
**Origine :** retour client après plusieurs runs de test
**Statut :** design validé, en attente de plan d'implémentation

---

## 1. Problèmes rapportés

Le client a testé l'outil sur plusieurs runs et remonte quatre points :

1. Avec la clé Perplexity renseignée, aucune donnée de contact ne remonte : ni email ni
   téléphone. Tous les leads sortent à `hit_score = 40` et `is_hit = False`, donc
   l'enrichissement ne se déclenche jamais.
2. Le scoring ICP est inversé : plus le modèle dispose d'informations sur une entreprise,
   plus il la note bas. Les leads sur lesquels il se déclare peu sûr ressortent en tête.
3. Le système ne produit jamais de verdict négatif — aucun lead `cold`, aucun disqualifié,
   même quand l'analyse identifie elle-même un motif de dépriorisation.
4. Plusieurs enregistrements pointent vers des sites d'entreprises sans aucun rapport avec
   le prospect.

---

## 2. Diagnostic

### 2.1 Scoring inversé et absence de verdict négatif (points 2 et 3)

Cause racine : **ordre d'exécution**. `processors/icp_scorer.py` tourne à l'étape 5, avant
le scraping du site (6a), avant l'analyse Claude (6b) et avant Perplexity (7).

`_build_batch_user_prompt` ne transmet que prénom, nom, poste, entreprise, localisation,
email, URL LinkedIn et URL du site. Aucun contenu. L'axe `signaux` pèse 40 % et demande
d'évaluer « site obsolète, recrutement marketing, levée de fonds, expansion » : le modèle
n'a aucune preuve à sa disposition pour cet axe.

Conséquence mécanique :

- entreprise inconnue du modèle → notes moyennes-hautes par défaut sur les quatre axes →
  score pondéré 60-75 → `warm` ou `hot` ;
- entreprise connue → critères réellement appliqués → motifs de baisse trouvés → `cold`.

L'information fait donc *baisser* la note. Observé dans les deux derniers CSV de sortie :

| société | llm_confidence | inconsistency_detected | icp_score | icp_tier |
|---|---|---|---|---|
| houzing (site retenu : rentkasa.com) | low | **True** | **78** | hot |
| Amundi | high | False | **25** | cold |

`llm_confidence` et `inconsistency_detected` sont produits par `enrichers/gpt_enricher.py`,
un appel distinct exécuté **après** le scoring. Les deux ne communiquent jamais : un lead
peu fiable et incohérent peut donc être classé `hot`.

Pour l'absence de verdict négatif : `_score_to_tier` place `cold` sous 40, mais un LLM sans
critère de disqualification n'ancre jamais une moyenne pondérée sous ce seuil. Les seuls
motifs de dépriorisation du projet existent sous forme de parenthèses indicatives dans
`prompts/icp_scoring.txt` et n'ont aucun effet mécanique :

| Motif existant | Emplacement |
|---|---|
| « industrie lourde, agriculture = score bas » | axe secteur |
| « micro-entreprise ou grand groupe = score moyen/bas » | axe taille |
| « Maroc, Afrique francophone, France = score élevé » | axe localisation |
| « présence digitale faible ou vieillissante » | préambule, profil idéal |

### 2.2 Incohérence société / site (point 4)

`enrichers/google_search.py`, fonction `_clearbit_domain` :

```python
input_words = [w for w in company.lower().split() if len(w) > 3]
if domain and input_words and any(w in returned_name for w in input_words):
```

Un seul mot de plus de trois lettres présent en sous-chaîne suffit à valider un domaine.
« Alp Financial » accepte « Financial Times ».

`_find_company_website(company)` ne reçoit jamais la localisation : aucun contrôle pays
n'est structurellement possible. Le fallback `_pick_website` retient le premier résultat non
blacklisté d'une recherche « {company} official website ».

Défaut annexe : `urlparse(url).netloc.lower().lstrip("www.")` retire des *caractères*, pas un
préfixe — « wework.com » devient « ework.com ».

### 2.3 Perte des données de contact (point 1)

Aucun chemin de code ne permet à Perplexity d'affecter email ou téléphone. `enrich_leads_perplexity`
s'exécute à l'étape 7, sur des `hit_leads` déjà calculés, et n'écrit que `digital_maturity`,
`estimated_budget` et `business_signals`. Il n'existe par ailleurs aucun toggle Perplexity
dans l'interface — seulement la clé API dans les Paramètres.

La signature décrite correspond en revanche exactement à un échec Dropcontact :
`hit_score = 40` = LinkedIn (30) + site (10), sans email ni téléphone. `enrichers/dropcontact.py`
traite ce cas en `logger.error` puis **poursuit silencieusement** : le run se termine en
statut `done`, le CSV est produit, rien n'indique que l'étape contacts a échoué.

Hypothèse la plus probable : crédits Dropcontact épuisés (403 → `AuthError` →
`_dropcontact_disabled = True` pour tout le run), corrélation fortuite avec les runs Perplexity.

Les logs du client n'étant pas disponibles, le point 1 est traité comme un **défaut
d'observabilité** : un échec fournisseur ne doit plus pouvoir produire un run « réussi ». La
cause deviendra visible dès le prochain run.

---

## 3. Architecture cible

### 3.1 Réordonnancement du pipeline

L'ordre `scoring → preuves` devient `preuves → scoring → rédaction`.

```
2  Scraping Apollo
3a Recherche LinkedIn + site      + contrôle de cohérence léger        (modifié)
3b Dropcontact                    + abandon si le 1er batch échoue     (modifié)
3c Hunter
4  Hit score
5  Collecte de preuves            site + LinkedIn + Perplexity         (ex-6a + ex-7 fusionnés)
6  Extraction de faits            LLM, sortie factuelle sourcée        (nouveau)
7  Évaluation                     Python pur : score, tier, disqualif. (réécrit)
8  Rédaction de l'angle           LLM, leads qualifiés uniquement      (nouveau)
```

Impact coût : neutre à légèrement inférieur. Perplexity et le scraping tournent déjà sur
tous les hit leads ; la rédaction d'angle passe de « tous les hit leads » à « les leads non
disqualifiés ».

### 3.2 Modules

| Module | Rôle | Remplace |
|---|---|---|
| `enrichers/evidence_collector.py` | Orchestre site + LinkedIn + Perplexity, retourne un objet `Evidence` par lead | appels dispersés dans `pipeline_runner` |
| `enrichers/fact_extractor.py` | LLM, température 0 : extrait des faits sourcés. Aucune note, aucune prose commerciale | partie analyse de `gpt_enricher.py` |
| `processors/icp_scorer.py` | Python pur : `evidence_level`, score, tier, disqualification | version LLM actuelle |
| `enrichers/angle_writer.py` | LLM : `activity_summary` + `conversion_angle` à partir des faits validés | partie rédaction de `gpt_enricher.py` |
| `processors/coherence.py` | Contrôle société / site / pays, léger puis complet | néant |
| `api/provider_status.py` | Agrégation des `StepOutcome` par fournisseur | néant |

`enrichers/gpt_enricher.py` est supprimé une fois `fact_extractor` et `angle_writer` en place.

---

## 4. Contrat de preuve

### 4.1 Sortie de `fact_extractor`

Chaque fait porte obligatoirement une source parmi `website`, `linkedin`, `perplexity`.

```json
{
  "identite_confirmee": true,
  "pays":     {"value": "Maroc",      "source": "website"},
  "secteur":  {"value": "immobilier", "source": "website"},
  "effectif": {"value": 45,           "source": "perplexity"},
  "est_concurrent": false,
  "maturite_digitale": {"value": 4,   "source": "perplexity"},
  "signaux": [
    {"type": "recrutement_marketing", "date": "2026-04",
     "source": "perplexity", "citation": "..."}
  ]
}
```

Règle appliquée **en Python, après réception** : tout fait dont `source` est absente, vide
ou non reconnue est supprimé avant scoring. Le modèle ne peut pas contourner la règle en se
déclarant confiant.

`identite_confirmee` remplace `inconsistency_detected` et reprend les règles anti-faux-positifs
déjà écrites dans le prompt actuel de `gpt_enricher.py` (localisation Apollo corrompue, ville
vs pays compatible, job_title imparfait → ne pas flagger).

### 4.2 `evidence_level`

Calculé mécaniquement, jamais déclaré par le modèle. Une source est dite *exploitable* si :

- `website` : le site a passé le contrôle de cohérence **et** le texte extrait fait ≥ 200 caractères ;
- `perplexity` : au moins un des trois champs est non vide et différent de
  « Aucun signal récent identifié ».

LinkedIn n'entre pas dans le calcul : `scrapers/website_scraper.py` force `linkedin_text = ""`,
le profil n'étant jamais scrapé pour éviter le bannissement du compte. Le champ reste dans les
structures pour compatibilité mais ne constitue pas une source.

**La règle est adaptative** : l'exigence porte sur les fournisseurs réellement activés pour le
run, pas sur une liste fixe. Soit `attendues` l'intersection entre `{website, perplexity}` et les
fournisseurs activés (clé API présente, étape non désactivée) :

| Condition | `evidence_level` |
|---|---|
| `identite_confirmee = false`, ou 0 source exploitable | `none` |
| au moins 1 source exploitable, mais moins que `attendues` | `weak` |
| toutes les sources `attendues` sont exploitables, et `identite_confirmee = true` | `sufficient` |

Justification : sans clé Perplexity, une règle fixe à deux sources rendrait `sufficient`
inatteignable et basculerait la totalité du portefeuille en `cold` — or c'est précisément le
mode que le client utilise aujourd'hui avec satisfaction. On sanctionne un lead pour lequel les
fournisseurs activés n'ont rien produit, jamais pour un fournisseur que l'opérateur a coupé.

**Mise à jour du 2026-08-11 — retour pilote : un site injoignable n'est pas une source muette.**
Astrak France (distributeur de pièces d'usure pour engins de chantier) a été mesuré `evidence_level
= weak` alors que Perplexity documentait effectif, secteur, pays et trois signaux datés : son site
`astrakgroup.fr` était injoignable au moment du scraping (étape 5/6a), ce qui produisait exactement
le même `website_text = ""` qu'un site qui aurait répondu 200 avec une page vide. Les deux cas sont
pourtant de nature différente et le principe ci-dessus s'étend à cette panne subie exactement comme
il s'étend à un fournisseur coupé par l'opérateur :

- **Fournisseur indisponible pour ce lead** (site injoignable : erreur réseau, DNS, timeout, refus
  de connexion, ou statut d'erreur HTTP) → le fournisseur n'a pas pu se prononcer, donc `website`
  sort de `attendues` pour ce lead précis. C'est le même raisonnement que « fournisseur désactivé
  par l'opérateur » de l'alinéa ci-dessus, appliqué au niveau du lead plutôt qu'au niveau du run.
- **Fournisseur disponible mais silencieux** (le site répond, la page est pauvre ou vide) → le
  fournisseur a eu sa chance et n'a rien produit ; `website` reste dans `attendues` et son silence
  continue de plafonner l'`evidence_level` à `weak`. C'est exactement le cas que la règle originale
  visait à sanctionner, et il ne change pas.

Techniquement : `scrapers/website_scraper.py::_scrape_website` distingue désormais les deux issues
au lieu d'avaler toute exception dans un `except Exception: return ""` commun. Une
`requests.exceptions.RequestException` (erreur réseau, DNS, timeout, connexion refusée, ou
`raise_for_status()`) pose `website_unreachable = True` sur le lead ; une page atteinte mais pauvre
laisse `website_unreachable = False` avec un `website_text` vide ou court, comportement inchangé.
`processors/evidence.py::Evidence` porte le nouveau champ `website_unreachable: bool = False`, et
`expected_sources` retire `"website"` de l'ensemble attendu quand il est vrai — la même ligne qui
retire déjà un fournisseur non activé pour le run, appliquée cette fois à un fournisseur activé mais
en panne pour ce lead. Un lead sans URL de site du tout (`website` absent ou vide) n'a jamais émis
de requête : il n'est ni joignable ni injoignable, et `website_unreachable` reste `False` pour lui —
seul un site qu'on a *essayé* d'atteindre et qui a refusé de répondre compte comme fournisseur en
panne. Cas adjacents non traités par ce correctif, laissés pour un arbitrage séparé : « aucun site
trouvé » (`website_check_reason = "aucun site candidat trouvé"`) et « site rejeté pour incohérence »
(`website_rejected` renseigné) — dans les deux CSV du run pilote du matin du 2026-08-11
(`leads_final_20260811_104801_1b78c172.csv`, 10 leads, et `leads_final_20260811_114838_f15d0081.csv`,
12 leads), aucun des 22 leads ne relève de l'un ou l'autre cas ; 6 relèvent en revanche de la
vérification légère à l'étape 3a (`website_check_reason = "site injoignable"`, distincte du
scraping lourd à l'étape 5/6a que ce correctif modifie, mais portant sur la même URL et donc
fortement corrélée).

Invariants vérifiés par `tests/test_evidence.py` et `tests/test_website_scraper.py` : un lead sans
aucune source exploitable reste `none` même site injoignable ; un site injoignable avec Perplexity
substantiel atteint `sufficient` (cas Astrak) ; un site joignable mais vide avec Perplexity
substantiel reste `weak` (pour ne plus jamais confondre les deux) ; `identite_confirmee = False`
force `none` dans tous les cas, y compris site injoignable.

---

## 5. Moteur de scoring déterministe

Pondération des axes inchangée : secteur 20 %, taille 20 %, localisation 20 %, signaux 40 %.
Les tables ci-dessous vivent dans un fichier de configuration versionné
(`config/icp_rules.json`), pas dans un prompt. Format JSON et non YAML : le projet n'embarque
pas PyYAML et cette refonte n'a pas à ajouter une dépendance pour un fichier de règles.

### 5.1 Table des axes

**secteur** (20 %)

| Cas | Points |
|---|---|
| e-commerce, SaaS, services B2B, immobilier, éducation, santé, tourisme | 100 |
| autre secteur non exclu | 50 |
| secteur non sourcé | 0 |
| industrie lourde, agriculture | → disqualification |

**taille** (20 %)

| Effectif | Points |
|---|---|
| 10 – 500 | 100 |
| 5 – 9 | 60 |
| 501 – 1000 | 40 |
| < 5 ou > 1000 | → disqualification |
| non sourcé | 0 |

**localisation** (20 %)

| Pays | Points |
|---|---|
| Maroc | 100 |
| Afrique francophone | 90 |
| France | 80 |
| Belgique, Suisse, Luxembourg, Québec | 50 |
| hors des listes ci-dessus | → disqualification |
| non sourcé | 0 |

Chaque zone est une liste explicite de pays dans `icp_rules.json`. « Afrique francophone » par
défaut : Maroc, Algérie, Tunisie, Sénégal, Côte d'Ivoire, Cameroun, Gabon, Bénin, Burkina Faso,
Mali, Niger, Togo, Guinée, Congo, RDC, Madagascar, Mauritanie, Tchad. Aucune inférence
géographique n'est laissée au modèle : il renvoie un pays, la table décide.

**signaux** (40 %)

| Signaux sourcés | Points |
|---|---|
| ≥ 3 dont au moins 1 récent | 100 |
| ≥ 3, aucun récent | 80 |
| 2 | 70 |
| 1 | 40 |
| 0 | **0** |

Un signal est *récent* si son champ `date` est renseigné et postérieur à la date du run moins
six mois. Un signal sans `date` est comptabilisé dans le total mais n'est jamais récent.

Ajustement maturité digitale, qui encode le quatrième motif de dépriorisation existant
(« présence digitale faible ou vieillissante » = client idéal) :

- `maturite_digitale ≤ 4` → +20 sur l'axe signaux, plafonné à 100 ;
- toute autre valeur, ou maturité non sourcée → aucun ajustement.

**Bonus seul, jamais de pénalité.** Une première version prévoyait −20 au-delà de 8. C'était une
réintroduction de l'inversion que ce chantier corrige : la maturité inconnue ne recevant aucun
ajustement, elle se serait placée *entre* les deux états connus, et « on n'a pas pu vérifier »
aurait battu « on a vérifié, c'est mauvais » de 20 points sur l'axe qui pèse 40 %. L'écart de 20
points entre maturité faible et maturité élevée est identique dans les deux encodages, donc
l'ordonnancement commercial voulu est préservé ; seule disparaît la prime à l'ignorance.

Règle générale qui en découle, applicable à tout ajustement futur : **acquérir un fait ne doit
jamais pouvoir faire baisser un score.** Tout nouveau critère s'encode en bonus, l'état non
renseigné servant de référence basse.

C'est le passage de « 0 signal = note inventée » à « 0 signal = 0 point » qui corrige
l'inversion constatée.

### 5.2 Ordre d'évaluation

**Mise à jour du 2026-08-11 — retour pilote : le concurrent ne disqualifie plus sans preuves
suffisantes.** Le design initial faisait de `est_concurrent = true` sourcé une exception qui
s'appliquait *avant* la porte de preuve, quel que soit `evidence_level`. Le pilote (10 leads) a
produit un faux positif direct : Astrak France, distributeur de pièces d'usure pour engins de
chantier, disqualifié « concurrent direct » d'une agence de communication avec
`evidence_level = "weak"` et `evidence_verified = False` — la seule règle de disqualification du
moteur qui pouvait se prononcer sans preuve suffisante. Elle ne le peut plus : la vérification du
concurrent est descendue après la porte de preuve, au même rang que les autres règles dures. Un
concurrent aux preuves insuffisantes ressort donc `cold` plafonné, non vérifié, comme tout lead
non étayé — voir `tests/test_icp_scorer.py::test_competitor_without_sufficient_evidence_is_cold_not_disqualified`.
Un concurrent avec `evidence_level = "sufficient"` reste disqualifié
(`test_competitor_with_sufficient_evidence_is_disqualified`). Le prompt de `fact_extractor.py`
resserre en miroir la définition de `est_concurrent` : il doit désormais s'agir du **métier
principal** de l'entreprise, pas d'une activité connexe ou d'un service parmi d'autres — en cas
de doute, le champ reste `null`.

1. **Porte de preuve.** Si `evidence_level ∈ {none, weak}` : `icp_score = min(score, 39)`,
   `icp_tier = "cold"`, `evidence_verified = False`, motif explicite dans `icp_rationale`.
   Aucune règle de disqualification n'est appliquée — on ne dispose pas des faits nécessaires
   pour l'affirmer. `est_concurrent = true` sourcé ne fait plus exception : voir la mise à jour
   ci-dessus.
2. **Disqualification.** Uniquement si `evidence_level = sufficient`. `icp_tier = "disqualified"`,
   `disqualification_reason` renseigné. `est_concurrent = true` sourcé est désormais une règle
   dure parmi les autres (secteur exclu, taille, zone géographique), évaluée à ce rang — plus une
   exception qui précède la porte de preuve.
3. **Tier normal.**

| Score | Tier |
|---|---|
| ≥ 70 | `hot` |
| 40 – 69 | `warm` |
| < 40 | `cold` |

Note : le code actuel utilise `> 70` pour `hot`. La cible utilise `≥ 70`.

### 5.3 Choix de restitution

Les leads non vérifiés sont **fusionnés dans `cold`** — pas de tier dédié. La distinction
« mauvais lead » / « lead non évaluable » reste lisible via la colonne booléenne
`evidence_verified` et le motif porté par `icp_rationale`.

---

## 6. Contrôle de cohérence société / site / pays

### 6.1 Correctifs dans `google_search.py`

1. `_clearbit_domain` : normalisation des deux noms (minuscules, suppression des formes
   juridiques SARL / SA / SAS / LLC / Inc / Ltd / GmbH, accents, ponctuation), puis
   **recouvrement de jetons** au lieu de `any(mot in nom)`. Liste noire de jetons génériques
   (`financial`, `group`, `tech`, `consulting`, `services`, `solutions`, `digital`,
   `international`, `partners`, `conseil`) qui ne peuvent pas valider un domaine à eux seuls.
2. `_find_company_website(company, location)` : la localisation entre dans la requête Serper /
   DuckDuckGo et sert de critère de départage entre candidats.
3. `netloc.lower().lstrip("www.")` → suppression de préfixe correcte.

### 6.2 Vérification légère en amont (étape 3a)

Simple `GET` de la page d'accueil, sans Playwright : `<title>`, meta description, mentions de
raison sociale. En cas d'incohérence : `website_coherent = False`, `website` déplacé
dans `website_rejected`, et **les 10 points de site ne sont pas attribués** au hit score.

Le contrôle sur le texte complet reste à l'étape 5 comme second filet, alimentant
`identite_confirmee`.

**Mise à jour du 2026-08-10 — retrait du contrôle de pays.** `check_site_coherence` ne compare
plus le pays déduit de `location` (Apollo) à celui déduit du contenu du site ; `detect_country`
et `COUNTRY_ALIASES` sont supprimés de `processors/coherence.py`, et le paramètre `location`
disparaît de `check_site_coherence` et de `verify_website`. Seule la vérification du nom
d'entreprise subsiste. Motif : la revue finale a montré deux faux rejets sur le marché
principal du client — un cabinet parisien évoquant « investir à Casablanca » rejeté pour
incohérence France/Maroc (la fenêtre de détection passée de 1 500 à 200 000 caractères capte
désormais ce genre de mention en aparté), et une société tunisienne mentionnant un partenaire
à Lausanne classée Suisse (le départage se faisait sur la longueur brute de l'alias). Un rejet
coûte 10 points de hit score et empêche `evidence_level="sufficient"`. Compromis assumé : perte
de la détection d'homonymie transfrontalière (ex. deux entités sans lien nommées « Atlas
Technologies », l'une à Paris, l'autre à Dakar), au bénéfice de zéro faux rejet sur les
prospects franco-maghrébins légitimes. `_find_company_website(company, location)` continue en
revanche d'utiliser `location` pour construire sa requête de recherche — seul le contrôle de
cohérence perd ce paramètre. La table `country_aliases` propre à `processors/icp_rules.py`
(scoring de l'axe localisation) n'est pas concernée.

---

## 7. Durcissement des échecs fournisseur

### 7.1 `StepOutcome`

Chaque étape retourne :

```python
StepOutcome(
    provider: str,             # "dropcontact" | "hunter" | "serper" | "perplexity" | "anthropic"
    status: str,               # "ok" | "degraded" | "failed"
    reason: str | None,
    leads_affected: int,
)
```

Agrégé dans `JobResult.provider_status`, persisté dans l'historique, exposé par
`GET /api/results/{job_id}` et affiché en bandeau de santé dans l'interface après chaque run.

### 7.2 Règles d'arrêt

- **Dropcontact** : si le premier batch échoue alors que la clé est configurée, le run
  s'interrompt immédiatement avec une erreur explicite. Aujourd'hui, les batches suivants
  s'enchaînent en silence et produisent un CSV sans contacts.
- Un run dont un fournisseur critique a échoué se termine en `completed_with_errors`, jamais
  `done`.
- Les fournisseurs optionnels (Hunter, Perplexity) en échec produisent `degraded`, pas d'arrêt.

### 7.3 Réserve

Un préflight du solde Dropcontact était envisagé, mais leur API ne documente pas d'endpoint
crédits stable. L'abandon au premier batch couvre le même besoin sans dépendre d'un endpoint
incertain. À revérifier à l'implémentation ; si un endpoint fiable existe, l'ajouter en
complément et non en remplacement.

---

## 8. Impacts de bord

### 8.1 Schéma CSV

Colonnes ajoutées : `evidence_level`, `evidence_verified`, `disqualification_reason`,
`facts_json`, `website_coherent`, `website_rejected`.

Colonne supprimée : `llm_confidence` — remplacée par `evidence_level`, mesurée et non déclarée
par le modèle.

Colonnes conservées avec sémantique modifiée : `icp_score`, `icp_tier` (nouvelle valeur
`disqualified`), `icp_rationale`, `icp_scores_detail`.

Trois listes de colonnes sont aujourd'hui dupliquées — `main.py:CSV_COLUMNS`,
`pipeline_runner.py` (deux occurrences) — plus `enrich_fields` dans `_run_enrich_only_sync`.
Elles sont factorisées en une constante unique dans le même mouvement : quatre définitions
divergentes du même schéma sont une source de bug garantie.

### 8.2 Configuration

Sortent du prompt et entrent dans `config/icp_rules.json` : pondération des axes, seuils
d'effectif, zones géographiques, secteurs à forte valeur, secteurs exclus, jetons génériques,
seuils `evidence_level`. `prompts/icp_scoring.txt` disparaît ; le prompt d'extraction
factuelle le remplace.

### 8.3 Frontend

`ResultsTable.tsx`, `LeadDetailModal.tsx`, `StatsBar.tsx` : nouvelle valeur de tier
`disqualified`, remplacement du badge `llm_confidence` par `evidence_level`, affichage de
`disqualification_reason`, bandeau `provider_status`.

### 8.4 Persistance

`api/leads_db.py` : la liste `enrich_fields` et le mapping `enrich_data` suivent le nouveau
schéma. Les pools existants restent lisibles — les colonnes absentes ressortent à `None`.

---

## 9. Tests

Le scoring devenant déterministe, il est testable sans appel API. Jeu de cas figés
(faits d'entrée en JSON → score, tier et motif attendus) :

| Cas | Attendu |
|---|---|
| Amundi, effectif > 1000, sourcé | `disqualified`, motif « grand groupe » |
| houzing, site rentkasa.com rejeté, 0 autre source | `cold`, `evidence_verified = False` |
| PME marocaine 45 salariés, 1 signal daté d'avril 2026 | `warm` |
| PME marocaine, 3 signaux dont un récent, maturité 3/10 | `hot` |
| Agence de communication à Casablanca | `disqualified`, motif « concurrent direct » |
| Exploitation agricole, effectif 80 | `disqualified`, motif « secteur exclu » |
| Fait `secteur` renvoyé sans clé `source` | fait ignoré, axe secteur à 0 |

Tests unitaires également sur `coherence.py` (« Alp Financial » ne doit pas accepter
`ft.com`) et sur la correction `lstrip` (`wework.com` reste `wework.com`).

---

## 10. Hors périmètre

Signalé sans être traité : depuis l'ajout de Hunter, un email `accept_all` ne vaut plus que
20 points (`processors/hit_calculator.py`, `_EMAIL_STATUS_WEIGHTS`). Avec `HIT_THRESHOLD = 50`,
un lead avec email `accept_all` + LinkedIn tombe à 50 pile, et sans LinkedIn devient no-hit.
Le volume de hit leads a mécaniquement baissé depuis cette version. Arbitrage à conduire
séparément avec le client.

---

## 11. Décisions actées

| Question | Décision |
|---|---|
| Logs client disponibles pour confirmer le point 1 | Non — traité comme un durcissement d'observabilité |
| Architecture du scoring | Preuves d'abord, extraction factuelle par LLM, score calculé en Python |
| Motifs de disqualification | Les quatre motifs déjà présents dans `prompts/icp_scoring.txt`, convertis en règles dures |
| Sort des leads non vérifiés | Fusionnés dans `cold`, distingués par `evidence_verified` |

---

## 12. Décisions prises pendant l'implémentation

Ces arbitrages ont été tranchés en cours de route, après que le code a révélé ce que le design
ne pouvait pas anticiper. Ils sont consignés ici parce que l'historique git sera écrasé en un
commit unique : sans cette section, il faudrait les redécouvrir.

### 12.1 Maturité digitale : bonus seul, jamais de pénalité

Le design prévoyait `+20` sous 4 et `−20` au-delà de 8. C'était une réintroduction de
l'inversion que ce chantier corrige : une maturité **non sourcée** ne recevant aucun ajustement,
elle se plaçait entre les deux états connus, et « on n'a pas pu vérifier » battait « on a
vérifié, c'est mauvais » de 20 points sur l'axe qui pèse 40 %. Mesuré : le même lead passait de
76 (`hot`) à 68 (`warm`) **en gagnant un fait**.

Règle générale qui en découle, applicable à tout critère futur : **acquérir un fait ne doit
jamais pouvoir faire baisser un score.** Tout nouvel ajustement s'encode en bonus, l'état non
renseigné servant de référence basse.

### 12.2 Un fournisseur critique dégradé bascule le run en `completed_with_errors`

`failed_batches` ne compte que les pannes d'infrastructure — un lot jamais soumis ou jamais
revenu. Un contact simplement introuvable laisse `email = None` après un lot **réussi** et
n'incrémente rien. Un seul lot en échec signifie donc ~50 leads jamais tentés, ce qui n'est
jamais un résultat légitime. Le CSV reste livré : `completed_with_errors` est un drapeau, pas
un blocage. Un seuil de tolérance reste possible en changeant un mot dans
`ProviderRegistry.has_critical_failure`.

### 12.3 Un libellé de pays non reconnu ne disqualifie pas

Une comparaison exacte contre une liste française disqualifiait « Morocco », « Tunisia » ou
« Maroc (Casablanca) » — sur le marché principal du client. Deux mesures : canonicalisation via
une table de 49 pays dans `config/icp_rules.json`, et surtout **un libellé non reconnu donne 0
sur l'axe localisation sans prononcer de disqualification.** On ne prononce pas un verdict qu'on
ne peut pas étayer. Conséquence acceptée : un pays absent de la table sort `warm` plutôt que
`disqualified` — ajouter le pays au JSON suffit à le corriger.

### 12.4 Le contrôle de cohérence de pays a été retiré

Décision du propriétaire du projet, après démonstration par sonde que la comparaison de pays
produisait des rejets durs sur le marché du client : un cabinet parisien évoquant « investir à
Casablanca » était rejeté pour incohérence France/Maroc, et une société tunisienne mentionnant
Lausanne se voyait attribuer la Suisse. Un rejet coûte 10 points de hit score, sort souvent le
lead du seuil, et rend `evidence_level = sufficient` inatteignable.

**Ce qu'on perd :** la détection d'homonymie transfrontalière — un cabinet parisien « Atlas
Technologies » face à un site agroalimentaire dakarois du même nom passe désormais. Le compromis
est épinglé par `test_cross_border_homonym_is_now_accepted`, pour qu'il reste une décision et
non un oubli.

**Ce qu'on garde :** la vérification du nom d'entreprise, qui est la partie solide et testée, et
qui traite les cas d'origine (« Alp Financial » → *Financial Times*, « Houzing » → *Rentkasa*).

### 12.5 Points laissés ouverts

- **Barème email non vérifié.** `hit_calculator` accorde toujours 40 points pleins à un email
  qu'Hunter n'a pas pu vérifier. L'événement est désormais visible dans `provider_status`, mais
  le barème lui-même demande un arbitrage produit.
- **Seuils de `config/icp_rules.json`.** Effectif 5-1000, zones, secteurs exclus : valeurs par
  défaut déduites de l'ancien prompt, à valider avec le client avant un run réel.
- **`App.tsx` ignore le `job_id` d'un enrichissement de pool** (défaut préexistant) : ce flux
  n'affiche ni progression ni bandeau de santé. Les données sont correctes en base et dans le CSV.
- **Taux de `cold` à surveiller au pilote.** Un site injoignable ou trop pauvre rend
  `sufficient` inatteignable. Le plancher `MIN_SOURCE_CHARS = 200` et la porte de cohérence
  doivent être réévalués sur données réelles, pas par raisonnement.

---

## 13. Enseignements du run pilote (10 leads, 11 août 2026)

Le premier run réel a révélé trois défauts que le raisonnement n'avait pas trouvés. Il a
aussi confirmé que le dispositif de détection fonctionne : le run est sorti en `done`, les
2 emails sur 10 étaient un vrai résultat Dropcontact et non une panne masquée, aucun site
n'a été écarté à tort, et les `location` Apollo toutes corrompues (« Excellent », « Good »)
n'ont eu aucun impact puisque le pays vient désormais du site.

### 13.1 `est_concurrent` disqualifiait sans preuves suffisantes

Astrak France, distributeur de pièces d'usure pour engins de chantier, a été disqualifié
« concurrent direct » d'une agence de communication, avec `evidence_level = "weak"`. C'était
la seule règle dure exemptée de la porte de preuve. Elle y est désormais soumise comme les
autres : on ne prononce pas un verdict qu'on ne peut pas étayer.

### 13.2 Le vocabulaire des secteurs ne correspondait à rien

Le modèle renvoyait des libellés libres — « datacenters », « recherche clinique »,
« logement social » — que la table de scoring ne connaissait pas. Neuf leads sur dix
retombaient donc à 50/100. Le vocabulaire est maintenant fermé et injecté dans le prompt
depuis `icp_rules.json`, qui reste la source de vérité.

**Règle pour toute évolution de `sector_aliases` : un alias est un synonyme, jamais un
jugement de classement.** « Hôtellerie » *est* du tourisme, « formation » *est* de
l'éducation. En revanche « datacenters » n'est pas du SaaS et « logement social » n'est pas
de l'immobilier au sens de cet ICP : ce sont des rapprochements de proximité, et les
admettre transforme la table en levier discret de gonflement des scores. Cinq alias de ce
type ont été retirés après avoir constaté qu'ils faisaient passer un constructeur de
datacenters et un office public de l'habitat de `cold` à `warm`. Un secteur non reconnu
vaut `other` (50) — « on sait ce qu'ils font, ce n'est pas prioritaire » — ce qui est le
message juste.

À revoir uniquement sur données de conversion réelles du portefeuille BoxCom, pas par
intuition.

### 13.3 Les deux axes vides avaient des causes, pas un barème erroné

`taille` (20 %) et `signaux` (40 %) étaient à zéro pour presque tous les leads. Deux causes
concrètes, aucune liée à la pondération :

- **Effectif** : Perplexity le renvoie sous forme de fourchette (« Effectif estimé: 11-50
  employés »), et le prompt d'extraction exigeait un entier sans dire quoi faire d'une
  fourchette. Le modèle convertissait « 50-100 » en 75 mais rendait `null` sur « 11-50 ».
  La règle est désormais explicite : milieu de fourchette arrondi à l'entier inférieur.
- **Signaux** : l'appel Perplexity passait `search_recency_filter: "month"` alors que le
  prompt demandait « les signaux des 6 derniers mois ». La recherche était six fois plus
  étroite que la question, d'où « Aucun signal récent identifié » neuf fois sur dix. Le
  filtre est passé à `"year"` et chaque signal doit être daté en `AAAA-MM`.

**Les poids et les seuils de tier n'ont volontairement pas été touchés.** Corriger les
causes et recalibrer le barème en même temps empêcherait de savoir ce qui a produit l'effet.
La recalibration éventuelle se fera après un nouveau run, sur la distribution réellement
observée.
