"""The adversarial suite for equiv-receipt.

Oracle: no input may produce a confident-looking answer that is wrong. A rejection
is fine; a crash is not, because it tells the caller nothing; an acceptance of
something unproven is a defect.

Concentrated on the surfaces added most recently — the watched-literal engine,
RAT, the sequential receipt and its re-encoding check, and the export formats.
"""
from __future__ import annotations

import copy
import json
import random
from xml.etree import ElementTree as ET

import pytest

import equiv_receipt as E
from equiv_receipt import seq
from equiv_receipt.report import EMITTERS, emit, verdict_meta
from equiv_receipt.rup import ClauseDB, bcp, forward_rup_check, parse_drat

SUCCESS = {"EQUIVALENT"}
ALL_VERDICTS = {"EQUIVALENT", "COUNTEREXAMPLE", "UNDECIDED-AT-K"}

COUNTER_A = {
    "inputs": ["en"],
    "latches": [{"name": "s0", "next": "n0", "init": 0}],
    "gates": [{"op": "XOR", "out": "n0", "args": ["s0", "en"]},
              {"op": "BUF", "out": "o", "args": ["s0"]}],
    "outputs": ["o"],
}
COUNTER_B = {
    "inputs": ["en"],
    "latches": [{"name": "t0", "next": "m0", "init": 0}],
    "gates": [{"op": "XOR", "out": "m0", "args": ["en", "t0"]},
              {"op": "NOT", "out": "nt", "args": ["t0"]},
              {"op": "NOT", "out": "o2", "args": ["nt"]}],
    "outputs": ["o2"],
}


# ============================================================ 1. MALFORMED

MALFORMED_DRAT = [
    "", "   ", "\n\n\n", "hello world", "1 2", "1 2 3", "d", "d 0",
    "1 2 0\ngarbage\n", "\x00\x01\x02", "1e5 0", "1.5 0", "0x10 0",
    "999999999999999999999999 0", "-0 0", "c comment only\n",
    "1 " * 100_000 + "0\n",
]


@pytest.mark.parametrize("proof", MALFORMED_DRAT,
                         ids=[repr(p)[:24] for p in MALFORMED_DRAT])
def test_malformed_proofs_are_rejected_not_raised(proof):
    r = forward_rup_check([[1, 2], [-1, 2]], proof)     # must not raise
    assert r["verified"] is False
    assert r.get("reason")


MALFORMED_CNF = [
    "", "p cnf", "p cnf abc def", "p cnf 1", "p dnf 1 1", "1 2\n",
    "p cnf 1 1\n1 2\n", "p cnf 1 1\nx 0\n", "p cnf -1 -1\n", "\x00",
    "p cnf 1 1\n1 0\nextra 0\n",
]


@pytest.mark.parametrize("cnf", MALFORMED_CNF, ids=[repr(c)[:24] for c in MALFORMED_CNF])
def test_malformed_cnf_raises_a_named_error_rather_than_mis_parsing(cnf):
    from equiv_receipt.receipt import CNFParseError
    with pytest.raises(CNFParseError):
        E.parse_dimacs(cnf)


MALFORMED_RECEIPTS = [
    ("not a dict", []),
    ("empty", {}),
    ("unknown format", {"format": "other/1"}),
    ("no records", {"format": E.FORMAT, "records": [], "payload": {}}),
    ("records not a list", {"format": E.FORMAT, "records": 5, "payload": {}}),
    ("payload not a dict", {"format": E.FORMAT, "records": [], "payload": 5}),
    ("cnf not a string", {"format": E.FORMAT, "records": [], "payload": {"cnf": 5}}),
    ("seed not a number", {"format": E.FORMAT, "seed": "x", "records": [],
                           "payload": {"cnf": "", "drat": ""}}),
]


@pytest.mark.parametrize("label,receipt", MALFORMED_RECEIPTS,
                         ids=[m[0] for m in MALFORMED_RECEIPTS])
def test_malformed_receipts_never_verify_and_never_crash(label, receipt):
    res = E.verify_receipt(receipt)                     # must not raise
    assert res["ok"] is False, label
    assert res.get("verdict") not in SUCCESS, label


