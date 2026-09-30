"""Records a real FraudGraph session into the static replay the public console plays.

    uv run python record.py                       # 4 minutes, scenarios, reports and answers
    uv run python record.py --duration 60 --no-agent

Nothing in the replay is synthetic. The recorder subscribes to the case service's live
WebSocket feed while the scenarios it triggers (generator.scenario) land in ordinary traffic,
then saves the cases that opened, the evidence behind them, an analyst report for each
featured case and the verified answers to its suggested questions, all fetched from the
running services. The console replays the ticks at their original timing.

The format is docs/showcase-contract.md §3. Needs the full stack (`make demo`) with the
analyst agent's ask endpoint, and a model key for the agent unless --no-agent.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
import os
import pathlib
import re
import shutil
import sys
import tempfile
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import websockets

log = logging.getLogger("record")

REPO = pathlib.Path(__file__).resolve().parent.parent

# (seconds after the start, scenario, extra arguments). Spaced so that each lands on its own
# and every one has finished well inside the default four minutes: the ring closes about 85 s
# in, the geo episode's second far payment lands by about 220 s.
SCHEDULE: tuple[tuple[int, str, tuple[str, ...]], ...] = (
    (10, "velocity", ()),
    (20, "ring", ("--accounts", "5", "--gap-secs", "12")),
    (40, "geo", ()),
    (150, "policy", ()),
)

ALWAYS_ASK = ("Why was this transaction flagged?",
              "Is this normal behaviour for this account?",
              "What evidence would change the verdict?")
RULE_QUESTIONS = (
    (("VELOCITY_1M", "VELOCITY_5M", "VELOCITY_1H"), "Could this be a genuine shopping spree?"),
    (("GEO_IMPOSSIBLE",), "Could this be a real trip?"),
    (("RING_SUSPECT", "PASS_THROUGH"), "Where did the money come from, and where did it go?"),
    (("HARD_BLOCK_MERCHANT",), "Why is this merchant blocked outright?"),
)
PATTERN_FOR_RULE = (("RING_SUSPECT", "RING"), ("PASS_THROUGH", "RING"), ("GEO_IMPOSSIBLE", "GEO"),
                    ("VELOCITY_1M", "VELOCITY"), ("HARD_BLOCK_MERCHANT", "POLICY"))
FEATURED_ORDER = ("RING", "GEO", "VELOCITY", "POLICY")


# ---- pure helpers (tested) ------------------------------------------------------------------

_FRACTION = re.compile(r"(\.\d{1,9})")


def parse_instant(value: str) -> datetime:
    """Java Instants carry nanoseconds; Python stops at microseconds."""
    text = value.replace("Z", "+00:00")
    text = _FRACTION.sub(lambda m: m.group(1)[:7], text, count=1)
    return datetime.fromisoformat(text)


def iso_ms(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def ticks_to_feed(ticks: list[dict[str, Any]], start: datetime, end: datetime) -> list[dict[str, Any]]:
    """Ticks decided inside [start, end), each stamped with `at` = ms since start, in order.
    The WebSocket backfill on connect carries older ticks; they are not part of the recording."""
    out = []
    seen: set[str] = set()
    for t in ticks:
        try:
            decided = parse_instant(t["decidedAt"])
        except (KeyError, TypeError, ValueError):
            continue
        if not start <= decided < end or t.get("txnId") in seen:
            continue
        seen.add(t.get("txnId"))
        tick = dict(t)
        tick["decidedAt"] = iso_ms(decided)
        if isinstance(tick.get("mlScore"), float):
            tick["mlScore"] = round(tick["mlScore"], 4)
        tick["at"] = int((decided - start).total_seconds() * 1000)
        out.append(tick)
    out.sort(key=lambda t: (t["at"], t["txnId"]))
    return out


def suggested_questions(fired_rules: list[str], limit: int | None = None) -> list[str]:
    """The contract's suggested questions in the order the replay offers them: why it was
    flagged, then the question specific to the pattern (the most revealing one), then what
    would change the verdict, then whether this is normal for the account."""
    why, normal, change = ALWAYS_ASK
    specific = [q for rules, q in RULE_QUESTIONS if any(r in rules for r in fired_rules)]
    questions = [why, *specific, change, normal]
    return questions[:limit] if limit else questions


def pattern_of(fired_rules: list[str]) -> str | None:
    for rule, pattern in PATTERN_FOR_RULE:
        if rule in fired_rules:
            return pattern
    return None


def signal(decision: dict[str, Any], code: str) -> dict[str, Any]:
    for s in decision.get("signals") or []:
        if s.get("code") == code:
            return s.get("evidence") or {}
    return {}


def nearest_city(lat: float, lon: float, cities: list[tuple[str, float, float]]) -> str | None:
    best, best_d = None, math.inf
    for name, clat, clon in cities:
        d = (lat - clat) ** 2 + (lon - clon) ** 2
        if d < best_d:
            best, best_d = name, d
    return best if best_d < 1.0 else None      # within about a degree, or say nothing


def describe(pattern: str, decision: dict[str, Any], scenario: dict[str, Any] | None,
             feed: list[dict[str, Any]], cities: list[tuple[str, float, float]]) -> tuple[str, str]:
    """A title and a one-line blurb for a featured case, written only from recorded data."""
    score = decision.get("mlScore")
    scored = f" The model scored it {score:.4f}." if isinstance(score, (int, float)) else ""
    if pattern == "RING":
        ring = signal(decision, "RING_SUSPECT")
        cycle = [str(u) for u in ring.get("cycle") or []]
        n = len(set(cycle)) or len((scenario or {}).get("users") or [])
        title = f"A {n}-account laundering ring" if n else "A laundering ring"
        parts = []
        if cycle:
            parts.append("Money went " + " → ".join(cycle))
        if scenario:
            mins = (parse_instant(scenario["endedAt"]) - parse_instant(scenario["startedAt"])).total_seconds() / 60
            parts[-1:] = [f"{parts[-1]} in {mins:.0f} minute{'s' if round(mins) != 1 else ''}"] if parts else []
            by_txn = {t["txnId"]: t for t in feed}
            hops = [by_txn.get(txn) for txn in scenario.get("labelledTxnIds") or []]
            flagged = [i for i, t in enumerate(hops) if t and t.get("verdict") in ("REVIEW", "BLOCK")]
            if hops and flagged:
                first = flagged[0] + 1
                parts.append(f"The engine flagged {len(flagged)} of {len(hops)} transfers, from transfer {first} on"
                             + (", before the ring closed" if first < len(hops) else ""))
        blurb = ". ".join(parts) + "." if parts else "The closing transfer completed a payment cycle."
        return title, blurb
    if pattern == "GEO":
        ev = signal(decision, "GEO_IMPOSSIBLE")
        dist, gap, speed = ev.get("distanceKm"), ev.get("gapSecs"), ev.get("speedKmh")
        a = nearest_city(ev.get("fromLat", 0.0), ev.get("fromLon", 0.0), cities) if ev else None
        b = nearest_city(ev.get("toLat", 0.0), ev.get("toLon", 0.0), cities) if ev else None
        span = (_duration(gap) if gap else "minutes")
        title = f"{a}, then {b}, {span} later" if a and b else f"{dist:,.0f} km in {span}" if dist else "Impossible travel"
        where = f" in {b}" if b else ""
        blurb = (f"The same card paid again {span} later, {dist:,.0f} km away{where}: {speed:,.0f} km/h.{scored}"
                 if dist and gap and speed else f"The same card appeared in two places at once.{scored}")
        return title, blurb
    if pattern == "VELOCITY":
        ev = signal(decision, "VELOCITY_1M")
        count, limit = ev.get("count"), ev.get("limit")
        title = f"{count} payments in a minute" if count else "A burst of payments"
        blurb = (f"The one-minute limit is {limit}; this account hit {count}.{scored}" if count and limit
                 else f"More payments in a minute than the limit allows.{scored}")
        return title, blurb
    ev = signal(decision, "HARD_BLOCK_MERCHANT")
    merchant = ev.get("merchantId") or decision.get("merchantId") or "the merchant"
    return ("A payment to a sanctioned merchant",
            f"{merchant} is on the sanctions list, so the engine blocks it outright, whatever the model thinks.")


def _duration(secs: float) -> str:
    if secs < 120:
        return f"{secs:.0f} seconds"
    mins = round(secs / 60)
    return f"{mins} minute{'s' if mins != 1 else ''}"


def pick_featured(window_cases: list[dict[str, Any]], scenarios: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """pattern -> {"caseId", "scenario"}. A scenario's own cases first; otherwise the newest
    case whose fired rules show the pattern, so a recording without scenarios still has some."""
    by_txn = {c["txnId"]: c for c in window_cases}
    chosen: dict[str, dict[str, Any]] = {}
    kinds = {"ring": "RING", "geo": "GEO", "velocity": "VELOCITY", "policy": "POLICY"}
    for sc in scenarios:
        pattern = kinds.get(sc.get("scenario", ""))
        if not pattern or pattern in chosen:
            continue
        txns = sc.get("labelledTxnIds") or sc.get("txnIds") or []
        cases = [by_txn[t] for t in txns if t in by_txn]
        if not cases:
            continue
        if pattern == "RING":
            pick = cases[-1]                                   # the closing hop when it has a case
        elif pattern == "VELOCITY":
            pick = cases[min(len(cases) - 1, 10)]              # far enough into the burst to be vivid
        else:
            pick = cases[0]
        chosen[pattern] = {"caseId": pick["caseId"], "scenario": sc}
    for c in window_cases:                                     # newest first
        pattern = pattern_of(c.get("firedRules") or [])
        if pattern and pattern not in chosen:
            chosen[pattern] = {"caseId": c["caseId"], "scenario": None}
    return {p: chosen[p] for p in FEATURED_ORDER if p in chosen}


def window_stats(window_cases: list[dict[str, Any]]) -> dict[str, Any]:
    """Stats for the recording itself, in the shape GET /stats returns."""
    by_status = Counter(c.get("status", "OPEN") for c in window_cases)
    verdicts = Counter(c.get("verdict") for c in window_cases)
    return {"byStatus": dict(by_status), "total": len(window_cases),
            "last1h": {"cases": len(window_cases), "review": verdicts.get("REVIEW", 0),
                       "block": verdicts.get("BLOCK", 0)}}


def load_cities() -> list[tuple[str, float, float]]:
    """The generator's city table, for naming coordinates in a blurb. Optional."""
    try:
        sys.path.insert(0, str(REPO / "generator"))
        from generator.users import CITIES  # type: ignore[import-not-found]
        return [(c.name, c.lat, c.lon) for c in CITIES]
    except Exception:  # noqa: BLE001 - blurbs fall back to distances
        return []
    finally:
        sys.path.pop(0)


