"""Enrichissement des titres via Wikidata SPARQL (par lots)."""

from __future__ import annotations

import time
import unicodedata
import httpx

SPARQL_URL = "https://query.wikidata.org/sparql"

BATCH_QUERY = """SELECT ?label ?item ?pubDate ?start ?genreLabel ?descFr ?descEn WHERE {
  VALUES ?label { __VALUES__ }
  ?item rdfs:label ?label ; wdt:P31/wdt:P279* __CLASS__ .
  OPTIONAL { ?item wdt:P577 ?pubDate . }
  OPTIONAL { ?item wdt:P580 ?start . }
  OPTIONAL { ?item wdt:P136 ?genre . ?genre rdfs:label ?genreLabel . FILTER(LANG(?genreLabel) = "fr") }
  OPTIONAL { ?item schema:description ?descFr . FILTER(LANG(?descFr) = "fr") }
  OPTIONAL { ?item schema:description ?descEn . FILTER(LANG(?descEn) = "en") }
} LIMIT 5000"""

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


class WikidataError(Exception):
    """Exception levée en cas d'erreur persistante (ex: 429, 503) auprès de Wikidata."""
    pass


def _plain(s: str) -> str:
    """Met en minuscules et supprime les accents d'une chaîne."""
    nfkd = unicodedata.normalize("NFKD", s.lower())
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def normalize_genres(labels: list[str]) -> set[str]:
    """Ramène les libellés Wikidata à notre vocabulaire par mots-clés sans accents."""
    matched = set()
    for label in labels:
        lbl_plain = _plain(label)
        for target_genre, kws in KEYWORDS_MAP.items():
            if any(_plain(kw) in lbl_plain for kw in kws):
                matched.add(target_genre)

    if not matched:
        return {"autre"}
    return matched


def enrich_many(http: httpx.Client, titles: list[str], kind: str, pause: float = 1.0) -> dict[str, dict]:
    """Interroge Wikidata en SPARQL par lots de 20 titres."""
    if not titles:
        return {}

    class_wd = "wd:Q11424" if kind == "film" else "wd:Q5398426"
    results_map = {}

    # Découpage par lots de 20 titres max
    batch_size = 20
    for i in range(0, len(titles), batch_size):
        chunk = titles[i : i + batch_size]
        # Format des valeurs SPARQL : "Titre"@en séparés par des espaces
        values_str = " ".join(f'"{t.replace('"', \'\\"\')}"@en' for t in chunk)

        query = (
            BATCH_QUERY
            .replace("__VALUES__", values_str)
            .replace("__CLASS__", class_wd)
        )

        headers = {
            "User-Agent": "streaming-platform-projet-etudiant/1.0",
            "Accept": "application/sparql-results+json",
        }

        response = None
        for attempt in range(3):
            try:
                response = http.get(
                    SPARQL_URL,
                    params={"query": query, "format": "json"},
                    headers=headers,
                )
                if response.status_code in (429, 503):
                    retry_after_hdr = response.headers.get("Retry-After")
                    try:
                        wait_sec = int(retry_after_hdr) if retry_after_hdr else 30
                    except ValueError:
                        wait_sec = 30
                    sleep_time = min(wait_sec, 120)
                    if attempt < 2:
                        time.sleep(sleep_time)
                        continue
                response.raise_for_status()
                break
            except Exception as e:
                if attempt == 2:
                    status = response.status_code if response else "réseau/inconnue"
                    raise WikidataError(f"Erreur Wikidata persistante (HTTP {status}) pour le lot : {e}") from e
                time.sleep(pause)

        if response is None or response.status_code != 200:
            status = response.status_code if response else "inconnu"
            raise WikidataError(f"Échec de la requête SPARQL (HTTP {status}) après 3 essais.")

        data = response.json()
        bindings = data.get("results", {}).get("bindings", [])

        # Regroupement par label puis par item
        labels_bindings = {}
        for b in bindings:
            label_val = b.get("label", {}).get("value")
            item_uri = b.get("item", {}).get("value")
            if not label_val or not item_uri:
                continue

            if label_val not in labels_bindings:
                labels_bindings[label_val] = {}

            items_map = labels_bindings[label_val]
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

        # Pour chaque label trouvé, déterminer l'item le plus récent
        for label_val, items_map in labels_bindings.items():
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

            if not processed_items:
                continue

            processed_items.sort(key=lambda x: (x[0] is not None, x[0] if x[0] is not None else 0), reverse=True)
            best_year, best_info = processed_items[0]

            description = best_info["desc_fr"] or best_info["desc_en"]
            genres_normalized = normalize_genres(list(best_info["genres"]))

            results_map[label_val] = {
                "qid": best_info["qid"],
                "year": best_year,
                "genres": genres_normalized,
                "description": description,
            }

        if i + batch_size < len(titles):
            time.sleep(pause)

    return results_map


def enrich(http: httpx.Client, title: str, kind: str) -> dict | None:
    """Interroge Wikidata SPARQL pour un titre unique."""
    res = enrich_many(http, [title], kind, pause=0.0)
    return res.get(title)
