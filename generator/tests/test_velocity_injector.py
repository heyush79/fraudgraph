from generator.injectors.velocity import MAX_SECS, MAX_TXNS, MIN_SECS, MIN_TXNS, VelocityInjector
from generator.models import FraudPattern


def test_episode_shape(users, traffic, rng, t0):
    inj = VelocityInjector(users, traffic, rng)
    for _ in range(50):
        ep = inj.episode(t0)
        assert MIN_TXNS <= len(ep) <= MAX_TXNS
        assert all(e.at >= t0 for e in ep)
        assert [e.at for e in ep] == sorted(e.at for e in ep)
        assert (ep[-1].at - t0).total_seconds() <= MAX_SECS
        # one user, one device, one episode id, every txn labelled
        assert len({e.txn.user_id for e in ep}) == 1
        assert len({e.txn.device_id for e in ep}) == 1
        assert len({e.label.episode_id for e in ep}) == 1
        assert all(e.label is not None and e.label.pattern is FraudPattern.VELOCITY for e in ep)
        assert all(e.label.txn_id == e.txn.txn_id for e in ep)
        assert all(e.txn.ts == e.at for e in ep)


def test_burst_exceeds_stream_engine_1m_limit(users, traffic, rng, t0):
    """The engine's velocity.limit1m is 8; a burst must reliably cross it or the
    injector is not testing anything."""
    inj = VelocityInjector(users, traffic, rng)
    for _ in range(50):
        ep = inj.episode(t0)
        best = 0
        for i in range(len(ep)):
            j = i
            while j < len(ep) and (ep[j].at - ep[i].at).total_seconds() < 60:
                j += 1
            best = max(best, j - i)
        assert best > 8, f"max txns in any 60s window was {best}"
        assert MIN_SECS <= MAX_SECS
