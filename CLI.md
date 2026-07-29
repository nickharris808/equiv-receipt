# CLI reference — `equiv-receipt`

**The command listings below are generated.** Run `python gen_cli_docs.py` after changing any
argument; a test fails if they are stale.

## Top level

```
usage: equiv-receipt [-h] {verify,verify-seq,solvers,check-drat,demo} ...

Verify logic-equivalence receipts and DRAT refutations.

positional arguments:
  {verify,verify-seq,solvers,check-drat,demo}
    verify              verify an EQUIV-1 receipt end to end
    verify-seq          verify a sequential (k-induction) receipt
    solvers             report which external SAT solvers are usable
    check-drat          check a DRAT refutation against a CNF
    demo                prove a De Morgan equivalence and verify the receipt

options:
  -h, --help            show this help message and exit
```

## `equiv-receipt verify`

```
usage: equiv-receipt verify [-h] [--json]
                            [--format {text,json,jsonl,junit,sarif}]
                            [-o OUTPUT]
                            receipt

positional arguments:
  receipt

options:
  -h, --help            show this help message and exit
  --json                same as --format json
  --format {text,json,jsonl,junit,sarif}
                        output format
  -o OUTPUT, --output OUTPUT
                        write here instead of stdout
```

## `equiv-receipt verify-seq`

```
usage: equiv-receipt verify-seq [-h] [--format {text,json,jsonl,junit,sarif}]
                                [-o OUTPUT]
                                receipt

positional arguments:
  receipt

options:
  -h, --help            show this help message and exit
  --format {text,json,jsonl,junit,sarif}
  -o OUTPUT, --output OUTPUT
```

## `equiv-receipt solvers`

```
usage: equiv-receipt solvers [-h]

options:
  -h, --help  show this help message and exit
```

## `equiv-receipt check-drat`

```
usage: equiv-receipt check-drat [-h] cnf drat

positional arguments:
  cnf
  drat

options:
  -h, --help  show this help message and exit
```

## `equiv-receipt demo`

```
usage: equiv-receipt demo [-h] [--solver SOLVER]

options:
  -h, --help       show this help message and exit
  --solver SOLVER  external solver: a known name, or an argv template
                   containing {cnf} and {drat}
```

## Exit codes

Every command in this toolkit uses the same taxonomy, so a caller can branch on it:

| Code | Meaning |
|---|---|
| `0` | verified / sealed / equivalent — the check was made and it stood |
| `1` | refuted by re-derivation |
| `2` | refuted on integrity: fingerprint, manifest, root, commitment |
| `3` | vacuous — nothing was certified |
| `4` | **abstained** — the evidence for an assertion is absent |
| `5` | usage error — not a verdict at all |

`4` is the one worth wiring up. It is not a failure of the artifact; it means nothing was
established, and treating it as a pass is the failure this toolkit exists to prevent.

---

*Part of [certified-oss](https://github.com/nickharris808/certified-oss).*
