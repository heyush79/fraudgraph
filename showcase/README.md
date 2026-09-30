# showcase

Records the public replay: a real session of the running pipeline, saved as the static JSON
that the console plays on GitHub Pages (`dashboard/public/showcase/`, format in
[`docs/showcase-contract.md`](../docs/showcase-contract.md)). Nothing in it is synthetic.

```bash
make demo                         # the full stack, with a model trained and a Groq key set
cd showcase
uv run python record.py           # ~4 min of traffic + reports and answers for the featured cases
```

What a recording does:

1. Subscribes to the live decision feed for `--duration` seconds (default 240) while four
   scenarios land in ordinary traffic: a velocity burst, a five-account ring, impossible travel
   and a sanctioned merchant (`generator.scenario`, the same as `make scenario-*`). Their labels
   are tagged as scenarios, so `make recall` leaves them out.
2. Saves every case that opened in the window, with its account's history and transfer graph.
3. Has the analyst write a report on the featured case of each pattern, then asks each one three
   suggested questions, 45 s apart. The free tier allows 8,000 tokens a minute; asked back to
   back, answers queue behind the provider's retries and the replay would show 40-second
   answers that say nothing about the system.
4. Writes everything to a temporary directory and swaps it in whole.

Other modes:

| | |
|---|---|
| `record.py --answers-only [--only RING,GEO]` | keep the recording, ask the featured cases' questions again (restart the agent first so its cache does not hand back the old answers) |
| `record.py --no-agent` | traffic and cases only, no model calls |
| `uv run --with playwright==1.62.0 --with pillow python hero_gif.py --out ../docs/media/console.gif` | the README's GIF, from the live console on the featured ring case |

Then commit `dashboard/public/showcase/`; the Pages workflow publishes it.
