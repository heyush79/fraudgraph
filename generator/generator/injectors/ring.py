"""RingInjector (LLD §7): 4–8 accounts pass money around a cycle A→B→C→A over
10–30 minutes. Every hop is a P2P transfer, so the engine sees edges A→B, B→C, …
and the closing hop back to A completes a cycle for the bounded DFS to find.
Amounts shrink a little at each hop (the mule keeps a cut)."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from ..models import FraudPattern, Label, ScheduledTxn
from .base import Injector

MIN_ACCOUNTS, MAX_ACCOUNTS = 4, 8
MIN_MINUTES, MAX_MINUTES = 10.0, 30.0
MIN_KEEP, MAX_KEEP = 0.90, 0.98   # fraction passed on at each hop

# A ring moves a sum that is large *for the accounts involved*, not a flat band.
# The original 20k-80k band made rings separable by amount alone: legitimate P2P averages a
# few hundred rupees, so the v1 model learned "unusually large P2P transfer" and never needed
# the graph at all (`in_cycle` ranked last of twelve features by gain). Drawing from the
# source account's own log-normal and scaling it keeps the transfer plausible for that
# account while still unusual for it, which is what forces the model to use the cycle.
MIN_MULTIPLIER, MAX_MULTIPLIER = 2.0, 6.0


class RingInjector(Injector):
    pattern = FraudPattern.RING

    @property
    def mean_episode_size(self) -> float:
        return (MIN_ACCOUNTS + MAX_ACCOUNTS) / 2

    def episode(self, start: datetime) -> list[ScheduledTxn]:
        k = self._rng.randint(MIN_ACCOUNTS, MAX_ACCOUNTS)
        ring = self._rng.sample(self._users, k)
        duration = self._rng.uniform(MIN_MINUTES, MAX_MINUTES) * 60.0
        episode_id = f"ep_{uuid.uuid4().hex[:12]}"

        # k hops spread over the duration, order preserved, mild jitter
        gap = duration / k
        offsets = [i * gap + self._rng.uniform(0.0, 0.5 * gap) for i in range(k)]
        amount = self._traffic.sample_amount(ring[0]) * self._rng.uniform(MIN_MULTIPLIER, MAX_MULTIPLIER)
        out: list[ScheduledTxn] = []
        for i, off in enumerate(offsets):
            src = ring[i]
            dst = ring[(i + 1) % k]
            at = start + timedelta(seconds=off)
            txn = self._traffic.make_p2p(src, dst.user_id, round(amount, 2), at)
            out.append(ScheduledTxn(at=at, txn=txn, label=Label(txn.txn_id, src.user_id, self.pattern, episode_id, at)))
            amount *= self._rng.uniform(MIN_KEEP, MAX_KEEP)
        return out
