"""Enrichissement des titres via Wikidata SPARQL."""

from __future__ import annotations

import unicodedata
import httpx

SPARQL_URL = "https://query.wikidata.org/sparql"

QUERY_TEMPLATE = """SELECT ?item ?pubDate ?start ?genreLabel ?descFr ?descEn WHERE {
  ?item rdfs:label "__TITLE__"@en ; wdt:P31/wdt:P279* __CLASS__ .
  OPTIONAL { ?item wdt:P577 ?pubDate . }
  OPTIONAL { ?item wdt:P580 ?start . }
  OPTIONAL { ?item wdt:P136 ?genre . ?genre rdfs:label ?genreLabel . FILTER(LANG(?genreLabel) = "fr") }
  OPTIONAL { ?item schema:description ?descFr . FILTER(LANG(?descFr) = "fr") }
  OPTIONAL { ?item schema:description ?descEn . FILTER(LANG(?descEn) = "en") }
} LIMIT 200"""

# Vocabulaire cible et mots-clés associés (sans accents)
KEYWORDS_MAP = {
    "science-fiction": ["science-fiction", "science fiction", "sci-fi"],
    "action": ["action"],
    "drame": ["drame", "drama", "dramatique"],
    "comedie": ["comedie", "comedy"],
    "animation": ["animation", "anime", "dessin anime"],
    "thriller": ["thriller", "suspense", "espionnage", "enigme", "mystere"],
    "horreur": ["horreur", "horror", "epouvante"],
    "fantastique": ["fantastique", "fantasy", "surnaturel"],
    "romance": ["romance", "romanti", "sentimental"],
    "documentaire": ["documentaire", "documentary"],
    "crime": ["crime", "criminel", "policier", "detective", "gangster"],
    "aventure": ["aventure", "adventure"],
    "famille": ["famille", "familial", "family", "jeunesse"],
    "telerealite": ["telerealite", "tele-realite", "reality", "emission de realite"],
}


def _plain(s: str) -> str:
    """Met en minuscules et supprime les accents d'une chaîne."""
    nfkd = unicodedata.normalize("NFKD", s.lower())
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def normalize_genres(labels: list[str]) -> set[str]:
    """Ramène les libellés Wikidata à notre vocabulaire par mots-clés sans accents."""
    matched = set()
    for label in labels:
        lbl_plain = _plain(label)
        found = False
        for target_genre, kws in KEYWORDS_MAP.items():
            if any(_plain(kw) in lbl_plain for kw in kws):
                matched.add(target_genre)
                found = True
        if not found:
            pass

    if not matched:
        return {"autre"}
    return matched


def enrich(client: httpx.Client, title: str, kind: str) -> dict | None:
    """Interroge Wikidata SPARQL pour enrichir un titre."""
    # Échappement basique des guillemets pour SPARQL
    escaped_title = title.replace('"', '\\"')
    class_wd = "wd:Q11424" if kind == "film" else "wd:Q5398426"

    query = (
        QUERY_TEMPLATE
        .replace("__TITLE__", escaped_title)
        .replace("__CLASS__", class_wd)
    )

    headers = {
        "User-Agent": "streaming-platform-projet-etudiant/1.0",
        "Accept": "application/sparql-results+json",
    }

    try:
        response = client.get(
            SPARQL_URL,
            params={"query": query, "format": "json"},
            headers=headers,
        )
        response.raise_for_status()
        data = response.json()
    except Exception:
        return None

    bindings = data.get("results", {}).get("bindings", [])
    if not bindings:
        return None

    # Regroupement par item
    items_map = {}
    for b in bindings:
        item_uri = b.get("item", {}).get("value")
        if not item_uri:
            continue
        if item_uri not in items_map:
            items_map[item_uri] = {
                "qid": item_uri.split("/")[-1],
                "pub_dates": set(),
                "starts": set(),
                "genres": set(),
                "desc_fr": None,
                "desc_en": None,
            }

        pd = b.get("pubDate", {}).get("value")
        if pd:
            items_map[item_uri]["pub_dates"].add(pd)

        st = b.get("start", {}).get("value")
        if st:
            items_map[item_uri]["starts"].add(st)

        gl = b.get("genreLabel", {}).get("value")
        if gl:
            items_map[item_uri]["genres"].add(gl)

        df = b.get("descFr", {}).get("value")
        if df and not items_map[item_uri]["desc_fr"]:
            items_map[item_uri]["desc_fr"] = df

        de = b.get("descEn", {}).get("value")
        if de and not items_map[item_uri]["desc_en"]:
            items_map[item_uri]["desc_en"] = de

    if not items_map:
        return None

    # Pour chaque item, calculer l'année min (pubDate puis start)
    processed_items = []
    for item_uri, info in items_map.items():
        years = []
        for pd in info["pub_dates"]:
            if len(pd) >= 4:
                try:
                    years.append(int(pd[:4]))
                except ValueError:
                    pass
        for st in info["starts"]:
            if len(st) >= 4:
                try:
                    years.append(int(st[:4]))
                except ValueError:
                    pass

        min_year = min(years) if years else None
        processed_items.append((min_year, info))

    # Trier pour garder l'item à l'année la plus récente (None en dernier)
    processed_items.sort(key=lambda x: (x[0] is not None, x[0] if x[0] is not None else 0), reverse=True)

    best_year, best_info = processed_items[0]

    # Description : descFr sinon descEn
    description = best_info["desc_fr"] or best_info["desc_en"]

    genres_normalized = normalize_genres(list(best_info["genres"]))

    return {
        "qid": best_info["qid"],
        "year": best_year,
        "genres": genres_normalized,
        "description": description,
    }
