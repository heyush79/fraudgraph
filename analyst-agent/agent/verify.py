"""The verify node: a hallucination guard implemented as code, not as prompt-begging.

Two checks, both mechanical:

1. Every ``evidence_refs`` index a finding cites must exist in the evidence the agent
   actually collected, and must point at a tool call that succeeded. Citing evidence that
   is not there is the most common way a model fabricates support.
2. Every number quoted in a claim must appear in the payloads of the evidence that claim
   cites. A model that writes "23 transactions in 60 seconds" when the evidence says 18 is
   caught here, and no amount of prompt wording would have prevented it.

Failure sends the report back through ``investigate`` once. A second failure escalates with
``fraud_type: UNCERTAIN``, which is an honest answer rather than a confident wrong one.
"""
from __future__ import annotations

import re
from typing import Any, Iterable

from .models import Evidence, Report, Violation

# 1,234.56 | 1234 | 0.91 | -3.8 — the thousands separator has to be optional-but-grouped
# or "18 transactions in 60s" would parse "18 60" as one number.
_NUMBER = re.compile(r"-?\d{1,3}(?:,\d{3})+(?:\.\d+)?|-?\d+(?:\.\d+)?")

# Numbers inside an ISO timestamp are describing *when*, not a quantity, and the evidence
# stores the timestamp as a string. Strip them before extracting quantities.
_ISO_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?Z?")

# Relative tolerance for a quoted number against the evidence. A report that rounds
# 13499.3 km/h to "13,499" or "13,500" is being readable, not wrong.
REL_TOLERANCE = 0.01

# Small integers are ordinary English ("one of the four accounts", "a 5-cycle") and appear
# in almost any evidence payload by coincidence, so requiring a match for them produces
# noise rather than signal.
MIN_CHECKED_VALUE = 3.0


def extract_numbers(text: str) -> list[float]:
    """Quantities a claim asserts. Timestamps and percent-of-nothing are excluded."""
    cleaned = _ISO_TIMESTAMP.sub(" ", text)
    out: list[float] = []
    for raw in _NUMBER.findall(cleaned):
        try:
            out.append(float(raw.replace(",", "")))
        except ValueError:  # pragma: no cover - the regex cannot produce this
            continue
    return out


def flatten_numbers(payload: Any) -> set[float]:
    """Every number reachable in an evidence payload, including inside strings, since the
    engine formats some values as text (a user id, a coordinate pair, a cycle).

    Collection sizes count as evidence too. A report that says "five accounts formed a
    cycle" is making a true statement about a six-element cycle list whose first and last
    entries are the same account, and refusing that would push the model towards vaguer
    prose rather than more accurate prose. Both the length and the distinct-element count
    are therefore available."""
    found: set[float] = set()
    _walk(payload, found)
    return found


def _walk(node: Any, found: set[float]) -> None:
    if node is None or isinstance(node, bool):
        return
    if isinstance(node, (int, float)):
        found.add(float(node))
        return
    if isinstance(node, str):
        found.update(extract_numbers(node))
        return
    if isinstance(node, dict):
        found.add(float(len(node)))
        for key, value in node.items():
            _walk(key, found)
            _walk(value, found)
        return
    if isinstance(node, Iterable):
        items = list(node)
        found.add(float(len(items)))
        try:
            found.add(float(len(set(items))))
        except TypeError:      # unhashable members, e.g. a list of dicts
            pass
        for item in items:
            _walk(item, found)


def _matches(value: float, candidates: set[float]) -> bool:
    for c in candidates:
        if value == c:
            return True
        tolerance = max(abs(c), abs(value)) * REL_TOLERANCE
        if abs(value - c) <= tolerance:
            return True
        # a claim may round or truncate: 13499.3 -> 13499, 0.9997 -> 1.0 is not ok but
        # 13499.3 -> 13500 is, so compare against the rounded forms explicitly
        if value in (round(c), int(c)) or round(value) == round(c):
            return True
    return False


def verify(report: Report, evidence: list[Evidence]) -> list[Violation]:
    """Empty list means the report is citable. Never raises."""
    violations: list[Violation] = []
    for i, finding in enumerate(report.findings):
        if not finding.evidence_refs:
            violations.append(Violation(
                finding_index=i, kind="no_refs",
                detail=f"claim cites no evidence: {finding.claim!r}"))
            continue

        bad = [r for r in finding.evidence_refs if r >= len(evidence)]
        if bad:
            violations.append(Violation(
                finding_index=i, kind="bad_ref",
                detail=f"evidence_refs {bad} do not exist; collected evidence is indexed 0..{len(evidence) - 1}"))
            continue

        failed = [r for r in finding.evidence_refs if not evidence[r].ok()]
        if failed:
            violations.append(Violation(
                finding_index=i, kind="failed_tool_ref",
                detail=f"evidence_refs {failed} point at tool calls that failed and carry no data"))
            continue

        available: set[float] = set()
        for r in finding.evidence_refs:
            available |= flatten_numbers(evidence[r].payload)

        for value in extract_numbers(finding.claim):
            if abs(value) < MIN_CHECKED_VALUE:
                continue
            if not _matches(value, available):
                violations.append(Violation(
                    finding_index=i, kind="uncited_number",
                    detail=(f"claim quotes {value:g}, which does not appear in evidence "
                            f"{finding.evidence_refs}: {finding.claim!r}")))
    return violations


def violations_prompt(violations: list[Violation]) -> str:
    """What the model is told on its one retry. Specific, and never 'try harder'."""
    lines = ["Your draft report failed verification. Each problem below is mechanical, "
             "not a matter of opinion. Fix them by gathering the missing evidence or by "
             "rewriting the claim to match what the evidence actually says."]
    for v in violations:
        lines.append(f"- finding #{v.finding_index} ({v.kind}): {v.detail}")
    lines.append("Do not remove a claim just to pass. If the evidence does not support a "
                 "claim, say what the evidence does support instead.")
    return "\n".join(lines)
