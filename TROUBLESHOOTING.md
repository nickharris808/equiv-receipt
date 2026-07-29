# Troubleshooting — equiv-receipt

The errors you will actually hit, and what each one means.

## `minisolve` raises `DepthExceeded`

The bundled solver is a demonstration, not a prover. It refuses rather than grinding forever, which
is the honest behaviour but not a useful one on real instances.

**Fix:** use an external solver. `equiv-receipt solvers` lists what is on PATH.

```python
from equiv_receipt.solver import refute
E.prove_equivalence(f, g, inputs, refute=refute)
```

## `SolverError: … reported UNSAT but wrote no proof`

The solver answered but emitted nothing to the proof path. Usually the argv template is missing the
proof flag, or the solver writes a **binary** proof by default.

**Fix:** CaDiCaL and Kissat need `--no-binary`. The adapter detects a binary proof and says so
rather than mis-parsing it.

An unproven UNSAT is a claim, and this package does not package claims — hence an error and not a
verdict.

## `SolverError: … exited N without reporting SAT or UNSAT`

The solver crashed, timed out inside itself, or is not the program you think it is. Silence is
never read as agreement.

## `refutation does not check: lemma is neither RUP nor RAT`

The proof does not establish what it claims at that lemma. The index and the lemma are in the
error, so it is locatable.

Two innocent causes worth ruling out first: the CNF and the DRAT are from **different runs**, or
the proof was truncated by a killed process.

## `verify-seq` returns `UNDECIDED-AT-K`, exit 4

Not a failure. The reset-state base cases proved, but neither inductive argument closed at this
`k`. The states the induction assumes need not be reachable.

**What to try:** raise `k`. If the two designs have the same number of latches, register
correspondence is tried first and is usually what succeeds; if their state encodings genuinely
differ, plain k-induction on outputs will often never close, and that is a property of the method
rather than a bug.

## `DesignError: gate 'x' reads 'y', which is not defined yet`

Gates must be listed in topological order. The validator rejects rather than sorting for you,
because a design that has to be guessed at cannot be re-encoded identically by someone else —
which would defeat the verifier's re-encoding check.

## `DesignError: register correspondence needs the same number of latches`

Only raised if you call `build_obligation(..., kind="rc-*")` directly. The prover checks first and
falls through to k-induction.

## `the committed formula is not what this design encodes to`

The receipt's CNF does not match what the committed design produces. Either the design was edited
after proving, or the formula came from somewhere else.

This is the check a combinational receipt cannot do, and it is working as intended.

## The verdict in the file says EQUIVALENT but verification fails

Correct behaviour. The verdict is **re-derived, never read**. A receipt whose recorded verdict
disagrees with the re-derivation is refuted — that is the whole point of the format.

## `CNFParseError` on a file another tool accepted

The DIMACS parser is strict: a header that does not match the clause count, non-integer tokens, or
a clause without its terminating `0` are all rejected. Silently mis-parsing a formula would mean
verifying the wrong problem.

## Tests skip with "no external solver on PATH"

Expected. Install `cadical` or `kissat` to run them; the suite is green either way and says which
it skipped.

---

*Still stuck? Open an issue with the command, the version, and the receipt if you can share it.*
