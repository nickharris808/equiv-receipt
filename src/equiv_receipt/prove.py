"""One-call equivalence proving: circuits in, receipt out."""
from __future__ import annotations

from typing import Dict, Sequence

from .dimacs import to_dimacs
from .minisolve import refute
from .receipt import build_receipt
from .tseitin import miter


def prove_equivalence(build_a, build_b, inputs: Sequence[str], *,
                      name_a: str = "circuit_a", name_b: str = "circuit_b",
                      seed: int = 1, max_depth: int = 60) -> Dict:
    """Build a miter, refute it, and return an EQUIV-1 receipt.

    UNSAT of the miter means the circuits are equivalent; a satisfying assignment
    is a concrete input on which they differ, and is bound into the receipt.
    """
    clauses, net = miter(build_a, build_b, inputs)
    cnf_text = to_dimacs(clauses)
    res = refute(clauses, max_depth=max_depth)

    if res["unsat"]:
        return build_receipt(
            verdict="EQUIVALENT",
            description_a=name_a, description_b=name_b,
            encoder_id="equiv-receipt.tseitin/1",
            cnf_text=cnf_text, drat_text=res["drat"],
            seed=seed,
            meta={"inputs": list(inputs), "n_vars": net.n_vars(),
                  "n_clauses": len(clauses), "n_lemmas": res["n_lemmas"]},
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
