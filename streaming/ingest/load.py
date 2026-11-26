"""Module d'ingestion et de chargement des données Netflix Top 10 et Wikidata dans Cassandra."""

from __future__ import annotations

import os
import time
from datetime import datetime
from pathlib import Path
import httpx

from ..schema import KEYSPACE, TABLES, create_schema
from ..dao.titles import TitleDAO
from ..dao.views import ViewDAO
from ..models import Title
from .netflix import fetch, parse, title_id
from .wikidata import enrich_many, WikidataError


def reset(session, keyspace: str = KEYSPACE) -> None:
    """Vide (TRUNCATE) toutes les tables du schéma."""
    for table in TABLES:
        session.execute(f"TRUNCATE {keyspace}.{table}")


def load(session, keyspace: str, rows: list[dict], enrich_many_fn) -> dict:
    """Charge les lignes Netflix et enrichit via Wikidata par type (film/serie), puis insère dans Cassandra."""
    title_dao = TitleDAO(session, keyspace)
    view_dao = ViewDAO(session, keyspace)

    # Regrouper par title_id
    titles_map = {}
    for r in rows:
        t_id = title_id(r["kind"], r["title"])
        if t_id not in titles_map:
            titles_map[t_id] = {
                "title": r["title"],
                "kind": r["kind"],
                "runtime_minutes": r["runtime_minutes"],
                "weeks": [],
            }
        titles_map[t_id]["weeks"].append((r["week"], r["views"]))

    # Séparer les titres par type ("film" et "serie")
    films_by_title = {}  # title -> t_id
    series_by_title = {}  # title -> t_id
    for t_id, info in titles_map.items():
        if info["kind"] == "film":
            films_by_title[info["title"]] = t_id
        else:
            series_by_title[info["title"]] = t_id

    wikidata_found = 0
    wikidata_missing = []
    wikidata_errors = {}
    weeks_set = set()

    # Fonction d'appel et d'intégration pour un ensemble de titres d'un type donné
    def process_category_titles(titles_dict: dict, kind: str):
        nonlocal wikidata_found
        if not titles_dict:
            return

        titles_list = list(titles_dict.keys())
        try:
            enriched_dict = enrich_many_fn(titles_list, kind)
        except Exception as e:
            err_msg = str(e)
            for t in titles_list:
                wikidata_errors[t] = err_msg
            return

        for title_str, t_id in titles_dict.items():
            wiki_data = enriched_dict.get(title_str)
            info = titles_map[t_id]
            weeks_set.update([w[0] for w in info["weeks"]])

            synopsis = "Description indisponible sur Wikidata"
            release_year = None
            genres = {"autre"}
            duration_minutes = info["runtime_minutes"] if kind == "film" else None

            if wiki_data:
                wikidata_found += 1
                if wiki_data.get("description"):
                    synopsis = wiki_data["description"]
                if wiki_data.get("year"):
                    release_year = wiki_data["year"]
                if wiki_data.get("genres"):
                    genres = wiki_data["genres"]
            else:
                wikidata_missing.append(title_str)

            if release_year is None and info["weeks"]:
                release_year = info["weeks"][0][0].year

            title_obj = Title(
                title_id=t_id,
                title=title_str,
                kind="movie" if kind == "film" else "series",
                release_year=release_year or 2026,
                genres=genres,
                synopsis=synopsis,
                duration_minutes=duration_minutes,
                episodes_count=None,
            )
            title_dao.save(title_obj)

            for week_date, views_count in info["weeks"]:
                if views_count > 0:
                    view_dao.add_views(t_id, week_date, views_count)

    # Traiter les films puis les séries
    process_category_titles(films_by_title, "film")
    process_category_titles(series_by_title, "serie")

    weeks_iso = sorted([w.isoformat() for w in weeks_set])

    return {
        "titles": len(titles_map),
        "rows": len(rows),
        "weeks": weeks_iso,
        "wikidata_found": wikidata_found,
        "wikidata_missing": wikidata_missing,
        "wikidata_errors": wikidata_errors,
    }


