import os

import pytest
from cassandra.cluster import EXEC_PROFILE_DEFAULT, Cluster, ExecutionProfile
from cassandra.policies import DCAwareRoundRobinPolicy


@pytest.fixture(scope="session")
def cluster():
    contact_points = os.environ.get("CASSANDRA_CONTACT_POINTS", "cassandra1").split(",")
    profile = ExecutionProfile(
        load_balancing_policy=DCAwareRoundRobinPolicy(local_dc="dc1"),
        # Sur un portable, un DDL peut dépasser les 10 s par défaut (pauses JVM mesurées jusqu'à 24 s).
        request_timeout=60,
    )
    c = Cluster(
        contact_points,
        execution_profiles={EXEC_PROFILE_DEFAULT: profile},
        protocol_version=5,
        max_schema_agreement_wait=60,  # attendre que les 3 nœuds aient le même schéma après un DDL
    )
    yield c
    c.shutdown()


@pytest.fixture(scope="session")
def session(cluster):
    return cluster.connect()
