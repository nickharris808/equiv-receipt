# Contributing

This package is a **checker**. Its worth is that a skeptic can read it in an
afternoon and be convinced. That imposes unusual constraints.

## The rules

1. **Standard library only.** `test_no_third_party_imports` enforces this. A
   checker that drags in dependencies is a checker nobody audits.
2. **Never trust a recorded value.** The verdict in a receipt is re-derived, not
   read. Patches that short-circuit re-derivation will be declined.
3. **Every check needs a failing case.** Add the tamper test in the same commit.
   A check with no demonstrated failure mode is decoration.
4. **Do not grow the bundled solver.** `minisolve` exists so the package is
   self-contained for small instances and demos. Performance work belongs in a
   real solver (CaDiCaL, Kissat); this package checks whatever DRAT it is given,
   whatever produced it. Pull requests adding heuristics to `minisolve` will be
   declined; pull requests improving the *checker* are very welcome.

## A note on test premises

Three tests in the original suite asserted that a clause was "not RUP" when it
in fact was — the checker was right and the test was wrong. If you add a
soundness test, verify the premise directly with `bcp()` before asserting on it.
It is easy to write a negative test that quietly passes for the wrong reason.

## Running the tests

```
pip install -e ".[test]"
pytest
```

## Scope

Combinational miters via the bundled Tseitin encoder; any CNF/DRAT pair via the
checker. Sequential equivalence, timing, and X-semantics are out of scope here.
