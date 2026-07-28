"""The watched-literal engine, RAT checking, and the external-solver adapter.

The load-bearing property throughout: the fast path must agree with the naive
reference, and neither may accept a proof that does not prove anything.
"""
from __future__ import annotations

import itertools
import random
import shutil
import sys

import pytest

import equiv_receipt as E
from equiv_receipt import solver as SV
from equiv_receipt.rup import ClauseDB, _is_rat, bcp, forward_rup_check, parse_drat

HAVE_CADICAL = shutil.which("cadical") is not None
needs_solver = pytest.mark.skipif(not HAVE_CADICAL, reason="no external solver on PATH")


def php(n, m):
    """Pigeonhole: n pigeons into m holes. UNSAT when n > m."""
    def v(p, h):
        return (p - 1) * m + h
    cl = [[v(p, h) for h in range(1, m + 1)] for p in range(1, n + 1)]
    for h in range(1, m + 1):
        for p, q in itertools.combinations(range(1, n + 1), 2):
            cl.append([-v(p, h), -v(q, h)])
    return cl


def random_cnf(rng, n_vars, n_clauses, width=3):
    return [[rng.choice([1, -1]) * rng.randint(1, n_vars) for _ in range(width)]
            for _ in range(n_clauses)]


# ---------------------------------------------------------------- the two engines agree

@pytest.mark.parametrize("seed", range(25))
def test_watched_propagation_agrees_with_the_naive_reference(seed):
    """The fast path has an executable oracle, not a promise."""
    rng = random.Random(seed)
    n_vars = rng.randint(3, 12)
    clauses = random_cnf(rng, n_vars, rng.randint(3, 30), rng.randint(2, 4))
    db = ClauseDB(clauses)
    for _ in range(20):
        assumed = [rng.choice([1, -1]) * rng.randint(1, n_vars)
                   for _ in range(rng.randint(0, 3))]
        naive_conflict, naive_assign = bcp(clauses, assumed)
        fast_conflict, fast_assign = db.propagate(assumed)
        assert naive_conflict == fast_conflict, (clauses, assumed)
        if not naive_conflict:
            # Unit propagation has a unique fixpoint, so the assignments must match
            # exactly — not merely be compatible.
            assert naive_assign == fast_assign, (clauses, assumed)


@pytest.mark.parametrize("seed", range(15))
def test_deletion_is_equivalent_to_removing_the_clause(seed):
    rng = random.Random(1000 + seed)
    clauses = random_cnf(rng, 8, 20)
    db = ClauseDB(clauses)
    victim = clauses[rng.randrange(len(clauses))]
    assert db.delete(victim) is True
    remaining = list(clauses)
    remaining.remove(victim)
    for _ in range(10):
        assumed = [rng.choice([1, -1]) * rng.randint(1, 8)]
        assert bcp(remaining, assumed)[0] == db.propagate(assumed)[0]


def test_deleting_an_absent_clause_is_reported_not_guessed():
    db = ClauseDB([[1, 2], [-1, 3]])
    assert db.delete([4, 5]) is False


def test_deleting_a_duplicate_removes_exactly_one():
    db = ClauseDB([[1, 2], [1, 2], [3]])
    assert db.delete([1, 2]) is True
    assert len(db.live()) == 2
    assert db.delete([1, 2]) is True
    assert len(db.live()) == 1
    assert db.delete([1, 2]) is False


def test_an_empty_clause_in_the_input_is_an_immediate_conflict():
    assert ClauseDB([[]]).propagate([])[0] is True


# ---------------------------------------------------------------- RAT

@needs_solver
def test_a_real_solver_proof_needs_rat_and_is_accepted(tmp_path):
    """The reason RAT is here: without it, real proofs are rejected outright."""
    clauses = php(7, 6)
    r = SV.refute(clauses, SV.known_solver("cadical"))
    assert r["unsat"] and r["proof_checked"]
    chk = forward_rup_check(clauses, r["drat"])
    assert chk["verified"]
    assert chk["n_rat"] > 0, "this instance no longer exercises the RAT path"


