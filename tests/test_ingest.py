"""Tests unitaires et d'intégration pour le module d'ingestion."""

from __future__ import annotations

import uuid
from datetime import date
import httpx
import pytest

from streaming.schema import create_schema, drop_schema, TABLES
from streaming.dao.titles import TitleDAO
from streaming.dao.views import ViewDAO
from streaming.ingest.netflix import parse, title_id
from streaming.ingest.wikidata import normalize_genres, enrich
from streaming.ingest.load import load, reset

TEST_KEYSPACE = "streaming_test_ingest"

SAMPLE_TSV = """week	category	weekly_rank	show_title	season_title	weekly_hours_viewed	runtime	weekly_views	cumulative_weeks_in_top_10
2026-11-22	Films (English)	1	Guarding Stars	N/A	50600000	1.8333	27600000	1
2026-11-22	TV (English)	1	The Body	The Body: Season 1	70300000		9500000	2
2026-11-15	Films (Non-English)	2	Other Film	N/A	10000000	2.0	5000000	1
"""


@pytest.fixture(scope="function")
def test_session(cluster):
    """Fixture créant un keyspace de test dédié et le supprimant à la fin."""
    session = cluster.connect()
    drop_schema(session, TEST_KEYSPACE)
    create_schema(session, TEST_KEYSPACE, replication_factor=1)
    session.set_keyspace(TEST_KEYSPACE)
    yield session
    drop_schema(session, TEST_KEYSPACE)


def test_parse_and_weeks():
    """Vérifie le parsing TSV, le filtre des N semaines et la gestion des valeurs vides."""
    rows = parse(SAMPLE_TSV, weeks=1)
    # Seule la semaine 2026-11-22 doit être gardée (la plus récente)
    assert len(rows) == 2
    assert all(r["week"] == date(2026, 11, 22) for r in rows)

    # Vérification des types et valeurs vides
    film_row = next(r for r in rows if r["title"] == "Guarding Stars")
    assert film_row["kind"] == "film"
    assert film_row["season"] is None
    assert film_row["views"] == 27600000
    assert film_row["runtime_minutes"] == 110  # round(1.8333 * 60) = 110

    tv_row = next(r for r in rows if r["title"] == "The Body")
    assert tv_row["kind"] == "serie"
    assert tv_row["season"] == "The Body: Season 1"
    assert tv_row["views"] == 9500000
    assert tv_row["runtime_minutes"] is None  # runtime vide


def test_title_id_stability():
    """Vérifie la stabilité de l'UUID v5 pour un titre et un kind donnés."""
    id1 = title_id("film", "Guarding Stars")
    id2 = title_id("film", "Guarding Stars")
    id3 = title_id("serie", "Guarding Stars")
    assert id1 == id2
    assert id1 != id3
    assert isinstance(id1, uuid.UUID)


def test_normalize_genres():
    """Vérifie la normalisation des genres Wikidata avec mots-clés et accents."""
    assert normalize_genres(["film d'animation", "Science-fiction"]) == {"animation", "science-fiction"}
    assert normalize_genres(["Comédie romantique"]) == {"comedie", "romance"}
    assert normalize_genres(["Film policier et dramatique"]) == {"crime", "drame"}
    assert normalize_genres(["Genre Inconnu"]) == {"autre"}


def test_enrich_wikidata_mock():
    """Vérifie l'enrichissement Wikidata avec mock HTTP (sélection du plus récent)."""
    sparql_response = {
        "results": {
            "bindings": [
                {
                    "item": {"value": "http://www.wikidata.org/entity/Q123"},
                    "pubDate": {"value": "2010-01-01T00:00:00Z"},
                    "genreLabel": {"value": "Drame"},
                    "desc": {"value": "An old movie", "xml:lang": "en"},
                },
                {
                    "item": {"value": "http://www.wikidata.org/entity/Q456"},
                    "pubDate": {"value": "2024-05-10T00:00:00Z"},
                    "genreLabel": {"value": "Action"},
                    "desc": {"value": "Un film récent", "xml:lang": "fr"},
                },
            ]
        }
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=sparql_response)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    res = enrich(client, "Test Movie", "film")

    assert res is not None
    assert res["qid"] == "Q456"
    assert res["year"] == 2024
    assert res["genres"] == ["Action"]
    assert res["description"] == "Un film récent"


def test_enrich_wikidata_not_found():
    """Vérifie qu'un résultat vide renvoie None."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": {"bindings": []}})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    res = enrich(client, "Unknown Title", "film")
    assert res is None


def test_load_end_to_end(test_session):
    """Test de bout en bout du chargement, enrichissement et compteurs de vues."""
    rows = parse(SAMPLE_TSV, weeks=1)

    def dummy_enrich(title: str, kind: str):
        if title == "Guarding Stars":
            return {
                "qid": "Q111",
                "year": 2025,
                "genres": ["Drame"],
                "description": "A wonderful star story",
            }
        return None

    report = load(test_session, TEST_KEYSPACE, rows, dummy_enrich)

    assert report["titles"] == 2
    assert report["rows"] == 2
    assert report["wikidata_found"] == 1
    assert "The Body" in report["wikidata_missing"]

    # Vérification du genre et du kind ("film" / "serie")
    title_dao = TitleDAO(test_session, TEST_KEYSPACE)
    t_id = title_id("film", "Guarding Stars")
    title_obj = title_dao.get(t_id)
    assert title_obj is not None
    assert title_obj.kind == "film"
    assert title_obj.release_year == 2025
    assert title_obj.synopsis == "A wonderful star story"

    # Vérification des vues du jour via ViewDAO
    view_dao = ViewDAO(test_session, TEST_KEYSPACE)
    views_map = view_dao.views_of_day(date(2026, 11, 22))
    assert views_map.get(t_id) == 27600000
