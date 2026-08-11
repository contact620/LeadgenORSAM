# Refonte scoring ICP et fiabilisation du pipeline — Plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rendre le scoring ICP factuel et reproductible, produire de vrais verdicts négatifs, empêcher l'association d'un prospect à un site sans rapport, et interdire qu'un échec fournisseur produise un run marqué « réussi ».

**Architecture :** Le scoring passe après la collecte de preuves. Un LLM à température 0 extrait des faits obligatoirement sourcés ; Python les valide, calcule le score, le tier et la disqualification à partir de tables versionnées ; un second LLM rédige l'angle commercial uniquement pour les leads retenus. La cohérence société / site / pays est vérifiée avant l'attribution du hit score.

**Tech Stack :** Python 3.11+, FastAPI, Pydantic v2, pandas, requests, anthropic SDK, pytest (nouveau, dev only). Frontend React 19 + TypeScript + Tailwind v4.

**Spec de référence :** [`docs/superpowers/specs/2026-08-10-scoring-icp-et-fiabilite-pipeline-design.md`](../specs/2026-08-10-scoring-icp-et-fiabilite-pipeline-design.md)

## Global Constraints

- **Un commit par tâche, sur `fix/scoring-icp-fiabilite-pipeline` uniquement.** Ne jamais pousser (`git push` interdit), ne jamais créer de branche supplémentaire, ne jamais toucher à `develop`. L'utilisateur écrasera l'historique en un commit unique à la fin s'il le souhaite.
- **Ne jamais ajouter `docs/` à un commit.** Le spec et ce plan restent non suivis : `git add` porte uniquement sur les fichiers de la tâche en cours. Un `git add .` est interdit.
- **Message de commit :** format conventionnel, en français, sans ligne `Co-Authored-By`.
- **Aucune nouvelle dépendance runtime.** Seul `pytest>=8.0` est ajouté à `requirements.txt`, pour les tests. Pas de PyYAML (les règles sont en JSON), pas de BeautifulSoup (extraction texte par regex, comme l'existant).
- **Plateforme Windows, shell PowerShell.** Les commandes de test s'écrivent `python -m pytest ...`. `&&` n'existe pas en PowerShell 5.1 : une commande par ligne.
- **Langue.** Docstrings et noms de symboles en anglais, comme tout le code existant. Messages de log techniques en anglais (cohérence avec `enrichers/*`). Messages destinés à l'utilisateur final — événements SSE, `icp_rationale`, `disqualification_reason`, erreurs remontées à l'UI — en français.
- **Modèles Anthropic.** Extraction factuelle : `claude-haiku-4-5-20251001` (appels en lot, tâche mécanique). Rédaction de l'angle : `config.LLM_MODEL` (défaut `claude-sonnet-4-6`). Ne jamais coder en dur un identifiant de modèle ailleurs que dans ces deux modules.
- **Températures.** Extraction factuelle : `temperature=0`. Rédaction : `temperature=0.3` (valeur actuelle de `gpt_enricher`).
- **Pas de régression sur les pools existants.** `api/leads_db.py` doit continuer à lire les pools créés avant la refonte : les colonnes absentes ressortent à `None`, jamais une exception.

---

## Structure des fichiers

**Créés**

| Fichier | Responsabilité |
|---|---|
| `tests/conftest.py` | Ajoute la racine projet au `sys.path` pour les imports de test |
| `tests/test_coherence.py` | Primitives de comparaison de noms et contrôle de cohérence |
| `tests/test_evidence.py` | Calcul de `evidence_level` |
| `tests/test_icp_rules.py` | Chargement et validation des règles |
| `tests/test_icp_scorer.py` | Moteur de scoring déterministe — cas figés du spec §9 |
| `tests/test_fact_extractor.py` | Validation des sources, suppression des faits non sourcés |
| `tests/test_lead_schema.py` | Unicité du schéma de colonnes |
| `tests/test_provider_status.py` | Agrégation des `StepOutcome` |
| `lead_schema.py` | Définition unique de `CSV_COLUMNS` et `ENRICH_FIELDS` |
| `config/icp_rules.json` | Tables de scoring et de disqualification |
| `processors/coherence.py` | Normalisation de noms, correspondance par jetons, contrôle site/pays |
| `processors/evidence.py` | Structure `Evidence` et calcul de `evidence_level` |
| `processors/icp_rules.py` | Chargement typé de `icp_rules.json` |
| `enrichers/fact_extractor.py` | Extraction LLM de faits sourcés + validation Python |
| `enrichers/angle_writer.py` | Rédaction `activity_summary` / `conversion_angle` |
| `enrichers/evidence_collector.py` | Orchestration site + Perplexity, construction de `Evidence` |
| `api/provider_status.py` | `StepOutcome`, `ProviderRegistry`, `ProviderFailure` |

**Modifiés**

| Fichier | Nature |
|---|---|
| `requirements.txt` | Ajout de `pytest` |
| `enrichers/google_search.py` | Correspondance stricte, localisation dans la requête, contrôle amont |
| `enrichers/dropcontact.py` | Abandon si le premier lot échoue, remontée d'un `StepOutcome` |
| `enrichers/hunter_verifier.py` | Remontée d'un `StepOutcome` |
| `enrichers/perplexity_enricher.py` | Remontée d'un `StepOutcome` |
| `processors/icp_scorer.py` | Réécriture complète, déterministe |
| `processors/hit_calculator.py` | Ne compte les 10 points de site que si `website_coherent` |
| `api/models.py` | Champs de `LeadRecord`, `JobStats`, `JobResult` |
| `api/pipeline_runner.py` | Réordonnancement des étapes, registre fournisseurs, schéma unique |
| `api/leads_db.py` | `ENRICH_FIELDS` importé du schéma partagé |
| `main.py` | Même réordonnancement côté CLI, schéma unique |
| `frontend/src/lib/api.ts` | Types des nouveaux champs |
| `frontend/src/components/ResultsTable.tsx` | Tier `disqualified`, `evidence_level` |
| `frontend/src/components/LeadDetailModal.tsx` | Idem + motif de disqualification |
| `frontend/src/components/StatsBar.tsx` | Compteur `disqualified` |

**Supprimés en fin de parcours**

| Fichier | Remplacé par |
|---|---|
| `enrichers/gpt_enricher.py` | `fact_extractor.py` + `angle_writer.py` |
| `prompts/icp_scoring.txt` | `config/icp_rules.json` + prompt d'extraction |

**Ordre de livraison.** Les tâches 1 à 5 sont indépendantes de la refonte du scoring et apportent une valeur immédiate : elles corrigent l'association de sites erronés et rendent visible tout échec fournisseur. Elles peuvent être validées et livrées avant d'entamer la tâche 6.

---

## Task 1: Harnais de test et primitives de comparaison de noms

**Files:**
- Create: `tests/conftest.py`
- Create: `tests/test_coherence.py`
- Create: `processors/coherence.py`
- Modify: `requirements.txt`

**Interfaces:**
- Consumes: rien.
- Produces:
  - `processors.coherence.strip_www(netloc: str) -> str`
  - `processors.coherence.normalize_tokens(name: str) -> set[str]`
  - `processors.coherence.significant_tokens(name: str) -> set[str]`
  - `processors.coherence.names_match(candidate: str, reference: str, min_overlap: float = 0.5) -> bool`
  - `processors.coherence.GENERIC_TOKENS: frozenset[str]`
  - `processors.coherence.LEGAL_SUFFIXES: frozenset[str]`

- [ ] **Step 1 : ajouter pytest aux dépendances**

Ajouter en fin de `requirements.txt` :

```
pytest>=8.0.0
```

Puis installer : `python -m pip install pytest`

- [ ] **Step 2 : créer le conftest**

`tests/conftest.py` :

```python
"""Make the project root importable from tests."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
```

- [ ] **Step 3 : écrire les tests qui échouent**

`tests/test_coherence.py` :

```python
import pytest

from processors.coherence import (
    names_match,
    normalize_tokens,
    significant_tokens,
    strip_www,
)


def test_strip_www_removes_prefix_not_characters():
    assert strip_www("www.acme.com") == "acme.com"
    # Regression: lstrip("www.") ate leading characters of the domain itself
    assert strip_www("wework.com") == "wework.com"
    assert strip_www("world.example.org") == "world.example.org"


def test_normalize_tokens_lowercases_and_strips_accents_and_punctuation():
    assert normalize_tokens("Société Générale") == {"societe", "generale"}
    assert normalize_tokens("Acme, Inc.") == {"acme", "inc"}


def test_significant_tokens_drops_legal_suffixes_and_generic_words():
    assert significant_tokens("Acme Solutions SARL") == {"acme"}
    assert significant_tokens("Alp Financial") == {"alp"}
    assert significant_tokens("Financial Times") == {"times"}


def test_names_match_rejects_generic_word_only_overlap():
    # The reported bug: "Alp Financial" must not accept "Financial Times"
    assert names_match("Financial Times", "Alp Financial") is False


def test_names_match_rejects_unrelated_names():
    assert names_match("Rentkasa", "Houzing") is False


def test_names_match_accepts_same_company_with_legal_suffix():
    assert names_match("Acme Solutions SARL", "Acme Solutions") is True


def test_names_match_accepts_subset_of_tokens():
    assert names_match("Atlas Technologies", "Groupe Atlas") is True


def test_names_match_with_only_generic_tokens_falls_back_to_exact_tokens():
    # Both sides reduce to an empty significant set; only an exact token match passes
    assert names_match("Digital Services", "Digital Solutions") is False
    assert names_match("Digital Services", "Services Digital") is True


def test_names_match_handles_empty_input():
    assert names_match("", "Acme") is False
    assert names_match("Acme", "") is False
```

- [ ] **Step 4 : vérifier que les tests échouent**

Run : `python -m pytest tests/test_coherence.py -v`
Attendu : ÉCHEC — `ModuleNotFoundError: No module named 'processors.coherence'`

- [ ] **Step 5 : implémenter les primitives**

`processors/coherence.py` :

```python
"""
Company-name and website coherence helpers.

Used to reject search results that belong to a different company than the
Apollo prospect. The matching rule is deliberately strict: a single generic
word in common (``financial``, ``group``, ``digital``...) must never be
enough to accept a domain.
"""
import re
import unicodedata

# Legal forms carry no identifying signal.
LEGAL_SUFFIXES = frozenset({
    "sarl", "sa", "sas", "sasu", "eurl", "sci", "snc", "scop",
    "llc", "inc", "ltd", "limited", "plc", "corp", "corporation",
    "gmbh", "ag", "bv", "nv", "srl", "spa", "oy", "ab",
})

# Words too common to identify a company on their own.
GENERIC_TOKENS = frozenset({
    "financial", "finance", "group", "groupe", "holding", "holdings",
    "tech", "technologies", "technology", "consulting", "conseil",
    "services", "service", "solutions", "solution", "digital",
    "international", "partners", "associes", "company", "agency",
    "agence", "systems", "global", "france", "maroc", "africa",
})

_PUNCTUATION_RE = re.compile(r"[^a-z0-9\s]+")
_WHITESPACE_RE = re.compile(r"\s+")


def strip_www(netloc: str) -> str:
    """Remove a leading 'www.' prefix. Unlike lstrip, never eats characters."""
    lowered = netloc.lower()
    prefix = "www."
    if lowered.startswith(prefix):
        return lowered[len(prefix):]
    return lowered


def _deaccent(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def normalize_tokens(name: str) -> set[str]:
    """Lowercase, strip accents and punctuation, split into tokens."""
    if not name:
        return set()
    cleaned = _PUNCTUATION_RE.sub(" ", _deaccent(name).lower())
    return {t for t in _WHITESPACE_RE.split(cleaned) if t}


def significant_tokens(name: str) -> set[str]:
    """Tokens left once legal forms and generic words are removed."""
    return {
        t for t in normalize_tokens(name)
        if t not in LEGAL_SUFFIXES and t not in GENERIC_TOKENS and len(t) > 2
    }


def names_match(candidate: str, reference: str, min_overlap: float = 0.5) -> bool:
    """
    True when both names plausibly designate the same company.

    Compares significant tokens only. When either side has no significant
    token left, falls back to requiring identical full token sets — this
    keeps "Digital Services" from matching "Digital Solutions".
    """
    if not candidate or not reference:
        return False

    cand_sig = significant_tokens(candidate)
    ref_sig = significant_tokens(reference)

    if not cand_sig or not ref_sig:
        cand_all = normalize_tokens(candidate)
        ref_all = normalize_tokens(reference)
        return bool(cand_all) and cand_all == ref_all

    overlap = len(cand_sig & ref_sig) / min(len(cand_sig), len(ref_sig))
    return overlap >= min_overlap
```

- [ ] **Step 6 : vérifier que les tests passent**

Run : `python -m pytest tests/test_coherence.py -v`
Attendu : 9 tests PASSED

---

## Task 2: Contrôle de cohérence site / société / pays

**Files:**
- Modify: `processors/coherence.py`
- Modify: `tests/test_coherence.py`

**Interfaces:**
- Consumes: `names_match`, `normalize_tokens` (tâche 1).
- Produces:
  - `processors.coherence.CoherenceResult` — dataclass `(coherent: bool, verified: bool, reason: str | None)`
  - `processors.coherence.detect_country(text: str) -> str | None`
  - `processors.coherence.check_site_coherence(company: str, location: str, page_title: str, page_text: str) -> CoherenceResult`

`verified=False` signifie « contrôle non concluant, faute de données » et n'entraîne jamais de rejet : conformément au prompt existant, un faux positif coûte plus cher qu'un faux négatif.

- [ ] **Step 1 : écrire les tests qui échouent**

Ajouter à `tests/test_coherence.py` :

```python
from processors.coherence import CoherenceResult, check_site_coherence, detect_country


def test_detect_country_finds_known_country():
    assert detect_country("Notre siège est à Casablanca, Maroc.") == "Maroc"
    assert detect_country("Head office in Dakar, Senegal") == "Sénégal"


def test_detect_country_returns_none_when_absent():
    assert detect_country("We build software for everyone.") is None
    assert detect_country("") is None


def test_check_site_coherence_accepts_matching_title():
    result = check_site_coherence(
        company="Acme Solutions",
        location="Casablanca, Maroc",
        page_title="Acme Solutions — Agence immobilière",
        page_text="Acme Solutions accompagne les investisseurs au Maroc.",
    )
    assert result.coherent is True
    assert result.verified is True


def test_check_site_coherence_accepts_company_named_in_body_only():
    # Fixture must clear MIN_TEXT_FOR_VERDICT (80 chars) — the threshold is a
    # product property, never something to lower so a short fixture passes.
    result = check_site_coherence(
        company="Houzing",
        location="Paris, France",
        page_title="Accueil",
        page_text=(
            "Bienvenue chez Houzing, spécialiste de la gestion locative en France. "
            "Nous accompagnons les propriétaires bailleurs dans la mise en location "
            "et le suivi quotidien de leurs biens."
        ),
    )
    assert result.coherent is True
    assert result.verified is True


def test_check_site_coherence_rejects_unrelated_site():
    # The reported case: company "houzing" resolved to rentkasa.com
    result = check_site_coherence(
        company="Houzing",
        location="Paris, France",
        page_title="Rentkasa — Location de vacances",
        page_text="Rentkasa propose des locations saisonnières en Espagne.",
    )
    assert result.coherent is False
    assert result.verified is True
    assert "Rentkasa" in (result.reason or "")


def test_check_site_coherence_rejects_country_mismatch():
    result = check_site_coherence(
        company="Atlas Technologies",
        location="Paris, France",
        page_title="Atlas Technologies",
        page_text="Atlas Technologies, transformation de mangues à Dakar, Sénégal.",
    )
    assert result.coherent is False
    assert "Sénégal" in (result.reason or "")


def test_check_site_coherence_is_inconclusive_on_empty_page():
    result = check_site_coherence(
        company="Acme",
        location="Paris, France",
        page_title="",
        page_text="",
    )
    assert result.coherent is True
    assert result.verified is False


def test_check_site_coherence_ignores_corrupted_apollo_location():
    # Apollo's `location` is often garbage; it must never trigger a rejection
    result = check_site_coherence(
        company="Acme",
        location="Access Mobile",
        page_title="Acme",
        page_text="Acme est basée à Dakar, Sénégal.",
    )
    assert result.coherent is True
```

- [ ] **Step 2 : vérifier que les tests échouent**

Run : `python -m pytest tests/test_coherence.py -v`
Attendu : ÉCHEC — `ImportError: cannot import name 'CoherenceResult'`

- [ ] **Step 3 : implémenter le contrôle**

Ajouter à `processors/coherence.py` :

```python
from dataclasses import dataclass

# Countries the pipeline can recognise, with the aliases seen in the wild.
# Key = canonical label used everywhere downstream (including icp_rules.json).
COUNTRY_ALIASES: dict[str, tuple[str, ...]] = {
    "Maroc": ("maroc", "morocco", "casablanca", "rabat", "marrakech", "tanger"),
    "France": ("france", "paris", "lyon", "marseille", "bordeaux", "lille"),
    "Algérie": ("algerie", "algeria", "alger"),
    "Tunisie": ("tunisie", "tunisia", "tunis"),
    "Sénégal": ("senegal", "dakar"),
    "Côte d'Ivoire": ("cote d ivoire", "ivory coast", "abidjan"),
    "Cameroun": ("cameroun", "cameroon", "douala", "yaounde"),
    "Belgique": ("belgique", "belgium", "bruxelles", "brussels"),
    "Suisse": ("suisse", "switzerland", "geneve", "zurich", "lausanne"),
    "Luxembourg": ("luxembourg",),
    "Canada": ("canada", "quebec", "montreal"),
    "Espagne": ("espagne", "spain", "madrid", "barcelone", "barcelona"),
    "Royaume-Uni": ("royaume uni", "united kingdom", "london", "londres"),
    "États-Unis": ("etats unis", "united states", "usa", "new york", "california"),
    "Allemagne": ("allemagne", "germany", "berlin", "munich"),
}

MIN_TEXT_FOR_VERDICT = 80  # characters below which the page proves nothing


@dataclass
class CoherenceResult:
    """Outcome of a company/website coherence check."""
    coherent: bool
    verified: bool          # False = not enough data to conclude, never a rejection
    reason: str | None = None


def _normalized_text(value: str) -> str:
    """Lowercase, de-accent and collapse whitespace, PRESERVING word order."""
    cleaned = _PUNCTUATION_RE.sub(" ", _deaccent(value or "").lower())
    return f" {_WHITESPACE_RE.sub(' ', cleaned).strip()} "


def detect_country(text: str) -> str | None:
    """
    Return the first canonical country label found in the text, if any.

    Word order must be preserved here: multi-word aliases such as
    "cote d ivoire" cannot be matched against a sorted token set.
    Dictionary order decides ties when a text mentions several countries.
    """
    if not text:
        return None
    haystack = _normalized_text(text)
    for country, aliases in COUNTRY_ALIASES.items():
        for alias in aliases:
            needle = _normalized_text(alias)
            if needle.strip() and needle in haystack:
                return country
    return None


def check_site_coherence(
    company: str,
    location: str,
    page_title: str,
    page_text: str,
) -> CoherenceResult:
    """
    Decide whether a scraped page really belongs to the prospect's company.

    Rejects only on positive evidence of a different entity. A thin or empty
    page returns coherent=True with verified=False.
    """
    combined = f"{page_title} {page_text}".strip()
    if len(combined) < MIN_TEXT_FOR_VERDICT:
        return CoherenceResult(coherent=True, verified=False,
                               reason="page trop pauvre pour conclure")

    # 1. Company name present in the title or anywhere in the body
    name_found = names_match(page_title, company)
    if not name_found:
        company_sig = significant_tokens(company)
        body_tokens = normalize_tokens(page_text)
        name_found = bool(company_sig) and company_sig.issubset(body_tokens)

    if not name_found:
        title_label = page_title.strip() or "le site"
        return CoherenceResult(
            coherent=False, verified=True,
            reason=f"{title_label} ne mentionne pas « {company} »",
        )

    # 2. Country contradiction — only when BOTH sides yield a country.
    #    Apollo's `location` is frequently corrupted, so an undetectable
    #    location simply skips this check.
    apollo_country = detect_country(location)
    site_country = detect_country(combined)
    if apollo_country and site_country and apollo_country != site_country:
        return CoherenceResult(
            coherent=False, verified=True,
            reason=f"pays incohérent : Apollo indique {apollo_country}, "
                   f"le site indique {site_country}",
        )

    return CoherenceResult(coherent=True, verified=True)
```

- [ ] **Step 4 : vérifier que les tests passent**

Run : `python -m pytest tests/test_coherence.py -v`
Attendu : 17 tests PASSED

Si `test_check_site_coherence_rejects_country_mismatch` échoue, vérifier que le nom « Atlas Technologies » est bien reconnu à l'étape 1 : le rejet attendu vient du pays, pas du nom.

---

## Task 3: Recherche de site — correspondance stricte et localisation

**Files:**
- Modify: `enrichers/google_search.py:31-35` (blocklist), `:86-113` (`_clearbit_domain`), `:138-147` (`_pick_website`), `:150-168` (`_find_company_website`), `:173-225` (`find_linkedin_and_website`)
- Create: `tests/test_google_search.py`

**Interfaces:**
- Consumes: `processors.coherence.names_match`, `strip_www` (tâche 1).
- Produces:
  - `enrichers.google_search._clearbit_domain(company: str) -> str | None` — signature inchangée, logique durcie
  - `enrichers.google_search._find_company_website(company: str, location: str) -> str | None` — **nouveau paramètre**
  - `find_linkedin_and_website(lead)` renseigne désormais `lead["website"]` **et** ne renseigne plus rien d'autre ; la cohérence est posée en tâche 4.

- [ ] **Step 1 : écrire les tests qui échouent**

`tests/test_google_search.py` :

```python
from unittest.mock import patch

from enrichers.google_search import _clearbit_domain, _pick_website


def test_clearbit_rejects_generic_word_match():
    # Real failure: "Alp Financial" accepted "Financial Times" -> ft.com
    fake = [{"name": "Financial Times", "domain": "ft.com"}]
    with patch("enrichers.google_search.retry_api_call", return_value=fake):
        assert _clearbit_domain("Alp Financial") is None


def test_clearbit_accepts_real_match():
    fake = [{"name": "Acme Solutions SARL", "domain": "acme-solutions.ma"}]
    with patch("enrichers.google_search.retry_api_call", return_value=fake):
        assert _clearbit_domain("Acme Solutions") == "https://acme-solutions.ma"


def test_clearbit_scans_all_candidates_not_only_the_first():
    fake = [
        {"name": "Unrelated Corp", "domain": "unrelated.com"},
        {"name": "Houzing", "domain": "houzing.eu"},
    ]
    with patch("enrichers.google_search.retry_api_call", return_value=fake):
        assert _clearbit_domain("Houzing") == "https://houzing.eu"


def test_clearbit_returns_none_on_empty_results():
    with patch("enrichers.google_search.retry_api_call", return_value=[]):
        assert _clearbit_domain("Whatever") is None


def test_pick_website_skips_blocked_domains():
    urls = [
        "https://www.linkedin.com/company/acme",
        "https://fr.wikipedia.org/wiki/Acme",
        "https://acme.ma/about",
    ]
    assert _pick_website(urls) == "https://acme.ma/about"


def test_pick_website_does_not_truncate_domain_names():
    # Regression on lstrip("www."): "wework.com" must not become "ework.com"
    assert _pick_website(["https://wework.com"]) == "https://wework.com"
```

- [ ] **Step 2 : vérifier que les tests échouent**

Run : `python -m pytest tests/test_google_search.py -v`
Attendu : ÉCHEC sur `test_clearbit_rejects_generic_word_match` (retourne `https://ft.com`) et sur `test_clearbit_scans_all_candidates_not_only_the_first` (ne regarde que `results[0]`).

- [ ] **Step 3 : durcir `_clearbit_domain`**

Remplacer le corps de `_clearbit_domain` après le bloc `try/except` (lignes 104-113) par :

```python
    for hit in results or []:
        domain = (hit.get("domain") or "").strip()
        returned_name = (hit.get("name") or "").strip()
        if not domain:
            continue
        if names_match(returned_name, company):
            return f"https://{domain}"
        logger.debug(
            f"Clearbit rejected '{returned_name}' ({domain}) for '{company}' (name mismatch)"
        )
    return None
```

Ajouter en tête de fichier, sous les imports existants :

```python
from processors.coherence import names_match, strip_www
```

- [ ] **Step 4 : corriger `_pick_website`**

Remplacer la ligne 142 :

```python
            domain = urlparse(url).netloc.lower().lstrip("www.")
```

par :

```python
            domain = strip_www(urlparse(url).netloc)
```

- [ ] **Step 5 : faire entrer la localisation dans la recherche**

Remplacer `_find_company_website` (lignes 150-168) par :

```python
def _find_company_website(company: str, location: str = "") -> str | None:
    """Find company website: Clearbit first, Serper then DuckDuckGo as fallback."""
    website = _clearbit_domain(company)
    if website:
        logger.debug(f"Clearbit domain found for '{company}': {website}")
        return website

    # Location narrows the search and keeps homonymous foreign companies out.
    locality = (location or "").strip()
    query = f"{company} {locality} site officiel".strip() if locality else f"{company} official website"

    if not config._is_placeholder(config.SERPER_API_KEY):
        logger.debug(f"Clearbit miss for '{company}', trying Serper...")
        website = _pick_website(_serper_search(query))
        if website:
            return website

    logger.debug(f"Serper miss for '{company}', trying DuckDuckGo...")
    return _pick_website(_ddg_search(query))
```

Puis, dans `find_linkedin_and_website`, remplacer la ligne 215 :

```python
        lead["website"] = _find_company_website(company)
```

par :

```python
        lead["website"] = _find_company_website(company, lead.get("location", ""))
```

- [ ] **Step 6 : vérifier que les tests passent**

Run : `python -m pytest tests/test_google_search.py tests/test_coherence.py -v`
Attendu : 23 tests PASSED

---

## Task 4: Vérification légère du site avant le hit score

**Files:**
- Modify: `enrichers/google_search.py` (nouvelle fonction + appel dans `find_linkedin_and_website`)
- Modify: `processors/hit_calculator.py:52-57`
- Create: `tests/test_hit_calculator.py`
- Modify: `tests/test_google_search.py`

**Interfaces:**
- Consumes: `check_site_coherence`, `CoherenceResult` (tâche 2).
- Produces:
  - `enrichers.google_search.verify_website(url: str, company: str, location: str) -> CoherenceResult`
  - Chaque lead porte après l'étape 3a : `website`, `website_coherent: bool`, `website_rejected: str | None`, `website_check_reason: str | None`
  - `processors.hit_calculator.calculate_hit_score` n'attribue les 10 points de site que si `website_coherent` n'est pas `False`

- [ ] **Step 1 : écrire les tests qui échouent**

`tests/test_hit_calculator.py` :

```python
import config
from processors.hit_calculator import calculate_hit_score


def test_incoherent_website_does_not_earn_points():
    # website is SET but was rejected by the coherence check. With website=None
    # this test would pass even without the guard, proving nothing.
    lead = {
        "email": None,
        "linkedin_url": "https://linkedin.com/in/x",
        "phone": None,
        "website": "https://rentkasa.com",
        "website_coherent": False,
    }
    calculate_hit_score(lead)
    assert lead["hit_score"] == config.SCORE_LINKEDIN


def test_coherent_website_earns_points():
    lead = {
        "email": None,
        "linkedin_url": "https://linkedin.com/in/x",
        "phone": None,
        "website": "https://acme.ma",
        "website_coherent": True,
    }
    calculate_hit_score(lead)
    assert lead["hit_score"] == config.SCORE_LINKEDIN + config.SCORE_WEBSITE


def test_website_without_coherence_flag_still_earns_points():
    # Backward compatibility with pools scraped before this change
    lead = {"email": None, "linkedin_url": None, "phone": None, "website": "https://acme.ma"}
    calculate_hit_score(lead)
    assert lead["hit_score"] == config.SCORE_WEBSITE
```

Ajouter à `tests/test_google_search.py` :

```python
from processors.coherence import CoherenceResult


def test_verify_website_rejects_unrelated_page():
    from enrichers.google_search import verify_website
    html = "<html><head><title>Rentkasa</title></head><body>" + \
           "Rentkasa propose des locations saisonnieres en Espagne. " * 5 + \
           "</body></html>"

    class _Resp:
        status_code = 200
        text = html

        def raise_for_status(self):
            return None

    with patch("enrichers.google_search.requests.get", return_value=_Resp()):
        result = verify_website("https://rentkasa.com", "Houzing", "Paris, France")
    assert result.coherent is False


def test_verify_website_is_inconclusive_when_fetch_fails():
    from enrichers.google_search import verify_website
    with patch("enrichers.google_search.requests.get", side_effect=OSError("boom")):
        result = verify_website("https://acme.ma", "Acme", "Casablanca, Maroc")
    assert result.coherent is True
    assert result.verified is False
```

- [ ] **Step 2 : vérifier que les tests échouent**

Run : `python -m pytest tests/test_hit_calculator.py tests/test_google_search.py -v`
Attendu : ÉCHEC — `ImportError: cannot import name 'verify_website'` et `test_incoherent_website_does_not_earn_points` retourne 40 au lieu de 30.

- [ ] **Step 3 : implémenter `verify_website`**

Ajouter à `enrichers/google_search.py`, après `_find_company_website` :

```python
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
LIGHT_CHECK_MAX_CHARS = 1500


def _light_page_text(html: str) -> tuple[str, str]:
    """Extract (title, plain text head) from raw HTML without a parser dependency."""
    title_match = _TITLE_RE.search(html)
    title = _TAG_RE.sub(" ", title_match.group(1)).strip() if title_match else ""

    body = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    body = re.sub(r"<style[^>]*>.*?</style>", " ", body, flags=re.DOTALL | re.IGNORECASE)
    body = _TAG_RE.sub(" ", body)
    body = re.sub(r"&[a-zA-Z]+;", " ", body)
    body = re.sub(r"\s{2,}", " ", body).strip()
    return title, body[:LIGHT_CHECK_MAX_CHARS]


def verify_website(url: str, company: str, location: str) -> CoherenceResult:
    """
    Cheap homepage fetch to confirm the domain belongs to the prospect's company.

    Runs before the hit score so an unrelated site never earns its 10 points.
    A failed fetch is inconclusive, never a rejection.
    """
    if not url:
        return CoherenceResult(coherent=True, verified=False, reason="aucun site à vérifier")
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=8,
            allow_redirects=True,
        )
        resp.raise_for_status()
        title, text = _light_page_text(resp.text)
    except Exception as e:
        logger.debug(f"Light website check failed for {url}: {e}")
        return CoherenceResult(coherent=True, verified=False, reason="site injoignable")

    return check_site_coherence(company, location, title, text)
```

Compléter l'import en tête de fichier :

```python
from processors.coherence import CoherenceResult, check_site_coherence, names_match, strip_www
```

- [ ] **Step 4 : câbler la vérification dans l'enrichissement**

Dans `find_linkedin_and_website`, remplacer le bloc site (lignes 213-221) par :

```python
    # ── Website via Clearbit (+ Serper / DuckDuckGo fallback) ────────────────
    lead["website_rejected"] = None
    lead["website_check_reason"] = None
    if company:
        candidate = _find_company_website(company, lead.get("location", ""))
        if candidate:
            check = verify_website(candidate, company, lead.get("location", ""))
            lead["website_coherent"] = check.coherent
            lead["website_check_reason"] = check.reason
            if check.coherent:
                lead["website"] = candidate
                logger.debug(f"Website accepted for {company}: {candidate}")
            else:
                lead["website"] = None
                lead["website_rejected"] = candidate
                logger.info(f"Website rejected for '{company}': {candidate} — {check.reason}")
        else:
            lead["website"] = None
            lead["website_coherent"] = False
            logger.debug(f"No website found for {company}")
    else:
        lead["website"] = None
        lead["website_coherent"] = False
```

Puis, dans `enrich_leads_google`, ajouter au bloc de résumé (après la ligne 252) :

```python
    rejected = [l for l in leads if l.get("website_rejected")]
    if rejected:
        logger.info(
            f"Websites rejected for incoherence: {len(rejected)} "
            f"({', '.join(l.get('company', '?') for l in rejected[:5])})"
        )
```

- [ ] **Step 5 : conditionner les points de site**

Dans `processors/hit_calculator.py`, remplacer les lignes 56-57 :

```python
    if lead.get("website"):
        score += config.SCORE_WEBSITE
```

par :

```python
    # A website rejected by the coherence check must not earn points.
    # Absent flag = pool scraped before the check existed -> keep legacy behaviour.
    if lead.get("website") and lead.get("website_coherent") is not False:
        score += config.SCORE_WEBSITE
```

- [ ] **Step 6 : vérifier que les tests passent**

Run : `python -m pytest tests/ -v`
Attendu : 28 tests PASSED

---

## Task 5: Statut des fournisseurs et arrêt sur échec Dropcontact

**Files:**
- Create: `api/provider_status.py`
- Create: `tests/test_provider_status.py`
- Modify: `enrichers/dropcontact.py:142-213`
- Modify: `api/models.py:75-86`
- Modify: `api/pipeline_runner.py:191-261`, `:425-435`

**Interfaces:**
- Consumes: rien.
- Produces:
  - `api.provider_status.StepOutcome` — dataclass `(provider: str, status: str, reason: str | None, leads_affected: int)`
  - `api.provider_status.ProviderRegistry` — `.record(outcome)`, `.to_dict() -> dict[str, dict]`, `.has_critical_failure() -> bool`
  - `api.provider_status.ProviderFailure(Exception)` — `.provider`, `.reason`
  - `api.provider_status.CRITICAL_PROVIDERS: frozenset[str]`
  - `enrichers.dropcontact.enrich_leads_dropcontact(leads, registry=None)` — lève `ProviderFailure` si le **premier** lot échoue
  - `api.models.JobResult.provider_status: dict[str, dict]`

- [ ] **Step 1 : écrire les tests qui échouent**

`tests/test_provider_status.py` :

```python
import pytest

from api.provider_status import (
    ProviderFailure,
    ProviderRegistry,
    StepOutcome,
)


def test_registry_records_and_exports():
    reg = ProviderRegistry()
    reg.record(StepOutcome("dropcontact", "ok", None, 50))
    assert reg.to_dict()["dropcontact"]["status"] == "ok"
    assert reg.to_dict()["dropcontact"]["leads_affected"] == 50


def test_registry_detects_critical_failure():
    reg = ProviderRegistry()
    reg.record(StepOutcome("dropcontact", "failed", "crédits épuisés", 0))
    assert reg.has_critical_failure() is True


def test_degraded_optional_provider_is_not_critical():
    reg = ProviderRegistry()
    reg.record(StepOutcome("perplexity", "degraded", "quota atteint", 12))
    assert reg.has_critical_failure() is False


def test_degraded_critical_provider_flags_the_run():
    reg = ProviderRegistry()
    reg.record(StepOutcome("dropcontact", "degraded", "3 lot(s) en échec sur 10", 120))
    assert reg.has_critical_failure() is True


def test_skipped_critical_provider_does_not_flag_the_run():
    reg = ProviderRegistry()
    reg.record(StepOutcome("dropcontact", "skipped", "clé API absente", 0))
    assert reg.has_critical_failure() is False


def test_last_record_wins_for_a_provider():
    reg = ProviderRegistry()
    reg.record(StepOutcome("hunter", "ok", None, 10))
    reg.record(StepOutcome("hunter", "degraded", "429", 3))
    assert reg.to_dict()["hunter"]["status"] == "degraded"


def test_provider_failure_carries_context():
    err = ProviderFailure("dropcontact", "HTTP 403")
    assert err.provider == "dropcontact"
    assert "403" in err.reason
```

Créer `tests/test_dropcontact.py` :

```python
from unittest.mock import patch

import pytest

from api.provider_status import ProviderFailure, ProviderRegistry
from enrichers.dropcontact import _reset_state, enrich_leads_dropcontact


def _leads(n):
    return [{"first_name": f"A{i}", "last_name": "B", "company": "Acme"} for i in range(n)]


def test_first_batch_failure_aborts_the_run():
    _reset_state()
    with patch("enrichers.dropcontact.config.DROPCONTACT_API_KEY", "key"), \
         patch("enrichers.dropcontact._post_batch", return_value=None):
        with pytest.raises(ProviderFailure) as exc:
            enrich_leads_dropcontact(_leads(3), registry=ProviderRegistry())
    assert exc.value.provider == "dropcontact"


def test_missing_key_is_recorded_as_skipped_not_failed():
    _reset_state()
    reg = ProviderRegistry()
    with patch("enrichers.dropcontact.config.DROPCONTACT_API_KEY", ""):
        enrich_leads_dropcontact(_leads(2), registry=reg)
    assert reg.to_dict()["dropcontact"]["status"] == "skipped"
    assert reg.has_critical_failure() is False
```

- [ ] **Step 2 : vérifier que les tests échouent**

Run : `python -m pytest tests/test_provider_status.py tests/test_dropcontact.py -v`
Attendu : ÉCHEC — `ModuleNotFoundError: No module named 'api.provider_status'`

- [ ] **Step 3 : implémenter le registre**

`api/provider_status.py` :

```python
"""
Per-provider outcome tracking for a pipeline run.

A run that silently degrades is worse than a run that fails: the operator
ships a CSV without contacts and never learns why. Every enrichment step
records an outcome; a failure on a critical provider stops the run.
"""
from dataclasses import dataclass, field
from typing import Optional

# Providers whose failure invalidates the run's core deliverable.
CRITICAL_PROVIDERS = frozenset({"dropcontact"})

# status values: "ok" | "degraded" | "failed" | "skipped"


@dataclass
class StepOutcome:
    """Result of one provider's contribution to a run."""
    provider: str
    status: str
    reason: Optional[str] = None
    leads_affected: int = 0


class ProviderFailure(Exception):
    """Raised when a critical provider cannot deliver — aborts the run."""

    def __init__(self, provider: str, reason: str):
        self.provider = provider
        self.reason = reason
        super().__init__(f"{provider}: {reason}")


@dataclass
class ProviderRegistry:
    """Collects one outcome per provider; the latest record wins."""
    _outcomes: dict[str, StepOutcome] = field(default_factory=dict)

    def record(self, outcome: StepOutcome) -> None:
        self._outcomes[outcome.provider] = outcome

    def to_dict(self) -> dict[str, dict]:
        return {
            name: {
                "status": o.status,
                "reason": o.reason,
                "leads_affected": o.leads_affected,
            }
            for name, o in self._outcomes.items()
        }

    def has_critical_failure(self) -> bool:
        """
        True when a critical provider failed OR merely degraded.

        Degradation counts: `failed_batches` only ever tracks infrastructure
        failures — a batch never submitted or never returned. A contact that
        simply could not be found leaves email=None after a *successful*
        batch and never increments it. So one failed batch means ~50 leads
        were never even attempted, which must never be reported as a clean run.
        """
        return any(
            o.status in ("failed", "degraded") and name in CRITICAL_PROVIDERS
            for name, o in self._outcomes.items()
        )
```

- [ ] **Step 4 : durcir Dropcontact**

Dans `enrichers/dropcontact.py`, ajouter aux imports :

```python
from api.provider_status import ProviderFailure, ProviderRegistry, StepOutcome
```

Remplacer la signature et le bloc « clé absente » (lignes 142-153) par :

```python
def enrich_leads_dropcontact(leads: list[dict], registry: ProviderRegistry | None = None) -> list[dict]:
    """
    Enrich a list of leads with email and phone via Dropcontact.

    Processes in batches of DROPCONTACT_BATCH_SIZE. Modifies leads in place.
    Raises ProviderFailure when the very first batch fails: continuing would
    produce a CSV with no contact data and a run marked successful.
    """
    if config._is_placeholder(config.DROPCONTACT_API_KEY):
        logger.info("DROPCONTACT_API_KEY not set. Skipping email/phone enrichment.")
        for lead in leads:
            lead.setdefault("email", None)
            lead.setdefault("phone", None)
        if registry:
            registry.record(StepOutcome("dropcontact", "skipped", "clé API absente", 0))
        return leads
```

Remplacer le bloc d'échec de soumission (lignes 164-170) par :

```python
        request_id = _post_batch(batch)
        if not request_id:
            if batch_num == 1:
                raise ProviderFailure(
                    "dropcontact",
                    "le premier lot a échoué — clé invalide ou crédits épuisés. "
                    "Run interrompu pour ne pas produire un fichier sans contacts.",
                )
            failed_batches += 1
            logger.warning(f"Batch {batch_num} submission failed. Setting email/phone to None.")
            for lead in batch:
                lead.setdefault("email", None)
                lead.setdefault("phone", None)
            continue
```

Remplacer le bloc d'échec de polling (lignes 172-178) par :

```python
        enriched_data = _poll_batch(request_id)
        if not enriched_data:
            if batch_num == 1:
                raise ProviderFailure(
                    "dropcontact",
                    "le premier lot n'a jamais abouti (timeout de polling). "
                    "Run interrompu pour ne pas produire un fichier sans contacts.",
                )
            failed_batches += 1
            logger.warning(f"Batch {batch_num} polling failed. Setting email/phone to None.")
            for lead in batch:
                lead.setdefault("email", None)
                lead.setdefault("phone", None)
            continue
```

Déclarer `failed_batches = 0` à côté de `enriched_count = 0` (ligne 157), et remplacer le bloc final (lignes 208-213) par :

```python
    phone_count = sum(1 for l in leads if l.get("phone"))
    logger.info(
        f"Dropcontact enrichment complete. "
        f"{enriched_count}/{total} emails, {phone_count}/{total} phones found."
    )
    if registry:
        if failed_batches:
            registry.record(StepOutcome(
                "dropcontact", "degraded",
                f"{failed_batches} lot(s) en échec sur {(total + batch_size - 1) // batch_size}",
                enriched_count,
            ))
        else:
            registry.record(StepOutcome("dropcontact", "ok", None, enriched_count))
    return leads
```

- [ ] **Step 5 : exposer le statut dans le modèle et le runner**

Dans `api/models.py`, ajouter à `JobResult` (après la ligne 85) :

```python
    provider_status: dict[str, dict] = {}
```

Dans `api/pipeline_runner.py`, à l'intérieur de `_run_pipeline_sync`, juste après `_jobs[job_id].status = "running"` (ligne 192) :

```python
        from api.provider_status import ProviderFailure, ProviderRegistry
        registry = ProviderRegistry()
```

Remplacer l'appel Dropcontact (ligne 237) par :

```python
        leads = enrich_leads_dropcontact(leads, registry=registry)
```

Ajouter la construction du `JobResult` final (ligne 425) le champ :

```python
            provider_status=registry.to_dict(),
```

et remplacer `status="done"` par :

```python
            status="completed_with_errors" if registry.has_critical_failure() else "done",
```

Ajouter un handler dédié **avant** `except Exception as exc:` (ligne 480) :

```python
    except ProviderFailure as exc:
        message = f"Étape contacts interrompue — {exc.reason}"
        logging.getLogger("pipeline_runner").error(message)
        _jobs[job_id] = JobResult(job_id=job_id, status="error", error=message)
        from api.history import save_job as _save_hist
        meta = _job_meta.get(job_id, {})
        _save_hist(
            job_id=job_id, status="error",
            apollo_url=meta.get("apollo_url", ""),
            max_leads=meta.get("max_leads", 0),
            skip_gpt=meta.get("skip_gpt", False),
            started_at=meta.get("started_at", ""),
            finished_at=datetime.now().isoformat(),
            error=message,
        )
        error_payload = json.dumps({"type": "error", "data": {"message": message}})
        asyncio.run_coroutine_threadsafe(queue.put(error_payload), loop)
        return
```

Appliquer le même appel `registry=registry` dans `_run_scrape_only_sync` (ligne 593) en y instanciant également un `ProviderRegistry`, et y ajouter le même bloc `except ProviderFailure` (le corps peut se limiter à `_jobs[job_id] = JobResult(...)` + événement `error`, ce flux n'écrit pas d'historique détaillé).

- [ ] **Step 6 : vérifier que les tests passent et que le serveur démarre**

Run : `python -m pytest tests/ -v`
Attendu : 35 tests PASSED

Run : `python -c "import api.server"`
Attendu : aucune sortie, aucune exception d'import.

---

## Task 6: Schéma de colonnes unique

**Files:**
- Create: `lead_schema.py`
- Create: `tests/test_lead_schema.py`
- Modify: `main.py:43-69`
- Modify: `api/pipeline_runner.py:334-344`, `:755-758`, `:771-780`

**Interfaces:**
- Consumes: rien.
- Produces:
  - `lead_schema.CSV_COLUMNS: list[str]`
  - `lead_schema.ENRICH_FIELDS: list[str]`

Quatre définitions divergentes du même schéma existent aujourd'hui. Cette tâche les réduit à une, avant que les tâches suivantes n'ajoutent des colonnes.

- [ ] **Step 1 : écrire le test qui échoue**

`tests/test_lead_schema.py` :

```python
from lead_schema import CSV_COLUMNS, ENRICH_FIELDS


def test_columns_are_unique():
    assert len(CSV_COLUMNS) == len(set(CSV_COLUMNS))


def test_enrich_fields_are_all_exported():
    missing = [f for f in ENRICH_FIELDS if f not in CSV_COLUMNS]
    assert missing == []


def test_identity_columns_come_first():
    assert CSV_COLUMNS[:5] == ["first_name", "last_name", "company", "job_title", "location"]


def test_single_source_of_truth_is_used_everywhere():
    import api.pipeline_runner as runner
    import main
    assert main.CSV_COLUMNS is CSV_COLUMNS
    assert runner.CSV_COLUMNS is CSV_COLUMNS
```

- [ ] **Step 2 : vérifier que le test échoue**

Run : `python -m pytest tests/test_lead_schema.py -v`
Attendu : ÉCHEC — `ModuleNotFoundError: No module named 'lead_schema'`

- [ ] **Step 3 : créer le schéma partagé**

`lead_schema.py` à la racine :

```python
"""
Single source of truth for the exported lead schema.

Before this module the column list was duplicated in main.py and three times
in api/pipeline_runner.py, which guarantees divergence over time.
"""

CSV_COLUMNS: list[str] = [
    # Identity
    "first_name", "last_name", "company", "job_title", "location",
    # Contact
    "email", "email_status", "email_confidence", "phone",
    "linkedin_url", "website", "website_coherent", "website_rejected",
    # Hit scoring
    "hit_score", "is_hit",
    # ICP scoring
    "icp_score", "icp_tier", "icp_rationale", "icp_scores_detail",
    "disqualification_reason", "evidence_level", "evidence_verified",
    # AI enrichment
    "activity_summary", "conversion_angle", "facts_json",
    # Legacy fields, still produced by enrichers/gpt_enricher.py.
    # Removed in task 13, together with the module that produces them —
    # dropping them earlier would lose data already written to
    # lead_pool.enrich_data, and every intermediate commit must stay a safe
    # stopping point for a partial delivery.
    "inconsistency_detected", "inconsistency_reason", "llm_confidence",
    # Company intelligence
    "digital_maturity", "estimated_budget", "business_signals",
    # Deduplication
    "is_duplicate", "first_seen_at",
]

# Fields produced by the enrichment phase, persisted per lead in the pool DB.
ENRICH_FIELDS: list[str] = [
    "icp_score", "icp_tier", "icp_rationale", "icp_scores_detail",
    "disqualification_reason", "evidence_level", "evidence_verified",
    "activity_summary", "conversion_angle", "facts_json",
    "digital_maturity", "estimated_budget", "business_signals",
    # Legacy, removed in task 13 with gpt_enricher.py — see CSV_COLUMNS above.
    "inconsistency_detected", "inconsistency_reason", "llm_confidence",
]
```

- [ ] **Step 4 : remplacer les quatre duplications**

Dans `main.py`, supprimer les lignes 43-69 et ajouter aux imports :

```python
from lead_schema import CSV_COLUMNS
```

Dans `api/pipeline_runner.py`, supprimer les blocs `CSV_COLUMNS = [...]` des lignes 334-344 et 771-780, remplacer `enrich_fields = [...]` des lignes 755-758 par `enrich_fields = ENRICH_FIELDS`, et ajouter aux imports du haut de fichier :

```python
from lead_schema import CSV_COLUMNS, ENRICH_FIELDS
```

- [ ] **Step 5 : vérifier**

Run : `python -m pytest tests/ -v`
Attendu : 39 tests PASSED

Run : `python -c "import main; import api.pipeline_runner"`
Attendu : aucune exception.

---

## Task 7: Règles ICP versionnées

**Files:**
- Create: `config/icp_rules.json`
- Create: `processors/icp_rules.py`
- Create: `tests/test_icp_rules.py`

**Interfaces:**
- Consumes: rien.
- Produces:
  - `processors.icp_rules.IcpRules` — dataclass exposant `weights`, `high_value_sectors`, `excluded_sectors`, `zone_points`, `zone_countries`, `size_bands`, `size_disqualify_below`, `size_disqualify_above`, `signal_points`, `maturity_bonus`, `maturity_penalty`, `maturity_low_max`, `maturity_high_min`, `tier_hot_min`, `tier_warm_min`, `unverified_score_cap`
  - `processors.icp_rules.load_rules(path: str | None = None) -> IcpRules`
  - `processors.icp_rules.RULES_PATH: str`

**Note :** `config/` est un répertoire nouveau alors que `config.py` est un module existant à la racine. Python résout `import config` vers le module `.py`, qui a la priorité sur un paquet sans `__init__.py` — mais pour lever toute ambiguïté, le répertoire ne contient **aucun** `__init__.py` et n'est jamais importé : il est lu comme fichier de données.

- [ ] **Step 1 : écrire les tests qui échouent**

`tests/test_icp_rules.py` :

```python
import json

import pytest

from processors.icp_rules import IcpRules, load_rules


def test_default_rules_load():
    rules = load_rules()
    assert isinstance(rules, IcpRules)
    assert rules.weights["signaux"] == 0.40


def test_weights_sum_to_one():
    rules = load_rules()
    assert round(sum(rules.weights.values()), 6) == 1.0


def test_zone_countries_cover_zone_points():
    rules = load_rules()
    for zone in rules.zone_points:
        assert zone in rules.zone_countries, f"zone '{zone}' has points but no country list"


def test_tier_thresholds_are_ordered():
    rules = load_rules()
    assert rules.tier_hot_min > rules.tier_warm_min > rules.unverified_score_cap


def test_invalid_weights_are_rejected(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"weights": {"secteur": 0.9, "taille": 0.9,
                                           "localisation": 0.1, "signaux": 0.1}}),
                   encoding="utf-8")
    with pytest.raises(ValueError, match="weights"):
        load_rules(str(bad))
```

- [ ] **Step 2 : vérifier que les tests échouent**

Run : `python -m pytest tests/test_icp_rules.py -v`
Attendu : ÉCHEC — `ModuleNotFoundError: No module named 'processors.icp_rules'`

- [ ] **Step 3 : écrire le fichier de règles**

`config/icp_rules.json` :

```json
{
  "weights": { "secteur": 0.20, "taille": 0.20, "localisation": 0.20, "signaux": 0.40 },

  "high_value_sectors": [
    "e-commerce", "saas", "services b2b", "immobilier",
    "education", "sante", "tourisme"
  ],
  "excluded_sectors": [
    "industrie lourde", "agriculture", "extraction miniere", "siderurgie"
  ],
  "sector_points": { "high_value": 100, "other": 50, "unknown": 0 },

  "zone_countries": {
    "maroc": ["Maroc"],
    "afrique_francophone": [
      "Algérie", "Tunisie", "Sénégal", "Côte d'Ivoire", "Cameroun", "Gabon",
      "Bénin", "Burkina Faso", "Mali", "Niger", "Togo", "Guinée", "Congo",
      "RDC", "Madagascar", "Mauritanie", "Tchad"
    ],
    "france": ["France"],
    "francophonie_elargie": ["Belgique", "Suisse", "Luxembourg", "Canada"]
  },
  "zone_points": {
    "maroc": 100,
    "afrique_francophone": 90,
    "france": 80,
    "francophonie_elargie": 50
  },

  "size_bands": [
    { "min": 10,  "max": 500,  "points": 100 },
    { "min": 5,   "max": 9,    "points": 60 },
    { "min": 501, "max": 1000, "points": 40 }
  ],
  "size_disqualify_below": 5,
  "size_disqualify_above": 1000,

  "signal_points": {
    "three_or_more_recent": 100,
    "three_or_more": 80,
    "two": 70,
    "one": 40,
    "none": 0
  },
  "signal_recency_months": 6,

  "maturity_low_max": 4,
  "maturity_bonus": 20,

  "tier_hot_min": 70,
  "tier_warm_min": 40,
  "unverified_score_cap": 39,

  "competitor_keywords": [
    "agence de communication", "communication digitale", "marketing digital",
    "agence web", "agence creative", "regie publicitaire", "agence seo"
  ]
}
```

- [ ] **Step 4 : implémenter le chargeur**

`processors/icp_rules.py` :

```python
"""
Typed loader for config/icp_rules.json.

Scoring tables live in a versioned data file rather than inside a prompt:
the score must be reproducible and reviewable without an API call.
"""
import json
import os
from dataclasses import dataclass

RULES_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config", "icp_rules.json",
)

_REQUIRED_AXES = ("secteur", "taille", "localisation", "signaux")


@dataclass(frozen=True)
class IcpRules:
    weights: dict[str, float]
    high_value_sectors: list[str]
    excluded_sectors: list[str]
    sector_points: dict[str, int]
    zone_countries: dict[str, list[str]]
    zone_points: dict[str, int]
    size_bands: list[dict]
    size_disqualify_below: int
    size_disqualify_above: int
    signal_points: dict[str, int]
    signal_recency_months: int
    maturity_low_max: int
    maturity_high_min: int
    maturity_bonus: int
    maturity_penalty: int
    tier_hot_min: int
    tier_warm_min: int
    unverified_score_cap: int
    competitor_keywords: list[str]

    def country_zone(self, country: str) -> str | None:
        """Return the zone a country belongs to, or None if outside all zones."""
        if not country:
            return None
        for zone, countries in self.zone_countries.items():
            if country in countries:
                return zone
        return None


def load_rules(path: str | None = None) -> IcpRules:
    """Load and validate the ICP rule table."""
    target = path or RULES_PATH
    with open(target, "r", encoding="utf-8") as f:
        raw = json.load(f)

    weights = raw.get("weights", {})
    missing = [a for a in _REQUIRED_AXES if a not in weights]
    if missing:
        raise ValueError(f"icp_rules: missing weights for {', '.join(missing)}")
    if round(sum(weights.values()), 6) != 1.0:
        raise ValueError(f"icp_rules: weights must sum to 1.0, got {sum(weights.values())}")

    return IcpRules(
        weights=weights,
        high_value_sectors=raw.get("high_value_sectors", []),
        excluded_sectors=raw.get("excluded_sectors", []),
        sector_points=raw.get("sector_points", {"high_value": 100, "other": 50, "unknown": 0}),
        zone_countries=raw.get("zone_countries", {}),
        zone_points=raw.get("zone_points", {}),
        size_bands=raw.get("size_bands", []),
        size_disqualify_below=raw.get("size_disqualify_below", 5),
        size_disqualify_above=raw.get("size_disqualify_above", 1000),
        signal_points=raw.get("signal_points", {}),
        signal_recency_months=raw.get("signal_recency_months", 6),
        maturity_low_max=raw.get("maturity_low_max", 4),
        maturity_high_min=raw.get("maturity_high_min", 8),
        maturity_bonus=raw.get("maturity_bonus", 20),
        maturity_penalty=raw.get("maturity_penalty", 20),
        tier_hot_min=raw.get("tier_hot_min", 70),
        tier_warm_min=raw.get("tier_warm_min", 40),
        unverified_score_cap=raw.get("unverified_score_cap", 39),
        competitor_keywords=raw.get("competitor_keywords", []),
    )
```

- [ ] **Step 5 : vérifier**

Run : `python -m pytest tests/test_icp_rules.py -v`
Attendu : 5 tests PASSED

---

## Task 8: Calcul de `evidence_level`

**Files:**
- Create: `processors/evidence.py`
- Create: `tests/test_evidence.py`

**Interfaces:**
- Consumes: rien.
- Produces:
  - `processors.evidence.Evidence` — dataclass `(website_text: str, website_coherent: bool, perplexity_fields: dict[str, str | None], enabled_providers: frozenset[str])`
  - `processors.evidence.MIN_SOURCE_CHARS: int`
  - `processors.evidence.usable_sources(ev: Evidence) -> set[str]`
  - `processors.evidence.expected_sources(ev: Evidence) -> set[str]`
  - `processors.evidence.compute_evidence_level(ev: Evidence, identity_confirmed: bool) -> str`

Rappel du spec : LinkedIn n'entre pas dans le calcul, `website_scraper.py` forçant `linkedin_text = ""`. La règle est adaptative — l'exigence porte sur les fournisseurs activés.

- [ ] **Step 1 : écrire les tests qui échouent**

`tests/test_evidence.py` :

```python
from processors.evidence import (
    Evidence,
    compute_evidence_level,
    expected_sources,
    usable_sources,
)

LONG = "a" * 300


def _ev(**kw):
    base = dict(
        website_text="",
        website_coherent=False,
        perplexity_fields={},
        enabled_providers=frozenset({"website", "perplexity"}),
    )
    base.update(kw)
    return Evidence(**base)


def test_no_source_gives_none():
    assert compute_evidence_level(_ev(), identity_confirmed=True) == "none"


def test_identity_not_confirmed_forces_none():
    ev = _ev(website_text=LONG, website_coherent=True,
             perplexity_fields={"digital_maturity": "Score: 4/10 — site vieillissant"})
    assert compute_evidence_level(ev, identity_confirmed=False) == "none"


def test_one_of_two_expected_sources_gives_weak():
    ev = _ev(website_text=LONG, website_coherent=True)
    assert compute_evidence_level(ev, identity_confirmed=True) == "weak"


def test_all_expected_sources_give_sufficient():
    ev = _ev(website_text=LONG, website_coherent=True,
             perplexity_fields={"business_signals": "- levée de fonds mars 2026"})
    assert compute_evidence_level(ev, identity_confirmed=True) == "sufficient"


def test_perplexity_disabled_makes_website_alone_sufficient():
    ev = _ev(website_text=LONG, website_coherent=True,
             enabled_providers=frozenset({"website"}))
    assert compute_evidence_level(ev, identity_confirmed=True) == "sufficient"


def test_incoherent_website_is_not_a_usable_source():
    ev = _ev(website_text=LONG, website_coherent=False)
    assert "website" not in usable_sources(ev)


def test_short_website_text_is_not_a_usable_source():
    ev = _ev(website_text="trop court", website_coherent=True)
    assert "website" not in usable_sources(ev)


def test_placeholder_perplexity_answer_is_not_a_usable_source():
    ev = _ev(perplexity_fields={"business_signals": "Aucun signal récent identifié"})
    assert "perplexity" not in usable_sources(ev)


def test_expected_sources_follow_enabled_providers():
    assert expected_sources(_ev(enabled_providers=frozenset({"website"}))) == {"website"}
    assert expected_sources(_ev()) == {"website", "perplexity"}


def test_no_declared_provider_but_real_content_gives_sufficient():
    # enabled_providers empty means the caller declared nothing — unreachable
    # today, since collect_evidence always includes "website". Pinned here so
    # the behaviour is a decision, not an accident of set arithmetic.
    ev = _ev(website_text=LONG, website_coherent=True,
             enabled_providers=frozenset())
    assert compute_evidence_level(ev, identity_confirmed=True) == "sufficient"
```

- [ ] **Step 2 : vérifier que les tests échouent**

Run : `python -m pytest tests/test_evidence.py -v`
Attendu : ÉCHEC — `ModuleNotFoundError: No module named 'processors.evidence'`

- [ ] **Step 3 : implémenter**

`processors/evidence.py` :

```python
"""
Evidence accounting for ICP scoring.

`evidence_level` is measured, never declared by the model: a model that says
it is confident has no bearing on whether sources actually exist.

LinkedIn is deliberately absent — scrapers/website_scraper.py forces
linkedin_text = "" to avoid getting the account banned, so it can never be
a source.
"""
from dataclasses import dataclass, field

MIN_SOURCE_CHARS = 200

# Perplexity's polite way of saying it found nothing.
_PERPLEXITY_EMPTY_MARKERS = (
    "aucun signal récent identifié",
    "aucun signal recent identifie",
    "non disponible",
    "aucune information",
)

SOURCE_PROVIDERS = frozenset({"website", "perplexity"})


@dataclass
class Evidence:
    """Raw material available to score one lead."""
    website_text: str = ""
    website_coherent: bool = False
    perplexity_fields: dict[str, str | None] = field(default_factory=dict)
    enabled_providers: frozenset[str] = frozenset()


def _perplexity_is_substantive(fields: dict[str, str | None]) -> bool:
    for value in (fields or {}).values():
        if not value:
            continue
        lowered = str(value).strip().lower()
        if len(lowered) < 10:
            continue
        if any(marker in lowered for marker in _PERPLEXITY_EMPTY_MARKERS):
            continue
        return True
    return False


def usable_sources(ev: Evidence) -> set[str]:
    """Sources that actually carry exploitable content."""
    found: set[str] = set()
    if ev.website_coherent and len(ev.website_text or "") >= MIN_SOURCE_CHARS:
        found.add("website")
    if _perplexity_is_substantive(ev.perplexity_fields):
        found.add("perplexity")
    return found


def expected_sources(ev: Evidence) -> set[str]:
    """Sources we are entitled to expect, given the providers enabled this run."""
    return set(SOURCE_PROVIDERS & ev.enabled_providers)


def compute_evidence_level(ev: Evidence, identity_confirmed: bool) -> str:
    """Return 'none' | 'weak' | 'sufficient'."""
    if not identity_confirmed:
        return "none"

    usable = usable_sources(ev)
    if not usable:
        return "none"

    expected = expected_sources(ev)
    if expected and usable >= expected:
        return "sufficient"
    if not expected:
        # No provider declared enabled but content exists — trust the content.
        return "sufficient"
    return "weak"
```

- [ ] **Step 4 : vérifier**

Run : `python -m pytest tests/test_evidence.py -v`
Attendu : 9 tests PASSED

---

## Task 9: Moteur de scoring déterministe

**Files:**
- Modify: `processors/icp_scorer.py` (réécriture complète)
- Create: `tests/test_icp_scorer.py`

**Interfaces:**
- Consumes: `IcpRules`, `load_rules` (tâche 7) ; `compute_evidence_level` (tâche 8).
- Produces:
  - `processors.icp_scorer.IcpResult` — dataclass `(icp_score: int, icp_tier: str, icp_rationale: str, icp_scores_detail: str, disqualification_reason: str | None, evidence_verified: bool)`
  - `processors.icp_scorer.score_lead(facts: dict, evidence_level: str, rules: IcpRules, run_date: date) -> IcpResult`
  - `processors.icp_scorer.apply_scores(leads: list[dict], rules: IcpRules | None = None, run_date: date | None = None) -> list[dict]`
  - `processors.icp_scorer._reset_state()` — conservé, désormais sans effet, pour ne pas casser les imports de `pipeline_runner`

Format d'entrée de `facts` (produit en tâche 10), après suppression des faits non sourcés :

```python
{
  "identite_confirmee": bool,
  "pays":     {"value": "Maroc", "source": "website"} | None,
  "secteur":  {"value": "immobilier", "source": "website"} | None,
  "effectif": {"value": 45, "source": "perplexity"} | None,
  "est_concurrent": bool,
  "maturite_digitale": {"value": 4, "source": "perplexity"} | None,
  "signaux": [{"type": str, "date": "2026-04" | None, "source": str, "citation": str}],
}
```

- [ ] **Step 1 : écrire les tests qui échouent**

`tests/test_icp_scorer.py` :

```python
from datetime import date

import pytest

from processors.icp_rules import load_rules
from processors.icp_scorer import score_lead

RUN_DATE = date(2026, 8, 10)


@pytest.fixture
def rules():
    return load_rules()


def _facts(**kw):
    base = {
        "identite_confirmee": True,
        "pays": {"value": "Maroc", "source": "website"},
        "secteur": {"value": "immobilier", "source": "website"},
        "effectif": {"value": 45, "source": "perplexity"},
        "est_concurrent": False,
        "maturite_digitale": None,
        "signaux": [],
    }
    base.update(kw)
    return base


# ── Spec §9 fixed cases ──────────────────────────────────────────────────────

def test_large_group_is_disqualified(rules):
    facts = _facts(effectif={"value": 5000, "source": "perplexity"},
                   pays={"value": "France", "source": "website"})
    result = score_lead(facts, "sufficient", rules, RUN_DATE)
    assert result.icp_tier == "disqualified"
    assert "grand groupe" in result.disqualification_reason


def test_unverified_lead_falls_into_cold_capped(rules):
    facts = _facts(identite_confirmee=False)
    result = score_lead(facts, "none", rules, RUN_DATE)
    assert result.icp_tier == "cold"
    assert result.icp_score <= rules.unverified_score_cap
    assert result.evidence_verified is False


def test_mid_fit_lead_with_one_signal_is_warm(rules):
    # secteur "other" 50x0.20 + taille 100x0.20 + France 80x0.20 + 1 signal 40x0.40 = 62
    facts = _facts(
        secteur={"value": "logistique", "source": "website"},
        pays={"value": "France", "source": "website"},
        signaux=[{"type": "recrutement_marketing", "date": "2026-04",
                  "source": "perplexity", "citation": "..."}],
    )
    result = score_lead(facts, "sufficient", rules, RUN_DATE)
    assert result.icp_score == 62
    assert result.icp_tier == "warm"


def test_ideal_moroccan_sme_with_one_signal_is_hot(rules):
    # 100x0.20 + 100x0.20 + 100x0.20 + 40x0.40 = 76
    facts = _facts(signaux=[{"type": "recrutement_marketing", "date": "2026-04",
                             "source": "perplexity", "citation": "..."}])
    result = score_lead(facts, "sufficient", rules, RUN_DATE)
    assert result.icp_score == 76
    assert result.icp_tier == "hot"


def test_moroccan_sme_with_three_recent_signals_and_low_maturity_is_hot(rules):
    facts = _facts(
        maturite_digitale={"value": 3, "source": "perplexity"},
        signaux=[
            {"type": "levee_de_fonds", "date": "2026-06", "source": "perplexity", "citation": "a"},
            {"type": "recrutement_marketing", "date": "2026-05", "source": "perplexity", "citation": "b"},
            {"type": "lancement_produit", "date": "2026-07", "source": "website", "citation": "c"},
        ],
    )
    result = score_lead(facts, "sufficient", rules, RUN_DATE)
    assert result.icp_tier == "hot"


def test_competitor_is_disqualified(rules):
    facts = _facts(est_concurrent=True)
    result = score_lead(facts, "sufficient", rules, RUN_DATE)
    assert result.icp_tier == "disqualified"
    assert "concurrent" in result.disqualification_reason


def test_excluded_sector_is_disqualified(rules):
    facts = _facts(secteur={"value": "agriculture", "source": "website"},
                   effectif={"value": 80, "source": "perplexity"})
    result = score_lead(facts, "sufficient", rules, RUN_DATE)
    assert result.icp_tier == "disqualified"
    assert "secteur" in result.disqualification_reason


def test_out_of_zone_country_is_disqualified(rules):
    facts = _facts(pays={"value": "États-Unis", "source": "website"})
    result = score_lead(facts, "sufficient", rules, RUN_DATE)
    assert result.icp_tier == "disqualified"


# ── The reported inversion ───────────────────────────────────────────────────

def test_absence_of_signals_scores_zero_on_that_axis(rules):
    """The core fix: no sourced signal must yield 0, never an invented score."""
    facts = _facts(signaux=[])
    result = score_lead(facts, "sufficient", rules, RUN_DATE)
    detail = __import__("json").loads(result.icp_scores_detail)
    assert detail["signaux"] == 0


def test_more_evidence_never_lowers_the_score(rules):
    poor = score_lead(_facts(signaux=[]), "sufficient", rules, RUN_DATE)
    rich = score_lead(
        _facts(signaux=[{"type": "levee_de_fonds", "date": "2026-07",
                         "source": "perplexity", "citation": "x"}]),
        "sufficient", rules, RUN_DATE,
    )
    assert rich.icp_score > poor.icp_score


def test_competitor_disqualifies_even_without_evidence(rules):
    facts = _facts(est_concurrent=True, identite_confirmee=False)
    result = score_lead(facts, "none", rules, RUN_DATE)
    assert result.icp_tier == "disqualified"


def test_disqualification_requires_sufficient_evidence(rules):
    """A weak-evidence lead is never disqualified — we cannot assert the reason."""
    facts = _facts(effectif={"value": 5000, "source": "perplexity"})
    result = score_lead(facts, "weak", rules, RUN_DATE)
    assert result.icp_tier == "cold"
    assert result.disqualification_reason is None


# ── Unsourced facts ──────────────────────────────────────────────────────────

def test_unknown_sector_scores_zero_not_average(rules):
    facts = _facts(secteur=None)
    result = score_lead(facts, "sufficient", rules, RUN_DATE)
    detail = __import__("json").loads(result.icp_scores_detail)
    assert detail["secteur"] == 0


def test_unknown_size_does_not_disqualify(rules):
    facts = _facts(effectif=None)
    result = score_lead(facts, "sufficient", rules, RUN_DATE)
    assert result.icp_tier != "disqualified"


# ── Signal recency ───────────────────────────────────────────────────────────

def test_old_signals_score_lower_than_recent_ones(rules):
    old = [{"type": "x", "date": "2024-01", "source": "perplexity", "citation": "c"}
           for _ in range(3)]
    recent = [{"type": "x", "date": "2026-07", "source": "perplexity", "citation": "c"}
              for _ in range(3)]
    old_result = score_lead(_facts(signaux=old), "sufficient", rules, RUN_DATE)
    new_result = score_lead(_facts(signaux=recent), "sufficient", rules, RUN_DATE)
    assert new_result.icp_score > old_result.icp_score


def test_signal_without_date_counts_but_is_never_recent(rules):
    facts = _facts(signaux=[{"type": "x", "date": None, "source": "website", "citation": "c"}])
    result = score_lead(facts, "sufficient", rules, RUN_DATE)
    detail = __import__("json").loads(result.icp_scores_detail)
    assert detail["signaux"] == rules.signal_points["one"]
```

- [ ] **Step 2 : vérifier que les tests échouent**

Run : `python -m pytest tests/test_icp_scorer.py -v`
Attendu : ÉCHEC — `ImportError: cannot import name 'score_lead'`

- [ ] **Step 3 : réécrire le moteur**

**Avant de réécrire le module**, neutraliser son appelant : `main.py` importe `score_leads_icp`
au niveau module, et cette réécriture le supprime. Remplacer le bloc de l'étape 5 de `main.py` par
une neutralisation explicite — à ce stade aucune preuve n'est collectée, donc il n'y a rien à
scorer, et la tâche 12 recâblera l'appel au bon endroit :

```python
    # ── Step 5: ICP scoring ───────────────────────────────────────────────────
    # Deliberately inert until task 12 reorders the pipeline: scoring now runs
    # AFTER evidence collection, and no evidence exists at this point. Emitting
    # verdicts here would label every lead from an empty fact set.
    for lead in hit_leads:
        lead.setdefault("icp_score", None)
        lead.setdefault("icp_tier", None)
        lead.setdefault("icp_rationale", None)
        lead.setdefault("icp_scores_detail", None)
        lead.setdefault("disqualification_reason", None)
        lead.setdefault("evidence_level", None)
        lead.setdefault("evidence_verified", None)
    logger.info("Step 5 — ICP scoring déplacé après la collecte de preuves (tâche 12)")
```

Ne pas se contenter de rendre l'import paresseux : le symbole n'existe plus, donc cela ne ferait
que déplacer l'`ImportError` de l'import vers l'exécution — après le scraping Apollo, la partie la
plus coûteuse du run — tout en faisant passer `python -c "import main"` au vert à tort.

Remplacer ensuite **intégralement** le contenu de `processors/icp_scorer.py` par :

```python
"""
Step 7 — Deterministic ICP scoring.

The previous version asked an LLM to grade four axes before any evidence had
been collected, which made the score inversely correlated with knowledge: an
unknown company got generous defaults, a known one got real criteria applied.

Here the LLM only extracts sourced facts (see enrichers/fact_extractor.py).
This module turns facts into a score using versioned tables, so the result is
reproducible, explainable and testable without an API call.
"""
import json
import logging
from dataclasses import dataclass
from datetime import date
from typing import Optional

from processors.icp_rules import IcpRules, load_rules

logger = logging.getLogger(__name__)


@dataclass
class IcpResult:
    icp_score: int
    icp_tier: str                       # "hot" | "warm" | "cold" | "disqualified"
    icp_rationale: str
    icp_scores_detail: str              # JSON string
    disqualification_reason: Optional[str]
    evidence_verified: bool


def _reset_state():
    """Kept for import compatibility with api/pipeline_runner.py. No-op."""
    return None


# ── Fact readers ─────────────────────────────────────────────────────────────

def _value(fact) -> object:
    """Read the value of a sourced fact, or None when the fact is absent."""
    if isinstance(fact, dict):
        return fact.get("value")
    return None


def _months_between(older: str, reference: date) -> Optional[int]:
    """Months from a 'YYYY-MM' (or 'YYYY-MM-DD') string to the reference date."""
    if not older:
        return None
    try:
        parts = str(older).split("-")
        year, month = int(parts[0]), int(parts[1])
    except (ValueError, IndexError):
        return None
    return (reference.year - year) * 12 + (reference.month - month)


# ── Axis scoring ─────────────────────────────────────────────────────────────

def _score_sector(facts: dict, rules: IcpRules) -> int:
    sector = _value(facts.get("secteur"))
    if not sector:
        return rules.sector_points.get("unknown", 0)
    normalized = str(sector).strip().lower()
    if any(h in normalized for h in rules.high_value_sectors):
        return rules.sector_points.get("high_value", 100)
    return rules.sector_points.get("other", 50)


def _score_size(facts: dict, rules: IcpRules) -> int:
    headcount = _value(facts.get("effectif"))
    if not isinstance(headcount, (int, float)):
        return 0
    for band in rules.size_bands:
        if band["min"] <= headcount <= band["max"]:
            return band["points"]
    return 0


def _score_location(facts: dict, rules: IcpRules) -> int:
    country = _value(facts.get("pays"))
    if not country:
        return 0
    zone = rules.country_zone(str(country))
    if zone is None:
        return 0
    return rules.zone_points.get(zone, 0)


def _score_signals(facts: dict, rules: IcpRules, run_date: date) -> int:
    signals = [s for s in (facts.get("signaux") or []) if isinstance(s, dict)]
    count = len(signals)

    recent = any(
        (age := _months_between(s.get("date"), run_date)) is not None
        and 0 <= age <= rules.signal_recency_months
        for s in signals
    )

    if count >= 3:
        key = "three_or_more_recent" if recent else "three_or_more"
    elif count == 2:
        key = "two"
    elif count == 1:
        key = "one"
    else:
        key = "none"
    points = rules.signal_points.get(key, 0)

    # Digital maturity encodes BoxCom's ideal profile: a weak or ageing
    # digital presence is the buying signal.
    #
    # Bonus only, never a penalty. An unsourced maturity gets no adjustment,
    # so penalising a HIGH maturity would place "we could not tell" above
    # "we checked and it is mature" — reintroducing exactly the inversion this
    # rework exists to remove. Acquiring a fact must never cost points.
    maturity = _value(facts.get("maturite_digitale"))
    if isinstance(maturity, (int, float)) and maturity <= rules.maturity_low_max:
        points += rules.maturity_bonus

    return max(0, min(100, points))


# ── Disqualification ─────────────────────────────────────────────────────────

def _disqualification_reason(facts: dict, rules: IcpRules) -> Optional[str]:
    headcount = _value(facts.get("effectif"))
    if isinstance(headcount, (int, float)):
        if headcount > rules.size_disqualify_above:
            return (f"grand groupe — {int(headcount)} employés, "
                    f"au-delà du seuil de {rules.size_disqualify_above}")
        if headcount < rules.size_disqualify_below:
            return (f"micro-entreprise — {int(headcount)} employés, "
                    f"sous le seuil de {rules.size_disqualify_below}")

    sector = _value(facts.get("secteur"))
    if sector:
        normalized = str(sector).strip().lower()
        for excluded in rules.excluded_sectors:
            if excluded in normalized:
                return f"secteur exclu — {sector}"

    country = _value(facts.get("pays"))
    if country and rules.country_zone(str(country)) is None:
        return f"hors zone géographique — {country}"

    return None


# ── Public API ───────────────────────────────────────────────────────────────

def score_lead(
    facts: dict,
    evidence_level: str,
    rules: IcpRules,
    run_date: date,
) -> IcpResult:
    """Turn validated facts into a score, a tier and, where warranted, a refusal."""
    detail = {
        "secteur": _score_sector(facts, rules),
        "taille": _score_size(facts, rules),
        "localisation": _score_location(facts, rules),
        "signaux": _score_signals(facts, rules, run_date),
    }
    raw_score = round(sum(detail[axis] * rules.weights[axis] for axis in detail))
    detail_json = json.dumps(detail)
    verified = evidence_level == "sufficient"

    # 1. A sourced competitor is disqualified whatever the evidence level:
    #    the fact alone settles it.
    if facts.get("est_concurrent") is True:
        return IcpResult(
            icp_score=raw_score, icp_tier="disqualified",
            icp_rationale="Concurrent direct de BoxCom — ne peut pas être client.",
            icp_scores_detail=detail_json,
            disqualification_reason="concurrent direct",
            evidence_verified=verified,
        )

    # 2. Insufficient evidence: cap and fall into cold. No disqualification
    #    claim is made — we lack the facts to assert one.
    if not verified:
        return IcpResult(
            icp_score=min(raw_score, rules.unverified_score_cap),
            icp_tier="cold",
            icp_rationale=(
                "Preuves insuffisantes pour évaluer ce prospect "
                f"(niveau de preuve : {evidence_level}). Score plafonné, "
                "qualification manuelle nécessaire."
            ),
            icp_scores_detail=detail_json,
            disqualification_reason=None,
            evidence_verified=False,
        )

    # 3. Hard rules, only on properly evidenced leads
    reason = _disqualification_reason(facts, rules)
    if reason:
        return IcpResult(
            icp_score=raw_score, icp_tier="disqualified",
            icp_rationale=f"Prospect disqualifié : {reason}.",
            icp_scores_detail=detail_json,
            disqualification_reason=reason,
            evidence_verified=True,
        )

    # 4. Normal tiers
    if raw_score >= rules.tier_hot_min:
        tier = "hot"
    elif raw_score >= rules.tier_warm_min:
        tier = "warm"
    else:
        tier = "cold"

    signal_count = len([s for s in (facts.get("signaux") or []) if isinstance(s, dict)])
    rationale = (
        f"Secteur {detail['secteur']}/100, taille {detail['taille']}/100, "
        f"localisation {detail['localisation']}/100, "
        f"signaux {detail['signaux']}/100 ({signal_count} signal(aux) sourcé(s))."
    )

    return IcpResult(
        icp_score=raw_score, icp_tier=tier,
        icp_rationale=rationale,
        icp_scores_detail=detail_json,
        disqualification_reason=None,
        evidence_verified=True,
    )


def apply_scores(
    leads: list[dict],
    rules: Optional[IcpRules] = None,
    run_date: Optional[date] = None,
) -> list[dict]:
    """
    Score every lead in place from lead['facts'] and lead['evidence_level'].

    Both keys are produced by enrichers/fact_extractor.py earlier in the run.
    """
    active_rules = rules or load_rules()
    today = run_date or date.today()

    counts = {"hot": 0, "warm": 0, "cold": 0, "disqualified": 0}
    for lead in leads:
        result = score_lead(
            lead.get("facts") or {},
            lead.get("evidence_level") or "none",
            active_rules,
            today,
        )
        lead["icp_score"] = result.icp_score
        lead["icp_tier"] = result.icp_tier
        lead["icp_rationale"] = result.icp_rationale
        lead["icp_scores_detail"] = result.icp_scores_detail
        lead["disqualification_reason"] = result.disqualification_reason
        lead["evidence_verified"] = result.evidence_verified
        counts[result.icp_tier] = counts.get(result.icp_tier, 0) + 1

    logger.info(
        f"ICP scoring complete: {counts['hot']} hot, {counts['warm']} warm, "
        f"{counts['cold']} cold, {counts['disqualified']} disqualified."
    )
    return leads
```

- [ ] **Step 4 : vérifier**

Run : `python -m pytest tests/test_icp_scorer.py -v`
Attendu : 16 tests PASSED

Les deux tests de tier vérifient un score exact, calculé à la main depuis les tables de
`icp_rules.json`. En cas d'échec, c'est le code qui est en cause, jamais l'attendu : la table du
spec est la référence produit. Ne jamais « ajuster » un test de scoring pour le faire passer.

---

## Task 10: Extraction de faits sourcés

**Files:**
- Create: `enrichers/fact_extractor.py`
- Create: `tests/test_fact_extractor.py`

**Interfaces:**
- Consumes: `Evidence`, `compute_evidence_level` (tâche 8).
- Produces:
  - `enrichers.fact_extractor.VALID_SOURCES: frozenset[str]`
  - `enrichers.fact_extractor.sanitize_facts(raw: dict) -> dict`
  - `enrichers.fact_extractor.extract_facts(lead: dict, ev: Evidence) -> dict`
  - `enrichers.fact_extractor.extract_leads_facts(leads: list[dict], enabled_providers: frozenset[str], registry=None) -> list[dict]` — renseigne `lead["facts"]`, `lead["facts_json"]`, `lead["evidence_level"]`
  - `enrichers.fact_extractor._reset_state()`

- [ ] **Step 1 : écrire les tests qui échouent**

`tests/test_fact_extractor.py` :

```python
from enrichers.fact_extractor import VALID_SOURCES, sanitize_facts


def test_unsourced_scalar_fact_is_dropped():
    raw = {"secteur": {"value": "immobilier"}, "identite_confirmee": True}
    assert sanitize_facts(raw)["secteur"] is None


def test_fact_with_unknown_source_is_dropped():
    raw = {"secteur": {"value": "immobilier", "source": "intuition"}}
    assert sanitize_facts(raw)["secteur"] is None


def test_properly_sourced_fact_survives():
    raw = {"secteur": {"value": "immobilier", "source": "website"}}
    assert sanitize_facts(raw)["secteur"] == {"value": "immobilier", "source": "website"}


def test_unsourced_signal_is_dropped_but_sourced_one_kept():
    raw = {"signaux": [
        {"type": "levee_de_fonds", "date": "2026-05", "source": "perplexity", "citation": "a"},
        {"type": "rumeur", "date": "2026-05", "citation": "b"},
    ]}
    signals = sanitize_facts(raw)["signaux"]
    assert len(signals) == 1
    assert signals[0]["type"] == "levee_de_fonds"


def test_missing_identity_defaults_to_false():
    assert sanitize_facts({})["identite_confirmee"] is False


def test_competitor_flag_is_coerced_to_bool():
    assert sanitize_facts({"est_concurrent": "true"})["est_concurrent"] is True
    assert sanitize_facts({})["est_concurrent"] is False


def test_headcount_string_is_coerced_to_int():
    raw = {"effectif": {"value": "45", "source": "perplexity"}}
    assert sanitize_facts(raw)["effectif"]["value"] == 45


def test_unparseable_headcount_is_dropped():
    raw = {"effectif": {"value": "une cinquantaine", "source": "perplexity"}}
    assert sanitize_facts(raw)["effectif"] is None


def test_valid_sources_are_the_three_expected():
    assert VALID_SOURCES == frozenset({"website", "linkedin", "perplexity"})
```

- [ ] **Step 2 : vérifier que les tests échouent**

Run : `python -m pytest tests/test_fact_extractor.py -v`
Attendu : ÉCHEC — `ModuleNotFoundError: No module named 'enrichers.fact_extractor'`

- [ ] **Step 3 : implémenter**

`enrichers/fact_extractor.py` :

```python
"""
Step 6 — Sourced fact extraction.

The model's only job here is to read the collected sources and report what
they say, with a source label on every claim. It does not grade, rank or sell.
Anything it reports without a usable source is discarded in Python before
scoring: a rule enforced in code cannot be talked around by a confident model.
"""
import json
import logging
import re
import time
from typing import Optional

import anthropic

import config
from api.provider_status import StepOutcome
from enrichers.retry import retry_api_call, AuthError
from processors.evidence import Evidence, compute_evidence_level

logger = logging.getLogger(__name__)

MODEL = "claude-haiku-4-5-20251001"
VALID_SOURCES = frozenset({"website", "linkedin", "perplexity"})

SYSTEM_PROMPT = """Tu es un analyste qui extrait des faits vérifiables sur une entreprise.

Tu ne notes pas. Tu ne vends pas. Tu ne rédiges pas d'argumentaire.
Tu lis les sources fournies et tu rapportes ce qu'elles disent.

═══ RÈGLE ABSOLUE : PAS DE SOURCE, PAS DE FAIT ═══

Chaque fait que tu rapportes doit porter une clé "source" valant exactement
"website", "linkedin" ou "perplexity", désignant la source où tu l'as lu.

Si une information n'apparaît dans AUCUNE source fournie, tu mets le champ à null.
Tu n'as pas le droit de la déduire, de l'estimer ou de la compléter par ta
connaissance générale de l'entreprise. Un champ null est un résultat correct
et attendu. Une invention est une faute.

═══ CONFIRMATION D'IDENTITÉ ═══

"identite_confirmee" vaut true si les sources décrivent bien l'entreprise du
prospect. Il vaut false uniquement si les sources décrivent manifestement une
AUTRE entité (homonymie : même nom, pays ou métier sans rapport).

Ne mets PAS false dans ces cas :
- le champ localisation du prospect est vide, tronqué ou incohérent (artefact
  de saisie) — ignore-le et juge sur les sources ;
- la localisation est une ville et la source mentionne le pays correspondant ;
- le poste du contact ne colle pas parfaitement au secteur.

En cas de doute : true.

═══ CHAMPS ═══

- "pays" : pays d'opération principal, en français ("Maroc", "France", "Sénégal"...)
- "secteur" : secteur d'activité en français, en deux mots maximum
- "effectif" : nombre d'employés, entier. null si aucune source ne le donne.
- "est_concurrent" : true si l'entreprise est une agence de communication,
  de marketing digital, de création ou de développement web.
- "maturite_digitale" : entier de 1 à 10 si une source l'évalue, sinon null
- "signaux" : événements datés des 12 derniers mois (recrutement, levée de fonds,
  lancement, expansion, refonte). Liste vide si aucune source n'en mentionne.

═══ FORMAT ═══

Réponds UNIQUEMENT par ce JSON, sans markdown ni commentaire :
{
  "identite_confirmee": true,
  "pays": {"value": "Maroc", "source": "website"},
  "secteur": {"value": "immobilier", "source": "website"},
  "effectif": {"value": 45, "source": "perplexity"},
  "est_concurrent": false,
  "maturite_digitale": {"value": 4, "source": "perplexity"},
  "signaux": [
    {"type": "recrutement_marketing", "date": "2026-04",
     "source": "perplexity", "citation": "extrait littéral de la source"}
  ]
}"""

USER_PROMPT_TEMPLATE = """Prospect (données Apollo, non vérifiées) :
Nom : {first_name} {last_name}
Poste : {job_title}
Entreprise : {company}
Localisation déclarée : {location}

═══ SOURCE "website" ═══
{website_text}

═══ SOURCE "perplexity" ═══
Maturité digitale : {digital_maturity}
Taille / budget : {estimated_budget}
Signaux business : {business_signals}

Extrais les faits au format JSON demandé."""

_EMPTY_FACTS = {
    "identite_confirmee": False,
    "pays": None,
    "secteur": None,
    "effectif": None,
    "est_concurrent": False,
    "maturite_digitale": None,
    "signaux": [],
}

_extractor_disabled = False


def _reset_state():
    global _extractor_disabled
    _extractor_disabled = False


def _sourced(fact) -> Optional[dict]:
    """Keep a fact only when it carries a recognised source and a value."""
    if not isinstance(fact, dict):
        return None
    if fact.get("source") not in VALID_SOURCES:
        return None
    if fact.get("value") in (None, "", []):
        return None
    return {"value": fact["value"], "source": fact["source"]}


def _as_int(fact: Optional[dict]) -> Optional[dict]:
    if fact is None:
        return None
    try:
        return {"value": int(str(fact["value"]).strip()), "source": fact["source"]}
    except (ValueError, TypeError):
        return None


def sanitize_facts(raw: dict) -> dict:
    """
    Drop every unsourced or malformed fact.

    Never raises, and always returns the complete shape whatever the input:
    this is the enforcement point for "no source, no fact", and callers must
    not have to wrap it in a try/except to get that guarantee.
    """
    if not isinstance(raw, dict):
        raw = {}
    raw_signals = raw.get("signaux")
    if not isinstance(raw_signals, list):
        raw_signals = []
    signals = []
    for signal in raw_signals:
        if not isinstance(signal, dict):
            continue
        if signal.get("source") not in VALID_SOURCES:
            continue
        signals.append({
            "type": signal.get("type") or "signal",
            "date": signal.get("date") or None,
            "source": signal["source"],
            "citation": signal.get("citation") or "",
        })

    return {
        "identite_confirmee": bool(raw.get("identite_confirmee", False)),
        "pays": _sourced(raw.get("pays")),
        "secteur": _sourced(raw.get("secteur")),
        "effectif": _as_int(_sourced(raw.get("effectif"))),
        "est_concurrent": str(raw.get("est_concurrent", "")).strip().lower() in ("true", "1", "yes")
                          or raw.get("est_concurrent") is True,
        "maturite_digitale": _as_int(_sourced(raw.get("maturite_digitale"))),
        "signaux": signals,
    }


def _parse_json(content: str) -> dict:
    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-z]*\n?", "", cleaned)
        cleaned = re.sub(r"\n?```$", "", cleaned).strip()
    return json.loads(cleaned)


def extract_facts(lead: dict, ev: Evidence) -> dict:
    """Call the model for one lead and return sanitized facts."""
    global _extractor_disabled
    if _extractor_disabled:
        return dict(_EMPTY_FACTS)

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    perplexity = ev.perplexity_fields or {}
    user_prompt = USER_PROMPT_TEMPLATE.format(
        first_name=lead.get("first_name", ""),
        last_name=lead.get("last_name", ""),
        job_title=lead.get("job_title", ""),
        company=lead.get("company", ""),
        location=lead.get("location", ""),
        website_text=(ev.website_text or "Non disponible")[:4000],
        digital_maturity=perplexity.get("digital_maturity") or "Non disponible",
        estimated_budget=perplexity.get("estimated_budget") or "Non disponible",
        business_signals=perplexity.get("business_signals") or "Non disponible",
    )
    name = f"{lead.get('first_name', '')} {lead.get('last_name', '')}".strip()

    def _do_request():
        message = client.messages.create(
            model=MODEL,
            max_tokens=1000,
            temperature=0,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
        return sanitize_facts(_parse_json(message.content[0].text.strip()))

    try:
        return retry_api_call(_do_request, max_retries=3, operation_name=f"Fact extraction ({name})")
    except AuthError as e:
        _extractor_disabled = True
        logger.error(f"Fact extraction auth failed — disabled for this run: {e}")
        return dict(_EMPTY_FACTS)
    except Exception as e:
        logger.error(f"Fact extraction failed for {name}: {e}")
        return dict(_EMPTY_FACTS)


def extract_leads_facts(
    leads: list[dict],
    enabled_providers: frozenset[str],
    registry=None,
) -> list[dict]:
    """
    Extract facts for every lead and compute its evidence level.

    Sets lead['facts'], lead['facts_json'] and lead['evidence_level'].
    """
    _reset_state()

    if config._is_placeholder(config.ANTHROPIC_API_KEY):
        logger.error("ANTHROPIC_API_KEY not set. Skipping fact extraction.")
        for lead in leads:
            lead["facts"] = dict(_EMPTY_FACTS)
            lead["facts_json"] = json.dumps(_EMPTY_FACTS, ensure_ascii=False)
            lead["evidence_level"] = "none"
        if registry:
            registry.record(StepOutcome("anthropic", "skipped", "clé API absente", 0))
        return leads

    total = len(leads)
    extracted = 0
    for i, lead in enumerate(leads, 1):
        name = f"{lead.get('first_name', '')} {lead.get('last_name', '')}".strip()
        logger.info(f"Fact extraction [{i}/{total}]: {name}")

        ev = Evidence(
            website_text=lead.get("website_text", "") or "",
            website_coherent=lead.get("website_coherent") is not False,
            perplexity_fields={
                "digital_maturity": lead.get("digital_maturity"),
                "estimated_budget": lead.get("estimated_budget"),
                "business_signals": lead.get("business_signals"),
            },
            enabled_providers=enabled_providers,
        )

        facts = extract_facts(lead, ev)
        lead["facts"] = facts
        lead["facts_json"] = json.dumps(facts, ensure_ascii=False)
        lead["evidence_level"] = compute_evidence_level(ev, facts["identite_confirmee"])

        if facts["identite_confirmee"]:
            extracted += 1
        if _extractor_disabled:
            logger.warning(f"Fact extraction disabled — skipping remaining {total - i} leads")
            for remaining in leads[i:]:
                remaining["facts"] = dict(_EMPTY_FACTS)
                remaining["facts_json"] = json.dumps(_EMPTY_FACTS, ensure_ascii=False)
                remaining["evidence_level"] = "none"
            break
        if i < total:
            time.sleep(0.3)

    logger.info(f"Fact extraction complete. {extracted}/{total} identities confirmed.")
    if registry:
        status = "degraded" if _extractor_disabled else "ok"
        registry.record(StepOutcome("anthropic", status, None, extracted))
    return leads
```

- [ ] **Step 4 : vérifier**

Run : `python -m pytest tests/test_fact_extractor.py -v`
Attendu : 9 tests PASSED

---

## Task 11: Rédaction de l'angle commercial

**Files:**
- Create: `enrichers/angle_writer.py`
- Create: `tests/test_angle_writer.py`

**Interfaces:**
- Consumes: faits validés produits en tâche 10.
- Produces:
  - `enrichers.angle_writer.write_leads_angles(leads: list[dict], enrich_instructions: str = "", registry=None) -> list[dict]` — renseigne `activity_summary` et `conversion_angle`
  - `enrichers.angle_writer.should_write(lead: dict) -> bool`
  - `enrichers.angle_writer._reset_state()`

Le rédacteur ne voit que les faits validés, jamais les sources brutes : il ne peut donc pas broder sur du texte non retenu.

- [ ] **Step 1 : écrire les tests qui échouent**

`tests/test_angle_writer.py` :

```python
from enrichers.angle_writer import should_write


def test_disqualified_lead_gets_no_angle():
    assert should_write({"icp_tier": "disqualified"}) is False


def test_well_evidenced_disqualified_lead_still_gets_no_angle():
    # The row that actually exercises the disqualification short-circuit: the
    # test above passes even without the guard, since a missing
    # evidence_verified already returns False.
    assert should_write({"icp_tier": "disqualified", "evidence_verified": True}) is False


def test_unverified_lead_gets_no_angle():
    assert should_write({"icp_tier": "cold", "evidence_verified": False}) is False


def test_verified_cold_lead_still_gets_an_angle():
    assert should_write({"icp_tier": "cold", "evidence_verified": True}) is True


def test_hot_lead_gets_an_angle():
    assert should_write({"icp_tier": "hot", "evidence_verified": True}) is True
```

- [ ] **Step 2 : vérifier que les tests échouent**

Run : `python -m pytest tests/test_angle_writer.py -v`
Attendu : ÉCHEC — `ModuleNotFoundError: No module named 'enrichers.angle_writer'`

- [ ] **Step 3 : implémenter**

`enrichers/angle_writer.py` :

```python
"""
Step 8 — Commercial angle writing.

Runs last, on validated facts only, and only for leads worth contacting.
Separating this from evaluation is deliberate: a model asked to judge and to
sell in the same breath will justify the sale it just wrote.
"""
import json
import logging
import time

import anthropic

import config
from api.provider_status import StepOutcome
from enrichers.retry import retry_api_call, AuthError

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Tu rédiges des accroches de prospection pour BoxCom, agence de \
communication digitale basée au Maroc (+10 ans d'expertise).

Services : Marketing Digital, Contenu Créatif, Développement Web, Lead Generation.

On te transmet des FAITS déjà vérifiés et sourcés. Tu n'as pas accès aux sources brutes.

Règles :
1. Tu n'écris que ce que les faits contiennent. Aucun chiffre, aucune date, aucune
   technologie qui ne figure pas dans les faits fournis.
2. Interdits : "leader du marché", "acteur de référence", "depuis X années",
   "équipe de X personnes" — sauf si présents dans les faits.
3. Si les faits sont pauvres, écris un résumé court plutôt qu'un texte étoffé.

Produis :
- "activity_summary" : 2-3 phrases décrivant l'activité de l'entreprise.
- "conversion_angle" : une accroche personnalisée reliant un fait précis à un
  service BoxCom nommé.

Réponds UNIQUEMENT par ce JSON, sans markdown :
{"activity_summary": "...", "conversion_angle": "..."}"""

USER_PROMPT_TEMPLATE = """Prospect : {first_name} {last_name}, {job_title} chez {company}

Faits vérifiés :
{facts_json}

Évaluation ICP : {icp_tier} ({icp_score}/100)
{icp_rationale}

Rédige le JSON demandé."""

_writer_disabled = False


def _reset_state():
    global _writer_disabled
    _writer_disabled = False


def should_write(lead: dict) -> bool:
    """Only evidenced, non-disqualified leads deserve the token spend."""
    if lead.get("icp_tier") == "disqualified":
        return False
    return bool(lead.get("evidence_verified"))


def _write_one(lead: dict, enrich_instructions: str = "") -> dict:
    global _writer_disabled
    empty = {"activity_summary": None, "conversion_angle": None}
    if _writer_disabled:
        return empty

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    system = SYSTEM_PROMPT
    if enrich_instructions:
        system += (
            "\n\nINSTRUCTIONS SPÉCIFIQUES DE L'UTILISATEUR :\n"
            f"{enrich_instructions}\n"
            "Oriente l'accroche selon ces instructions, sans inventer de fait."
        )

    user_prompt = USER_PROMPT_TEMPLATE.format(
        first_name=lead.get("first_name", ""),
        last_name=lead.get("last_name", ""),
        job_title=lead.get("job_title", ""),
        company=lead.get("company", ""),
        facts_json=lead.get("facts_json") or json.dumps(lead.get("facts") or {}, ensure_ascii=False),
        icp_tier=lead.get("icp_tier", "?"),
        icp_score=lead.get("icp_score", "?"),
        icp_rationale=lead.get("icp_rationale", ""),
    )
    name = f"{lead.get('first_name', '')} {lead.get('last_name', '')}".strip()

    def _do_request():
        message = client.messages.create(
            model=config.LLM_MODEL,
            max_tokens=600,
            temperature=0.3,
            system=system,
            messages=[{"role": "user", "content": user_prompt}],
        )
        content = message.content[0].text.strip()
        if content.startswith("```"):
            import re
            content = re.sub(r"^```[a-z]*\n?", "", content)
            content = re.sub(r"\n?```$", "", content).strip()
        data = json.loads(content)
        return {
            "activity_summary": (data.get("activity_summary") or "").strip() or None,
            "conversion_angle": (data.get("conversion_angle") or "").strip() or None,
        }

    try:
        return retry_api_call(_do_request, max_retries=3, operation_name=f"Angle writing ({name})")
    except AuthError as e:
        _writer_disabled = True
        logger.error(f"Angle writing auth failed — disabled for this run: {e}")
        return empty
    except Exception as e:
        logger.error(f"Angle writing failed for {name}: {e}")
        return empty


def write_leads_angles(leads: list[dict], enrich_instructions: str = "", registry=None) -> list[dict]:
    """Write summary and angle for every lead that qualifies."""
    _reset_state()

    eligible = [l for l in leads if should_write(l)]
    skipped = len(leads) - len(eligible)
    logger.info(f"Angle writing: {len(eligible)} eligible leads, {skipped} skipped")

    for lead in leads:
        lead.setdefault("activity_summary", None)
        lead.setdefault("conversion_angle", None)

    if config._is_placeholder(config.ANTHROPIC_API_KEY):
        logger.error("ANTHROPIC_API_KEY not set. Skipping angle writing.")
        return leads

    written = 0
    total = len(eligible)
    for i, lead in enumerate(eligible, 1):
        name = f"{lead.get('first_name', '')} {lead.get('last_name', '')}".strip()
        logger.info(f"Angle writing [{i}/{total}]: {name}")
        result = _write_one(lead, enrich_instructions)
        lead["activity_summary"] = result["activity_summary"]
        lead["conversion_angle"] = result["conversion_angle"]
        if result["activity_summary"]:
            written += 1
        if _writer_disabled:
            logger.warning(f"Angle writing disabled — skipping remaining {total - i} leads")
            break
        if i < total:
            time.sleep(0.3)

    logger.info(f"Angle writing complete. {written}/{total} written.")
    if registry:
        registry.record(StepOutcome("anthropic", "degraded" if _writer_disabled else "ok", None, written))
    return leads
```

- [ ] **Step 4 : vérifier**

Run : `python -m pytest tests/ -v`
Attendu : 82 tests PASSED

---

## Task 12: Collecteur de preuves et réordonnancement du pipeline

**Files:**
- Create: `enrichers/evidence_collector.py`
- Modify: `api/pipeline_runner.py:75-94` (étapes), `:287-326` (corps), `:693-763` (enrich-only)
- Modify: `main.py:126-230`
- Modify: `enrichers/perplexity_enricher.py:125-182` (registre)

**Interfaces:**
- Consumes: `scrape_hit_leads`, `enrich_leads_perplexity`, `extract_leads_facts` (tâche 10), `apply_scores` (tâche 9), `write_leads_angles` (tâche 11), `ProviderRegistry` (tâche 5).
- Produces:
  - `enrichers.evidence_collector.collect_evidence(leads: list[dict], enrich_instructions: str = "", registry=None) -> tuple[list[dict], frozenset[str]]` — renvoie les leads enrichis et l'ensemble des fournisseurs de preuve actifs.

- [ ] **Step 1 : implémenter le collecteur**

`enrichers/evidence_collector.py` :

```python
"""
Step 5 — Evidence collection.

Gathers every source the scoring engine will rely on, before any judgement is
made. Returns which providers were actually active so evidence_level can adapt:
a lead must not be penalised for a provider the operator turned off.
"""
import asyncio
import logging

import config
from api.provider_status import StepOutcome

logger = logging.getLogger(__name__)


def collect_evidence(leads: list[dict], enrich_instructions: str = "", registry=None):
    """Scrape websites and query Perplexity. Returns (leads, active_providers)."""
    from scrapers.website_scraper import scrape_hit_leads
    from enrichers.perplexity_enricher import enrich_leads_perplexity

    active = {"website"}  # website scraping needs no API key

    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        leads = loop.run_until_complete(scrape_hit_leads(leads))
    finally:
        loop.close()

    scraped = sum(1 for l in leads if (l.get("website_text") or "").strip())
    logger.info(f"Evidence: {scraped}/{len(leads)} websites yielded text")
    if registry:
        registry.record(StepOutcome("website", "ok", None, scraped))

    if config._is_placeholder(config.PERPLEXITY_API_KEY):
        logger.info("PERPLEXITY_API_KEY not set — Perplexity excluded from evidence expectations.")
        for lead in leads:
            lead.setdefault("digital_maturity", None)
            lead.setdefault("estimated_budget", None)
            lead.setdefault("business_signals", None)
        if registry:
            registry.record(StepOutcome("perplexity", "skipped", "clé API absente", 0))
    else:
        leads = enrich_leads_perplexity(leads, enrich_instructions, registry=registry)
        active.add("perplexity")

    return leads, frozenset(active)
```

- [ ] **Step 2 : faire remonter le statut Perplexity**

Dans `enrichers/perplexity_enricher.py`, changer la signature (ligne 125) :

```python
def enrich_leads_perplexity(hit_leads: list[dict], enrich_instructions: str = "", registry=None) -> list[dict]:
```

Ajouter l'import `from api.provider_status import StepOutcome`, et remplacer le bloc final (lignes 177-182) par :

```python
    unique_companies = len(company_cache)
    logger.info(
        f"Perplexity enrichment complete. {success}/{total} leads enriched "
        f"({unique_companies} unique companies queried)."
    )
    if registry:
        status = "degraded" if _perplexity_disabled else "ok"
        registry.record(StepOutcome("perplexity", status, None, success))
    return hit_leads
```

- [ ] **Step 3 : réordonner le pipeline web**

Dans `api/pipeline_runner.py`, remplacer `STEP_NAMES` et `STEP_PATTERNS` (lignes 75-94) par :

```python
STEP_WEIGHTS = {1: 0.05, 2: 0.18, 3: 0.22, 4: 0.05, 5: 0.25, 6: 0.13, 7: 0.05, 8: 0.07}
STEP_NAMES = {
    1: "Input Apollo URL",
    2: "Scraping Apollo",
    3: "Enrichissement (Google + Dropcontact + Hunter)",
    4: "Calcul du taux de hit",
    5: "Collecte de preuves (site + Perplexity)",
    6: "Extraction de faits sourcés",
    7: "Scoring ICP",
    8: "Rédaction des angles commerciaux",
}

STEP_PATTERNS = [
    (2, re.compile(r"Step 2|Scraping Apollo|apollo|page \d+", re.I)),
    (3, re.compile(r"Step 3|Google enrichment|Dropcontact|dropcontact|batch \d+|Hunter\.io|email verification", re.I)),
    (4, re.compile(r"Step 4|hit score|Hit score complete", re.I)),
    (5, re.compile(r"Step 5|Evidence|Perplexity|Scraping hit lead|website", re.I)),
    (6, re.compile(r"Step 6|Fact extraction", re.I)),
    (7, re.compile(r"Step 7|ICP scoring", re.I)),
    (8, re.compile(r"Step 8|Angle writing", re.I)),
]
```

Remplacer le bloc des étapes 5 à 7 (lignes 287-326) par :

```python
        # ── Step 5: Evidence collection ───────────────────────────────────
        if not skip_gpt and hit_leads:
            handler.set_explicit_progress(5, 0.0, "Collecte de preuves (sites web + Perplexity)...")
            from enrichers.evidence_collector import collect_evidence
            hit_leads, active_providers = collect_evidence(
                hit_leads, enrich_instructions, registry=registry
            )
            handler.set_explicit_progress(5, 1.0, "Collecte de preuves terminée")
            _check_cancelled(job_id)

            # ── Step 6: Fact extraction ───────────────────────────────────
            handler.set_explicit_progress(6, 0.0, "Extraction des faits sourcés...")
            from enrichers.fact_extractor import extract_leads_facts
            hit_leads = extract_leads_facts(hit_leads, active_providers, registry=registry)
            confirmed = sum(1 for l in hit_leads if (l.get("facts") or {}).get("identite_confirmee"))
            handler.set_explicit_progress(
                6, 1.0, f"Faits extraits — {confirmed}/{len(hit_leads)} identités confirmées"
            )
            _check_cancelled(job_id)

            # ── Step 7: Deterministic ICP scoring ─────────────────────────
            handler.set_explicit_progress(7, 0.0, "Scoring ICP...")
            from processors.icp_scorer import apply_scores
            hit_leads = apply_scores(hit_leads)
            disq = sum(1 for l in hit_leads if l.get("icp_tier") == "disqualified")
            handler.set_explicit_progress(
                7, 1.0, f"Scoring terminé — {disq} lead(s) disqualifié(s)"
            )

            # ── Step 8: Angle writing ─────────────────────────────────────
            handler.set_explicit_progress(8, 0.0, "Rédaction des angles commerciaux...")
            from enrichers.angle_writer import write_leads_angles
            hit_leads = write_leads_angles(hit_leads, enrich_instructions, registry=registry)
            handler.set_explicit_progress(8, 1.0, "Rédaction terminée")
        else:
            for lead in hit_leads:
                lead.setdefault("icp_score", None)
                lead.setdefault("icp_tier", None)
                lead.setdefault("icp_rationale", None)
                lead.setdefault("icp_scores_detail", None)
                lead.setdefault("disqualification_reason", None)
                lead.setdefault("evidence_level", None)
                lead.setdefault("evidence_verified", None)
                lead.setdefault("facts_json", None)
                lead.setdefault("activity_summary", None)
                lead.setdefault("conversion_angle", None)
                lead.setdefault("digital_maturity", None)
                lead.setdefault("estimated_budget", None)
                lead.setdefault("business_signals", None)
```

**Conserver** `new_loop` (lignes 208-210) et son `new_loop.close()` : l'étape 2 y exécute encore
`scrape_apollo`. Seul l'appel `new_loop.run_until_complete(scrape_hit_leads(...))` disparaît, le
scraping de sites étant désormais géré par `collect_evidence`, qui ouvre sa propre boucle.

Le compteur de disqualifiés dans `JobStats` est ajouté en tâche 13.

- [ ] **Step 4 : réordonner le flux enrich-only**

Dans `_run_enrich_only_sync`, remplacer le bloc des étapes 5-7 (lignes 728-749) par :

```python
        # Step 5: Evidence collection
        handler.set_explicit_progress(5, 0.0, "Collecte de preuves...")
        from enrichers.evidence_collector import collect_evidence
        leads, active_providers = collect_evidence(leads, registry=registry)
        handler.set_explicit_progress(5, 1.0, "Collecte terminée")
        _check_cancelled(job_id)

        # Step 6: Fact extraction
        handler.set_explicit_progress(6, 0.0, "Extraction des faits...")
        from enrichers.fact_extractor import extract_leads_facts
        leads = extract_leads_facts(leads, active_providers, registry=registry)
        handler.set_explicit_progress(6, 1.0, "Faits extraits")
        _check_cancelled(job_id)

        # Step 7: ICP scoring
        handler.set_explicit_progress(7, 0.0, "Scoring ICP...")
        from processors.icp_scorer import apply_scores
        leads = apply_scores(leads)
        handler.set_explicit_progress(7, 1.0, "Scoring terminé")

        # Step 8: Angle writing
        handler.set_explicit_progress(8, 0.0, "Rédaction des angles...")
        from enrichers.angle_writer import write_leads_angles
        leads = write_leads_angles(leads, registry=registry)
        handler.set_explicit_progress(8, 1.0, "Rédaction terminée")
```

Y instancier `registry = ProviderRegistry()` en début de fonction, et remplacer les imports `_reset_state` de `gpt_enricher` / `icp_scorer` (lignes 708-713) par ceux de `fact_extractor` et `angle_writer`.

- [ ] **Step 5 : aligner le CLI**

Dans `main.py`, remplacer le bloc des étapes 5 et 6 (lignes 165-218) par :

```python
    # ── Step 5: Evidence collection (hit leads only) ──────────────────────────
    if not args.skip_gpt and hit_leads:
        logger.info(f"Step 5 — Evidence collection on {len(hit_leads)} hit leads...")
        from enrichers.evidence_collector import collect_evidence
        hit_leads, active_providers = collect_evidence(hit_leads)

        logger.info("Step 6 — Fact extraction...")
        from enrichers.fact_extractor import extract_leads_facts
        hit_leads = extract_leads_facts(hit_leads, active_providers)

        logger.info("Step 7 — ICP scoring...")
        from processors.icp_scorer import apply_scores
        hit_leads = apply_scores(hit_leads)

        logger.info("Step 8 — Angle writing...")
        from enrichers.angle_writer import write_leads_angles
        hit_leads = write_leads_angles(hit_leads)
    else:
        reason = "--skip-gpt flag set" if args.skip_gpt else "no hit leads"
        logger.info(f"Steps 5-8 — Skipped ({reason})")
        for lead in hit_leads:
            for field in ("icp_score", "icp_tier", "icp_rationale", "icp_scores_detail",
                          "disqualification_reason", "evidence_level", "evidence_verified",
                          "facts_json", "activity_summary", "conversion_angle",
                          "digital_maturity", "estimated_budget", "business_signals"):
                lead.setdefault(field, None)
```

Supprimer les imports devenus inutiles en tête de `main.py` : `enrich_leads_gpt`, `enrich_leads_perplexity`, `score_leads_icp`, `scrape_hit_leads`.

Dans `print_summary`, ajouter après la ligne des tiers :

```python
        icp_disq = sum(1 for l in all_leads if l.get("icp_tier") == "disqualified")
        if icp_disq:
            print(f"  ICP disqualifiés        : {icp_disq}")
```

- [ ] **Step 6 : vérifier**

Run : `python -m pytest tests/ -v`
Attendu : 82 tests PASSED

Run : `python -c "import main; import api.server; import api.pipeline_runner"`
Attendu : aucune exception d'import.

Run : `python -m uvicorn api.server:app --port 8010`
Attendu : le serveur démarre. Vérifier `GET http://localhost:8010/api/health`, puis arrêter.

---

## Task 13: Statistiques, persistance et suppression de l'ancien code

**Files:**
- Modify: `api/models.py:31-72`
- Modify: `api/pipeline_runner.py:366-379` (stats)
- Modify: `api/leads_db.py:168-198`
- Delete: `enrichers/gpt_enricher.py`
- Delete: `prompts/icp_scoring.txt`

**Interfaces:**
- Consumes: `ENRICH_FIELDS` (tâche 6), tiers produits en tâche 9.
- Produces: `api.models.JobStats.icp_disqualified_count: int`, `LeadRecord` aligné sur le nouveau schéma.

- [ ] **Step 1 : mettre à jour les modèles**

**Retirer aussi les trois champs legacy de `lead_schema.py`** — `inconsistency_detected`,
`inconsistency_reason`, `llm_confidence`, présents dans `CSV_COLUMNS` et `ENRICH_FIELDS` — dans le
même mouvement que la suppression de `gpt_enricher.py` à l'étape 5. Ils ont été conservés jusqu'ici
pour qu'aucun commit intermédiaire ne perde de données déjà écrites en base.

Dans `api/models.py`, `LeadRecord` : supprimer `inconsistency_detected`, `inconsistency_reason`, `llm_confidence` ; ajouter :

```python
    website_coherent: Optional[bool] = None
    website_rejected: Optional[str] = None
    disqualification_reason: Optional[str] = None
    evidence_level: Optional[str] = None
    evidence_verified: Optional[bool] = None
    facts_json: Optional[str] = None
```

Dans `JobStats`, ajouter :

```python
    icp_disqualified_count: int = 0
```

- [ ] **Step 2 : compter les disqualifiés**

Dans `api/pipeline_runner.py`, ajouter au constructeur `JobStats` (après la ligne 378) :

```python
            icp_disqualified_count=sum(1 for l in leads if l.get("icp_tier") == "disqualified"),
```

- [ ] **Step 3 : aligner la persistance des pools**

Dans `api/leads_db.py`, ajouter l'import `from lead_schema import ENRICH_FIELDS` et remplacer la boucle de reconstruction dans `get_pool_leads` (lignes 191-196) par :

```python
        # Parse enrich_data JSON if present; absent keys stay None so pools
        # created before the ICP rework keep loading.
        for field_name in ENRICH_FIELDS:
            d.setdefault(field_name, None)
        if d.get("enrich_data"):
            try:
                d.update(json.loads(d["enrich_data"]))
            except (json.JSONDecodeError, TypeError):
                pass
```

- [ ] **Step 4 : écrire le test de non-régression des pools**

Ajouter à `tests/test_lead_schema.py` :

```python
def test_pool_leads_expose_every_enrich_field(tmp_path, monkeypatch):
    import api.leads_db as db

    monkeypatch.setattr(db, "_DB_PATH", str(tmp_path / "t.db"))
    db.init_leads_table()
    pool_id = db.create_pool("test", "url", "job", [
        {"first_name": "A", "last_name": "B", "company": "Acme",
         "email": "a@b.c", "hit_score": 80, "is_hit": True},
    ])
    lead = db.get_pool_leads(pool_id)[0]
    for field in ENRICH_FIELDS:
        assert field in lead, f"{field} missing from pool lead"
```

- [ ] **Step 5 : supprimer l'ancien code**

D'abord, purger le bloc de réinitialisation d'état de `_run_pipeline_sync`
(`api/pipeline_runner.py`, lignes 195-206), qui importe encore `gpt_enricher` :

```python
        from enrichers.google_search import _reset_state as _reset_google
        from enrichers.dropcontact import _reset_state as _reset_dc
        from enrichers.hunter_verifier import _reset_state as _reset_hunter
        from enrichers.fact_extractor import _reset_state as _reset_facts
        from enrichers.angle_writer import _reset_state as _reset_angle
        from enrichers.perplexity_enricher import _reset_state as _reset_perplexity
        _reset_google()
        _reset_dc()
        _reset_hunter()
        _reset_facts()
        _reset_angle()
        _reset_perplexity()
```

L'import `from processors.icp_scorer import _reset_state as _reset_icp` disparaît : le moteur est
sans état depuis la tâche 9. Supprimer aussi la fonction `_reset_state` de
`processors/icp_scorer.py` elle-même, ainsi que le même import dans `_run_enrich_only_sync` —
elle n'a plus aucun appelant.

Vérifier ensuite qu'aucune référence ne subsiste :

Run : `python -m pytest tests/ -q`
Run : `git grep -n "gpt_enricher\|icp_scoring.txt\|score_leads_icp\|llm_confidence\|inconsistency_detected" -- "*.py"`
Attendu : aucune occurrence hors `frontend/`.

Puis supprimer :

```
Remove-Item enrichers/gpt_enricher.py
Remove-Item prompts/icp_scoring.txt
Remove-Item -Recurse prompts
```

Retirer aussi `ICP_PROMPT_PATH` de `config.py` (ligne 33).

- [ ] **Step 6 : vérifier**

Run : `python -m pytest tests/ -v`
Attendu : 83 tests PASSED

Run : `python -c "import api.server"`
Attendu : aucune exception.

---

## Task 14: Interface — tier disqualifié, niveau de preuve, santé des fournisseurs

**Files:**
- Modify: `frontend/src/lib/api.ts:29-31`, `:45-60`, `:111-112`
- Modify: `frontend/src/components/ResultsTable.tsx:53`, `:69`, `:169-174`, `:264-268`, `:350-390`
- Modify: `frontend/src/components/LeadDetailModal.tsx:18-30`, `:66-70`, `:143-160`
- Modify: `frontend/src/components/StatsBar.tsx:56-95`
- Modify: `frontend/src/components/PipelineProgress.tsx:5-23` — la liste `STEPS` et `mapApiStepToDisplay` décrivent encore l'ancien pipeline (5 = « Scoring ICP », 7 = « Perplexity », tout ce qui dépasse 7 replié sur 7). Depuis la tâche 12 le backend a huit étapes dans un autre ordre : l'interface affiche « Scoring ICP » pendant la collecte de preuves.
- Modify: `frontend/src/components/ApolloForm.tsx:74-81` — même liste statique périmée.

**Interfaces:**
- Consumes: champs produits par les tâches 9 et 13.
- Produces: aucune interface consommée par d'autres tâches.

- [ ] **Step 1 : mettre à jour les types**

Dans `frontend/src/lib/api.ts`, dans l'interface des statistiques (lignes 29-31), ajouter :

```typescript
  icp_disqualified_count: number
```

Dans l'interface du lead (lignes 45-60), supprimer `inconsistency_detected`, `inconsistency_reason`, `llm_confidence` et ajouter :

```typescript
  website_coherent?: boolean
  website_rejected?: string
  disqualification_reason?: string
  evidence_level?: 'none' | 'weak' | 'sufficient'
  evidence_verified?: boolean
  facts_json?: string
```

Dans l'interface du résultat de job, ajouter :

```typescript
  provider_status?: Record<string, { status: string; reason: string | null; leads_affected: number }>
```

- [ ] **Step 2 : introduire un helper de tier partagé**

Créer `frontend/src/lib/tiers.ts` :

```typescript
import type { CSSProperties } from 'react'

export type IcpTier = 'hot' | 'warm' | 'cold' | 'disqualified'

export const TIER_ICON: Record<IcpTier, string> = {
  hot: '🔥',
  warm: '🟡',
  cold: '❄️',
  disqualified: '⛔',
}

export const TIER_STYLE: Record<IcpTier, CSSProperties> = {
  hot: { background: 'rgba(249,115,22,0.12)', color: '#fb923c', border: '1px solid rgba(249,115,22,0.25)' },
  warm: { background: 'rgba(251,191,36,0.10)', color: '#fbbf24', border: '1px solid rgba(251,191,36,0.22)' },
  cold: { background: 'rgba(96,165,250,0.10)', color: '#60a5fa', border: '1px solid rgba(96,165,250,0.22)' },
  disqualified: { background: 'rgba(148,163,184,0.12)', color: '#94a3b8', border: '1px solid rgba(148,163,184,0.28)' },
}

export function tierOf(value?: string): IcpTier {
  return (['hot', 'warm', 'cold', 'disqualified'] as const).includes(value as IcpTier)
    ? (value as IcpTier)
    : 'cold'
}
```

- [ ] **Step 3 : câbler `ResultsTable`**

Ajouter l'import : `import { TIER_ICON, TIER_STYLE, tierOf } from '@/lib/tiers'`

Ligne 53 — élargir le type du filtre :

```typescript
  const [icpFilter, setIcpFilter] = useState<'all' | 'hot' | 'warm' | 'cold' | 'disqualified'>('all')
```

Lignes 171-173 — ajouter l'entrée manquante à la liste des filtres :

```typescript
            { key: 'hot', label: '🔥 Hot' },
            { key: 'warm', label: '🟡 Warm' },
            { key: 'cold', label: '❄️ Cold' },
            { key: 'disqualified', label: '⛔ Disqualifié' },
```

Lignes 356-361 — remplacer la chaîne de ternaires, qui afficherait ❄️ pour un lead disqualifié :

```typescript
                            style={TIER_STYLE[tierOf(lead.icp_tier)]}
                          >
                            {TIER_ICON[tierOf(lead.icp_tier)]} {lead.icp_score}
```

Lignes 264-268 — remplacer le badge `inconsistency_detected` par le badge de preuve :

```typescript
                          {lead.evidence_verified === false && (
                            <span
                              title={lead.icp_rationale || 'Preuves insuffisantes'}
                              className="text-xs px-1.5 py-0.5 rounded"
                              style={{ background: 'rgba(148,163,184,0.12)', color: '#94a3b8' }}
                            >
                              non vérifié
                            </span>
                          )}
```

Panneau de détail du scoring (lignes 379-390) — afficher le motif de refus au-dessus du détail
par axe :

```typescript
                                {lead.disqualification_reason && (
                                  <div className="text-xs mb-2" style={{ color: '#94a3b8' }}>
                                    ⛔ Disqualifié — {lead.disqualification_reason}
                                  </div>
                                )}
```

- [ ] **Step 4 : câbler `LeadDetailModal`**

Lignes 18-30 — dans l'interface locale du lead, supprimer `inconsistency_detected` /
`inconsistency_reason` et ajouter :

```typescript
  disqualification_reason?: string
  evidence_level?: 'none' | 'weak' | 'sufficient'
  evidence_verified?: boolean
  website_rejected?: string
```

Lignes 66-70 — remplacer le bloc `{lead.inconsistency_detected && (...)}` par :

```typescript
              {lead.disqualification_reason && (
                <div className="text-sm rounded-lg px-3 py-2 mb-2"
                     style={{ background: 'rgba(148,163,184,0.12)', color: '#94a3b8' }}>
                  ⛔ Disqualifié — {lead.disqualification_reason}
                </div>
              )}
              {lead.evidence_verified === false && (
                <div className="text-sm rounded-lg px-3 py-2 mb-2"
                     style={{ background: 'var(--th-warning-soft)', color: 'var(--th-warning-text)' }}>
                  Preuves insuffisantes — qualification manuelle nécessaire
                </div>
              )}
```

Lignes 151-156 — remplacer les ternaires de tier :

```typescript
                style={TIER_STYLE[tierOf(lead.icp_tier)]}
              >
                {TIER_ICON[tierOf(lead.icp_tier)]} {lead.icp_score}
```

Sous le bloc ICP, ajouter la trace du site écarté :

```typescript
          {lead.website_rejected && (
            <p className="text-xs mt-2" style={{ color: 'var(--th-text-faint)' }}>
              Site écarté (incohérent) : {lead.website_rejected}
            </p>
          )}
```

- [ ] **Step 5 : câbler `StatsBar`**

Ajouter un quatrième compteur `icp_disqualified_count` à côté de hot / warm / cold (lignes 66-84), en gris `#94a3b8`, et l'inclure dans le `total` et la barre de répartition (lignes 86-94).

- [ ] **Step 6 : vérifier**

```
cd frontend
npm run lint
npm run build
```

Attendu : lint sans erreur, build réussi.

Lancer ensuite le pipeline complet sur un petit lot :

```
python -m uvicorn api.server:app --port 8000
```

Dans un second terminal, démarrer `npm run dev`, lancer un run avec `max_leads = 5`, et vérifier dans l'interface :
- le bandeau de santé des fournisseurs après le run ;
- au moins un tier affiché parmi `hot` / `warm` / `cold` / `disqualified` ;
- pour un lead sans preuve, le badge « non vérifié » et un score ≤ 39.

---

## Vérification finale

- [ ] `python -m pytest tests/ -v` → 83 tests PASSED
- [ ] `cd frontend; npm run build` → succès
- [ ] Run complet sur 5 leads, CSV téléchargé, colonnes `evidence_level`, `evidence_verified`, `disqualification_reason`, `facts_json` présentes et renseignées
- [ ] Test manuel de l'arrêt Dropcontact : mettre temporairement `DROPCONTACT_API_KEY` à une valeur invalide dans `.env`, lancer un run, vérifier que le job passe en `error` avec le message « Étape contacts interrompue » et **non** en `done`
- [ ] `git status` → uniquement des fichiers non suivis et modifiés, **aucun commit créé** (l'utilisateur commite lui-même)
