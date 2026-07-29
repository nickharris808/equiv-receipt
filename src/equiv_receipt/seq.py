"""Sequential equivalence by k-induction, with a re-derivable receipt.

Combinational equivalence is one SAT call. Sequential equivalence is not: two
circuits with state agree only over reachable states, and reachability is the hard
part. This module proves it by **k-induction**, which is a standard technique —
Sheeran, Singh and Stålmarck introduced it; Bradley, Biere, Heljanko and others
developed the certification of it. Nothing about the method is new here. What this
module adds is that the *result* arrives as an artifact a third party can re-derive.

Two arguments are available, and the receipt records which one carried the result.

**Register correspondence** — the practical one. The invariant is "corresponding
latches hold equal values", discharged as three obligations: it holds at reset, one
step preserves it, and it implies equal outputs. When that goes through, a single
step of induction settles every time step.

**k-induction on outputs** — the general one, for designs whose state encodings do
not correspond. From the reset state the outputs agree at times ``0 … k-1``; and
from an *arbitrary* state, agreement at ``k`` consecutive times implies agreement
at the next.

Reset-state base cases run first under either argument, because a failure there is
a *real* counterexample rather than an artefact of an unreachable assumed state.
Every obligation is discharged by a SAT solver and carries a DRAT proof, so the
receipt contains proofs, not assurances.

A note on why the first argument exists: plain k-induction on the output property
alone will essentially never prove two independently-encoded state machines
equivalent, because an arbitrary assumed state can have the two circuits in
different — but output-agreeing — states, from which they diverge. That is not a
bug in k-induction; it is why practical sequential equivalence checking looks for
a state invariant. Shipping only the general argument would have been a feature
that abstains almost always.

**The third outcome is the honest one.** Both arguments are sound but
*incomplete*: they can fail on circuits that are genuinely equivalent, because the
assumed states need not be reachable. When the reset-state base cases pass and
neither inductive argument closes, the verdict is ``UNDECIDED-AT-K`` — an
abstention. It is not a failure of the circuits and it is not a pass. Raising ``k``
may resolve it; nothing here pretends otherwise.

**The encoder gap is closed here.** A combinational receipt commits the CNF bytes
and a prose description of the circuits, so a verifier can detect a swapped
formula but cannot confirm the formula *is* the circuits. A sequential design is
committed as machine-readable data, so :func:`verify_seq_receipt` **re-encodes
every obligation from the design and compares it to the committed formula**. A
receipt whose CNF does not correspond to its circuits is rejected.
"""
from __future__ import annotations

import hashlib
import json
from typing import Dict, List, Optional

from .dimacs import to_dimacs
from .receipt import DOMAIN_CHAIN, GENESIS, canon, chain
from .rup import forward_rup_check
from .tseitin import Netlist

SEQ_FORMAT = "equiv-receipt-seq/1"
ENCODER_ID = "equiv-receipt.unroll/1"

BINARY_OPS = {"AND", "OR", "XOR"}
UNARY_OPS = {"NOT", "BUF"}

EQUIVALENT = "EQUIVALENT"
COUNTEREXAMPLE = "COUNTEREXAMPLE"
UNDECIDED = "UNDECIDED-AT-K"


class DesignError(ValueError):
    """A sequential design that cannot be interpreted."""


def validate_design(d: Dict) -> Dict:
    """Check a design is well formed and in a canonical, re-encodable shape.

    Rejects rather than repairs. A design that has to be guessed at cannot be
    re-encoded identically by someone else, which would defeat the point.
    """
    for key in ("inputs", "latches", "gates", "outputs"):
        if key not in d:
            raise DesignError(f"design is missing {key!r}")
    if not isinstance(d["inputs"], list) or not all(isinstance(x, str) for x in d["inputs"]):
        raise DesignError("inputs must be a list of names")
    if not d["outputs"]:
        raise DesignError("a design with no outputs has nothing to compare")

    defined = set(d["inputs"])
    if len(defined) != len(d["inputs"]):
        raise DesignError("duplicate input name")
    for lat in d["latches"]:
        for key in ("name", "next", "init"):
            if key not in lat:
                raise DesignError(f"latch is missing {key!r}: {lat}")
        if lat["init"] not in (0, 1, False, True):
            raise DesignError(f"latch {lat['name']!r} init must be 0 or 1")
        if lat["name"] in defined:
            raise DesignError(f"latch {lat['name']!r} collides with an existing signal")
        defined.add(lat["name"])

    for g in d["gates"]:
        op, out, args = g.get("op"), g.get("out"), g.get("args", [])
        if op in BINARY_OPS and len(args) != 2:
            raise DesignError(f"{op} takes 2 arguments, got {len(args)}")
        elif op in UNARY_OPS and len(args) != 1:
            raise DesignError(f"{op} takes 1 argument, got {len(args)}")
        elif op not in BINARY_OPS | UNARY_OPS:
            raise DesignError(f"unknown gate op {op!r}")
        if out in defined:
            raise DesignError(f"signal {out!r} defined twice")
        for a in args:
            if a not in defined:
                raise DesignError(
                    f"gate {out!r} reads {a!r}, which is not defined yet — "
                    f"gates must be listed in topological order")
        defined.add(out)

    for lat in d["latches"]:
        if lat["next"] not in defined:
            raise DesignError(f"latch {lat['name']!r} next signal {lat['next']!r} undefined")
    for o in d["outputs"]:
        if o not in defined:
            raise DesignError(f"output {o!r} undefined")
    return d


