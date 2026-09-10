import random
from datetime import datetime, timezone

import pytest

from generator.traffic import BaseTraffic
from generator.users import build_population


@pytest.fixture
def rng() -> random.Random:
    return random.Random(1234)


@pytest.fixture
def users():
    return build_population(50, seed=7)


@pytest.fixture
def traffic(users, rng) -> BaseTraffic:
    return BaseTraffic(users, tps=50.0, rng=rng)


@pytest.fixture
def t0() -> datetime:
    return datetime(2026, 9, 4, 10, 15, 3, 120000, tzinfo=timezone.utc)