@needs_solver
def test_fast_and_naive_rat_agree_on_every_rat_lemma_of_a_real_proof():
    clauses = php(6, 5)
    drat = SV.refute(clauses, SV.known_solver("cadical"))["drat"]

    def naive_rat(active, lits):
        if not lits:
            return False
        pivot = lits[0]
        for d in active:
            if -pivot not in d:
                continue
            resolvent = list(lits) + [x for x in d if x != -pivot]
            if not bcp(active, [-x for x in resolvent])[0]:
                return False
        return True

    db, compared = ClauseDB(clauses), 0
    for op, lits in parse_drat(drat):
        if op == "d":
            db.delete(lits)
            continue
        live = db.live()
        if not bcp(live, [-x for x in lits])[0]:
            assert naive_rat(live, lits) == _is_rat(db, lits)
            compared += 1
        db.add(lits)
    assert compared > 0, "no RAT lemmas in this proof; the test proves nothing"


def test_rat_on_an_empty_clause_is_refused():
    assert _is_rat(ClauseDB([[1], [-1]]), []) is False


# ---------------------------------------------------------------- soundness

def test_the_checker_still_rejects_what_it_should():
    clauses = php(5, 4)
    for label, proof in [
        ("empty", ""),
        ("garbage", "hello world\n"),
        ("bare empty clause", "0\n"),
        ("deletions only", "d 1 0\nd 2 0\n"),
        ("a lemma nothing implies", "1 2 3 4 5 0\n"),
    ]:
        assert forward_rup_check(clauses, proof)["verified"] is False, label


def test_a_satisfiable_formula_cannot_be_refuted():
    assert forward_rup_check([[1, 2], [-1, 2]], "0\n")["verified"] is False
    assert forward_rup_check([[1, 2]], "2 0\n0\n")["verified"] is False


def test_a_refutation_of_a_different_formula_does_not_transfer():
    unsat, other = php(4, 3), [[1, 2], [3]]
    proof = E.refute(unsat, max_depth=40)["drat"]
    assert forward_rup_check(unsat, proof)["verified"] is True
    assert forward_rup_check(other, proof)["verified"] is False


def test_failure_is_located_not_merely_reported():
    """A lemma that is neither RUP nor RAT must name itself.

    `[-1]` over `[[1, 2]]`: the only resolvent on the pivot is `[-1, 2]`, and
    assuming `1, -2` satisfies the single clause rather than conflicting.
    """
    r = forward_rup_check([[1, 2]], "-1 0\n")
    assert r["verified"] is False
    assert r["failed_index"] == 0 and r["failed_lemma"] == [-1]
    assert "RAT" in r["reason"]


def test_a_lemma_that_is_rat_but_not_rup_is_accepted_and_counted():
    """RAT is strictly weaker than RUP, and the count says which path was taken.

    `(1)` over `(1 OR 2)`: no clause contains `-1`, so the RAT condition is
    vacuous and adding it cannot lose a model. It is not RUP — assuming `-1`
    propagates `2` and stops.
    """
    r = forward_rup_check([[1, 2]], "1 0\n")
    assert r["n_rat"] == 1
    assert r["verified"] is False, "one RAT lemma is not a refutation"


# ---------------------------------------------------------------- external solver

def test_a_solver_that_emits_no_proof_is_refused_at_construction():
    with pytest.raises(ValueError, match="proof is the product"):
        SV.Solver("noproof", ["thing", "{cnf}"])
    with pytest.raises(ValueError, match=r"\{cnf\}"):
        SV.Solver("noinput", ["thing", "{drat}"])


def test_a_missing_solver_is_an_error_not_a_verdict():
    s = SV.Solver("nope", ["definitely-not-a-real-solver-xyz", "{cnf}", "{drat}"])
    assert s.available() is False
    with pytest.raises(SV.SolverError, match="not on PATH"):
        s.run("p cnf 1 1\n1 0\n")


def test_a_solver_that_says_nothing_is_an_error_not_a_verdict(tmp_path):
    script = tmp_path / "mute.py"
    script.write_text("import sys; sys.exit(0)\n")
    s = SV.Solver("mute", [sys.executable, str(script), "{cnf}", "{drat}"])
    with pytest.raises(SV.SolverError, match="not a verdict"):
        s.run("p cnf 1 1\n1 0\n")


def test_an_unsat_claim_without_a_proof_is_refused(tmp_path):
    script = tmp_path / "liar.py"
    script.write_text("import sys; print('s UNSATISFIABLE'); sys.exit(20)\n")
    s = SV.Solver("liar", [sys.executable, str(script), "{cnf}", "{drat}"])
    with pytest.raises(SV.SolverError, match="does not package claims"):
        s.run("p cnf 2 2\n1 0\n-1 0\n")