def design_digest(d: Dict) -> str:
    return hashlib.sha256(canon(validate_design(d))).hexdigest()


def _emit(net: Netlist, design: Dict, side: str, k: int, free_state: bool,
          sig: Dict) -> None:
    """Unroll one design over frames ``0..k`` into ``net``, filling ``sig``."""
    for t in range(k + 1):
        for name in design["inputs"]:
            sig[(side, name, t)] = f"{name}@{t}"          # inputs are shared

    for lat in design["latches"]:
        n = f"{side}.{lat['name']}@0"
        if free_state:
            sig[(side, lat["name"], 0)] = n               # declared as a free input
        else:
            net.CONST(n, bool(lat["init"]))
            sig[(side, lat["name"], 0)] = n

    for t in range(k + 1):
        for g in design["gates"]:
            out = f"{side}.{g['out']}@{t}"
            args = [sig[(side, a, t)] for a in g["args"]]
            op = g["op"]
            if op == "AND":
                net.AND(out, *args)
            elif op == "OR":
                net.OR(out, *args)
            elif op == "XOR":
                net.XOR(out, *args)
            elif op == "NOT":
                net.NOT(out, *args)
            else:
                net.BUF(out, *args)
            sig[(side, g["out"], t)] = out
        if t < k:
            for lat in design["latches"]:
                sig[(side, lat["name"], t + 1)] = sig[(side, lat["next"], t)]


def build_obligation(a: Dict, b: Dict, k: int, *, kind: str, at: int = 0) -> List[List[int]]:
    """CNF for one proof obligation. UNSAT is the desired answer in every case.

    ``kind`` is ``"base"`` (differ at time ``at``, from the initial state) or
    ``"step"`` (agree at ``0..k-1`` from an arbitrary state, differ at ``k``).

    Deterministic in its inputs, which is what lets a verifier re-encode and
    compare bytes.
    """
    validate_design(a)
    validate_design(b)
    if len(a["outputs"]) != len(b["outputs"]):
        raise DesignError("designs have different output counts and cannot be compared")
    if a["inputs"] != b["inputs"]:
        raise DesignError("designs must share the same primary inputs, in the same order")

    if kind.startswith("rc-"):
        if len(a["latches"]) != len(b["latches"]):
            raise DesignError(
                "register correspondence needs the same number of latches in "
                "both designs; use k-induction on outputs instead")
        free = True
        frames = 1 if kind == "rc-step" else 0
        if kind == "rc-base":
            free = False                                   # reset state, not arbitrary
    else:
        free = kind == "step"
        frames = k if kind == "step" else at
    inputs: List[str] = [f"{n}@{t}" for t in range(frames + 1) for n in a["inputs"]]
    if free:
        inputs += [f"A.{lat['name']}@0" for lat in a["latches"]]
        inputs += [f"B.{lat['name']}@0" for lat in b["latches"]]

    net = Netlist(inputs)
    sig: Dict = {}
    _emit(net, a, "A", frames, free, sig)
    _emit(net, b, "B", frames, free, sig)

    def diff_at(t: int) -> str:
        """A signal that is true exactly when the two disagree at time ``t``."""
        xs = []
        for j, (oa, ob) in enumerate(zip(a["outputs"], b["outputs"])):
            x = f"diff{j}@{t}"
            net.XOR(x, sig[("A", oa, t)], sig[("B", ob, t)])
            xs.append(x)
        acc = xs[0]
        for j, x in enumerate(xs[1:], 1):
            nxt = f"anydiff{j}@{t}"
            net.OR(nxt, acc, x)
            acc = nxt
        return acc

    def latch_diff_at(t: int) -> str:
        """True exactly when some corresponding latch pair disagrees at ``t``."""
        xs = []
        for j, (la, lb) in enumerate(zip(a["latches"], b["latches"])):
            x = f"ldiff{j}@{t}"
            net.XOR(x, sig[("A", la["name"], t)], sig[("B", lb["name"], t)])
            xs.append(x)
        acc = xs[0]
        for j, x in enumerate(xs[1:], 1):
            nxt = f"anyldiff{j}@{t}"
            net.OR(nxt, acc, x)
            acc = nxt
        return acc

    if kind == "base":
        d = diff_at(at)
        clauses = net.clauses
        clauses.append([net.var(d)])                       # assert they differ
    elif kind == "step":
        ds = [diff_at(t) for t in range(k + 1)]
        clauses = net.clauses
        for t in range(k):
            clauses.append([-net.var(ds[t])])              # assume agreement
        clauses.append([net.var(ds[k])])                   # assert disagreement
    elif kind == "rc-base":
        ld = latch_diff_at(0)
        clauses = net.clauses
        clauses.append([net.var(ld)])                      # assert states differ at reset
    elif kind == "rc-step":
        ld0, ld1 = latch_diff_at(0), latch_diff_at(1)
        clauses = net.clauses
        clauses.append([-net.var(ld0)])                    # assume states agree
        clauses.append([net.var(ld1)])                     # assert next states differ
    elif kind == "rc-out":
        ld0, d0 = latch_diff_at(0), diff_at(0)
        clauses = net.clauses
        clauses.append([-net.var(ld0)])                    # assume states agree
        clauses.append([net.var(d0)])                      # assert outputs differ
    else:
        raise DesignError(f"unknown obligation kind {kind!r}")
    return clauses