def main() -> None:
    """Point d'entrée principal pour l'ingestion (exécuté en CLI)."""
    from cassandra.cluster import Cluster
    from cassandra.policies import DCAwareRoundRobinPolicy

    contact_points = os.getenv("CASSANDRA_CONTACT_POINTS", "127.0.0.1").split(",")
    cluster = Cluster(
        contact_points=contact_points,
        load_balancing_policy=DCAwareRoundRobinPolicy(local_dc="dc1"),
    )
    session = cluster.connect()

    print(f"Connexion au cluster Cassandra établie sur {contact_points}...")

    # Correction humaine (26/11/2026) : on télécharge et on analyse AVANT de vider la base — une panne
    # réseau laissait sinon la plateforme vide. Copie brute conservée (preuve de la source) ; la variable
    # NETFLIX_TSV_FILE permet de recharger une copie locale si netflix.com est injoignable.
    netflix_url = fetch.__globals__.get("NETFLIX_URL")
    local_file = os.getenv("NETFLIX_TSV_FILE")
    downloaded_at = datetime.now().isoformat(timespec="seconds")
    if local_file:
        print(f"Lecture de la copie locale {local_file} (source : {netflix_url})...")
        tsv_text = Path(local_file).read_text(encoding="utf-8")
        raw_path = Path(local_file)
    else:
        print(f"Téléchargement de Netflix Top 10 depuis {netflix_url}...")
        client = httpx.Client(timeout=30, follow_redirects=True)
        try:
            tsv_text = fetch(client)
        finally:
            client.close()
        raw_dir = Path("data/raw")
        raw_dir.mkdir(parents=True, exist_ok=True)
        raw_path = raw_dir / f"netflix-all-weeks-global-{datetime.now():%Y%m%d-%H%M%S}.tsv"
        raw_path.write_text(tsv_text, encoding="utf-8")

    print("Parsing des 4 semaines les plus récentes...")
    rows = parse(tsv_text, weeks=4)
    if not rows:
        raise SystemExit("Aucune ligne Netflix exploitable : base laissée intacte.")

    create_schema(session, KEYSPACE, replication_factor=3)
    print(f"Réinitialisation du keyspace {KEYSPACE}...")
    reset(session, KEYSPACE)

    print("Chargement et enrichissement Wikidata par lots en cours...")
    wikidata_client = httpx.Client(timeout=30, follow_redirects=True)

    def enrich_many_wrapper(titles: list[str], kind: str):
        return enrich_many(wikidata_client, titles, kind, pause=1.0)

    report = load(session, KEYSPACE, rows, enrich_many_wrapper)
    wikidata_client.close()

    # Écriture du rapport dans reports/ingest/
    now_str = datetime.now().strftime("%Y%m%d-%H%M%S")
    reports_dir = Path("reports/ingest")
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / f"ingest-{now_str}.md"

    missing = "\n".join(f"  - {t}" for t in report["wikidata_missing"]) or "  - Aucun"
    errors = "\n".join(f"  - {t}: {err}" for t, err in report["wikidata_errors"].items()) or "  - Aucune"

    report_content = f"""# Rapport d'ingestion – {now_str}

- **Source Netflix** : {netflix_url} (Netflix Top 10 officiel, téléchargé le {downloaded_at})
- **Copie brute conservée** : `{raw_path.as_posix()}`
- **Source Wikidata** : https://query.wikidata.org/sparql (licence CC0)
- **Semaines traitées** : {report['weeks']}
- **Titres distincts chargés** : {report['titles']}
- **Lignes de visionnage traitées** : {report['rows']}
- **Correspondances Wikidata trouvées** : {report['wikidata_found']}
- **Titres sans correspondance Wikidata** :
{missing}
- **Erreurs Wikidata (429/503/réseau)** :
{errors}
"""
    report_path.write_text(report_content, encoding="utf-8")
    print(f"Rapport d'ingestion généré : {report_path}")

    cluster.shutdown()


if __name__ == "__main__":
    main()