def test_a_binary_proof_is_named_rather_than_mis_parsed(tmp_path):
    script = tmp_path / "bin.py"
    script.write_text(
        "import sys; open(sys.argv[2],'wb').write(b'\\x01\\x00\\x02\\x00');"
        " print('s UNSATISFIABLE'); sys.exit(20)\n")
    s = SV.Solver("bin", [sys.executable, str(script), "{cnf}", "{drat}"])
    with pytest.raises(SV.SolverError, match="BINARY"):
        s.run("p cnf 2 2\n1 0\n-1 0\n")


def test_a_proof_that_does_not_check_withholds_the_verdict(tmp_path):
    script = tmp_path / "bogus.py"
    script.write_text(
        "import sys; open(sys.argv[2],'w').write('1 2 3 4 0\\n');"
        " print('s UNSATISFIABLE'); sys.exit(20)\n")
    s = SV.Solver("bogus", [sys.executable, str(script), "{cnf}", "{drat}"])
    with pytest.raises(SV.SolverError, match="proof does not check"):
        SV.refute(php(4, 3), s)


def test_contradictory_solver_output_is_refused(tmp_path):
    script = tmp_path / "both.py"
    script.write_text(
        "import sys; print('s SATISFIABLE'); print('s UNSATISFIABLE'); sys.exit(0)\n")
    s = SV.Solver("both", [sys.executable, str(script), "{cnf}", "{drat}"])
    with pytest.raises(SV.SolverError, match="both SAT and UNSAT"):
        s.run("p cnf 1 1\n1 0\n")


def test_unknown_named_solver_names_the_alternatives():
    with pytest.raises(ValueError, match="known:"):
        SV.known_solver("no-such-solver")


@needs_solver
def test_external_solver_proves_a_real_equivalence():
    def f(net, p):
        net.AND(p + "t1", "x0", "x1")
        net.AND(p + "t2", "x2", "x3")
        return net.OR(p + "o", p + "t1", p + "t2")

    def g(net, p):
        net.AND(p + "u1", "x2", "x3")
        net.AND(p + "u2", "x1", "x0")
        return net.OR(p + "o", p + "u1", p + "u2")

    clauses, _ = E.miter(f, g, ["x0", "x1", "x2", "x3"])
    r = SV.refute(clauses, SV.known_solver("cadical"))
    assert r["unsat"] and r["proof_checked"] and r["solver"] == "cadical"


@needs_solver
def test_external_solver_reaches_instances_the_bundled_one_cannot():
    """The reason this module exists, asserted rather than asserted-about."""
    clauses = php(10, 9)
    r = SV.refute(clauses, SV.known_solver("cadical"))
    assert r["unsat"] and r["proof_checked"]
    assert r["n_lemmas"] > 1000
    with pytest.raises(Exception):
        E.refute(clauses, max_depth=12)      # bundled solver bails at its depth


@needs_solver
def test_a_receipt_built_from_an_external_proof_verifies_without_the_solver():
    """The trust story: the receipt stands on its own once written."""
    def f(net, p):
        return net.AND(p + "o", "a", "b")

    def g(net, p):
        net.NOT(p + "na", "a")
        net.NOT(p + "nb", "b")
        net.OR(p + "or", p + "na", p + "nb")
        return net.NOT(p + "o", p + "or")

    r = E.prove_equivalence(f, g, ["a", "b"], refute=SV.refute)
    res = E.verify_receipt(r)
    assert res["ok"] and res["verdict"] == "EQUIVALENT"


def test_env_var_selects_the_solver(monkeypatch):
    monkeypatch.setenv("EQUIV_RECEIPT_SOLVER", "/usr/bin/whatever {cnf} {drat}")
    s = SV.detect()
    assert s is not None and s.argv[0] == "/usr/bin/whatever"


def test_detect_returns_none_rather_than_guessing(monkeypatch):
    monkeypatch.delenv("EQUIV_RECEIPT_SOLVER", raising=False)
    monkeypatch.setattr(SV, "KNOWN", {"nope-xyz": ["nope-xyz", "{cnf}", "{drat}"]})
    assert SV.detect() is None


def test_model_parsing_handles_multi_line_v_records():
    m = SV._parse_model("s SATISFIABLE\nv 1 -2 3\nv -4 0\n")
    assert m == {1: True, 2: False, 3: True, 4: False}
