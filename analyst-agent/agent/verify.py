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

import math
import re
from typing import Any, Iterable

from .models import Evidence, Finding, Report, Violation

# 1,234.56 | 1234 | 0.91 | -3.8 — the thousands separator has to be optional-but-grouped
# or "18 transactions in 60s" would parse "18 60" as one number.
_NUMBER = re.compile(r"-?\d{1,3}(?:,\d{3})+(?:\.\d+)?|-?\d+(?:\.\d+)?")

# Numbers inside an ISO timestamp are describing *when*, not a quantity, and the evidence
# stores the timestamp as a string. Strip them before extracting quantities.
_ISO_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?Z?")

# Nor are the digits inside a UUID: a transaction id like 1af96d0e-5b18-... would otherwise
# put 5, 18 and friends into every payload that mentions it, supporting claims by accident.
_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")

# Models write minus signs as whatever the tokenizer offers: U+2212, a non-breaking hyphen,
# an en dash. "amtZ = ‑0.38" is a correct quote of -0.38 and must not read as +0.38.
_MINUS_SIGNS = str.maketrans({c: "-" for c in "\u2212\u2010\u2011\u2012\u2013\ufe63\uff0d"})

# Thousands separators written as a narrow or no-break space ("13 805", "1 033 km"), which
# models produce as readily as commas. Read as two numbers, "13" would fail a claim whose
# number is in the evidence. Only a space followed by exactly three digits is a separator.
_SPACED_THOUSANDS = re.compile(r"(?<=\d)[\u202f\u00a0\u2009](?=\d{3}(?!\d))")

# Citation markers the model writes into its own prose, "(evidence [3])" or "[0, 2]": they
# point at evidence, they do not quote a quantity, and read as numbers they fail the claim.
_CITATION_MARKER = re.compile(r"\[\s*\d+(?:\s*,\s*\d+)*\s*\]")

# Relative tolerance for a quoted number against the evidence. A report that rounds
# 13499.3 km/h to "13,499" or "13,500" is being readable, not wrong.
REL_TOLERANCE = 0.01

# Small integers are ordinary English ("one of the four accounts", "two signals") and appear
# in almost any evidence payload by coincidence, so requiring a match for them produces
# noise rather than signal. Only integers: a decimal is never ordinary English, and the
# numbers below 3 that matter most (a model score of 0.9997, a ratio of 0.96, a SHAP
# contribution of 1.57) are exactly the ones a fabricated claim would get wrong.
MIN_CHECKED_VALUE = 3.0


def _exempt(value: float) -> bool:
    return abs(value) < MIN_CHECKED_VALUE and value.is_integer()


def extract_numbers(text: str) -> list[float]:
    """Quantities a claim asserts. Timestamps and percent-of-nothing are excluded."""
    return [value for value, _ in extract_quantities(text)]


def extract_quantities(text: str) -> list[tuple[float, bool]]:
    """(value, is_percent) for every quantity in a claim. "Forwarded 97% of it" yields
    (97.0, True), which may be checked against a ratio of 0.97 in the evidence."""
    cleaned = _CITATION_MARKER.sub(" ", _UUID.sub(" ", _ISO_TIMESTAMP.sub(
        " ", _SPACED_THOUSANDS.sub("", text.translate(_MINUS_SIGNS)))))
    out: list[tuple[float, bool]] = []
    for m in _NUMBER.finditer(cleaned):
        try:
            value = float(m.group(0).replace(",", ""))
        except ValueError:  # pragma: no cover - the regex cannot produce this
            continue
        is_percent = cleaned[m.end():m.end() + 1] == "%"
        out.append((value, is_percent))
    return out


def flatten_numbers(payload: Any) -> set[float]:
    """Every number reachable in an evidence payload, including inside strings, since the
    engine formats some values as text (a user id, a coordinate pair, a cycle).

    List sizes count as evidence too. A report that says "five accounts formed a cycle" is
    making a true statement about a six-element cycle list whose first and last entries are
    the same account, and refusing that would push the model towards vaguer prose rather
    than more accurate prose. Both the length and the distinct-element count are therefore
    available. The number of keys in an object is not: nobody means "12" when they write
    about a decision that happens to have twelve fields, and counting it let a fabricated
    "flagged 12 times" through."""
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


def _decimal_places(value: float) -> int | None:
    text = repr(value)
    if "e" in text or "n" in text:              # 1e-05, inf, nan: relative tolerance only
        return None
    return len(text.split(".")[1].rstrip("0")) if "." in text else 0


def _matches(value: float, candidates: set[float]) -> bool:
    places = _decimal_places(value)
    for c in candidates:
        if value == c:
            return True
        # Rounding for readability is not fabrication: 13499.3 km/h quoted as "13,500".
        if abs(value - c) <= max(abs(c), abs(value)) * REL_TOLERANCE:
            return True
        # Nor is quoting fewer decimals than the evidence carries: 1.5672 as "1.6", 4.669 s as
        # "5 s". Half a unit in the claim's last place and no more, so that a claim of 0.42 is
        # never "about" a 0.25 somewhere in the payload.
        if places is not None and abs(value - c) <= 0.5 * 10 ** -places + 1e-9:
            return True
        # Truncating to a whole number is the other common reading: 4.669 s as "4 seconds".
        if places == 0 and value == math.trunc(c):
            return True
    return False


def verify(report: Report, evidence: list[Evidence]) -> list[Violation]:
    """Empty list means the report is citable. Never raises."""
    return verify_claims(report.findings, evidence)


def verify_claims(findings: list[Finding], evidence: list[Evidence]) -> list[Violation]:
    """The check itself, over any list of claims: a report's findings, or the sentences of a
    chat answer. Each violation carries the index of the claim it applies to."""
    violations: list[Violation] = []
    for i, finding in enumerate(findings):
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

        # Magnitudes, not signs. Direction is carried by the words around a number ("pushed it
        # away from fraud by 0.68", "0.38 below its average"), and requiring the sign as well
        # rejected correct prose far more often than it caught a flipped one. What this
        # check guarantees is that the quantity itself came from the evidence.
        available: set[float] = set()
        for r in finding.evidence_refs:
            available |= {abs(n) for n in flatten_numbers(evidence[r].payload)}

        for value, is_percent in extract_quantities(finding.claim):
            value = abs(value)
            if _exempt(value):
                continue
            if _matches(value, available) or (is_percent and _matches(value / 100.0, available)):
                continue
            violations.append(Violation(
                finding_index=i, kind="uncited_number",
                detail=(f"claim quotes {value:g}{'%' if is_percent else ''}, which does not appear in evidence "
                        f"{finding.evidence_refs}: {finding.claim!r}")))
    return violations


def violations_prompt(violations: list[Violation], what: str = "draft report") -> str:
    """What the model is told on its one retry. Specific, and never 'try harder'."""
    lines = [f"Your {what} failed verification. Each problem below is mechanical, "
             "not a matter of opinion. Fix them by gathering the missing evidence or by "
             "rewriting the claim to match what the evidence actually says."]
    for v in violations:
        lines.append(f"- finding #{v.finding_index} ({v.kind}): {v.detail}")
    lines.append("Do not remove a claim just to pass. If the evidence does not support a "
                 "claim, say what the evidence does support instead.")
    return "\n".join(lines)
