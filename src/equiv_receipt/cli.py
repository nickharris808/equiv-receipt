"""``equiv-receipt verify|check-drat|demo``."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .dimacs import parse_dimacs
from .receipt import read_receipt, verify_receipt
from .rup import forward_rup_check


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="equiv-receipt",
        description="Verify logic-equivalence receipts and DRAT refutations.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    v = sub.add_parser("verify", help="verify an EQUIV-1 receipt end to end")
    v.add_argument("receipt")
    v.add_argument("--json", action="store_true", help="emit machine-readable output")

    d = sub.add_parser("check-drat", help="check a DRAT refutation against a CNF")
    d.add_argument("cnf")
    d.add_argument("drat")

    sub.add_parser("demo", help="prove a De Morgan equivalence and verify the receipt")

    a = ap.parse_args(argv if argv is not None else sys.argv[1:])

    if a.cmd == "verify":
        res = verify_receipt(read_receipt(a.receipt))
        if a.json:
            print(json.dumps(res, indent=2, sort_keys=True))
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

    r = prove_equivalence(f, g, ["a", "b"],
                          name_a="f = a AND b", name_b="g = NOT(NOT a OR NOT b)")
    res = verify_receipt(r)
    print("proved: f = a AND b  ==  g = NOT(NOT a OR NOT b)")
    print(f"  verdict re-derived : {res['verdict']}")
    print(f"  lemmas checked     : {res['detail'].get('n_lemmas')}")
    print(f"  receipt verifies   : {res['ok']}")
    return 0 if res["ok"] else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
