"""VelocityInjector (LLD §7): pick a user, fire 15–40 transactions in 1–3 minutes."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from ..models import FraudPattern, Label, ScheduledTxn, Transaction
from .base import Injector

MIN_TXNS, MAX_TXNS = 15, 40
MIN_SECS, MAX_SECS = 60.0, 180.0
MIN_RATE_PER_MIN = 10.0  # > stream-engine velocity.limit1m (8)


class VelocityInjector(Injector):
    pattern = FraudPattern.VELOCITY

    @property
    def mean_episode_size(self) -> float:
        return (MIN_TXNS + MAX_TXNS) / 2

    def episode(self, start: datetime) -> list[ScheduledTxn]:
        user = self._rng.choice(self._users)
        n = self._rng.randint(MIN_TXNS, MAX_TXNS)
        # Cap the duration so the burst averages >= MIN_RATE_PER_MIN: a 15-txn
        # episode spread evenly over 3 minutes would never cross the engine's
        # velocity.limit1m (8) and would be an unlabelled false negative.
        duration = self._rng.uniform(MIN_SECS, min(MAX_SECS, n * 60.0 / MIN_RATE_PER_MIN))
        episode_id = f"ep_{uuid.uuid4().hex[:12]}"
        # A card-testing / account-takeover burst usually hits a small set of
        # merchants, not the user's usual favourites.
        merchants = self._rng.sample(_burst_merchants(), k=self._rng.randint(1, 3))

        # Evenly spaced with +/-20% jitter: bursty enough to look automated,
        # regular enough that every 60 s slice holds more than the limit.
        gap = duration / n
        offsets = sorted(i * gap + self._rng.uniform(-0.2 * gap, 0.2 * gap) for i in range(n))
        offsets[0] = max(0.0, offsets[0])
        out: list[ScheduledTxn] = []
        for off in offsets:
            at = start + timedelta(seconds=off)
            base = self._traffic.make_transaction(user, at)
            txn = Transaction(
                txn_id=base.txn_id,
                user_id=user.user_id,
                merchant_id=self._rng.choice(merchants),
                counterparty_id=None,
                # burst amounts are smaller and more uniform than the user's norm
                amount=round(self._rng.uniform(50.0, 500.0), 2),
                currency="INR",
                lat=base.lat,
                lon=base.lon,
                device_id=user.device_id,
                channel=base.channel if base.channel is not base.channel.P2P else base.channel.CARD,
                ts=at,
            )
            label = Label(txn_id=txn.txn_id, user_id=user.user_id, pattern=self.pattern, episode_id=episode_id, ts=at)
            out.append(ScheduledTxn(at=at, txn=txn, label=label))
        return out


def _burst_merchants() -> list[str]:
    return [f"m_{cat}_{i:04d}" for cat in ("ELEC", "GIFT", "CRYPTO") for i in range(50)]
