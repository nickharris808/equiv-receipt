"""DIMACS CNF read/write — standard library only."""
from __future__ import annotations

from typing import List, Sequence

Clause = List[int]


class CNFParseError(ValueError):
    """A DIMACS text that cannot be parsed."""


def parse_dimacs(text: str, *, strict: bool = True) -> List[Clause]:
    """Parse DIMACS CNF.

    With ``strict=True`` (the default) a malformed header, a non-integer token, or
    an unterminated final clause **raises** :class:`CNFParseError`. Silently
    returning a partial or empty clause list would let a caller reason confidently
    about a formula that is not the one on disk — the worst failure mode available
    to a proof checker.

    Pass ``strict=False`` for the older lenient behaviour.
    """
    clauses: List[Clause] = []
    cur: Clause = []
    saw_header = False
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("c"):
            continue
        if line.startswith("p"):
            parts = line.split()
            if strict:
                if len(parts) != 4 or parts[1] != "cnf":
                    raise CNFParseError(
                        f"line {lineno}: malformed header {line[:40]!r} "
                        f"(expected 'p cnf <vars> <clauses>')")
                try:
                    int(parts[2])
                    int(parts[3])
                except ValueError as exc:
                    raise CNFParseError(
                        f"line {lineno}: header counts are not integers: {line[:40]!r}") from exc
            saw_header = True
            continue
        for tok in line.split():
            try:
                v = int(tok)
            except ValueError as exc:
                if strict:
                    raise CNFParseError(
                        f"line {lineno}: {tok!r} is not an integer literal") from exc
                raise
            if v == 0:
                clauses.append(cur)
                cur = []
            else:
                cur.append(v)
    if cur:
        if strict:
            raise CNFParseError(
                "final clause is not terminated by 0 — the formula is truncated")
        clauses.append(cur)
    if strict and not saw_header and clauses:
        raise CNFParseError(
            "no 'p cnf' header found — refusing to guess the formula's shape; "
            "pass strict=False to parse anyway")
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
