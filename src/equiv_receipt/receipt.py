"""EQUIV-1 receipts — a portable, independently re-derivable equivalence verdict.

The receipt binds, into a salted hash chain: the two circuit descriptions, the
identity of the encoder that produced the formula, the formula itself, and the
refutation. A verifier re-runs the RUP check over the committed formula and
proof and recomputes the chain. It needs nothing from the producer.

The design choice that matters: the receipt commits to the **encoder identity and
the formula bytes**, so a verifier can detect a formula that does not correspond
to the circuits it claims to. A receipt carrying only a proof would let a
producer supply a valid refutation of the wrong formula.

Standard library only.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from .dimacs import CNFParseError, parse_dimacs  # noqa: F401
from .rup import forward_rup_check

FORMAT = "equiv-receipt/1"
DOMAIN_LEAF = b"EQUIV-leaf-v1"
DOMAIN_NODE = b"EQUIV-node-v1"
DOMAIN_SALT = b"EQUIV-salt-v1"
DOMAIN_CHAIN = b"EQUIV-chain-v1"
GENESIS = "0" * 64


class ReceiptError(Exception):
    """Raised when a receipt fails verification."""


def canon(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _h(*parts: bytes) -> bytes:
    d = hashlib.sha256()
    for p in parts:
        d.update(p)
    return d.digest()


def derive_salts(master: bytes, n: int) -> List[bytes]:
    return [hmac.new(master, DOMAIN_SALT + i.to_bytes(4, "big"), hashlib.sha256).digest()
            for i in range(n)]


def leaf_hash(i: int, salt: bytes, blob: bytes) -> bytes:
    return _h(DOMAIN_LEAF, i.to_bytes(4, "big"), salt, hashlib.sha256(blob).digest())


def merkle_root(leaves: List[bytes]) -> bytes:
    if not leaves:
        return _h(DOMAIN_NODE, b"empty")
    level = list(leaves)
    while len(level) > 1:
        nxt = []
        for i in range(0, len(level), 2):
            a = level[i]
            b = level[i + 1] if i + 1 < len(level) else level[i]
            nxt.append(_h(DOMAIN_NODE, a, b))
        level = nxt
    return level[0]


def chain(records: List[Dict]) -> List[Dict]:
    """Hash-chain a record list. Each record carries the digest of the previous."""
    out, prev = [], GENESIS
    for rec in records:
        r = dict(rec)
        r["prev"] = prev
        prev = hashlib.sha256(DOMAIN_CHAIN + canon(r)).hexdigest()
        r["this"] = prev
        out.append(r)
    return out


def build_receipt(*, verdict: str, description_a: str, description_b: str,
                  encoder_id: str, cnf_text: str, drat_text: str = "",
                  counterexample: Optional[Dict] = None,
                  seed: int = 1, meta: Optional[Dict] = None) -> Dict:
    """Assemble an EQUIV-1 receipt.

    ``verdict`` is ``"EQUIVALENT"`` or ``"COUNTEREXAMPLE"``. The verdict is
    recorded but **re-derived** by :func:`verify_receipt`; recording it is a
    convenience, never a basis for acceptance.
    """
    if verdict not in ("EQUIVALENT", "COUNTEREXAMPLE"):
        raise ValueError("verdict must be EQUIVALENT or COUNTEREXAMPLE")

    blobs = {
        "description_a": description_a.encode("utf-8"),
        "description_b": description_b.encode("utf-8"),
        "encoder_id": encoder_id.encode("utf-8"),
        "cnf": cnf_text.encode("utf-8"),
        "drat": drat_text.encode("utf-8"),
    }
    master = hmac.new(seed.to_bytes(8, "big"), DOMAIN_SALT + b"master",
                      hashlib.sha256).digest()
    names = sorted(blobs)
    salts = derive_salts(master, len(names))
    leaves = [leaf_hash(i, salts[i], name.encode() + b"\x00" + blobs[name])
              for i, name in enumerate(names)]
    root = merkle_root(leaves).hex()

    records = [
        {"kind": "header", "format": FORMAT, "seed": int(seed)},
        {"kind": "commitment", "merkle_root": root,
         "digests": {k: hashlib.sha256(v).hexdigest() for k, v in sorted(blobs.items())}},
        {"kind": "encoder", "encoder_id": encoder_id},
        {"kind": "verdict", "verdict": verdict,
         "counterexample": counterexample or None},
    ]
    if meta:
        records.insert(3, {"kind": "meta", "meta": meta})

    return {
        "format": FORMAT,
        "seed": int(seed),
        "records": chain(records),
        "payload": {
            "description_a": description_a,
            "description_b": description_b,
            "encoder_id": encoder_id,
            "cnf": cnf_text,
            "drat": drat_text,
        },
    }


def verify_receipt(receipt: Dict) -> Dict:
    """Re-derive the verdict and the commitments. Returns a result dict.

    Checks, in order: format; chain integrity; commitment root over the payload;
    and — the one that matters — the verdict, **re-derived** by running the RUP
    checker over the committed formula and proof, or by re-simulating the
    committed counterexample.
    """
    errors: List[str] = []
    if receipt.get("format") != FORMAT:
        return {"ok": False, "errors": [f"unknown format {receipt.get('format')!r}"]}

    payload = receipt.get("payload") or {}
    records = receipt.get("records") or []

    # 1. chain integrity
    prev = GENESIS
    for i, rec in enumerate(records):
        body = {k: v for k, v in rec.items() if k != "this"}
        if body.get("prev") != prev:
            errors.append(f"record {i}: broken chain link")
        expect = hashlib.sha256(DOMAIN_CHAIN + canon(body)).hexdigest()
        if expect != rec.get("this"):
            errors.append(f"record {i}: record digest does not recompute")
        prev = rec.get("this")

    by_kind = {r.get("kind"): r for r in records}

    # 2. commitment over the payload
    blobs = {k: str(payload.get(k, "")).encode("utf-8")
             for k in ("description_a", "description_b", "encoder_id", "cnf", "drat")}
    commitment = by_kind.get("commitment", {})
    for name, blob in sorted(blobs.items()):
        want = (commitment.get("digests") or {}).get(name)
        got = hashlib.sha256(blob).hexdigest()
        if want != got:
            errors.append(f"payload {name!r} does not match its committed digest")

    master = hmac.new(int(receipt.get("seed", 1)).to_bytes(8, "big"),
                      DOMAIN_SALT + b"master", hashlib.sha256).digest()
    names = sorted(blobs)
    salts = derive_salts(master, len(names))
    leaves = [leaf_hash(i, salts[i], n.encode() + b"\x00" + blobs[n])
              for i, n in enumerate(names)]
    if merkle_root(leaves).hex() != commitment.get("merkle_root"):
        errors.append("merkle root does not recompute over the payload")

    # 3. re-derive the verdict — never read it
    recorded = (by_kind.get("verdict") or {}).get("verdict")
    try:
        clauses = parse_dimacs(payload.get("cnf", ""))
    except ValueError as exc:
        # An unparseable formula cannot be reasoned about. Reject; do not crash.
        return {"ok": False, "verdict": None, "detail": {},
                "errors": errors + [f"committed formula is malformed: {exc}"]}
    rederived, detail = None, {}
    if payload.get("drat", "").strip():
        chk = forward_rup_check(clauses, payload["drat"])
        detail = chk
        rederived = "EQUIVALENT" if chk["verified"] else None
        if not chk["verified"]:
            errors.append(f"refutation does not check: {chk.get('reason')}")
    else:
        cex = (by_kind.get("verdict") or {}).get("counterexample")
        if cex:
            ok = _replay_counterexample(clauses, cex)
            detail = {"counterexample_satisfies_miter": ok}
            rederived = "COUNTEREXAMPLE" if ok else None
            if not ok:
                errors.append("counterexample does not satisfy the committed formula")
        else:
            errors.append("receipt carries neither a refutation nor a counterexample")

    if rederived is not None and recorded != rederived:
        errors.append(f"recorded verdict {recorded!r} but re-derived {rederived!r}")

    return {"ok": not errors, "errors": errors,
            "verdict": rederived, "detail": detail}


def _replay_counterexample(clauses, cex: Dict) -> bool:
    """A counterexample must satisfy every clause of the miter."""
    assign = {int(k): bool(v) for k, v in cex.items()}
    for cl in clauses:
        if not any(assign.get(abs(lit), False) == (lit > 0) for lit in cl):
            return False
    return True


def write_receipt(path, receipt: Dict) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(canon(receipt) + b"\n")
    return p


def read_receipt(path) -> Dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))
