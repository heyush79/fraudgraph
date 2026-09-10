from __future__ import annotations

import random
from abc import ABC, abstractmethod
from datetime import datetime

from ..models import FraudPattern, ScheduledTxn
from ..traffic import BaseTraffic
from ..users import UserProfile


class Injector(ABC):
    """Produces one fraud *episode*: a list of scheduled transactions, each carrying
    its ground-truth label. Episodes are pure data — the runner decides when to
    publish them — which keeps injectors trivially unit-testable."""

    pattern: FraudPattern

    def __init__(self, users: list[UserProfile], traffic: BaseTraffic, rng: random.Random) -> None:
        self._users = users
        self._traffic = traffic
        self._rng = rng

    @abstractmethod
    def episode(self, start: datetime) -> list[ScheduledTxn]:
        """Return the episode's transactions, sorted by `at`, starting at `start`."""

    @property
    @abstractmethod
    def mean_episode_size(self) -> float:
        """Expected transactions per episode; the runner uses it to hit --fraud-rate."""
