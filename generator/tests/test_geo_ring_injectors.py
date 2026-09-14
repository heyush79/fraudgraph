from generator.geo import haversine_km
from generator.injectors.geo import GeoInjector, MIN_FAR_KM
from generator.injectors.ring import MAX_ACCOUNTS, MAX_MULTIPLIER, MIN_ACCOUNTS, RingInjector
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


def test_ring_amounts_overlap_legitimate_p2p(users, traffic, rng, t0):
    """The point of drawing ring amounts from the accounts' own spend: a model must not be
    able to separate rings by amount alone, or the graph feature never earns its place."""
    inj = RingInjector(users, traffic, rng)
    ring_amounts = [e.txn.amount for _ in range(60) for e in inj.episode(t0)]
    legit_amounts = [traffic.sample_amount(u) for u in users for _ in range(20)]

    ring_amounts.sort()
    legit_amounts.sort()
    legit_p95 = legit_amounts[int(len(legit_amounts) * 0.95)]
    # a good chunk of ring hops must sit inside the ordinary P2P range
    overlap = sum(1 for a in ring_amounts if a <= legit_p95) / len(ring_amounts)
    assert overlap > 0.25, f"only {overlap:.0%} of ring hops look like ordinary transfers"
    # and none should be absurd: the multiplier is bounded, so nothing is orders of magnitude out
    assert max(ring_amounts) <= max(legit_amounts) * MAX_MULTIPLIER
