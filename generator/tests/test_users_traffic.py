import random
import statistics

from generator.models import Channel
from generator.traffic import BaseTraffic
from generator.users import DEFAULT_USERS, build_population


def test_population_is_deterministic_per_seed():
    a = build_population(20, seed=1)
    b = build_population(20, seed=1)
    c = build_population(20, seed=2)
    assert a == b
    assert a != c
    assert len({u.user_id for u in a}) == 20


def test_poisson_gaps_average_to_one_over_tps(users):
    traffic = BaseTraffic(users, tps=50.0, rng=random.Random(0))
    gaps = [traffic.next_gap_seconds() for _ in range(20_000)]
    assert abs(statistics.mean(gaps) - 1 / 50) < 0.002


def test_transactions_stay_near_home_and_have_valid_shape(traffic, users, t0):
    for u in users:
        for _ in range(5):
            txn = traffic.make_transaction(u, t0)
            assert txn.user_id == u.user_id
            assert abs(txn.lat - u.home.lat) < 0.03 and abs(txn.lon - u.home.lon) < 0.03
            assert txn.amount >= 1.0
            if txn.channel is Channel.P2P:
                assert txn.counterparty_id in u.contacts and txn.counterparty_id != u.user_id
            else:
                assert txn.counterparty_id is None
                assert txn.merchant_id in u.favourite_merchants


def test_contacts_are_small_and_never_self(users):
    for u in users:
        assert 2 <= len(u.contacts) <= 4
        assert u.user_id not in u.contacts


def test_default_population_keeps_honest_users_under_the_hourly_limit():
    """Engine velocity.limit1h is 60. At the default 50 tps the per-user hourly rate
    must sit well under half of it, or ordinary users get flagged (day-1 bug)."""
    per_user_per_hour = 50.0 * 3600 / DEFAULT_USERS
    assert per_user_per_hour < 30