@pytest.mark.parametrize("label,receipt", MALFORMED_RECEIPTS,
                         ids=[m[0] for m in MALFORMED_RECEIPTS])
def test_malformed_sequential_receipts_never_verify_and_never_crash(label, receipt):
    res = seq.verify_seq_receipt(receipt if isinstance(receipt, dict) else {})
    assert res["ok"] is False, label
    assert res.get("verdict") not in SUCCESS, label


# ============================================================ 2. EMPTY / DEGENERATE

def test_an_empty_formula_cannot_be_refuted_by_an_empty_proof():
    assert forward_rup_check([], "")["verified"] is False


def test_a_formula_that_is_already_refuted_needs_no_lemmas():
    """`[[]]` contains the empty clause, so it propagates to a conflict."""
    assert forward_rup_check([[]], "")["verified"] is True


def test_an_empty_clause_database_propagates_nothing():
    assert ClauseDB([]).propagate([])[0] is False


def test_a_design_with_no_latches_is_combinational_and_still_handled():
    a = {"inputs": ["x"], "latches": [],
         "gates": [{"op": "NOT", "out": "o", "args": ["x"]}], "outputs": ["o"]}
    b = {"inputs": ["x"], "latches": [],
         "gates": [{"op": "NOT", "out": "n", "args": ["x"]},
                   {"op": "BUF", "out": "o2", "args": ["n"]}], "outputs": ["o2"]}
    r = seq.prove_sequential_equivalence(a, b, k=1)
    assert seq.verify_seq_receipt(r)["verdict"] in ALL_VERDICTS


# ============================================================ 3. ENORMOUS

def test_a_long_proof_of_a_trivial_formula_terminates():
    clauses = [[1], [-1]]
    proof = "\n".join("2 0" for _ in range(20_000)) + "\n0\n"
    assert forward_rup_check(clauses, proof)["verified"] is True


def test_a_wide_clause_does_not_break_propagation():
    wide = list(range(1, 2001))
    db = ClauseDB([wide, [-1]])
    assert db.propagate([])[0] is False
    assert bcp([wide, [-1]], [])[0] is False


def test_many_deletions_of_absent_clauses_are_harmless():
    db = ClauseDB([[1, 2]])
    for i in range(5_000):
        # offset so none of these is the clause actually in the database
        assert db.delete([1000 + i, 1001 + i]) is False
    assert db.delete([1, 2]) is True, "the real clause is still there"


# ============================================================ 4. OUT OF DISTRIBUTION

@pytest.mark.parametrize("seed", range(30))
def test_random_proofs_are_almost_never_accepted_and_never_crash(seed):
    """Fuzzing the proof against a fixed formula. The oracle is soundness."""
    rng = random.Random(seed)
    clauses = [[1, 2], [-1, 3], [-2, -3]]          # satisfiable
    lines = []
    for _ in range(rng.randint(1, 20)):
        lits = [rng.choice([1, -1]) * rng.randint(1, 4)
                for _ in range(rng.randint(0, 4))]
        prefix = "d " if rng.random() < 0.3 else ""
        lines.append(prefix + " ".join(map(str, lits)) + " 0")
    r = forward_rup_check(clauses, "\n".join(lines))    # must not raise
    if r["verified"]:
        # Only legitimate if the formula really is refuted by that proof; check
        # with the naive reference, which shares no code with the fast path.
        db = ClauseDB(clauses)
        for op, lits in parse_drat("\n".join(lines)):
            if op == "d":
                db.delete(lits)
            else:
                db.add(lits)
        assert bcp(db.live(), [])[0], "accepted a proof that does not refute"


@pytest.mark.parametrize("lit", [0, 2**31, -(2**31), 2**63, 10**30])
def test_extreme_literals_do_not_break_the_engine(lit):
    if lit == 0:
        pytest.skip("0 terminates a clause and cannot be a literal")
    db = ClauseDB([[lit], [-lit]])
    assert db.propagate([])[0] is True


def test_a_tautological_clause_is_handled():
    db = ClauseDB([[1, -1]])
    assert db.propagate([])[0] is False
    assert db.propagate([1])[0] is False


def test_duplicate_literals_in_a_clause():
    db = ClauseDB([[1, 1, 1], [-1]])
    assert db.propagate([])[0] is True


