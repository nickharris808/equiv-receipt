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

For real designs, use a proof-emitting solver and check its output:

```
equiv-receipt check-drat miter.cnf miter.drat
# VERIFIED  <n> lemmas (empty clause derived)
```

The checker does not care what produced the DRAT. That is the point: **checking is cheap and
public, proving is expensive and yours.**

## Scope

Combinational equivalence via the bundled encoder; arbitrary CNF/DRAT via the checker. Sequential
equivalence, timing, and X-semantics are **not** covered — a sequential conclusion rests on a
composition argument that a propositional proof format cannot express, which needs a different
receipt design.

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