# ---- the session ----------------------------------------------------------------------------

@dataclass
class Session:
    case_url: str
    agent_url: str
    scorer_url: str
    duration: float
    scenarios: bool
    agent: bool
    questions: int | None
    max_cases: int
    compose_dir: pathlib.Path
    ticks: list[dict[str, Any]] = field(default_factory=list)
    scenario_results: list[dict[str, Any]] = field(default_factory=list)

    @property
    def ws_url(self) -> str:
        return re.sub(r"^http", "ws", self.case_url.rstrip("/")) + "/ws/feed"

    async def _feed(self, end_monotonic: float) -> None:
        async with websockets.connect(self.ws_url, max_size=None, open_timeout=10) as ws:
            while (remaining := end_monotonic - time.monotonic()) > 0:
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=remaining)
                except asyncio.TimeoutError:
                    break
                batch = json.loads(msg)
                self.ticks.extend(batch if isinstance(batch, list) else [batch])

    async def _scenario(self, offset: float, kind: str, extra: tuple[str, ...]) -> None:
        await asyncio.sleep(offset)
        log.info("scenario %s starting", kind)
        # A one-off container from the generator image, as `make scenario-*` runs it.
        proc = await asyncio.create_subprocess_exec(
            "docker", "compose", "--profile", "demo", "run", "--rm", "--no-deps", "-T", "--entrypoint", "python",
            "generator", "-m", "generator.scenario", kind, *extra,
            cwd=self.compose_dir, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        out, err = await proc.communicate()
        if proc.returncode != 0:
            log.warning("scenario %s failed: %s", kind, err.decode()[-400:])
            return
        try:
            self.scenario_results.append(json.loads(out.decode().strip().splitlines()[-1]))
            log.info("scenario %s done", kind)
        except (IndexError, json.JSONDecodeError):
            log.warning("scenario %s printed no summary", kind)

    async def record(self) -> tuple[datetime, datetime]:
        start = datetime.now(timezone.utc)
        end_mono = time.monotonic() + self.duration
        tasks = [asyncio.create_task(self._feed(end_mono))]
        if self.scenarios:
            tasks += [asyncio.create_task(self._scenario(o, k, e)) for o, k, e in SCHEDULE if o < self.duration]
        log.info("recording %.0f s of live traffic from %s", self.duration, self.ws_url)
        await asyncio.gather(*tasks)
        return start, start + timedelta(seconds=self.duration)


def _get(client: httpx.Client, url: str, **kw) -> Any:
    r = client.get(url, **kw)
    r.raise_for_status()
    return r.json()


def cases_in_window(client: httpx.Client, case_url: str, start: datetime, limit: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    offset = 0
    while len(out) < limit:
        page = _get(client, f"{case_url}/cases", params={"limit": 200, "offset": offset})
        items = page.get("items") or []
        for c in items:
            if parse_instant(c["createdAt"]) < start:
                return out
            out.append(c)
        size = page.get("limit") or 200          # the server may cap the page below what was asked
        if len(items) < size:
            break
        offset += len(items)
    return out[:limit]


# Seconds between questions. The free tier allows 8,000 tokens a minute and one answer costs
# 3,000 to 6,000, so back-to-back questions queue behind the provider's retries and a replay
# would show 40-second answers that say nothing about the system. Spaced out, they take ~2 s.
ASK_PACE_S = 45.0


def ask_all(client: httpx.Client, agent_url: str, case_id: str, questions: list[str],
            pace_s: float = ASK_PACE_S) -> list[dict[str, Any]]:
    answers = []
    for i, q in enumerate(questions):
        if i:
            time.sleep(pace_s)
        for attempt in range(3):
            r = client.post(f"{agent_url}/cases/{case_id}/ask", json={"question": q}, timeout=180)
            if r.status_code == 429 and attempt < 2:
                wait = int(r.headers.get("Retry-After", "20"))
                log.info("rate limited; waiting %d s", wait)
                time.sleep(wait)
                continue
            if r.status_code != 200:
                log.warning("ask %r on %s: HTTP %d %s", q, case_id, r.status_code, r.text[:200])
            else:
                answer = r.json()
                answer["mode"] = "replay"
                answer.pop("cached", None)
                answers.append(answer)
                log.info("  %-55s %d sentence(s), %d removed, %d ms", q[:55], len(answer["answer"]),
                         len(answer["removed"]), answer["latencyMs"])
            break
    return answers


def reanswer(out_dir: pathlib.Path, agent_url: str, questions: int | None, pace_s: float,
             only: set[str] | None = None) -> None:
    """Asks the featured cases' questions again and rewrites only their answer files: for when
    the recorded answers were throttled, or the analyst changed, and the traffic is still fine.
    Restart the agent first so its answer cache does not hand back the old answers."""
    manifest = json.loads((out_dir / "manifest.json").read_text())
    with httpx.Client(timeout=30) as client:
        chosen = [f for f in manifest["featured"] if not only or f["pattern"] in only]
        for n, f in enumerate(chosen):
            if n:
                time.sleep(pace_s)
            case = json.loads((out_dir / "cases" / f"{f['caseId']}.json").read_text())
            path = out_dir / "ask" / f"{f['caseId']}.json"
            old = {a["question"]: a for a in json.loads(path.read_text()).get("answers", [])} if path.exists() else {}
            log.info("asking about %s case %s", f["pattern"], f["caseId"][:8])
            wanted = suggested_questions(case.get("firedRules") or [], questions)
            fresh = {a["question"]: a for a in ask_all(client, agent_url, f["caseId"], wanted, pace_s)}
            # a question the provider refused this time keeps the answer it already had
            kept = [fresh.get(q) or old.get(q) for q in wanted]
            path.write_text(json.dumps({"answers": [a for a in kept if a]}, separators=(",", ":"), ensure_ascii=False))
            log.info("  %d new, %d kept from before", len(fresh), sum(1 for q in wanted if q not in fresh and q in old))


def collect(s: Session, start: datetime, end: datetime, out_dir: pathlib.Path) -> dict[str, Any]:
    feed = ticks_to_feed(s.ticks, start, end)
    if not feed:
        raise SystemExit("recorded no ticks: is the generator running and the case service reachable?")
    with httpx.Client(timeout=30) as client:
        window = cases_in_window(client, s.case_url, start, s.max_cases)
        window = [c for c in window if parse_instant(c["createdAt"]) < end + timedelta(seconds=30)]
        featured = pick_featured(window, s.scenario_results)
        log.info("%d ticks, %d cases; featured: %s", len(feed), len(window),
                 ", ".join(f"{p} {v['caseId'][:8]}" for p, v in featured.items()) or "none")

        agent_model = None
        if s.agent:
            health = _get(client, f"{s.agent_url}/health")
            agent_model = f"{health.get('model')} via {health.get('provider', '?').capitalize()}"
            for pattern, f in featured.items():
                log.info("analyst report for %s case %s", pattern, f["caseId"][:8])
                r = client.post(f"{s.agent_url}/investigate/sync", json={"caseId": f["caseId"]}, timeout=300)
                if r.status_code != 200:
                    log.warning("report for %s failed: HTTP %d", f["caseId"], r.status_code)

        details: dict[str, dict[str, Any]] = {}
        order = [f["caseId"] for f in featured.values()] + [c["caseId"] for c in window]
        for case_id in dict.fromkeys(order):
            details[case_id] = _get(client, f"{s.case_url}/cases/{case_id}")

        # Every case that opens gets its account's history and graph, so the replay never asks
        # for a file that is not there; ring members too, so the graph can be walked.
        users: list[str] = [d["userId"] for d in details.values()]
        for f in featured.values():
            d = details[f["caseId"]]
            users += [str(u) for u in signal(d.get("decisionDoc") or {}, "RING_SUSPECT").get("cycle") or []]
            users += (f["scenario"] or {}).get("users") or []
        histories, graphs = {}, {}
        for user in dict.fromkeys(users):
            try:
                histories[user] = _get(client, f"{s.case_url}/internal/users/{user}/history")
                graphs[user] = _get(client, f"{s.case_url}/internal/graph/{user}/neighborhood", params={"depth": 2})
            except httpx.HTTPError as e:
                log.warning("no history/graph for %s: %s", user, e)

        asks: dict[str, list[dict[str, Any]]] = {}
        if s.agent:
            time.sleep(ASK_PACE_S)         # the reports just spent this minute's token budget
            for n, (pattern, f) in enumerate(featured.items()):
                if n:
                    time.sleep(ASK_PACE_S)
                rules = details[f["caseId"]].get("firedRules") or []
                log.info("asking about %s case %s", pattern, f["caseId"][:8])
                asks[f["caseId"]] = ask_all(client, s.agent_url, f["caseId"], suggested_questions(rules, s.questions))

        try:
            scorer_model = _get(client, f"{s.scorer_url}/health").get("modelVersion")
        except httpx.HTTPError:
            scorer_model = None

    cities = load_cities()
    manifest = {
        "recordedAt": iso_ms(start),
        "durationMs": int((end - start).total_seconds() * 1000),
        "tps": round(len(feed) / max(1.0, (end - start).total_seconds()), 1),
        "scorerModel": scorer_model,
        "agentModel": agent_model,
        "stats": window_stats(window),
        "featured": [],
    }
    for pattern, f in featured.items():
        d = details[f["caseId"]]
        title, blurb = describe(pattern, d.get("decisionDoc") or {}, f["scenario"], feed, cities)
        manifest["featured"].append({"caseId": f["caseId"], "pattern": pattern, "title": title, "blurb": blurb})

    files: dict[str, Any] = {
        "manifest.json": manifest,
        "feed.json": {"ticks": feed},
        "cases.json": {"items": window, "total": len(window)},
        **{f"cases/{cid}.json": d for cid, d in details.items()},
        **{f"history/{u}.json": h for u, h in histories.items()},
        **{f"graph/{u}.json": g for u, g in graphs.items()},
        # an empty file for every case with no recorded answers: the replay then knows there
        # are none without a 404 in the console
        **{f"ask/{cid}.json": {"answers": asks.get(cid, [])} for cid in details},
    }
    write_atomically(out_dir, files)
    return manifest


def write_atomically(out_dir: pathlib.Path, files: dict[str, Any]) -> None:
    """The console must never see half a recording, so the new one is built beside the old
    and swapped in."""
    out_dir.parent.mkdir(parents=True, exist_ok=True)
    tmp = pathlib.Path(tempfile.mkdtemp(prefix=".showcase-", dir=out_dir.parent))
    for rel, doc in files.items():
        path = tmp / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(doc, separators=(",", ":"), ensure_ascii=False))
    old = out_dir.with_name(out_dir.name + ".old")
    if out_dir.exists():
        shutil.rmtree(old, ignore_errors=True)
        os.replace(out_dir, old)
    os.replace(tmp, out_dir)
    shutil.rmtree(old, ignore_errors=True)
    size = sum(p.stat().st_size for p in out_dir.rglob("*") if p.is_file())
    log.info("wrote %d files, %.1f MB, to %s", len(files), size / 1e6, out_dir)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="record a live FraudGraph session for the public replay")
    ap.add_argument("--duration", type=float, default=240.0, help="seconds of live traffic to record")
    ap.add_argument("--out", type=pathlib.Path, default=REPO / "dashboard" / "public" / "showcase")
    ap.add_argument("--case-url", default="http://localhost:8082")
    ap.add_argument("--agent-url", default="http://localhost:8010")
    ap.add_argument("--scorer-url", default="http://localhost:8000")
    ap.add_argument("--no-scenarios", action="store_true", help="record only what the generator plants at random")
    ap.add_argument("--no-agent", action="store_true", help="skip analyst reports and recorded answers")
    ap.add_argument("--questions", type=int, default=3, help="suggested questions answered per featured case")
    ap.add_argument("--max-cases", type=int, default=400, help="cases saved in full (all of the window, up to this)")
    ap.add_argument("--answers-only", action="store_true",
                    help="keep the recording, re-ask the featured cases' questions and rewrite their answers")
    ap.add_argument("--pace", type=float, default=ASK_PACE_S, help="seconds between questions to the analyst")
    ap.add_argument("--only", default="", help="with --answers-only: featured patterns to redo, e.g. RING,GEO")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s", stream=sys.stderr)

    s = Session(case_url=args.case_url.rstrip("/"), agent_url=args.agent_url.rstrip("/"),
                scorer_url=args.scorer_url.rstrip("/"), duration=args.duration, scenarios=not args.no_scenarios,
                agent=not args.no_agent, questions=args.questions, max_cases=args.max_cases,
                compose_dir=REPO)
    if args.answers_only:
        reanswer(args.out, s.agent_url, args.questions, args.pace,
                 {x.strip().upper() for x in args.only.split(",") if x.strip()} or None)
        return 0
    if s.agent:
        health = httpx.get(f"{s.agent_url}/health", timeout=10).json()
        if "ask" not in health:
            raise SystemExit("the running analyst-agent predates the ask endpoint: rebuild it (make demo), "
                             "or pass --no-agent")
        if health.get("status") != "UP":
            raise SystemExit(f"the analyst agent is not ready: {health.get('error')}")
    start, end = asyncio.run(s.record())
    time.sleep(5)                       # the last ticks' cases are still being written
    manifest = collect(s, start, end, args.out)
    print(json.dumps({k: manifest[k] for k in ("recordedAt", "durationMs", "tps", "scorerModel", "agentModel")}))
    for f in manifest["featured"]:
        print(f"  {f['pattern']:<9} {f['title']}  —  {f['blurb']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