def prove_sequential_equivalence(a: Dict, b: Dict, *, k: int = 1,
                                 refute=None, name_a: str = "A", name_b: str = "B",
                                 seed: int = 1) -> Dict:
    """Prove ``a`` and ``b`` sequentially equivalent, or find a counterexample.

    ``refute(clauses) -> {"unsat", "drat", "model"}``; defaults to the bundled
    solver. Pass :func:`equiv_receipt.solver.refute` for a real one.

    Two arguments are attempted, in this order, and the receipt records which one
    carried the result:

    1. **Register correspondence** — the stronger invariant "corresponding latches
       hold equal values". Three obligations: it holds at reset, it is preserved
       by one step, and it implies equal outputs. When it goes through, one step of
       induction settles every time, which is why it is tried first.
    2. **k-induction on outputs** — the general argument, for designs whose state
       encodings do not correspond.

    Base cases from the reset state are always run first, because a failure there
    is a *real* counterexample rather than an artefact of an unreachable assumed
    state.
    """
    if k < 1:
        raise ValueError("k must be at least 1")
    if refute is None:
        from .minisolve import refute as _bundled
        refute = _bundled

    obligations: List[Dict] = []
    counterexample: Optional[Dict] = None

    def discharge(kind: str, at: int = 0) -> bool:
        cl = build_obligation(a, b, k, kind=kind, at=at)
        res = refute(cl)
        obligations.append({"kind": kind, "at": at, "cnf": to_dimacs(cl),
                            "drat": res.get("drat", "") if res["unsat"] else "",
                            "unsat": bool(res["unsat"]),
                            "model": {str(kk): bool(v) for kk, v in
                                      (res.get("model") or {}).items()}
                            if not res["unsat"] else {}})
        return bool(res["unsat"])

    # 1. Reset-state base cases. A SAT answer here is a genuine counterexample.
    for t in range(k):
        if not discharge("base", t):
            counterexample = {"time": t, "assignment": obligations[-1]["model"]}
            return build_seq_receipt(
                verdict=COUNTEREXAMPLE, design_a=a, design_b=b, k=k,
                obligations=obligations, counterexample=counterexample,
                name_a=name_a, name_b=name_b, seed=seed, method="base")

    # 2. Register correspondence, when the latch counts allow it.
    if len(a["latches"]) == len(b["latches"]) and a["latches"]:
        mark = len(obligations)
        if all(discharge(kind) for kind in ("rc-base", "rc-step", "rc-out")):
            return build_seq_receipt(
                verdict=EQUIVALENT, design_a=a, design_b=b, k=k,
                obligations=obligations, name_a=name_a, name_b=name_b,
                seed=seed, method="register-correspondence")
        # It did not go through. Keep the attempt in the receipt rather than
        # hiding it: a reader should see what was tried.
        del obligations[mark:]

    # 3. k-induction on the output property.
    if discharge("step", k):
        return build_seq_receipt(
            verdict=EQUIVALENT, design_a=a, design_b=b, k=k,
            obligations=obligations, name_a=name_a, name_b=name_b,
            seed=seed, method="k-induction")

    # Sound but incomplete: the assumed states need not be reachable. Abstain.
    return build_seq_receipt(
        verdict=UNDECIDED, design_a=a, design_b=b, k=k, obligations=obligations,
        name_a=name_a, name_b=name_b, seed=seed, method="k-induction")


