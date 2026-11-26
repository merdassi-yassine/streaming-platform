"""Module d'ingestion des données Netflix Top 10 (source 1)."""

from __future__ import annotations

import csv
import io
import uuid
from datetime import datetime
from typing import Dict, List, Optional
import httpx

NETFLIX_URL = "https://www.netflix.com/tudum/top10/data/all-weeks-global.tsv"


def fetch(http: httpx.Client) -> str:
    """Télécharge le fichier TSV Netflix brut et renvoie son contenu texte."""
    response = http.get(NETFLIX_URL)
    response.raise_for_status()
    return response.text


def parse(tsv_text: str, weeks: int = 4) -> List[Dict]:
    """Parse le TSV Netflix et ne garde que les `weeks` semaines les plus récentes."""
    f = io.StringIO(tsv_text.strip())
    reader = csv.DictReader(f, delimiter="\t")
    rows = list(reader)

    # Récupérer toutes les semaines uniques triées de la plus ancienne à la plus récente
    all_weeks = sorted({r["week"] for r in rows if r.get("week")})
    recent_weeks_set = set(all_weeks[-weeks:]) if all_weeks else set()

    parsed_rows = []
    for r in rows:
        wk_str = r.get("week", "").strip()
        if not wk_str or wk_str not in recent_weeks_set:
            continue

        week_date = datetime.strptime(wk_str, "%Y-%m-%d").date()
        category = r.get("category", "").strip()
        kind = "film" if category.lower().startswith("films") else "serie"

        show_title = r.get("show_title", "").strip()
        season_title_raw = r.get("season_title", "").strip()
        season = None if season_title_raw in ("", "N/A") else season_title_raw

        try:
            rank = int(r.get("weekly_rank", 0))
        except ValueError:
            rank = 0

        views_raw = r.get("weekly_views", "").strip()
        try:
            views = int(views_raw) if views_raw else 0
        except ValueError:
            views = 0

        hours_raw = r.get("weekly_hours_viewed", "").strip()
        try:
            hours = int(float(hours_raw)) if hours_raw else 0
        except ValueError:
            hours = 0

        runtime_raw = r.get("runtime", "").strip()
        runtime_minutes = None
        if runtime_raw:
            try:
                runtime_minutes = round(float(runtime_raw) * 60)
            except ValueError:
                pass

        parsed_rows.append({
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

    return parsed_rows


def title_id(kind: str, title: str) -> uuid.UUID:
    """Génère un UUID v5 stable pour un titre Netflix donné."""
    return uuid.uuid5(uuid.NAMESPACE_URL, f"netflix-top10:{kind}:{title}")
