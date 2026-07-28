"""Prove two 2-bit counters sequentially equivalent, and re-derive the result.

Run it:  python examples/sequential.py
This exact file is what the README shows, and a test runs it.
"""
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
