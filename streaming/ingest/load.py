"""Module principal d'ingestion et chargement des données Netflix et Wikidata."""

from __future__ import annotations

import os
import time
from datetime import datetime
from typing import Callable, Dict, List, Optional
import httpx

from cassandra.cluster import Cluster
from cassandra.policies import DCAwareRoundRobinPolicy

from ..schema import KEYSPACE, TABLES, create_schema, drop_schema
from ..models import Title
from ..dao.titles import TitleDAO
from ..dao.views import ViewDAO
from .netflix import NETFLIX_URL, fetch, parse, title_id
from .wikidata import enrich


def reset(session, keyspace: str) -> None:
    """Effectue un TRUNCATE de chaque table du schéma."""
    for table in TABLES:
        session.execute(f"TRUNCATE TABLE {keyspace}.{table}")


def load(session, keyspace: str, rows: List[Dict], enrich_fn: Callable[[str, str], Optional[Dict]]) -> Dict:
    """Charge les lignes Netflix et enrichit les titres via Wikidata."""
    title_dao = TitleDAO(session, keyspace)
    view_dao = ViewDAO(session, keyspace)

    distinct_titles = {}  # title_id -> row info
    weeks_set = set()

    for r in rows:
        t_id = title_id(r["kind"], r["title"])
        weeks_set.add(r["week"])
        if t_id not in distinct_titles:
            distinct_titles[t_id] = {
                "kind": r["kind"],
                "title": r["title"],
                "runtime_minutes": r["runtime_minutes"],
                "week": r["week"],
            }

    titles_count = 0
    wikidata_found = 0
    wikidata_missing = []

    for t_id, info in distinct_titles.items():
        title_name = info["title"]
        kind = info["kind"]
        runtime_min = info["runtime_minutes"]
        week_date = info["week"]

        enrich_data = None
        try:
            enrich_data = enrich_fn(title_name, kind)
        except Exception:
            pass

        if enrich_data and enrich_data.get("qid"):
            wikidata_found += 1
            synopsis = enrich_data.get("description") or "Description indisponible sur Wikidata"
            release_year = enrich_data.get("year") or week_date.year
            genres = enrich_data.get("genres") or {"autre"}
        else:
            wikidata_missing.append(title_name)
            synopsis = "Description indisponible sur Wikidata"
            release_year = week_date.year
            genres = {"autre"}

        duration = runtime_min if kind == "film" else None

        title_obj = Title(
            title_id=t_id,
            title=title_name,
            kind="movie" if kind == "film" else "series",
            release_year=release_year,
            genres=genres,
            synopsis=synopsis,
            duration_minutes=duration,
            episodes_count=None,
        )
        title_dao.save(title_obj)
        titles_count += 1

    # Enregistrer les vues
    total_rows = 0
    for r in rows:
        t_id = title_id(r["kind"], r["title"])
        views_count = r["views"]
        week_d = r["week"]
        if views_count > 0:
            view_dao.add_views(t_id, week_d, views_count)
        total_rows += 1

    weeks_iso = sorted([w.isoformat() for w in weeks_set])

    return {
        "titles": titles_count,
        "rows": total_rows,
        "weeks": weeks_iso,
        "wikidata_found": wikidata_found,
        "wikidata_missing": sorted(list(set(wikidata_missing))),
    }


def main() -> None:
    """Point d'entrée de l'ingestion (python -m streaming.ingest.load)."""
    contact_points = os.getenv("CASSANDRA_CONTACT_POINTS", "127.0.0.1").split(",")
    cluster = Cluster(
        contact_points=contact_points,
        load_balancing_policy=DCAwareRoundRobinPolicy(local_dc="dc1"),
    )
    session = cluster.connect()

    create_schema(session, KEYSPACE)
    reset(session, KEYSPACE)

    client = httpx.Client(timeout=30, follow_redirects=True)
    try:
        print(f"Téléchargement de {NETFLIX_URL}...")
        tsv_text = fetch(client)
        print("Parsing du TSV (4 dernières semaines)...")
        rows = parse(tsv_text, weeks=4)
        print(f"{len(rows)} lignes parsées. Lancement du chargement avec enrichissement Wikidata...")

        def enrich_with_sleep(title: str, kind: str) -> Optional[Dict]:
            res = enrich(client, title, kind)
            time.sleep(0.3)
            return res

        report = load(session, KEYSPACE, rows, enrich_with_sleep)

        os.makedirs("reports/ingest", exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        report_path = f"reports/ingest/ingest-{timestamp}.md"

        content = f"""# Rapport d'ingestion Netflix Top 10 & Wikidata ({timestamp})

## Sources
- **Netflix Top 10 URL**: {NETFLIX_URL}
- **Dernière semaine incluse**: {report['weeks'][-1] if report['weeks'] else 'N/A'}
- **Semaines traitées**: {', '.join(report['weeks'])}

## Statistiques
- **Titres distincts chargés**: {report['titles']}
- **Lignes de vues traitées**: {report['rows']}
- **Correspondances Wikidata trouvées**: {report['wikidata_found']}
- **Titres sans correspondance Wikidata**: {len(report['wikidata_missing'])}

## Titres sans correspondance Wikidata
"""
        for missing in report["wikidata_missing"]:
            content += f"- {missing}\n"

        with open(report_path, "w", encoding="utf-8") as f:
            f.write(content)

        print(f"Ingestion terminée avec succès. Rapport généré : {report_path}")

    finally:
        client.close()
        cluster.shutdown()


if __name__ == "__main__":
    main()
