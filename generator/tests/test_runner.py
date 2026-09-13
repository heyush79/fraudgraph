from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from generator.publisher import InMemoryPublisher
from generator.runner import Clock, Runner, RunnerConfig


class FakeClock(Clock):
    def __init__(self, start: datetime) -> None:
        self._now = start

    def now(self) -> datetime:
        return self._now

    def sleep_until(self, when: datetime) -> None:
        if when > self._now:
            self._now = when


def _run(**overrides):
    cfg = RunnerConfig(tps=100.0, fraud_rate=0.05, patterns=("velocity",), n_users=100, seed=3, max_events=20_000)
    cfg = replace(cfg, **overrides)
    pub = InMemoryPublisher()
    runner = Runner(cfg, pub, clock=FakeClock(datetime(2026, 9, 4, tzinfo=timezone.utc)))
    return runner.run(), pub


def test_events_are_published_in_time_order_and_labelled():
    stats, pub = _run()
    assert stats.published == 20_000 == len(pub.txns)
    ts = [t.ts for t in pub.txns]
    assert ts == sorted(ts)
    assert len(pub.labels) == stats.fraud_published > 0
    label_ids = {l.txn_id for l in pub.labels}
    assert label_ids <= {t.txn_id for t in pub.txns}
    assert len({t.txn_id for t in pub.txns}) == len(pub.txns)


def test_fraud_rate_is_roughly_honoured():
    stats, _ = _run(max_events=50_000)
    rate = stats.fraud_published / stats.published
    assert 0.03 <= rate <= 0.07, rate


def test_all_three_patterns_inject_and_label():
    # ring episodes take 10–30 min to play out, so run ~50 min of fake time
    stats, pub = _run(patterns=("velocity", "ring", "geo"), max_events=300_000)
    assert set(stats.per_pattern) == {"VELOCITY", "RING", "GEO"}
    assert all(n > 0 for n in stats.per_pattern.values())
    assert 0.035 <= stats.fraud_published / stats.published <= 0.065


def test_zero_fraud_rate_publishes_no_labels():
    stats, pub = _run(fraud_rate=0.0, max_events=2_000)
    assert stats.fraud_published == 0 and pub.labels == []


def test_duration_stops_the_run():
    stats, pub = _run(duration_secs=30.0, max_events=None)
    assert pub.txns[-1].ts - pub.txns[0].ts <= timedelta(seconds=31)
    assert 2_000 <= stats.published <= 4_000  # 100 tps * 30 s ± Poisson noise


def test_unknown_pattern_is_rejected():
    with pytest.raises(ValueError, match="mule"):
        Runner(RunnerConfig(patterns=("mule",), n_users=10), InMemoryPublisher())


class SleepingClock(FakeClock):
    """Jumps forward one hour on the 500th sleep, like a laptop lid closing."""

    def __init__(self, start: datetime) -> None:
        super().__init__(start)
        self.sleeps = 0

    def sleep_until(self, when: datetime) -> None:
        self.sleeps += 1
        if self.sleeps == 500:
            self._now += timedelta(hours=1)
        super().sleep_until(when)


def test_host_sleep_skips_ahead_instead_of_backfilling():
    cfg = RunnerConfig(tps=100.0, fraud_rate=0.05, patterns=("velocity", "ring", "geo"), n_users=100, seed=5, max_events=5_000)
    pub = InMemoryPublisher()
    clock = SleepingClock(datetime(2026, 9, 4, tzinfo=timezone.utc))
    runner = Runner(cfg, pub, clock=clock)

    seen_at: list[datetime] = []
    original = runner._publish

    def spy(ev):
        seen_at.append(clock.now())
        original(ev)

    runner._publish = spy  # type: ignore[method-assign]
    stats = runner.run()

    assert stats.clock_jumps == 1
    # no published event is ever more than a few seconds older than the clock that published it
    staleness = [(at - t.ts).total_seconds() for at, t in zip(seen_at, pub.txns)]
    assert max(staleness) < 6.0, max(staleness)
    # timestamps remain monotonic and the hour-long gap is a real hole, not a burst
    ts = [t.ts for t in pub.txns]
    assert ts == sorted(ts)
    gaps = [(b - a).total_seconds() for a, b in zip(ts, ts[1:])]
    assert max(gaps) > 3500
    assert sum(1 for g in gaps if g > 60) == 1
