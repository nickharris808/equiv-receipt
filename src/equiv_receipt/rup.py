"""Forward RUP checking of DRAT refutations — standard library only.

A DRAT refutation is a sequence of clause additions and deletions. An addition is
sound if the added clause is *reverse unit propagation* (RUP): assuming the
negation of every literal in the clause and running unit propagation over the
currently active clause set yields a conflict.

Checking that is a few dozen lines. Producing it is what a SAT solver is for.
That asymmetry is the whole reason this file exists: anyone can check, nobody has
to trust.
"""
from __future__ import annotations

from typing import Dict, List, Sequence, Tuple

Clause = List[int]


def bcp(clauses: Sequence[Clause], assumed: Sequence[int]) -> Tuple[bool, Dict[int, bool]]:
    """Unit propagation. Returns ``(conflict, assignment)``.

    ``conflict`` is True when propagation derives a contradiction.
    """
    assign: Dict[int, bool] = {}
    for a in assumed:
        v, val = abs(a), a > 0
        if assign.get(v, val) != val:
            return True, assign
        assign[v] = val

    changed = True
    while changed:
        changed = False
        for cl in clauses:
            unassigned: List[int] = []
            satisfied = False
            for lit in cl:
                v = abs(lit)
                if v in assign:
                    if assign[v] == (lit > 0):
                        satisfied = True
                        break
                else:
                    unassigned.append(lit)
            if satisfied:
                continue
            if not unassigned:
                return True, assign
            if len(unassigned) == 1:
                lit = unassigned[0]
                assign[abs(lit)] = lit > 0
                changed = True
    return False, assign


class MalformedProof(ValueError):
    """A DRAT text that cannot be parsed. Raised only by strict callers."""


def parse_drat(drat_text: str) -> List[Tuple[str, Clause]]:
    """Parse DRAT into ``("a"|"d", clause)`` steps. Comment lines (``c``) are skipped.

    Raises :class:`MalformedProof` on unparseable input. Callers that must not
    crash should use :func:`forward_rup_check`, which converts this into a
    *rejection* — an unreadable proof proves nothing, which is a verdict, not an
    error condition.
    """
    steps: List[Tuple[str, Clause]] = []
    for lineno, raw in enumerate(drat_text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("c"):
            continue
        toks = line.split()
        try:
            if toks[0] == "d":
                steps.append(("d", [int(t) for t in toks[1:] if int(t) != 0]))
            else:
                steps.append(("a", [int(t) for t in toks if int(t) != 0]))
        except ValueError as exc:
            raise MalformedProof(
                f"line {lineno}: {raw.strip()[:60]!r} is not a DRAT step "
                f"(expected space-separated integers ending in 0)") from exc
    return steps


def forward_rup_check(clauses: Sequence[Clause], drat_text: str) -> dict:
    """Verify a DRAT refutation by forward RUP checking.

    Returns a dict with ``verified``, ``n_lemmas``, and — on failure — the
    ``failed_lemma`` and its zero-based ``failed_index`` so the defect is
    locatable rather than merely reported.

    A refutation is accepted when an empty clause is derived, or when the final
    active set propagates to a conflict with no assumptions.
    """
    active: List[Clause] = [list(c) for c in clauses]
    n_lemmas = 0

    # An unreadable proof does not prove anything. That is a REJECTION, not a
    # crash: a checker that raises on hostile input is a denial of service, and a
    # caller catching broadly might mistake the exception for something else.
    try:
        steps = parse_drat(drat_text)
    except MalformedProof as exc:
        return {"verified": False, "n_lemmas": 0,
                "reason": f"malformed proof: {exc}"}

    for idx, (op, lits) in enumerate(steps):
        if op == "d":
            key = sorted(lits)
            for i, cl in enumerate(active):
                if sorted(cl) == key:
                    active.pop(i)
                    break
            continue

        conflict, _ = bcp(active, [-lit for lit in lits])
        if not conflict:
            return {"verified": False, "n_lemmas": n_lemmas,
                    "failed_lemma": lits, "failed_index": idx,
                    "reason": "lemma is not RUP: assuming its negation does not "
                              "propagate to a conflict"}
        n_lemmas += 1
        active.append(list(lits))
        if not lits:
            return {"verified": True, "n_lemmas": n_lemmas, "reason": "empty clause derived"}

    conflict, _ = bcp(active, [])
    return {"verified": bool(conflict), "n_lemmas": n_lemmas,
            "reason": "final clause set propagates to conflict" if conflict
                      else "proof ended without deriving a contradiction"}
