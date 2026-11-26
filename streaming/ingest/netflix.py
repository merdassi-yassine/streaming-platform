"""Ingestion des données Netflix Top 10."""

from __future__ import annotations

import csv
import io
import uuid
from datetime import datetime
import httpx

NETFLIX_URL = "https://www.netflix.com/tudum/top10/data/all-weeks-global.tsv"


def fetch(client: httpx.Client) -> str:
    """Télécharge le fichier TSV Netflix Top 10."""
    response = client.get(NETFLIX_URL)
    response.raise_for_status()
    return response.text


def parse(tsv_text: str, weeks: int = 4) -> list[dict]:
    """Parse le TSV Netflix et ne garde que les `weeks` semaines les plus récentes."""
    f = io.StringIO(tsv_text.strip())
    reader = csv.DictReader(f, delimiter="\t")
    rows = list(reader)

    if not rows:
        return []

    # Extraire toutes les semaines uniques triées de la plus ancienne à la plus récente
    all_weeks = sorted(list({r["week"] for r in rows if r.get("week")}))
    recent_weeks = set(all_weeks[-weeks:]) if weeks > 0 else set(all_weeks)

    result = []
    for r in rows:
        w_str = r.get("week")
        if not w_str or w_str not in recent_weeks:
            continue

        try:
            week_date = datetime.strptime(w_str, "%Y-%m-%d").date()
        except ValueError:
            continue

        category = r.get("category", "")
        kind = "film" if category.lower().startswith("films") else "serie"

        show_title = r.get("show_title", "").strip()
        season_title = r.get("season_title", "").strip()
        if not season_title or season_title.upper() == "N/A":
            season = None
        else:
            season = season_title

        try:
            rank = int(r.get("weekly_rank", 0) or 0)
        except ValueError:
            rank = 0

        try:
            views = int(r.get("weekly_views", 0) or 0)
        except ValueError:
            views = 0

        try:
            hours = int(r.get("weekly_hours_viewed", 0) or 0)
        except ValueError:
            hours = 0

        runtime_raw = r.get("runtime", "")
        runtime_minutes = None
        if runtime_raw:
            try:
                rt_float = float(runtime_raw)
                runtime_minutes = round(rt_float * 60)
            except ValueError:
                pass

        result.append({
            "week": week_date,
            "kind": kind,
            "title": show_title,
            "season": season,
            "rank": rank,
            "views": views,
            "hours": hours,
            "runtime_minutes": runtime_minutes,
            "category": category,
        })

    return result


def title_id(kind: str, title: str) -> uuid.UUID:
    """Génère un UUID v5 stable pour un titre Netflix."""
    return uuid.uuid5(uuid.NAMESPACE_URL, f"netflix-top10:{kind}:{title}")
