"""Module d'enrichissement Wikidata (source 2)."""

from __future__ import annotations

import re
import unicodedata
from typing import Dict, List, Optional, Set
import httpx

SPARQL_URL = "https://query.wikidata.org/sparql"


def normalize_genres(labels: List[str]) -> Set[str]:
    """Ramène les libellés Wikidata à notre vocabulaire par mots-clés."""
    keywords_map = {
        "science-fiction": "science-fiction",
        "science fiction": "science-fiction",
        "action": "action",
        "drame": "drame",
        "comedie": "comedie",
        "comédie": "comedie",
        "animation": "animation",
        "thriller": "thriller",
        "horreur": "horreur",
        "fantastique": "fantastique",
        "romance": "romance",
        "romanti": "romance",  # pour romantique / romantique
        "documentaire": "documentaire",
        "crime": "crime",
        "policier": "crime",
        "aventure": "aventure",
        "famille": "famille",
        "telerealite": "telerealite",
        "téléréalité": "telerealite",
    }

    found: Set[str] = {}
    for lbl in labels:
        # Normalisation sans accents et minuscules
        norm_lbl = unicodedata.normalize("NFKD", lbl).encode("ascii", "ignore").decode("utf-8").lower()
        for kw, target in keywords_map.items():
            norm_kw = unicodedata.normalize("NFKD", kw).encode("ascii", "ignore").decode("utf-8").lower()
            if norm_kw in norm_lbl:
                found.add(target)

    return found if found else {"autre"}


def enrich(http: httpx.Client, title: str, kind: str) -> Optional[Dict]:
    """Interroge Wikidata en SPARQL pour enrichir un titre (QID, année, genres, description)."""
    # Échapper les guillemets et antislashs du titre pour la requête SPARQL
    escaped_title = title.replace("\\", "\\\\").replace('"', '\\"')

    # Instance (wdt:P31/wdt:P279*) : Q11424 (film) ou Q5398426 (série)
    target_class = "wd:Q11424" if kind == "film" else "wd:Q5398426"

    query = f"""
    SELECT ?item ?itemLabel ?pubDate ?seriesStart ?genreLabel ?desc WHERE {{
      ?item rdt:notused 0 .
      {{
        SELECT ?item WHERE {{
          ?item rdfs:label "{escaped_title}"@en .
          ?item wdt:P31/wdt:P279* {target_class} .
        }
        LIMIT 10
      }}
      OPTIONAL {{ ?item wdt:P577 ?pubDate . }}
      OPTIONAL {{ ?item wdt:P580 ?seriesStart . }}
      OPTIONAL {{
        ?item wdt:P136 ?genre .
        ?genre rdfs:label ?genreLabel .
        FILTER(LANG(?genreLabel) = "fr")
      }}
      OPTIONAL {{
        ?item schema:description ?desc .
        FILTER(LANG(?desc) = "fr")
      }}
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "fr,en". }}
    }
    """

    # Requête SPARQL propre et optimisée sans variable fictive rdt:notused
    query = f"""
    SELECT ?item ?pubDate ?seriesStart ?genreLabel ?desc WHERE {{
      {{
        SELECT ?item WHERE {{
          ?item rdfs:label "{escaped_title}"@en .
          ?item wdt:P31/wdt:P279* {target_class} .
        }
        LIMIT 10
      }}
      OPTIONAL {{ ?item wdt:P577 ?pubDate . }}
      OPTIONAL {{ ?item wdt:P580 ?seriesStart . }}
      OPTIONAL {{
        ?item wdt:P136 ?genre .
        ?genre rdfs:label ?genreLabel .
        FILTER(LANG(?genreLabel) = "fr")
      }}
      OPTIONAL {{
        ?item schema:description ?desc .
        FILTER(LANG(?desc) = "fr" || LANG(?desc) = "en")
      }}
    }}
    """

    headers = {"User-Agent": "streaming-platform-projet-etudiant/1.0"}
    params = {"query": query, "format": "json"}

    try:
        response = http.get(SPARQL_URL, params=params, headers=headers)
        response.raise_for_status()
        data = response.json()
    except Exception:
        return None

    bindings = data.get("results", {}).get("bindings", [])
    if not bindings:
        return None

    # Regrouper par ?item (URI)
    items_map: Dict[str, dict] = {}
    for b in bindings:
        item_uri = b.get("item", {}).get("value")
        if not item_uri:
            continue
        if item_uri not in items_map:
            items_map[item_uri] = {
                "qid": item_uri.split("/")[-1],
                "dates": [],
                "genres": set(),
                "desc_fr": None,
                "desc_en": None,
            }

        # Date P577 ou P580
        pub_date = b.get("pubDate", {}).get("value")
        series_start = b.get("seriesStart", {}).get("value")
        for d_str in [pub_date, series_start]:
            if d_str:
                try:
                    year_val = int(d_str[:4])
                    items_map[item_uri]["dates"].append(year_val)
                except ValueError:
                    pass

        # Genre label
        g_label = b.get("genreLabel", {}).get("value")
        if g_label:
            items_map[item_uri]["genres"].add(g_label)

        # Description
        desc_node = b.get("desc", {})
        desc_val = desc_node.get("value")
        desc_lang = desc_node.get("xml:lang")
        if desc_val:
            if desc_lang == "fr":
                items_map[item_uri]["desc_fr"] = desc_val
            elif desc_lang == "en" and not items_map[item_uri]["desc_en"]:
                items_map[item_uri]["desc_en"] = desc_val

    if not items_map:
        return None

    # Calculer l'année pour chaque item (min des dates, ou 0)
    scored_items = []
    for item_uri, info in items_map.items():
        dates = info["dates"]
        year = min(dates) if dates else 0
        desc = info["desc_fr"] or info["desc_en"]
        scored_items.append((year, item_uri, info, desc))

    # Garder l'élément le plus récent (année max)
    scored_items.sort(key=lambda x: x[0], reverse=True)
    best_year, _, best_info, best_desc = scored_items[0]

    return {
        "qid": best_info["qid"],
        "year": best_year if best_year > 0 else None,
        "genres": list(best_info["genres"]),
        "description": best_desc,
    }
