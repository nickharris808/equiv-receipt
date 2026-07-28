# equiv-receipt

[![ci](https://github.com/nickharris808/equiv-receipt/actions/workflows/ci.yml/badge.svg)](https://github.com/nickharris808/equiv-receipt/actions/workflows/ci.yml)
![license](https://img.shields.io/badge/license-Apache--2.0-blue)
![python](https://img.shields.io/badge/python-3.9%20%7C%203.10%20%7C%203.11%20%7C%203.12%20%7C%203.13-blue)
![dependencies](https://img.shields.io/badge/dependencies-none-brightgreen)
![tests](https://img.shields.io/badge/tests-32%20passing-brightgreen)

**An AI edited your RTL. Prove it still does the same thing — with a receipt anyone can re-check,
using nothing but the Python standard library.**

Equivalence checkers return a verdict. A verdict is a claim about a computation you did not
watch, produced by a tool you did not audit. `equiv-receipt` returns a **receipt**: the formula,
the refutation, the encoder's identity, and both circuit descriptions, bound into a salted hash
chain — so a third party can re-derive the verdict without your tools, your solver, or your trust.

Zero dependencies. The checker is a few hundred lines and you are meant to read it.

## Install

> **Not yet on PyPI.** Install from the repository — it works exactly the same:
>
> ```
> pip install git+https://github.com/nickharris808/equiv-receipt.git
> ```

```
pip install equiv-receipt
```

## 30-second quickstart

```
equiv-receipt demo
```

```
proved: f = a AND b  ==  g = NOT(NOT a OR NOT b)
  verdict re-derived : EQUIVALENT
  lemmas checked     : 3
  receipt verifies   : True
```

That ran a real Tseitin encoding, a real refutation search, and a real DRAT check. No SAT solver
was installed.

## Worked example

```python
import equiv_receipt as E

def f(n, p):                      # a AND b
    return n.AND(p + "and", "a", "b")

def g(n, p):                      # NOT(NOT a OR NOT b)  — De Morgan
    n.NOT(p + "na", "a"); n.NOT(p + "nb", "b")
    n.OR(p + "or", p + "na", p + "nb")
    return n.NOT(p + "out", p + "or")

receipt = E.prove_equivalence(f, g, ["a", "b"], name_a="f", name_b="g")
E.write_receipt("f_vs_g.json", receipt)

print(E.verify_receipt(receipt)["verdict"])     # EQUIVALENT
```

Now hand `f_vs_g.json` to someone with no access to your code:

```
equiv-receipt verify f_vs_g.json
# OK  verdict re-derived: EQUIVALENT
```

When the circuits **differ**, you get a counterexample instead — and the receipt binds it, so the
verifier re-simulates it rather than believing it:

```python
import equiv_receipt as E

def f(n, p): return n.AND(p + "and", "a", "b")
def h(n, p): return n.OR(p + "or", "a", "b")

r = E.prove_equivalence(f, h, ["a", "b"])
print(E.verify_receipt(r)["verdict"])           # COUNTEREXAMPLE
```

## Forgery is caught

The verdict is never read from the receipt. It is recomputed.

```python
import equiv_receipt as E

def f(n, p): return n.AND(p + "and", "a", "b")
def h(n, p): return n.OR(p + "or", "a", "b")

r = E.prove_equivalence(f, h, ["a", "b"])        # genuinely different circuits
for rec in r["records"]:
    if rec.get("kind") == "verdict":
        rec["verdict"] = "EQUIVALENT"            # lie about it

print(E.verify_receipt(r)["ok"])                 # False
```

Tampering with the formula, the proof, the encoder identity, either circuit description, or any
link in the chain is likewise rejected. There are tamper tests for all of them.

## Bring your own solver

The bundled `minisolve` is a textbook DPLL with no heuristics. It exists so the package is
self-contained and testable — **it is not a production prover** and it raises rather than grinding
when an instance exceeds its declared depth.

For real designs, point the package at a solver that emits DRAT:

```bash
equiv-receipt solvers          # which are on PATH, and their versions
equiv-receipt demo --solver cadical
```

```python
from equiv_receipt import prove_equivalence, verify_receipt
from equiv_receipt.solver import refute            # external solver

r = prove_equivalence(f, g, ["a", "b"], refute=refute)
verify_receipt(r)["verdict"]                       # 'EQUIVALENT'
```

Any DIMACS-in, text-DRAT-out solver works. `cadical`, `kissat` and `minisat` are known by name;
anything else is one argv template:

```bash
export EQUIV_RECEIPT_SOLVER='mysolver --proof {drat} {cnf}'
```

**The trust story does not change, and that is the point.** The solver is not trusted. It is asked
for a proof; the proof goes in the receipt; the proof is re-checked by code you can read before any
verdict is asserted. Swapping in a faster solver buys reach, not credibility. Three things the
adapter refuses to do:

| Situation | What happens |
|---|---|
| Solver says UNSAT but writes no proof | **Error.** An unproven UNSAT is a claim, and this package does not package claims. |
| Solver writes a proof that does not check | **Error**, and the verdict is withheld. |
| Solver exits without saying SAT or UNSAT | **Error**, never read as agreement. |

### The checker had to grow up first

A DRAT proof from a real solver contains **RAT** lemmas — the ones emitted when the solver
eliminates a variable — and deletion lines. The checker now handles both. It also uses two watched
literals per clause and an index for deletions, which is what makes long proofs checkable at all.
Measured numbers are in [PERFORMANCE.md](PERFORMANCE.md).

## Sequential equivalence

Circuits with state are not one SAT call. `equiv-receipt` proves them by induction, and every
obligation carries its own proof:

```python
from equiv_receipt import prove_sequential_equivalence, verify_seq_receipt
from equiv_receipt.solver import detect, refute

counter_a = {
    "inputs": ["en"],
    "latches": [{"name": "s0", "next": "n0", "init": 0},
                {"name": "s1", "next": "n1", "init": 0}],
    "gates": [{"op": "XOR", "out": "n0", "args": ["s0", "en"]},
              {"op": "AND", "out": "c",  "args": ["s0", "en"]},
              {"op": "XOR", "out": "n1", "args": ["s1", "c"]},
              {"op": "OR",  "out": "o",  "args": ["s0", "s1"]}],
    "outputs": ["o"],
}

# The same machine: different signal names, and the output written with De Morgan.
counter_b = {
    "inputs": ["en"],
    "latches": [{"name": "t0", "next": "m0", "init": 0},
                {"name": "t1", "next": "m1", "init": 0}],
    "gates": [{"op": "XOR", "out": "m0", "args": ["en", "t0"]},
              {"op": "AND", "out": "cc", "args": ["en", "t0"]},
              {"op": "XOR", "out": "m1", "args": ["cc", "t1"]},
              {"op": "NOT", "out": "a",  "args": ["t0"]},
              {"op": "NOT", "out": "b",  "args": ["t1"]},
              {"op": "AND", "out": "z",  "args": ["a", "b"]},
              {"op": "NOT", "out": "o2", "args": ["z"]}],
    "outputs": ["o2"],
}

# `refute` uses an external solver when one is on PATH; without it, the bundled
# demonstration solver handles an instance this small.
solve = refute if detect() else None

receipt = prove_sequential_equivalence(counter_a, counter_b, k=1, refute=solve)
res = verify_seq_receipt(receipt)

print(f"verdict     : {res['verdict']}")
print(f"argument    : {res['method']}")
print(f"obligations : {res['detail']['n_obligations']}, each with its own proof")
print(f"re-derived  : {res['ok']}")
```

```
verdict     : EQUIVALENT
argument    : register-correspondence
obligations : 4, each with its own proof
re-derived  : True
```

That is [`examples/sequential.py`](examples/sequential.py) verbatim; a test runs it and
checks this output, so it cannot rot.

Two arguments are tried, and the receipt records which one carried the result:

1. **Register correspondence** — the invariant "corresponding latches hold equal values", as three
   obligations: it holds at reset, one step preserves it, and it implies equal outputs.
2. **k-induction on outputs** — the general argument, for designs whose state encodings do not
   correspond.

**There are three outcomes, and the third is the honest one.** Both arguments are sound but
incomplete: they can fail on circuits that really are equivalent, because the assumed states need
not be reachable. When that happens the verdict is `UNDECIDED-AT-K` — an abstention, exit code 4.
It is not a failure of the circuits and it is not a pass.

Why two arguments rather than the textbook one: plain k-induction on outputs will essentially never
prove two independently-encoded state machines equivalent, because an arbitrary assumed state can
have them in different-but-output-agreeing states from which they diverge. That is not a bug in
k-induction; it is why practical sequential equivalence checking looks for a state invariant.
Shipping only the general argument would have been a feature that abstains almost always.

Nothing about the method is new — Sheeran, Singh and Stålmarck introduced k-induction; certifying
it is a studied problem. What is added here is that the **result arrives as an artifact a third
party can re-derive.**

### And it closes the encoder gap

A combinational receipt commits the CNF bytes and a *prose* description of the circuits, so a
verifier can detect a swapped formula but cannot confirm the formula really is those circuits. A
sequential design is committed as machine-readable data, so the verifier **re-encodes every
obligation from the design and compares it byte for byte**. A receipt carrying a perfectly valid
proof of a *different problem* is rejected — `test_a_valid_proof_of_a_different_problem_is_caught`
asserts exactly that.

## Structured output

```bash
equiv-receipt verify r.json --format sarif -o equiv.sarif
equiv-receipt verify-seq s.json --format junit -o results.xml
```

`text` · `json` · `jsonl` · `sarif` (GitHub's Security tab) · `junit` (any CI test report).

Neither SARIF nor JUnit has an "abstained" state, so `UNDECIDED-AT-K` renders as a **failure with
the reason attached**. A green check mark on a question that was not answered is precisely the
confident wrong answer this package exists to avoid.

## Scope

Combinational equivalence via the bundled encoder; sequential equivalence by induction over the
JSON netlist format; arbitrary CNF/DRAT via the checker. Timing and X-semantics are **not**
covered.

## Beyond this package

`equiv-receipt` proves two descriptions agree. It does not tell you whether the design is
*manufacturable*, whether it survives process variation, or whether it prints. Those need a
certified admission gate over physical models — a separate, closed product. This package is the
part you should never have to trust anyone for.

## License

Apache-2.0.

## Honest scope — what this proves, and what it does not

| Question | Answer |
|---|---|
| Does the committed proof actually refute the committed formula? | **Yes, every lemma re-checked.** |
| Does that formula correspond to the two circuits named in the receipt? | **Yes** — the encoder identity and both descriptions are committed, so a swap is detectable. |
| Were the descriptions altered after the proof was made? | **Yes, caught** by the hash chain. |
| Are the circuits equivalent under *timing*, or with state, or under X-semantics? | **Never checked.** Combinational only. |
| Is the design *correct*? | **Never checked.** Equivalence is not correctness — two circuits can agree and both be wrong. |

A malformed proof or formula is **rejected**, never silently parsed into something else.

---

## The rest of the toolkit

One idea, six pieces: **a recorded verdict is a claim to be checked, never an input to be trusted.**

The whole story, and the objections answered, live at **[certified-oss](https://github.com/nickharris808/certified-oss)** — start there if this is the first of the six you have opened.

| | |
|---|---|
| [**lcert-verify**](https://github.com/nickharris808/lcert-verify) | Re-derive a manufacturing certificate's verdict. Stdlib only. |
| [**equiv-receipt**](https://github.com/nickharris808/equiv-receipt) | Prove two circuits equivalent, with a receipt anyone can re-check. |
| [**prereg-seal**](https://github.com/nickharris808/prereg-seal) | Seal acceptance criteria before you measure. |
| [**cert-atlas**](https://github.com/nickharris808/cert-atlas) | 21 labelled forgeries and a metric no degenerate verifier can win. |
| [**certified-mcp**](https://github.com/nickharris808/certified-mcp) | The above, as tools your AI agent can call. |
| [**lcert-verify-web**](https://github.com/nickharris808/lcert-verify-web) | The verifier in a browser. Nothing uploaded. |

**Try it now, no install:** [🔏 the verifier Space](https://huggingface.co/spaces/nickh007/cert-verifier) ·
**Browse the forgeries:** [📊 the atlas dataset](https://huggingface.co/datasets/nickh007/cert-atlas)

### Where the free edition stops

Everything here **checks**. None of it **produces** a certificate that is physically meaningful —
that needs sound enclosures over real process models, which is a separate commercial product. If
you need certificates rather than a way to check them, that is the conversation to have.
