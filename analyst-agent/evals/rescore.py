"""Re-score a saved eval run without calling the model again.

    python -m evals.rescore evals/results/20260914T101231Z.json

Useful when the scoring logic changes, and essential when a run was partly starved by a
provider quota: the raw results still hold every report, so the corrected numbers cost nothing.
"""
from __future__ import annotations

import json
import pathlib
import sys

from .run import markdown, score


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        runs = sorted(pathlib.Path("evals/results").glob("*.json"))
        if not runs:
            print("no saved runs under evals/results", file=sys.stderr)
            return 1
        path = runs[-1]
    else:
        path = pathlib.Path(args[0])

    saved = json.loads(path.read_text())
    summary = score(saved["results"])
    table = markdown(summary, saved["meta"])
    out = path.with_suffix(".rescored.md")
    out.write_text(table)
    pathlib.Path("evals/results/latest.md").write_text(table)
    print(f"rescored {path.name} -> {out.name}\n")
    print(table)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
