"""Module d'ingestion des classements Netflix Top 10."""

from __future__ import annotations

import csv
import io
import uuid
from datetime import date
from typing import Dict, List, Optional
import httpx

NETFLIX_URL = "https://www.netflix.com/tudum/top10/data/all-weeks-global.tsv"


def fetch(client: httpx.Client) -> str:
    """Télécharge le fichier TSV Netflix Top 10 et retourne son contenu textuel."""
    response = client.get(NETFLIX_URL)
    response.raise_for_status()
    return response.text


def parse(tsv_text: str, weeks: int = 4) -> List[Dict]:
    """Parse le TSV Netflix et ne garde que les `weeks` semaines les plus récentes."""
    f = io.StringIO(tsv_text.strip())
    reader = csv.DictReader(f, delimiter="\t")
    rows = list(reader)

    if not rows:
        return []

    # Extraire toutes les semaines uniques triées par ordre chronologique
    all_weeks = sorted(list({r["week"] for r in rows if r.get("week")}))
    if not all_weeks:
        return []

    recent_weeks = set(all_weeks[-weeks:])

    parsed_rows = []
    for r in rows:
        week_str = r.get("week", "").strip()
        if week_str not in recent_weeks:
            continue

        category = r.get("category", "").strip()
        kind = "film" if category.startswith("Films") else "serie"

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
                rt_val = float(runtime_raw)
                runtime_minutes = round(rt_val * 60)
            except ValueError:
                pass

        try:
            week_date = date.fromisoformat(week_str)
        except ValueError:
            continue

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
