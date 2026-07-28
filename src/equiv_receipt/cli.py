"""``equiv-receipt verify|verify-seq|check-drat|solvers|demo``."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .dimacs import parse_dimacs
from .receipt import read_receipt, verify_receipt
from .report import EMITTERS, emit
from .rup import forward_rup_check


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="equiv-receipt",
        description="Verify logic-equivalence receipts and DRAT refutations.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    v = sub.add_parser("verify", help="verify an EQUIV-1 receipt end to end")
    v.add_argument("receipt")
    v.add_argument("--json", action="store_true", help="same as --format json")
    v.add_argument("--format", choices=("text",) + tuple(sorted(EMITTERS)),
                   default="text", help="output format")
    v.add_argument("-o", "--output", default="", help="write here instead of stdout")

    q = sub.add_parser("verify-seq", help="verify a sequential (k-induction) receipt")
    q.add_argument("receipt")
    q.add_argument("--format", choices=("text",) + tuple(sorted(EMITTERS)),
                   default="text")
    q.add_argument("-o", "--output", default="")

    sub.add_parser("solvers", help="report which external SAT solvers are usable")

    d = sub.add_parser("check-drat", help="check a DRAT refutation against a CNF")
    d.add_argument("cnf")
    d.add_argument("drat")

    dm = sub.add_parser("demo",
                        help="prove a De Morgan equivalence and verify the receipt")
    dm.add_argument("--solver", default="",
                    help="external solver: a known name, or an argv template "
                         "containing {cnf} and {drat}")

    a = ap.parse_args(argv if argv is not None else sys.argv[1:])

    if a.cmd == "solvers":
        from .solver import KNOWN, Solver
        found = 0
        for name, argv in sorted(KNOWN.items()):
            s = Solver(name, argv)
            ok = s.available()
            found += ok
            print(f"  {name:10} {'available' if ok else 'not on PATH':12} "
                  f"{s.version() if ok else ''}")
        print(f"\n{found} usable. The bundled solver always works but is a "
              f"demonstration; an external one is needed for real designs.")
        print("Any DIMACS-in / text-DRAT-out solver works: set "
              "EQUIV_RECEIPT_SOLVER='mysolver {cnf} {drat}'.")
        return 0 if found else 3

    if a.cmd == "verify-seq":
        from .seq import read_seq_receipt, verify_seq_receipt
        res = verify_seq_receipt(read_seq_receipt(a.receipt))
        if a.format != "text":
            out = emit(res, a.format, source=a.receipt)
            if a.output:
                Path(a.output).write_text(out + "\n", encoding="utf-8")
            else:
                print(out)
        elif res["verdict"] == "UNDECIDED-AT-K":
            print(f"UNDECIDED at k={res['k']}  (base cases hold; no inductive "
                  f"argument closed)")
            print("  This is an abstention, not a failure of the circuits. "
                  "Try a larger k.")
        elif res["ok"]:
            print(f"OK  verdict re-derived: {res['verdict']}  "
                  f"via {res['method']}, {res['detail']['n_obligations']} obligations")
        else:
            print("FAILED", file=sys.stderr)
            for e in res["errors"]:
                print(f"  - {e}", file=sys.stderr)
        return 0 if res["ok"] and res["verdict"] == "EQUIVALENT" else (
            1 if res["verdict"] == "COUNTEREXAMPLE" else
            4 if res["verdict"] == "UNDECIDED-AT-K" else 2)

    if a.cmd == "verify":
        res = verify_receipt(read_receipt(a.receipt))
        fmt = "json" if a.json and a.format == "text" else a.format
        if fmt != "text":
            out = emit(res, fmt, source=a.receipt)
            if a.output:
                Path(a.output).write_text(out + "\n", encoding="utf-8")
                return 0 if res["ok"] else 1
            print(out)
        elif res["ok"]:
            print(f"OK  verdict re-derived: {res['verdict']}")
        else:
            print("FAILED", file=sys.stderr)
            for e in res["errors"]:
                print(f"  - {e}", file=sys.stderr)
        return 0 if res["ok"] else 1

    if a.cmd == "check-drat":
        clauses = parse_dimacs(Path(a.cnf).read_text())
        res = forward_rup_check(clauses, Path(a.drat).read_text())
        if res["verified"]:
            print(f"VERIFIED  {res['n_lemmas']} lemmas ({res['reason']})")
            return 0
        print(f"NOT VERIFIED  {res.get('reason')}", file=sys.stderr)
        if "failed_lemma" in res:
            print(f"  first bad lemma (index {res['failed_index']}): "
                  f"{res['failed_lemma']}", file=sys.stderr)
        return 1

    from .prove import prove_equivalence

    def f(n, p):
        return n.AND(p + "and", "a", "b")

    def g(n, p):
        n.NOT(p + "na", "a")
        n.NOT(p + "nb", "b")
        n.OR(p + "or", p + "na", p + "nb")
        return n.NOT(p + "out", p + "or")

    refuter = None
    if a.solver:
        from .solver import KNOWN, Solver, known_solver
        from .solver import refute as ext
        s = known_solver(a.solver) if a.solver in KNOWN else Solver(
            a.solver.split()[0], a.solver.split())

        def refuter(clauses):
            return ext(clauses, s)

    r = prove_equivalence(f, g, ["a", "b"], refute=refuter,
                          name_a="f = a AND b", name_b="g = NOT(NOT a OR NOT b)")
    res = verify_receipt(r)
    print("proved: f = a AND b  ==  g = NOT(NOT a OR NOT b)")
    print(f"  verdict re-derived : {res['verdict']}")
    print(f"  lemmas checked     : {res['detail'].get('n_lemmas')}")
    print(f"  receipt verifies   : {res['ok']}")
    return 0 if res["ok"] else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
