"""Sequential equivalence: the argument, the abstention, and the encoder gap.

The property that distinguishes a sequential receipt from a combinational one:
the verifier re-encodes every obligation from the committed design, so a receipt
carrying a valid proof of the *wrong problem* is caught.
"""
from __future__ import annotations

import copy
import json
import shutil

import pytest

from equiv_receipt import seq
from equiv_receipt import solver as SV

HAVE_CADICAL = shutil.which("cadical") is not None
needs_solver = pytest.mark.skipif(not HAVE_CADICAL, reason="no external solver on PATH")


def _refute(clauses):
    if HAVE_CADICAL:
        return SV.refute(clauses, SV.known_solver("cadical"))
    from equiv_receipt.minisolve import refute
    return refute(clauses, max_depth=40)


# --- a 2-bit counter, and the same counter written differently -----------------

COUNTER_A = {
    "inputs": ["en"],
    "latches": [{"name": "s0", "next": "n0", "init": 0},
                {"name": "s1", "next": "n1", "init": 0}],
    "gates": [{"op": "XOR", "out": "n0", "args": ["s0", "en"]},
              {"op": "AND", "out": "c", "args": ["s0", "en"]},
              {"op": "XOR", "out": "n1", "args": ["s1", "c"]},
              {"op": "OR", "out": "o", "args": ["s0", "s1"]}],
    "outputs": ["o"],
}
COUNTER_B = {
    "inputs": ["en"],
    "latches": [{"name": "t0", "next": "m0", "init": 0},
                {"name": "t1", "next": "m1", "init": 0}],
    "gates": [{"op": "XOR", "out": "m0", "args": ["en", "t0"]},
              {"op": "AND", "out": "cc", "args": ["en", "t0"]},
              {"op": "XOR", "out": "m1", "args": ["cc", "t1"]},
              {"op": "NOT", "out": "ns0", "args": ["t0"]},
              {"op": "NOT", "out": "ns1", "args": ["t1"]},
              {"op": "AND", "out": "z", "args": ["ns0", "ns1"]},
              {"op": "NOT", "out": "o2", "args": ["z"]}],
    "outputs": ["o2"],
}


@pytest.fixture(scope="module")
def proved():
    return seq.prove_sequential_equivalence(COUNTER_A, COUNTER_B, k=1, refute=_refute)


# ---------------------------------------------------------------- the happy path

def test_equivalent_counters_are_proved_and_re_derived(proved):
    res = seq.verify_seq_receipt(proved)
    assert res["ok"] and res["verdict"] == seq.EQUIVALENT
    assert res["method"] == "register-correspondence"
    assert res["detail"]["register_correspondence"] == ["rc-base", "rc-out", "rc-step"]


def test_every_obligation_carries_a_proof(proved):
    for o in proved["payload"]["obligations"]:
        assert o["unsat"] and o["drat"].strip(), o["kind"]


def test_a_receipt_round_trips_through_a_file(tmp_path, proved):
    p = seq.write_seq_receipt(tmp_path / "r.json", proved)
    assert seq.verify_seq_receipt(seq.read_seq_receipt(p))["verdict"] == seq.EQUIVALENT


# ---------------------------------------------------------------- the abstention

def test_output_only_k_induction_abstains_rather_than_guessing():
    """Two independent state encodings: the step case cannot close, so abstain."""
    cl = seq.build_obligation(COUNTER_A, COUNTER_B, 1, kind="step")
    assert _refute(cl)["unsat"] is False, "this pair no longer exercises the abstention"

    receipt = seq.build_seq_receipt(
        verdict=seq.UNDECIDED, design_a=COUNTER_A, design_b=COUNTER_B, k=1,
        obligations=[o for o in
                     seq.prove_sequential_equivalence(
                         COUNTER_A, COUNTER_B, k=1, refute=_refute)["payload"]["obligations"]
                     if o["kind"] == "base"],
        method="k-induction")
    res = seq.verify_seq_receipt(receipt)
    assert res["verdict"] == seq.UNDECIDED
    assert res["ok"], "an abstention is a well-formed outcome, not an error"


def test_undecided_is_not_reported_as_either_outcome():
    assert seq.UNDECIDED not in (seq.EQUIVALENT, seq.COUNTEREXAMPLE)
    assert "UNDECIDED" in seq.UNDECIDED


# ---------------------------------------------------------------- counterexamples

def test_a_genuine_difference_is_found_with_a_replayable_witness():
    bad = copy.deepcopy(COUNTER_B)
    bad["outputs"] = ["t0"]                       # drops the s1 term
    r = seq.prove_sequential_equivalence(COUNTER_A, bad, k=3, refute=_refute)
    res = seq.verify_seq_receipt(r)
    assert res["verdict"] == seq.COUNTEREXAMPLE and res["ok"]


def test_a_fabricated_counterexample_is_refused():
    bad = copy.deepcopy(COUNTER_B)
    bad["outputs"] = ["t0"]
    r = seq.prove_sequential_equivalence(COUNTER_A, bad, k=3, refute=_refute)
    r["payload"]["obligations"] = r["payload"]["obligations"]     # unchanged
    victim = r["records"][-1]
    victim["counterexample"] = {"time": 0, "assignment": {"1": True, "2": True}}
    res = seq.verify_seq_receipt(r)
    assert res["ok"] is False
    assert any("counterexample" in e or "chain" in e for e in res["errors"])


# ---------------------------------------------------------------- the encoder gap