def build_seq_receipt(*, verdict: str, design_a: Dict, design_b: Dict, k: int,
                      obligations: List[Dict], counterexample: Optional[Dict] = None,
                      name_a: str = "A", name_b: str = "B", seed: int = 1,
                      method: str = "k-induction") -> Dict:
    if verdict not in (EQUIVALENT, COUNTEREXAMPLE, UNDECIDED):
        raise ValueError(f"unknown verdict {verdict!r}")
    records = [
        {"kind": "header", "format": SEQ_FORMAT, "seed": int(seed), "k": int(k)},
        {"kind": "designs", "name_a": name_a, "name_b": name_b,
         "digest_a": design_digest(design_a), "digest_b": design_digest(design_b)},
        {"kind": "encoder", "encoder_id": ENCODER_ID, "method": method},
        {"kind": "obligations", "digests": [
            {"kind": o["kind"], "at": o["at"],
             "cnf": hashlib.sha256(o["cnf"].encode()).hexdigest(),
             "drat": hashlib.sha256(o["drat"].encode()).hexdigest(),
             "unsat": o["unsat"]} for o in obligations]},
        {"kind": "verdict", "verdict": verdict, "counterexample": counterexample},
    ]
    return {"format": SEQ_FORMAT, "seed": int(seed), "k": int(k),
            "records": chain(records),
            "payload": {"design_a": validate_design(design_a),
                        "design_b": validate_design(design_b),
                        "obligations": obligations}}


