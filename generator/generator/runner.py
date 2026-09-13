"""The event loop: merges Poisson base traffic with stochastically scheduled
fraud episodes and publishes everything in timestamp order.

Fraud-rate accounting: --fraud-rate is the fraction of *transactions* that are
fraud. With tps legitimate arrivals and episodes of mean size E, spawning
episodes at rate (fraud_rate * tps / E) per second gives that fraction."""
from __future__ import annotations

import heapq
import logging
import random
import time
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone

from .injectors import REGISTRY, Injector
from .models import ScheduledTxn
from .publisher import Publisher
from .traffic import BaseTraffic
from .users import DEFAULT_USERS, UserProfile, build_population

log = logging.getLogger(__name__)

# If the schedule falls this far behind the wall clock the host slept (or we can't keep
# up): jump forward instead of replaying the gap. A real payment stream never backfills,
# and replayed events carry stale timestamps that make end-to-end latency meaningless.
MAX_BEHIND_SECS = 5.0


@dataclass(frozen=True, slots=True)
class RunnerConfig:
    tps: float = 50.0
    fraud_rate: float = 0.02
    patterns: tuple[str, ...] = ("velocity",)
    n_users: int = DEFAULT_USERS
    seed: int | None = None
    duration_secs: float | None = None  # None = run until interrupted
    max_events: int | None = None       # mostly for tests


@dataclass
class RunnerStats:
    published: int = 0
    fraud_published: int = 0
    episodes: int = 0
    clock_jumps: int = 0
    per_pattern: dict[str, int] = field(default_factory=dict)


class Clock:
    """Wall clock, swappable in tests. `sleep_until` returns immediately in the fake."""

    def now(self) -> datetime:
        return datetime.now(timezone.utc)

    def sleep_until(self, when: datetime) -> None:
        delay = (when - self.now()).total_seconds()
        if delay > 0:
            time.sleep(delay)


class Runner:
    def __init__(self, cfg: RunnerConfig, publisher: Publisher, clock: Clock | None = None) -> None:
        if not 0.0 <= cfg.fraud_rate < 1.0:
            raise ValueError("fraud-rate must be in [0, 1)")
        unknown = [p for p in cfg.patterns if p not in REGISTRY]
        if unknown:
            raise ValueError(f"unknown/unimplemented patterns {unknown}; available: {sorted(REGISTRY)}")

        self.cfg = cfg
        self.publisher = publisher
        self.clock = clock or Clock()
        self.stats = RunnerStats()
        self._rng = random.Random(cfg.seed)
        self.users: list[UserProfile] = build_population(cfg.n_users, seed=cfg.seed if cfg.seed is not None else 42)
        self.traffic = BaseTraffic(self.users, cfg.tps, self._rng)
        # fraud-rate 0 (benchmark mode) means no injectors at all, whatever --patterns says
        active = cfg.patterns if cfg.fraud_rate > 0.0 else ()
        self.injectors: list[Injector] = [REGISTRY[p](self.users, self.traffic, self._rng) for p in active]
        self._queue: list[ScheduledTxn] = []
        self._stop = False

    # -- episode scheduling ---------------------------------------------------

    def _episode_gap_seconds(self, inj: Injector) -> float:
        legit_tps = self.cfg.tps
        fraud_tps = legit_tps * self.cfg.fraud_rate / (1.0 - self.cfg.fraud_rate)
        rate = fraud_tps / inj.mean_episode_size / len(self.injectors)
        return self._rng.expovariate(rate)

    def _schedule_episode(self, inj: Injector, start: datetime) -> None:
        for ev in inj.episode(start):
            heapq.heappush(self._queue, ev)
        self.stats.episodes += 1

    # -- main loop --------------------------------------------------------------

    def stop(self) -> None:
        self._stop = True

    def run(self) -> RunnerStats:
        start = self.clock.now()
        deadline = start + timedelta(seconds=self.cfg.duration_secs) if self.cfg.duration_secs else None
        next_base = start
        next_episode: dict[int, datetime] = {
            i: start + timedelta(seconds=self._episode_gap_seconds(inj)) for i, inj in enumerate(self.injectors)
        }
        log.info(
            "generator started tps=%.1f fraud_rate=%.3f patterns=%s users=%d",
            self.cfg.tps, self.cfg.fraud_rate, list(self.cfg.patterns), len(self.users),
        )
        last_report = start
        try:
            while not self._stop:
                if deadline and self.clock.now() >= deadline:
                    break
                if self._limit_reached():
                    break

                now = self.clock.now()
                if (now - next_base).total_seconds() > MAX_BEHIND_SECS:
                    behind = now - next_base
                    self._skip_ahead(behind)
                    next_base += behind
                    next_episode = {i: t + behind for i, t in next_episode.items()}

                # spawn any due episodes (they push future events onto the heap)
                for i, inj in enumerate(self.injectors):
                    while next_episode[i] <= next_base:
                        self._schedule_episode(inj, next_episode[i])
                        next_episode[i] += timedelta(seconds=self._episode_gap_seconds(inj))

                # publish injected events that are due before the next base arrival
                resync = False
                while self._queue and self._queue[0].at <= next_base and not self._limit_reached():
                    ev = heapq.heappop(self._queue)
                    self.clock.sleep_until(ev.at)
                    if self._behind(ev.at):          # the host slept during that sleep
                        heapq.heappush(self._queue, ev)
                        resync = True
                        break
                    self._publish(ev)
                if resync or self._limit_reached():
                    continue  # loop head resyncs the schedule / breaks

                self.clock.sleep_until(next_base)
                if self._behind(next_base):
                    continue
                user = self.traffic.pick_user(next_base)
                self._publish(ScheduledTxn(at=next_base, txn=self.traffic.make_transaction(user, next_base)))
                next_base += timedelta(seconds=self.traffic.next_gap_seconds())

                now = self.clock.now()
                if (now - last_report).total_seconds() >= 10:
                    log.info("published=%d fraud=%d episodes=%d", self.stats.published, self.stats.fraud_published, self.stats.episodes)
                    last_report = now
        finally:
            self.publisher.close()
            log.info("generator stopped: %s", self.stats)
        return self.stats

    def _behind(self, scheduled: datetime) -> bool:
        return (self.clock.now() - scheduled).total_seconds() > MAX_BEHIND_SECS

    def _skip_ahead(self, behind: timedelta) -> None:
        """Shift every queued episode event forward by `behind` so episodes stay intact
        (a ring still closes; its hops just happen after the gap, not during it)."""
        self.stats.clock_jumps += 1
        log.warning("schedule is %.0fs behind the wall clock (host slept?); skipping ahead, not backfilling", behind.total_seconds())
        shifted = []
        for ev in self._queue:
            txn = replace(ev.txn, ts=ev.txn.ts + behind)
            label = replace(ev.label, ts=ev.label.ts + behind) if ev.label else None
            shifted.append(ScheduledTxn(at=ev.at + behind, txn=txn, label=label))
        heapq.heapify(shifted)
        self._queue = shifted

    def _limit_reached(self) -> bool:
        return bool(self.cfg.max_events) and self.stats.published >= self.cfg.max_events

    def _publish(self, ev: ScheduledTxn) -> None:
        self.publisher.publish_txn(ev.txn)
        self.stats.published += 1
        if ev.label is not None:
            self.publisher.publish_label(ev.label)
            self.stats.fraud_published += 1
            self.stats.per_pattern[ev.label.pattern.value] = self.stats.per_pattern.get(ev.label.pattern.value, 0) + 1
