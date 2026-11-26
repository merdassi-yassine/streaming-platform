import datetime
import uuid
import pytest

from streaming.dao import RatingDAO, StatsDAO, TitleDAO, UserDAO, ViewDAO
from streaming.models import Title, User
from streaming.schema import create_schema, drop_schema

KS_DAO = "test_dao_ks"
KS_ACT = "test_act_ks"


@pytest.fixture(scope="module")
def schema_dao(session):
    create_schema(session, KS_DAO, replication_factor=1)
    yield
    drop_schema(session, KS_DAO)


@pytest.fixture(scope="module")
def schema_act(session):
    create_schema(session, KS_ACT, replication_factor=1)
    yield
    drop_schema(session, KS_ACT)


def test_title_dao_roundtrip(session, schema_dao):
    dao = TitleDAO(session, KS_DAO)
    tid = uuid.uuid4()
    t = Title(title_id=tid, title="Matrix", kind="movie", release_year=1999, genres={"Sci-Fi"}, synopsis="Hacker", duration_minutes=136, episodes_count=None)
    dao.save(t)
    fetched = dao.get(tid)
    assert fetched is not None
    assert fetched.title == "Matrix"
    assert fetched.genres == {"Sci-Fi"}


def test_user_dao_roundtrip(session, schema_dao):
    dao = UserDAO(session, KS_DAO)
    uid = uuid.uuid4()
    u = User(user_id=uid, email="neo@matrix.com", username="neo", created_at=datetime.datetime.now(datetime.timezone.utc))
    dao.save(u)
    fetched = dao.get(uid)
    assert fetched is not None
    assert fetched.username == "neo"


def test_list_by_genre(session, schema_dao):
    dao = TitleDAO(session, KS_DAO)
    tid = uuid.uuid4()
    dao.save(Title(title_id=tid, title="Inception", kind="movie", release_year=2010, genres={"Action"}, synopsis=None, duration_minutes=148, episodes_count=None))
    titles = dao.list_by_genre("Action")
    assert any(item["title_id"] == tid for item in titles)


def test_rating_dao_and_stats(session, schema_act):
    r_dao = RatingDAO(session, KS_ACT)
    s_dao = StatsDAO(session, KS_ACT)
    uid = uuid.uuid4()
    tid = uuid.uuid4()

    with pytest.raises(ValueError):
        r_dao.add(uid, tid, 6)

    r_dao.add(uid, tid, 5, comment="Super", username="alice", title="Film")
    r_dao.add(uuid.uuid4(), tid, 3, comment="Bien", username="bob", title="Film")

    for_title = r_dao.list_for_title(tid)
    assert len(for_title) == 2

    for_user = r_dao.list_for_user(uid)
    assert len(for_user) == 1

    views, sum_r, count_r = s_dao.get(tid)
    assert count_r == 2
    assert sum_r == 8


def test_view_dao_history_and_day(session, schema_act):
    v_dao = ViewDAO(session, KS_ACT)
    uid = uuid.uuid4()
    tid = uuid.uuid4()
    today = datetime.date.today()
    now = datetime.datetime.now(datetime.timezone.utc)

    v_dao.record_view(uid, tid, now, title="Inception", duration_watched_seconds=5400, completed=True)
    history = v_dao.history(uid)
    assert len(history) >= 1
    record = history[0]
    assert record["title"] == "Inception"
    assert record["duration_watched_seconds"] == 5400
    assert record["completed"] is True

    daily = v_dao.views_of_day(today)
    assert daily.get(tid, 0) >= 1


def test_extra_dao_coverage_users(session, schema_dao):
    dao = UserDAO(session, KS_DAO)
    assert dao.get(uuid.uuid4()) is None


def test_extra_dao_coverage_titles(session, schema_dao):
    dao = TitleDAO(session, KS_DAO)
    assert dao.get(uuid.uuid4()) is None
