"""Legitimate base traffic: Poisson arrivals over the user population."""
from __future__ import annotations

import random
import uuid
from datetime import datetime

from .models import Channel, Transaction
from .users import UserProfile

# ~0.02 degrees ≈ 2 km of GPS jitter around the home city.
HOME_JITTER_DEG = 0.02
# Share of legitimate traffic that is a P2P transfer (feeds the graph in Phase 2).
P2P_SHARE = 0.10


class BaseTraffic:
    def __init__(self, users: list[UserProfile], tps: float, rng: random.Random) -> None:
        if tps <= 0:
            raise ValueError("tps must be > 0")
        self._users = users
        self._tps = tps
        self._rng = rng

    def next_gap_seconds(self) -> float:
        """Inter-arrival time of a Poisson process with rate `tps`."""
        return self._rng.expovariate(self._tps)

    def pick_user(self, now: datetime) -> UserProfile:
        """Users inside their active hours are 5x as likely to be picked; it keeps
        the population realistic without ever starving anyone."""
        for _ in range(8):
            u = self._rng.choice(self._users)
            if u.active_start_hour <= now.hour < u.active_end_hour or self._rng.random() < 0.2:
                return u
        return self._rng.choice(self._users)

    def make_transaction(self, user: UserProfile, now: datetime) -> Transaction:
        if self._rng.random() < P2P_SHARE:
            counterparty = self._rng.choice(self._users)
            while counterparty.user_id == user.user_id:
                counterparty = self._rng.choice(self._users)
            return self.make_p2p(user, counterparty, self.sample_amount(user), now)
        return Transaction(
            txn_id=str(uuid.uuid4()),
            user_id=user.user_id,
            merchant_id=self._rng.choice(user.favourite_merchants),
            counterparty_id=None,
            amount=self.sample_amount(user),
            currency="INR",
            lat=user.home.lat + self._rng.uniform(-HOME_JITTER_DEG, HOME_JITTER_DEG),
            lon=user.home.lon + self._rng.uniform(-HOME_JITTER_DEG, HOME_JITTER_DEG),
            device_id=user.device_id,
            channel=self._rng.choice((Channel.CARD, Channel.UPI)),
            ts=now,
        )

    def make_p2p(self, user: UserProfile, counterparty: UserProfile, amount: float, now: datetime) -> Transaction:
        return Transaction(
            txn_id=str(uuid.uuid4()),
            user_id=user.user_id,
            merchant_id="m_P2P_0000",
            counterparty_id=counterparty.user_id,
            amount=amount,
            currency="INR",
            lat=user.home.lat + self._rng.uniform(-HOME_JITTER_DEG, HOME_JITTER_DEG),
            lon=user.home.lon + self._rng.uniform(-HOME_JITTER_DEG, HOME_JITTER_DEG),
            device_id=user.device_id,
            channel=Channel.P2P,
            ts=now,
        )

    def sample_amount(self, user: UserProfile) -> float:
        return max(1.0, self._rng.lognormvariate(user.amount_mu, user.amount_sigma))
