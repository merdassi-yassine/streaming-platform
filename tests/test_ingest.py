"""Tests unitaires et d'intégration pour l'ingestion (Netflix, Wikidata, Load)."""

from __future__ import annotations

import datetime
import uuid
import httpx
import pytest

from streaming.schema import create_schema, drop_schema
from streaming.ingest.netflix import parse, title_id
from streaming.ingest.wikidata import normalize_genres, enrich
from streaming.ingest.load import load
from streaming.dao.views import ViewDAO
from streaming.dao.titles import TitleDAO


TEST_KEYSPACE = "streaming_test_ingest"


@pytest.fixture(scope="function")
def pytest_keyspace(session):
    """Fixture créant et supprimant un keyspace de test dédié."""
    create_schema(session, keyspace=TEST_KEYSPACE, replication_factor=1)
    yield TEST_KEYSPACE
    drop_schema(session, TEST_KEYSPACE)


SAMPLE_TSV = """week\tcategory\tweekly_rank\tshow_title\tseason_title\tweekly_hours_viewed\truntime\tweekly_views\tcumulative_weeks_in_top_10
2026-11-22\tFilms (English)\t1\tGuarding Stars\tN/A\t50600000\t1.8333\t27600000\t1
2026-11-22\tTV (English)\t1\tThe Body\tThe Body: Season 1\t70300000\t7.3833\t9500000\t2
2026-11-15\tFilms (English)\t2\tGuarding Stars\tN/A\t40000000\t1.8333\t20000000\t2
2026-11-01\tFilms (English)\t5\tOld Movie\tN/A\t10000000\t2.0\t5000000\t1
"""


def test_parse_netflix():
    """Vérifie que parse garde les N semaines les plus récentes et gère les valeurs vides/N/A."""
    rows = parse(SAMPLE_TSV, weeks=2)
    # Les semaines dans le sample sont 2026-11-22, 2026-11-15, 2026-11-01.
    # Les 2 plus récentes sont 2026-11-22 et 2026-11-15 (3 lignes au total).
    assert len(rows) == 3
    weeks_found = {r["week"] for r in rows}
    assert weeks_found == {datetime.date(2026, 11, 22), datetime.date(2026, 11, 15)}

    # Vérification des types et champs
    guarding = next(r for r in rows if r["title"] == "Guarding Stars" and r["week"] == datetime.date(2026, 11, 22))
    assert guarding["kind"] == "film"
    assert guarding["season"] is None
    assert guarding["views"] == 27600000
    assert guarding["runtime_minutes"] == round(1.8333 * 60)

    body = next(r for r in rows if r["title"] == "The Body")
    assert body["kind"] == "serie"
    assert body["season"] == "The Body: Season 1"


def test_title_id_stability():
    """Vérifie que title_id est stable (uuid5) et identique pour un même titre."""
    id1 = title_id("film", "Guarding Stars")
    id2 = title_id("film", "Guarding Stars")
    id3 = title_id("serie", "Guarding Stars")
    assert id1 == id2
    assert id1 != id3
    assert isinstance(id1, uuid.UUID)


def test_normalize_genres():
    """Vérifie la normalisation des genres Wikidata."""
    assert normalize_genres(["film d'animation", "action"]) == {"animation", "action"}
    assert normalize_genres(["comédie romantique"]) == {"comedie", "romance"}
    assert normalize_genres(["genre inconnu xyz"]) == {"autre"}


def test_enrich_wikidata_mock():
    """Teste enrich avec un MockTransport httpx simulant Wikidata SPARQL."""
    sparql_json_response = {
        "results": {
            "bindings": [
                {
                    "item": {"value": "http://www.wikidata.org/entity/Q12345"},
                    "pubDate": {"value": "2026-01-01T00:00:00Z"},
                    "genreLabel": {"value": "science-fiction"},
                    "descFr": {"value": "Un film de science fiction."},
                }
            ]
        }
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=sparql_json_response)

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)

    result = enrich(client, "Guarding Stars", "film")
    assert result is not None
    assert result["qid"] == "Q12345"
    assert result["year"] == 2026
    assert result["genres"] == {"science-fiction"}
    assert result["description"] == "Un film de science fiction."

    # Test sans résultat
    empty_handler = lambda req: httpx.Response(200, json={"results": {"bindings": []}})
    client_empty = httpx.Client(transport=httpx.MockTransport(empty_handler))
    assert enrich(client_empty, "Inconnu", "film") is None


def test_load_end_to_end(session, pytest_keyspace):
    """Teste le chargement complet (load) avec un enrich_fn factice et vérifie les vues du jour."""
    rows = parse(SAMPLE_TSV, weeks=1)

    def dummy_enrich(title: str, kind: str):
        if title == "Guarding Stars":
            return {
                "qid": "Q111",
                "year": 2026,
                "genres": {"action"},
                "description": "Desc of Guarding Stars",
            }
        return None

    report = load(session, pytest_keyspace, rows, dummy_enrich)
    assert report["titles"] == 2
    assert report["wikidata_found"] == 1
    assert "The Body" in report["wikidata_missing"]

    # Vérification des vues du jour via ViewDAO
    view_dao = ViewDAO(session, pytest_keyspace)
    day = datetime.date(2026, 11, 22)
    views_day = view_dao.views_of_day(day)

    guarding_id = title_id("film", "Guarding Stars")
    assert guarding_id in views_day
    assert views_day[guarding_id] == 27600000

    # Vérification TitleDAO
    title_dao = TitleDAO(session, pytest_keyspace)
    t = title_dao.get(guarding_id)
    assert t is not None
    assert t.title == "Guarding Stars"
    assert t.synopsis == "Desc of Guarding Stars"
    assert t.release_year == 2026
    assert t.genres == {"action"}