# ============================================================ 5. DIFFERENTIAL

@pytest.mark.parametrize("seed", range(40))
def test_the_two_engines_agree_on_random_instances(seed):
    """The fast path has an executable oracle, not a promise."""
    rng = random.Random(10_000 + seed)
    n_vars = rng.randint(2, 10)
    clauses = [[rng.choice([1, -1]) * rng.randint(1, n_vars)
                for _ in range(rng.randint(1, 4))]
               for _ in range(rng.randint(1, 25))]
    db = ClauseDB(clauses)
    for _ in range(15):
        assumed = [rng.choice([1, -1]) * rng.randint(1, n_vars)
                   for _ in range(rng.randint(0, 3))]
        n_conf, n_assign = bcp(clauses, assumed)
        f_conf, f_assign = db.propagate(assumed)
        assert n_conf == f_conf, (clauses, assumed)
        if not n_conf:
            assert n_assign == f_assign, (clauses, assumed)


def test_every_export_format_preserves_the_verdict():
    for verdict in sorted(ALL_VERDICTS) + ["SOMETHING_NEW", "", None]:
        ok, _level, _summary = verdict_meta(verdict)
        expected = verdict in SUCCESS
        assert ok is expected, verdict
        res = {"verdict": verdict, "ok": expected, "errors": ["x"], "detail": {}}
        for fmt in EMITTERS:
            out = emit(res, fmt)
            assert out.strip(), (verdict, fmt)
        sarif = json.loads(emit(res, "sarif"))
        assert sarif["runs"][0]["invocations"][0]["executionSuccessful"] is expected
        x = ET.fromstring(emit(res, "junit"))
        assert (x.get("failures") == "0") is expected
        if not expected and verdict:
            assert verdict in json.dumps(sarif), verdict


def test_the_abstention_is_never_a_pass_in_any_format():
    res = {"verdict": seq.UNDECIDED, "ok": True, "errors": [], "detail": {}}
    assert json.loads(emit(res, "sarif"))["runs"][0]["invocations"][0][
        "executionSuccessful"] is False
    assert ET.fromstring(emit(res, "junit")).get("failures") == "1"
    assert "ABSTAINED" in emit(res, "junit")


# ============================================================ 6. THE SEQUENTIAL RECEIPT

@pytest.fixture(scope="module")
def proved():
    return seq.prove_sequential_equivalence(COUNTER_A, COUNTER_B, k=1)


MUTATIONS = [
    ("verdict flipped", lambda r: [rec.update(verdict="COUNTEREXAMPLE")
                                   for rec in r["records"] if rec.get("kind") == "verdict"]),
    ("design edited", lambda r: r["payload"]["design_a"].update(outputs=["s0"])),
    ("proof dropped", lambda r: r["payload"]["obligations"][-1].update(drat="")),
    ("proof truncated", lambda r: r["payload"]["obligations"][-1].update(
        drat=r["payload"]["obligations"][-1]["drat"][:20])),
    ("cnf swapped", lambda r: r["payload"]["obligations"][0].update(
        cnf=r["payload"]["obligations"][-1]["cnf"])),
    ("obligation removed", lambda r: r["payload"]["obligations"].pop()),
    ("obligation duplicated", lambda r: r["payload"]["obligations"].append(
        copy.deepcopy(r["payload"]["obligations"][0]))),
    ("chain link broken", lambda r: r["records"][1].update(name_a="something else")),
    ("k changed", lambda r: r.update(k=9)),
    ("format changed", lambda r: r.update(format="other/1")),
    ("obligations not a list", lambda r: r["payload"].update(obligations={})),
    ("obligation not an object", lambda r: r["payload"]["obligations"].__setitem__(0, 5)),
]


@pytest.mark.parametrize("label,mutate", MUTATIONS, ids=[m[0] for m in MUTATIONS])
def test_no_mutation_of_a_sequential_receipt_still_verifies(proved, label, mutate):
    r = copy.deepcopy(proved)
    mutate(r)
    res = seq.verify_seq_receipt(r)                    # must not raise
    assert res["ok"] is False, label
    assert res["errors"], label


