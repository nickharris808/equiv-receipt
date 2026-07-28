"""A small DRAT-emitting refutation search — standard library only.

**Scope, stated plainly.** This is a textbook DPLL search with no clause-learning
heuristics, no watched literals, and no restarts. It exists so that this package
is *self-contained and testable* — you can build a miter, refute it, and check
the refutation without installing a SAT solver. It is emphatically **not** a
production prover. For anything beyond small instances use a real solver
(CaDiCaL, Kissat) in proof-emitting mode; this package checks whatever DRAT it
is handed, regardless of origin.

**Why the emitted proof is valid.** At a node whose decision literals are
``d1..dk``, if unit propagation conflicts, the clause ``(-d1 … -dk)`` is RUP by
construction — assuming its negation *is* assuming ``d1..dk``, which is exactly
the propagation that just conflicted. After both children of a branch have
emitted their lemmas, the parent's own clause becomes RUP too, because the two
child lemmas propagate to opposite values of the branch variable. At the root
this yields the empty clause.
"""
from __future__ import annotations

import sys
from typing import List, Optional, Sequence

from .rup import Clause, bcp


def _pick(clauses: Sequence[Clause], assign) -> Optional[int]:
    for cl in clauses:
        for lit in cl:
            if abs(lit) not in assign:
                return abs(lit)
    return None


def refute(clauses: Sequence[Clause], *, max_depth: int = 60) -> dict:
    """Search for a refutation, emitting DRAT lemmas.

    Returns ``{"unsat": bool, "drat": str, "n_lemmas": int, "model": dict|None}``.
    When ``unsat`` is False a satisfying assignment is returned instead — for a
    miter that is a **counterexample**: the two circuits differ on it.
    """
    active: List[Clause] = [list(c) for c in clauses]
    lemmas: List[Clause] = []
    model = {}

    limit = max(1000, sys.getrecursionlimit())
    sys.setrecursionlimit(limit)

    def emit(lits: Clause) -> None:
        lemmas.append(list(lits))
        active.append(list(lits))

    def search(decisions: List[int], depth: int) -> bool:
        nonlocal model
        if depth > max_depth:
            raise RecursionError(
                f"search exceeded max_depth={max_depth}; this is a small-instance "
                f"solver — use an external proof-emitting SAT solver")
        conflict, assign = bcp(active, decisions)
        if conflict:
            emit([-d for d in decisions])
            return True
        v = _pick(active, assign)
        if v is None:
            model = dict(assign)
            return False
        if not search(decisions + [v], depth + 1):
            return False
        if not search(decisions + [-v], depth + 1):
            return False
        emit([-d for d in decisions])
        return True

    unsat = search([], 0)
    drat = "".join(" ".join(str(lit) for lit in lem) + (" " if lem else "") + "0\n"
                   for lem in lemmas)
    return {"unsat": unsat, "drat": drat, "n_lemmas": len(lemmas),
            "model": None if unsat else model}
