"""Adversarial regression suite for equiv-receipt.

Oracle: NO INPUT MAY PRODUCE A CONFIDENT-LOOKING ANSWER THAT IS WRONG.
A checker may say verified, may say refuted, may say "malformed". It may never
say verified about something it did not check.
"""
from __future__ import annotations


import pytest

import equiv_receipt as E
from equiv_receipt.dimacs import CNFParseError
from equiv_receipt.rup import MalformedProof, parse_drat

UNSAT = [[1, 2], [-1, 2], [1, -2], [-1, -2]]


# ---------------------------------------------------------------- malformed proofs

@pytest.mark.parametrize("drat", ["garbage\n", "\x00\x01", "1 x 0\n", "a b c\n", "d z 0\n"])
def test_malformed_drat_is_rejected_not_raised(drat):
    r = E.forward_rup_check(UNSAT, drat)
    assert r["verified"] is False
    assert "malformed" in r["reason"]


def test_strict_parse_drat_still_raises_for_callers_that_want_it():
    with pytest.raises(MalformedProof):
        parse_drat("garbage\n")


@pytest.mark.parametrize("drat", ["", "c only a comment\n", "\n\n"])
def test_empty_proof_never_verifies(drat):
    assert E.forward_rup_check(UNSAT, drat)["verified"] is False


def test_proof_of_a_satisfiable_formula_never_verifies():
    assert E.forward_rup_check([[1, 2]], "0\n")["verified"] is False


def test_non_rup_lemma_is_rejected_with_a_location():
    r = E.forward_rup_check([[1, 2]], "1 0\n0\n")
    assert r["verified"] is False and r["failed_index"] == 0


# ---------------------------------------------------------------- malformed CNF

@pytest.mark.parametrize("cnf", [
    "p cnf abc\n", "p cnf 1\n", "p dnf 1 1\n", "1 2\n", "not a cnf\n", "p cnf 1 1\n1 2\n",
])
def test_malformed_cnf_raises_rather_than_silently_mis_parsing(cnf):
    with pytest.raises(CNFParseError):
        E.parse_dimacs(cnf)


def test_lenient_mode_is_an_explicit_opt_in():
    assert E.parse_dimacs("1 2\n", strict=False) == [] or True  # does not raise


def test_wellformed_cnf_round_trips():
    cl = [[1, -2, 3], [-1, 2], [3]]
    assert E.parse_dimacs(E.to_dimacs(cl)) == cl


# ---------------------------------------------------------------- receipts

def _f(n, p):
    return n.AND(p + "and", "a", "b")


def _g(n, p):
    n.NOT(p + "na", "a")
    n.NOT(p + "nb", "b")
    n.OR(p + "or", p + "na", p + "nb")
    return n.NOT(p + "out", p + "or")


def _h(n, p):
    return n.OR(p + "or", "a", "b")


def test_receipt_with_malformed_formula_is_rejected_not_crashed():
    r = E.prove_equivalence(_f, _g, ["a", "b"])
    r["payload"]["cnf"] = "p cnf abc\n"
    res = E.verify_receipt(r)
    assert res["ok"] is False
    assert any("malformed" in e for e in res["errors"])


def test_receipt_with_malformed_proof_is_rejected():
    r = E.prove_equivalence(_f, _g, ["a", "b"])
    r["payload"]["drat"] = "garbage\n"
    assert E.verify_receipt(r)["ok"] is False


@pytest.mark.parametrize("mutate", [
    lambda r: r.update(format="equiv-receipt/99"),
    lambda r: r.update(records=[]),
    lambda r: r.update(payload={}),
    lambda r: r["payload"].update(cnf=""),
    lambda r: r["payload"].update(drat=""),
    lambda r: r["payload"].update(encoder_id="untrusted/9"),
    lambda r: r["payload"].update(description_a="something else"),
])
def test_tampered_receipts_never_verify(mutate):
    r = E.prove_equivalence(_f, _g, ["a", "b"])
    mutate(r)
    assert E.verify_receipt(r)["ok"] is False


def test_forged_equivalent_verdict_on_differing_circuits():
    r = E.prove_equivalence(_f, _h, ["a", "b"])
    for rec in r["records"]:
        if rec.get("kind") == "verdict":
            rec["verdict"] = "EQUIVALENT"
    assert E.verify_receipt(r)["ok"] is False


# ---------------------------------------------------------------- OOD / enormous

def test_solver_refuses_beyond_declared_depth_rather_than_grinding():
    with pytest.raises(RecursionError):
        E.refute(UNSAT, max_depth=0)


def test_single_input_circuits():
    r = E.prove_equivalence(lambda n, p: n.NOT(p + "y", "a"),
                            lambda n, p: n.NOT(p + "z", "a"), ["a"])
    assert E.verify_receipt(r)["verdict"] == "EQUIVALENT"


def test_large_cnf_parses_without_blowup():
    cl = [[i, -(i + 1)] for i in range(1, 5000)]
    assert len(E.parse_dimacs(E.to_dimacs(cl))) == len(cl)


def test_deeply_repeated_clauses():
    cl = [[1, 2]] * 5000
    assert E.forward_rup_check(cl, "0\n")["verified"] is False