@pytest.mark.parametrize("kind", ["base", "step", "rc-base", "rc-step", "rc-out"])
def test_re_encoding_is_deterministic(kind):
    """Byte-identical re-encoding is what lets a third party check the formula."""
    a = seq.build_obligation(COUNTER_A, COUNTER_B, 2, kind=kind)
    b = seq.build_obligation(COUNTER_A, COUNTER_B, 2, kind=kind)
    assert a == b


@pytest.mark.parametrize("bad", [
    {}, {"inputs": []}, {"inputs": [], "latches": [], "gates": [], "outputs": []},
    {"inputs": "x", "latches": [], "gates": [], "outputs": ["a"]},
    {"inputs": ["a", "a"], "latches": [], "gates": [], "outputs": ["a"]},
])
def test_malformed_designs_are_refused_with_a_reason(bad):
    with pytest.raises(seq.DesignError):
        seq.validate_design(bad)


def test_a_design_cycle_is_refused():
    cyclic = {"inputs": ["x"], "latches": [],
              "gates": [{"op": "AND", "out": "a", "args": ["b", "x"]},
                        {"op": "AND", "out": "b", "args": ["a", "x"]}],
              "outputs": ["a"]}
    with pytest.raises(seq.DesignError, match="topological"):
        seq.validate_design(cyclic)


# ============================================================ 7. THE SOLVER ADAPTER

@pytest.mark.parametrize("argv", [
    ["x"], ["x", "{cnf}"], ["x", "{drat}"], [],
])
def test_a_solver_template_without_both_placeholders_is_refused(argv):
    from equiv_receipt import solver as SV
    with pytest.raises((ValueError, IndexError)):
        SV.Solver("bad", argv)


def test_an_unknown_solver_name_lists_the_known_ones():
    from equiv_receipt import solver as SV
    with pytest.raises(ValueError, match="known:"):
        SV.known_solver("nope-xyz")


@pytest.mark.parametrize("stdout,exit_code,expect", [
    ("", 0, "not a verdict"),
    ("s SATISFIABLE\ns UNSATISFIABLE", 0, "both SAT and UNSAT"),
])
def test_ambiguous_solver_output_is_an_error_not_a_verdict(tmp_path, stdout, exit_code,
                                                           expect):
    import sys

    from equiv_receipt import solver as SV
    script = tmp_path / "s.py"
    script.write_text(f"import sys\nprint({stdout!r})\nsys.exit({exit_code})\n")
    s = SV.Solver("t", [sys.executable, str(script), "{cnf}", "{drat}"])
    with pytest.raises(SV.SolverError, match=expect):
        s.run("p cnf 1 1\n1 0\n")


# ============================================================ 8. NO STATE LEAKS

def test_checking_the_same_proof_twice_gives_the_same_answer():
    clauses = [[1, 2], [-1, 2], [1, -2], [-1, -2]]
    proof = E.refute(clauses, max_depth=20)["drat"]
    first = forward_rup_check(clauses, proof)
    second = forward_rup_check(clauses, proof)
    assert first == second


def test_a_clause_database_is_not_shared_between_checks():
    a = forward_rup_check([[1], [-1]], "0\n")
    b = forward_rup_check([[1, 2]], "0\n")
    assert a["verified"] is True and b["verified"] is False
    assert forward_rup_check([[1], [-1]], "0\n") == a


def test_the_input_clause_list_is_not_mutated():
    """The watched-literal engine reorders literals; it must copy first."""
    clauses = [[1, 2, 3], [-1, -2]]
    before = copy.deepcopy(clauses)
    forward_rup_check(clauses, "1 2 0\n")
    assert clauses == before, "the caller's clauses were reordered in place"


def test_a_receipt_is_not_mutated_by_verification(proved):
    before = json.dumps(proved, sort_keys=True)
    seq.verify_seq_receipt(proved)
    assert json.dumps(proved, sort_keys=True) == before


@pytest.mark.parametrize("n", [1, 2, 3])
def test_repeated_proving_is_deterministic(n):
    r1 = seq.prove_sequential_equivalence(COUNTER_A, COUNTER_B, k=n)
    r2 = seq.prove_sequential_equivalence(COUNTER_A, COUNTER_B, k=n)
    assert json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True)
