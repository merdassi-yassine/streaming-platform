"""Tests unitaires et d'intégration pour l'ingestion (Netflix, Wikidata, Load)."""

from __future__ import annotations

import datetime
import uuid
import httpx
import pytest

from streaming.schema import create_schema, drop_schema
from streaming.ingest.netflix import parse, title_id
from streaming.ingest.wikidata import normalize_genres, enrich, enrich_many, WikidataError
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
    assert len(rows) == 3
    weeks_found = {r["week"] for r in rows}
    assert weeks_found == {datetime.date(2026, 11, 22), datetime.date(2026, 11, 15)}

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


def test_enrich_wikidata_grouped_and_homonym():
    """Teste enrich_many avec réponse factice groupée : 2 titres dont un homonyme à 2 items (garde le plus récent)."""
    sparql_json_response = {
        "results": {
            "bindings": [
                {
                    "label": {"value": "Guarding Stars"},
                    "item": {"value": "http://www.wikidata.org/entity/Q100"},
                    "pubDate": {"value": "2020-01-01T00:00:00Z"},
                    "genreLabel": {"value": "drame"},
                    "descFr": {"value": "Ancienne version."},
                },
                {
                    "label": {"value": "Guarding Stars"},
                    "item": {"value": "http://www.wikidata.org/entity/Q200"},
                    "pubDate": {"value": "2026-01-01T00:00:00Z"},
                    "genreLabel": {"value": "action"},
                    "descFr": {"value": "Version récente."},
                },
                {
                    "label": {"value": "Other Show"},
                    "item": {"value": "http://www.wikidata.org/entity/Q300"},
                    "pubDate": {"value": "2024-01-01T00:00:00Z"},
                    "genreLabel": {"value": "comedie"},
                    "descEn": {"value": "English description."},
                }
            ]
        }
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=sparql_json_response)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    res = enrich_many(client, ["Guarding Stars", "Other Show"], "film")

    assert "Guarding Stars" in res
    # Doit avoir choisi Q200 (année 2026 plus récente que 2020)
    assert res["Guarding Stars"]["qid"] == "Q200"
    assert res["Guarding Stars"]["year"] == 2026
    assert res["Guarding Stars"]["genres"] == {"action"}
    assert res["Guarding Stars"]["description"] == "Version récente."

    assert "Other Show" in res
    assert res["Other Show"]["qid"] == "Q300"
    assert res["Other Show"]["description"] == "English description."

    # Test liste vide -> None
    empty_client = httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(200, json={"results": {"bindings": []}})))
    assert enrich_many(empty_client, ["Unknown"], "film") == {}


def test_enrich_many_retry_429(monkeypatch):
    """Teste un lot qui renvoie 429 puis 200 (avec pause=0 et sleep monkeypatché)."""
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "1"})
        return httpx.Response(200, json={"results": {"bindings": [{"label": {"value": "Test"}, "item": {"value": "http://wd/Q1"}}]}})

    monkeypatch.setattr("time.sleep", lambda s: None)
    client = httpx.Client(transport=httpx.MockTransport(handler))
    res = enrich_many(client, ["Test"], "film", pause=0.0)
    assert calls == 2
    assert "Test" in res


def test_enrich_many_permanent_429(monkeypatch):
    """Teste un 429 permanent qui lève WikidataError après 3 essais."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "1"})

    monkeypatch.setattr("time.sleep", lambda s: None)
    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(WikidataError):
        enrich_many(client, ["Test"], "film", pause=0.0)


def test_load_end_to_end_with_errors(session, pytest_keyspace):
    """Teste le chargement load avec un enrich_many_fn qui lève une exception (capturée dans wikidata_errors)."""
    rows = parse(SAMPLE_TSV, weeks=1)

    def failing_enrich_many(titles, kind):
        raise WikidataError("HTTP 503 Service Unavailable")

    report = load(session, pytest_keyspace, rows, failing_enrich_many)
    assert len(report["wikidata_errors"]) > 0
    assert "HTTP 503" in list(report["wikidata_errors"].values())[0]

    # Test add_views incrémentation
    view_dao = ViewDAO(session, pytest_keyspace)
    day = datetime.date(2026, 11, 22)
    view_dao.add_views(title_id("film", "Guarding Stars"), day, 1000)
    views_day = view_dao.views_of_day(day)
    assert views_day[title_id("film", "Guarding Stars")] == 1000
