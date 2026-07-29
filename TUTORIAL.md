# Tutorial — equiv-receipt

Prove two circuits equivalent, keep the proof, and hand someone a file they can check without your
tools, your solver, or your word.

## Install

```bash
pip install "equiv-receipt @ git+https://github.com/nickharris808/equiv-receipt.git@main"
equiv-receipt demo
```

## 1. Combinational equivalence in one call

```python
import equiv_receipt as E

def f(net, p):
    return net.AND(p + "o", "a", "b")

def g(net, p):
    net.NOT(p + "na", "a")
    net.NOT(p + "nb", "b")
    net.OR(p + "or", p + "na", p + "nb")
    return net.NOT(p + "o", p + "or")

receipt = E.prove_equivalence(f, g, ["a", "b"],
                              name_a="a AND b", name_b="NOT(NOT a OR NOT b)")
E.write_receipt("demorgan.json", receipt)
```

`prove_equivalence` builds a **miter** — a circuit that outputs 1 exactly when the two disagree —
and refutes it. UNSAT of the miter *is* equivalence, and the DRAT refutation is the evidence.

## 2. Verify it as a stranger

```bash
equiv-receipt verify demorgan.json
# OK  verdict re-derived: EQUIVALENT
```

Nothing is trusted. The verifier re-runs the proof check over the committed formula and proof,
recomputes the salted hash chain, and compares the recorded verdict against what it derived. The
verdict in the file is never *read* as the answer — a test asserts that editing it is caught.

## 3. Circuits that differ

Change `g` to `a OR b` and the miter is satisfiable. The receipt then carries a
**counterexample**: a concrete input assignment. `verify_receipt` re-simulates it against the
committed formula, so a fabricated counterexample is refused.

## 4. Use a real solver

The bundled `minisolve` is a textbook DPLL that exists so the package is self-contained. It raises
rather than grinding once an instance exceeds its declared depth.

```bash
equiv-receipt solvers                    # which are on PATH
equiv-receipt demo --solver cadical
```

```python
from equiv_receipt.solver import refute
receipt = E.prove_equivalence(f, g, ["a", "b"], refute=refute)
```

Any DIMACS-in, text-DRAT-out solver works — `export EQUIV_RECEIPT_SOLVER='mysolver --proof {drat} {cnf}'`.

**The trust story does not change, and that is the point.** The solver is not trusted; it is asked
for a proof, the proof goes in the receipt, and the proof is re-checked by code you can read.
Three things the adapter refuses to do: accept UNSAT with no proof, accept a proof that does not
check, or read silence as agreement.

## 5. Circuits with state

```python
from equiv_receipt import prove_sequential_equivalence, verify_seq_receipt

receipt = prove_sequential_equivalence(counter_a, counter_b, k=1)
res = verify_seq_receipt(receipt)
print(res["verdict"], res["method"])     # EQUIVALENT register-correspondence
```

Designs are JSON — inputs, latches, gates in topological order, outputs. See
[`examples/sequential.py`](examples/sequential.py), which the test suite runs.

Two arguments are tried and the receipt records which carried the result: **register
correspondence** (latches hold equal values — three obligations) and **k-induction on outputs**
(the general one). Every obligation carries its own DRAT proof.

**There are three outcomes and the third is the honest one.** Both arguments are sound but
incomplete: they can fail on circuits that really are equivalent, because the assumed states need
not be reachable. That is `UNDECIDED-AT-K`, exit code 4 — not a failure of the circuits and not a
pass.

### It closes the encoder gap

A combinational receipt commits the CNF bytes and a *prose* description, so a reader can detect a
swapped formula but cannot confirm the formula really is those circuits. A sequential design is
committed as data, so the verifier **re-encodes every obligation and compares bytes**. A receipt
carrying a valid proof of a *different problem* is rejected.

## 6. Check a proof you already have

```bash
equiv-receipt check-drat miter.cnf miter.drat
# VERIFIED  1149 lemmas (empty clause derived)
```

The checker does not care what produced the DRAT. It handles RUP, RAT and deletion lines — real
solvers emit all three.

## 7. Wire it into CI

```bash
equiv-receipt verify r.json --format sarif -o equiv.sarif
equiv-receipt verify-seq s.json --format junit -o results.xml
```

Neither SARIF nor JUnit has an "abstained" state, so `UNDECIDED-AT-K` renders as a **failure with
the reason attached**.

---

*See [CLI.md](CLI.md) for every flag, [TROUBLESHOOTING.md](TROUBLESHOOTING.md) for the errors you
will hit, and [certified-oss](https://github.com/nickharris808/certified-oss) for why any of this
exists.*
