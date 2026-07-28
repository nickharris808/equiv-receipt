"""DIMACS CNF read/write — standard library only."""
from __future__ import annotations

from typing import List, Sequence

Clause = List[int]


def parse_dimacs(text: str) -> List[Clause]:
    """Parse DIMACS CNF. Header and comments are tolerated but not required."""
    clauses: List[Clause] = []
    cur: Clause = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("c") or line.startswith("p"):
            continue
        for tok in line.split():
            v = int(tok)
            if v == 0:
                clauses.append(cur)
                cur = []
            else:
                cur.append(v)
    if cur:
        clauses.append(cur)
    return clauses


def to_dimacs(clauses: Sequence[Clause]) -> str:
    """Serialize to DIMACS with a correct header.

    The byte-level output is deterministic: this is what a receipt commits to, so
    an unstable serializer would make receipts unverifiable.
    """
    n_vars = max((abs(lit) for cl in clauses for lit in cl), default=0)
    lines = [f"p cnf {n_vars} {len(clauses)}"]
    lines += [" ".join(str(lit) for lit in cl) + " 0" for cl in clauses]
    return "\n".join(lines) + "\n"
