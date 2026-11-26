"""Tests pour le module d'ingestion (Netflix, Wikidata, chargement DAO)."""

from __future__ import annotations

import uuid
from datetime import date
import httpx
import pytest

from streaming.schema import KEYSPACE, create_schema, drop_schema
from streaming.dao.titles import TitleDAO
from streaming.dao.views import ViewDAO
from streaming.ingest.netflix import parse, title_id
from streaming.ingest.wikidata import normalize_genres, enrich
from streaming.ingest.load import load, reset


@pytest.fixture
def ingest_keyspace(session):
    """Fixture créant un keyspace de test dédié, supprimé à la fin."""
    ks = "streaming_test_ingest"
    create_schema(session, keyspace=ks, replication_factor=1)
    yield ks
    drop_schema(session, keyspace=ks)


def test_parse_netflix():
    tsv = (
        "week\tcategory\tweekly_rank\tshow_title\tseason_title\tweekly_hours_viewed\truntime\tweekly_views\tcumulative_weeks_in_top_10\n"
        "2026-11-15\tFilms (English)\t1\tOld Movie\tN/A\t10000000\t2.0\t5000000\t1\n"
        "2026-11-22\tFilms (English)\t1\tGuarding Stars\tN/A\t50600000\t1.8333\t27600000\t1\n"
        "2026-11-22\tTV (English)\t1\tThe Body\tThe Body: Season 1\t70300000\t7.3833\t9500000\t2\n"
        "2026-11-22\tTV (English)\t2\tEmpty Views\t\t0\t\t\t1\n"
    )
    rows = parse(tsv, weeks=2)
    # Ne doit garder que les semaines 2026-11-15 et 2026-11-22 (2 semaines)
    assert len(rows) == 4

    # Vérifier le parsing et les valeurs vides
    guarding = next(r for r in rows if r["title"] == "Guarding Stars")
    assert guarding["kind"] == "film"
    assert guarding["season"] is None
    assert guarding["views"] == 27600000
    assert guarding["runtime_minutes"] == round(1.8333 * 60)

    empty_row = next(r for r in rows if r["title"] == "Empty Views")
    assert empty_row["views"] == 0
    assert empty_row["runtime_minutes"] is None
    assert empty_row["season"] is None


def test_title_id_stability():
    id1 = title_id("film", "Guarding Stars")
    id2 = title_id("film", "Guarding Stars")
    id3 = title_id("serie", "Guarding Stars")
    assert id1 == id2
    assert id1 != id3
    assert isinstance(id1, uuid.UUID)


def test_normalize_genres():
    assert normalize_genres(["Film d'animation", "Comédie romantique"]) == {"animation", "comedie", "romance"}
    assert normalize_genres(["Film policier et dramatique"]) == {"crime", "drame"}
    assert normalize_genres(["Inconnu XYZ"]) == {"autre"}


def test_enrich_mock():
    # Mock transport pour httpx
    def handler(request: httpx.Request) -> httpx.Response:
        data = {
            "results": {
                "bindings": [
                    {
                        "item": {"value": "http://www.wikidata.org/entity/Q12345"},
                        "pubDate": {"value": "2026-01-01T00:00:00Z"},
                        "desc": {"value": "Un film passionnant"},
                        "genreLabel": {"value": "Action"},
                    }
                ]
            }
        }
        return httpx.Response(200, json=data)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = enrich(client, "Test Movie", "film")
    assert result is not None
    assert result["qid"] == "Q12345"
    assert result["year"] == 2026
    assert result["genres"] == {"action"}
    assert result["description"] == "Un film passionnant"

    # Test sans résultat
    def handler_empty(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": {"bindings": []}})

    client_empty = httpx.Client(transport=httpx.MockTransport(handler_empty))
    assert enrich(client_empty, "Unknown", "film") is None


def test_add_views_dao(session, ingest_keyspace):
    view_dao = ViewDAO(session, ingest_keyspace)
    t_id = uuid.uuid4()
    d = date(2026, 11, 22)

    view_dao.add_views(t_id, d, 100)
    view_dao.add_views(t_id, d, 50)

    views = view_dao.views_of_day(d)
    assert views.get(t_id) == 150


def test_load_end_to_end(session, ingest_keyspace):
    reset(session, ingest_keyspace)

    rows = [
        {
            "week": date(2026, 11, 22),
            "kind": "film",
            "title": "Awesome Movie",
            "season": None,
            "rank": 1,
            "views": 1000,
            "hours": 5000,
            "runtime_minutes": 120,
            "category": "Films (English)",
        }
    ]

    def dummy_enrich(title: str, kind: str):
        return {
            "qid": "Q999",
            "year": 2026,
            "genres": {"action"},
            "description": "An awesome movie description",
        }

    report = load(session, ingest_keyspace, rows, dummy_enrich)
    assert report["titles"] == 1
    assert report["rows"] == 1
    assert report["wikidata_found"] == 1
    assert report["wikidata_missing"] == []

    # Vérification dans DAO
    title_dao = TitleDAO(session, ingest_keyspace)
    t_id = title_id("film", "Awesome Movie")
    saved_title = title_dao.get(t_id)
    assert saved_title is not None
    assert saved_title.title == "Awesome Movie"
    assert saved_title.synopsis == "An awesome movie description"

    view_dao = ViewDAO(session, ingest_keyspace)
    views = view_dao.views_of_day(date(2026, 11, 22))
    assert views.get(t_id) == 1000
