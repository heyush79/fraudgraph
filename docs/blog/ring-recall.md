# My fraud model caught 44% of laundering rings. In production it caught 7%.

I built [FraudGraph](https://github.com/heyush79/fraudgraph), a real-time payment fraud
pipeline: Kafka Streams decides ALLOW, REVIEW or BLOCK for every payment in milliseconds, an
XGBoost model scores the suspicious ones, and a language model writes an investigation of every
flagged case. A synthetic generator plants three kinds of fraud in ordinary traffic, and it
knows exactly which payments it planted, so every number below is measured against ground
truth.

This is the story of one number, ring recall, and the two different ways it lied to me.

## What a ring is

Money laundering often looks like this: account A sends ₹40,000 to B, B sends ₹38,500 to C,
C sends ₹37,000 to D, and D sends it back to A. Each account is a mule that keeps a small cut.
Each transfer, on its own, is an ordinary peer-to-peer payment. The pattern only exists in the
graph.

FraudGraph keeps a graph of recent transfers in memory, and when A pays B it runs a bounded
search: can B's money already reach A in five hops or fewer? If yes, this payment closed a
cycle, and the engine raises `RING_SUSPECT`.

## Lie #1: 99% recall

The first model I trained caught 99% of ring payments. It also ranked "is this payment part of
a cycle" as the *least* useful of its twelve features.

Those two facts cannot both be good news. The ring injector moved between ₹20,000 and ₹80,000
per hop, while ordinary transfers averaged a few hundred rupees. The model had learned "large
transfer", not "ring". When I changed the generator to draw ring amounts from each account's own
spending, so a ring looks like the accounts' normal behaviour scaled up a little:

| | before | after |
|---|---|---|
| PR-AUC | 0.973 | 0.873 |
| ring recall | 99% | 44% |
| rank of the cycle feature | 12th of 12 | 9th |

Worse numbers, and much more honest ones. The model finally had to use the graph.

## Lie #2: 44% recall

44% is offline recall: take a held-out slice of history, score every row with the model, count
how many ring payments cross the threshold.

But production doesn't score every row. The engine only calls the model when a rule-based check
has already fired (plus a 1% random sample). That's a sensible design: 99% of traffic is clean,
and there's no reason to pay a network round trip for it. It also means that **a payment which
fires no rule is never shown to the model at all**, so the model's offline recall on it is
irrelevant.

So I measured what the running system actually did: joined every verdict the engine emitted to
the generator's ground truth, over an hour of traffic, 117,000 decisions.

| pattern | production recall | model consulted |
|---|---|---|
| velocity | 62.6% | 62.9% |
| geo | 43.2% | 43.4% |
| ring | **7.2%** | 7.4% |

Look at the two columns. For every pattern, recall is within a point of how often the model was
even asked. **The model wasn't the bottleneck. The gate in front of it was.**

For rings, the reason is structural. Breaking recall down by where a payment sits in its ring
(94 complete rings):

| position | recall |
|---|---|
| first transfer | 0% |
| middle transfers | 0.7% |
| closing transfer | 39.4% |

A ring is only a ring once it closes. Cycle detection can only fire on the last hop, so every
earlier hop sails through unscored, and the closing hop's 39% is roughly the model's offline
recall on exactly the payments it gets to see.

## The fix: follow the money, not the cycle

A mule doesn't need a cycle to be suspicious. What a mule does is **receive money and pass most
of it on, quickly**. That's visible on the second hop, not the last.

So the engine now remembers each account's recent inbound transfers (a 60-minute window), and
when an account sends money onwards it asks: is this forwarding something that just arrived?

- the outgoing amount is 80% to 102% of an inbound one (a mule keeps a cut; sending on *more*
  than arrived isn't forwarding),
- it happened within the window,
- and it counts how many accounts in a row have done the same (`chainDepth`).

A match fires a new signal, `PASS_THROUGH`, which opens the gate to the model, and the same three
numbers (ratio, seconds since the money arrived, chain depth) become model features.

Here is a live five-account ring going through the upgraded engine, still with the *old* model
(which has never seen the new features):

| hop | signals | model score | verdict |
|---|---|---|---|
| 1, origin | none | not asked | ALLOW |
| 2 | PASS_THROUGH | 0.09 | ALLOW |
| 3 | PASS_THROUGH | 0.61 | REVIEW |
| 4 | PASS_THROUGH | 0.88 | REVIEW |
| 5, closing | RING_SUSPECT, PASS_THROUGH | 0.998 | BLOCK |

Before the fix, hops 2 to 4 would all have been ALLOW without the model ever being consulted.

## Results

Same measurement, same kind of window (one hour, joined to ground truth, complete rings only),
before and after the new gate. **The model did not change**: this is still the model trained
before the pass-through features existed.

| ring transfer | before (94 rings) | after (167 rings) |
|---|---|---|
| first | 0% | 3.6% |
| middle | 0.7% | **85.9%** |
| closing | 39.4% | 95.2% |
| **all ring transfers** | **7.2%** | **71.9%** |

Ten times the recall, from widening the gate alone. The closing hop improved too: it now
arrives with a PASS_THROUGH signal alongside the cycle, so it clears the review threshold far
more often.

The cost, measured the same way: PASS_THROUGH also fires on 1.57% of honest peer-to-peer
transfers (people do pass money on), and the old model, which has never seen the new features,
sent about half of those to review. Legitimate payments flagged went from 0.038% to 0.082% of
traffic, roughly one extra review per 2,750 honest payments, and the model is now consulted on
2.6% of traffic instead of 1.7%.

**Then the model.** The next model (v3) trained on 357,000 decisions logged after the change.
To separate what the new features are worth from what fresh data is worth, I trained it a
second time on exactly the same rows and the same time split, without the three features:

| | with the features | without |
|---|---|---|
| PR-AUC | **0.874** | 0.803 |
| ring recall at the review threshold (0.60) | 77.4% | 78.9% |
| honest payments flagged at 0.60 | **0.96%** | 2.60% |
| ring recall at the auto-block threshold (0.99) | **55.1%** | 25.9% |

These score every row offline, so they describe the model, not production. They say the features
barely change *which* ring transfers the model can find, and change a lot about how *sure* it
is: at the review threshold it finds the same rings while flagging 63% fewer honest payments,
and at the block threshold it blocks twice as many ring transfers. `chain_depth`, how many
accounts in a row have forwarded the money, became the model's second most important feature,
above every velocity count. The cycle feature I started with is fourteenth of fifteen.

**And in production.** v3 went live next to the new gate, measured exactly as before (73
minutes, 223,000 decisions, 161 complete rings):

| ring transfer | before | new gate, old model | new gate + v3 |
|---|---|---|---|
| first | 0% | 3.6% | 1.2% |
| middle | 0.7% | 85.9% | **99.7%** |
| closing | 39.4% | 95.2% | **100%** |
| **all ring transfers** | **7.2%** | **71.9%** | **84.5%** |

Every ring transfer after the first is now caught, and most are stopped outright: 1,062 of
1,354 ring transfers were blocked automatically rather than queued for a human, where the old
model blocked 239. What remains is the first hop, which no per-payment check can see.

The false-positive cost did *not* come down, though, and that is the most useful result of all.
Offline, the new features cut honest payments flagged by 63%. In production, about 46% of honest
transfers that trip the pass-through check are still flagged, the same as with the old model,
and 28 of them were blocked outright in 73 minutes. The offline number was counted over every
row; production only scores the gated ones, and among those, an honest person passing money on
to a friend looks exactly like a mule to every feature I have. Automatic blocks as a whole
still clear the 98% precision bar (98.7% of 2,673 were planted fraud), but legitimate payments
flagged rose from 0.038% to 0.085% of traffic, and that cost is real. The next lever is not the
model; it is evidence the model cannot see yet, like how long the two accounts have known each
other.

## What I'd tell another engineer

1. **Measure the system, not the model.** Offline recall answered "how good is the model on
   what it's shown". The question that mattered was "what does production catch", and only a
   join between live verdicts and ground truth answers it. It cut both ways here: production
   recall was far worse than offline before the fix, and the false-positive gain the offline
   ablation promised never showed up after it.
2. **Your gate is part of your model.** Any cheap filter in front of an expensive model sets
   a ceiling on recall that no amount of retraining can raise.
3. **Be suspicious of good numbers.** 99% recall with the key feature ranked last was a data
   bug, and I'd have shipped it if I'd only looked at the headline.
4. **Some limits are structural.** The first transfer of a ring looks exactly like any other
   payment until someone forwards it. No per-payment check can catch it; you'd need to flag it
   retroactively once the ring is known. Knowing that is better than a dashboard that implies
   otherwise.

---

*FraudGraph is open source: Java 17, Kafka Streams, Python, XGBoost, LangGraph. The public
console replays a recorded session of the real pipeline, including an analyst chat where every
sentence is checked against the evidence it cites.*
