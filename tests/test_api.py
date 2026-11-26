import datetime
import uuid
import pytest
from fastapi.testclient import TestClient

from streaming.api import create_app
from streaming.dao import TitleDAO, UserDAO, ViewDAO, RatingDAO, StatsDAO
from streaming.models import Title, User
from streaming.schema import create_schema, drop_schema

KS_API = "streaming_test_api"


@pytest.fixture(scope="module")
def api_client(session):
    create_schema(session, KS_API, replication_factor=3)
    app = create_app(session, KS_API)
    client = TestClient(app)
    yield client
    drop_schema(session, KS_API)


def test_health_check(api_client):
    response = api_client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert "nodes_known" in data
    assert "nodes_up" in data
    assert data["nodes_known"] >= 1
    assert data["nodes_up"] >= 1


def test_get_title_not_found(api_client):
    tid = uuid.uuid4()
    response = api_client.get(f"/titles/{tid}")
    assert response.status_code == 404


def test_get_title_success(session, api_client):
    tid = uuid.uuid4()
    t_dao = TitleDAO(session, KS_API)
    t_dao.save(Title(
        title_id=tid,
        title="Inception",
        kind="movie",
        release_year=2010,
        genres={"Sci-Fi", "Action"},
        synopsis="A thief who steals corporate secrets...",
        duration_minutes=148,
        episodes_count=None,
    ))

    response = api_client.get(f"/titles/{tid}")
    assert response.status_code == 200
    data = response.json()
    assert data["title"]["title"] == "Inception"
    assert data["views"] == 0
    assert data["rating_count"] == 0


def test_get_genres_titles(session, api_client):
    tid = uuid.uuid4()
    t_dao = TitleDAO(session, KS_API)
    t_dao.save(Title(
        title_id=tid,
        title="Interstellar",
        kind="movie",
        release_year=2014,
        genres={"Sci-Fi"},
        synopsis="Space exploration",
        duration_minutes=169,
        episodes_count=None,
    ))

    response = api_client.get("/genres/Sci-Fi/titles")
    assert response.status_code == 200
    titles = response.json()
    assert any(t["title_id"] == str(tid) for t in titles)


def test_post_rating_validation_error(api_client):
    # Note hors 1..5 -> 422
    payload = {
        "user_id": str(uuid.uuid4()),
        "title_id": str(uuid.uuid4()),
        "rating": 6,
        "comment": "Too high"
    }
    response = api_client.post("/ratings", json=payload)
    assert response.status_code == 422


def test_post_rating_not_found(api_client):
    # Utilisateur ou titre inconnu -> 404
    payload = {
        "user_id": str(uuid.uuid4()),
        "title_id": str(uuid.uuid4()),
        "rating": 5,
        "comment": "Nice"
    }
    response = api_client.post("/ratings", json=payload)
    assert response.status_code == 404


def test_post_rating_success_and_history(session, api_client):
    uid = uuid.uuid4()
    tid = uuid.uuid4()
    u_dao = UserDAO(session, KS_API)
    t_dao = TitleDAO(session, KS_API)

    u_dao.save(User(user_id=uid, email="user@test.com", username="moviefan", created_at=datetime.datetime.now(datetime.timezone.utc)))
    t_dao.save(Title(title_id=tid, title="Matrix", kind="movie", release_year=1999, genres={"Action"}, synopsis=None, duration_minutes=136, episodes_count=None))

    payload = {
        "user_id": str(uid),
        "title_id": str(tid),
        "rating": 5,
        "comment": "Masterpiece"
    }
    response = api_client.post("/ratings", json=payload)
    assert response.status_code == 201

    res_title = api_client.get(f"/titles/{tid}")
    assert res_title.status_code == 200
    assert res_title.json()["rating_count"] == 1

    res_history = api_client.get(f"/users/{uid}/history")
    assert res_history.status_code == 200
    assert isinstance(res_history.json(), list)


def test_trending_endpoint(session, api_client):
    today = datetime.date.today().isoformat()
    response = api_client.get(f"/trending/{today}")
    assert response.status_code == 200
    assert isinstance(response.json(), list)
