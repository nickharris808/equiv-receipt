"""One-call equivalence proving: circuits in, receipt out."""
from __future__ import annotations

from typing import Dict, Sequence

from .dimacs import to_dimacs
from .minisolve import refute as _bundled_refute
from .receipt import build_receipt
from .tseitin import miter


def prove_equivalence(build_a, build_b, inputs: Sequence[str], *,
                      name_a: str = "circuit_a", name_b: str = "circuit_b",
                      seed: int = 1, max_depth: int = 60, refute=None) -> Dict:
    """Build a miter, refute it, and return an EQUIV-1 receipt.

    UNSAT of the miter means the circuits are equivalent; a satisfying assignment
    is a concrete input on which they differ, and is bound into the receipt.

    ``refute`` defaults to the bundled demonstration solver. Pass
    :func:`equiv_receipt.solver.refute` to use an external one — the receipt is
    unchanged in kind, because the solver was never trusted: its proof is
    re-checked here and again by every reader.
    """
    clauses, net = miter(build_a, build_b, inputs)
    cnf_text = to_dimacs(clauses)
    if refute is None:
        res = _bundled_refute(clauses, max_depth=max_depth)
    else:
        res = refute(clauses)

    if res["unsat"]:
        return build_receipt(
            verdict="EQUIVALENT",
            description_a=name_a, description_b=name_b,
            encoder_id="equiv-receipt.tseitin/1",
            cnf_text=cnf_text, drat_text=res["drat"],
            seed=seed,
            meta={"inputs": list(inputs), "n_vars": net.n_vars(),
                  "n_clauses": len(clauses), "n_lemmas": res["n_lemmas"],
                  "solver": res.get("solver", "equiv-receipt.minisolve"),
                  "solver_version": res.get("solver_version", "")},
        )

    model = res["model"] or {}
    cex = {str(net.var(i)): bool(model.get(net.var(i), False)) for i in inputs}
    full = {str(v): bool(model.get(v, False)) for v in range(1, net.n_vars() + 1)}
    return build_receipt(
        verdict="COUNTEREXAMPLE",
        description_a=name_a, description_b=name_b,
        encoder_id="equiv-receipt.tseitin/1",
        cnf_text=cnf_text, drat_text="",
        counterexample=full, seed=seed,
        meta={"inputs": list(inputs), "differing_input_assignment": cex},
    )