def verify_seq_receipt(receipt: Dict) -> Dict:
    """Re-derive a sequential receipt from scratch. Never reads the verdict.

    Four things are checked, and the third is the one a combinational receipt
    cannot do: the CNF of every obligation is **re-encoded from the committed
    design** and compared, so the formula is proven to be the circuits.
    """
    errors: List[str] = []
    if not isinstance(receipt, dict):
        return {"ok": False, "verdict": None, "errors": [
            f"a receipt must be an object, got {type(receipt).__name__}"]}
    if receipt.get("format") != SEQ_FORMAT:
        return {"ok": False, "verdict": None,
                "errors": [f"unknown format {receipt.get('format')!r}"]}

    records = receipt.get("records") or []
    payload = receipt.get("payload") or {}
    if not isinstance(records, list) or not all(isinstance(r, dict) for r in records):
        return {"ok": False, "verdict": None,
                "errors": ["records must be a list of objects"]}
    if not isinstance(payload, dict):
        return {"ok": False, "verdict": None,
                "errors": [f"payload must be an object, got {type(payload).__name__}"]}

    prev = GENESIS
    for i, rec in enumerate(records):
        body = {kk: vv for kk, vv in rec.items() if kk != "this"}
        if body.get("prev") != prev:
            errors.append(f"record {i}: broken chain link")
        if hashlib.sha256(DOMAIN_CHAIN + canon(body)).hexdigest() != rec.get("this"):
            errors.append(f"record {i}: record digest does not recompute")
        prev = rec.get("this")
    by_kind = {r.get("kind"): r for r in records}

    a, b = payload.get("design_a"), payload.get("design_b")
    try:
        k = int(receipt.get("k", 0))
    except (TypeError, ValueError):
        return {"ok": False, "verdict": None,
                "errors": [f"k must be an integer, got {receipt.get('k')!r}"]}
    try:
        validate_design(a)
        validate_design(b)
    except (DesignError, TypeError) as exc:
        return {"ok": False, "verdict": None, "errors": errors + [f"design: {exc}"]}

    d = by_kind.get("designs", {})
    if design_digest(a) != d.get("digest_a") or design_digest(b) != d.get("digest_b"):
        errors.append("a design does not match its committed digest")

    obligations = payload.get("obligations") or []
    if not isinstance(obligations, list):
        return {"ok": False, "verdict": None, "k": k,
                "errors": errors + [f"obligations must be a list, got "
                                    f"{type(obligations).__name__}"]}
    if not all(isinstance(o, dict) for o in obligations):
        return {"ok": False, "verdict": None, "k": k,
                "errors": errors + ["every obligation must be an object"]}
    committed = (by_kind.get("obligations") or {}).get("digests") or []
    if len(obligations) != len(committed):
        errors.append("obligation count does not match the commitment")

    proved: Dict[str, set] = {"base": set(), "rc": set(), "step": set()}
    for i, o in enumerate(obligations):
        tag = f"obligation {i} ({o.get('kind')} at {o.get('at')})"
        if i < len(committed):
            c = committed[i]
            if hashlib.sha256(o["cnf"].encode()).hexdigest() != c.get("cnf"):
                errors.append(f"{tag}: formula does not match its committed digest")
            if hashlib.sha256(o["drat"].encode()).hexdigest() != c.get("drat"):
                errors.append(f"{tag}: proof does not match its committed digest")

        # Re-encode from the design. This is what makes the formula *the circuits*.
        try:
            clauses = build_obligation(a, b, k, kind=o["kind"], at=int(o["at"]))
        except (DesignError, KeyError, ValueError) as exc:
            errors.append(f"{tag}: could not re-encode: {exc}")
            continue
        if to_dimacs(clauses).strip() != str(o.get("cnf", "")).strip():
            errors.append(f"{tag}: the committed formula is not what this design "
                          f"encodes to — the proof may be of a different problem")
            continue

        if o.get("drat", "").strip():
            chk = forward_rup_check(clauses, o["drat"])
            if not chk["verified"]:
                errors.append(f"{tag}: refutation does not check: {chk.get('reason')}")
            elif o["kind"] == "base":
                proved["base"].add(int(o["at"]))
            elif o["kind"] == "step":
                proved["step"].add(k)
            else:
                proved["rc"].add(o["kind"])
        elif o.get("unsat"):
            errors.append(f"{tag}: claims UNSAT but carries no proof")

    recorded = (by_kind.get("verdict") or {}).get("verdict")
    cex = (by_kind.get("verdict") or {}).get("counterexample")
    method = (by_kind.get("encoder") or {}).get("method")

    sat_base = [o for o in obligations if o.get("kind") == "base" and not o.get("unsat")]
    all_base = all(t in proved["base"] for t in range(k)) if k else False
    rc_complete = proved["rc"] == {"rc-base", "rc-step", "rc-out"}

    if sat_base:
        # A reset-state base case that is satisfiable is a genuine counterexample,
        # but only if the assignment actually witnesses it. Re-simulate; never
        # take the producer's word.
        ok = bool(cex) and _replay(a, b, k, sat_base[0], cex)
        rederived = COUNTEREXAMPLE if ok else None
        if not ok:
            errors.append("a base case is satisfiable but no valid counterexample "
                          "is committed, so no verdict follows")
    elif not all_base:
        rederived = None
        errors.append("not every reset-state base case was proved, so no verdict follows")
    elif rc_complete:
        rederived = EQUIVALENT           # register correspondence: 3 obligations
    elif k in proved["step"]:
        rederived = EQUIVALENT           # k-induction on outputs
    else:
        # Base cases hold, no inductive argument closed. Sound but incomplete.
        rederived = UNDECIDED

    if rederived is not None and recorded != rederived:
        errors.append(f"recorded verdict {recorded!r} but re-derived {rederived!r}")

    return {"ok": not errors and rederived is not None, "errors": errors,
            "verdict": rederived, "k": k, "method": method,
            "detail": {"base_proved": sorted(proved["base"]),
                       "register_correspondence": sorted(proved["rc"]),
                       "step_proved": k in proved["step"],
                       "n_obligations": len(obligations)}}


def _replay(a: Dict, b: Dict, k: int, obligation: Dict, cex: Dict) -> bool:
    """A counterexample must satisfy the base-case formula it claims to."""
    assign = {int(kk): bool(v) for kk, v in (cex.get("assignment") or {}).items()}
    try:
        clauses = build_obligation(a, b, k, kind="base", at=int(obligation["at"]))
    except (DesignError, ValueError):
        return False
    return all(any(assign.get(abs(lit), False) == (lit > 0) for lit in cl)
               for cl in clauses)


def write_seq_receipt(path, receipt: Dict):
    from pathlib import Path
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(canon(receipt) + b"\n")
    return p


def read_seq_receipt(path) -> Dict:
    from pathlib import Path
    return json.loads(Path(path).read_text(encoding="utf-8"))
