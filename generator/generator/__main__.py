"""CLI: python -m generator --tps 50 --fraud-rate 0.02 --patterns velocity"""
from __future__ import annotations

import argparse
import logging
import os
import signal
import sys

from .injectors import REGISTRY
from .publisher import KafkaPublisher, StdoutPublisher
from .runner import Runner, RunnerConfig


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="generator", description="FraudGraph synthetic traffic generator")
    p.add_argument("--tps", type=float, default=50.0, help="legitimate transactions per second (Poisson)")
    p.add_argument("--fraud-rate", type=float, default=0.02, help="fraction of transactions that are injected fraud")
    p.add_argument(
        "--patterns", default="velocity",
        help=f"comma-separated fraud patterns to inject; available: {','.join(sorted(REGISTRY))}",
    )
    p.add_argument("--users", type=int, default=500, help="size of the synthetic user population")
    p.add_argument("--seed", type=int, default=None, help="RNG seed for reproducible runs")
    p.add_argument("--duration", type=float, default=None, help="stop after N seconds (default: run forever)")
    p.add_argument(
        "--bootstrap-servers", default=os.environ.get("FRAUDGRAPH_BOOTSTRAP_SERVERS", "localhost:29092"),
        help="Kafka bootstrap servers (env FRAUDGRAPH_BOOTSTRAP_SERVERS)",
    )
    p.add_argument("--dry-run", action="store_true", help="print events to stdout instead of Kafka")
    p.add_argument("--log-level", default="INFO")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=args.log_level.upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s", stream=sys.stderr)

    patterns = tuple(p.strip() for p in args.patterns.split(",") if p.strip()) if args.fraud_rate > 0 else ()
    cfg = RunnerConfig(
        tps=args.tps, fraud_rate=args.fraud_rate, patterns=patterns,
        n_users=args.users, seed=args.seed, duration_secs=args.duration,
    )
    publisher = StdoutPublisher() if args.dry_run else KafkaPublisher(args.bootstrap_servers)
    runner = Runner(cfg, publisher)

    def _on_signal(signum, _frame):  # type: ignore[no-untyped-def]
        logging.getLogger(__name__).info("signal %s received, stopping", signum)
        runner.stop()

    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)
    runner.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
