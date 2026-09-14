# analyst-agent

LangGraph agent that investigates a flagged case and writes a report in which **every claim
cites the evidence that supports it**. A `verify` node then checks those citations
programmatically. That check is the point of the component: it is a hallucination guard
implemented as code rather than as an instruction the model may ignore.

```
triage -> investigate ⟲ (hard budget: 8 tool calls) -> similar_cases
       -> draft_report -> verify -> finalize
                            └─(violations, one retry)─> investigate
```

## What verify actually checks

1. Every `evidence_refs` index exists in the evidence the agent collected, and points at a
   tool call that succeeded. Citing evidence that is not there is the commonest fabrication.
2. Every number quoted in a claim appears in the payloads of the evidence that claim cites.
   A report saying "23 transactions in 60 seconds" when the evidence says 18 is rejected.

Rounding is allowed within one percent, and collection sizes count as evidence, so "five
accounts formed a cycle" is supported by a six-element cycle list whose ends are the same
account. Small integers below three are treated as ordinary English rather than quantities.

Two failures escalate the case as `UNCERTAIN` with the unsupported claims removed, which is
an honest answer rather than a confident wrong one.

## The agent cannot reach anything

Four tools, all thin HTTP clients to our own services or local vector search. No database
handle, no Kafka client, no access to the engine's state stores. That boundary is the answer
to "what stops the model doing something unexpected": it has nothing to reach.

| tool | source |
|---|---|
| `get_user_history` | case-service `/internal/users/{id}/history` |
| `get_window_counts` | engine read API, proxied |
| `get_graph_neighborhood` | engine read API, proxied |
| `find_similar_cases` | local Chroma over closed reports |

## Running it

```bash
export GROQ_API_KEY=...                 # free key from console.groq.com
uv run python -m agent.server           # :8000, or 8010 on the host under compose
curl localhost:8000/health
curl -X POST localhost:8000/investigate/sync -H 'content-type: application/json' \
  -d '{"caseId":"<a case id from /cases>"}'
```

The provider is one environment variable. `FRAUDGRAPH_LLM_PROVIDER` takes `groq`, `ollama`
or `gemini`; only `agent/llm.py` knows the difference.

Model ids get retired, and the available set differs per account: `llama-3.3-70b-versatile`
was already gone when this was first wired up. `/health` therefore checks the configured id
against what the account can actually use and reports the real list when it does not match,
rather than failing with a bare 404 mid-investigation.

## Evals

The generator knows which transactions it planted, so scoring needs no human labelling.

```bash
python -m evals.run --limit 30 --hours 6 --sleep 2
```

The headline metric is whether the agent made the **right call**, because that is the one
thing the engine does not hand it: triage shows which rules fired, so predicting the fraud
*type* from `GEO_IMPOSSIBLE` needs no reasoning at all. Cases are scored by kind:

| kind | right call | why |
|---|---|---|
| planted fraud | confirm | the generator injected it |
| policy breach (a hard rule fired) | confirm | a sanctioned merchant is a policy breach, not a pattern, so there is no ground-truth label and confirming is still correct |
| engine false positive | release or escalate | the only group where declining is right |

Fraud-type agreement is still reported, with a note saying not to trust it.

Results land in `evals/results/latest.md`. `python -m evals.rescore` re-reads a saved run
through the current scoring logic without spending a single token, which is how the first
run was corrected after the harness turned out to be scoring a quota as a quality problem.

### The free tier is the binding constraint

Groq allows **8,000 tokens per minute and 200,000 per day** on every model that supports tool
calling, which is roughly 25 cases a day. A run that exceeds it does not fail loudly: every
model call returns 429, the graph escalates those cases as UNCERTAIN exactly as designed, and
the numbers quietly become a measurement of the quota. The harness therefore detects starved
cases and excludes them from every quality metric rather than reporting them as mistakes.

Three design choices follow from that ceiling, and each is a trade worth knowing:

- the tool budget defaults to **4**, not the 8 the design document allows, because the
  conversation is resent every turn so cost grows quadratically in tool calls;
- the drafting step does **not** resend the investigation transcript, only the numbered
  evidence, which costs the model its own earlier reasoning;
- investigations run **one at a time**, since two competing for the same per-minute budget
  makes both slow instead of one fast.

Automatic hand-off from the case service is off by default for the same reason. With it on,
every new case triggers an investigation and several hundred of them stampede the limit.

## Tests

33 tests, no API key and no running stack required. The graph tests replay a scripted model,
so the retry path, the tool budget, the failed-tool path and the escalation are all
deterministic.

```bash
uv run --extra dev pytest -q
```
