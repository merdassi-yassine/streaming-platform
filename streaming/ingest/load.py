"""Module d'orchestration de l'ingestion (chargement et reset)."""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional
import httpx
from cassandra.cluster import Cluster
from cassandra.policies import DCAwareRoundRobinPolicy

from ..schema import KEYSPACE, TABLES, create_schema, drop_schema
from ..dao.titles import TitleDAO
from ..dao.views import ViewDAO
from ..models import Title
from .netflix import fetch, parse, title_id
from .wikidata import enrich, normalize_genres, SPARQL_URL


def reset(session, keyspace: str = KEYSPACE) -> None:
    """Effectue un TRUNCATE de chaque table du keyspace."""
    for table in TABLES:
        session.execute(f"TRUNCATE TABLE {keyspace}.{table}")


def load(session, keyspace: str, rows: List[Dict], enrich_fn: Callable[[str, str], Optional[Dict]]) -> Dict:
    """Charge les lignes Netflix et enrichit les titres via Wikidata."""
    title_dao = TitleDAO(session, keyspace)
    view_dao = ViewDAO(session, keyspace)

    # Regrouper par title_id pour identifier les titres distincts
    distinct_titles: Dict[uuid.UUID, Dict] = {}
    for r in rows:
        t_id = title_id(r["kind"], r["title"])
        if t_id not in distinct_titles:
            distinct_titles[t_id] = {
                "title_id": t_id,
                "title": r["title"],
                "kind": "film" if r["kind"] == "film" else "serie",  # normalisé en "film" / "serie"
                "runtime_minutes": r["runtime_minutes"],
                "week": r["week"],
            }

    titles_count = 0
    wikidata_found = 0
    wikidata_missing: List[str] = []
    weeks_set = set()

    for t_id, info in distinct_titles.items():
        t_name = info["title"]
        t_kind = info["kind"]
        runtime_min = info["runtime_minutes"]
        fallback_year = info["week"].year

        # Appel enrich_fn UNE seule fois par titre distinct
        wiki = enrich_fn(t_name, t_kind)

        synopsis = "Description indisponible sur Wikidata"
        release_year = fallback_year
        genres = {"autre"}
        duration_minutes = runtime_min if t_kind == "film" else None

        if wiki:
            wikidata_found += 1
            if wiki.get("description"):
                synopsis = wiki["description"]
            if wiki.get("year"):
                release_year = wiki["year"]
            raw_genres = wiki.get("genres", [])
            if raw_genres:
                genres = normalize_genres(raw_genres)
        else:
            wikidata_missing.append(t_name)

        title_obj = Title(
            title_id=t_id,
            title=t_name,
            kind=t_kind,
            release_year=release_year,
            genres=genres,
            synopsis=synopsis,
            duration_minutes=duration_minutes,
            episodes_count=None,
        )
        title_dao.save(title_obj)
        titles_count += 1

    # Insérer les vues pour chaque ligne
    for r in rows:
        t_id = title_id(r["kind"], r["title"])
        view_dao.add_views(t_id, r["week"], r["views"])
        weeks_set.add(r["week"].isoformat())

    return {
        "titles": titles_count,
        "rows": len(rows),
        "weeks": sorted(list(weeks_set)),
        "wikidata_found": wikidata_found,
        "wikidata_missing": sorted(wikidata_missing),
    }


def main() -> None:
    """Point d'entrée principal pour l'ingestion de données réelles."""
    cluster = Cluster(
        contact_points=["127.0.0.1"],
        load_balancing_policy=DCAwareRoundRobinPolicy(local_dc="dc1"),
    )
    session = cluster.connect()

    print(f"Création du schéma pour le keyspace {KEYSPACE}...")
    create_schema(session, KEYSPACE, replication_factor=3)
    print("Réinitialisation des données (TRUNCATE)...")
    reset(session, KEYSPACE)

    print("Téléchargement du Top 10 Netflix...")
    with httpx.Client(timeout=30, follow_redirects=True) as client:
        tsv_text = fetch(client)
        rows = parse(tsv_text, weeks=4)

        print(f"{len(rows)} lignes parsées. Lancement du chargement avec enrichissement Wikidata...")

        def bounded_enrich(title: str, kind: str) -> Optional[Dict]:
            res = enrich(client, title, kind)
            time.sleep(0.3)
            return res

        report_data = load(session, KEYSPACE, rows, bounded_enrich)

    # Écriture du rapport
    now_str = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    reports_dir = Path("reports/ingest")
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / f"ingest-{now_str}.md"

    latest_week = report_data["weeks"][-1] if report_data["weeks"] else "N/A"

    report_content = f"""# Rapport d'ingestion - {now_str}

## Sources
- **Netflix Top 10** : [https://www.netflix.com/tudum/top10/data/all-weeks-global.tsv](https://www.netflix.com/tudum/top10/data/all-weeks-global.tsv) (Dernière semaine : {latest_week})
- **Wikidata** : [{SPARQL_URL}]({SPARQL_URL}) (Licence CC0, téléchargement le {datetime.utcnow().strftime("%Y-%m-%d")})

## Statistiques
- **Titres distincts chargés** : {report_data['titles']}
- **Lignes de vues traitées** : {report_data['rows']}
- **Semaines traitées** : {len(report_data['weeks'])} ({', '.join(report_data['weeks'])})
- **Correspondances Wikidata trouvées** : {report_data['wikidata_found']}
- **Titres sans correspondance Wikidata** : {len(report_data['wikidata_missing'])}

## Titres sans correspondance Wikidata
{'\n'.join([f'- {t}' for t in report_data['wikidata_missing']]) if report_data['wikidata_missing'] else '- Aucun'}
"""

    report_path.write_text(report_content, encoding="utf-8")
    print(f"Rapport d'ingestion généré avec succès : {report_path}")

    session.shutdown()
    cluster.shutdown()


if __name__ == "__main__":
    main()
