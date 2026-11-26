"""Module d'ingestion et de chargement des données Netflix Top 10 et Wikidata dans Cassandra."""

from __future__ import annotations

import os
import time
from datetime import datetime
from pathlib import Path
import httpx

from ..schema import TABLES, KEYSPACE
from ..dao.titles import TitleDAO
from ..dao.views import ViewDAO
from ..models import Title
from .netflix import fetch, parse, title_id
from .wikidata import enrich


def reset(session, keyspace: str = KEYSPACE) -> None:
    """Vide (TRUNCATE) toutes les tables du schéma."""
    for table in TABLES:
        session.execute(f"TRUNCATE {keyspace}.{table}")


def load(session, keyspace: str, rows: list[dict], enrich_fn) -> dict:
    """Charge les lignes Netflix et enrichit via Wikidata, puis insère dans Cassandra."""
    title_dao = TitleDAO(session, keyspace)
    view_dao = ViewDAO(session, keyspace)

    # Regrouper par title_id pour traiter chaque titre unique une seule fois
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

    wikidata_found = 0
    wikidata_missing = []
    weeks_set = set()

    for t_id, info in titles_map.items():
        weeks_set.update([w[0] for w in info["weeks"]])
        
        # Appel enrich_fn UNE seule fois par titre distinct
        wiki_data = enrich_fn(info["title"], info["kind"])
        
        synopsis = "Description indisponible sur Wikidata"
        release_year = None
        genres = {"autre"}
        duration_minutes = info["runtime_minutes"] if info["kind"] == "film" else None

        if wiki_data:
            wikidata_found += 1
            if wiki_data.get("description"):
                synopsis = wiki_data["description"]
            if wiki_data.get("year"):
                release_year = wiki_data["year"]
            if wiki_data.get("genres"):
                genres = wiki_data["genres"]
        else:
            wikidata_missing.append(info["title"])

        # Si release_year toujours None, prendre l'année de la première semaine dispo
        if release_year is None and info["weeks"]:
            release_year = info["weeks"][0][0].year

        title_obj = Title(
            title_id=t_id,
            title=info["title"],
            kind="movie" if info["kind"] == "film" else "series",
            release_year=release_year or 2026,
            genres=genres,
            synopsis=synopsis,
            duration_minutes=duration_minutes,
            episodes_count=None,
        )
        title_dao.save(title_obj)

        # Enregistrer les vues par semaine (ViewDAO.add_views)
        for week_date, views_count in info["weeks"]:
            if views_count > 0:
                view_dao.add_views(t_id, week_date, views_count)

    weeks_iso = sorted([w.isoformat() for w in weeks_set])

    return {
        "titles": len(titles_map),
        "rows": len(rows),
        "weeks": weeks_iso,
        "wikidata_found": wikidata_found,
        "wikidata_missing": wikidata_missing,
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
    print(f"Réinitialisation du keyspace {KEYSPACE}...")
    reset(session, KEYSPACE)

    print(f"Téléchargement de Netflix Top 10 depuis {fetch.__globals__.get('NETFLIX_URL')}...")
    client = httpx.Client(timeout=30, follow_redirects=True)
    try:
        tsv_text = fetch(client)
    finally:
        client.close()

    print("Parsing des 4 semaines les plus récentes...")
    rows = parse(tsv_text, weeks=4)

    print("Chargement et enrichissement Wikidata en cours...")
    wikidata_client = httpx.Client(timeout=30, follow_redirects=True)

    def rate_limited_enrich(title: str, kind: str):
        res = enrich(wikidata_client, title, kind)
        time.sleep(0.3)
        return res

    report = load(session, KEYSPACE, rows, rate_limited_enrich)
    wikidata_client.close()

    # Écriture du rapport dans reports/ingest/
    now_str = datetime.now().strftime("%Y%m%d-%H%M%S")
    reports_dir = Path("reports/ingest")
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / f"ingest-{now_str}.md"

    missing = "\n".join(f"  - {t}" for t in report["wikidata_missing"]) or "  - Aucun"
    report_content = f"""# Rapport d'ingestion – {now_str}

- **Source Netflix** : {fetch.__globals__.get('NETFLIX_URL')}
- **Semaines traitées** : {report['weeks']}
- **Titres distincts chargés** : {report['titles']}
- **Lignes de visionnage traitées** : {report['rows']}
- **Correspondances Wikidata trouvées** : {report['wikidata_found']}
- **Titres sans correspondance Wikidata** :
{missing}
"""
    report_path.write_text(report_content, encoding="utf-8")
    print(f"Rapport d'ingestion généré : {report_path}")

    cluster.shutdown()


if __name__ == "__main__":
    main()
