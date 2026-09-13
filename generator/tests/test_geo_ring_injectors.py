from generator.geo import haversine_km
from generator.injectors.geo import GeoInjector, MIN_FAR_KM
from generator.injectors.ring import MAX_ACCOUNTS, MIN_ACCOUNTS, RingInjector
from generator.models import Channel, FraudPattern
from generator.users import CITIES, far_cities


def test_haversine_known_distance():
    hyd = next(c for c in CITIES if c.name == "Hyderabad")
    delhi = next(c for c in CITIES if c.name == "Delhi")
    assert abs(haversine_km(hyd.lat, hyd.lon, delhi.lat, delhi.lon) - 1253) < 15
    assert haversine_km(1, 2, 1, 2) == 0.0


def test_every_city_has_a_far_partner():
    for c in CITIES:
        assert far_cities(c, MIN_FAR_KM), c.name


def test_geo_episode_is_anchor_plus_far_txns(users, traffic, rng, t0):
    inj = GeoInjector(users, traffic, rng)
    for _ in range(50):
        ep = inj.episode(t0)
        anchor, far = ep[0], ep[1:]
        assert anchor.label is None and anchor.at == t0
        assert anchor.txn.counterparty_id is None
        assert 1 <= len(far) <= 3
        assert all(f.label is not None and f.label.pattern is FraudPattern.GEO for f in far)
        assert all(f.txn.user_id == anchor.txn.user_id for f in far)
        gap_min = (far[0].at - t0).total_seconds() / 60
        assert 2 <= gap_min <= 10
        for f in far:
            km = haversine_km(anchor.txn.lat, anchor.txn.lon, f.txn.lat, f.txn.lon)
            assert km > 1000 - 10  # jitter of ~2 km each side
            hours = (f.at - t0).total_seconds() / 3600
            assert km / hours > 900  # implied speed the engine must flag
            assert f.txn.device_id != anchor.txn.device_id


def test_ring_episode_closes_the_cycle(users, traffic, rng, t0):
    inj = RingInjector(users, traffic, rng)
    for _ in range(50):
        ep = inj.episode(t0)
        k = len(ep)
        assert MIN_ACCOUNTS <= k <= MAX_ACCOUNTS
        srcs = [e.txn.user_id for e in ep]
        dsts = [e.txn.counterparty_id for e in ep]
        assert len(set(srcs)) == k  # distinct accounts
        assert dsts == srcs[1:] + srcs[:1]  # A→B, B→C, …, last→A
        assert all(e.txn.channel is Channel.P2P for e in ep)
        assert all(e.label is not None and e.label.pattern is FraudPattern.RING for e in ep)
        assert [e.at for e in ep] == sorted(e.at for e in ep)
        minutes = (ep[-1].at - ep[0].at).total_seconds() / 60
        assert minutes <= 30
        amounts = [e.txn.amount for e in ep]
        assert all(b <= a for a, b in zip(amounts, amounts[1:]))  # shrinks each hop
