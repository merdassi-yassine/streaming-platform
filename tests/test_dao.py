"""Tests des DAO sur un keyspace de test dédié."""

import uuid
from datetime import date, datetime, timezone

import pytest

from streaming.dao import RatingDAO, StatsDAO, TitleDAO, UserDAO, ViewDAO
from streaming.models import Title, User
from streaming.schema import create_schema, drop_schema

KS = "streaming_test_dao"


@pytest.fixture(scope="module")
def ks(session):
    create_schema(session, KS, replication_factor=3)
    yield KS
    drop_schema(session, KS)


def _make_title(title_id