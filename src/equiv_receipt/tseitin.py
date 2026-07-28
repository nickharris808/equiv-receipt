"""Gate-netlist to CNF, and equivalence miters — standard library only.

A miter of two circuits is satisfiable exactly when they differ on some input.
So *unsatisfiability of the miter is equivalence*, and a DRAT refutation of the
miter is a checkable proof of it.
"""
from __future__ import annotations

from typing import Dict, List, Sequence, Tuple

Clause = List[int]


class Netlist:
    """A tiny combinational netlist over AND / OR / NOT / XOR gates.

    Inputs are named; every gate produces a new named signal. Deliberately
    minimal — this exists so the package is usable and testable without a
    synthesis tool, not to replace one.
    """

    def __init__(self, inputs: Sequence[str]):
        self._var: Dict[str, int] = {}
        self._clauses: List[Clause] = []
        self._n = 0
        self.inputs = list(inputs)
        for name in inputs:
            self._new(name)

    def _new(self, name: str) -> int:
        if name in self._var:
            raise ValueError(f"signal {name!r} already defined")
        self._n += 1
        self._var[name] = self._n
        return self._n

    def var(self, name: str) -> int:
        return self._var[name]

    # --- gates: each emits the standard Tseitin clauses ---

    def NOT(self, out: str, a: str) -> str:
        o, x = self._new(out), self.var(a)
        self._clauses += [[-o, -x], [o, x]]
        return out

    def AND(self, out: str, a: str, b: str) -> str:
        o, x, y = self._new(out), self.var(a), self.var(b)
        self._clauses += [[-o, x], [-o, y], [o, -x, -y]]
        return out

    def OR(self, out: str, a: str, b: str) -> str:
        o, x, y = self._new(out), self.var(a), self.var(b)
        self._clauses += [[o, -x], [o, -y], [-o, x, y]]
        return out

    def XOR(self, out: str, a: str, b: str) -> str:
        o, x, y = self._new(out), self.var(a), self.var(b)
        self._clauses += [[-o, x, y], [-o, -x, -y], [o, -x, y], [o, x, -y]]
        return out

    @property
    def clauses(self) -> List[Clause]:
        return [list(c) for c in self._clauses]

    def n_vars(self) -> int:
        return self._n


def miter(build_a, build_b, inputs: Sequence[str]) -> Tuple[List[Clause], Netlist]:
    """Build a miter CNF for two single-output circuit builders.

    ``build_a(net, prefix) -> output_signal_name``. The returned CNF is
    satisfiable iff the two circuits differ on some input assignment; therefore
    **UNSAT means equivalent**.
    """
    net = Netlist(inputs)
    out_a = build_a(net, "a_")
    out_b = build_b(net, "b_")
    net.XOR("miter_out", out_a, out_b)
    clauses = net.clauses
    clauses.append([net.var("miter_out")])   # assert they differ
    return clauses, net
