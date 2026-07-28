"""Tests for equiv-receipt.

The soundness tests are the load-bearing ones: a checker that accepts everything
passes every happy-path test too.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

import equiv_receipt as E


# ---------- circuits used across the suite ----------

def and_gate(n, p):
    return n.AND(p + "and", "a", "b")


def demorgan(n, p):
    n.NOT(p + "na", "a")
    n.NOT(p + "nb", "b")
    n.OR(p + "or", p + "na", p + "nb")
    return n.NOT(p + "out", p + "or")


def or_gate(n, p):
    return n.OR(p + "or", "a", "b")


def xor_direct(n, p):
    return n.XOR(p + "x", "a", "b")


def xor_expanded(n, p):
    # (a OR b) AND NOT(a AND b)
    n.OR(p + "o", "a", "b")
    n.AND(p + "ab", "a", "b")
    n.NOT(p + "nab", p + "ab")
    return n.AND(p + "out", p + "o", p + "nab")


# ---------- RUP checker ----------

UNSAT_CLAUSES = [[1, 2], [-1, 2], [1, -2], [-1, -2]]
GOOD_DRAT = "2 0\n0\n"


def test_rup_accepts_a_valid_refutation():
    r = E.forward_rup_check(UNSAT_CLAUSES, GOOD_DRAT)
    assert r["verified"] is True
    assert r["n_lemmas"] == 2


def test_rup_rejects_a_non_rup_lemma():
    """The central soundness property: an unjustified lemma must be refused.

    Base formula ``(1 OR 2)`` is satisfiable. Asserting the unit ``(1)`` does not
    follow: negating it assumes ``-1``, which propagates ``2`` and stops without
    a conflict. So the lemma is not RUP and must be rejected.
    """
    r = E.forward_rup_check([[1, 2]], "1 0\n0\n")
    assert r["verified"] is False
    assert r["failed_lemma"] == [1]
    assert r["failed_index"] == 0
    assert "not RUP" in r["reason"]


def test_rup_rejects_an_empty_proof():
    assert E.forward_rup_check(UNSAT_CLAUSES, "")["verified"] is False


def test_rup_rejects_proof_of_a_satisfiable_formula():
    sat = [[1, 2], [-1, 2]]
    assert E.forward_rup_check(sat, "0\n")["verified"] is False


def test_rup_handles_deletions():
    r = E.forward_rup_check(UNSAT_CLAUSES, "2 0\nd 1 2 0\n0\n")
    assert r["verified"] is True


def test_bcp_detects_direct_contradiction():
    conflict, _ = E.bcp([[1], [-1]], [])
    assert conflict is True


# ---------- solver + checker agree ----------

@pytest.mark.parametrize("a,b,expect", [
    (and_gate, demorgan, True),
    (xor_direct, xor_expanded, True),
    (and_gate, or_gate, False),
    (and_gate, xor_direct, False),
])
def test_solver_verdicts_are_correct(a, b, expect):
    clauses, _ = E.miter(a, b, ["a", "b"])
    res = E.refute(clauses)
    assert res["unsat"] is expect


def test_emitted_drat_passes_the_independent_checker():
    """Every lemma the solver emits must be RUP — checked, not assumed."""
    clauses, _ = E.miter(xor_direct, xor_expanded, ["a", "b"])
    res = E.refute(clauses)
    assert res["unsat"]
    chk = E.forward_rup_check(clauses, res["drat"])
    assert chk["verified"] is True
    assert chk["n_lemmas"] == res["n_lemmas"]


def test_counterexample_actually_satisfies_the_miter():
    clauses, net = E.miter(and_gate, or_gate, ["a", "b"])
    res = E.refute(clauses)
    assert not res["unsat"]
    model = res["model"]
    for cl in clauses:
        assert any(model.get(abs(lit), False) == (lit > 0) for lit in cl)


# ---------- receipts ----------

def _receipt(a=and_gate, b=demorgan):
    return E.prove_equivalence(a, b, ["a", "b"], name_a="A", name_b="B")


def test_receipt_roundtrip_equivalent():
    res = E.verify_receipt(_receipt())
    assert res["ok"] is True and res["verdict"] == "EQUIVALENT"


def test_receipt_roundtrip_counterexample():
    res = E.verify_receipt(_receipt(and_gate, or_gate))
    assert res["ok"] is True and res["verdict"] == "COUNTEREXAMPLE"


def test_forged_verdict_is_caught():
    """A receipt claiming EQUIVALENT with no valid proof must fail."""
    r = _receipt(and_gate, or_gate)                 # genuinely different
    for rec in r["records"]:
        if rec.get("kind") == "verdict":
            rec["verdict"] = "EQUIVALENT"           # lie
    res = E.verify_receipt(r)
    assert res["ok"] is False


def test_tampered_cnf_is_caught():
    r = _receipt()
    r["payload"]["cnf"] = r["payload"]["cnf"].replace("p cnf", "p cnf ")
    res = E.verify_receipt(r)
    assert res["ok"] is False
    assert any("committed digest" in e or "merkle" in e for e in res["errors"])


def test_tampered_drat_is_caught():
    r = _receipt()
    r["payload"]["drat"] = "1 0\n0\n"
    res = E.verify_receipt(r)
    assert res["ok"] is False


def test_broken_chain_is_caught():
    r = _receipt()
    r["records"][1]["prev"] = "ff" * 32
    res = E.verify_receipt(r)
    assert res["ok"] is False
    assert any("chain" in e for e in res["errors"])


def test_swapped_description_is_caught():
    """The receipt binds the circuit descriptions, not just the formula."""
    r = _receipt()
    r["payload"]["description_a"] = "some other circuit entirely"
    res = E.verify_receipt(r)
    assert res["ok"] is False


def test_swapped_encoder_id_is_caught():
    r = _receipt()
    r["payload"]["encoder_id"] = "untrusted-encoder/9"
    res = E.verify_receipt(r)
    assert res["ok"] is False


def test_forged_counterexample_is_caught():
    r = _receipt(and_gate, or_gate)
    for rec in r["records"]:
        if rec.get("kind") == "verdict":
            rec["counterexample"] = {"1": False, "2": False}   # does not satisfy the miter
    res = E.verify_receipt(r)
    assert res["ok"] is False


def test_receipt_file_roundtrip(tmp_path):
    p = E.write_receipt(tmp_path / "r.json", _receipt())
    assert E.verify_receipt(E.read_receipt(p))["ok"] is True


def test_unknown_format_rejected():
    r = _receipt()
    r["format"] = "equiv-receipt/99"
    assert E.verify_receipt(r)["ok"] is False


# ---------- dimacs ----------

def test_dimacs_roundtrip():
    clauses = [[1, -2, 3], [-1, 2], [3]]
    assert E.parse_dimacs(E.to_dimacs(clauses)) == clauses


def test_dimacs_header_is_correct():
    text = E.to_dimacs([[1, -2], [3]])
    assert text.splitlines()[0] == "p cnf 3 2"


# ---------- solver scope is honest ----------

def test_solver_refuses_beyond_its_declared_depth():
    """The small-instance limit must be enforced, not merely documented.

    ``UNSAT_CLAUSES`` has no unit clauses, so the search must make at least one
    decision; with ``max_depth=0`` that decision exceeds the budget.
    """
    with pytest.raises(RecursionError):
        E.refute(UNSAT_CLAUSES, max_depth=0)


# ---------- CLI ----------

def _env():
    return {"PYTHONPATH": str(Path(__file__).parent.parent / "src"), "PATH": ""}


def test_cli_demo_runs():
    r = subprocess.run([sys.executable, "-m", "equiv_receipt.cli", "demo"],
                       capture_output=True, text=True, env=_env())
    assert r.returncode == 0, r.stderr
    assert "EQUIVALENT" in r.stdout


def test_cli_verify_and_reject(tmp_path):
    good = tmp_path / "good.json"
    E.write_receipt(good, _receipt())
    r = subprocess.run([sys.executable, "-m", "equiv_receipt.cli", "verify", str(good)],
                       capture_output=True, text=True, env=_env())
    assert r.returncode == 0, r.stderr

    bad_receipt = _receipt()
    bad_receipt["payload"]["drat"] = "1 0\n0\n"
    bad = tmp_path / "bad.json"
    E.write_receipt(bad, bad_receipt)
    r = subprocess.run([sys.executable, "-m", "equiv_receipt.cli", "verify", str(bad)],
                       capture_output=True, text=True, env=_env())
    assert r.returncode == 1


def test_cli_check_drat(tmp_path):
    cnf = tmp_path / "f.cnf"
    drat = tmp_path / "f.drat"
    cnf.write_text(E.to_dimacs(UNSAT_CLAUSES))
    drat.write_text(GOOD_DRAT)
    r = subprocess.run([sys.executable, "-m", "equiv_receipt.cli", "check-drat",
                        str(cnf), str(drat)], capture_output=True, text=True, env=_env())
    assert r.returncode == 0 and "VERIFIED" in r.stdout

    # a proof that does not follow: assert the empty clause over a satisfiable formula
    cnf.write_text(E.to_dimacs([[1, 2]]))
    drat.write_text("0\n")
    r = subprocess.run([sys.executable, "-m", "equiv_receipt.cli", "check-drat",
                        str(cnf), str(drat)], capture_output=True, text=True, env=_env())
    assert r.returncode == 1
    assert "NOT VERIFIED" in r.stderr


def test_no_third_party_imports():
    """Standard library only — the property that makes the checker auditable."""
    import ast
    src_dir = Path(E.__file__).parent
    allowed = {"hashlib", "hmac", "json", "pathlib", "typing", "sys", "argparse",
               "equiv_receipt", "__future__", "os"}
    for py in src_dir.glob("*.py"):
        tree = ast.parse(py.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for n in node.names:
                    assert n.name.split(".")[0] in allowed, f"{py.name}: {n.name}"
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                assert node.module.split(".")[0] in allowed, f"{py.name}: {node.module}"


# ---------- README fidelity ----------

def test_readme_demo_output_matches_cli():
    """The block the README shows for `equiv-receipt demo` must be what it prints."""
    readme = (Path(__file__).parent.parent / "README.md").read_text()
    r = subprocess.run([sys.executable, "-m", "equiv_receipt.cli", "demo"],
                       capture_output=True, text=True, env=_env())
    assert r.returncode == 0
    for line in r.stdout.strip().splitlines():
        assert line.strip() in readme, f"README does not show actual demo line: {line!r}"


def test_readme_claims_no_specific_lemma_counts_it_cannot_back():
    """Guard against re-introducing a fabricated benchmark number."""
    readme = (Path(__file__).parent.parent / "README.md").read_text()
    import re
    # any 'N lemmas' claim in the README must be one the demo actually produces
    for n in re.findall(r"(\d+)\s+lemmas", readme):
        assert n == "3", f"README claims {n} lemmas; the only reproducible figure is 3"
