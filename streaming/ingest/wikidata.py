"""Ingestion helpers for Wikidata.

Ce module fournit deux fonctions principales utilisées lors du chargement des titres :

* ``enrich`` interroge le point d'accès SPARQL de Wikidata afin de récupérer des métadonnées
  (identifiant QID, année de sortie, genres et description) pour un titre donné.
* ``normalize_genres`` convertit les libellés de genres retournés par Wikidata en un vocabulaire
  interne limité.

Le code est volontairement simple : il ne gère pas le découpage en lots ni le cache, car les
 tests utilisent un ``httpx.MockTransport`` qui renvoie une réponse unique.
"""

from __future__ import annotations

import json
from typing import Iterable, Set, Dict, Any

import httpx

SPARQL_URL = "https://query.wikidata.org/sparql"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sparql_literal(title: str) -> str:
    """Littéral SPARQL anglais, guillemets et antislashs échappés.

    Wikidata attend les chaînes entre guillemets doubles, suivies du suffixe ``@en``.
    Cette fonction remplace les caractères problématiques afin d'éviter les erreurs de
    syntaxe dans la requête.
    """
    escaped = title.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"@en'

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def normalize_genres(labels: Iterable[str]) -> Set[str]:
    """Normalise les libellés de genres Wikidata.

    Les libellés sont comparés en minuscules et chaque mot‑clé connu est ajouté au
    résultat. Si aucun mot‑clé n'est reconnu, le set ``{"autre"}`` est retourné.
    """
    # Mapping de mots‑clés possibles vers le vocabulaire interne
    keyword_map = {
        "science-fiction": "science-fiction",
        "science fiction": "science-fiction",
        "action": "action",
        "drame": "drame",
        "drama": "drame",
        "comédie": "comedie",
        "comedie": "comedie",
        "animation": "animation",
        "thriller": "thriller",
        "horreur": "horreur",
        "fantastique": "fantastique",
        "romance": "romance",
        "documentaire": "documentaire",
        "crime": "crime",
        "aventure": "aventure",
        "famille": "famille",
        "téléréalité": "telerealite",
        "telerealite": "telerealite",
    }
    result: Set[str] = set()
    for label in labels:
        lowered = label.lower()
        for key, norm in keyword_map.items():
            if key in lowered:
                result.add(norm)
    if not result:
        result.add("autre")
    return result


def enrich(http: httpx.Client, title: str, kind: str) -> Dict[str, Any] | None:
    """Interroge Wikidata pour enrichir un titre.

    Parameters
    ----------
    http: httpx.Client
        Client utilisé pour effectuer la requête GET.
    title: str
        Titre exact en anglais.
    kind: str
        ``"film"`` ou ``"serie"`` – détermine le filtre d'instance.

    Returns
    -------
    dict | None
        Dictionnaire contenant ``qid``, ``year``, ``genres`` (liste de libellés français) et
        ``description`` (en français) ou ``None`` si aucun résultat n'est trouvé.
    """
    # Choix de l'instance selon le type
    if kind == "film":
        instance_filter = "wd:Q11424"  # film
    else:
        instance_filter = "wd:Q5398426"  # série télévisée

    title_literal = _sparql_literal(title)
    query = (
        "SELECT ?item ?year ?genreLabel ?desc WHERE {\n"
        f"  VALUES ?item {{ {title_literal} }}\n"
        "  ?item rdfs:label " + title_literal + " .\n"
        f"  ?item wdt:P31/wdt:P279* {instance_filter} .\n"
        "  OPTIONAL { ?item wdt:P577 ?date } .\n"
        "  BIND(year(?date) AS ?year) .\n"
        "  OPTIONAL { ?item wdt:P136 ?genre .\n"
        "             ?genre rdfs:label ?genreLabel FILTER (lang(?genreLabel) = \"fr\") } .\n"
        "  OPTIONAL { ?item schema:description ?desc FILTER (lang(?desc) = \"fr\") } .\n"
        "  BIND(strafter(str(?item), \"/entity/\") AS ?qid)\n"
        "}"
    )

    headers = {"User-Agent": "streaming-platform-projet-etudiant/1.0"}
    resp = http.get(SPARQL_URL, params={"query": query, "format": "json"}, headers=headers)
    resp.raise_for_status()
    data = resp.json()
    bindings = data.get("results", {}).get("bindings", [])
    if not bindings:
        return None
    first = bindings[0]
    # Extraction sécurisée des champs
    qid = first.get("qid", {}).get("value")
    year_str = first.get("year", {}).get("value")
    year = int(year_str) if year_str and year_str.isdigit() else None
    # Genres peut être une liste ou un seul binding – on récupère tous les genreLabel
    genres = []
    for b in bindings:
        gl = b.get("genreLabel", {}).get("value")
        if gl:
            genres.append(gl)
    description = first.get("desc", {}).get("value")
    if description is None:
        description = "Description indisponible sur Wikidata"
    return {
        "qid": qid,
        "year": year,
        "genres": genres,
        "description": description,
    }

# NOTE: le module expose uniquement les fonctions requises par les tests.
