"""Forward DRAT checking — standard library only.

A DRAT refutation is a sequence of clause additions and deletions. An addition is
sound if the added clause is *reverse unit propagation* (RUP): assuming the
negation of every literal in the clause and propagating over the currently active
clause set yields a conflict. Failing that, it may still be a *resolution
asymmetric tautology* (RAT) on its first literal, which is what solvers emit when
they eliminate variables.

Checking that is a few hundred lines. Producing it is what a SAT solver is for.
That asymmetry is the whole reason this file exists: anyone can check, nobody has
to trust.

**Two implementations, on purpose.** :func:`bcp` is the naive one: a few dozen
lines, obviously correct, re-scanning every clause until nothing changes. It is
the specification. :class:`ClauseDB` is the fast one, using two watched literals
per clause and an index for deletion, and it is what :func:`forward_rup_check`
actually runs. They are checked against each other on random instances, so the
fast path has an executable oracle rather than a promise.
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


def _as_assignment(trail: Sequence[int]) -> Dict[int, bool]:
    """Trail of true literals to the ``{var: bool}`` map :func:`bcp` returns."""
    return {abs(lit): lit > 0 for lit in trail}


class ClauseDB:
    """A clause store with two watched literals per clause.

    The naive checker re-scans every active clause on every propagation round, and
    the active set grows by one on every lemma — so the cost of checking a proof
    grows worse than the product of its two dimensions. Watching two literals per
    clause means a clause is only visited when one of the two literals it is
    watching becomes false, which is what makes long proofs checkable.

    The watch invariant survives between calls because every call propagates from
    an empty assignment and undoes nothing: there is no backtracking to invalidate.
    """

    __slots__ = ("cl", "watch", "units", "deleted", "index", "has_empty")

    def __init__(self, clauses: Sequence[Clause] = ()):
        self.cl: List[Clause] = []
        self.watch: Dict[int, List[int]] = {}
        self.units: List[int] = []
        self.deleted: set = set()
        # sorted-literal tuple -> clause indices, so a deletion is a lookup rather
        # than a linear scan that re-sorts every active clause.
        self.index: Dict[Tuple[int, ...], List[int]] = {}
        self.has_empty = False
        for c in clauses:
            self.add(c)

    def add(self, lits: Sequence[int]) -> int:
        c = list(lits)
        i = len(self.cl)
        self.cl.append(c)
        self.index.setdefault(tuple(sorted(c)), []).append(i)
        if not c:
            self.has_empty = True
        elif len(c) == 1:
            self.units.append(i)
        else:
            self.watch.setdefault(c[0], []).append(i)
            self.watch.setdefault(c[1], []).append(i)
        return i

    def delete(self, lits: Sequence[int]) -> bool:
        """Mark one clause with exactly these literals deleted. False if absent.

        Deletion is lazy: the index entry is dropped and the clause is added to a
        deleted set that propagation skips. Removing it from its two watch lists
        eagerly would cost more than skipping it.
        """
        bucket = self.index.get(tuple(sorted(lits)))
        while bucket:
            i = bucket.pop()
            if i not in self.deleted:
                self.deleted.add(i)
                return True
        return False

    def live(self):
        """The currently active clauses, in insertion order."""
        return [c for i, c in enumerate(self.cl) if i not in self.deleted]

    def propagate(self, assumed: Sequence[int]) -> Tuple[bool, Dict[int, bool]]:
        """Unit propagation from ``assumed``. Returns ``(conflict, assignment)``.

        Semantics are identical to :func:`bcp`; only the cost differs.

        Truth is tracked as a set of true *literals* rather than a variable-to-bool
        map. "Is this literal true" becomes one set lookup and "is it false"
        becomes one on its negation, which removes an ``abs()`` and a second
        lookup from the innermost loop — measurably the hottest path in the file.
        """
        if self.has_empty:
            return True, {}
        true_lits: set = set()
        trail: List[int] = []
        watch = self.watch
        cls = self.cl
        deleted = self.deleted

        for lit in assumed:
            if -lit in true_lits:
                return True, _as_assignment(trail)
            if lit not in true_lits:
                true_lits.add(lit)
                trail.append(lit)
        for i in self.units:
            if i in deleted:
                continue
            lit = cls[i][0]
            if -lit in true_lits:
                return True, _as_assignment(trail)
            if lit not in true_lits:
                true_lits.add(lit)
                trail.append(lit)

        qi = 0
        while qi < len(trail):
            false_lit = -trail[qi]
            qi += 1
            ws = watch.get(false_lit)
            if not ws:
                continue
            # Compact the watch list in place. Allocating a replacement list here
            # was 4.5M appends on a 6.5k-lemma proof.
            j = 0
            conflict = False
            for n in range(len(ws)):
                ci = ws[n]
                if ci in deleted:
                    continue
                c = cls[ci]
                if c[0] == false_lit:          # normalise: c[1] is the false watch
                    c[0], c[1] = c[1], c[0]
                other = c[0]
                if other in true_lits:
                    ws[j] = ci                  # satisfied by the other watch
                    j += 1
                    continue
                for k in range(2, len(c)):
                    lit = c[k]
                    if -lit not in true_lits:
                        c[1], c[k] = c[k], c[1]
                        watch.setdefault(c[1], []).append(ci)
                        break
                else:
                    ws[j] = ci                  # no replacement: unit, or conflicting
                    j += 1
                    if -other in true_lits:
                        conflict = True
                        rest = ws[n + 1:]
                        del ws[j:]
                        ws.extend(rest)
                        break
                    if other not in true_lits:
                        true_lits.add(other)
                        trail.append(other)
            else:
                del ws[j:]
            if conflict:
                return True, _as_assignment(trail)
        return False, _as_assignment(trail)


def _is_rat(db: ClauseDB, lits: Sequence[int]) -> bool:
    """RAT on the first literal: every resolvent on the pivot must be RUP.

    Solvers emit these when they eliminate variables, so a checker that only knows
    RUP will reject perfectly good proofs from real tools. Rejecting a valid proof
    is not unsound, but it is wrong, and it would make the external-solver adapter
    useless in exactly the cases it exists for.
    """
    if not lits:
        return False
    pivot = lits[0]
    for ci, c in enumerate(db.cl):
        if ci in db.deleted or -pivot not in c:
            continue
        resolvent = list(lits) + [x for x in c if x != -pivot]
        conflict, _ = db.propagate([-x for x in resolvent])
        if not conflict:
            return False
    return True


def forward_rup_check(clauses: Sequence[Clause], drat_text: str) -> dict:
    """Verify a DRAT refutation by forward RUP checking.

    Returns a dict with ``verified``, ``n_lemmas``, and — on failure — the
    ``failed_lemma`` and its zero-based ``failed_index`` so the defect is
    locatable rather than merely reported.

    A refutation is accepted when an empty clause is derived, or when the final
    active set propagates to a conflict with no assumptions.
    """
    db = ClauseDB(clauses)
    n_lemmas = 0
    n_rat = 0

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
            db.delete(lits)
            continue

        conflict, _ = db.propagate([-lit for lit in lits])
        if not conflict:
            if _is_rat(db, lits):
                n_rat += 1
            else:
                return {"verified": False, "n_lemmas": n_lemmas,
                        "failed_lemma": lits, "failed_index": idx,
                        "reason": "lemma is neither RUP nor RAT on its first "
                                  "literal: assuming its negation does not "
                                  "propagate to a conflict, and neither does at "
                                  "least one resolvent on the pivot"}
        n_lemmas += 1
        db.add(lits)
        if not lits:
            return {"verified": True, "n_lemmas": n_lemmas, "n_rat": n_rat,
                    "reason": "empty clause derived"}

    conflict, _ = db.propagate([])
    return {"verified": bool(conflict), "n_lemmas": n_lemmas, "n_rat": n_rat,
            "reason": "final clause set propagates to conflict" if conflict
                      else "proof ended without deriving a contradiction"}