def test_a_valid_proof_of_a_different_problem_is_caught(proved):
    """The property a combinational receipt cannot have.

    Swap in the formula and proof from a *different* obligation. Both are
    internally valid — the proof really does refute that formula — but it is not
    what this design encodes to, and re-encoding catches it.
    """
    r = copy.deepcopy(proved)
    obs = r["payload"]["obligations"]
    i, j = 0, len(obs) - 1
    assert obs[i]["kind"] != obs[j]["kind"]
    obs[i]["cnf"], obs[i]["drat"] = obs[j]["cnf"], obs[j]["drat"]
    res = seq.verify_seq_receipt(r)
    assert res["ok"] is False
    assert any("not what this design encodes to" in e or "committed digest" in e
               for e in res["errors"]), res["errors"]


def test_editing_the_design_invalidates_the_receipt(proved):
    r = copy.deepcopy(proved)
    r["payload"]["design_a"]["outputs"] = ["s0"]
    res = seq.verify_seq_receipt(r)
    assert res["ok"] is False


def test_a_tampered_verdict_is_re_derived_not_read(proved):
    r = copy.deepcopy(proved)
    for rec in r["records"]:
        if rec.get("kind") == "verdict":
            rec["verdict"] = seq.COUNTEREXAMPLE
    res = seq.verify_seq_receipt(r)
    assert res["ok"] is False


def test_a_dropped_proof_is_not_an_accepted_claim(proved):
    r = copy.deepcopy(proved)
    r["payload"]["obligations"][-1]["drat"] = ""
    res = seq.verify_seq_receipt(r)
    assert res["ok"] is False
    assert any("carries no proof" in e or "committed digest" in e for e in res["errors"])


def test_an_unknown_format_is_refused():
    assert seq.verify_seq_receipt({"format": "something/9"})["ok"] is False


# ---------------------------------------------------------------- designs

@pytest.mark.parametrize("mutate,msg", [
    (lambda d: d.pop("outputs"), "missing"),
    (lambda d: d.update(outputs=[]), "nothing to compare"),
    (lambda d: d.update(outputs=["nope"]), "undefined"),
    (lambda d: d["gates"].append({"op": "NAND", "out": "q", "args": ["s0", "s1"]}), "unknown gate"),
    (lambda d: d["gates"].append({"op": "AND", "out": "q", "args": ["later", "s0"]}),
     "topological"),
    (lambda d: d["latches"].append({"name": "s0", "next": "n0", "init": 0}), "collides"),
    (lambda d: d["latches"].append({"name": "z", "next": "n0", "init": 7}), "init must be"),
])
def test_a_malformed_design_is_rejected_with_a_reason(mutate, msg):
    d = copy.deepcopy(COUNTER_A)
    mutate(d)
    with pytest.raises(seq.DesignError, match=msg):
        seq.validate_design(d)


def test_designs_with_different_inputs_cannot_be_compared():
    other = copy.deepcopy(COUNTER_B)
    other["inputs"] = ["go"]
    for g in other["gates"]:
        g["args"] = ["go" if a == "en" else a for a in g["args"]]
    with pytest.raises(seq.DesignError, match="same primary inputs"):
        seq.build_obligation(COUNTER_A, other, 1, kind="base")


def test_mismatched_latch_counts_fall_back_rather_than_crash():
    """Register correspondence needs a correspondence; without one, say so."""
    small = {"inputs": ["en"], "latches": [{"name": "u", "next": "nu", "init": 0}],
             "gates": [{"op": "XOR", "out": "nu", "args": ["u", "en"]},
                       {"op": "BUF", "out": "oo", "args": ["u"]}],
             "outputs": ["oo"]}
    with pytest.raises(seq.DesignError, match="same number of latches"):
        seq.build_obligation(COUNTER_A, small, 1, kind="rc-step")
    # the prover must not crash on such a pair; it falls through to k-induction
    r = seq.prove_sequential_equivalence(COUNTER_A, small, k=1, refute=_refute)
    assert seq.verify_seq_receipt(r)["verdict"] in (seq.UNDECIDED, seq.COUNTEREXAMPLE)


# ---------------------------------------------------------------- determinism

def test_encoding_is_deterministic_so_a_third_party_gets_the_same_bytes():
    a = seq.build_obligation(COUNTER_A, COUNTER_B, 2, kind="step")
    b = seq.build_obligation(COUNTER_A, COUNTER_B, 2, kind="step")
    assert a == b


def test_design_digest_ignores_key_order_but_not_content():
    reordered = json.loads(json.dumps(COUNTER_A))
    assert seq.design_digest(reordered) == seq.design_digest(COUNTER_A)
    changed = copy.deepcopy(COUNTER_A)
    changed["latches"][0]["init"] = 1
    assert seq.design_digest(changed) != seq.design_digest(COUNTER_A)


def test_k_must_be_positive():
    with pytest.raises(ValueError, match="at least 1"):
        seq.prove_sequential_equivalence(COUNTER_A, COUNTER_B, k=0, refute=_refute)


# ---------------------------------------------------------------- the README example

def test_the_readme_example_runs_and_prints_what_the_readme_says():
    """A quickstart nobody runs is a quickstart that is wrong."""
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    example = root / "examples" / "sequential.py"
    r = subprocess.run([sys.executable, str(example)], capture_output=True, text=True,
                       cwd=root)
    assert r.returncode == 0, r.stderr
    for line in ("verdict     : EQUIVALENT",
                 "argument    : register-correspondence",
                 "obligations : 4, each with its own proof",
                 "re-derived  : True"):
        assert line in r.stdout, r.stdout
        assert line in (root / "README.md").read_text(), f"README does not show: {line}"


def test_the_readme_shows_the_example_file_verbatim():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    body = (root / "examples" / "sequential.py").read_text().split('"""\n', 2)[-1].strip()
    assert body in (root / "README.md").read_text(), (
        "README code block has drifted from examples/sequential.py")
