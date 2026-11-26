"""Module d'enrichissement des métadonnées via Wikidata SPARQL."""

from __future__ import annotations

import json
from typing import Dict, List, Optional, Set
import httpx

SPARQL_URL = "https://query.wikidata.org/sparql"
USER_AGENT = "streaming-platform-projet-etudiant/1.0"


def normalize_genres(labels: List[str]) -> Set[str]:
    """Ramène les libellés Wikidata à notre vocabulaire par mots-clés."""
    vocabulary = {
        "science-fiction",
        "action",
        "drame",
        "comedie",
        "animation",
        "thriller",
        "horreur",
        "fantastique",
        "romance",
        "documentaire",
        "crime",
        "aventure",
        "famille",
        "telerealite",
    }
    
    mapping = {
        "science-fiction": "science-fiction",
        "sf": "science-fiction",
        "science fiction": "science-fiction",
        "action": "action",
        "drame": "drame",
        "dramatique": "drame",
        "comedie": "comedie",
        "comédie": "comedie",
        "animation": "animation",
        "anime": "animation",
        "dessin anime": "animation",
        "thriller": "thriller",
        "suspense": "thriller",
        "horreur": "horreur",
        "epouvante": "horreur",
        "fantastique": "fantastique",
        "fantasy": "fantastique",
        "romance": "romance",
        "sentimentaux": "romance",
        "documentaire": "documentaire",
        "crime": "crime",
        "policier": "crime",
        "gangster": "crime",
        "aventure": "aventure",
        "famille": "famille",
        "familial": "famille",
        "telerealite": "telerealite",
        "téléréalité": "telerealite",
    }

    found = set()
    for lbl in labels:
        lbl_lower = lbl.lower()
        # Direct match or substring check
        matched = False
        for key, target in mapping.items():
            if key in lbl_lower:
                found.add(target)
                matched = True
        if not matched:
            # Check direct vocabulary words
            for v in vocabulary:
                if v in lbl_lower:
                    found.add(v)
                    matched = True

    if not found:
        return {"autre"}
    return found


def enrich(client: httpx.Client, title: str, kind: str) -> Optional[Dict]:
    """Interroge Wikidata SPARQL pour trouver QID, année, genres et description."""
    # Q11424 = film, Q5398426 = television series
    item_type_q = "wd:Q11424" if kind == "film" else "wd:Q5398426"

    query = f"""
    SELECT ?item ?itemLabel ?pubDate ?desc ?genreLabel WHERE {{
      ?item rtw:label-ignored-or-not ?item .
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "fr,en". }}
      ?item rdfs:label "{title}"@en.
      ?item wdt:P31/wdt:P279* {item_type_q}.
      OPTIONAL {{ ?item wdt:P577 ?pubDate. }}
      OPTIONAL {{ ?item wdt:P136 ?genre. }}
      OPTIONAL {{
        {{ ?item schema:description ?desc. FILTER(lang(?desc) = "fr") }}
        UNION
        {{ ?item schema:description ?desc. FILTER(lang(?desc) = "en") }}
      }}
    }}
    LIMIT 10
    """
    # Simplified and robust SPARQL query
    query = f"""
    SELECT ?item ?pubDate ?desc ?genreLabel WHERE {{
      ?item rdfs:label "{title}"@en.
      ?item wdt:P31/wdt:P279* {item_type_q}.
      OPTIONAL {{ ?item wdt:P577 ?pubDate. }}
      OPTIONAL {{ ?item wdt:P136 ?genre. 
                ?genre rdfs:label ?genreLabel. FILTER(lang(?genreLabel) = "fr") }}
      OPTIONAL {{ ?item schema:description ?desc. FILTER(lang(?desc) = "fr") }}
    }}
    LIMIT 50
    """

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/sparql-results+json",
    }

    try:
        response = client.get(SPARQL_URL, params={"query": query, "format": "json"}, headers=headers)
        if response.status_code != 200:
            return None
        data = response.json()
    except Exception:
        return None

    bindings = data.get("results", {}).get("bindings", [])
    if not bindings:
        return None

    qid = None
    year = None
    description = None
    genre_labels = set()

    for b in bindings:
        if not qid and "item" in b:
            uri = b["item"]["value"]
            qid = uri.split("/")[-1]
        if not year and "pubDate" in b:
            date_str = b["pubDate"]["value"]
            try:
                year = int(date_str[:4])
            except ValueError:
                pass
        if not description and "desc" in b:
            description = b["desc"]["value"]
        if "genreLabel" in b:
            genre_labels.add(b["genreLabel"]["value"])

    if not qid:
        return None

    # Fallback description en si pas de fr (handled by query or checking bindings)
    if not description:
        # try another pass if needed or accept None
        pass

    genres = normalize_genres(list(genre_labels))

    return {
        "qid": qid,
        "year": year,
        "genres": genres,
        "description": description,
    }
