import datetime
import uuid
import pytest

from streaming.dao import RatingDAO, StatsDAO, TitleDAO, UserDAO, ViewDAO
from streaming.models import Title, User
from streaming.schema import create_schema, drop_schema
from streaming.services import CatalogService, ReviewService, TrendingService

KS_SRV = "streaming_test_services"


@pytest.fixture(scope="module")
def schema_srv(session):
    create_schema(session, KS_SRV, replication_factor=1)
    yield
    drop_schema(session, KS_SRV)


def test_services_catalog_and_review(session, schema_srv):
    t_dao = TitleDAO(session, KS_SRV)
    u_dao = UserDAO(session, KS_SRV)
    r_dao = RatingDAO(session, KS_SRV)
    s_dao = StatsDAO(session, KS_SRV)

    cat_srv = CatalogService(t_dao, s_dao)
    rev_srv = ReviewService(u_dao, t_dao, r_dao)

    tid = uuid.uuid4()
    uid = uuid.uuid4()

    # Inconnu -> LookupError
    with pytest.raises(LookupError):
        rev_srv.rate(uid, tid, 5)

    u_dao.save(User(user_id=uid, email="t@t.com", username="tester", created_at=datetime.datetime.now(datetime.timezone.utc)))
    with pytest.raises(LookupError):
        rev_srv.rate(uid, tid, 5)

    t_dao.save(Title(title_id=tid, title="Test Movie", kind="movie", release_year=2020, genres={"Drama"}, synopsis=None, duration_minutes=100, episodes_count=None))
    
    # Valide
    rev_srv.rate(uid, tid, 4, comment="Good")

    details = cat_srv.title_details(tid)
    assert details is not None
    assert details["average_rating"] == 4.0
    assert details["rating_count"] == 1


def test_trending_service_top10(session, schema_srv):
    t_dao = TitleDAO(session, KS_SRV)
    v_dao = ViewDAO(session, KS_DAOMock if False else ViewDAO(session, KS_SRV))
    trend_srv = TrendingService(v_dao, t_dao)

    today = datetime.date.today()
    now = datetime.datetime.now(datetime.timezone.utc)

    # Insérer 12 titres avec des vues différentes
    for i in range(12):
        tid = uuid.uuid4()
        t_dao.save(Title(title_id=tid, title=f"Film {i}", kind="movie", release_year=2020, genres={"Action"}, synopsis=None, duration_minutes=90, episodes_count=None))
        # Enregistrer i vues pour donner un classement clair
        for _ in range(i + 1):
            v_dao.record_view(uuid.uuid4(), tid, now)

    top = trend_srv.top10(today)
    assert len(top) <= 10
    # Vérifier l'ordre décroissant par vues
    views_list = [item["views"] for item in top]
    assert views_list == sorted(views_list, reverse=True)
