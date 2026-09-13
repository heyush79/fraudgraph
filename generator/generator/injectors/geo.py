"""GeoInjector (LLD §7): same card, two cities > 1000 km apart, minutes apart.

One unlabelled transaction at home anchors the user's last known location, then
1–3 labelled transactions from a far city a few minutes later — the cloned-card
signature the engine's GeoCheck (> 900 km/h and > 100 km) is built to catch."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from ..models import FraudPattern, Label, ScheduledTxn, Transaction
from ..users import far_cities
from .base import Injector

MIN_FAR_KM = 1000.0
MIN_GAP_MIN, MAX_GAP_MIN = 2.0, 10.0
MIN_FAR_TXNS, MAX_FAR_TXNS = 1, 3
FAR_JITTER_DEG = 0.02


class GeoInjector(Injector):
    pattern = FraudPattern.GEO

    @property
    def mean_episode_size(self) -> float:
        return (MIN_FAR_TXNS + MAX_FAR_TXNS) / 2  # labelled txns only

    def episode(self, start: datetime) -> list[ScheduledTxn]:
        user = self._rng.choice(self._users)
        candidates = far_cities(user.home, MIN_FAR_KM)
        if not candidates:  # every city in the table is within 1000 km of this home
            return []
        far = self._rng.choice(candidates)
        episode_id = f"ep_{uuid.uuid4().hex[:12]}"

        anchor = self._traffic.make_transaction(user, start)
        if anchor.counterparty_id is not None:  # keep the anchor a plain card txn at home
            anchor = self._traffic.make_transaction(user, start)
        out = [ScheduledTxn(at=start, txn=anchor)]

        # a cloned card shows up as a different terminal/device far away
        cloned_device = f"d_{self._rng.getrandbits(32):08x}"
        first_far = start + timedelta(minutes=self._rng.uniform(MIN_GAP_MIN, MAX_GAP_MIN))
        n_far = self._rng.randint(MIN_FAR_TXNS, MAX_FAR_TXNS)
        at = first_far
        for _ in range(n_far):
            txn = Transaction(
                txn_id=str(uuid.uuid4()),
                user_id=user.user_id,
                merchant_id=self._rng.choice(_cashout_merchants()),
                counterparty_id=None,
                amount=round(self._rng.uniform(2000.0, 20000.0), 2),
                currency="INR",
                lat=far.lat + self._rng.uniform(-FAR_JITTER_DEG, FAR_JITTER_DEG),
                lon=far.lon + self._rng.uniform(-FAR_JITTER_DEG, FAR_JITTER_DEG),
                device_id=cloned_device,
                channel=anchor.channel,
                ts=at,
            )
            out.append(ScheduledTxn(at=at, txn=txn, label=Label(txn.txn_id, user.user_id, self.pattern, episode_id, at)))
            at += timedelta(seconds=self._rng.uniform(20.0, 90.0))
        return out


def _cashout_merchants() -> list[str]:
    return [f"m_{cat}_{i:04d}" for cat in ("ELEC", "GIFT") for i in range(50)]
